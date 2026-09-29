"""
Service Chatbot d'aide — RAG (Retrieval Augmented Generation) sur la base doc.

Pipeline :
1. Normalisation de la question
2. Détection de la page courante (contexte)
3. Recherche full-text dans les articles (top 5)
4. Appel OpenAI avec la question + les extraits d'articles
5. Retour de la réponse + sources citées
6. Suggestion d'escalade si confiance < seuil
"""
from __future__ import annotations

import logging
import re
import time
import unicodedata
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.formation_syscohada import (
    SEUIL_CHATBOT_AUTO_RESOLUTION,
    SEUIL_CHATBOT_CONFIANCE,
)
from app.integrations.openai_client import get_openai_client
from app.models.formation import (
    Article,
    ArticleCategory,
    ChatbotConversation,
    ChatbotMessage,
)
from app.schemas.formation import (
    ChatbotAskIn,
    ChatbotAskOut,
    ChatbotFeedbackIn,
)

logger = logging.getLogger(__name__)


CHATBOT_SYSTEM_PROMPT = """Tu es l'assistant d'aide de MTech SaaS SYSCOHADA, un logiciel de comptabilité pour l'Afrique francophone (Côte d'Ivoire).

TON RÔLE : Répondre aux questions des utilisateurs en te basant EXCLUSIVEMENT sur les articles de documentation fournis dans le contexte.

RÈGLES STRICTES :
1. Utilise UNIQUEMENT les articles fournis. Si l'information n'y est pas, dis "Je n'ai pas cette information dans ma base. Voulez-vous créer un ticket de support ?"
2. Réponds en français, ton professionnel et amical.
3. Sois concis (3-5 phrases maximum), sauf si l'utilisateur demande un tutoriel détaillé.
4. Cite les articles sources en fin de réponse (format : "📖 Articles liés : [titre]").
5. Si la question concerne un bug ou une anomalie technique, suggère de créer un ticket.
6. Utilise le vocabulaire SYSCOHADA (écriture, journal, compte, partie double...).
7. Ne JAMAIS inventer de fonctionnalités qui n'existent pas dans MTech.

FORMAT DE SORTIE (JSON strict) :
{
  "reponse": "ta réponse en français",
  "confiance": 0.95,
  "articles_cites": ["slug1", "slug2"],
  "suggestion_ticket": false,
  "raisonnement": "bref raisonnement interne (1 phrase)"
}
"""


class ChatbotService:
    def __init__(self, db: AsyncSession, tenant_id: UUID | None, user_id: UUID | None) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self.user_id = user_id

    # ═════════════════════════════════════════════════════════════════════
    # QUESTION AU CHATBOT
    # ═════════════════════════════════════════════════════════════════════
    async def poser_question(self, data: ChatbotAskIn) -> ChatbotAskOut:
        """
        Pipeline complet : recherche → LLM → réponse structurée.
        """
        if not settings.nlp_enabled:
            raise HTTPException(503, "Chatbot indisponible (config IA manquante)")

        start = time.monotonic()

        # 1. Récupérer ou créer la conversation
        conv = await self._get_or_create_conversation(data.session_id, data.page_courante)

        # 2. Enregistrer le message utilisateur
        user_msg = ChatbotMessage(
            conversation_id=conv.id,
            role="user",
            contenu=data.question,
        )
        self.db.add(user_msg)
        await self.db.flush()

        # 3. Recherche d'articles pertinents (contexte RAG)
        articles = await self._rechercher_articles(data.question, limit=5)

        # 4. Appel OpenAI
        try:
            client = get_openai_client()
            response_data = await self._appeler_llm(
                client, data.question, articles, data.page_courante
            )
        except Exception as exc:
            logger.exception("[chatbot] Échec OpenAI")
            # Fallback : réponse basée uniquement sur les articles
            response_data = self._reponse_fallback(articles)

        latence_ms = int((time.monotonic() - start) * 1000)

        # 5. Enregistrer la réponse assistant
        assistant_msg = ChatbotMessage(
            conversation_id=conv.id,
            role="assistant",
            contenu=response_data["reponse"],
            articles_sources=[a["slug"] for a in response_data.get("articles_cites", [])],
            score_confiance=response_data.get("confiance"),
            latence_ms=latence_ms,
        )
        self.db.add(assistant_msg)

        conv.nb_messages += 2
        await self.db.flush()

        # 6. Auto-résolution ?
        confiance = response_data.get("confiance", 0.0)
        auto_resolu = confiance >= SEUIL_CHATBOT_AUTO_RESOLUTION and not response_data.get("suggestion_ticket")
        if auto_resolu and not conv.resolu:
            conv.resolu = True
            conv.resolu_at = datetime.now(timezone.utc)

        await self.db.flush()

        # 7. Construire les sources enrichies
        sources = []
        for slug in response_data.get("articles_cites", []):
            article = next((a for a in articles if a["slug"] == slug), None)
            if article:
                sources.append({
                    "slug": article["slug"],
                    "titre": article["titre"],
                    "resume": article.get("resume"),
                    "type": article.get("type_contenu"),
                })

        return ChatbotAskOut(
            conversation_id=conv.id,
            question=data.question,
            reponse=response_data["reponse"],
            articles_sources=sources,
            score_confiance=confiance,
            escalade_suggeree=confiance < SEUIL_CHATBOT_CONFIANCE,
            suggestion_creation_ticket=response_data.get("suggestion_ticket", False) or confiance < SEUIL_CHATBOT_CONFIANCE,
            latence_ms=latence_ms,
        )

    # ═════════════════════════════════════════════════════════════════════
    # RECHERCHE D'ARTICLES
    # ═════════════════════════════════════════════════════════════════════
    async def _rechercher_articles(self, question: str, limit: int = 5) -> list[dict[str, Any]]:
        """
        Recherche full-text PostgreSQL (french config) + fallback LIKE
        si la recherche retourne peu de résultats.
        """
        from sqlalchemy import text

        # Recherche full-text
        sql = """
            SELECT id, slug, titre, resume, contenu, type_contenu,
                   ts_rank(search_vector, plainto_tsquery('french', :q)) AS score
            FROM articles
            WHERE statut = 'publie'
              AND search_vector @@ plainto_tsquery('french', :q)
            ORDER BY score DESC
            LIMIT :limit
        """
        rows = (await self.db.execute(text(sql), {"q": question, "limit": limit})).all()

        articles: list[dict[str, Any]] = []
        for r in rows:
            articles.append({
                "id": str(r.id),
                "slug": r.slug,
                "titre": r.titre,
                "resume": r.resume,
                "contenu": r.contenu[:2000],   # Tronqué pour le contexte
                "type_contenu": r.type_contenu,
                "score": float(r.score or 0),
            })

        # Fallback : recherche par mots-clés si < 2 résultats
        if len(articles) < 2:
            keywords = self._extraire_mots_cles(question)
            if keywords:
                like_conditions = " OR ".join(
                    [f"titre ILIKE '%{kw}%' OR resume ILIKE '%{kw}%'" for kw in keywords[:3]]
                )
                sql_like = f"""
                    SELECT id, slug, titre, resume, contenu, type_contenu, 0.1 AS score
                    FROM articles
                    WHERE statut = 'publie' AND ({like_conditions})
                    ORDER BY nb_vues DESC
                    LIMIT :limit
                """
                rows_like = (await self.db.execute(text(sql_like), {"limit": limit})).all()
                seen_slugs = {a["slug"] for a in articles}
                for r in rows_like:
                    if r.slug in seen_slugs:
                        continue
                    articles.append({
                        "id": str(r.id),
                        "slug": r.slug,
                        "titre": r.titre,
                        "resume": r.resume,
                        "contenu": r.contenu[:2000],
                        "type_contenu": r.type_contenu,
                        "score": float(r.score or 0),
                    })

        return articles

    # ═════════════════════════════════════════════════════════════════════
    # APPEL LLM
    # ═════════════════════════════════════════════════════════════════════
    async def _appeler_llm(
        self,
        client: Any,
        question: str,
        articles: list[dict[str, Any]],
        page_courante: str | None,
    ) -> dict[str, Any]:
        """Appel OpenAI avec le contexte RAG."""
        if not articles:
            return {
                "reponse": (
                    "Je n'ai pas trouvé d'article correspondant à votre question. "
                    "Voulez-vous créer un ticket de support pour qu'un expert vous réponde ?"
                ),
                "confiance": 0.0,
                "articles_cites": [],
                "suggestion_ticket": True,
            }

        # Construire le contexte
        contexte_articles = []
        for i, a in enumerate(articles, 1):
            contexte_articles.append(
                f"--- Article {i} ---\n"
                f"Titre : {a['titre']}\n"
                f"Slug : {a['slug']}\n"
                f"Type : {a['type_contenu']}\n"
                f"Résumé : {a.get('resume') or 'N/A'}\n"
                f"Contenu (extrait) :\n{a['contenu'][:1500]}\n"
            )
        contexte_str = "\n".join(contexte_articles)

        user_prompt = f"""Page actuelle de l'utilisateur : {page_courante or 'inconnue'}

Question de l'utilisateur : {question}

Voici les articles pertinents de notre base documentaire :

{contexte_str}

Réponds à la question en te basant UNIQUEMENT sur ces articles."""

        result = await client.chat_json(
            system_prompt=CHATBOT_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.2,
            max_tokens=800,
        )

        content = result["content"]

        # Validation
        if "reponse" not in content:
            content["reponse"] = "Je n'ai pas pu générer de réponse. Voulez-vous créer un ticket ?"
            content["confiance"] = 0.0
            content["suggestion_ticket"] = True

        # Normaliser les slugs cités
        if "articles_cites" not in content:
            content["articles_cites"] = [articles[0]["slug"]] if articles else []

        # Filtrer les slugs valides
        valid_slugs = {a["slug"] for a in articles}
        content["articles_cites"] = [
            s for s in content["articles_cites"] if s in valid_slugs
        ]

        return content

    def _reponse_fallback(self, articles: list[dict[str, Any]]) -> dict[str, Any]:
        """Réponse de secours si l'IA est indisponible."""
        if not articles:
            return {
                "reponse": "Le service d'aide est momentanément indisponible. Veuillez réessayer ou créer un ticket.",
                "confiance": 0.0,
                "articles_cites": [],
                "suggestion_ticket": True,
            }
        a = articles[0]
        return {
            "reponse": f"Voici un article qui pourrait vous aider : **{a['titre']}**\n\n{a.get('resume') or ''}",
            "confiance": 0.5,
            "articles_cites": [a["slug"]],
            "suggestion_ticket": False,
        }

    # ═════════════════════════════════════════════════════════════════════
    # CONVERSATION
    # ═════════════════════════════════════════════════════════════════════
    async def _get_or_create_conversation(
        self, session_id: str, page_courante: str | None
    ) -> ChatbotConversation:
        conv = await self.db.scalar(
            select(ChatbotConversation).where(
                ChatbotConversation.session_id == session_id
            )
        )
        if conv:
            if page_courante:
                conv.page_courante = page_courante
            return conv

        conv = ChatbotConversation(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            session_id=session_id,
            page_courante=page_courante,
            nb_messages=0,
        )
        self.db.add(conv)
        await self.db.flush()
        return conv

    async def get_historique(self, session_id: str, limit: int = 50) -> list[ChatbotMessage]:
        conv = await self.db.scalar(
            select(ChatbotConversation).where(
                ChatbotConversation.session_id == session_id
            )
        )
        if conv is None:
            return []
        stmt = (
            select(ChatbotMessage)
            .where(ChatbotMessage.conversation_id == conv.id)
            .order_by(ChatbotMessage.created_at)
            .limit(limit)
        )
        return list((await self.db.execute(stmt)).scalars().all())

    async def feedback_message(self, data: ChatbotFeedbackIn) -> ChatbotMessage:
        msg = await self.db.scalar(
            select(ChatbotMessage).where(ChatbotMessage.id == data.message_id)
        )
        if msg is None:
            raise HTTPException(404, "Message introuvable")
        msg.feedback = data.feedback

        # Si négatif, marquer la conversation comme non résolue
        if data.feedback == -1:
            conv = await self.db.scalar(
                select(ChatbotConversation).where(ChatbotConversation.id == msg.conversation_id)
            )
            if conv:
                conv.resolu = False

        await self.db.flush()
        return msg

    async def marquer_satisfaction(
        self, session_id: str, satisfaction: int, commentaire: str | None = None
    ) -> ChatbotConversation:
        conv = await self.db.scalar(
            select(ChatbotConversation).where(
                ChatbotConversation.session_id == session_id
            )
        )
        if conv is None:
            raise HTTPException(404, "Conversation introuvable")
        conv.satisfaction = satisfaction
        conv.satisfaction_commentaire = commentaire
        await self.db.flush()
        return conv

    async def escalader_vers_ticket(
        self, session_id: str, ticket_id: UUID
    ) -> ChatbotConversation:
        conv = await self.db.scalar(
            select(ChatbotConversation).where(
                ChatbotConversation.session_id == session_id
            )
        )
        if conv is None:
            raise HTTPException(404, "Conversation introuvable")
        conv.escalade_ticket_id = ticket_id
        conv.escalade_at = datetime.now(timezone.utc)
        await self.db.flush()
        return conv

    # ═════════════════════════════════════════════════════════════════════
    # HELPERS
    # ═════════════════════════════════════════════════════════════════════
    @staticmethod
    def _extraire_mots_cles(question: str) -> list[str]:
        """Extrait 3-5 mots-clés significatifs de la question."""
        STOPWORDS = {
            "le", "la", "les", "un", "une", "des", "du", "de", "à", "au", "aux",
            "et", "ou", "mais", "donc", "or", "ni", "car", "que", "qui", "quoi",
            "je", "tu", "il", "elle", "nous", "vous", "ils", "elles",
            "comment", "pourquoi", "quand", "où", "quel", "quelle",
            "est", "sont", "être", "avoir", "faire", "peux", "peut",
            "mon", "ma", "mes", "ton", "ta", "tes", "son", "sa", "ses",
            "ce", "cette", "ces", "cet", "pour", "avec", "sans", "sur", "dans",
        }
        s = question.lower()
        s = unicodedata.normalize("NFD", s)
        s = "".join(c for c in s if unicodedata.category(c) != "Mn")
        s = re.sub(r"[^a-z0-9\s]", " ", s)
        words = [w for w in s.split() if w not in STOPWORDS and len(w) > 3]
        # Top 5 par longueur (proxy de pertinence)
        words.sort(key=len, reverse=True)
        return words[:5]
