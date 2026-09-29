"""DTO API publique & Webhooks sortants."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, HttpUrl, model_validator

TypeClientT = Literal["partenaire", "expert_comptable", "integration_interne", "developpeur", "auditeur"]
EnvAPI = Literal["sandbox", "production"]
StatutCleT = Literal["active", "suspendue", "expiree", "revoquee"]
StatutDeliveryT = Literal["pending", "success", "failed", "retrying", "exhausted", "dlq"]


# ─────────────────────────────────────────────────────────────────────────────
# CLIENT API
# ─────────────────────────────────────────────────────────────────────────────
class ApiClientCreate(BaseModel):
    code: str = Field(min_length=2, max_length=30, pattern=r"^[a-z0-9_-]+$")
    nom: str = Field(min_length=2, max_length=200)
    description: str | None = None
    type_client: TypeClientT
    contact_nom: str | None = None
    contact_email: EmailStr | None = None
    contact_telephone: str | None = None
    organisation: str | None = None
    environnement: EnvAPI = "production"
    webhook_url_racine: str | None = None
    ip_whitelist: list[str] = Field(default_factory=list)
    rate_limit_per_minute: int | None = Field(None, ge=10, le=100_000)
    quota_mensuel: int | None = Field(None, ge=100)


class ApiClientUpdate(BaseModel):
    nom: str | None = None
    description: str | None = None
    contact_nom: str | None = None
    contact_email: EmailStr | None = None
    contact_telephone: str | None = None
    organisation: str | None = None
    webhook_url_racine: str | None = None
    ip_whitelist: list[str] | None = None
    rate_limit_per_minute: int | None = Field(None, ge=10, le=100_000)
    quota_mensuel: int | None = Field(None, ge=100)
    actif: bool | None = None


class ApiClientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    code: str
    nom: str
    description: str | None
    type_client: str
    contact_nom: str | None
    contact_email: str | None
    organisation: str | None
    environnement: str
    ip_whitelist: list[str]
    rate_limit_per_minute: int | None
    quota_mensuel: int | None
    actif: bool
    created_at: datetime


# ─────────────────────────────────────────────────────────────────────────────
# CLÉS API
# ─────────────────────────────────────────────────────────────────────────────
class ApiKeyCreate(BaseModel):
    nom: str = Field(min_length=2, max_length=200)
    scopes: list[str] = Field(min_length=1)
    expire_at: datetime | None = None
    environnement: EnvAPI | None = None   # override du client


class ApiKeyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    api_client_id: UUID
    prefix: str
    nom: str
    scopes: list[str]
    environnement: str
    statut: str
    expire_at: datetime | None
    derniere_utilisation_at: datetime | None
    derniere_utilisation_ip: str | None
    nb_requetes_total: int
    revoquee_at: datetime | None
    created_at: datetime


class ApiKeyCreatedOut(ApiKeyOut):
    """Réponse à la création : inclut la clé en clair UNE SEULE FOIS."""
    key_plain: str = Field(description="⚠️ Ne sera plus jamais affichée. Stockez-la sécurisée.")


class ApiKeyRevokeIn(BaseModel):
    motif: str = Field(min_length=5, max_length=500)


class ApiKeyRotateIn(BaseModel):
    expire_at: datetime | None = None
    grace_period_hours: int = Field(24, ge=0, le=168)


# ─────────────────────────────────────────────────────────────────────────────
# WEBHOOKS
# ─────────────────────────────────────────────────────────────────────────────
class WebhookEndpointCreate(BaseModel):
    nom: str = Field(min_length=2, max_length=200)
    description: str | None = None
    url: HttpUrl
    events: list[str] = Field(min_length=1)
    headers_custom: dict[str, str] = Field(default_factory=dict)


class WebhookEndpointUpdate(BaseModel):
    nom: str | None = None
    description: str | None = None
    url: HttpUrl | None = None
    events: list[str] | None = None
    headers_custom: dict[str, str] | None = None
    actif: bool | None = None


class WebhookEndpointOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    api_client_id: UUID
    nom: str
    description: str | None
    url: str
    events: list[str]
    headers_custom: dict[str, Any]
    actif: bool
    nb_deliveries_total: int
    nb_succes: int
    nb_echecs: int
    derniere_delivery_at: datetime | None
    derniere_delivery_statut: str | None
    dernier_code_http: int | None
    echecs_consecutifs: int
    desactive_auto_at: datetime | None
    created_at: datetime


class WebhookEndpointCreatedOut(WebhookEndpointOut):
    """Inclut le secret HMAC UNE SEULE FOIS."""
    secret_plain: str = Field(description="⚠️ Secret HMAC. Ne sera plus jamais affiché.")


class WebhookDeliveryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    delivery_id: str
    endpoint_id: UUID
    event_type: str
    statut: str
    nb_tentatives: int
    max_tentatives: int
    prochaine_tentative_at: datetime | None
    response_status: int | None
    latence_ms: int | None
    erreur: str | None
    premiere_tentative_at: datetime | None
    derniere_tentative_at: datetime | None
    reussie_at: datetime | None
    created_at: datetime


class WebhookTestIn(BaseModel):
    event_type: str
    payload_custom: dict[str, Any] | None = None


class WebhookTestOut(BaseModel):
    delivery_id: str
    statut: str
    response_status: int | None
    latence_ms: int | None
    erreur: str | None


# ─────────────────────────────────────────────────────────────────────────────
# USAGE & ANALYTICS
# ─────────────────────────────────────────────────────────────────────────────
class ApiUsageLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    methode: str
    endpoint: str
    statut_http: int
    error_code: str | None
    latence_ms: int | None
    ip: str | None
    request_id: str | None
    created_at: datetime


class ApiUsageStatsOut(BaseModel):
    api_client_id: UUID
    periode_debut: datetime
    periode_fin: datetime
    nb_requetes: int
    nb_succes: int
    nb_erreurs_4xx: int
    nb_erreurs_5xx: int
    nb_rate_limited: int
    taux_succes_pct: float
    latence_moyenne_ms: float
    latence_p95_ms: float
    top_endpoints: list[dict[str, Any]]
    repartition_par_statut: dict[str, int]


class WebhookEndpointStatsOut(BaseModel):
    endpoint_id: UUID
    periode_debut: datetime
    periode_fin: datetime
    nb_deliveries: int
    nb_succes: int
    nb_echecs: int
    taux_succes_pct: float
    latence_moyenne_ms: float
    top_events: list[dict[str, Any]]
    derniere_erreur: str | None


# ─────────────────────────────────────────────────────────────────────────────
# OAUTH 2.0
# ─────────────────────────────────────────────────────────────────────────────
class OAuthTokenRequest(BaseModel):
    grant_type: Literal["client_credentials"]
    client_id: str
    client_secret: str
    scope: str | None = None


class OAuthTokenResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int
    scope: str


# ─────────────────────────────────────────────────────────────────────────────
# CATALOGUE
# ─────────────────────────────────────────────────────────────────────────────
class ApiScopeOut(BaseModel):
    scope: str
    description: str
    categorie: str   # read | write | admin


class WebhookEventOut(BaseModel):
    event_type: str
    description: str
    categorie: str
    payload_schema: dict[str, Any] | None = None


# ─────────────────────────────────────────────────────────────────────────────
# IDEMPOTENCE
# ─────────────────────────────────────────────────────────────────────────────
class IdempotencyKeyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    key: str
    endpoint: str
    response_status: int
    expire_at: datetime
    created_at: datetime
