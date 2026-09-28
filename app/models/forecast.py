"""Modèle de prévision de trésorerie."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Date, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class CashflowForecast(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Prévision de trésorerie calculée à un instant T pour un horizon donné.
    Snapshot immuable → permet de comparer prévision vs réalité.
    """
    __tablename__ = "cashflow_forecasts"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    date_calcul: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    horizon_jours: Mapped[int] = mapped_column(Integer, nullable=False)      # 30/60/90
    date_debut: Mapped[date] = mapped_column(Date, nullable=False)
    date_fin: Mapped[date] = mapped_column(Date, nullable=False)

    solde_initial_xof: Mapped[int] = mapped_column(Integer, nullable=False)
    solde_final_prevu_xof: Mapped[int] = mapped_column(Integer, nullable=False)
    flux_entrant_prevu_xof: Mapped[int] = mapped_column(Integer, nullable=False)
    flux_sortant_prevu_xof: Mapped[int] = mapped_column(Integer, nullable=False)

    # Qualité de la prévision
    jours_historique: Mapped[int] = mapped_column(Integer, nullable=False)
    fiabilite: Mapped[str] = mapped_column(
        String(20), nullable=False, default="moyenne", server_default="moyenne"
    )  # faible | moyenne | elevee
    methode: Mapped[str] = mapped_column(
        String(30), nullable=False, default="hybride", server_default="hybride"
    )  # moyenne_mobile | regression | saisonnalite | hybride

    # Détail jour par jour
    courbe_quotidienne: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)

    # Alertes générées
    alerte_tresorerie_negative: Mapped[bool] = mapped_column(
        default=False, server_default="false"
    )
    premiere_date_negative: Mapped[date | None] = mapped_column(Date, nullable=True)
    creux_max_xof: Mapped[int | None] = mapped_column(Integer, nullable=True)

    resume_ia: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("idx_forecast_tenant_date", "tenant_id", "date_calcul"),
        Index("idx_forecast_tenant_horizon", "tenant_id", "horizon_jours", "date_calcul"),
    )

    def __repr__(self) -> str:
        return f"<CashflowForecast tenant={self.tenant_id} horizon={self.horizon_jours}j>"
