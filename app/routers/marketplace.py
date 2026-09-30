"""Endpoints Marketplace — Catalogue, installations, reviews (côté tenant)."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query

from app.dependencies.auth import CurrentUser, RequireAdminTenant
from app.dependencies.subscription import RequireActiveSubscription
from app.dependencies.tenant import CurrentTenant
from app.dependencies.tenant_db import TenantDBSession
from app.schemas.marketplace import (
    ExtensionBriefOut,
    ExtensionDetailOut,
    ExtensionOut,
    ExtensionReviewOut,
    HookExecutionOut,
    InstallationCreateIn,
    InstallationDetailOut,
    InstallationOut,
    InstallationUpdateIn,
    ReviewCreateIn,
    ReviewPublisherResponseIn,
    ReviewReportIn,
)
from app.services.marketplace_service import MarketplaceService

router = APIRouter()


# ═════════════════════════════════════════════════════════════════════════════
# CATALOGUE (public/tenant)
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/extensions", response_model=list[ExtensionBriefOut])
async def list_extensions(
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
    categorie: str | None = Query(None),
    type_extension: str | None = Query(None),
    search: str | None = Query(None),
    epinglees_seulement: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[ExtensionBriefOut]:
    svc = MarketplaceService(db, current_user.id)
    rows, _ = await svc.lister_extensions(
        categorie=categorie,
        type_extension=type_extension,
        search=search,
        epinglees_seulement=epinglees_seulement,
        limit=limit,
        offset=offset,
    )
    return [ExtensionBriefOut.model_validate(e) for e in rows]


@router.get("/extensions/{slug}", response_model=ExtensionDetailOut)
async def get_extension(
    slug: str,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
) -> ExtensionDetailOut:
    svc = MarketplaceService(db, current_user.id)
    ext = await svc.get_extension_by_slug(slug)

    # Récupérer les reviews
    reviews = await svc.lister_avis(ext.id, limit=10)

    out = ExtensionDetailOut.model_validate(ext)
    out.reviews = [ExtensionReviewOut.model_validate(r) for r in reviews]
    return out


@router.get("/extensions/{extension_id}/reviews", response_model=list[ExtensionReviewOut])
async def list_reviews(
    extension_id: UUID,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[ExtensionReviewOut]:
    svc = MarketplaceService(db, current_user.id)
    rows = await svc.lister_avis(extension_id, limit, offset)
    return [ExtensionReviewOut.model_validate(r) for r in rows]


# ═════════════════════════════════════════════════════════════════════════════
# INSTALLATIONS (côté tenant)
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/installations", response_model=list[InstallationOut])
async def list_installations(
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
    statut: str | None = Query(None),
) -> list[InstallationOut]:
    svc = MarketplaceService(db, current_user.id)
    rows = await svc.lister_installations(current_tenant.id, statut)
    return [InstallationOut.model_validate(i) for i in rows]


@router.post("/installations", response_model=InstallationOut, status_code=201)
async def install_extension(
    data: InstallationCreateIn,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    _: RequireActiveSubscription,
    db: TenantDBSession,
) -> InstallationOut:
    svc = MarketplaceService(db, current_user.id)
    inst = await svc.installer(current_tenant.id, data)
    return InstallationOut.model_validate(inst)


@router.patch("/installations/{installation_id}", response_model=InstallationOut)
async def update_installation(
    installation_id: UUID,
    data: InstallationUpdateIn,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    db: TenantDBSession,
) -> InstallationOut:
    svc = MarketplaceService(db, current_user.id)
    inst = await svc.modifier_installation(installation_id, data)
    return InstallationOut.model_validate(inst)


@router.post("/installations/{installation_id}/activer", response_model=InstallationOut)
async def activate_installation(
    installation_id: UUID,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    db: TenantDBSession,
) -> InstallationOut:
    svc = MarketplaceService(db, current_user.id)
    inst = await svc.activer_installation(installation_id)
    return InstallationOut.model_validate(inst)


@router.post("/installations/{installation_id}/desactiver", response_model=InstallationOut)
async def deactivate_installation(
    installation_id: UUID,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    db: TenantDBSession,
    motif: str | None = Query(None),
) -> InstallationOut:
    svc = MarketplaceService(db, current_user.id)
    inst = await svc.desactiver_installation(installation_id, motif)
    return InstallationOut.model_validate(inst)


@router.delete("/installations/{installation_id}", response_model=InstallationOut)
async def uninstall_extension(
    installation_id: UUID,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    db: TenantDBSession,
    motif: str | None = Query(None),
) -> InstallationOut:
    svc = MarketplaceService(db, current_user.id)
    inst = await svc.desinstaller(installation_id, motif)
    return InstallationOut.model_validate(inst)


# ═════════════════════════════════════════════════════════════════════════════
# REVIEWS (côté tenant)
# ═════════════════════════════════════════════════════════════════════════════
@router.post("/extensions/{extension_id}/reviews", response_model=ExtensionReviewOut, status_code=201)
async def create_review(
    extension_id: UUID,
    data: ReviewCreateIn,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
) -> ExtensionReviewOut:
    svc = MarketplaceService(db, current_user.id)
    r = await svc.laisser_avis(current_tenant.id, extension_id, data)
    return ExtensionReviewOut.model_validate(r)


@router.post("/extensions/{extension_id}/signaler", status_code=202)
async def report_extension(
    extension_id: UUID,
    data: ReviewReportIn,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
) -> dict:
    svc = MarketplaceService(db, current_user.id)
    r = await svc.signaler_extension(
        extension_id, data.motif, data.description, current_tenant.id,
    )
    return {"ok": True, "report_id": str(r.id)}


# ═════════════════════════════════════════════════════════════════════════════
# LOGS DES HOOKS (côté tenant)
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/installations/{installation_id}/hooks", response_model=list[HookExecutionOut])
async def list_hook_executions(
    installation_id: UUID,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    db: TenantDBSession,
    limit: int = Query(100, ge=1, le=500),
):
    from sqlalchemy import desc, select
    from app.models.marketplace import HookExecution

    stmt = (
        select(HookExecution)
        .where(
            HookExecution.installation_id == installation_id,
            HookExecution.tenant_id == current_tenant.id,
        )
        .order_by(desc(HookExecution.created_at))
        .limit(limit)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [HookExecutionOut.model_validate(h) for h in rows]
