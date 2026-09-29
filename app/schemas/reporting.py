"""DTO Reporting & Déclarations Fiscales."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# ─── Salariés ────────────────────────────────────────────────────────────────
class EmployeeCreate(BaseModel):
    matricule: str = Field(min_length=1, max_length=30)
    nom_prenoms: str = Field(min_length=2, max_length=200)
    date_naissance: date | None = None
    numero_cnps: str | None = None
    numero_cmu: str | None = None
    numero_contribuable: str | None = None
    poste: str | None = None
    date_embauche: date
    type_contrat: str = Field("CDI", pattern=r"^(CDI|CDD|Stage|Apprentissage)$")
    situation_familiale: str = Field("celibataire", pattern=r"^(celibataire|marie|divorce|veuf)$")
    nombre_enfants: int = Field(0, ge=0, le=30)
    parts_fiscales: float = Field(1.0, ge=1.0, le=5.0)
    salaire_base_mensuel: int = Field(ge=75_000, le=100_000_000)
    sursalaire: int = Field(0, ge=0)
    primes_fixes: dict[str, int] = Field(default_factory=dict)
    avantages_nature: dict[str, int] = Field(default_factory=dict)
    est_expatrie: bool = False
    taux_at_mp: float = Field(3.0, ge=2.0, le=5.0)


class EmployeeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    matricule: str
    nom_prenoms: str
    poste: str | None
    date_embauche: date
    type_contrat: str
    situation_familiale: str
    nombre_enfants: int
    parts_fiscales: float
    salaire_base_mensuel: int
    est_expatrie: bool
    actif: bool


# ─── Bulletins de paie ───────────────────────────────────────────────────────
class PayslipOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    employee_id: UUID
    periode: str
    date_paie: date
    salaire_brut: int
    salaire_brut_imposable: int
    cnps_salarial: int
    cmu_salarial: int
    its_brut: int
    ricf_reduction: int
    its_net: int
    cnps_patronal: int
    prestations_familiales: int
    accidents_travail: int
    taxe_salaires_patronale: int
    fdfp: int
    contribution_nationale: int
    total_retenues: int
    net_a_payer: int
    cout_employeur: int
    detail_its: dict[str, Any]
    statut: str


class PayslipCalculRequest(BaseModel):
    employee_id: UUID
    periode: str = Field(pattern=r"^\d{4}-\d{2}$")


# ─── Déclarations ────────────────────────────────────────────────────────────
class CnpsDeclarationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    periode_debut: date
    periode_fin: date
    type_periode: str
    masse_salariale_brute: int
    nb_salaries: int
    cnps_patronal: int
    cnps_salarial: int
    prestations_familiales: int
    accidents_travail: int
    cmu_total: int
    total_a_payer: int
    date_echeance: date
    statut: str


class DgiDeclarationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    type_declaration: str
    periode: str
    date_echeance: date
    base_imposable: int
    taux: float | None
    montant_du: int
    credits: int
    montant_net: int
    detail: dict[str, Any]
    statut: str


# ─── États financiers ────────────────────────────────────────────────────────
class FinancialStatementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    exercice_id: UUID
    type_etat: str
    donnees: dict[str, Any]
    total_actif: int | None
    total_passif: int | None
    resultat_net: int | None
    chiffre_affaires: int | None
    valeur_ajoutee: int | None
    statut: str


class BilanOut(BaseModel):
    actif: dict[str, Any]
    passif: dict[str, Any]
    equilibre: bool


class CompteResultatOut(BaseModel):
    chiffre_affaires: int
    marge_commerciale: int
    valeur_ajoutee: int
    ebe: int
    resultat_exploitation: int
    resultat_financier: int
    rao: int
    resultat_hao: int
    resultat_net: int
