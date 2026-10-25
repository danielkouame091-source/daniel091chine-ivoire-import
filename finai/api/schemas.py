"""Schémas Pydantic (validation stricte des entrées de l'API)."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, field_validator

from ..accounting.standards import ZONES

CHAMPS_NUMERIQUES = {
    "ventes_marchandises", "achats_marchandises", "var_stock_marchandises", "production_vendue", "production_stockee",
    "production_immobilisee", "achats_matieres", "var_stock_matieres", "autres_achats", "transports",
    "services_exterieurs", "impots_taxes", "charges_personnel", "subventions_exploitation", "autres_produits",
    "autres_charges", "reprises_transferts", "dotations_amort_prov", "produits_financiers", "charges_financieres",
    "produits_hao", "charges_hao", "impot_resultat", "immobilisations_nettes", "stocks", "creances_clients",
    "autres_creances", "tresorerie_actif", "capital_social", "capitaux_propres", "dettes_financieres_lt",
    "dettes_financieres_ct", "dettes_fournisseurs", "dettes_fiscales_sociales", "autres_dettes_ct",
    "tresorerie_passif", "loyers_credit_bail", "frais_dev_actives", "reserve_lifo", "nb_employes",
}


class EtatFinancier(BaseModel):
    """États financiers d'un exercice (montants en unités monétaires locales, charges/produits positifs)."""
    donnees: dict[str, float] = Field(..., description="Champs du schéma interne (voir CHAMPS_NUMERIQUES).")

    @field_validator("donnees")
    @classmethod
    def champs_connus(cls, v: dict[str, float]) -> dict[str, float]:
        inconnus = set(v) - CHAMPS_NUMERIQUES
        if inconnus:
            raise ValueError(f"Champs inconnus : {sorted(inconnus)}")
        if any(x != x or abs(x) > 1e15 for x in v.values()):
            raise ValueError("Valeur non numérique ou démesurée.")
        return v


class DemandeDiagnostic(BaseModel):
    zone: str = "OHADA"
    secteur: str = "Commerce"
    courant: EtatFinancier
    precedent: Optional[EtatFinancier] = None

    @field_validator("zone")
    @classmethod
    def zone_valide(cls, v: str) -> str:
        if v not in ZONES:
            raise ValueError(f"Zone inconnue ; choisir parmi {list(ZONES)}")
        return v


class ChocScenario(BaseModel):
    ventes_pct: float = Field(0.0, gt=-1, le=5)
    prix_achats_pct: float = Field(0.0, gt=-1, le=5)
    personnel_pct: float = Field(0.0, gt=-1, le=5)
    dso_delta: float = Field(0.0, ge=-200, le=200)
    dio_delta: float = Field(0.0, ge=-200, le=200)
    dpo_delta: float = Field(0.0, ge=-200, le=200)
    taux_dette_delta: float = Field(0.0, ge=-0.2, le=0.5)
    dette_supplementaire: float = Field(0.0, ge=0)


class DemandeScenario(BaseModel):
    zone: str = "OHADA"
    courant: EtatFinancier
    choc: ChocScenario


class Transaction(BaseModel):
    fournisseur: str
    compte: str
    montant: float = Field(..., ge=0)
    heure: int = Field(..., ge=0, le=23)
    jour_semaine: int = Field(..., ge=0, le=6)
    utilisateur: str = "NA"
    seuil_approbation: float = Field(500_000.0, gt=0)


class DemandeFraude(BaseModel):
    transactions: list[Transaction] = Field(..., min_length=10, max_length=50_000)


class DemandePrevision(BaseModel):
    flux_hebdomadaires: list[float] = Field(..., min_length=80, max_length=2000)
    date_debut: str = "2020-01-06"
    horizon: int = Field(13, ge=1, le=26)
    modele: str = Field("gb", pattern="^(gb|mlp)$")


class DemandeTexte(BaseModel):
    texte: str = Field(..., min_length=3, max_length=5000)
