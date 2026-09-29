"""Endpoints FNE — Facture Normalisée Électronique DGI CI."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.dependencies.auth import CurrentUser, RequireAdminTenant, RequireComptable
from app.dependencies.subscription import RequireActiveSubscription
from app.dependencies.tenant import CurrentTenant
from app.dependencies.tenant_db import TenantDBSession
from app.models.fne import FneApiLog, FneConfiguration, FneEvent, FneInvoice, FneStickerBalance
from app.schemas.fne import (
    FneApiLogOut,
    FneCancelRequest,
    FneCertificationRequest,
    FneCertificationResult,
    FneConfigCreate,
    FneConfigOut,
    FneConfigUpdate,
    FneEventOut,
    FneHealthOut,
    FneInvoiceOut,
    FneRefundRequest,
    FneStatsOut,
    FneStickerAlertOut,
    FneStickerBalanceOut,
)
from app.services.fne_service import FneService

router = APIRouter()


# ═════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/config", response_model=FneConfigOut)
async def get_config(
    current_tenant: CurrentTenant,
    _: RequireComptable,
    db: TenantDBSession,
) -> FneConfigOut:
    svc = FneService(db, current_tenant.id, current_tenant.id)
    config = await svc.get_configuration_active()
    return FneConfigOut.model_validate(config)


@router.post("/config", response_model=FneConfigOut, status_code=201)
async def create_config(
    data: FneConfigCreate,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> FneConfigOut:
    svc = FneService(db, current_tenant.id, current_user.id)
    config = await svc.creer_configuration(data)
    return FneConfigOut.model_validate(config)


@router.patch("/config/{config_id}", response_model=FneConfigOut)
async def update_config(
    config_id: UUID,
    data: FneConfigUpdate,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> FneConfigOut:
    svc = FneService(db, current_tenant.id, current_user.id)
    config = await svc.modifier_configuration(config_id, data)
    return FneConfigOut.model_validate(config)


# ═════════════════════════════════════════════════════════════════════════════
# CERTIFICATION
# ═════════════════════════════════════════════════════════════════════════════
@router.post("/certify", response_model=FneCertificationResult, status_code=201)
async def certify_invoice(
    data: FneCertificationRequest,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> FneCertificationResult:
    """Certifie une facture client auprès de la DGI (temps réel)."""
    svc = FneService(db, current_tenant.id, current_user.id)
    return await svc.certifier_facture(data)


@router.post("/refund", response_model=FneCertificationResult, status_code=201)
async def certify_refund(
    data: FneRefundRequest,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> FneCertificationResult:
    """Certifie un avoir lié à une facture déjà certifiée."""
    svc = FneService(db, current_tenant.id, current_user.id)
    return await svc.certifier_avoir(data)


@router.post("/invoices/{fne_invoice_id}/cancel", response_model=FneInvoiceOut)
async def cancel_invoice(
    fne_invoice_id: UUID,
    data: FneCancelRequest,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> FneInvoiceOut:
    """Annule une facture certifiée (avec motif)."""
    svc = FneService(db, current_tenant.id, current_user.id)
    return await svc.annuler_facture(fne_invoice_id, data)


# ═════════════════════════════════════════════════════════════════════════════
# CONSULTATION
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/invoices", response_model=list[FneInvoiceOut])
async def list_fne_invoices(
    current_tenant: CurrentTenant,
    _: RequireComptable,
    db: TenantDBSession,
    statut: str | None = Query(None),
    document_type: str | None = Query(None),
    limit: int = 200,
) -> list[FneInvoiceOut]:
    stmt = select(FneInvoice).where(FneInvoice.tenant_id == current_tenant.id)
    if statut:
        stmt = stmt.where(FneInvoice.statut == statut)
    if document_type:
        stmt = stmt.where(FneInvoice.document_type == document_type)
    stmt = stmt.order_by(FneInvoice.created_at.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [FneInvoiceOut.model_validate(i) for i in rows]


@router.get("/invoices/{fne_invoice_id}", response_model=FneInvoiceOut)
async def get_fne_invoice(
    fne_invoice_id: UUID,
    current_tenant: CurrentTenant,
    _: RequireComptable,
    db: TenantDBSession,
) -> FneInvoiceOut:
    svc = FneService(db, current_tenant.id, current_tenant.id)
    fne = await svc._get_fne_invoice(fne_invoice_id)
    return FneInvoiceOut.model_validate(fne)


# ═════════════════════════════════════════════════════════════════════════════
# STICKERS
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/stickers", response_model=FneStickerBalanceOut)
async def get_sticker_balance(
    current_tenant: CurrentTenant,
    _: RequireComptable,
    db: TenantDBSession,
) -> FneStickerBalanceOut:
    balance = await db.scalar(
        select(FneStickerBalance).where(FneStickerBalance.tenant_id == current_tenant.id)
    )
    if balance is None:
        from fastapi import HTTPException
        raise HTTPException(404, "Aucun solde de stickers enregistré")
    return FneStickerBalanceOut.model_validate(balance)


@router.post("/stickers/sync", response_model=FneStickerBalanceOut)
async def sync_sticker_balance(
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> FneStickerBalanceOut:
    """Synchronise le solde depuis l'API FNE."""
    svc = FneService(db, current_tenant.id, current_user.id)
    return await svc.synchroniser_balance_stickers()


@router.get("/stickers/alert", response_model=FneStickerAlertOut)
async def sticker_alert(
    current_tenant: CurrentTenant,
    _: RequireComptable,
    db: TenantDBSession,
) -> FneStickerAlertOut:
    balance = await db.scalar(
        select(FneStickerBalance).where(FneStickerBalance.tenant_id == current_tenant.id)
    )
    if balance is None:
        return FneStickerAlertOut(
            tenant_id=current_tenant.id, balance_total=0,
            seuil_alerte=50, alerte=True,
            message="Aucun sticker disponible",
        )
    alerte = balance.balance_total <= balance.seuil_alerte
    message = (
        f"⚠️ Solde faible : {balance.balance_total} stickers restants "
        f"(seuil : {balance.seuil_alerte})"
        if alerte else
        f"Solde OK : {balance.balance_total} stickers"
    )
    return FneStickerAlertOut(
        tenant_id=current_tenant.id,
        balance_total=balance.balance_total,
        seuil_alerte=balance.seuil_alerte,
        alerte=alerte,
        message=message,
    )


# ═════════════════════════════════════════════════════════════════════════════
# STATS & LOGS
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/stats", response_model=FneStatsOut)
async def get_stats(
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
) -> FneStatsOut:
    svc = FneService(db, current_tenant.id, current_user.id)
    return await svc.get_stats()


@router.get("/logs", response_model=list[FneApiLogOut])
async def list_logs(
    current_tenant: CurrentTenant,
    _: RequireComptable,
    db: TenantDBSession,
    limit: int = 100,
) -> list[FneApiLogOut]:
    stmt = (
        select(FneApiLog)
        .where(FneApiLog.tenant_id == current_tenant.id)
        .order_by(FneApiLog.created_at.desc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [FneApiLogOut.model_validate(l) for l in rows]


@router.get("/events", response_model=list[FneEventOut])
async def list_events(
    current_tenant: CurrentTenant,
    _: RequireComptable,
    db: TenantDBSession,
    limit: int = 100,
) -> list[FneEventOut]:
    stmt = (
        select(FneEvent)
        .where(FneEvent.tenant_id == current_tenant.id)
        .order_by(FneEvent.created_at.desc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [FneEventOut.model_validate(e) for e in rows]


# ═════════════════════════════════════════════════════════════════════════════
# HEALTH
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/health", response_model=FneHealthOut)
async def health_check(
    current_tenant: CurrentTenant,
    _: RequireComptable,
    db: TenantDBSession,
) -> FneHealthOut:
    try:
        svc = FneService(db, current_tenant.id, current_tenant.id)
        config = await svc.get_configuration_active()
        from app.integrations.fne_client import get_fne_client
        client = get_fne_client(
            base_url=config.base_url, api_key=config.api_key,
            environnement=config.environnement, entity_id=config.entity_id,
        )
        ok = await client.health_check()
        return FneHealthOut(
            api_accessible=ok,
            environnement=config.environnement,
            latence_ms=None,
            message="API FNE accessible" if ok else "API FNE inaccessible",
        )
    except Exception as exc:
        return FneHealthOut(
            api_accessible=False,
            environnement="unknown",
            latence_ms=None,
            message=f"Erreur : {exc}",
        )
