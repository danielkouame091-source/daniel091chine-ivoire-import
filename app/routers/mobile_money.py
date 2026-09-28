"""Webhooks Mobile Money (Wave, Orange, MTN, Moov) + endpoints de consultation."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.crypto import verify_hmac
from app.db.deps import get_db
from app.dependencies.auth import CurrentUser, RequireComptable
from app.dependencies.subscription import RequireActiveSubscription
from app.dependencies.tenant import CurrentTenant
from app.dependencies.tenant_db import TenantDBSession
from app.models.enums import MMProvider, MMStatut
from app.models.tenant import Tenant
from app.schemas.mobile_money import (
    MmRapprochementIn,
    MmTransactionOut,
)
from app.services.mobile_money_service import MobileMoneyService

router = APIRouter()


# ---------------------------------------------------------------------
# Webhooks (PUBLICS — signature HMAC obligatoire)
# ---------------------------------------------------------------------
async def _resolve_tenant_from_slug(db: AsyncSession, slug: str) -> UUID:
    tenant_id = await db.scalar(select(Tenant.id).where(Tenant.slug == slug))
    if tenant_id is None:
        raise HTTPException(404, "Tenant inconnu")
    return tenant_id


@router.post("/webhooks/mobile-money/{provider}/{tenant_slug}", status_code=202)
async def webhook_mm(
    provider: str,
    tenant_slug: str,
    request: Request,
    x_wave_signature: str | None = Header(default=None),
    x_orange_signature: str | None = Header(default=None),
    x_mtn_signature: str | None = Header(default=None),
    x_moov_signature: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        prov = MMProvider(provider)
    except ValueError:
        raise HTTPException(400, f"Provider inconnu : {provider}")

    secret_map = {
        MMProvider.WAVE: (settings.WAVE_WEBHOOK_SECRET, x_wave_signature),
        MMProvider.ORANGE_MONEY: (settings.ORANGE_WEBHOOK_SECRET, x_orange_signature),
        MMProvider.MTN_MOMO: (settings.MTN_WEBHOOK_SECRET, x_mtn_signature),
        MMProvider.MOOV_MONEY: (settings.MOOV_WEBHOOK_SECRET, x_moov_signature),
    }
    secret, signature = secret_map[prov]
    if not secret or not signature:
        raise HTTPException(401, "Signature manquante")

    raw_body = await request.body()
    if not verify_hmac(raw_body, signature, secret):
        raise HTTPException(401, "Signature invalide")

    payload = await request.json()
    tenant_id = await _resolve_tenant_from_slug(db, tenant_slug)

    svc = MobileMoneyService(db, tenant_id=tenant_id)
    tx = await svc.ingerer(prov, payload, tenant_id=tenant_id)
    return {"ok": True, "id": str(tx.id), "statut": tx.statut_rappro.value}


# ---------------------------------------------------------------------
# Consultation (tenant authentifié)
# ---------------------------------------------------------------------
@router.get("/mm/transactions", response_model=list[MmTransactionOut])
async def list_mm_transactions(
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
    statut: MMStatut | None = None,
    provider: MMProvider | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[MmTransactionOut]:
    svc = MobileMoneyService(db, tenant_id=current_tenant.id)
    rows, _ = await svc.list(statut=statut, provider=provider, limit=limit, offset=offset)
    return [MmTransactionOut.model_validate(t) for t in rows]


@router.post("/mm/transactions/{mm_tx_id}/rapprocher", response_model=MmTransactionOut)
async def rapprocher_mm(
    mm_tx_id: UUID,
    data: MmRapprochementIn,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> MmTransactionOut:
    svc = MobileMoneyService(db, tenant_id=current_tenant.id)
    tx = await svc.rapprocher(mm_tx_id, user_id=current_user.id)
    return MmTransactionOut.model_validate(tx)
