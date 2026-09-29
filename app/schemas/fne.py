"""DTO FNE — Facture Normalisée Électronique DGI CI."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

EnvironnementFne = Literal["sandbox", "production"]
StatutFne = Literal["brouillon", "en_attente", "certifiee", "rejetee", "annulee", "expiree", "error"]
TypeDocFne = Literal["invoice", "refund", "proforma", "rne", "bapa", "rapa"]
TemplateFne = Literal["B2B", "B2C", "B2F"]


# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────
class FneConfigCreate(BaseModel):
    ncc: str = Field(min_length=5, max_length=20)
    centre_rattachement: str | None = None
    regime_imposition: str | None = None
    environnement: EnvironnementFne = "sandbox"
    base_url: str | None = None
    api_key: str = Field(min_length=10)
    entity_id: str | None = None
    template_defaut: TemplateFne = "B2F"
    prefixe_reference: str | None = None


class FneConfigUpdate(BaseModel):
    api_key: str | None = None
    base_url: str | None = None
    entity_id: str | None = None
    template_defaut: TemplateFne | None = None
    active: bool | None = None
    seuil_alerte_stickers: int | None = Field(None, ge=0)


class FneConfigOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    ncc: str
    centre_rattachement: str | None
    regime_imposition: str | None
    environnement: str
    base_url: str
    entity_id: str | None
    active: bool
    certification_validee: bool
    date_validation_dgi: date | None
    template_defaut: str
    prefixe_reference: str | None
    created_at: datetime


# ─────────────────────────────────────────────────────────────────────────────
# CERTIFICATION
# ─────────────────────────────────────────────────────────────────────────────
class FneCertificationRequest(BaseModel):
    """Payload de certification d'une facture client."""
    customer_invoice_id: UUID
    template: TemplateFne | None = None   # override du template par défaut


class FneRefundRequest(BaseModel):
    """Payload de certification d'un avoir."""
    credit_note_id: UUID
    fne_invoice_id: UUID                   # ID de la facture d'origine certifiée


class FneCancelRequest(BaseModel):
    motif: str = Field(min_length=5, max_length=200)


class FneInvoiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    customer_invoice_id: UUID
    fne_id: str | None
    fne_reference: str | None
    fne_token: str | None
    qr_code_url: str | None
    fiscal_stamp: str | None
    document_type: str
    template: str
    numero_normalise: str | None
    annee_edition: int
    sequence_annuelle: int | None
    statut: str
    date_soumission: datetime | None
    date_certification: datetime | None
    date_annulation: datetime | None
    nb_tentatives: int
    derniere_erreur: str | None
    balance_sticker_apres: int | None
    created_at: datetime


class FneCertificationResult(BaseModel):
    """Résultat d'une certification."""
    fne_invoice: FneInvoiceOut
    success: bool
    message: str
    balance_stickers_restant: int | None = None
    qr_code_url: str | None = None
    numero_normalise: str | None = None


# ─────────────────────────────────────────────────────────────────────────────
# STICKERS
# ─────────────────────────────────────────────────────────────────────────────
class FneStickerBalanceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    tenant_id: UUID
    balance_fne: int
    balance_rne: int
    balance_total: int
    seuil_alerte: int
    derniere_sync_at: datetime | None
    derniere_consommation_at: datetime | None


class FneStickerAchatRequest(BaseModel):
    """Achat de stickers (hors API — via portail DGI)."""
    nb_fne: int = Field(0, ge=0)
    nb_rne: int = Field(0, ge=0)


class FneStickerAlertOut(BaseModel):
    tenant_id: UUID
    balance_total: int
    seuil_alerte: int
    alerte: bool
    message: str


# ─────────────────────────────────────────────────────────────────────────────
# LOGS API
# ─────────────────────────────────────────────────────────────────────────────
class FneApiLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    fne_invoice_id: UUID | None
    methode: str
    url: str
    statut_http: int | None
    error_code: str | None
    error_message: str | None
    latence_ms: int | None
    tentatives: int
    correlation_id: str | None
    created_at: datetime


# ─────────────────────────────────────────────────────────────────────────────
# ÉVÉNEMENTS
# ─────────────────────────────────────────────────────────────────────────────
class FneEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    fne_invoice_id: UUID
    event_type: str
    payload: dict[str, Any]
    traite: bool
    traite_at: datetime | None
    source: str
    created_at: datetime


class FneWebhookPayload(BaseModel):
    """Payload webhook DGI (si activé)."""
    event_type: str
    fne_reference: str
    fne_id: str | None = None
    statut: str | None = None
    motif_rejet: str | None = None
    timestamp: datetime | None = None
    raw: dict[str, Any] | None = None


# ─────────────────────────────────────────────────────────────────────────────
# STATISTIQUES
# ─────────────────────────────────────────────────────────────────────────────
class FneStatsOut(BaseModel):
    tenant_id: UUID
    nb_factures_certifiees: int
    nb_factures_en_attente: int
    nb_factures_rejetees: int
    nb_avoirs_certifies: int
    stickers_consommes_mois: int
    balance_stickers: int
    taux_succes_pct: float
    latence_moyenne_ms: int | None
    derniere_certification_at: datetime | None


# ─────────────────────────────────────────────────────────────────────────────
# SANTÉ
# ─────────────────────────────────────────────────────────────────────────────
class FneHealthOut(BaseModel):
    api_accessible: bool
    environnement: str
    latence_ms: int | None
    message: str
