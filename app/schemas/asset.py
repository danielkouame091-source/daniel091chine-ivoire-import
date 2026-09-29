"""DTO Immobilisations & Amortissements SYSCOHADA."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

MethodeAmort = Literal["lineaire", "degressif", "variable", "accelere"]
StatutImmo = Literal["actif", "totalement_amorti", "cede", "rebute", "en_reevaluation"]
TypeCession = Literal["cession", "rebut", "echange"]


# ─────────────────────────────────────────────────────────────────────────────
# Création
# ─────────────────────────────────────────────────────────────────────────────
class FixedAssetCreate(BaseModel):
    code: str = Field(min_length=1, max_length=30)
    designation: str = Field(min_length=2, max_length=200)
    description: str | None = None
    famille: str = Field(min_length=2, max_length=40)
    localisation: str | None = None
    numero_serie: str | None = None
    fournisseur: str | None = None

    date_acquisition: date
    date_mise_en_service: date
    valeur_origine: int = Field(gt=0)
    valeur_residuelle: int = Field(0, ge=0)

    methode_amortissement: MethodeAmort = "lineaire"
    duree_amortissement_ans: float = Field(gt=0, le=50)

    @model_validator(mode="after")
    def coherent(self):
        if self.date_mise_en_service < self.date_acquisition:
            raise ValueError("Date de mise en service doit être ≥ date d'acquisition")
        if self.valeur_residuelle >= self.valeur_origine:
            raise ValueError("Valeur résiduelle doit être < valeur d'origine")
        return self


class FixedAssetUpdate(BaseModel):
    designation: str | None = None
    description: str | None = None
    localisation: str | None = None
    numero_serie: str | None = None
    fournisseur: str | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Sortie
# ─────────────────────────────────────────────────────────────────────────────
class FixedAssetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    code: str
    designation: str
    description: str | None
    famille: str
    compte: str
    compte_amortissement: str
    localisation: str | None
    numero_serie: str | None
    date_acquisition: date
    date_mise_en_service: date
    valeur_origine: int
    valeur_residuelle: int
    methode_amortissement: str
    duree_amortissement_ans: float
    taux_amortissement: float
    base_amortissable: int
    amortissement_cumule: int
    vnc: int
    statut: str
    totalement_amorti: bool
    created_at: datetime


class DepreciationEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    asset_id: UUID
    exercice: int
    periode_debut: date
    periode_fin: date
    base_amortissement: int
    taux_applique: float
    dotation: int
    amortissement_cumule: int
    vnc_debut: int
    vnc_fin: int
    prorata: float
    comptabilise: bool
    ecriture_id: UUID | None


class AmortissementPlanOut(BaseModel):
    asset_id: UUID
    valeur_origine: int
    valeur_residuelle: int
    base_amortissable: int
    methode: str
    duree_ans: float
    taux: float
    entrees: list[DepreciationEntryOut]


# ─────────────────────────────────────────────────────────────────────────────
# Cession
# ─────────────────────────────────────────────────────────────────────────────
class DisposalCreate(BaseModel):
    asset_id: UUID
    type_cession: TypeCession
    date_cession: date
    motif: str = Field(min_length=2, max_length=200)
    prix_cession_ht: int = Field(0, ge=0)
    taux_tva: float = Field(0.18, ge=0.0, le=1.0)
    acquereur: str | None = None
    reference_piece: str | None = None

    @model_validator(mode="after")
    def coherent(self):
        if self.type_cession == "rebut" and self.prix_cession_ht > 0:
            raise ValueError("Un rebut ne peut avoir de prix de cession")
        return self


class DisposalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    asset_id: UUID
    type_cession: str
    date_cession: date
    motif: str
    valeur_origine: int
    amortissement_cumule: int
    vnc: int
    prix_cession_ht: int
    tva_collectee: int
    prix_cession_ttc: int
    plus_value: int
    moins_value: int
    acquereur: str | None
    ecriture_id: UUID | None


# ─────────────────────────────────────────────────────────────────────────────
# Réévaluation
# ─────────────────────────────────────────────────────────────────────────────
class RevaluationCreate(BaseModel):
    asset_id: UUID
    date_reevaluation: date
    valeur_reevaluee: int = Field(gt=0)
    nouvelle_duree_restante_ans: float | None = Field(None, gt=0)


class RevaluationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    asset_id: UUID
    date_reevaluation: date
    vnc_avant: int
    valeur_reevaluee: int
    ecart: int
    ecriture_id: UUID | None


class RevaluationResultOut(BaseModel):
    revaluation: RevaluationOut
    nouvelle_vnc: int
    nouveau_plan: list[DepreciationEntryOut]


# ─────────────────────────────────────────────────────────────────────────────
# Reporting
# ─────────────────────────────────────────────────────────────────────────────
class DotationExerciceOut(BaseModel):
    exercice: int
    nb_immobilisations: int
    dotation_totale: int
    par_famille: dict[str, int]


class TableauImmobilisationsOut(BaseModel):
    tenant_id: UUID
    date_arret: date
    nb_immobilisations: int
    valeur_origine_totale: int
    amortissement_cumule_total: int
    vnc_totale: int
    par_famille: dict[str, dict[str, int]]
