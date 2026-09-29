"""DTO Audit & Contrôle interne."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

CategorieCtrl = Literal[
    "coherence_comptable", "integrite_donnees", "conformite_fiscale",
    "conformite_sociale", "securite_acces", "fraude_detection",
    "performance", "tracabilite",
]
Severite = Literal["info", "low", "medium", "high", "critique"]
StatutFindingT = Literal["nouveau", "en_cours", "resolu", "ignore", "faux_positif", "escalade"]
Frequence = Literal["temps_reel", "quotidien", "hebdomadaire", "mensuel", "annuel", "manuel"]


# ─────────────────────────────────────────────────────────────────────────────
# RÈGLES
# ─────────────────────────────────────────────────────────────────────────────
class AuditRuleCreate(BaseModel):
    code: str = Field(min_length=2, max_length=50)
    libelle: str = Field(min_length=2, max_length=200)
    description: str | None = None
    categorie: CategorieCtrl
    type_regle: str
    severite: Severite = "medium"
    active: bool = True
    frequence: Frequence = "quotidien"
    parametres: dict[str, Any] = Field(default_factory=dict)
    reference_legale: str | None = None
    procedure_resolution: str | None = None


class AuditRuleUpdate(BaseModel):
    libelle: str | None = None
    description: str | None = None
    severite: Severite | None = None
    active: bool | None = None
    frequence: Frequence | None = None
    parametres: dict[str, Any] | None = None
    procedure_resolution: str | None = None


class AuditRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID | None
    code: str
    libelle: str
    description: str | None
    categorie: str
    type_regle: str
    severite: str
    active: bool
    frequence: str
    parametres: dict[str, Any]
    reference_legale: str | None
    procedure_resolution: str | None
    created_at: datetime


# ─────────────────────────────────────────────────────────────────────────────
# RUNS
# ─────────────────────────────────────────────────────────────────────────────
class AuditRunRequest(BaseModel):
    rule_code: str | None = None       # Si absent : toutes les règles actives
    date_debut: date | None = None
    date_fin: date | None = None
    max_findings: int = Field(500, ge=1, le=5000)


class AuditRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    rule_id: UUID
    reference: str
    date_debut: date | None
    date_fin: date | None
    statut: str
    nb_lignes_analysees: int
    nb_findings: int
    severite_max: str | None
    duree_ms: int | None
    declencheur: str
    created_at: datetime


# ─────────────────────────────────────────────────────────────────────────────
# FINDINGS
# ─────────────────────────────────────────────────────────────────────────────
class AuditFindingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    rule_id: UUID
    run_id: UUID | None
    reference: str
    titre: str
    description: str
    severite: str
    ressource_type: str
    ressource_id: UUID | None
    ressource_ref: str | None
    donnees: dict[str, Any]
    recommandation: str | None
    impact_estime: int | None
    statut: str
    assigne_a: UUID | None
    resolu_par: UUID | None
    resolu_at: datetime | None
    commentaire_resolution: str | None
    escalade_fondateur: bool
    escalade_at: datetime | None
    created_at: datetime


class FindingResolveRequest(BaseModel):
    commentaire: str = Field(min_length=10, max_length=2000)
    statut: Literal["resolu", "ignore", "faux_positif"] = "resolu"


class FindingAssignRequest(BaseModel):
    user_id: UUID


class FindingEscalateRequest(BaseModel):
    motif: str = Field(min_length=10, max_length=1000)


# ─────────────────────────────────────────────────────────────────────────────
# AUDIT TRAIL
# ─────────────────────────────────────────────────────────────────────────────
class AuditTrailOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID | None
    user_id: UUID | None
    action: str
    categorie: str
    ressource_type: str
    ressource_id: UUID | None
    ressource_ref: str | None
    ip_address: str | None
    endpoint: str | None
    methode_http: str | None
    request_id: str | None
    avant: dict[str, Any] | None
    apres: dict[str, Any] | None
    succes: bool
    code_erreur: str | None
    hash_courant: str
    created_at: datetime


class AuditTrailFilter(BaseModel):
    user_id: UUID | None = None
    action: str | None = None
    ressource_type: str | None = None
    ressource_id: UUID | None = None
    date_debut: date | None = None
    date_fin: date | None = None
    succes: bool | None = None


class AuditTrailVerifyOut(BaseModel):
    """Résultat de la vérification d'intégrité du hash-chain."""
    tenant_id: UUID
    nb_entrees: int
    integre: bool
    premiere_entree: datetime | None
    derniere_entree: datetime | None
    premiere_alteration: datetime | None


# ─────────────────────────────────────────────────────────────────────────────
# RAPPORT DE CONFORMITÉ
# ─────────────────────────────────────────────────────────────────────────────
class ComplianceCheckResult(BaseModel):
    code: str
    libelle: str
    reference_legale: str
    obligatoire: bool
    statut: str                    # conforme | non_conforme | non_applicable | a_verifier
    preuve: str | None
    derniere_verification: datetime | None
    commentaire: str | None


class ComplianceReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    reference: str
    type_rapport: str
    periode_debut: date
    periode_fin: date
    score_global: float
    score_ohada: float
    score_dgi: float
    score_securite: float
    nb_checks_total: int
    nb_checks_reussis: int
    nb_checks_echoues: int
    nb_checks_non_applicables: int
    detail_checks: list[dict[str, Any]]
    nb_findings_critiques: int
    nb_findings_hauts: int
    resume_ia: str | None
    statut: str
    created_at: datetime


class ComplianceReportRequest(BaseModel):
    type_rapport: Literal["mensuel", "trimestriel", "annuel", "ad_hoc"] = "mensuel"
    periode_debut: date
    periode_fin: date
    generer_resume_ia: bool = True


# ─────────────────────────────────────────────────────────────────────────────
# BENFORD
# ─────────────────────────────────────────────────────────────────────────────
class BenfordAnalysisOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    periode_debut: date
    periode_fin: date
    nb_echantillons: int
    distribution_observee: dict[str, float]
    distribution_attendue: dict[str, float]
    score_conformite: float
    chi_square: float
    conforme: bool
    anomalies: list[dict[str, Any]]
    created_at: datetime


class BenfordAnalysisRequest(BaseModel):
    periode_debut: date
    periode_fin: date
    compte_prefixe: str | None = None       # Filtrer sur certains comptes
    min_montant: int = Field(1000, ge=0)


# ─────────────────────────────────────────────────────────────────────────────
# DASHBOARD AUDIT
# ─────────────────────────────────────────────────────────────────────────────
class AuditDashboardOut(BaseModel):
    tenant_id: UUID
    date_arret: date
    nb_findings_nouveaux: int
    nb_findings_en_cours: int
    nb_findings_critiques: int
    nb_findings_hauts: int
    top_5_regles_declenchantes: list[dict[str, Any]]
    score_conformite_actuel: float
    derniere_execution_at: datetime | None
    derniere_verification_hash_chain: datetime | None
    hash_chain_integre: bool
    tendance_30j: list[dict[str, Any]]


# ─────────────────────────────────────────────────────────────────────────────
# DETECTION FRAUDE
# ─────────────────────────────────────────────────────────────────────────────
class CircularTransactionOut(BaseModel):
    """Détection de transactions circulaires (A → B → A)."""
    cycle: list[dict[str, Any]]
    montant_total: int
    nb_operations: int
    periode_jours: int
    score_suspicion: float


class JustBelowThresholdOut(BaseModel):
    """Transactions juste sous un seuil (ex: 4 999 999 pour un seuil à 5M)."""
    seuil: int
    nb_transactions: int
    montant_total: int
    transactions: list[dict[str, Any]]
    score_suspicion: float
