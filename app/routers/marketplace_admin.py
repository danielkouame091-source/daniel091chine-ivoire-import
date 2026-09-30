"""Endpoints Marketplace Admin — Modération fondateur."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query

from app.dependencies.founder import FounderUser
from app.dependencies.tenant_db import TenantDBSession
from app.schemas.marketplace import (
    ExtensionBriefOut,
    ExtensionOut,
    MarketplaceDashboardOut,
    PublisherDetailOut,
    PublisherOut,
)
from app.services.marketplace_service import MarketplaceService

router = APIRouter()


# ═════════════════════════════════════════════════════════════════════════════
# DASHBOARD
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/dashboard", response_model=MarketplaceDashboardOut)
async def admin_dashboard(
    _: FounderUser,
    db: TenantDBSession,
) -> MarketplaceDashboardOut:
    svc = MarketplaceService(db)
    data = await svc.dashboard_fondateur()
    return MarketplaceDashboardOut(**data)


# ═════════════════════════════════════════════════════════════════════════════
# PUBLISHERS
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/publishers", response_model=list[PublisherOut])
async def list_publishers(
    _: FounderUser,
    db: TenantDBSession,
    statut: str | None = Query(None),
) -> list[PublisherOut]:
    svc = MarketplaceService(db)
    rows = await svc.lister_publishers(statut)
    return [PublisherOut.model_validate(p) for p in rows]


@router.post("/publishers/{publisher_id}/verifier", response_model=PublisherOut)
async def verify_publisher(
    publisher_id: UUID,
    current_user: FounderUser,
    db: TenantDBSession,
    certification: str = Query("verifie"),
) -> PublisherOut:
    svc = MarketplaceService(db, current_user.id)
    pub = await svc.verifier_publisher(publisher_id, certification)
    return PublisherOut.model_validate(pub)


# ═════════════════════════════════════════════════════════════════════════════
# EXTENSIONS — MODÉRATION
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/extensions", response_model=list[ExtensionOut])
async def list_all_extensions(
    _: FounderUser,
    db: TenantDBSession,
    statut: str | None = Query(None),
) -> list[ExtensionOut]:
    svc = MarketplaceService(db)
    rows, _ = await svc.lister_extensions(statut=statut, limit=500)
    return [ExtensionOut.model_validate(e) for e in rows]


@router.post("/extensions/{extension_id}/approuver", response_model=ExtensionOut)
async def approve_extension(
    extension_id: UUID,
    current_user: FounderUser,
    db: TenantDBSession,
    certification: str | None = Query(None),
) -> ExtensionOut:
    svc = MarketplaceService(db, current_user.id)
    ext = await svc.approuver_extension(extension_id, certification)
    return ExtensionOut.model_validate(ext)


@router.post("/extensions/{extension_id}/rejeter", response_model=ExtensionOut)
async def reject_extension(
    extension_id: UUID,
    current_user: FounderUser,
    db: TenantDBSession,
    motif: str = Query(..., min_length=10),
) -> ExtensionOut:
    svc = MarketplaceService(db, current_user.id)
    ext = await svc.rejeter_extension(extension_id, motif)
    return ExtensionOut.model_validate(ext)
