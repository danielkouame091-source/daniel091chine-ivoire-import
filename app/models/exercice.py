"""Modèle Exercice — période comptable (généralement 01/01 → 31/12)."""
from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.tenant import Tenant


class Exercice(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "exercices"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    libelle: Mapped[str] = mapped_column(Text, nullable=False)          # "Exercice 2025"
    date_debut: Mapped[date] = mapped_column(Date, nullable=False)
    date_fin: Mapped[date] = mapped_column(Date, nullable=False)

    cloture: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    cloture_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Soldes reportés à l'ouverture du suivant (JSONB pour souplesse)
    report_solde: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # Relations
    tenant: Mapped["Tenant"] = relationship(back_populates="exercices")

    __table_args__ = (
        UniqueConstraint("tenant_id", "date_debut", "date_fin", name="uq_exercice_periode"),
        CheckConstraint("date_fin > date_debut", name="exercice_dates_coherentes"),
        Index("idx_exercices_tenant_dates", "tenant_id", "date_debut", "date_fin"),
    )

    def __repr__(self) -> str:
        return f"<Exercice {self.libelle} ({self.date_debut}→{self.date_fin})>"

    @property
    def est_ouvert(self) -> bool:
        return not self.cloture
