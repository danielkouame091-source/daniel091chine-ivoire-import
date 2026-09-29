"""Endpoints d'administration de l'API publique (côté tenant)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Query

from app.dependencies.auth import CurrentUser, RequireAdminTenant
from app.dependencies.subscription import RequireActiveSubscription
from app.dependencies.tenant import CurrentTenant
from app.dependencies.tenant_db import TenantDBSession
from app.core.public_api_syscohada import TOUS_WEBHOOK_EVENTS
from app.schemas.public_api import (
    ApiClientCreate,
    ApiClientOut,
    ApiClientUpdate,
    ApiKeyCreate,
    ApiKeyCreatedOut,
    ApiKeyOut,
    ApiKeyRevokeIn,
    ApiKeyRotateIn,
    ApiScopeOut,
    ApiUsageLogOut,
    ApiUsageStatsOut,
    WebhookDeliveryOut,
    WebhookEndpointCreate,
    WebhookEndpointCreatedOut,
    WebhookEndpointOut,
    WebhookEndpointStatsOut,
    WebhookEndpointUpdate,
    WebhookEventOut,
    WebhookTestIn,
    WebhookTestOut,
)
from app.services.public_api_service import PublicApiService
from app.services.webhook_dispatch_service import WebhookDispatchService

router = APIRouter()


# ═════════════════════════════════════════════════════════════════════════════
# CATALOGUE
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/scopes", response_model=list[ApiScopeOut])
async def list_scopes(
    current_tenant: CurrentTenant,
    _: RequireAdminTenant,
) -> list[ApiScopeOut]:
    """Liste tous les scopes disponibles pour les clés API."""
    return [ApiScopeOut(**s) for s in PublicApiService.catalogue_scopes()]


@router.get("/webhook-events", response_model=list[WebhookEventOut])
async def list_webhook_events(
    current_tenant: CurrentTenant,
    _: RequireAdminTenant,
) -> list[WebhookEventOut]:
    """Liste tous les événements webhook disponibles."""
    descriptions = {
        "ecriture.created": ("Écriture comptable créée", "comptabilite"),
        "ecriture.validated": ("Écriture comptable validée", "comptabilite"),
        "invoice.created": ("Facture client créée", "ventes"),
        "invoice.validated": ("Facture client validée", "ventes"),
        "invoice.paid": ("Facture client payée", "ventes"),
        "invoice.overdue": ("Facture client en retard", "ventes"),
        "payment.received": ("Encaissement reçu", "tresorerie"),
        "payment.sent": ("Paiement envoyé", "tresorerie"),
        "fne.certified": ("Facture certifiée FNE", "fiscalite"),
        "fne.rejected": ("Facture rejetée FNE", "fiscalite"),
        "stock.low": ("Stock faible", "stocks"),
        "stock.out": ("Rupture de stock", "stocks"),
        "leave.requested": ("Demande de congé", "rh"),
        "leave.approved": ("Congé approuvé", "rh"),
        "payslip.available": ("Bulletin de paie disponible", "rh"),
        "audit.critical": ("Anomalie critique d'audit", "audit"),
        "subscription.expired": ("Abonnement expiré", "abonnement"),
    }
    return [
        WebhookEventOut(
            event_type=e,
            description=descriptions.get(e, ("Événement", "general"))[0],
            categorie=descriptions.get(e, ("Événement", "general"))[1],
        )
        for e in sorted(TOUS_WEBHOOK_EVENTS)
    ]


# ═════════════════════════════════════════════════════════════════════════════
# CLIENTS API
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/clients", response_model=list[ApiClientOut])
async def list_clients(
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    db: TenantDBSession,
    actif_only: bool = Query(True),
) -> list[ApiClientOut]:
    svc = PublicApiService(db, current_tenant.id, current_user.id)
    rows = await svc.lister_clients(actif_only)
    return [ApiClientOut.model_validate(c) for c in rows]


@router.post("/clients", response_model=ApiClientOut, status_code=201)
async def create_client(
    data: ApiClientCreate,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    _: RequireActiveSubscription,
    db: TenantDBSession,
) -> ApiClientOut:
    svc = PublicApiService(db, current_tenant.id, current_user.id)
    c = await svc.creer_client(data)
    return ApiClientOut.model_validate(c)


@router.patch("/clients/{client_id}", response_model=ApiClientOut)
async def update_client(
    client_id: UUID,
    data: ApiClientUpdate,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    _: RequireActiveSubscription,
    db: TenantDBSession,
) -> ApiClientOut:
    svc = PublicApiService(db, current_tenant.id, current_user.id)
    c = await svc.modifier_client(client_id, data)
    return ApiClientOut.model_validate(c)


# ═════════════════════════════════════════════════════════════════════════════
# CLÉS API
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/clients/{client_id}/keys", response_model=list[ApiKeyOut])
async def list_keys(
    client_id: UUID,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    db: TenantDBSession,
    statut: str | None = Query(None),
) -> list[ApiKeyOut]:
    svc = PublicApiService(db, current_tenant.id, current_user.id)
    rows = await svc.lister_cles(client_id, statut)
    return [ApiKeyOut.model_validate(k) for k in rows]


@router.post("/clients/{client_id}/keys", response_model=ApiKeyCreatedOut, status_code=201)
async def create_key(
    client_id: UUID,
    data: ApiKeyCreate,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    _: RequireActiveSubscription,
    db: TenantDBSession,
) -> ApiKeyCreatedOut:
    """Crée une clé API. La clé en clair n'est affichée qu'UNE fois."""
    svc = PublicApiService(db, current_tenant.id, current_user.id)
    api_key, key_plain = await svc.creer_cle(client_id, data)
    return ApiKeyCreatedOut(
        **ApiKeyOut.model_validate(api_key).model_dump(),
        key_plain=key_plain,
    )


@router.post("/keys/{key_id}/revoke", response_model=ApiKeyOut)
async def revoke_key(
    key_id: UUID,
    data: ApiKeyRevokeIn,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    _: RequireActiveSubscription,
    db: TenantDBSession,
) -> ApiKeyOut:
    svc = PublicApiService(db, current_tenant.id, current_user.id)
    k = await svc.revoquer_cle(key_id, data.motif)
    return ApiKeyOut.model_validate(k)


@router.post("/keys/{key_id}/suspend", response_model=ApiKeyOut)
async def suspend_key(
    key_id: UUID,
    motif: str = Query(..., min_length=5),
    current_tenant: CurrentTenant = None,
    current_user: RequireAdminTenant = None,
    db: TenantDBSession = None,
) -> ApiKeyOut:
    svc = PublicApiService(db, current_tenant.id, current_user.id)
    k = await svc.suspendre_cle(key_id, motif)
    return ApiKeyOut.model_validate(k)


@router.post("/keys/{key_id}/reactivate", response_model=ApiKeyOut)
async def reactivate_key(
    key_id: UUID,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    _: RequireActiveSubscription,
    db: TenantDBSession,
) -> ApiKeyOut:
    svc = PublicApiService(db, current_tenant.id, current_user.id)
    k = await svc.reactiver_cle(key_id)
    return ApiKeyOut.model_validate(k)


@router.post("/keys/{key_id}/rotate", response_model=ApiKeyCreatedOut)
async def rotate_key(
    key_id: UUID,
    data: ApiKeyRotateIn,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    _: RequireActiveSubscription,
    db: TenantDBSession,
) -> ApiKeyCreatedOut:
    svc = PublicApiService(db, current_tenant.id, current_user.id)
    nouvelle, _, key_plain = await svc.roter_cle(key_id, data)
    return ApiKeyCreatedOut(
        **ApiKeyOut.model_validate(nouvelle).model_dump(),
        key_plain=key_plain,
    )


# ═════════════════════════════════════════════════════════════════════════════
# WEBHOOKS — ENDPOINTS
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/webhooks", response_model=list[WebhookEndpointOut])
async def list_webhook_endpoints(
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    db: TenantDBSession,
    client_id: UUID | None = Query(None),
    actif_only: bool = Query(True),
) -> list[WebhookEndpointOut]:
    svc = WebhookDispatchService(db, current_tenant.id, current_user.id)
    rows = await svc.lister_endpoints(client_id, actif_only)
    return [WebhookEndpointOut.model_validate(e) for e in rows]


@router.post("/webhooks", response_model=WebhookEndpointCreatedOut, status_code=201)
async def create_webhook_endpoint(
    data: WebhookEndpointCreate,
    client_id: UUID = Query(...),
    current_tenant: CurrentTenant = None,
    current_user: RequireAdminTenant = None,
    _: RequireActiveSubscription = None,
    db: TenantDBSession = None,
) -> WebhookEndpointCreatedOut:
    """Crée un endpoint webhook. Le secret HMAC n'est affiché qu'UNE fois."""
    svc = WebhookDispatchService(db, current_tenant.id, current_user.id)
    endpoint, secret = await svc.creer_endpoint(client_id, data)
    return WebhookEndpointCreatedOut(
        **WebhookEndpointOut.model_validate(endpoint).model_dump(),
        secret_plain=secret,
    )


@router.patch("/webhooks/{endpoint_id}", response_model=WebhookEndpointOut)
async def update_webhook_endpoint(
    endpoint_id: UUID,
    data: WebhookEndpointUpdate,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    _: RequireActiveSubscription,
    db: TenantDBSession,
) -> WebhookEndpointOut:
    svc = WebhookDispatchService(db, current_tenant.id, current_user.id)
    ep = await svc.modifier_endpoint(endpoint_id, data)
    return WebhookEndpointOut.model_validate(ep)


@router.post("/webhooks/{endpoint_id}/regenerate-secret", response_model=WebhookEndpointCreatedOut)
async def regenerate_webhook_secret(
    endpoint_id: UUID,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    _: RequireActiveSubscription,
    db: TenantDBSession,
) -> WebhookEndpointCreatedOut:
    svc = WebhookDispatchService(db, current_tenant.id, current_user.id)
    ep, secret = await svc.regenerer_secret(endpoint_id)
    return WebhookEndpointCreatedOut(
        **WebhookEndpointOut.model_validate(ep).model_dump(),
        secret_plain=secret,
    )


@router.delete("/webhooks/{endpoint_id}", status_code=204)
async def delete_webhook_endpoint(
    endpoint_id: UUID,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    _: RequireActiveSubscription,
    db: TenantDBSession,
) -> None:
    svc = WebhookDispatchService(db, current_tenant.id, current_user.id)
    await svc.supprimer_endpoint(endpoint_id)


@router.post("/webhooks/{endpoint_id}/test", response_model=WebhookTestOut)
async def test_webhook_endpoint(
    endpoint_id: UUID,
    data: WebhookTestIn,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    _: RequireActiveSubscription,
    db: TenantDBSession,
) -> WebhookTestOut:
    svc = WebhookDispatchService(db, current_tenant.id, current_user.id)
    result = await svc.tester_endpoint(endpoint_id, data)
    return WebhookTestOut(**result)


# ═════════════════════════════════════════════════════════════════════════════
# WEBHOOKS — DELIVERIES
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/webhooks/deliveries", response_model=list[WebhookDeliveryOut])
async def list_webhook_deliveries(
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    db: TenantDBSession,
    endpoint_id: UUID | None = Query(None),
    statut: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[WebhookDeliveryOut]:
    svc = WebhookDispatchService(db, current_tenant.id, current_user.id)
    rows = await svc.lister_deliveries(endpoint_id, statut, limit, offset)
    return [WebhookDeliveryOut.model_validate(d) for d in rows]


@router.post("/webhooks/deliveries/{delivery_id}/replay", response_model=WebhookDeliveryOut)
async def replay_webhook_delivery(
    delivery_id: UUID,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    _: RequireActiveSubscription,
    db: TenantDBSession,
) -> WebhookDeliveryOut:
    """Rejoue manuellement une livraison échouée."""
    svc = WebhookDispatchService(db, current_tenant.id, current_user.id)
    d = await svc.rejouer_delivery(delivery_id)
    return WebhookDeliveryOut.model_validate(d)


@router.get("/webhooks/{endpoint_id}/stats", response_model=WebhookEndpointStatsOut)
async def get_webhook_stats(
    endpoint_id: UUID,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    db: TenantDBSession,
    jours: int = Query(30, ge=1, le=365),
) -> WebhookEndpointStatsOut:
    svc = WebhookDispatchService(db, current_tenant.id, current_user.id)
    fin = datetime.now(timezone.utc)
    debut = fin - timedelta(days=jours)
    data = await svc.stats_endpoint(endpoint_id, debut, fin)
    return WebhookEndpointStatsOut(**data)


# ═════════════════════════════════════════════════════════════════════════════
# USAGE
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/usage/logs", response_model=list[ApiUsageLogOut])
async def list_usage_logs(
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    db: TenantDBSession,
    client_id: UUID | None = Query(None),
    statut_http: int | None = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> list[ApiUsageLogOut]:
    svc = PublicApiService(db, current_tenant.id, current_user.id)
    rows = await svc.lister_logs(client_id, statut_http, limit, offset)
    return [ApiUsageLogOut.model_validate(l) for l in rows]


@router.get("/usage/stats/{client_id}", response_model=ApiUsageStatsOut)
async def get_usage_stats(
    client_id: UUID,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    db: TenantDBSession,
    jours: int = Query(30, ge=1, le=365),
) -> ApiUsageStatsOut:
    svc = PublicApiService(db, current_tenant.id, current_user.id)
    fin = datetime.now(timezone.utc)
    debut = fin - timedelta(days=jours)
    data = await svc.stats_usage(client_id, debut, fin)
    return ApiUsageStatsOut(**data)
