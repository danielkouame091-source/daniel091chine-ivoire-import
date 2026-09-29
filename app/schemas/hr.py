"""DTO RH — Départements, Contrats, Congés, Évaluations, Formations."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

TypeContratT = Literal["CDI", "CDD", "Stage", "Apprentissage", "Interim", "Consultant", "Stagiaire école"]
TypeCongeT = Literal[
    "annuel", "maladie", "maternite", "paternite", "exceptionnel",
    "sans_solde", "formation", "sabbatique", "mariage",
    "deces_conjoint", "deces_parent", "naissance",
]
StatutCongeT = Literal[
    "brouillon", "soumise", "validee_manager", "validee_rh",
    "validee", "refusee", "annulee", "en_cours", "terminee",
]
TypeEvalT = Literal["annuelle", "semestrielle", "probatoire", "objectifs", "a_chaud", "reconnaissance", "plan_developpement"]
TypeFormatT = Literal["initiale", "continue", "securite", "technique", "manageriale", "linguistique", "informatique", "certifiante"]
TypeDocRHT = Literal[
    "contrat", "avenant", "certificat_travail", "attestation_travail",
    "bulletin_paie", "cv", "diplome", "attestation_formation", "fiche_poste",
    "lettre_licenciement", "lettre_demission", "certificat_medical", "autre",
]
MotifDepartT = Literal[
    "demission", "licenciement_faute", "licenciement_economique",
    "rupture_conventionnelle", "fin_cdd", "retraite", "deces",
    "abandon_poste", "periode_essai_non_concluante",
]


# ─────────────────────────────────────────────────────────────────────────────
# DÉPARTEMENTS
# ─────────────────────────────────────────────────────────────────────────────
class DepartmentCreate(BaseModel):
    code: str = Field(min_length=2, max_length=20)
    libelle: str = Field(min_length=2, max_length=200)
    description: str | None = None
    parent_id: UUID | None = None
    responsable_employee_id: UUID | None = None
    budget_masse_salariale_ht: int = Field(0, ge=0)


class DepartmentUpdate(BaseModel):
    libelle: str | None = None
    description: str | None = None
    parent_id: UUID | None = None
    responsable_employee_id: UUID | None = None
    budget_masse_salariale_ht: int | None = Field(None, ge=0)
    actif: bool | None = None


class DepartmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    code: str
    libelle: str
    description: str | None
    parent_id: UUID | None
    responsable_employee_id: UUID | None
    budget_masse_salariale_ht: int
    actif: bool
    created_at: datetime


# ─────────────────────────────────────────────────────────────────────────────
# CONTRATS
# ─────────────────────────────────────────────────────────────────────────────
class ContractCreate(BaseModel):
    employee_id: UUID
    type_contrat: TypeContratT
    date_debut: date
    date_fin: date | None = None
    date_signature: date | None = None

    periode_essai_mois: int | None = Field(None, ge=0, le=12)
    poste: str = Field(min_length=2, max_length=200)
    categorie_professionnelle: str | None = None
    coefficient: int | None = None
    departement_id: UUID | None = None
    manager_employee_id: UUID | None = None

    salaire_base_mensuel: int = Field(gt=0)
    sursalaire: int = Field(0, ge=0)
    primes_contractuelles: dict[str, int] = Field(default_factory=dict)
    avantages: dict[str, int] = Field(default_factory=dict)

    lieu_travail: str | None = None
    convention_collective: str | None = None
    document_contrat_url: str | None = None

    @model_validator(mode="after")
    def coherent(self):
        if self.date_fin and self.date_fin < self.date_debut:
            raise ValueError("date_fin doit être ≥ date_debut")
        if self.type_contrat == "CDI" and self.date_fin is not None:
            raise ValueError("Un CDI ne peut pas avoir de date_fin")
        if self.type_contrat != "CDI" and self.date_fin is None:
            raise ValueError(f"Un contrat {self.type_contrat} doit avoir une date_fin")
        return self


class ContractUpdate(BaseModel):
    poste: str | None = None
    categorie_professionnelle: str | None = None
    coefficient: int | None = None
    departement_id: UUID | None = None
    manager_employee_id: UUID | None = None
    salaire_base_mensuel: int | None = Field(None, gt=0)
    sursalaire: int | None = Field(None, ge=0)
    primes_contractuelles: dict[str, int] | None = None
    avantages: dict[str, int] | None = None
    lieu_travail: str | None = None
    statut: str | None = None
    document_contrat_url: str | None = None


class ContractOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    employee_id: UUID
    numero: str
    type_contrat: str
    date_debut: date
    date_fin: date | None
    date_signature: date | None
    periode_essai_mois: int | None
    date_fin_periode_essai: date | None
    poste: str
    categorie_professionnelle: str | None
    coefficient: int | None
    departement_id: UUID | None
    manager_employee_id: UUID | None
    salaire_base_mensuel: int
    sursalaire: int
    primes_contractuelles: dict[str, Any]
    avantages: dict[str, Any]
    lieu_travail: str | None
    statut: str
    motif_rupture: str | None
    date_rupture: date | None
    preavis_jours: int | None
    created_at: datetime


class ContractRuptureIn(BaseModel):
    motif: MotifDepartT
    date_effective: date
    dispense_preavis: bool = False
    commentaire: str | None = Field(None, max_length=2000)


# ─────────────────────────────────────────────────────────────────────────────
# SOLDE DE CONGÉS
# ─────────────────────────────────────────────────────────────────────────────
class LeaveBalanceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    employee_id: UUID
    annee: int
    conges_annuels_acquis: float
    conges_annuels_reportes: float
    conges_annuels_pris: float
    conges_annuels_solde: float
    jours_anciennete: float
    conges_maladie_pris: int
    conges_exceptionnels_pris: int


# ─────────────────────────────────────────────────────────────────────────────
# DEMANDES DE CONGÉ
# ─────────────────────────────────────────────────────────────────────────────
class LeaveRequestCreate(BaseModel):
    employee_id: UUID
    type_conge: TypeCongeT
    date_debut: date
    date_fin: date
    motif: str | None = None
    justificatif_url: str | None = None
    manager_validateur_id: UUID | None = None

    @model_validator(mode="after")
    def coherent(self):
        if self.date_fin < self.date_debut:
            raise ValueError("date_fin doit être ≥ date_debut")
        return self


class LeaveRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    employee_id: UUID
    reference: str
    type_conge: str
    date_debut: date
    date_fin: date
    nb_jours_ouvrables: float
    nb_jours_calendaires: int
    motif: str | None
    statut: str
    manager_validateur_id: UUID | None
    validee_manager_at: datetime | None
    commentaire_manager: str | None
    validee_rh_at: datetime | None
    commentaire_rh: str | None
    motif_refus: str | None
    validee_at: datetime | None
    created_at: datetime


class LeaveApprovalIn(BaseModel):
    approuve: bool
    commentaire: str | None = Field(None, max_length=1000)


class LeaveRefuseIn(BaseModel):
    motif_refus: str = Field(min_length=5, max_length=1000)


class LeaveCancelIn(BaseModel):
    motif_annulation: str = Field(min_length=5, max_length=500)


# ─────────────────────────────────────────────────────────────────────────────
# ABSENCES
# ─────────────────────────────────────────────────────────────────────────────
class AbsenceCreate(BaseModel):
    employee_id: UUID
    date_debut: date
    date_fin: date
    type_absence: Literal[
        "justifiee", "non_justifiee", "maladie", "urgence_familiale", "retard_recurrent"
    ]
    motif: str | None = None
    justificatif_url: str | None = None
    impact_salaire: bool = False


class AbsenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    employee_id: UUID
    date_debut: date
    date_fin: date
    nb_jours: float
    type_absence: str
    motif: str | None
    impact_salaire: bool
    montant_retenue: int
    created_at: datetime


# ─────────────────────────────────────────────────────────────────────────────
# ÉVALUATIONS
# ─────────────────────────────────────────────────────────────────────────────
class ReviewCreate(BaseModel):
    employee_id: UUID
    evaluateur_id: UUID | None = None
    type_evaluation: TypeEvalT
    periode_debut: date
    periode_fin: date
    date_entretien: date | None = None

    competences: list[dict[str, Any]] = Field(default_factory=list)
    objectifs: list[dict[str, Any]] = Field(default_factory=list)

    points_forts: str | None = None
    axes_amelioration: str | None = None
    commentaires_employe: str | None = None
    objectifs_prochaine_periode: list[dict[str, Any]] = Field(default_factory=list)

    augmentation_proposee_pct: float | None = Field(None, ge=0, le=50)
    promotion_proposee: bool = False
    nouveau_poste_propose: str | None = None


class ReviewUpdate(BaseModel):
    date_entretien: date | None = None
    competences: list[dict[str, Any]] | None = None
    objectifs: list[dict[str, Any]] | None = None
    points_forts: str | None = None
    axes_amelioration: str | None = None
    commentaires_employe: str | None = None
    objectifs_prochaine_periode: list[dict[str, Any]] | None = None
    augmentation_proposee_pct: float | None = None
    promotion_proposee: bool | None = None
    nouveau_poste_propose: str | None = None
    statut: str | None = None


class ReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    employee_id: UUID
    evaluateur_id: UUID | None
    reference: str
    type_evaluation: str
    periode_debut: date
    periode_fin: date
    date_entretien: date | None
    date_finalisation: date | None
    competences: list[dict[str, Any]]
    objectifs: list[dict[str, Any]]
    score_global: float | None
    niveau_performance: str | None
    points_forts: str | None
    axes_amelioration: str | None
    augmentation_proposee_pct: float | None
    promotion_proposee: bool
    signee_employe_at: datetime | None
    signee_evaluateur_at: datetime | None
    statut: str
    created_at: datetime


class ReviewFinalizeIn(BaseModel):
    score_global: float = Field(ge=0, le=200)
    commentaire: str | None = None


# ─────────────────────────────────────────────────────────────────────────────
# FORMATIONS
# ─────────────────────────────────────────────────────────────────────────────
class TrainingCreate(BaseModel):
    code: str = Field(min_length=2, max_length=30)
    titre: str = Field(min_length=2, max_length=200)
    description: str | None = None
    type_formation: TypeFormatT
    organisme: str | None = None
    formateur: str | None = None
    date_debut: date
    date_fin: date
    duree_heures: float = Field(gt=0)
    lieu: str | None = None
    en_ligne: bool = False
    url_formation: str | None = None
    cout_total: int = Field(0, ge=0)
    pris_en_charge_employeur: int = Field(0, ge=0)
    certifiante: bool = False
    organisme_certificateur: str | None = None


class TrainingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    code: str
    titre: str
    type_formation: str
    organisme: str | None
    date_debut: date
    date_fin: date
    duree_heures: float
    lieu: str | None
    en_ligne: bool
    cout_total: int
    certifiante: bool
    statut: str
    created_at: datetime


class TrainingParticipantCreate(BaseModel):
    employee_id: UUID


class TrainingParticipantUpdate(BaseModel):
    statut_participation: Literal["inscrit", "present", "absent", "complete", "abandonne"] | None = None
    presence_pct: float | None = Field(None, ge=0, le=100)
    score_evaluation: float | None = Field(None, ge=0, le=100)
    certification_obtenue: bool | None = None
    attestation_url: str | None = None
    feedback: str | None = None
    note_satisfaction: int | None = Field(None, ge=1, le=5)


class TrainingParticipantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    training_id: UUID
    employee_id: UUID
    statut_participation: str
    presence_pct: float | None
    score_evaluation: float | None
    certification_obtenue: bool
    attestation_url: str | None
    note_satisfaction: int | None


# ─────────────────────────────────────────────────────────────────────────────
# DOCUMENTS RH
# ─────────────────────────────────────────────────────────────────────────────
class EmployeeDocumentCreate(BaseModel):
    employee_id: UUID
    type_document: TypeDocRHT
    titre: str = Field(min_length=2, max_length=200)
    description: str | None = None
    fichier_url: str
    fichier_nom: str
    fichier_taille_kb: int | None = None
    mime_type: str = "application/pdf"
    confidentiel: bool = False
    date_document: date | None = None
    date_expiration: date | None = None


class EmployeeDocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    employee_id: UUID
    type_document: str
    titre: str
    description: str | None
    fichier_nom: str
    fichier_taille_kb: int | None
    mime_type: str
    confidentiel: bool
    date_document: date | None
    date_expiration: date | None
    created_at: datetime


# ─────────────────────────────────────────────────────────────────────────────
# SANCTIONS
# ─────────────────────────────────────────────────────────────────────────────
class SanctionCreate(BaseModel):
    employee_id: UUID
    type_sanction: Literal[
        "avertissement_ecrit", "blame",
        "mise_a_pied_1_3j", "mise_a_pied_4_8j", "licenciement",
    ]
    motif: str = Field(min_length=5, max_length=500)
    description: str | None = None
    date_faits: date
    date_notification: date
    duree_jours: int | None = Field(None, ge=0)
    date_debut: date | None = None
    date_fin: date | None = None
    impact_salaire: bool = False
    montant_retenue: int = Field(0, ge=0)


class SanctionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    employee_id: UUID
    reference: str
    type_sanction: str
    motif: str
    date_faits: date
    date_notification: date
    duree_jours: int | None
    impact_salaire: bool
    montant_retenue: int
    notifiee_at: datetime | None
    contestee: bool
    created_at: datetime


# ─────────────────────────────────────────────────────────────────────────────
# POINTAGE
# ─────────────────────────────────────────────────────────────────────────────
class TimeEntryCreate(BaseModel):
    employee_id: UUID
    date_travail: date
    heure_arrivee: datetime | None = None
    heure_depart: datetime | None = None
    heures_travaillees: float = Field(0, ge=0, le=24)
    heures_supplementaires: float = Field(0, ge=0, le=12)
    heures_nuit: float = Field(0, ge=0, le=12)
    type_journee: Literal["travail", "conge", "absence", "ferie", "weekend"] = "travail"
    project_id: UUID | None = None
    notes: str | None = None


class TimeEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    employee_id: UUID
    date_travail: date
    heure_arrivee: datetime | None
    heure_depart: datetime | None
    heures_travaillees: float
    heures_supplementaires: float
    heures_nuit: float
    type_journee: str
    validee: bool
    project_id: UUID | None
    created_at: datetime


# ─────────────────────────────────────────────────────────────────────────────
# DÉPART (OFFBOARDING)
# ─────────────────────────────────────────────────────────────────────────────
class OffboardingCreate(BaseModel):
    employee_id: UUID
    motif_depart: MotifDepartT
    date_annonce: date
    date_effective: date
    dispense_preavis: bool = False
    commentaire: str | None = None


class OffboardingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    employee_id: UUID
    motif_depart: str
    date_annonce: date
    date_effective: date
    preavis_jours: int | None
    dispense_preavis: bool
    solde_conges_jours: float
    indemnite_conges: int
    indemnite_preavis: int
    indemnite_licenciement: int
    total_solde: int
    statut: str
    certificat_travail_url: str | None
    created_at: datetime


# ─────────────────────────────────────────────────────────────────────────────
# ANALYTICS RH
# ─────────────────────────────────────────────────────────────────────────────
class HRDashboardOut(BaseModel):
    tenant_id: UUID
    date_arret: date
    nb_employes_actifs: int
    nb_employes_sortis_12m: int
    nb_employes_en_conge_actuellement: int
    nb_candidats_periode_essai: int
    taux_turnover_12m_pct: float
    anciennete_moyenne_annees: float
    masse_salariale_mensuelle_ht: int
    conges_en_attente_validation: int
    evaluations_a_venir_30j: int
    formations_planifiees_30j: int
    repartition_par_departement: dict[str, int]
    repartition_par_contrat: dict[str, int]


class TurnoverAnalysisOut(BaseModel):
    tenant_id: UUID
    periode_debut: date
    periode_fin: date
    effectif_debut: int
    effectif_fin: int
    entrees: int
    sorties: int
    taux_turnover_pct: float
    taux_turnover_volontaire_pct: float
    motif_depart_repartition: dict[str, int]
    anciennete_moyenne_sortants_annees: float


class LeaveSummaryOut(BaseModel):
    tenant_id: UUID
    annee: int
    nb_demandes_total: int
    nb_validees: int
    nb_refusees: int
    nb_en_attente: int
    jours_pris_total: float
    taux_utilisation_conges_pct: float
    top_employes_conges: list[dict[str, Any]]
