"""Modèles WhatsApp : liaisons de comptes + messages."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Index, String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class WhatsAppLink(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Liaison entre un numéro WhatsApp et un utilisateur/tenant."""
    __tablename__ = "whatsapp_links"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    phone_number: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    verification_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    verification_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    derniere_activite_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    actif: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "phone_number", name="uq_wa_tenant_phone"),
        Index("idx_wa_phone", "phone_number"),
    )

    def __repr__(self) -> str:
        return f"<WhatsAppLink {self.phone_number} tenant={self.tenant_id}>"


class WhatsAppMessage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Historique des messages WhatsApp (entrants + sortants)."""
    __tablename__ = "whatsapp_messages"

    tenant_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    link_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("whatsapp_links.id"),
        nullable=True,
    )

    direction: Mapped[str] = mapped_column(String(10), nullable=False)  # in | out
    phone_from: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    phone_to: Mapped[str] = mapped_column(String(20), nullable=False)

    type_message: Mapped[str] = mapped_column(
        String(20), nullable=False, default="text", server_default="text"
    )  # text | audio | image | document

    contenu: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcription: Mapped[str | None] = mapped_column(Text, nullable=True)

    external_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    statut_envoi: Mapped[str | None] = mapped_column(String(20), nullable=True)
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    suggestion_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("nlp_suggestions.id"), nullable=True
    )

    __table_args__ = (
        Index("idx_wa_msg_tenant_date", "tenant_id", "created_at"),
        Index("idx_wa_msg_external", "external_id"),
    )

    def __repr__(self) -> str:
        return f"<WhatsAppMessage {self.direction} {self.phone_from}>"
