"""Endpoints du cockpit fondateur — accès strictement réservé (is_founder + MFA)."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.deps import get_db
from app.dependencies.founder import FounderUser
from app.models.ecriture import Ecriture
from app.models.freeze import FreezeEvent
from app.models.subscription import Subscription
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.freeze import FreezeEventOut
from app.schemas.tenant import TenantBrief
from app.services.audit_service import AuditService

router = APIRouter()


@router.get("/tenants", response_model=list[TenantBrief])
async def list_tenants(
    _: FounderUser,
    db: AsyncSession = Depends(get_db),
) -> list[TenantBrief]:
    rows = (
        await db.execute(
            select(Tenant).where(Tenant.deleted_at.is_(None)).order_by(Tenant.created_at.desc())
        )
    ).scalars().all()
    return [TenantBrief.model_validate(t) for t in rows]


@router.get("/stats")
async def global_stats(
    _: FounderUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    nb_tenants = await db.scalar(select(func.count(Tenant.id)).where(Tenant.deleted_at.is_(None)))
    nb_users = await db.scalar(select(func.count(User.id)).where(User.deleted_at.is_(None)))
    nb_ecritures = await db.scalar(select(func.count(Ecriture.id)))
    nb_freeze_actifs = await db.scalar(
        select(func.count(FreezeEvent.id)).where(FreezeEvent.statut == "actif")
    )
    return {
        "tenants": nb_tenants or 0,
        "users": nb_users or 0,
        "ecritures": nb_ecritures or 0,
        "freeze_actifs": nb_freeze_actifs or 0,
    }


@router.get("/subscriptions/expirations")
async def expirations(
    _: FounderUser,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    from datetime import datetime, timedelta, timezone
    horizon = datetime.now(timezone.utc) + timedelta(days=7)
    rows = (
        await db.execute(
            select(Subscription, Tenant.raison_sociale, Tenant.slug)
            .join(Tenant, Tenant.id == Subscription.tenant_id)
            .where(
                Subscription.statut.in_(["trial", "actif", "impaye"]),
                Subscription.periode_fin <= horizon,
            )
            .order_by(Subscription.periode_fin.asc())
        )
    ).all()
    return [
        {
            "tenant_id": str(s.tenant_id),
            "tenant_slug": slug,
            "raison_sociale": raison,
            "statut": s.statut.value,
            "periode_fin": s.periode_fin.isoformat(),
        }
        for s, raison, slug in rows
    ]


@router.get("/freeze/events", response_model=list[FreezeEventOut])
async def freeze_events(
    _: FounderUser,
    db: AsyncSession = Depends(get_db),
    limit: int = 100,
) -> list[FreezeEventOut]:
    rows = (
        await db.execute(
            select(FreezeEvent).order_by(FreezeEvent.created_at.desc()).limit(limit)
        )
    ).scalars().all()
    return [FreezeEventOut.model_validate(e) for e in rows]


@router.get("/audit/verify/{tenant_id}")
async def verify_audit(
    tenant_id: UUID,
    _: FounderUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    svc = AuditService(db)
    valide, nb = await svc.verify_chain(tenant_id)
    return {"tenant_id": str(tenant_id), "integre": valide, "entrees_verifiees": nb}
