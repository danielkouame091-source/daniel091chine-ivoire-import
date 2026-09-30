"""
Service Chatbot principal — orchestration RAG + LLM + tools + mémoire.

Pipeline :
1. Charge la conversation (ou en crée une nouvelle)
2. Récupère la mémoire (fenêtre + résumé)
3. RAG retrieval (recherche hybride)
4. Construit le prompt système
5. Appel LLM avec tools
6. Boucle tool calling (max 5 itérations)
7. Persiste la réponse
8. Feedback / résumé auto
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, AsyncIterator
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.llm_config import llm_settings
from app.integrations.ollama_client import ollama_client
from app.models.chatbot import ChatMessage, Conversation, ToolExecution
from app.schemas.chatbot import ChatResponse, SourceOut, ToolCallOut
from app.services.audit_service import AuditService
from app.services.conversation_memory import ConversationMemory
from app.services.rag_service import RAGService
from app.services.tool_registry import tool_registry
from app.services.tools import (  # noqa: F401  — enregistre les outils
    ecriture_tools, invoice_tools, kpi_tools, rh_tools, search_tools,
)

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """Tu es l'assistant IA de MTech, un logiciel de comptabilité SYSCOHADA pour l'Afrique francophone (Côte d'Ivoire).

TON RÔLE :
- Aider les dirigeants, DAF et comptables à utiliser MTech
- Répondre aux questions comptables (SYSCOHADA révisé)
- Exécuter des actions simples via les outils mis à ta disposition

RÈGLES STRICTES :
1. Réponds en français, ton professionnel et concis.
2. Utilise EXCLUSIVEMENT les informations du contexte fourni quand il s'agit de la doc MTech.
3. Pour les questions comptables générales, tu peux t'appuyer sur ta connaissance du SYSCOHADA.
4. Utilise les OUTILS quand l'utilisateur demande une action concrète (créer écriture, consulter KPI, etc.).
5. Ne JAMAIS inventer de données financières. Si tu ne sais pas, dis-le.
6. Ne JAMAIS exécuter d'action sensible sans confirmation explicite de l'utilisateur.
7. Cite tes sources quand tu utilises la documentation.

FORMAT DE RÉPONSE :
- Court (3-6 phrases) sauf si l'utilisateur demande un développement
- Utilise des **gras** pour les chiffres clés
- Structure avec des listes si utile
"""


class ChatbotService:
    def __init__(self, db: AsyncSession, tenant_id: UUID, user_id: UUID, role: str = "LECTEUR") -> None:
        self.db = db
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.role = role
        self.audit = AuditService(db)

    # ═════════════════════════════════════════════════════════════════════
    # MÉTHODE PRINCIPALE — NON-STREAMING
    # ═════════════════════════════════════════════════════════════════════
    async def chat(
        self,
        message: str,
        conversation_id: UUID | None = None,
        page_contexte: str | None = None,
        use_tools: bool = True,
        use_rag: bool = True,
        langue: str = "fr",
    ) -> ChatResponse:
        start = time.monotonic()

        # 1. Conversation (existante ou nouvelle)
        conv = await self._get_or_create_conversation(conversation_id, page_contexte)

        # 2. Sauvegarder le message utilisateur
        user_msg = ChatMessage(
            conversation_id=conv.id,
            tenant_id=self.tenant_id,
            role="user",
            contenu=message,
        )
        self.db.add(user_msg)
        await self.db.flush()

        # 3. Récupérer la mémoire
        memory = ConversationMemory(self.db, conv.id)
        history = await memory.build_context()

        # 4. RAG retrieval
        sources: list[dict[str, Any]] = []
        context_text = ""
        if use_rag:
            try:
                rag = RAGService(self.db, self.tenant_id)
                sources = await rag.retrieve(message)
                context_text = rag.build_context(sources)
            except Exception:
                logger.exception("[chatbot] Erreur RAG")

        # 5. Construire le prompt
        messages = self._build_messages(history, context_text, message, page_contexte)

        # 6. Obtenir les schémas d'outils
        tool_schemas = tool_registry.list_schemas(role=self.role) if use_tools else []

        # 7. Appel LLM avec boucle tool calling
        tool_calls_log: list[ToolCallOut] = []
        max_iterations = 5
        final_response_text = ""
        tokens_prompt_total = 0
        tokens_completion_total = 0

        for iteration in range(max_iterations):
            try:
                response = await ollama_client.chat(
                    messages=messages,
                    tools=tool_schemas if tool_schemas else None,
                )
            except Exception as exc:
                logger.exception("[chatbot] Erreur LLM")
                raise HTTPException(502, f"Erreur LLM : {exc}")

            msg = response.get("message", {})
            tokens_prompt_total += response.get("prompt_eval_count", 0)
            tokens_completion_total += response.get("eval_count", 0)

            # Si le LLM appelle un/des outils
            if msg.get("tool_calls"):
                messages.append(msg)  # Ajouter le message assistant avec tool_calls

                for tool_call in msg["tool_calls"]:
                    tool_name = tool_call["function"]["name"]
                    tool_args = tool_call["function"]["arguments"]
                    if isinstance(tool_args, str):
                        try:
                            tool_args = json.loads(tool_args)
                        except json.JSONDecodeError:
                            tool_args = {}

                    tool_start = time.monotonic()
                    try:
                        result = await tool_registry.execute(
                            name=tool_name,
                            arguments=tool_args,
                            db=self.db,
                            tenant_id=self.tenant_id,
                            user_id=self.user_id,
                            role=self.role,
                        )
                        statut = "success" if "error" not in result else "error"
                    except Exception as exc:
                        result = {"error": str(exc)}
                        statut = "error"

                    latence_ms = int((time.monotonic() - tool_start) * 1000)

                    # Log de l'exécution
                    self.db.add(ToolExecution(
                        conversation_id=conv.id,
                        tenant_id=self.tenant_id,
                        tool_name=tool_name,
                        arguments=tool_args,
                        resultat=result,
                        statut=statut,
                        latence_ms=latence_ms,
                        created_at=datetime.now(timezone.utc),
                    ))

                    tool_calls_log.append(ToolCallOut(
                        tool_name=tool_name,
                        arguments=tool_args,
                        resultat=result,
                        statut=statut,
                        latence_ms=latence_ms,
                    ))

                    # Ajouter le résultat dans le contexte
                    messages.append({
                        "role": "tool",
                        "content": json.dumps(result, ensure_ascii=False, default=str),
                    })

                continue  # Relancer le LLM avec les résultats

            # Réponse finale
            final_response_text = msg.get("content", "")
            break

        # 8. Sauvegarder la réponse assistant
        assistant_msg = ChatMessage(
            conversation_id=conv.id,
            tenant_id=self.tenant_id,
            role="assistant",
            contenu=final_response_text,
            tool_calls=[tc.model_dump() for tc in tool_calls_log] if tool_calls_log else None,
            sources=[{"titre": s["titre"], "score": s["score_rrf"]} for s in sources] if sources else None,
            nb_sources=len(sources),
            tokens_prompt=tokens_prompt_total,
            tokens_completion=tokens_completion_total,
            latence_ms=int((time.monotonic() - start) * 1000),
            modele=llm_settings.OLLAMA_MODEL,
        )
        self.db.add(assistant_msg)

        # 9. Mettre à jour la conversation
        conv.nb_messages += 2
        conv.nb_tokens_total += tokens_prompt_total + tokens_completion_total
        if conv.titre is None:
            conv.titre = message[:100]
        await self.db.flush()

        # 10. Résumé auto (async, non bloquant)
        try:
            await memory.maybe_summarize()
        except Exception:
            logger.exception("[chatbot] Erreur résumé auto")

        # 11. Retour
        return ChatResponse(
            conversation_id=conv.id,
            message_id=assistant_msg.id,
            reponse=final_response_text,
            sources=[
                SourceOut(
                    document_id=s["document_id"],
                    chunk_id=s["chunk_id"],
                    titre=s["titre"],
                    extrait=s["contenu"][:300],
                    score=s["score_rrf"],
                    source_url=s.get("source_url"),
                )
                for s in sources
            ],
            tools_executed=tool_calls_log,
            tokens_prompt=tokens_prompt_total,
            tokens_completion=tokens_completion_total,
            latence_ms=int((time.monotonic() - start) * 1000),
            modele=llm_settings.OLLAMA_MODEL,
        )

    # ═════════════════════════════════════════════════════════════════════
    # MÉTHODE STREAMING (SSE)
    # ═════════════════════════════════════════════════════════════════════
    async def chat_stream(
        self,
        message: str,
        conversation_id: UUID | None = None,
        page_contexte: str | None = None,
        use_tools: bool = True,
        use_rag: bool = True,
        langue: str = "fr",
    ) -> AsyncIterator[dict[str, Any]]:
        """
        Streaming SSE — yield des chunks :
        {type: 'meta', conversation_id, message_id}
        {type: 'sources', sources: [...]}
        {type: 'token', content: '...'}
        {type: 'tool', tool: {...}}
        {type: 'done', message_id: ...}
        """
        start = time.monotonic()
        conv = await self._get_or_create_conversation(conversation_id, page_contexte)

        # Message utilisateur
        user_msg = ChatMessage(
            conversation_id=conv.id, tenant_id=self.tenant_id,
            role="user", contenu=message,
        )
        self.db.add(user_msg)
        await self.db.flush()

        # RAG
        sources: list[dict[str, Any]] = []
        context_text = ""
        if use_rag:
            try:
                rag = RAGService(self.db, self.tenant_id)
                sources = await rag.retrieve(message)
                context_text = rag.build_context(sources)
            except Exception:
                logger.exception("[chatbot_stream] Erreur RAG")

        # Message assistant placeholder
        assistant_msg_id = uuid4()
        yield {
            "type": "meta",
            "conversation_id": str(conv.id),
            "message_id": str(assistant_msg_id),
        }
        if sources:
            yield {
                "type": "sources",
                "sources": [
                    {"titre": s["titre"], "score": s["score_rrf"], "url": s.get("source_url")}
                    for s in sources
                ],
            }

        # Mémoire
        memory = ConversationMemory(self.db, conv.id)
        history = await memory.build_context()
        messages = self._build_messages(history, context_text, message, page_contexte)
        tool_schemas = tool_registry.list_schemas(role=self.role) if use_tools else []

        # Streaming du LLM
        full_response = ""
        tool_calls_log: list[ToolCallOut] = []

        async for chunk in ollama_client.chat_stream(
            messages=messages,
            tools=tool_schemas if tool_schemas else None,
        ):
            msg = chunk.get("message", {})
            content = msg.get("content", "")

            if content:
                full_response += content
                yield {"type": "token", "content": content}

            # Gestion des tool_calls en streaming
            if msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    tool_name = tc["function"]["name"]
                    tool_args = tc["function"]["arguments"]
                    if isinstance(tool_args, str):
                        try:
                            tool_args = json.loads(tool_args)
                        except Exception:
                            tool_args = {}

                    tool_start = time.monotonic()
                    result = await tool_registry.execute(
                        name=tool_name, arguments=tool_args,
                        db=self.db, tenant_id=self.tenant_id,
                        user_id=self.user_id, role=self.role,
                    )
                    latence = int((time.monotonic() - tool_start) * 1000)

                    tool_calls_log.append(ToolCallOut(
                        tool_name=tool_name, arguments=tool_args,
                        resultat=result,
                        statut="success" if "error" not in result else "error",
                        latence_ms=latence,
                    ))

                    yield {
                        "type": "tool",
                        "tool": {
                            "name": tool_name,
                            "arguments": tool_args,
                            "resultat": result,
                        },
                    }

        # Persister la réponse finale
        assistant_msg = ChatMessage(
            id=assistant_msg_id,
            conversation_id=conv.id, tenant_id=self.tenant_id,
            role="assistant", contenu=full_response,
            tool_calls=[tc.model_dump() for tc in tool_calls_log] if tool_calls_log else None,
            sources=[{"titre": s["titre"]} for s in sources] if sources else None,
            nb_sources=len(sources),
            latence_ms=int((time.monotonic() - start) * 1000),
            modele=llm_settings.OLLAMA_MODEL,
        )
        self.db.add(assistant_msg)
        conv.nb_messages += 2
        if conv.titre is None:
            conv.titre = message[:100]
        await self.db.flush()

        yield {"type": "done", "message_id": str(assistant_msg_id)}

    # ═════════════════════════════════════════════════════════════════════
    # CONVERSATIONS
    # ═════════════════════════════════════════════════════════════════════
    async def lister_conversations(self, limit: int = 50) -> list[Conversation]:
        stmt = (
            select(Conversation)
            .where(
                Conversation.tenant_id == self.tenant_id,
                Conversation.user_id == self.user_id,
                Conversation.statut != "supprimee",
            )
            .order_by(desc(Conversation.updated_at))
            .limit(limit)
        )
        return list((await self.db.execute(stmt)).scalars().all())

    async def get_conversation_detail(self, conv_id: UUID) -> dict[str, Any]:
        conv = await self.db.scalar(
            select(Conversation).where(
                Conversation.id == conv_id,
                Conversation.tenant_id == self.tenant_id,
                Conversation.user_id == self.user_id,
            )
        )
        if conv is None:
            raise HTTPException(404, "Conversation introuvable")

        messages = (
            await self.db.execute(
                select(ChatMessage)
                .where(ChatMessage.conversation_id == conv.id)
                .order_by(ChatMessage.created_at)
            )
        ).scalars().all()

        return {
            "id": conv.id,
            "titre": conv.titre,
            "nb_messages": conv.nb_messages,
            "statut": conv.statut,
            "created_at": conv.created_at,
            "updated_at": conv.updated_at,
            "messages": messages,
        }

    async def supprimer_conversation(self, conv_id: UUID) -> None:
        conv = await self.db.scalar(
            select(Conversation).where(
                Conversation.id == conv_id,
                Conversation.tenant_id == self.tenant_id,
                Conversation.user_id == self.user_id,
            )
        )
        if conv is None:
            raise HTTPException(404, "Conversation introuvable")
        conv.statut = "supprimee"
        await self.db.flush()

    # ═════════════════════════════════════════════════════════════════════
    # FEEDBACK
    # ═════════════════════════════════════════════════════════════════════
    async def donner_feedback(
        self, message_id: UUID, feedback: int, commentaire: str | None = None
    ) -> ChatMessage:
        msg = await self.db.scalar(
            select(ChatMessage).where(
                ChatMessage.id == message_id,
                ChatMessage.tenant_id == self.tenant_id,
            )
        )
        if msg is None:
            raise HTTPException(404, "Message introuvable")
        msg.feedback = feedback
        msg.feedback_commentaire = commentaire
        await self.db.flush()
        return msg

    # ═════════════════════════════════════════════════════════════════════
    # HELPERS
    # ═════════════════════════════════════════════════════════════════════
    async def _get_or_create_conversation(
        self, conversation_id: UUID | None, page_contexte: str | None
    ) -> Conversation:
        if conversation_id:
            conv = await self.db.scalar(
                select(Conversation).where(
                    Conversation.id == conversation_id,
                    Conversation.tenant_id == self.tenant_id,
                    Conversation.user_id == self.user_id,
                )
            )
            if conv is None:
                raise HTTPException(404, "Conversation introuvable")
            return conv

        conv = Conversation(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            page_contexte=page_contexte,
            statut="active",
        )
        self.db.add(conv)
        await self.db.flush()
        return conv

    def _build_messages(
        self,
        history: list[dict[str, str]],
        context_text: str,
        message: str,
        page_contexte: str | None,
    ) -> list[dict[str, str]]:
        """Construit la liste finale des messages pour le LLM."""
        system_content = SYSTEM_PROMPT

        if page_contexte:
            system_content += f"\n\nPAGE ACTUELLE : {page_contexte}"

        if context_text:
            system_content += (
                "\n\n=== DOCUMENTATION MTech PERTINENTE ===\n"
                f"{context_text}\n"
                "=== FIN DOCUMENTATION ==="
            )

        messages: list[dict[str, str]] = [{"role": "system", "content": system_content}]
        messages.extend(history)
        messages.append({"role": "user", "content": message})
        return messages
