"""Outils KPI pour le chatbot."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.analytics_service import analytics_service
from app.services.bi_kpi_engine import KPIEngine
from app.services.tool_registry import Tool, tool_registry


async def _get_kpi(
    db: AsyncSession,
    tenant_id: UUID,
    user_id: UUID,
    kpi_code: str,
    periode: str = "this_month",
) -> dict[str, Any]:
    """Calcule un KPI standard."""
    engine = KPIEngine(db, tenant_id)
    result = await engine.calculer_kpi(kpi_code, {"periode": periode})
    return {"success": True, "kpi": result}


async def _get_realtime_kpis(
    db: AsyncSession,
    tenant_id: UUID,
    user_id: UUID,
) -> dict[str, Any]:
    """KPIs temps réel consolidés."""
    kpis = await analytics_service.kpi_consolides(tenant_id)
    return {"success": True, "kpis": kpis}


async def _top_clients(
    db: AsyncSession,
    tenant_id: UUID,
    user_id: UUID,
    limit: int = 10,
) -> dict[str, Any]:
    """Top clients du mois."""
    data = await analytics_service.top_clients_temps_reel(tenant_id, limit)
    return {"success": True, "clients": data}


# ─── ENREGISTREMENT ─────────────────────────────────────────
tool_registry.register(Tool(
    name="consulter_kpi",
    description="Consulte un KPI financier (CA, trésorerie, marge, résultat, etc.).",
    parameters={
        "type": "object",
        "properties": {
            "kpi_code": {
                "type": "string",
                "enum": [
                    "CA_MENSUEL", "CA_YTD", "TRESORERIE", "MARGE_BRUTE",
                    "RESULTAT_NET", "CREANCES_TOTAL", "DETTES_TOTAL",
                    "NB_FACTURES_MOIS", "FACTURES_RETARD",
                ],
            },
            "periode": {
                "type": "string",
                "enum": ["this_month", "last_month", "this_year", "last_year"],
                "default": "this_month",
            },
        },
        "required": ["kpi_code"],
    },
    handler=_get_kpi,
))

tool_registry.register(Tool(
    name="consulter_kpis_temps_reel",
    description="Récupère tous les KPIs en temps réel (CA jour, trésorerie, anomalies).",
    parameters={"type": "object", "properties": {}},
    handler=_get_realtime_kpis,
))

tool_registry.register(Tool(
    name="top_clients",
    description="Retourne les meilleurs clients du mois par chiffre d'affaires.",
    parameters={
        "type": "object",
        "properties": {"limit": {"type": "integer", "default": 10}},
    },
    handler=_top_clients,
))
