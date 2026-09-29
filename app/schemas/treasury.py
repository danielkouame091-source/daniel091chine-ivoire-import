"""DTO Trésorerie & Rapprochement bancaire SYSCOHADA."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

TypeCompte = Literal["banque", "caisse", "mobile_money", "placement"]
TypeMouvement = Literal["debit", "credit"]
FormatReleve = Literal["csv", "ofx", "mt940", "manuel"]
StatutRappro = Literal["non_rapprochee", "rapprochee_auto", "rapprochee_manuelle", "ecart", "frais_bancaire", "interet"]


# ─────────────────────────────────────────────────────────────────────────────
# COMPTES DE TRÉSORERIE
# ─────────────────────────────────────────────────────────────────────────────
class TreasuryAccountCreate(BaseModel):
    code: str = Field(min_length=1, max_length=20)
    libelle: str = Field(min_length=2, max_length=200)
    type_compte: TypeCompte
    compte_comptable: str = Field(pattern=r"^5\d{5}$")
    banque: str | None = None
    numero_compte: str | None = None
    iban: str | None = None
    bic: str | None = None
    devise: str = Field("XOF", min_length=3, max_length=3)
    compte_principal: bool = False


class TreasuryAccountUpdate(BaseModel):
    libelle: str | None = None
    banque: str | None = None
    numero_compte: str | None = None
    iban: str | None = None
    bic: str | None = None
    compte_principal: bool | None = None
    actif: bool | None = None


class TreasuryAccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    code: str
    libelle: str
    type_compte: str
    compte_comptable: str
    banque: str | None
    numero_compte: str | None
    devise: str
    solde_comptable: int
    solde_dernier_releve: int | None
    date_dernier_releve: date | None
    compte_principal: bool
    actif: bool
    created_at: datetime


# ─────────────────────────────────────────────────────────────────────────────
# IMPORT DE RELEVÉ
# ─────────────────────────────────────────────────────────────────────────────
class BankStatementImportRequest(BaseModel):
    treasury_account_id: UUID
    format: FormatReleve = "csv"
    reference: str | None = None
    # Le fichier lui-même arrive en multipart/form-data


class BankStatementLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    date_operation: date
    date_valeur: date | None
    libelle: str
    reference_banque: str | None
    type_mouvement: str
    montant: int
    categorie: str | None
    statut_rapprochement: str
    ecriture_id: UUID | None
    score_matching: float | None
    rapproche_at: datetime | None


class BankStatementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    treasury_account_id: UUID
    reference: str
    date_debut: date
    date_fin: date
    format_source: str
    fichier_nom: str | None
    solde_ouverture: int
    solde_cloture: int
    nb_lignes: int
    nb_lignes_rapprochees: int
    statut: str
    created_at: datetime


class BankStatementDetailOut(BankStatementOut):
    lignes: list[BankStatementLineOut] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# RAPPROCHEMENT
# ─────────────────────────────────────────────────────────────────────────────
class RapprochementAutoRequest(BaseModel):
    statement_id: UUID
    tolerance_jours: int = Field(3, ge=0, le=30)
    tolerance_montant_pct: float = Field(0.005, ge=0.0, le=0.10)
    seuil_libelle: float = Field(0.65, ge=0.0, le=1.0)
    comptabiliser_frais: bool = Field(True, description="Génère les écritures pour frais/interets bancaires")


class RapprochementManuelRequest(BaseModel):
    statement_line_id: UUID
    ecriture_ligne_id: UUID
    creer_ecriture: bool = False


class CandidatRapprochement(BaseModel):
    ecriture_ligne_id: UUID
    ecriture_id: UUID
    date_ecriture: date
    libelle: str
    montant: int
    sens: str                    # debit | credit
    score: float
    score_date: float
    score_montant: float
    score_libelle: float


class RapprochementAutoResultOut(BaseModel):
    statement_id: UUID
    nb_lignes_total: int
    nb_rapprochees_auto: int
    nb_rapprochees_montant_exact: int
    nb_ecarts: int
    nb_frais_bancaires: int
    nb_interets: int
    detail: list[dict[str, Any]]


class EcartRapprochement(BaseModel):
    statement_line_id: UUID
    date_operation: date
    libelle: str
    montant: int
    type_mouvement: str
    raison: str


class ReconciliationSessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    treasury_account_id: UUID
    statement_id: UUID | None
    reference: str
    date_debut: date
    date_fin: date
    solde_comptable: int
    solde_bancaire: int
    total_credits_non_comptabilises: int
    total_debits_non_comptabilises: int
    total_frais_bancaires: int
    total_interets: int
    ecart: int
    etat: str
    statut: str
    nb_lignes_total: int
    nb_lignes_rapprochees: int
    nb_ecarts: int
    ecarts_detail: list[dict[str, Any]]
    ecriture_regularisation_id: UUID | None
    valide_at: datetime | None
    created_at: datetime


class EtatRapprochementOut(BaseModel):
    """État de rapprochement bancaire formel (document comptable)."""
    reference: str
    date_debut: date
    date_fin: date
    treasury_account_code: str
    treasury_account_libelle: str
    # Partie 1 : solde comptable
    solde_comptable: int
    # Partie 2 : ajustements
    moins_credits_bancaires_non_comptabilises: int
    plus_debits_bancaires_non_comptabilises: int
    moins_frais_bancaires: int
    moins_interets_debiteurs: int
    plus_interets_crediteurs: int
    # Partie 3 : solde ajusté
    solde_comptable_ajuste: int
    # Partie 4 : solde bancaire
    solde_bancaire: int
    # Partie 5 : réconciliation
    ecart: int
    equilibre: bool
    # Lignes non rapprochées
    lignes_comptables_non_rapprochees: list[dict[str, Any]]
    lignes_bancaires_non_rapprochees: list[dict[str, Any]]


# ─────────────────────────────────────────────────────────────────────────────
# TABLEAU DE BORD 13 SEMAINES
# ─────────────────────────────────────────────────────────────────────────────
class CashPositionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    date_snapshot: date
    solde_total: int
    solde_banques: int
    solde_caisses: int
    solde_mobile_money: int
    solde_placements: int
    variation_j1: int
    variation_s1: int
    variation_m1: int
    detail_comptes: list[dict[str, Any]]


class CashForecastWeekOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    semaine_iso: str
    date_debut: date
    date_fin: date
    solde_ouverture: int
    entrees_prevues: int
    sorties_prevues: int
    solde_cloture_prevu: int
    encaissements_clients: int
    paiements_fournisseurs: int
    salaires: int
    impots_taxes: int
    autres_entrees: int
    autres_sorties: int
    fiabilite: str
    alerte_negative: bool
    detail_previsions: list[dict[str, Any]]


class CashDashboard13WeeksOut(BaseModel):
    """Tableau de bord DAF : position + 13 semaines de prévision."""
    date_arret: date
    position_actuelle: CashPositionOut
    semaines: list[CashForecastWeekOut]
    total_entrees_13s: int
    total_sorties_13s: int
    solde_final_13s: int
    premiere_semaine_negative: str | None
    creux_max: int
    resume_ia: str | None
