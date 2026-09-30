"""Endpoints Analytics temps réel (REST)."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.dependencies.auth import CurrentUser, RequireComptable
from app.dependencies.subscription import RequireActiveSubscription
from app.dependencies.tenant import CurrentTenant
from app.services.analytics_service import analytics_service

router = APIRouter()


@router.get("/kpis")
async def get_kpis(
    current_tenant: CurrentTenant,
    current_user: RequireComptable,
) -> dict:
    """KPIs consolidés temps réel."""
    return await analytics_service.kpi_consolides(current_tenant.id)


@router.get("/ca")
async def get_ca_realtime(
    current_tenant: CurrentTenant,
    current_user: RequireComptable,
) -> dict:
    """CA en temps réel (par heure)."""
    return await analytics_service.ca_temps_reel(current_tenant.id)


@router.get("/tresorerie")
async def get_tresorerie(
    current_tenant: CurrentTenant,
    current_user: RequireComptable,
) -> dict:
    """Trésorerie Mobile Money temps réel."""
    return await analytics_service.tresorerie_temps_reel(current_tenant.id)


@router.get("/top-clients")
async def get_top_clients(
    current_tenant: CurrentTenant,
    current_user: RequireComptable,
    limit: int = 10,
) -> list[dict]:
    """Top clients du mois (temps réel)."""
    return await analytics_service.top_clients_temps_reel(current_tenant.id, limit)


@router.get("/anomalies")
async def get_anomalies(
    current_tenant: CurrentTenant,
    current_user: RequireComptable,
) -> list[dict]:
    """Anomalies détectées dans la dernière heure."""
    return await analytics_service.anomalies_recentes(current_tenant.id)
