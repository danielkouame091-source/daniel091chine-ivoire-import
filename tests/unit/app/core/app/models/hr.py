"""Modèles RH — Départements, Contrats, Congés, Évaluations, Formations."""
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
# DÉPARTEMENT
# ─────────────────────────────────────────────────────────────────────────────
class Department(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Département / service d'une entreprise."""
    __tablename__ = "departments"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    code: Mapped[str] = mapped_column(String(20), nullable=False)
    libelle: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Hiérarchie
    parent_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("departments.id"), nullable=True
    )

    # Responsable
    responsable_employee_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("employees.id"), nullable=True
    )

    # Budget annuel masse salariale
    budget_masse_salariale_ht: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )

    actif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_department_code"),
        Index("idx_dept_tenant_actif", "tenant_id", "actif"),
    )

    def __repr__(self) -> str:
        return f"<Department {self.code} — {self.libelle}>"


# ─────────────────────────────────────────────────────────────────────────────
# CONTRAT DE TRAVAIL
# ─────────────────────────────────────────────────────────────────────────────
class EmploymentContract(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Contrat de travail d'un employé.
    Peut y avoir plusieurs contrats successifs (CDD renouvelé, changement de poste...).
    """
    __tablename__ = "employment_contracts"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    employee_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Identification
    numero: Mapped[str] = mapped_column(String(30), nullable=False)
    type_contrat: Mapped[str] = mapped_column(String(30), nullable=False)

    # Période
    date_debut: Mapped[date] = mapped_column(Date, nullable=False)
    date_fin: Mapped[date | None] = mapped_column(Date, nullable=True)   # NULL pour CDI
    date_signature: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Période d'essai
    periode_essai_mois: Mapped[int | None] = mapped_column(Integer, nullable=True)
    date_fin_periode_essai: Mapped[date | None] = mapped_column(Date, nullable=True)
    periode_essai_renouvelee: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # Poste
    poste: Mapped[str] = mapped_column(Text, nullable=False)
    categorie_professionnelle: Mapped[str | None] = mapped_column(String(20), nullable=True)
    coefficient: Mapped[int | None] = mapped_column(Integer, nullable=True)
    departement_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("departments.id"), nullable=True
    )
    manager_employee_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("employees.id"), nullable=True
    )

    # Rémunération contractuelle
    salaire_base_mensuel: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sursalaire: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    primes_contractuelles: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )

    # Avantages
    avantages: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )   # {logement: 100000, transport: 50000, ...}

    # Lieu de travail
    lieu_travail: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Convention collective
    convention_collective: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Statut
    statut: Mapped[str] = mapped_column(
        String(20), nullable=False, default="actif", server_default="actif"
    )
    motif_rupture: Mapped[str | None] = mapped_column(String(50), nullable=True)
    date_rupture: Mapped[date | None] = mapped_column(Date, nullable=True)
    preavis_jours: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Documents
    document_contrat_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Signature électronique
    signe_employeur_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    signe_employe_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    created_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "numero", name="uq_contract_numero"),
        Index("idx_contract_employee", "employee_id", "date_debut"),
        Index("idx_contract_tenant_statut", "tenant_id", "statut"),
        Index("idx_contract_fin_cdd", "date_fin"),
        CheckConstraint("date_fin IS NULL OR date_fin >= date_debut", name="contract_dates_coherentes"),
    )

    def __repr__(self) -> str:
        return f"<EmploymentContract {self.numero} ({self.type_contrat})>"

    @property
    def est_cdi(self) -> bool:
        return self.type_contrat == "CDI"

    @property
    def est_actif(self) -> bool:
        return self.statut == "actif"


# ─────────────────────────────────────────────────────────────────────────────
# SOLDE DE CONGÉS
# ─────────────────────────────────────────────────────────────────────────────
class LeaveBalance(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Solde de congés d'un employé pour une année donnée.
    Recalculé automatiquement lors des embauches et en début d'année.
    """
    __tablename__ = "leave_balances"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    employee_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    annee: Mapped[int] = mapped_column(Integer, nullable=False)

    # Congés annuels
    conges_annuels_acquis: Mapped[float] = mapped_column(
        Numeric(6, 2), nullable=False, default=0, server_default="0"
    )
    conges_annuels_reportes: Mapped[float] = mapped_column(
        Numeric(6, 2), nullable=False, default=0, server_default="0"
    )
    conges_annuels_pris: Mapped[float] = mapped_column(
        Numeric(6, 2), nullable=False, default=0, server_default="0"
    )
    conges_annuels_solde: Mapped[float] = mapped_column(
        Numeric(6, 2), nullable=False, default=0, server_default="0"
    )

    # Majoration ancienneté
    jours_anciennete: Mapped[float] = mapped_column(
        Numeric(4, 1), nullable=False, default=0, server_default="0"
    )

    # Autres compteurs (pour usage interne)
    conges_maladie_pris: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    conges_exceptionnels_pris: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        UniqueConstraint("employee_id", "annee", name="uq_leave_balance_year"),
    )

    def __repr__(self) -> str:
        return f"<LeaveBalance emp={self.employee_id} {self.annee} solde={self.conges_annuels_solde}>"


# ─────────────────────────────────────────────────────────────────────────────
# DEMANDE DE CONGÉ
# ─────────────────────────────────────────────────────────────────────────────
class LeaveRequest(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Demande de congé avec workflow de validation."""
    __tablename__ = "leave_requests"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    employee_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    # Identification
    reference: Mapped[str] = mapped_column(String(30), nullable=False)
    type_conge: Mapped[str] = mapped_column(String(30), nullable=False)

    # Période
    date_debut: Mapped[date] = mapped_column(Date, nullable=False)
    date_fin: Mapped[date] = mapped_column(Date, nullable=False)
    nb_jours_ouvrables: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False)
    nb_jours_calendaires: Mapped[int] = mapped_column(Integer, nullable=False)

    # Justification
    motif: Mapped[str | None] = mapped_column(Text, nullable=True)
    justificatif_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Statut
    statut: Mapped[str] = mapped_column(
        String(30), nullable=False, default="brouillon", server_default="brouillon"
    )

    # Workflow de validation
    manager_validateur_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("employees.id"), nullable=True
    )
    validee_manager_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    validee_manager_par: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    commentaire_manager: Mapped[str | None] = mapped_column(Text, nullable=True)

    rh_validateur_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    validee_rh_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    commentaire_rh: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Refus
    motif_refus: Mapped[str | None] = mapped_column(Text, nullable=True)
    refusee_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Annulation
    annulee_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    motif_annulation: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Validation finale
    validee_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    created_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "reference", name="uq_leave_request_ref"),
        Index("idx_lr_employee_dates", "employee_id", "date_debut"),
        Index("idx_lr_tenant_statut", "tenant_id", "statut"),
        Index("idx_lr_statut_dates", "statut", "date_debut"),
        CheckConstraint("date_fin >= date_debut", name="leave_dates_coherentes"),
    )

    def __repr__(self) -> str:
        return f"<LeaveRequest {self.reference} ({self.statut})>"


# ─────────────────────────────────────────────────────────────────────────────
# ABSENCE
# ─────────────────────────────────────────────────────────────────────────────
class EmployeeAbsence(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Absence non planifiée (maladie, urgence, injustifiée)."""
    __tablename__ = "employee_absences"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    employee_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    date_debut: Mapped[date] = mapped_column(Date, nullable=False)
    date_fin: Mapped[date] = mapped_column(Date, nullable=False)
    nb_jours: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False)

    type_absence: Mapped[str] = mapped_column(String(30), nullable=False)
    # justifiee | non_justifiee | maladie | urgence_familiale | retard_recurrent

    motif: Mapped[str | None] = mapped_column(Text, nullable=True)
    justificatif_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    impact_salaire: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    montant_retenue: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )

    sanction_associee: Mapped[str | None] = mapped_column(String(30), nullable=True)

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    created_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    __table_args__ = (
        Index("idx_absence_employee_dates", "employee_id", "date_debut"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# ÉVALUATION
# ─────────────────────────────────────────────────────────────────────────────
class PerformanceReview(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Évaluation de performance."""
    __tablename__ = "performance_reviews"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    employee_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    evaluateur_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("employees.id"), nullable=True
    )

    reference: Mapped[str] = mapped_column(String(30), nullable=False)
    type_evaluation: Mapped[str] = mapped_column(String(30), nullable=False)

    periode_debut: Mapped[date] = mapped_column(Date, nullable=False)
    periode_fin: Mapped[date] = mapped_column(Date, nullable=False)

    date_entretien: Mapped[date | None] = mapped_column(Date, nullable=True)
    date_finalisation: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Scores (JSONB : {competence: {libelle, score, commentaire}, ...})
    competences: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    objectifs: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )

    score_global: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    niveau_performance: Mapped[str | None] = mapped_column(String(30), nullable=True)

    # Appréciations
    points_forts: Mapped[str | None] = mapped_column(Text, nullable=True)
    axes_amelioration: Mapped[str | None] = mapped_column(Text, nullable=True)
    commentaires_employe: Mapped[str | None] = mapped_column(Text, nullable=True)
    objectifs_prochaine_periode: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )

    # Décisions
    augmentation_proposee_pct: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    promotion_proposee: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    nouveau_poste_propose: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Signature
    signee_employe_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    signee_evaluateur_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    statut: Mapped[str] = mapped_column(
        String(20), nullable=False, default="brouillon", server_default="brouillon"
    )

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "reference", name="uq_review_ref"),
        Index("idx_review_employee_periode", "employee_id", "periode_fin"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# FORMATION
# ─────────────────────────────────────────────────────────────────────────────
class Training(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Session de formation."""
    __tablename__ = "trainings"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    code: Mapped[str] = mapped_column(String(30), nullable=False)
    titre: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    type_formation: Mapped[str] = mapped_column(String(30), nullable=False)

    # Organisme
    organisme: Mapped[str | None] = mapped_column(Text, nullable=True)
    formateur: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Période
    date_debut: Mapped[date] = mapped_column(Date, nullable=False)
    date_fin: Mapped[date] = mapped_column(Date, nullable=False)
    duree_heures: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False)

    # Lieu
    lieu: Mapped[str | None] = mapped_column(Text, nullable=True)
    en_ligne: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    url_formation: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Coût
    cout_total: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    pris_en_charge_employeur: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )

    # Certification
    certifiante: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    organisme_certificateur: Mapped[str | None] = mapped_column(Text, nullable=True)

    statut: Mapped[str] = mapped_column(
        String(20), nullable=False, default="planifiee", server_default="planifiee"
    )

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    created_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_training_code"),
        Index("idx_training_tenant_dates", "tenant_id", "date_debut"),
    )


class TrainingParticipant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Participant à une formation."""
    __tablename__ = "training_participants"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    training_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("trainings.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    employee_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("employees.id"),
        nullable=False, index=True,
    )

    statut_participation: Mapped[str] = mapped_column(
        String(20), nullable=False, default="inscrit", server_default="inscrit"
    )
    # inscrit | present | absent | complete | abandonne

    presence_pct: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    score_evaluation: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    certification_obtenue: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    attestation_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    note_satisfaction: Mapped[int | None] = mapped_column(Integer, nullable=True)

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        UniqueConstraint("training_id", "employee_id", name="uq_training_participant"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# DOCUMENT RH
# ─────────────────────────────────────────────────────────────────────────────
class EmployeeDocument(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Document attaché à un employé (contrat, diplôme, certificat...)."""
    __tablename__ = "employee_documents"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    employee_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    type_document: Mapped[str] = mapped_column(String(30), nullable=False)
    titre: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    fichier_url: Mapped[str] = mapped_column(Text, nullable=False)
    fichier_nom: Mapped[str] = mapped_column(Text, nullable=False)
    fichier_taille_kb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False, default="application/pdf")

    confidentiel: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    date_document: Mapped[date | None] = mapped_column(Date, nullable=True)
    date_expiration: Mapped[date | None] = mapped_column(Date, nullable=True)

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    uploaded_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    __table_args__ = (
        Index("idx_emp_doc_employee_type", "employee_id", "type_document"),
        Index("idx_emp_doc_expiration", "date_expiration"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# SANCTION DISCIPLINAIRE
# ─────────────────────────────────────────────────────────────────────────────
class DisciplinaryAction(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Sanction disciplinaire notifiée à un employé."""
    __tablename__ = "disciplinary_actions"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    employee_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("employees.id"),
        nullable=False, index=True,
    )

    reference: Mapped[str] = mapped_column(String(30), nullable=False)
    type_sanction: Mapped[str] = mapped_column(String(30), nullable=False)
    motif: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    date_faits: Mapped[date] = mapped_column(Date, nullable=False)
    date_notification: Mapped[date] = mapped_column(Date, nullable=False)

    # Demande d'explication préalable
    demande_explication_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reponse_employe: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Durée (mise à pied)
    duree_jours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    date_debut: Mapped[date | None] = mapped_column(Date, nullable=True)
    date_fin: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Impact salaire
    impact_salaire: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    montant_retenue: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )

    # Notification
    notifiee_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    document_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Contestation
    contestee: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    contestation_motif: Mapped[str | None] = mapped_column(Text, nullable=True)

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    created_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "reference", name="uq_sanction_ref"),
        Index("idx_sanction_employee_date", "employee_id", "date_notification"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# POINTAGE / TEMPS DE TRAVAIL
# ─────────────────────────────────────────────────────────────────────────────
class TimeEntry(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Saisie de temps / pointage pour un employé."""
    __tablename__ = "time_entries"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    employee_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    date_travail: Mapped[date] = mapped_column(Date, nullable=False)

    heure_arrivee: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heure_depart: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    heures_travaillees: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=0, server_default="0")
    heures_supplementaires: Mapped[float] = mapped_column(
        Numeric(5, 2), nullable=False, default=0, server_default="0"
    )
    heures_nuit: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=0, server_default="0")

    # Type
    type_journee: Mapped[str] = mapped_column(
        String(20), nullable=False, default="travail", server_default="travail"
    )
    # travail | conge | absence | ferie | weekend

    # Validation
    validee: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    validee_par: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    validee_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Rattachement à un projet (si applicable)
    project_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        UniqueConstraint("employee_id", "date_travail", name="uq_time_entry_day"),
        Index("idx_time_entry_tenant_date", "tenant_id", "date_travail"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# DÉPART EMPLOYÉ (offboarding)
# ─────────────────────────────────────────────────────────────────────────────
class EmployeeOffboarding(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Processus de sortie d'un employé."""
    __tablename__ = "employee_offboardings"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    employee_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("employees.id"),
        nullable=False, index=True,
    )

    motif_depart: Mapped[str] = mapped_column(String(40), nullable=False)
    date_annonce: Mapped[date] = mapped_column(Date, nullable=False)
    date_effective: Mapped[date] = mapped_column(Date, nullable=False)

    # Préavis
    preavis_jours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    preavis_effectue: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    dispense_preavis: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # Solde de tout compte
    solde_conges_jours: Mapped[float] = mapped_column(
        Numeric(6, 2), nullable=False, default=0, server_default="0"
    )
    indemnite_conges: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    indemnite_preavis: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    indemnite_licenciement: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    autres_indemnites: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    total_solde: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")

    # Documents
    certificat_travail_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    attestation_pole_emploi_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    solde_tout_compte_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Restitution matériel
    materiel_restitue: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )

    # Statut
    statut: Mapped[str] = mapped_column(
        String(20), nullable=False, default="en_cours", server_default="en_cours"
    )
    # en_cours | complete | annule

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    created_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    __table_args__ = (
        Index("idx_offboard_tenant_statut", "tenant_id", "statut"),
    )
