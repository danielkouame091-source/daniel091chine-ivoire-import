"""Endpoints plan comptable SYSCOHADA."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.auth import RequireComptable
from app.dependencies.subscription import RequireActiveSubscription
from app.dependencies.tenant import CurrentTenant
from app.dependencies.tenant_db import TenantDBSession
from app.schemas.plan_comptable import (
    PlanComptableCreate,
    PlanComptableOut,
    PlanComptableUpdate,
)
from app.services.plan_comptable_service import PlanComptableService

router = APIRouter()


@router.get("", response_model=list[PlanComptableOut])
async def list_comptes(
    current_tenant: CurrentTenant,
    _: RequireComptable,
    db: TenantDBSession,
    classe: int | None = Query(default=None, ge=1, le=9),
    actif_only: bool = True,
) -> list[PlanComptableOut]:
    svc = PlanComptableService(db, current_tenant.id)
    rows = await svc.list(classe=classe, actif_only=actif_only)
    return [PlanComptableOut.model_validate(c) for c in rows]


@router.post("", response_model=PlanComptableOut, status_code=201)
async def create_compte(
    data: PlanComptableCreate,
    current_tenant: CurrentTenant,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> PlanComptableOut:
    svc = PlanComptableService(db, current_tenant.id)
    obj = await svc.create(data)
    return PlanComptableOut.model_validate(obj)


@router.patch("/{compte_id}", response_model=PlanComptableOut)
async def update_compte(
    compte_id: UUID,
    data: PlanComptableUpdate,
    current_tenant: CurrentTenant,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> PlanComptableOut:
    svc = PlanComptableService(db, current_tenant.id)
    obj = await svc.update(compte_id, data)
    return PlanComptableOut.model_validate(obj)


@router.post("/import", status_code=200)
async def import_plan(
    current_tenant: CurrentTenant,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
    file: UploadFile = File(..., description="CSV : compte,libelle,type_compte"),
) -> dict:
    content = await file.read()
    svc = PlanComptableService(db, current_tenant.id)
    return await svc.import_csv(content)
