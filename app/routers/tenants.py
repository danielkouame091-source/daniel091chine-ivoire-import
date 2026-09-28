"""Endpoints tenant (profil entreprise)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.deps import get_db
from app.dependencies.auth import CurrentUser, RequireAdminTenant
from app.dependencies.tenant import CurrentTenant
from app.models.tenant import Tenant
from app.schemas.tenant import TenantOut, TenantUpdate

router = APIRouter()


@router.get("/me", response_model=TenantOut)
async def get_my_tenant(current_tenant: CurrentTenant) -> TenantOut:
    return TenantOut.model_validate(current_tenant)


@router.patch("/me", response_model=TenantOut)
async def update_my_tenant(
    data: TenantUpdate,
    current_user: RequireAdminTenant,
    current_tenant: CurrentTenant,
    db: AsyncSession = Depends(get_db),
) -> TenantOut:
    for field, value in data.model_dump(exclude_unset=True).items():
        if field == "adresse" and value is not None:
            setattr(current_tenant, "adresse", value.model_dump() if hasattr(value, "model_dump") else value)
        else:
            setattr(current_tenant, field, value)
    await db.flush()
    return TenantOut.model_validate(current_tenant)
