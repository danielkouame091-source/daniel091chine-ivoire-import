"""Endpoints journaux comptables."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from app.dependencies.auth import RequireComptable
from app.dependencies.subscription import RequireActiveSubscription
from app.dependencies.tenant import CurrentTenant
from app.dependencies.tenant_db import TenantDBSession
from app.schemas.journal import JournalCreate, JournalOut, JournalUpdate
from app.services.journal_service import JournalService

router = APIRouter()


@router.get("", response_model=list[JournalOut])
async def list_journaux(
    current_tenant: CurrentTenant,
    _: RequireComptable,
    db: TenantDBSession,
) -> list[JournalOut]:
    svc = JournalService(db, current_tenant.id)
    return [JournalOut.model_validate(j) for j in await svc.list()]


@router.post("", response_model=JournalOut, status_code=201)
async def create_journal(
    data: JournalCreate,
    current_tenant: CurrentTenant,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> JournalOut:
    svc = JournalService(db, current_tenant.id)
    return JournalOut.model_validate(await svc.create(data))


@router.patch("/{journal_id}", response_model=JournalOut)
async def update_journal(
    journal_id: UUID,
    data: JournalUpdate,
    current_tenant: CurrentTenant,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> JournalOut:
    svc = JournalService(db, current_tenant.id)
    return JournalOut.model_validate(await svc.update(journal_id, data))
