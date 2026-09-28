"""DTO IA/NLP : suggestions, feedback, prévisions."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import EcritureSource


# ─────────────────────────────────────────────────────────────────────────────
# Suggestions
# ─────────────────────────────────────────────────────────────────────────────
class SuggestionRequest(BaseModel):
    phrase: str = Field(min_length=5, max_length=1000)
    langue: Literal["fr", "dyu", "bci", "en", "nouchi"] = "fr"
    canal: Literal["web", "whatsapp", "api", "import"] = "web"


class LigneProposee(BaseModel):
    compte: str
    libelle: str | None = None
    debit: int = 0
    credit: int = 0


class EcritureProposee(BaseModel):
    numero_piece: str | None = None
    date_ecriture: date
    code_journal: str
    libelle: str
    reference_ext: str | None = None
    lignes: list[LigneProposee] = Field(min_length=2)
    confiance: float = Field(ge=0.0, le=1.0)
    raisonnement: str | None = None


class NlpSuggestionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    phrase_source: str
    langue: str
    source_canal: str
    ecriture_proposee: dict[str, Any]
    confiance: float
    modele_utilise: str | None
    statut: str
    created_at: datetime
    ecriture_id: UUID | None = None


class NlpSuggestionAccept(BaseModel):
    """Payload pour acceptation (optionnel : corrigée par l'utilisateur)."""
    corrigee: dict[str, Any] | None = None
    motif: str | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Feedback / stats
# ─────────────────────────────────────────────────────────────────────────────
class NlpStatsOut(BaseModel):
    total: int
    par_statut: dict[str, int]
    confiance_moyenne: float


# ─────────────────────────────────────────────────────────────────────────────
# Prévision trésorerie
# ─────────────────────────────────────────────────────────────────────────────
class ForecastPoint(BaseModel):
    date: str
    entrant: int
    sortant: int
    solde: int


class ForecastOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    date_calcul: datetime
    horizon_jours: int
    date_debut: date
    date_fin: date
    solde_initial_xof: int
    solde_final_prevu_xof: int
    flux_entrant_prevu_xof: int
    flux_sortant_prevu_xof: int
    jours_historique: int
    fiabilite: str
    methode: str
    courbe_quotidienne: list[dict[str, Any]]
    alerte_tresorerie_negative: bool
    premiere_date_negative: date | None
    creux_max_xof: int | None
    resume_ia: str | None


class ForecastRequest(BaseModel):
    horizon_jours: int = Field(90, ge=30, le=180)


# ─────────────────────────────────────────────────────────────────────────────
# WhatsApp
# ─────────────────────────────────────────────────────────────────────────────
class WhatsAppLinkRequest(BaseModel):
    phone_number: str = Field(pattern=r"^\+?[0-9]{8,15}$")


class WhatsAppLinkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    phone_number: str
    verified: bool
    verification_code: str | None = None
    created_at: datetime


class WhatsAppVerifyRequest(BaseModel):
    phone_number: str
    code: str = Field(min_length=6, max_length=6)
