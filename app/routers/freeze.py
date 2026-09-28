"""Endpoints du protocole de gel en cascade — réservés aux admins tenant."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request, status

from app.dependencies.auth import RequireAdminTenant
from app.dependencies.subscription import RequireActiveSubscription
from app.dependencies.tenant import CurrentTenant
from app.dependencies.tenant_db import TenantDBSession
from app.schemas.freeze import (
    FreezeEventOut,
    FreezeRequest,
    FreezeResultOut,
    UnfreezeRequest,
)
from app.services.freeze_service import FreezeService

router = APIRouter()


@router.post("", response_model=FreezeResultOut, status_code=status.HTTP_201_CREATED)
async def geler(
    data: FreezeRequest,
    request: Request,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    _: RequireActiveSubscription,
    db: TenantDBSession,
) -> FreezeResultOut:
    svc = FreezeService(db, current_tenant.id, current_user.id)
    ip = request.client.host if request.client else None
    result = await svc.geler(data, ip=ip)
    return result


@router.post("/{freeze_event_id}/lever", response_model=FreezeEventOut)
async def lever(
    freeze_event_id: UUID,
    data: UnfreezeRequest,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    _: RequireActiveSubscription,
    db: TenantDBSession,
) -> FreezeEventOut:
    svc = FreezeService(db, current_tenant.id, current_user.id)
    event = await svc.lever(freeze_event_id, data.motif_levee)
    return FreezeEventOut.model_validate(event)
