"""Modèles SYSCOHADA — Comptabilité analytique & Budget."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index,
    Integer, Numeric, String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


# ─────────────────────────────────────────────────────────────────────────────
# AXE ANALYTIQUE
# ─────────────────────────────────────────────────────────────────────────────
class AnalyticalAxis(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Axe analytique — regroupe un type d'analyse (centre de coût, produit, projet, etc.).
    Un tenant peut avoir plusieurs axes simultanés (ex: 1 axe centres + 1 axe produits).
    """
    __tablename__ = "analytical_axes"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    code: Mapped[str] = mapped_column(String(20), nullable=False)
    libelle: Mapped[str] = mapped_column(Text, nullable=False)
    type_axe: Mapped[str] = mapped_column(String(30), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Hiérarchie (un axe peut avoir des sous-axes)
    parent_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("analytical_axes.id"), nullable=True
    )

    # Obligatoire : toutes les écritures doivent avoir cet axe
    obligatoire: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # Actif : l'axe est utilisé pour de nouvelles écritures
    actif: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    # Configuration
    ordre_affichage: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    couleur: Mapped[str | None] = mapped_column(String(7), nullable=True)   # #RRGGBB

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_analytical_axis_code"),
        Index("idx_ana_axis_tenant_type", "tenant_id", "type_axe"),
        Index("idx_ana_axis_tenant_actif", "tenant_id", "actif"),
    )

    def __repr__(self) -> str:
        return f"<AnalyticalAxis {self.code} ({self.type_axe})>"


# ─────────────────────────────────────────────────────────────────────────────
# SECTION ANALYTIQUE
# ─────────────────────────────────────────────────────────────────────────────
class AnalyticalSection(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Section analytique — une valeur concrète dans un axe.
    Ex : axe "centres_coût" → sections ["ADMIN", "PRODUCTION", "COMMERCIAL"]
    """
    __tablename__ = "analytical_sections"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    axis_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("analytical_axes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    code: Mapped[str] = mapped_column(String(20), nullable=False)
    libelle: Mapped[str] = mapped_column(Text, nullable=False)

    # Hiérarchie (une section peut avoir des sous-sections)
    parent_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("analytical_sections.id"), nullable=True
    )

    # Responsable
    responsable_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    # Rattachement direct à un tiers (pour axes client/fournisseur)
    lien_client_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("customers.id"), nullable=True
    )
    lien_fournisseur_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("suppliers.id"), nullable=True
    )
    lien_article_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("items.id"), nullable=True
    )

    # Métadonnées métier (surface, effectif, etc. — pour les clés de répartition)
    surface_m2: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    effectif: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chiffre_affaires_ref: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    actif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        UniqueConstraint("axis_id", "code", name="uq_analytical_section_code"),
        Index("idx_ana_sec_axis_actif", "axis_id", "actif"),
        Index("idx_ana_sec_tenant", "tenant_id"),
    )

    def __repr__(self) -> str:
        return f"<AnalyticalSection {self.code}>"


# ─────────────────────────────────────────────────────────────────────────────
# IMPUTATION ANALYTIQUE D'UNE LIGNE D'ÉCRITURE
# ─────────────────────────────────────────────────────────────────────────────
class AnalyticalEntry(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Imputation analytique d'une ligne d'écriture.
    Une ligne d'écriture peut avoir plusieurs imputations (multi-axes ou multi-sections).
    La somme des imputations par section = montant total de la ligne.
    """
    __tablename__ = "analytical_entries"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ecriture_ligne_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("ecriture_lignes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ecriture_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("ecritures.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Section analytique
    section_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("analytical_sections.id"),
        nullable=False,
        index=True,
    )
    axis_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("analytical_axes.id"),
        nullable=False,
        index=True,
    )

    # Montant imputé sur cette section
    montant: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Type d'imputation
    type_imputation: Mapped[str] = mapped_column(
        String(20), nullable=False, default="directe", server_default="directe"
    )  # directe | repartie | manuelle

    # Clé de répartition utilisée (si type=repartie)
    cle_repartition_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("allocation_keys.id"), nullable=True
    )
    pourcentage: Mapped[float | None] = mapped_column(Numeric(6, 3), nullable=True)  # 0-100

    # Traçabilité
    created_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    __table_args__ = (
        Index("idx_ana_entry_tenant_section", "tenant_id", "section_id"),
        Index("idx_ana_entry_tenant_ecriture", "tenant_id", "ecriture_id"),
        Index("idx_ana_entry_ligne", "ecriture_ligne_id"),
        CheckConstraint("montant != 0", name="ana_entry_montant_non_nul"),
    )

    def __repr__(self) -> str:
        return f"<AnalyticalEntry section={self.section_id} montant={self.montant}>"


# ─────────────────────────────────────────────────────────────────────────────
# CLÉ DE RÉPARTITION
# ─────────────────────────────────────────────────────────────────────────────
class AllocationKey(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Clé de répartition — permet de ventiler automatiquement une charge
    (ex: loyer) sur plusieurs sections selon une méthode.
    """
    __tablename__ = "allocation_keys"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    code: Mapped[str] = mapped_column(String(20), nullable=False)
    libelle: Mapped[str] = mapped_column(Text, nullable=False)
    methode: Mapped[str] = mapped_column(String(30), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    axis_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("analytical_axes.id"),
        nullable=False,
        index=True,
    )

    actif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_allocation_key_code"),
    )

    def __repr__(self) -> str:
        return f"<AllocationKey {self.code} ({self.methode})>"


class AllocationKeyLine(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Ligne d'une clé de répartition — associe une section à un poids."""
    __tablename__ = "allocation_key_lines"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    key_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("allocation_keys.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    section_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("analytical_sections.id"),
        nullable=False,
        index=True,
    )

    # Pourcentage (0-100) — somme des lignes = 100%
    pourcentage: Mapped[float] = mapped_column(Numeric(6, 3), nullable=False)

    # Valeur métier utilisée pour le calcul dynamique (surface, effectif...)
    valeur_base: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)

    __table_args__ = (
        UniqueConstraint("key_id", "section_id", name="uq_alloc_key_line"),
    )

    def __repr__(self) -> str:
        return f"<AllocationKeyLine section={self.section_id} %={self.pourcentage}>"


# ─────────────────────────────────────────────────────────────────────────────
# BUDGET
# ─────────────────────────────────────────────────────────────────────────────
class Budget(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Budget annuel (ou période personnalisée) rattaché à une section analytique.
    Contient des prévisions par compte comptable et par mois.
    """
    __tablename__ = "budgets"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    section_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("analytical_sections.id"),
        nullable=True,
        index=True,
    )   # NULL = budget global (toutes sections confondues)

    code: Mapped[str] = mapped_column(String(30), nullable=False)
    libelle: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Période
    annee: Mapped[int] = mapped_column(Integer, nullable=False)
    date_debut: Mapped[date] = mapped_column(Date, nullable=False)
    date_fin: Mapped[date] = mapped_column(Date, nullable=False)

    # Version (permet de garder l'historique)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    statut: Mapped[str] = mapped_column(
        String(20), nullable=False, default="brouillon", server_default="brouillon"
    )

    # Totaux (calculés à partir des lignes)
    total_produits: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    total_charges: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    resultat_prevu: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")

    # Validation
    soumis_par: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    soumis_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valide_par: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    valide_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "code", "version", name="uq_budget_code_version"),
        Index("idx_budget_tenant_annee", "tenant_id", "annee"),
        Index("idx_budget_tenant_statut", "tenant_id", "statut"),
    )

    def __repr__(self) -> str:
        return f"<Budget {self.code} v{self.version} — {self.annee}>"


class BudgetLine(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Ligne de budget — une ligne par compte comptable (ou regroupement).
    Contient 12 valeurs mensuelles + totaux.
    """
    __tablename__ = "budget_lines"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    budget_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("budgets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    section_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("analytical_sections.id"),
        nullable=True,
    )

    # Compte comptable cible
    compte: Mapped[str] = mapped_column(String(10), nullable=False)
    libelle: Mapped[str] = mapped_column(Text, nullable=False)

    # Nature (produit ou charge)
    nature: Mapped[str] = mapped_column(String(10), nullable=False)   # produit | charge

    # 12 mois
    m01: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    m02: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    m03: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    m04: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    m05: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    m06: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    m07: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    m08: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    m09: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    m10: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    m11: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    m12: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")

    total: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")

    # Commentaire / hypothèse
    hypothese: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("budget_id", "compte", name="uq_budget_line_compte"),
        Index("idx_budget_line_tenant_compte", "tenant_id", "compte"),
    )

    def get_mois(self, mois: int) -> int:
        """Retourne la valeur budgétée pour un mois (1-12)."""
        return getattr(self, f"m{mois:02d}")


# ─────────────────────────────────────────────────────────────────────────────
# SUIVI BUDGÉTAIRE (cache de calcul)
# ─────────────────────────────────────────────────────────────────────────────
class BudgetConsumption(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Cache de consommation budgétaire — recalculé périodiquement.
    Permet un contrôle budgétaire temps réel sans recalculer à chaque requête.
    """
    __tablename__ = "budget_consumption"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    budget_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("budgets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    budget_line_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("budget_lines.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    section_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("analytical_sections.id"),
        nullable=True,
    )

    annee: Mapped[int] = mapped_column(Integer, nullable=False)
    mois: Mapped[int] = mapped_column(Integer, nullable=False)   # 1-12

    # Montants
    budget_mois: Mapped[int] = mapped_column(BigInteger, nullable=False)
    budget_cumule: Mapped[int] = mapped_column(BigInteger, nullable=False)
    realise_mois: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    realise_cumule: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")

    # Écarts
    ecart_mois: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    ecart_cumule: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    consommation_pct: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False, default=0, server_default="0")

    # Alerte
    niveau_alerte: Mapped[str] = mapped_column(
        String(20), nullable=False, default="ok", server_default="ok"
    )

    # Projection fin d'année (extrapolation linéaire)
    projection_fin_annee: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    recalcule_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("budget_line_id", "annee", "mois", name="uq_budget_consommation"),
        Index("idx_budget_cons_tenant_periode", "tenant_id", "annee", "mois"),
        Index("idx_budget_cons_tenant_alerte", "tenant_id", "niveau_alerte"),
    )

    def __repr__(self) -> str:
        return f"<BudgetConsumption line={self.budget_line_id} {self.annee}-{self.mois:02d} {self.consommation_pct}%>"
