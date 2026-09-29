"""Modèles SYSCOHADA — immobilisations, amortissements, cessions."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Date, DateTime, Float, ForeignKey,
    Index, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


# ─────────────────────────────────────────────────────────────────────────────
# Immobilisation
# ─────────────────────────────────────────────────────────────────────────────
class FixedAsset(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Registre des immobilisations — fiche par bien."""
    __tablename__ = "fixed_assets"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Identification
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    designation: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Classification SYSCOHADA
    famille: Mapped[str] = mapped_column(String(40), nullable=False)
    compte: Mapped[str] = mapped_column(String(10), nullable=False)
    compte_amortissement: Mapped[str] = mapped_column(String(10), nullable=False)

    # Localisation physique
    localisation: Mapped[str | None] = mapped_column(Text, nullable=True)
    numero_serie: Mapped[str | None] = mapped_column(String(50), nullable=True)
    fournisseur: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Acquisition
    date_acquisition: Mapped[date] = mapped_column(Date, nullable=False)
    date_mise_en_service: Mapped[date] = mapped_column(Date, nullable=False)
    valeur_origine: Mapped[int] = mapped_column(BigInteger, nullable=False)     # VO HT
    valeur_residuelle: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )

    # Amortissement
    methode_amortissement: Mapped[str] = mapped_column(
        String(20), nullable=False, default="lineaire", server_default="lineaire"
    )
    duree_amortissement_ans: Mapped[float] = mapped_column(
        Float, nullable=False, default=1.0, server_default="1.0"
    )
    taux_amortissement: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0"
    )  # en % (calculé = 100/durée)
    coefficient_degressif: Mapped[float] = mapped_column(
        Float, nullable=False, default=1.0, server_default="1.0"
    )
    base_amortissable: Mapped[int] = mapped_column(BigInteger, nullable=False)  # VO - VR
    amortissement_cumule: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    vnc: Mapped[int] = mapped_column(BigInteger, nullable=False)                # Valeur nette comptable

    # Statut
    statut: Mapped[str] = mapped_column(
        String(20), nullable=False, default="actif", server_default="actif"
    )
    totalement_amorti: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # Écriture d'acquisition
    ecriture_acquisition_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("ecritures.id"), nullable=True
    )

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_fixed_asset_code"),
        Index("idx_fa_tenant_statut", "tenant_id", "statut"),
        Index("idx_fa_tenant_famille", "tenant_id", "famille"),
        CheckConstraint("valeur_origine > 0", name="fa_valeur_positive"),
        CheckConstraint("duree_amortissement_ans > 0", name="fa_duree_positive"),
    )

    def __repr__(self) -> str:
        return f"<FixedAsset {self.code} — {self.designation} VNC={self.vnc}>"


# ─────────────────────────────────────────────────────────────────────────────
# Plan / ligne d'amortissement
# ─────────────────────────────────────────────────────────────────────────────
class DepreciationEntry(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Ligne annuelle (ou mensuelle) du plan d'amortissement.
    Une ligne = une période (année fiscale).
    """
    __tablename__ = "depreciation_entries"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    asset_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("fixed_assets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    exercice: Mapped[int] = mapped_column(Integer, nullable=False)              # 2025
    periode_debut: Mapped[date] = mapped_column(Date, nullable=False)
    periode_fin: Mapped[date] = mapped_column(Date, nullable=False)

    # Valeurs
    base_amortissement: Mapped[int] = mapped_column(BigInteger, nullable=False)
    taux_applique: Mapped[float] = mapped_column(Float, nullable=False)
    dotation: Mapped[int] = mapped_column(BigInteger, nullable=False)           # annuité de l'exercice
    amortissement_cumule: Mapped[int] = mapped_column(BigInteger, nullable=False)
    vnc_debut: Mapped[int] = mapped_column(BigInteger, nullable=False)
    vnc_fin: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Prorata temporis (1re année ou exercice incomplet)
    jours_periode: Mapped[int] = mapped_column(Integer, nullable=False, default=365)
    prorata: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)

    # Écriture comptable générée
    ecriture_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("ecritures.id"), nullable=True
    )
    comptabilise: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    comptabilise_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        UniqueConstraint("asset_id", "exercice", name="uq_dep_entry_asset_exo"),
        Index("idx_dep_tenant_exercice", "tenant_id", "exercice"),
        Index("idx_dep_tenant_comptabilise", "tenant_id", "comptabilise"),
    )

    def __repr__(self) -> str:
        return f"<DepreciationEntry asset={self.asset_id} exo={self.exercice} dotation={self.dotation}>"


# ─────────────────────────────────────────────────────────────────────────────
# Cession / mise au rebut
# ─────────────────────────────────────────────────────────────────────────────
class AssetDisposal(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Cession, mise au rebut ou échange d'une immobilisation."""
    __tablename__ = "asset_disposals"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    asset_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("fixed_assets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    type_cession: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # cession | rebut | echange
    date_cession: Mapped[date] = mapped_column(Date, nullable=False)
    motif: Mapped[str] = mapped_column(Text, nullable=False)

    # Valeurs au moment de la cession
    valeur_origine: Mapped[int] = mapped_column(BigInteger, nullable=False)
    amortissement_cumule: Mapped[int] = mapped_column(BigInteger, nullable=False)
    vnc: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Prix de cession (0 pour un rebut)
    prix_cession_ht: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    tva_collectee: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    prix_cession_ttc: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )

    # Résultat
    plus_value: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    moins_value: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")

    acquereur: Mapped[str | None] = mapped_column(Text, nullable=True)
    reference_piece: Mapped[str | None] = mapped_column(String(50), nullable=True)

    ecriture_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("ecritures.id"), nullable=True
    )
    created_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        Index("idx_disposal_tenant_date", "tenant_id", "date_cession"),
        Index("idx_disposal_asset", "asset_id"),
    )

    def __repr__(self) -> str:
        return f"<AssetDisposal asset={self.asset_id} {self.type_cession} prix={self.prix_cession_ht}>"


# ─────────────────────────────────────────────────────────────────────────────
# Réévaluation
# ─────────────────────────────────────────────────────────────────────────────
class AssetRevaluation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Réévaluation d'une immobilisation.
    Constatation : écart entre VNC et valeur réévaluée.
    """
    __tablename__ = "asset_revaluations"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    asset_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("fixed_assets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    date_reevaluation: Mapped[date] = mapped_column(Date, nullable=False)
    vnc_avant: Mapped[int] = mapped_column(BigInteger, nullable=False)
    valeur_reevaluee: Mapped[int] = mapped_column(BigInteger, nullable=False)
    ecart: Mapped[int] = mapped_column(BigInteger, nullable=False)

    nouvelle_duree_restante_ans: Mapped[float | None] = mapped_column(Float, nullable=True)

    ecriture_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("ecritures.id"), nullable=True
    )
    created_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    __table_args__ = (
        Index("idx_reval_tenant_date", "tenant_id", "date_reevaluation"),
    )
