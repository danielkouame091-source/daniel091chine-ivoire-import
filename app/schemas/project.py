"""DTO Projets & Chantiers SYSCOHADA."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

TypeProj = Literal[
    "chantier_btp", "projet_investissement", "projet_interne",
    "mission_service", "projet_production", "maintenance", "formation", "autre",
]
MethodeReco = Literal["a_l_avancement", "a_terminaison", "a_l_encaissement", "pourcentage_avancement"]
MethodeAvct = Literal["physique", "couts_engages", "heures_travaillees", "unites_produites", "jalons_atteints"]
StatutProj = Literal["brouillon", "en_preparation", "en_cours", "en_pause", "termine", "annule", "en_litige", "cloture"]
TypePhaseT = Literal["etude", "conception", "approvisionnement", "execution", "controle", "reception", "garantie", "livraison"]
TypeCout = Literal["achat", "sous_traitance", "main_oeuvre", "location", "frais_generaux", "autre"]


# ─────────────────────────────────────────────────────────────────────────────
# PROJET
# ─────────────────────────────────────────────────────────────────────────────
class ProjectCreate(BaseModel):
    code: str = Field(min_length=1, max_length=30)
    libelle: str = Field(min_length=2, max_length=200)
    description: str | None = None
    type_projet: TypeProj
    methode_reconnaissance: MethodeReco = "a_l_avancement"
    methode_avancement: MethodeAvct = "couts_engages"

    customer_id: UUID | None = None
    chef_projet_user_id: UUID | None = None

    date_debut_prevue: date
    date_fin_prevue: date

    montant_marche_ht: int = Field(0, ge=0)
    taux_tva: float = Field(0.18, ge=0.0, le=0.30)
    budget_previsionnel_ht: int = Field(0, ge=0)

    retenue_garantie_taux: float = Field(0.05, ge=0.0, le=0.10)
    avance_demarrage_pct: float = Field(0, ge=0.0, le=100.0)

    compte_projet: str = Field(min_length=2, max_length=10)
    analytical_section_id: UUID | None = None

    @model_validator(mode="after")
    def coherent(self):
        if self.date_fin_prevue < self.date_debut_prevue:
            raise ValueError("date_fin_prevue doit être ≥ date_debut_prevue")
        return self


class ProjectUpdate(BaseModel):
    libelle: str | None = None
    description: str | None = None
    chef_projet_user_id: UUID | None = None
    date_fin_prevue: date | None = None
    montant_marche_ht: int | None = Field(None, ge=0)
    budget_previsionnel_ht: int | None = Field(None, ge=0)
    cout_total_estime_ht: int | None = Field(None, ge=0)
    retenue_garantie_taux: float | None = Field(None, ge=0.0, le=0.10)


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    code: str
    libelle: str
    description: str | None
    type_projet: str
    methode_reconnaissance: str
    methode_avancement: str
    customer_id: UUID | None
    chef_projet_user_id: UUID | None
    date_debut_prevue: date
    date_fin_prevue: date
    date_debut_reelle: date | None
    date_fin_reelle: date | None
    statut: str
    pourcentage_avancement_physique: float
    pourcentage_avancement_financier: float
    montant_marche_ht: int
    montant_marche_ttc: int
    budget_previsionnel_ht: int
    budget_engage: int
    budget_realise: int
    cout_total_estime_ht: int
    retenue_garantie_taux: float
    retenue_garantie_montant: int
    avance_demarrage_montant: int
    avance_remboursee: int
    compte_projet: str
    niveau_alerte: str
    created_at: datetime


class ProjectDetailOut(ProjectOut):
    phases: list["ProjectPhaseOut"] = Field(default_factory=list)
    jalons: list["ProjectMilestoneOut"] = Field(default_factory=list)
    nb_taches: int = 0
    nb_taches_terminees: int = 0
    nb_couts_imputes: int = 0
    nb_situations: int = 0
    marge_previsionnelle: int = 0
    marge_previsionnelle_pct: float = 0.0
    taux_consommation_budget: float = 0.0


# ─────────────────────────────────────────────────────────────────────────────
# PHASE
# ─────────────────────────────────────────────────────────────────────────────
class ProjectPhaseCreate(BaseModel):
    code: str = Field(min_length=1, max_length=30)
    libelle: str = Field(min_length=2, max_length=200)
    description: str | None = None
    type_phase: TypePhaseT
    ordre: int = Field(1, ge=1)
    date_debut_prevue: date
    date_fin_prevue: date
    budget_ht: int = Field(0, ge=0)
    poids: float = Field(0, ge=0, le=100)
    responsable_user_id: UUID | None = None

    @model_validator(mode="after")
    def coherent(self):
        if self.date_fin_prevue < self.date_debut_prevue:
            raise ValueError("date_fin_prevue doit être ≥ date_debut_prevue")
        return self


class ProjectPhaseUpdate(BaseModel):
    libelle: str | None = None
    description: str | None = None
    date_fin_prevue: date | None = None
    budget_ht: int | None = Field(None, ge=0)
    poids: float | None = Field(None, ge=0, le=100)
    statut: str | None = None
    pourcentage_avancement: float | None = Field(None, ge=0, le=100)


class ProjectPhaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    code: str
    libelle: str
    type_phase: str
    ordre: int
    date_debut_prevue: date
    date_fin_prevue: date
    date_debut_reelle: date | None
    date_fin_reelle: date | None
    budget_ht: int
    budget_realise: int
    pourcentage_avancement: float
    poids: float
    statut: str
    responsable_user_id: UUID | None


# ─────────────────────────────────────────────────────────────────────────────
# TÂCHE
# ─────────────────────────────────────────────────────────────────────────────
class ProjectTaskCreate(BaseModel):
    code: str = Field(min_length=1, max_length=30)
    libelle: str = Field(min_length=2, max_length=200)
    description: str | None = None
    phase_id: UUID | None = None
    ordre: int = Field(1, ge=1)
    date_debut_prevue: date
    date_fin_prevue: date
    duree_estimee_h: float | None = Field(None, ge=0)
    budget_ht: int = Field(0, ge=0)
    priorite: Literal["basse", "normale", "haute", "critique"] = "normale"
    assigne_a_user_id: UUID | None = None


class ProjectTaskUpdate(BaseModel):
    libelle: str | None = None
    description: str | None = None
    date_fin_prevue: date | None = None
    duree_estimee_h: float | None = Field(None, ge=0)
    budget_ht: int | None = Field(None, ge=0)
    pourcentage_avancement: float | None = Field(None, ge=0, le=100)
    statut: Literal["a_faire", "en_cours", "terminee", "bloquee", "annulee"] | None = None
    priorite: Literal["basse", "normale", "haute", "critique"] | None = None
    assigne_a_user_id: UUID | None = None


class ProjectTaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    phase_id: UUID | None
    code: str
    libelle: str
    ordre: int
    date_debut_prevue: date
    date_fin_prevue: date
    date_debut_reelle: date | None
    date_fin_reelle: date | None
    duree_estimee_h: float | None
    duree_reelle_h: float | None
    budget_ht: int
    budget_realise: int
    pourcentage_avancement: float
    statut: str
    priorite: str
    assigne_a_user_id: UUID | None


# ─────────────────────────────────────────────────────────────────────────────
# JALON
# ─────────────────────────────────────────────────────────────────────────────
class ProjectMilestoneCreate(BaseModel):
    code: str = Field(min_length=1, max_length=30)
    libelle: str = Field(min_length=2, max_length=200)
    description: str | None = None
    date_prevue: date
    montant_associe_ht: int | None = Field(None, ge=0)
    pourcentage_avancement_attendu: float = Field(0, ge=0, le=100)
    ordre: int = Field(1, ge=1)


class ProjectMilestoneOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    code: str
    libelle: str
    date_prevue: date
    date_atteinte: date | None
    montant_associe_ht: int | None
    pourcentage_avancement_attendu: float
    atteint: bool
    ordre: int


# ─────────────────────────────────────────────────────────────────────────────
# COÛT RÉEL
# ─────────────────────────────────────────────────────────────────────────────
class ProjectCostCreate(BaseModel):
    phase_id: UUID | None = None
    date_cout: date
    libelle: str = Field(min_length=2, max_length=200)
    type_cout: TypeCout
    montant_ht: int = Field(gt=0)
    montant_tva: int = Field(0, ge=0)
    compte_comptable: str = Field(min_length=2, max_length=10)
    source_type: str = "manuel"
    source_id: UUID | None = None


class ProjectCostOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    phase_id: UUID | None
    date_cout: date
    libelle: str
    type_cout: str
    montant_ht: int
    montant_tva: int
    source_type: str
    compte_comptable: str
    ecriture_id: UUID | None
    valide: bool
    created_at: datetime


# ─────────────────────────────────────────────────────────────────────────────
# SITUATION DE TRAVAUX
# ─────────────────────────────────────────────────────────────────────────────
class ProgressBillingLineCreate(BaseModel):
    phase_id: UUID | None = None
    ordre: int = Field(1, ge=1)
    designation: str = Field(min_length=2, max_length=200)
    unite: str = Field("U", max_length=10)
    quantite_marche: float = Field(gt=0)
    quantite_cumulee_precedente: float = Field(0, ge=0)
    quantite_cumulee_actuelle: float = Field(ge=0)
    prix_unitaire_ht: int = Field(gt=0)
    compte_produit: str = Field(min_length=2, max_length=10)

    @model_validator(mode="after")
    def coherent(self):
        if self.quantite_cumulee_actuelle < self.quantite_cumulee_precedente:
            raise ValueError("quantite_cumulee_actuelle doit être ≥ quantite_cumulee_precedente")
        if self.quantite_cumulee_actuelle > self.quantite_marche:
            raise ValueError("quantite_cumulee_actuelle ne peut dépasser quantite_marche")
        return self


class ProgressBillingCreate(BaseModel):
    project_id: UUID
    date_situation: date
    date_echeance: date | None = None
    libelle: str = Field(min_length=2, max_length=200)
    pourcentage_avancement_cumule: float = Field(ge=0, le=100)

    taux_tva: float = Field(0.18, ge=0.0, le=0.30)
    retenue_garantie_taux: float | None = None  # Si None, utilise celui du projet
    ras_taux: float = Field(0, ge=0.0, le=0.30)

    lignes: list[ProgressBillingLineCreate] = Field(min_length=1)


class ProgressBillingLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    ordre: int
    designation: str
    unite: str
    quantite_marche: float
    quantite_cumulee_precedente: float
    quantite_cumulee_actuelle: float
    quantite_situation: float
    prix_unitaire_ht: int
    montant_cumule_precedent_ht: int
    montant_cumule_actuel_ht: int
    montant_situation_ht: int
    compte_produit: str


class ProgressBillingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    project_id: UUID
    customer_id: UUID | None
    numero: str
    numero_situation: int
    date_situation: date
    date_echeance: date | None
    libelle: str
    pourcentage_avancement_cumule: float
    montant_cumule_precedent_ht: int
    montant_cumule_actuel_ht: int
    montant_situation_ht: int
    montant_tva: int
    retenue_garantie_taux: float
    retenue_garantie_montant: int
    avance_remboursee_situation: int
    ras_montant: int
    montant_net_a_payer: int
    statut: str
    ecriture_id: UUID | None
    customer_invoice_id: UUID | None
    created_at: datetime


class ProgressBillingDetailOut(ProgressBillingOut):
    lignes: list[ProgressBillingLineOut] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# REPORTING
# ─────────────────────────────────────────────────────────────────────────────
class ProjectMarginOut(BaseModel):
    project_id: UUID
    code: str
    libelle: str
    statut: str
    montant_marche_ht: int
    budget_previsionnel_ht: int
    budget_realise_ht: int
    marge_previsionnelle: int
    marge_previsionnelle_pct: float
    marge_actuelle: int
    marge_actuelle_pct: float
    avancement_physique_pct: float
    avancement_financier_pct: float
    niveau_alerte: str
    est_en_retard: bool


class ProjectPortfolioOut(BaseModel):
    tenant_id: UUID
    date_arret: date
    nb_projets_total: int
    nb_projets_en_cours: int
    nb_projets_termines: int
    nb_projets_en_retard: int
    nb_projets_depassement: int
    montant_marche_total_ht: int
    budget_realise_total_ht: int
    marge_globale_ht: int
    marge_globale_pct: float
    projets: list[ProjectMarginOut]


class AvancementSituationOut(BaseModel):
    """
    Calcul de l'avancement à facturer (méthode à l'avancement SYSCOHADA).
    Montant à facturer = % avancement × montant marché - déjà facturé.
    """
    project_id: UUID
    montant_marche_ht: int
    pourcentage_avancement: float
    montant_a_facturer_cumule_ht: int
    montant_deja_facture_ht: int
    montant_a_facturer_situation_ht: int
    ecart_a_facturer_ht: int
    methode: str
    note: str
