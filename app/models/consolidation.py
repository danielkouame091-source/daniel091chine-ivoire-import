"""Modèles OHADA — Consolidation & Groupes."""
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
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


# ─────────────────────────────────────────────────────────────────────────────
# GROUPE DE CONSOLIDATION
# ─────────────────────────────────────────────────────────────────────────────
class ConsolidationGroup(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Groupe de consolidation — entité juridique qui publie les comptes consolidés.
    Contient la société mère + la liste des filiales.
    """
    __tablename__ = "consolidation_groups"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    code: Mapped[str] = mapped_column(String(30), nullable=False)
    libelle: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Société mère (parent)
    parent_tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id"),
        nullable=False,
        index=True,
    )

    # Devise de présentation des comptes consolidés
    devise_presentation: Mapped[str] = mapped_column(
        String(3), nullable=False, default="XOF", server_default="XOF"
    )

    # Période de consolidation (année civile par défaut)
    date_cloture: Mapped[str] = mapped_column(
        String(5), nullable=False, default="12-31", server_default="12-31"
    )   # MM-DD

    # Mode de consolidation (OHADA autorise deux méthodes pour l'écart d'acquisition)
    methode_ecart_acquisition: Mapped[str] = mapped_column(
        String(20), nullable=False, default="goodwill", server_default="goodwill"
    )   # goodwill | capitaux_propres

    # Statut
    actif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_consolidation_group_code"),
        Index("idx_cons_group_tenant_actif", "tenant_id", "actif"),
    )

    def __repr__(self) -> str:
        return f"<ConsolidationGroup {self.code} — {self.libelle}>"


# ─────────────────────────────────────────────────────────────────────────────
# SOCIÉTÉ MEMBRE DU GROUPE
# ─────────────────────────────────────────────────────────────────────────────
class GroupCompany(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Société membre d'un groupe de consolidation.
    Chaque société est liée à un tenant (d'où viennent ses écritures).
    """
    __tablename__ = "group_companies"

    group_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("consolidation_groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id"),
        nullable=False,
        index=True,
    )

    code: Mapped[str] = mapped_column(String(30), nullable=False)
    libelle: Mapped[str] = mapped_column(Text, nullable=False)

    # Relation de contrôle
    societe_mere_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("group_companies.id"), nullable=True
    )

    # Pourcentages (crucial pour la consolidation)
    pourcentage_controle: Mapped[float] = mapped_column(
        Numeric(7, 4), nullable=False, default=100.0, server_default="100.0"
    )   # 0-100 : droits de vote détenus (directement + indirectement)
    pourcentage_interet: Mapped[float] = mapped_column(
        Numeric(7, 4), nullable=False, default=100.0, server_default="100.0"
    )   # 0-100 : part du groupe dans les capitaux propres

    # Méthode applicable
    methode: Mapped[str] = mapped_column(
        String(30), nullable=False, default="integration_globale", server_default="integration_globale"
    )

    # Période d'appartenance au groupe
    date_entree: Mapped[date] = mapped_column(Date, nullable=False)
    date_sortie: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Devise de la société (si différente de la devise de présentation)
    devise_comptable: Mapped[str] = mapped_column(
        String(3), nullable=False, default="XOF", server_default="XOF"
    )

    # Statut
    statut: Mapped[str] = mapped_column(
        String(20), nullable=False, default="actif", server_default="actif"
    )

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        UniqueConstraint("group_id", "code", name="uq_group_company_code"),
        UniqueConstraint("group_id", "tenant_id", name="uq_group_company_tenant"),
        Index("idx_group_company_group_statut", "group_id", "statut"),
        CheckConstraint(
            "pourcentage_controle >= 0 AND pourcentage_controle <= 100",
            name="gc_pct_controle_valide",
        ),
        CheckConstraint(
            "pourcentage_interet >= 0 AND pourcentage_interet <= 100",
            name="gc_pct_interet_valide",
        ),
    )

    def __repr__(self) -> str:
        return f"<GroupCompany {self.code} ({self.methode}, {self.pourcentage_controle}%)>"


# ─────────────────────────────────────────────────────────────────────────────
# TRANSACTIONS INTRAGROUPE (intercos)
# ─────────────────────────────────────────────────────────────────────────────
class IntercompanyTransaction(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Transaction entre deux sociétés du groupe — à éliminer.
    Peut être détectée automatiquement ou saisie manuellement.
    """
    __tablename__ = "intercompany_transactions"

    group_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("consolidation_groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id"),
        nullable=False, index=True,
    )

    # Société source et destination
    source_company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("group_companies.id"),
        nullable=False, index=True,
    )
    target_company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("group_companies.id"),
        nullable=False, index=True,
    )

    # Écritures concernées
    source_ecriture_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("ecritures.id"), nullable=True
    )
    target_ecriture_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("ecritures.id"), nullable=True
    )

    # Type et montant
    type_transaction: Mapped[str] = mapped_column(String(40), nullable=False)
    date_transaction: Mapped[date] = mapped_column(Date, nullable=False)
    libelle: Mapped[str] = mapped_column(Text, nullable=False)
    montant_ht: Mapped[int] = mapped_column(BigInteger, nullable=False)
    devise: Mapped[str] = mapped_column(String(3), nullable=False, default="XOF", server_default="XOF")

    # Détection automatique (score de matching)
    detection_auto: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    score_matching: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)

    # Élimination
    eliminee: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    elimination_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("elimination_entries.id"), nullable=True
    )

    created_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    __table_args__ = (
        Index("idx_ico_group_date", "group_id", "date_transaction"),
        Index("idx_ico_group_eliminee", "group_id", "eliminee"),
        CheckConstraint("montant_ht > 0", name="ico_montant_positif"),
        CheckConstraint(
            "source_company_id != target_company_id",
            name="ico_societes_differentes",
        ),
    )

    def __repr__(self) -> str:
        return f"<IntercompanyTransaction {self.type_transaction} {self.montant_ht} ({self.source_company_id}→{self.target_company_id})>"


# ─────────────────────────────────────────────────────────────────────────────
# ÉLIMINATION
# ─────────────────────────────────────────────────────────────────────────────
class EliminationEntry(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Écriture d'élimination intragroupe.
    Génère les lignes de contrepartie pour neutraliser les flux internes.
    """
    __tablename__ = "elimination_entries"

    group_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("consolidation_groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    consolidation_run_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("consolidation_runs.id"), nullable=True
    )

    reference: Mapped[str] = mapped_column(String(50), nullable=False)
    type_elimination: Mapped[str] = mapped_column(String(40), nullable=False)
    date_elimination: Mapped[date] = mapped_column(Date, nullable=False)
    libelle: Mapped[str] = mapped_column(Text, nullable=False)

    # Contreparties
    montant: Mapped[int] = mapped_column(BigInteger, nullable=False)
    section_elimination: Mapped[str] = mapped_column(
        String(30), nullable=False, default="groupe", server_default="groupe"
    )

    # Lignes comptables détaillées
    lignes: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)

    # Statut
    appliquee: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    appliquee_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        UniqueConstraint("group_id", "reference", name="uq_elimination_ref"),
        Index("idx_elim_group_type", "group_id", "type_elimination"),
        CheckConstraint("montant > 0", name="elim_montant_positif"),
    )

    def __repr__(self) -> str:
        return f"<EliminationEntry {self.reference} ({self.type_elimination})>"


# ─────────────────────────────────────────────────────────────────────────────
# RETRAITEMENT D'HOMOGÉNÉISATION
# ─────────────────────────────────────────────────────────────────────────────
class AdjustmentEntry(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Retraitement pour homogénéiser les méthodes comptables du groupe.
    Ex : une filiale applique l'amortissement dégressif alors que la mère
    applique le linéaire → retraitement pour aligner.
    """
    __tablename__ = "adjustment_entries"

    group_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("consolidation_groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("group_companies.id"),
        nullable=False, index=True,
    )

    reference: Mapped[str] = mapped_column(String(50), nullable=False)
    type_retraitement: Mapped[str] = mapped_column(String(40), nullable=False)
    date_retraitement: Mapped[date] = mapped_column(Date, nullable=False)
    libelle: Mapped[str] = mapped_column(Text, nullable=False)

    montant: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sens: Mapped[str] = mapped_column(String(10), nullable=False)   # debit | credit

    lignes: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)

    appliquee: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    created_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("group_id", "reference", name="uq_adjustment_ref"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# EXÉCUTION DE CONSOLIDATION (run)
# ─────────────────────────────────────────────────────────────────────────────
class ConsolidationRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Une exécution de consolidation.
    Snapshot immuable des comptes consolidés à une date donnée.
    """
    __tablename__ = "consolidation_runs"

    group_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("consolidation_groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    reference: Mapped[str] = mapped_column(String(50), nullable=False)
    date_debut: Mapped[date] = mapped_column(Date, nullable=False)
    date_fin: Mapped[date] = mapped_column(Date, nullable=False)

    statut: Mapped[str] = mapped_column(
        String(20), nullable=False, default="brouillon", server_default="brouillon"
    )

    # Périmètre au moment du run
    nb_societes: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    societes_incluses: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )

    # Totaux consolidés
    total_actif_consolide: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    total_passif_consolide: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    chiffre_affaires_consolide: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    resultat_net_part_groupe: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    resultat_net_part_minoritaires: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    interets_minoritaires_cp: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    ecart_acquisition_total: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")

    # Statistiques
    nb_eliminations: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    nb_retraitements: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    # Comptes détaillés (JSONB pour flexibilité)
    bilan_consolide: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    compte_resultat_consolide: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    tafire_consolide: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    notes_annexes: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # Traçabilité
    execute_par: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    execute_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valide_par: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    valide_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duree_execution_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        UniqueConstraint("group_id", "reference", name="uq_consolidation_run_ref"),
        Index("idx_cons_run_group_date", "group_id", "date_fin"),
        Index("idx_cons_run_group_statut", "group_id", "statut"),
    )

    def __repr__(self) -> str:
        return f"<ConsolidationRun {self.reference} ({self.date_debut}→{self.date_fin})>"


# ─────────────────────────────────────────────────────────────────────────────
# TAUX DE CHANGE (pour consolidation multi-devises)
# ─────────────────────────────────────────────────────────────────────────────
class ExchangeRate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Taux de change à une date donnée.
    Utilisé pour convertir les comptes de filiales étrangères en devise
    de présentation du groupe.
    """
    __tablename__ = "exchange_rates"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    devise_source: Mapped[str] = mapped_column(String(3), nullable=False)
    devise_cible: Mapped[str] = mapped_column(String(3), nullable=False)
    date_taux: Mapped[date] = mapped_column(Date, nullable=False)

    # Taux de clôture (bilan) et taux moyen (compte de résultat)
    taux_cloture: Mapped[float] = mapped_column(Numeric(18, 8), nullable=False)
    taux_moyen: Mapped[float | None] = mapped_column(Numeric(18, 8), nullable=True)

    source: Mapped[str] = mapped_column(
        String(20), nullable=False, default="manuel", server_default="manuel"
    )   # manuel | bceao | api

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "devise_source", "devise_cible", "date_taux",
            name="uq_exchange_rate",
        ),
        Index("idx_fx_tenant_devises_date", "tenant_id", "devise_source", "devise_cible", "date_taux"),
    )

    def __repr__(self) -> str:
        return f"<ExchangeRate {self.devise_source}→{self.devise_cible} @ {self.date_taux}={self.taux_cloture}>"


# ─────────────────────────────────────────────────────────────────────────────
# PART D'INTÉRÊT MINORITAIRE (cache)
# ─────────────────────────────────────────────────────────────────────────────
class MinorityInterest(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Calcul de la part d'intérêts minoritaires pour une filiale à une date.
    Cache pour éviter le recalcul à chaque affichage.
    """
    __tablename__ = "minority_interests"

    group_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("consolidation_groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("group_companies.id"),
        nullable=False, index=True,
    )

    date_calcul: Mapped[date] = mapped_column(Date, nullable=False)

    pct_interet_groupe: Mapped[float] = mapped_column(Numeric(7, 4), nullable=False)
    pct_interet_minoritaire: Mapped[float] = mapped_column(Numeric(7, 4), nullable=False)

    capitaux_propres_filiale: Mapped[int] = mapped_column(BigInteger, nullable=False)
    resultat_filiale: Mapped[int] = mapped_column(BigInteger, nullable=False)

    interets_minoritaires_cp: Mapped[int] = mapped_column(BigInteger, nullable=False)
    interets_minoritaires_resultat: Mapped[int] = mapped_column(BigInteger, nullable=False)

    __table_args__ = (
        UniqueConstraint("company_id", "date_calcul", name="uq_minority_interest_date"),
        Index("idx_mi_group_date", "group_id", "date_calcul"),
    )
