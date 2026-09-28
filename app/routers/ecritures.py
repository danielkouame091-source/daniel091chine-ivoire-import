"""Endpoints écritures comptables — partie double SYSCOHADA."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.dependencies.auth import CurrentUser, RequireComptable
from app.dependencies.subscription import RequireActiveSubscription
from app.dependencies.tenant import CurrentTenant
from app.dependencies.tenant_db import TenantDBSession
from app.schemas.common import Page
from app.schemas.ecriture import (
    EcritureCreate,
    EcritureFilter,
    EcritureOut,
    EcritureUpdate,
    LigneOut,
)
from app.services.syscohada_service import SyscohadaService

router = APIRouter()


@router.get("", response_model=Page[EcritureOut])
async def list_ecritures(
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
    date_debut: str | None = None,
    date_fin: str | None = None,
    journal_code: str | None = None,
    compte: str | None = None,
    numero_piece: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> Page[EcritureOut]:
    from datetime import date as _date

    filters = EcritureFilter(
        date_debut=_date.fromisoformat(date_debut) if date_debut else None,
        date_fin=_date.fromisoformat(date_fin) if date_fin else None,
        journal_code=journal_code,
        compte=compte,
        numero_piece=numero_piece,
    )
    svc = SyscohadaService(db, current_tenant.id, current_user.id)
    rows, total = await svc.list(filters, limit=page_size, offset=(page - 1) * page_size)
    return Page(
        items=[EcritureOut.model_validate(e) for e in rows],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=(total + page_size - 1) // page_size,
    )


@router.get("/{ecriture_id}", response_model=EcritureOut)
async def get_ecriture(
    ecriture_id: UUID,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
) -> EcritureOut:
    svc = SyscohadaService(db, current_tenant.id, current_user.id)
    return EcritureOut.model_validate(await svc.get(ecriture_id))


@router.post("", response_model=EcritureOut, status_code=201)
async def create_ecriture(
    data: EcritureCreate,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> EcritureOut:
    svc = SyscohadaService(db, current_tenant.id, current_user.id)
    obj = await svc.create(data)
    return EcritureOut.model_validate(obj)


@router.patch("/{ecriture_id}", response_model=EcritureOut)
async def update_ecriture(
    ecriture_id: UUID,
    data: EcritureUpdate,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> EcritureOut:
    svc = SyscohadaService(db, current_tenant.id, current_user.id)
    return EcritureOut.model_validate(await svc.update(ecriture_id, data))


@router.post("/{ecriture_id}/validate", response_model=EcritureOut)
async def validate_ecriture(
    ecriture_id: UUID,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> EcritureOut:
    svc = SyscohadaService(db, current_tenant.id, current_user.id)
    return EcritureOut.model_validate(await svc.validate(ecriture_id))


@router.post("/lettrer", response_model=dict)
async def lettrer(
    ligne_ids: list[UUID],
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> dict:
    svc = SyscohadaService(db, current_tenant.id, current_user.id)
    code = await svc.lettrer(ligne_ids)
    return {"code_lettrage": code, "nb_lignes": len(ligne_ids)}
