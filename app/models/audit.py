"""Modèle AuditLog — journal immuable, chaîné par hash (WORM)."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, Index, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AuditLog(Base):
    """Pas de TimestampMixin : on ne modifie JAMAIS une ligne d'audit."""
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    tenant_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    user_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)

    action: Mapped[str] = mapped_column(Text, nullable=False)
    ressource: Mapped[str] = mapped_column(Text, nullable=False)
    ressource_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)

    ip: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)

    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # Chaînage cryptographique
    hash_precedent: Mapped[str | None] = mapped_column(Text, nullable=True)
    hash_courant: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("idx_audit_tenant_date", "tenant_id", "created_at"),
        Index("idx_audit_action", "action"),
    )

    def __repr__(self) -> str:
        return f"<AuditLog {self.action} on {self.ressource}>"
