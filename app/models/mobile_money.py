"""Modèle MmTransaction — flux Wave / Orange Money / MTN MoMo / Moov Money."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import MMProvider, MMSens, MMStatut


class MmTransaction(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "mm_transactions"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    provider: Mapped[MMProvider] = mapped_column(nullable=False)
    external_id: Mapped[str] = mapped_column(Text, nullable=False)   # ID côté provider

    montant_xof: Mapped[int] = mapped_column(BigInteger, nullable=False)
    frais_xof: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    sens: Mapped[MMSens] = mapped_column(nullable=False)

    numero_tiers: Mapped[str | None] = mapped_column(Text, nullable=True)
    libelle: Mapped[str | None] = mapped_column(Text, nullable=True)
    horodatage: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Payload brut (immuable, pour audit/replay)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    statut_rappro: Mapped[MMStatut] = mapped_column(
        nullable=False, default=MMStatut.NON_RAPPROCHE, server_default="non_rapproche"
    )
    ecriture_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("ecritures.id"), nullable=True
    )
    rapproche_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "provider", "external_id",
            name="uq_mm_tenant_provider_extid",
        ),
        Index("idx_mm_tenant_date", "tenant_id", "horodatage"),
        Index("idx_mm_tenant_statut", "tenant_id", "statut_rappro"),
    )

    def __repr__(self) -> str:
        return f"<MmTransaction {self.provider}:{self.external_id} {self.montant_xof} XOF>"
