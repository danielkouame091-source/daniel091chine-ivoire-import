"""Modèles Chatbot — Conversations, messages, outils appelés."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer,
    String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Conversation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Session conversationnelle avec l'assistant."""
    __tablename__ = "chatbot_conversations"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    titre: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_contexte: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Statistiques
    nb_messages: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    nb_tokens_total: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    duree_totale_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")

    # Résumé automatique (pour les longues conversations)
    resume: Mapped[str | None] = mapped_column(Text, nullable=True)
    resume_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Statut
    statut: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default="active"
    )  # active | archivee | supprimee

    # Feedback global
    satisfaction: Mapped[int | None] = mapped_column(Integer, nullable=True)

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        Index("idx_conv_tenant_user", "tenant_id", "user_id", "created_at"),
        Index("idx_conv_statut", "tenant_id", "statut"),
    )


class ChatMessage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Message d'une conversation (user, assistant, tool, system)."""
    __tablename__ = "chatbot_messages"

    conversation_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("chatbot_conversations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    role: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # user | assistant | tool | system
    contenu: Mapped[str] = mapped_column(Text, nullable=False)

    # Outils appelés (si assistant a utilisé des tools)
    tool_calls: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    tool_call_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # RAG — sources utilisées
    sources: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    nb_sources: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    # Métriques LLM
    tokens_prompt: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_completion: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latence_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    modele: Mapped[str | None] = mapped_column(String(80), nullable=True)

    # Feedback
    feedback: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1 = 👍, -1 = 👎
    feedback_commentaire: Mapped[str | None] = mapped_column(Text, nullable=True)

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        Index("idx_msg_conv_date", "conversation_id", "created_at"),
        Index("idx_msg_role", "conversation_id", "role"),
    )


class ToolExecution(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Trace d'exécution d'un outil (audit + debug)."""
    __tablename__ = "chatbot_tool_executions"

    conversation_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("chatbot_conversations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    message_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("chatbot_messages.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    tool_name: Mapped[str] = mapped_column(String(80), nullable=False)
    arguments: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    resultat: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    statut: Mapped[str] = mapped_column(
        String(20), nullable=False, default="success", server_default="success"
    )  # success | error | timeout
    erreur: Mapped[str | None] = mapped_column(Text, nullable=True)
    latence_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("idx_tool_exec_conv", "conversation_id", "created_at"),
        Index("idx_tool_exec_name", "tool_name"),
    )
