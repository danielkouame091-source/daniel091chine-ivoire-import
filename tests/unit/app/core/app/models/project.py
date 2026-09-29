"""Modèles SYSCOHADA — Projets, Chantiers, Situations de travaux."""
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
# PROJET / CHANTIER
# ─────────────────────────────────────────────────────────────────────────────
class Project(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Projet ou chantier — entité pivot du module."""
    __tablename__ = "projects"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Identification
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    libelle: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Type & méthode
    type_projet: Mapped[str] = mapped_column(String(30), nullable=False)
    methode_reconnaissance: Mapped[str] = mapped_column(
        String(30), nullable=False, default="a_l_avancement", server_default="a_l_avancement"
    )
    methode_avancement: Mapped[str] = mapped_column(
        String(30), nullable=False, default="couts_engages", server_default="couts_engages"
    )

    # Client associé
    customer_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("customers.id"), nullable=True, index=True
    )
    chef_projet_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    # Dates
    date_debut_prevue: Mapped[date] = mapped_column(Date, nullable=False)
    date_fin_prevue: Mapped[date] = mapped_column(Date, nullable=False)
    date_debut_reelle: Mapped[date | None] = mapped_column(Date, nullable=True)
    date_fin_reelle: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Statut & avancement
    statut: Mapped[str] = mapped_column(
        String(20), nullable=False, default="brouillon", server_default="brouillon"
    )
    pourcentage_avancement_physique: Mapped[float] = mapped_column(
        Numeric(5, 2), nullable=False, default=0, server_default="0"
    )
    pourcentage_avancement_financier: Mapped[float] = mapped_column(
        Numeric(5, 2), nullable=False, default=0, server_default="0"
    )

    # Montants contractuels
    montant_marche_ht: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    taux_tva: Mapped[float] = mapped_column(
        Numeric(5, 4), nullable=False, default=0.18, server_default="0.18"
    )
    montant_marche_ttc: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )

    # Budget prévisionnel
    budget_previsionnel_ht: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    budget_engage: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    budget_realise: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    cout_total_estime_ht: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )

    # Retenue de garantie
    retenue_garantie_taux: Mapped[float] = mapped_column(
        Numeric(5, 4), nullable=False, default=0.05, server_default="0.05"
    )
    retenue_garantie_montant: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    retenue_garantie_liberee: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # Avances
    avance_demarrage_pct: Mapped[float] = mapped_column(
        Numeric(5, 2), nullable=False, default=0, server_default="0"
    )
    avance_demarrage_montant: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    avance_remboursee: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )

    # Compte comptable principal (23x ou 34x selon le type)
    compte_projet: Mapped[str] = mapped_column(String(10), nullable=False)

    # Rattachement analytique
    analytical_section_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("analytical_sections.id"), nullable=True
    )

    # Immobilisation créée à la clôture (si type=investissement)
    immobilisation_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("fixed_assets.id"), nullable=True
    )

    # Reporting
    niveau_alerte: Mapped[str] = mapped_column(
        String(20), nullable=False, default="ok", server_default="ok"
    )
    derniere_alerte_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    created_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_project_code"),
        Index("idx_proj_tenant_statut", "tenant_id", "statut"),
        Index("idx_proj_tenant_customer", "tenant_id", "customer_id"),
        Index("idx_proj_tenant_dates", "tenant_id", "date_debut_prevue", "date_fin_prevue"),
        CheckConstraint("date_fin_prevue >= date_debut_prevue", name="proj_dates_coherentes"),
        CheckConstraint(
            "pourcentage_avancement_physique BETWEEN 0 AND 100",
            name="proj_avct_physique_valide",
        ),
        CheckConstraint(
            "retenue_garantie_taux BETWEEN 0 AND 0.10",
            name="proj_retenue_valide",
        ),
    )

    def __repr__(self) -> str:
        return f"<Project {self.code} — {self.libelle} ({self.statut})>"

    # ─── Propriétés calculées ─────────────────────────────────────────
    @property
    def marge_previsionnelle(self) -> int:
        return self.montant_marche_ht - self.budget_previsionnel_ht

    @property
    def marge_previsionnelle_pct(self) -> float:
        if self.montant_marche_ht == 0:
            return 0.0
        return (self.marge_previsionnelle / self.montant_marche_ht) * 100

    @property
    def taux_consommation_budget(self) -> float:
        if self.budget_previsionnel_ht == 0:
            return 0.0
        return (self.budget_realise / self.budget_previsionnel_ht) * 100

    @property
    def est_en_retard(self) -> bool:
        if self.statut != "en_cours":
            return False
        return date.today() > self.date_fin_prevue


# ─────────────────────────────────────────────────────────────────────────────
# PHASE / LOT DU PROJET
# ─────────────────────────────────────────────────────────────────────────────
class ProjectPhase(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Phase / lot d'un projet (permet un WBS à 2 niveaux)."""
    __tablename__ = "project_phases"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    code: Mapped[str] = mapped_column(String(30), nullable=False)
    libelle: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    type_phase: Mapped[str] = mapped_column(String(30), nullable=False)

    ordre: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    date_debut_prevue: Mapped[date] = mapped_column(Date, nullable=False)
    date_fin_prevue: Mapped[date] = mapped_column(Date, nullable=False)
    date_debut_reelle: Mapped[date | None] = mapped_column(Date, nullable=True)
    date_fin_reelle: Mapped[date | None] = mapped_column(Date, nullable=True)

    budget_ht: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    budget_realise: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")

    pourcentage_avancement: Mapped[float] = mapped_column(
        Numeric(5, 2), nullable=False, default=0, server_default="0"
    )

    poids: Mapped[float] = mapped_column(
        Numeric(5, 2), nullable=False, default=0, server_default="0"
    )   # Poids dans le projet (0-100)

    statut: Mapped[str] = mapped_column(
        String(20), nullable=False, default="non_demarre", server_default="non_demarre"
    )
    responsable_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        UniqueConstraint("project_id", "code", name="uq_project_phase_code"),
        Index("idx_proj_phase_tenant", "tenant_id"),
    )

    def __repr__(self) -> str:
        return f"<ProjectPhase {self.code} — {self.libelle}>"


# ─────────────────────────────────────────────────────────────────────────────
# TÂCHE
# ─────────────────────────────────────────────────────────────────────────────
class ProjectTask(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Tâche au sein d'une phase (WBS à 3 niveaux)."""
    __tablename__ = "project_tasks"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    phase_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("project_phases.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )

    code: Mapped[str] = mapped_column(String(30), nullable=False)
    libelle: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    ordre: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    date_debut_prevue: Mapped[date] = mapped_column(Date, nullable=False)
    date_fin_prevue: Mapped[date] = mapped_column(Date, nullable=False)
    date_debut_reelle: Mapped[date | None] = mapped_column(Date, nullable=True)
    date_fin_reelle: Mapped[date | None] = mapped_column(Date, nullable=True)

    duree_estimee_h: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    duree_reelle_h: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)

    budget_ht: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    budget_realise: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")

    pourcentage_avancement: Mapped[float] = mapped_column(
        Numeric(5, 2), nullable=False, default=0, server_default="0"
    )
    statut: Mapped[str] = mapped_column(
        String(20), nullable=False, default="a_faire", server_default="a_faire"
    )   # a_faire | en_cours | terminee | bloquee | annulee

    priorite: Mapped[str] = mapped_column(
        String(20), nullable=False, default="normale", server_default="normale"
    )   # basse | normale | haute | critique

    assigne_a_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        UniqueConstraint("project_id", "code", name="uq_project_task_code"),
        Index("idx_proj_task_assignee", "tenant_id", "assigne_a_user_id", "statut"),
    )

    def __repr__(self) -> str:
        return f"<ProjectTask {self.code} — {self.libelle}>"


# ─────────────────────────────────────────────────────────────────────────────
# AFFECTATION DE RESSOURCE
# ─────────────────────────────────────────────────────────────────────────────
class ProjectResourceAssignment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Affectation d'une ressource (humaine ou matérielle) à un projet."""
    __tablename__ = "project_resource_assignments"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    task_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("project_tasks.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Type de ressource
    type_ressource: Mapped[str] = mapped_column(
        String(20), nullable=False
    )   # employe | equipement | vehicule | sous_traitant | autre

    # Employé (si type=employe)
    employee_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("employees.id"), nullable=True
    )
    # Utilisateur système (si ressource interne)
    user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    # Équipement (nouvelle entité à terme)
    equipement_ref: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Période
    date_debut: Mapped[date] = mapped_column(Date, nullable=False)
    date_fin: Mapped[date] = mapped_column(Date, nullable=False)

    # Charge allouée
    pourcentage_allocation: Mapped[float] = mapped_column(
        Numeric(5, 2), nullable=False, default=100, server_default="100"
    )
    heures_prevues: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    heures_reelles: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)

    # Coût
    taux_horaire: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    cout_prevu: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    cout_reel: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    actif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    __table_args__ = (
        Index("idx_pra_project_dates", "project_id", "date_debut", "date_fin"),
        Index("idx_pra_employee", "employee_id", "date_debut"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# COÛT RÉEL DU PROJET (imputation)
# ─────────────────────────────────────────────────────────────────────────────
class ProjectCost(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Imputation d'un coût réel au projet (depuis une facture, une paie,
    une note de frais, ou une saisie manuelle).
    """
    __tablename__ = "project_costs"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    phase_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("project_phases.id"), nullable=True
    )

    date_cout: Mapped[date] = mapped_column(Date, nullable=False)
    libelle: Mapped[str] = mapped_column(Text, nullable=False)

    # Nature
    type_cout: Mapped[str] = mapped_column(
        String(30), nullable=False
    )   # achat | sous_traitance | main_oeuvre | location | frais_generaux | autre

    montant_ht: Mapped[int] = mapped_column(BigInteger, nullable=False)
    montant_tva: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")

    # Lien avec la source
    source_type: Mapped[str] = mapped_column(
        String(30), nullable=False, default="manuel", server_default="manuel"
    )   # facture_fournisseur | payslip | note_frais | manuel
    source_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    compte_comptable: Mapped[str] = mapped_column(String(10), nullable=False)

    # Écriture comptable générée
    ecriture_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("ecritures.id"), nullable=True
    )

    # Validation
    valide: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    valide_par: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    created_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    __table_args__ = (
        Index("idx_pc_project_date", "project_id", "date_cout"),
        Index("idx_pc_tenant_type", "tenant_id", "type_cout"),
    )

    def __repr__(self) -> str:
        return f"<ProjectCost {self.libelle[:50]} — {self.montant_ht}>"


# ─────────────────────────────────────────────────────────────────────────────
# SITUATION DE TRAVAUX
# ─────────────────────────────────────────────────────────────────────────────
class ProgressBilling(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Situation de travaux (décompte) — facturation périodique à l'avancement.
    Élément clé du BTP ivoirien.
    """
    __tablename__ = "progress_billings"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    customer_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("customers.id"), nullable=True
    )

    numero: Mapped[str] = mapped_column(String(30), nullable=False)
    numero_situation: Mapped[int] = mapped_column(Integer, nullable=False)  # N° séquentiel
    date_situation: Mapped[date] = mapped_column(Date, nullable=False)
    date_echeance: Mapped[date | None] = mapped_column(Date, nullable=True)

    libelle: Mapped[str] = mapped_column(Text, nullable=False)

    # Avancement à la date de la situation
    pourcentage_avancement_cumule: Mapped[float] = mapped_column(
        Numeric(5, 2), nullable=False
    )

    # Montants (cumulés depuis le début du projet)
    montant_cumule_precedent_ht: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )   # Situations précédentes
    montant_cumule_actuel_ht: Mapped[int] = mapped_column(
        BigInteger, nullable=False
    )   # Cumul jusqu'à cette situation
    montant_situation_ht: Mapped[int] = mapped_column(
        BigInteger, nullable=False
    )   # Montant de cette situation = actuel - précédent

    # TVA
    taux_tva: Mapped[float] = mapped_column(
        Numeric(5, 4), nullable=False, default=0.18, server_default="0.18"
    )
    montant_tva: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")

    # Retenue de garantie
    retenue_garantie_taux: Mapped[float] = mapped_column(
        Numeric(5, 4), nullable=False, default=0.05, server_default="0.05"
    )
    retenue_garantie_montant: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )

    # Remboursement d'avance
    avance_remboursee_situation: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )

    # Retenues fiscales
    ras_montant: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    ras_taux: Mapped[float] = mapped_column(
        Numeric(5, 4), nullable=False, default=0, server_default="0"
    )

    # Montant net à payer
    montant_net_a_payer: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Écriture comptable
    ecriture_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("ecritures.id"), nullable=True
    )
    customer_invoice_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("customer_invoices.id"), nullable=True
    )

    # Statut
    statut: Mapped[str] = mapped_column(
        String(20), nullable=False, default="brouillon", server_default="brouillon"
    )
    date_validation_client: Mapped[date | None] = mapped_column(Date, nullable=True)
    motif_contestation: Mapped[str | None] = mapped_column(Text, nullable=True)

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    created_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("project_id", "numero_situation", name="uq_progress_billing_num"),
        UniqueConstraint("tenant_id", "numero", name="uq_progress_billing_ref"),
        Index("idx_pb_project_date", "project_id", "date_situation"),
    )

    def __repr__(self) -> str:
        return f"<ProgressBilling {self.numero} — Sit. {self.numero_situation}>"


class ProgressBillingLine(UUIDPrimaryKeyMixin, Base):
    """Ligne de situation de travaux (par phase ou par nature de prestation)."""
    __tablename__ = "progress_billing_lines"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    billing_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("progress_billings.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    phase_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("project_phases.id"), nullable=True
    )

    ordre: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    designation: Mapped[str] = mapped_column(Text, nullable=False)
    unite: Mapped[str] = mapped_column(String(10), nullable=False, default="U", server_default="U")

    # Quantités
    quantite_marche: Mapped[float] = mapped_column(Numeric(18, 3), nullable=False)
    quantite_cumulee_precedente: Mapped[float] = mapped_column(
        Numeric(18, 3), nullable=False, default=0, server_default="0"
    )
    quantite_cumulee_actuelle: Mapped[float] = mapped_column(Numeric(18, 3), nullable=False)
    quantite_situation: Mapped[float] = mapped_column(Numeric(18, 3), nullable=False)

    # Prix
    prix_unitaire_ht: Mapped[int] = mapped_column(BigInteger, nullable=False)

    montant_cumule_precedent_ht: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    montant_cumule_actuel_ht: Mapped[int] = mapped_column(BigInteger, nullable=False)
    montant_situation_ht: Mapped[int] = mapped_column(BigInteger, nullable=False)

    compte_produit: Mapped[str] = mapped_column(String(10), nullable=False)

    __table_args__ = (
        Index("idx_pbl_billing", "billing_id", "ordre"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# JALON / MILESTONE
# ─────────────────────────────────────────────────────────────────────────────
class ProjectMilestone(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Jalon contractuel (déclenche souvent un paiement)."""
    __tablename__ = "project_milestones"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    code: Mapped[str] = mapped_column(String(30), nullable=False)
    libelle: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    date_prevue: Mapped[date] = mapped_column(Date, nullable=False)
    date_atteinte: Mapped[date | None] = mapped_column(Date, nullable=True)

    montant_associe_ht: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    pourcentage_avancement_attendu: Mapped[float] = mapped_column(
        Numeric(5, 2), nullable=False, default=0, server_default="0"
    )

    atteint: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    ordre: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        UniqueConstraint("project_id", "code", name="uq_project_milestone_code"),
    )
