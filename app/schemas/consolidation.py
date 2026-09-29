"""DTO Consolidation & Groupes OHADA."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

MethodeCons = Literal[
    "integration_globale", "integration_proportionnelle",
    "mise_en_equivalence", "exclue",
]
TypeElim = Literal[
    "titres_capitaux_propres", "creances_dettes", "produits_charges",
    "dividendes", "plus_values_stocks", "plus_values_immos", "prets_avances",
]
TypeRetrait = Literal[
    "homogeneisation_methodes", "retraitement_location",
    "reprise_provisions_reg", "frais_etablissement",
    "ecart_conversion", "impots_differes",
]
StatutRun = Literal["brouillon", "en_cours", "calcule", "valide", "publie", "annule"]


# ─────────────────────────────────────────────────────────────────────────────
# GROUPE
# ─────────────────────────────────────────────────────────────────────────────
class ConsolidationGroupCreate(BaseModel):
    code: str = Field(min_length=1, max_length=30)
    libelle: str = Field(min_length=2, max_length=200)
    description: str | None = None
    parent_tenant_id: UUID
    devise_presentation: str = Field("XOF", min_length=3, max_length=3)
    date_cloture: str = Field("12-31", pattern=r"^\d{2}-\d{2}$")
    methode_ecart_acquisition: Literal["goodwill", "capitaux_propres"] = "goodwill"


class ConsolidationGroupUpdate(BaseModel):
    libelle: str | None = None
    description: str | None = None
    devise_presentation: str | None = Field(None, min_length=3, max_length=3)
    date_cloture: str | None = Field(None, pattern=r"^\d{2}-\d{2}$")
    methode_ecart_acquisition: Literal["goodwill", "capitaux_propres"] | None = None
    actif: bool | None = None


class ConsolidationGroupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    code: str
    libelle: str
    description: str | None
    parent_tenant_id: UUID
    devise_presentation: str
    date_cloture: str
    methode_ecart_acquisition: str
    actif: bool
    created_at: datetime


# ─────────────────────────────────────────────────────────────────────────────
# SOCIÉTÉ MEMBRE
# ─────────────────────────────────────────────────────────────────────────────
class GroupCompanyCreate(BaseModel):
    code: str = Field(min_length=1, max_length=30)
    libelle: str = Field(min_length=2, max_length=200)
    tenant_id: UUID
    societe_mere_id: UUID | None = None
    pourcentage_controle: float = Field(100.0, ge=0.0, le=100.0)
    pourcentage_interet: float = Field(100.0, ge=0.0, le=100.0)
    methode: MethodeCons
    date_entree: date
    date_sortie: date | None = None
    devise_comptable: str = Field("XOF", min_length=3, max_length=3)


class GroupCompanyUpdate(BaseModel):
    libelle: str | None = None
    pourcentage_controle: float | None = Field(None, ge=0.0, le=100.0)
    pourcentage_interet: float | None = Field(None, ge=0.0, le=100.0)
    methode: MethodeCons | None = None
    date_sortie: date | None = None
    statut: str | None = None


class GroupCompanyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    group_id: UUID
    tenant_id: UUID
    code: str
    libelle: str
    societe_mere_id: UUID | None
    pourcentage_controle: float
    pourcentage_interet: float
    methode: str
    date_entree: date
    date_sortie: date | None
    devise_comptable: str
    statut: str
    created_at: datetime


# ─────────────────────────────────────────────────────────────────────────────
# PÉRIMÈTRE
# ─────────────────────────────────────────────────────────────────────────────
class PerimetreLigne(BaseModel):
    company_id: UUID
    code: str
    libelle: str
    pct_controle: float
    pct_interet: float
    methode: str
    inclus: bool
    raison_exclusion: str | None = None
    date_entree: date
    date_sortie: date | None


class PerimetreOut(BaseModel):
    group_id: UUID
    group_libelle: str
    date_arret: date
    devise_presentation: str
    nb_societes_incluses: int
    nb_societes_exclues: int
    societes: list[PerimetreLigne]
    pct_interet_total: float


# ─────────────────────────────────────────────────────────────────────────────
# TRANSACTIONS INTRAGROUPE
# ─────────────────────────────────────────────────────────────────────────────
class IntercompanyTransactionCreate(BaseModel):
    source_company_id: UUID
    target_company_id: UUID
    type_transaction: str = Field(min_length=2, max_length=40)
    date_transaction: date
    libelle: str = Field(min_length=2, max_length=200)
    montant_ht: int = Field(gt=0)
    devise: str = Field("XOF", min_length=3, max_length=3)
    source_ecriture_id: UUID | None = None
    target_ecriture_id: UUID | None = None


class IntercompanyTransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    group_id: UUID
    tenant_id: UUID
    source_company_id: UUID
    target_company_id: UUID
    type_transaction: str
    date_transaction: date
    libelle: str
    montant_ht: int
    devise: str
    detection_auto: bool
    score_matching: float | None
    eliminee: bool
    created_at: datetime


class DetectionIntercosResult(BaseModel):
    group_id: UUID
    date_debut: date
    date_fin: date
    nb_detectees: int
    nb_creances_dettes: int
    nb_produits_charges: int
    nb_dividendes: int
    montant_total: int
    details: list[dict[str, Any]]


# ─────────────────────────────────────────────────────────────────────────────
# ÉLIMINATIONS
# ─────────────────────────────────────────────────────────────────────────────
class EliminationCreate(BaseModel):
    type_elimination: TypeElim
    date_elimination: date
    libelle: str = Field(min_length=2, max_length=200)
    montant: int = Field(gt=0)
    lignes: list[dict[str, Any]] = Field(min_length=2)
    section_elimination: str = "groupe"


class EliminationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    group_id: UUID
    reference: str
    type_elimination: str
    date_elimination: date
    libelle: str
    montant: int
    lignes: list[dict[str, Any]]
    appliquee: bool
    appliquee_at: datetime | None
    created_at: datetime


class EliminationAutoRequest(BaseModel):
    date_debut: date
    date_fin: date
    types: list[TypeElim] = Field(
        default_factory=lambda: ["creances_dettes", "produits_charges", "dividendes"]
    )


class EliminationAutoResult(BaseModel):
    group_id: UUID
    nb_eliminations: int
    montant_total_elimine: int
    by_type: dict[str, dict[str, int]]   # {type: {count, montant}}


# ─────────────────────────────────────────────────────────────────────────────
# RETRAITEMENTS
# ─────────────────────────────────────────────────────────────────────────────
class AdjustmentCreate(BaseModel):
    company_id: UUID
    type_retraitement: TypeRetrait
    date_retraitement: date
    libelle: str = Field(min_length=2, max_length=200)
    montant: int = Field(gt=0)
    sens: Literal["debit", "credit"]
    lignes: list[dict[str, Any]] = Field(min_length=2)


class AdjustmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    group_id: UUID
    company_id: UUID
    reference: str
    type_retraitement: str
    date_retraitement: date
    libelle: str
    montant: int
    sens: str
    lignes: list[dict[str, Any]]
    appliquee: bool
    created_at: datetime


# ─────────────────────────────────────────────────────────────────────────────
# EXÉCUTION DE CONSOLIDATION
# ─────────────────────────────────────────────────────────────────────────────
class ConsolidationRunRequest(BaseModel):
    date_debut: date
    date_fin: date
    appliquer_eliminations: bool = True
    appliquer_retraitements: bool = True
    convertir_devises: bool = True
    generer_notes: bool = True

    @model_validator(mode="after")
    def coherent(self):
        if self.date_fin <= self.date_debut:
            raise ValueError("date_fin doit être > date_debut")
        return self


class ConsolidationRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    group_id: UUID
    reference: str
    date_debut: date
    date_fin: date
    statut: str
    nb_societes: int
    total_actif_consolide: int
    total_passif_consolide: int
    chiffre_affaires_consolide: int
    resultat_net_part_groupe: int
    resultat_net_part_minoritaires: int
    interets_minoritaires_cp: int
    ecart_acquisition_total: int
    nb_eliminations: int
    nb_retraitements: int
    execute_at: datetime | None
    valide_at: datetime | None
    duree_execution_ms: int | None
    created_at: datetime


class ConsolidationRunDetailOut(ConsolidationRunOut):
    bilan_consolide: dict[str, Any] | None = None
    compte_resultat_consolide: dict[str, Any] | None = None
    tafire_consolide: dict[str, Any] | None = None
    notes_annexes: dict[str, Any] | None = None
    societes_incluses: list[dict[str, Any]] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# COMPTES CONSOLIDÉS
# ─────────────────────────────────────────────────────────────────────────────
class BilanConsolideLigne(BaseModel):
    compte: str
    libelle: str
    montant_brut: int
    eliminations: int
    retraitements: int
    montant_consolide: int
    part_groupe: int
    part_minoritaires: int


class BilanConsolideOut(BaseModel):
    run_id: UUID
    date_fin: date
    devise: str
    actif: dict[str, Any]
    passif: dict[str, Any]
    total_actif: int
    total_passif: int
    equilibre: bool


class CompteResultatConsolideOut(BaseModel):
    run_id: UUID
    date_debut: date
    date_fin: date
    devise: str
    chiffre_affaires: int
    resultat_exploitation: int
    resultat_financier: int
    resultat_avant_impots: int
    impots: int
    resultat_net_ensemble: int
    resultat_net_part_groupe: int
    resultat_net_part_minoritaires: int
    resultat_par_action: float | None = None


class TAFIREConsolideOut(BaseModel):
    run_id: UUID
    date_debut: date
    date_fin: date
    devise: str
    cafg: int          # Capacité d'autofinancement globale
    variations_bfr: int
    flux_investissement: int
    flux_financement: int
    variation_tresorerie: int
    tresorerie_ouverture: int
    tresorerie_cloture: int


# ─────────────────────────────────────────────────────────────────────────────
# NOTES ANNEXES
# ─────────────────────────────────────────────────────────────────────────────
class NoteAnnexeOut(BaseModel):
    numero: str
    titre: str
    contenu: str
    tableaux: list[dict[str, Any]] = Field(default_factory=list)


class NotesAnnexesOut(BaseModel):
    run_id: UUID
    nb_notes: int
    notes: list[NoteAnnexeOut]


# ─────────────────────────────────────────────────────────────────────────────
# INTÉRÊTS MINORITAIRES
# ─────────────────────────────────────────────────────────────────────────────
class MinorityInterestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    date_calcul: date
    pct_interet_groupe: float
    pct_interet_minoritaire: float
    capitaux_propres_filiale: int
    resultat_filiale: int
    interets_minoritaires_cp: int
    interets_minoritaires_resultat: int


# ─────────────────────────────────────────────────────────────────────────────
# DEVISES
# ─────────────────────────────────────────────────────────────────────────────
class ExchangeRateCreate(BaseModel):
    devise_source: str = Field(min_length=3, max_length=3)
    devise_cible: str = Field(min_length=3, max_length=3)
    date_taux: date
    taux_cloture: float = Field(gt=0)
    taux_moyen: float | None = Field(None, gt=0)
    source: Literal["manuel", "bceao", "api"] = "manuel"


class ExchangeRateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    devise_source: str
    devise_cible: str
    date_taux: date
    taux_cloture: float
    taux_moyen: float | None
    source: str
    created_at: datetime
