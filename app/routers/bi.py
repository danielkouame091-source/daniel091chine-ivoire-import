"""Endpoints Business Intelligence & Reporting."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.core.bi_syscohada import KPIS_STANDARD
from app.dependencies.auth import CurrentUser, RequireAdminTenant, RequireComptable
from app.dependencies.tenant import CurrentTenant
from app.dependencies.tenant_db import TenantDBSession
from app.models.bi import Dashboard, DashboardWidget, ReportExport, SavedReport
from app.schemas.bi import (
    BIAnalyticsOut,
    DashboardCreate,
    DashboardDetailOut,
    DashboardDuplicateIn,
    DashboardOut,
    DashboardPartageIn,
    DashboardPartageOut,
    DashboardUpdate,
    ExportOut,
    ExportRequestIn,
    KPIResultSetOut,
    KPISnapshotOut,
    KPIStandardOut,
    KPITrendOut,
    KPIValueOut,
    ReportCreate,
    ReportOut,
    ReportRunIn,
    ReportRunOut,
    ReportUpdate,
    WidgetCreate,
    WidgetOut,
    WidgetUpdate,
)
from app.services.bi_kpi_engine import KPIEngine
from app.services.bi_service import BIService

router = APIRouter()


# ═════════════════════════════════════════════════════════════════════════════
# CATALOGUE KPI
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/kpis", response_model=list[KPIStandardOut])
async def list_kpis_catalogue(
    current_tenant: CurrentTenant,
    _: RequireComptable,
) -> list[KPIStandardOut]:
    """Liste tous les KPIs standards disponibles."""
    return [
        KPIStandardOut(
            code=k.code,
            libelle=k.libelle,
            description=k.description,
            source=k.source,
            format_affichage=k.format_affichage,
            unite=k.unite,
        )
        for k in KPIS_STANDARD
    ]


@router.get("/kpis/{kpi_code}/value", response_model=KPIValueOut)
async def get_kpi_value(
    kpi_code: str,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
    date_debut: date | None = Query(None),
    date_fin: date | None = Query(None),
    periode: str | None = Query(None),
    comparer: bool = Query(True),
) -> KPIValueOut:
    """Calcule un KPI individuel."""
    engine = KPIEngine(db, current_tenant.id)
    filtres: dict = {}
    if date_debut:
        filtres["date_debut"] = date_debut
    if date_fin:
        filtres["date_fin"] = date_fin
    if periode:
        filtres["periode"] = periode

    result = await engine.calculer_kpi(kpi_code, filtres, comparer_precedent=comparer)
    return KPIValueOut(**result)


@router.get("/kpis/{kpi_code}/trend", response_model=KPITrendOut)
async def get_kpi_trend(
    kpi_code: str,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
    jours: int = Query(30, ge=1, le=365),
) -> KPITrendOut:
    """Tendance historique d'un KPI sur N jours."""
    engine = KPIEngine(db, current_tenant.id)
    data = await engine.get_tendance(kpi_code, jours)
    return KPITrendOut(**data)


@router.get("/kpis/{kpi_code}/serie", response_model=list[dict])
async def get_kpi_serie(
    kpi_code: str,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
    date_debut: date = Query(...),
    date_fin: date = Query(...),
    granularite: str = Query("month", pattern=r"^(day|week|month|quarter|year)$"),
) -> list[dict]:
    """Série temporelle d'un KPI."""
    engine = KPIEngine(db, current_tenant.id)
    return await engine.calculer_serie_temporelle(
        kpi_code, date_debut, date_fin, granularite,
    )


# ═════════════════════════════════════════════════════════════════════════════
# DASHBOARDS
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/dashboards", response_model=list[DashboardOut])
async def list_dashboards(
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
    categorie: str | None = Query(None),
) -> list[DashboardOut]:
    svc = BIService(db, current_tenant.id, current_user.id)
    role = current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role)
    rows = await svc.lister_dashboards(categorie=categorie, role=role)
    return [DashboardOut.model_validate(d) for d in rows]


@router.post("/dashboards", response_model=DashboardOut, status_code=201)
async def create_dashboard(
    data: DashboardCreate,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    db: TenantDBSession,
) -> DashboardOut:
    svc = BIService(db, current_tenant.id, current_user.id)
    d = await svc.creer_dashboard(data)
    return DashboardOut.model_validate(d)


@router.get("/dashboards/{dashboard_id}", response_model=DashboardDetailOut)
async def get_dashboard(
    dashboard_id: UUID,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
) -> DashboardDetailOut:
    svc = BIService(db, current_tenant.id, current_user.id)
    d = await svc.get_dashboard_detail(dashboard_id)
    widgets = d.__dict__.get("widgets", [])
    out = DashboardDetailOut.model_validate(d)
    out.widgets = [WidgetOut.model_validate(w) for w in widgets]
    return out


@router.patch("/dashboards/{dashboard_id}", response_model=DashboardOut)
async def update_dashboard(
    dashboard_id: UUID,
    data: DashboardUpdate,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    db: TenantDBSession,
) -> DashboardOut:
    svc = BIService(db, current_tenant.id, current_user.id)
    d = await svc.modifier_dashboard(dashboard_id, data)
    return DashboardOut.model_validate(d)


@router.delete("/dashboards/{dashboard_id}", status_code=204)
async
