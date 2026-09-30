"""
Mémoire conversationnelle — fenêtre glissante + résumé automatique.
"""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rag_config import rag_settings
from app.integrations.ollama_client import ollama_client
from app.models.chatbot import ChatMessage, Conversation

logger = logging.getLogger(__name__)


class ConversationMemory:
    """Gestion de la mémoire d'une conversation."""

    def __init__(self, db: AsyncSession, conversation_id: UUID) -> None:
        self.db = db
        self.conversation_id = conversation_id

    async def build_context(self) -> list[dict[str, str]]:
        """
        Construit la liste des messages à envoyer au LLM.
        Fenêtre glissante + résumé si trop long.
        """
        conv = await self.db.scalar(
            select(Conversation).where(Conversation.id == self.conversation_id)
        )
        if conv is None:
            return []

        # Récupérer les N derniers messages
        messages = (
            await self.db.execute(
                select(ChatMessage)
                .where(ChatMessage.conversation_id == self.conversation_id)
                .order_by(desc(ChatMessage.created_at))
                .limit(rag_settings.MEMORY_MAX_TURNS * 2)
            )
        ).scalars().all()

        messages = list(reversed(messages))  # Chronologique

        # Contexte de base
        result: list[dict[str, str]] = []

        # Ajouter le résumé s'il existe (conversations longues)
        if conv.resume:
            result.append({
                "role": "system",
                "content": f"Résumé de la conversation précédente :\n{conv.resume}",
            })

        # Ajouter les messages
        for m in messages:
            if m.role in ("user", "assistant"):
                result.append({"role": m.role, "content": m.contenu})

        return result

    async def maybe_summarize(self) -> None:
        """
        Si la conversation dépasse N messages, génère un résumé
        des anciens messages pour libérer de l'espace contexte.
        """
        conv = await self.db.scalar(
            select(Conversation).where(Conversation.id == self.conversation_id)
        )
        if conv is None or conv.nb_messages < rag_settings.MEMORY_SUMMARIZE_AFTER:
            return

        # Récupérer les messages à résumer (tous sauf les 10 derniers)
        messages = (
            await self.db.execute(
                select(ChatMessage)
                .where(ChatMessage.conversation_id == self.conversation_id)
                .order_by(ChatMessage.created_at)
            )
        ).scalars().all()

        a_resumer = messages[:-rag_settings.MEMORY_MAX_TURNS * 2]
        if not a_resumer:
            return

        # Construire le texte
        texte = "\n".join(f"{m.role}: {m.contenu}" for m in a_resumer)

        # Demander au LLM de résumer
        try:
            response = await ollama_client.chat(
                messages=[{
                    "role": "user",
                    "content": (
                        "Résume cette conversation comptable en 5 phrases clés. "
                        "Garde les montants, dates et noms importants.\n\n" + texte
                    ),
                }],
                model="llama3.2:3b-instruct-q5_K_M",  # Modèle rapide
                temperature=0.2,
            )
            from datetime import datetime, timezone
            conv.resume = response["message"]["content"]
            conv.resume_at = datetime.now(timezone.utc)
            await self.db.flush()
            logger.info(f"[memory] Résumé généré pour conversation {self.conversation_id}")
        except Exception:
            logger.exception("[memory] Échec génération résumé")
