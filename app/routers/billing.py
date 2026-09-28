"""Endpoints abonnements SaaS."""
from __future__ import annotations

from fastapi import APIRouter

from app.dependencies.auth import CurrentUser, RequireAdminTenant
from app.dependencies.subscription import SubscriptionStatus
from app.dependencies.tenant import CurrentTenant
from app.dependencies.tenant_db import TenantDBSession
from app.schemas.subscription import (
    PlanOut,
    SubscriptionCreate,
    SubscriptionOut,
    SubscriptionRenewIn,
    SubscriptionStatusOut,
)
from app.services.billing_service import BillingService

router = APIRouter()


@router.get("/plans", response_model=list[PlanOut])
async def list_plans(db: TenantDBSession) -> list[PlanOut]:
    svc = BillingService(db, tenant_id=None, user_id=None)  # type: ignore[arg-type]
    plans = await svc.list_plans()
    return [PlanOut.model_validate(p) for p in plans]


@router.get("/status", response_model=SubscriptionStatusOut | None)
async def status(current_status: SubscriptionStatus) -> SubscriptionStatusOut | None:
    return current_status


@router.post("/subscribe", response_model=SubscriptionOut, status_code=201)
async def subscribe(
    data: SubscriptionCreate,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    db: TenantDBSession,
) -> SubscriptionOut:
    svc = BillingService(db, current_tenant.id, current_user.id)
    sub = await svc.create_subscription(data)
    return SubscriptionOut.model_validate(sub)


@router.post("/renew", response_model=SubscriptionOut)
async def renew(
    data: SubscriptionRenewIn,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    db: TenantDBSession,
) -> SubscriptionOut:
    # ⚠️ PAS de guard RequireActiveSubscription : c'est justement l'endpoint
    # qui permet de sortir du mode read-only.
    svc = BillingService(db, current_tenant.id, current_user.id)
    sub = await svc.renew(data)
    return SubscriptionOut.model_validate(sub)
