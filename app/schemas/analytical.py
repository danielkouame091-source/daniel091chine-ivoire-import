"""DTO Analytique & Budget SYSCOHADA."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

TypeAxe = Literal[
    "centre_cout", "centre_profit", "produit", "projet",
    "region", "client", "canal", "activite",
]
MethodeRepart = Literal["fixe", "prorata_ca", "prorata_charges", "prorata_effectif", "prorata_surface", "manuelle"]
StatutBudg = Literal["brouillon", "soumis", "valide", "actif", "cloture", "revise"]
NatureBudget = Literal["produit", "charge"]


# ─────────────────────────────────────────────────────────────────────────────
# AXES
# ─────────────────────────────────────────────────────────────────────────────
class AnalyticalAxisCreate(BaseModel):
    code: str = Field(min_length=1, max_length=20)
    libelle: str = Field(min_length=2, max_length=200)
    type_axe: TypeAxe
    description: str | None = None
    parent_id: UUID | None = None
    obligatoire: bool = False
    ordre_affichage: int = 0
    couleur: str | None = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")


class AnalyticalAxisUpdate(BaseModel):
    libelle: str | None = None
    description: str | None = None
    obligatoire: bool | None = None
    actif: bool | None = None
    ordre_affichage: int | None = None
    couleur: str | None = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")


class AnalyticalAxisOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    code: str
    libelle: str
    type_axe: str
    description: str | None
    parent_id: UUID | None
    obligatoire: bool
    actif: bool
    ordre_affichage: int
    couleur: str | None
    created_at: datetime


# ─────────────────────────────────────────────────────────────────────────────
# SECTIONS
# ─────────────────────────────────────────────────────────────────────────────
class AnalyticalSectionCreate(BaseModel):
    axis_id: UUID
    code: str = Field(min_length=1, max_length=20)
    libelle: str = Field(min_length=2, max_length=200)
    parent_id: UUID | None = None
    responsable_user_id: UUID | None = None
    lien_client_id: UUID | None = None
    lien_fournisseur_id: UUID | None = None
    lien_article_id: UUID | None = None
    surface_m2: float | None = Field(None, ge=0)
    effectif: int | None = Field(None, ge=0)
    chiffre_affaires_ref: int | None = Field(None, ge=0)


class AnalyticalSectionUpdate(BaseModel):
    libelle: str | None = None
    parent_id: UUID | None = None
    responsable_user_id: UUID | None = None
    surface_m2: float | None = Field(None, ge=0)
    effectif: int | None = Field(None, ge=0)
    chiffre_affaires_ref: int | None = Field(None, ge=0)
    actif: bool | None = None


class AnalyticalSectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    axis_id: UUID
    code: str
    libelle: str
    parent_id: UUID | None
    responsable_user_id: UUID | None
    surface_m2: float | None
    effectif: int | None
    chiffre_affaires_ref: int | None
    actif: bool
    created_at: datetime


# ─────────────────────────────────────────────────────────────────────────────
# CLÉS DE RÉPARTITION
# ─────────────────────────────────────────────────────────────────────────────
class AllocationKeyLineCreate(BaseModel):
    section_id: UUID
    pourcentage: float = Field(ge=0, le=100)
    valeur_base: float | None = Field(None, ge=0)


class AllocationKeyCreate(BaseModel):
    code: str = Field(min_length=1, max_length=20)
    libelle: str = Field(min_length=2, max_length=200)
    methode: MethodeRepart
    axis_id: UUID
    description: str | None = None
    lignes: list[AllocationKeyLineCreate] = Field(min_length=1)

    @model_validator(mode="after")
    def valider_total(self):
        total = sum(l.pourcentage for l in self.lignes)
        if abs(total - 100.0) > 0.01:
            raise ValueError(f"Somme des pourcentages = {total}% (doit être 100%)")
        return self


class AllocationKeyLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    section_id: UUID
    pourcentage: float
    valeur_base: float | None


class AllocationKeyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    code: str
    libelle: str
    methode: str
    axis_id: UUID
    description: str | None
    actif: bool
    created_at: datetime
    lignes: list[AllocationKeyLineOut] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# IMPUTATION ANALYTIQUE
# ─────────────────────────────────────────────────────────────────────────────
class ImputationCreate(BaseModel):
    section_id: UUID
    montant: int
    type_imputation: Literal["directe", "repartie", "manuelle"] = "directe"
    cle_repartition_id: UUID | None = None
    pourcentage: float | None = Field(None, ge=0, le=100)


class ImputationBatchRequest(BaseModel):
    """Impute une ligne d'écriture sur plusieurs sections."""
    ecriture_ligne_id: UUID
    imputations: list[ImputationCreate] = Field(min_length=1)


class ImputationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    ecriture_ligne_id: UUID
    ecriture_id: UUID
    section_id: UUID
    axis_id: UUID
    montant: int
    type_imputation: str
    pourcentage: float | None
    created_at: datetime


# ─────────────────────────────────────────────────────────────────────────────
# BUDGET
# ─────────────────────────────────────────────────────────────────────────────
class BudgetLineCreate(BaseModel):
    compte: str = Field(min_length=2, max_length=10)
    libelle: str = Field(min_length=2, max_length=200)
    nature: NatureBudget
    mois: list[int] = Field(min_length=12, max_length=12, description="12 montants mensuels")
    hypothese: str | None = None


class BudgetCreate(BaseModel):
    code: str = Field(min_length=1, max_length=30)
    libelle: str = Field(min_length=2, max_length=200)
    description: str | None = None
    section_id: UUID | None = None
    annee: int = Field(ge=2020, le=2100)
    date_debut: date
    date_fin: date
    lignes: list[BudgetLineCreate] = Field(min_length=1)

    @model_validator(mode="after")
    def coherent(self):
        if self.date_fin <= self.date_debut:
            raise ValueError("date_fin doit être > date_debut")
        return self


class BudgetLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    compte: str
    libelle: str
    nature: str
    m01: int
    m02: int
    m03: int
    m04: int
    m05: int
    m06: int
    m07: int
    m08: int
    m09: int
    m10: int
    m11: int
    m12: int
    total: int
    hypothese: str | None


class BudgetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    section_id: UUID | None
    code: str
    libelle: str
    description: str | None
    annee: int
    date_debut: date
    date_fin: date
    version: int
    statut: str
    total_produits: int
    total_charges: int
    resultat_prevu: int
    valide_at: datetime | None
    created_at: datetime
    lignes: list[BudgetLineOut] = Field(default_factory=list)


class BudgetValidateRequest(BaseModel):
    commentaire: str | None = None


# ─────────────────────────────────────────────────────────────────────────────
# CONTRÔLE BUDGÉTAIRE
# ─────────────────────────────────────────────────────────────────────────────
class BudgetConsumptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    budget_line_id: UUID
    section_id: UUID | None
    annee: int
    mois: int
    budget_mois: int
    budget_cumule: int
    realise_mois: int
    realise_cumule: int
    ecart_mois: int
    ecart_cumule: int
    consommation_pct: float
    niveau_alerte: str
    projection_fin_annee: int | None
    recalcule_at: datetime | None


class BudgetControlLigne(BaseModel):
    budget_line_id: UUID
    compte: str
    libelle: str
    nature: str
    section_id: UUID | None
    section_libelle: str | None
    budget_annuel: int
    budget_cumule_a_date: int
    realise_cumule: int
    ecart: int
    consommation_pct: float
    niveau_alerte: str
    projection_fin_annee: int


class BudgetControlOut(BaseModel):
    budget_id: UUID
    budget_libelle: str
    annee: int
    mois_arret: int
    total_produits_budget: int
    total_produits_realise: int
    total_charges_budget: int
    total_charges_realise: int
    resultat_budget: int
    resultat_realise: int
    nb_lignes_vigilance: int
    nb_lignes_alerte: int
    nb_lignes_depassement: int
    lignes: list[BudgetControlLigne]


# ─────────────────────────────────────────────────────────────────────────────
# TABLEAUX DE BORD ANALYTIQUES
# ─────────────────────────────────────────────────────────────────────────────
class MargeParSectionLigne(BaseModel):
    section_id: UUID
    section_code: str
    section_libelle: str
    chiffre_affaires: int
    couts_directs: int
    marge_brute: int
    taux_marge_pct: float
    charges_indirectes_reparties: int
    resultat_analytique: int
    taux_rentabilite_pct: float


class MargeParSectionOut(BaseModel):
    tenant_id: UUID
    axis_id: UUID
    axis_libelle: str
    date_debut: date
    date_fin: date
    total_chiffre_affaires: int
    total_couts: int
    total_marge: int
    taux_marge_global_pct: float
    lignes: list[MargeParSectionLigne]


class RentabiliteProduitLigne(BaseModel):
    section_id: UUID
    code_produit: str
    libelle_produit: str
    quantite_vendue: float
    chiffre_affaires: int
    cout_revient: int
    marge_unitaire: int
    marge_totale: int
    taux_marge_pct: float


class RentabiliteProduitOut(BaseModel):
    tenant_id: UUID
    date_debut: date
    date_fin: date
    nb_produits: int
    chiffre_affaires_total: int
    marge_totale: int
    taux_marge_moyen_pct: float
    top_5_rentables: list[RentabiliteProduitLigne]
    bottom_5_rentables: list[RentabiliteProduitLigne]
    lignes: list[RentabiliteProduitLigne]


class RepartitionChargeOut(BaseModel):
    """Simulation : répartition d'une charge selon une clé."""
    cle_id: UUID
    cle_libelle: str
    montant_total: int
    methode: str
    repartitions: list[dict[str, Any]]


# ─────────────────────────────────────────────────────────────────────────────
# RÉSULTAT ANALYTIQUE
# ─────────────────────────────────────────────────────────────────────────────
class ResultatAnalytiqueOut(BaseModel):
    """Résultat analytique SYSCOHADA (compte 98x)."""
    tenant_id: UUID
    date_debut: date
    date_fin: date
    chiffre_affaires: int
    couts_directs: int
    marge_brute: int
    charges_indirectes: int
    resultat_analytique: int
    reconciliation_avec_cg: int      # Doit matcher avec le résultat net de la CG
    ecart_reconciliation: int
    equilibre: bool
