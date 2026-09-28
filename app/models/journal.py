"""Modèle Journal — journaux comptables SYSCOHADA (VE, AC, BQ, CA, OD, AN, MM)."""
from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import JournalType

if TYPE_CHECKING:
    from app.models.tenant import Tenant


class Journal(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "journaux"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    code: Mapped[str] = mapped_column(String(5), nullable=False)   # VE, AC, BQ, CA, OD, AN, MM
    libelle: Mapped[str] = mapped_column(Text, nullable=False)
    type_journal: Mapped[JournalType] = mapped_column(nullable=False)

    # Compte de trésorerie par défaut (ex: 521000 pour BQ)
    compte_contrepartie: Mapped[str | None] = mapped_column(String(10), nullable=True)

    actif: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    # Relations
    tenant: Mapped["Tenant"] = relationship(back_populates="journaux")

    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_journal_tenant_code"),
    )

    def __repr__(self) -> str:
        return f"<Journal {self.code} — {self.libelle}>"
