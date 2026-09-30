"""
Service Analytics — requêtes analytiques temps réel sur ClickHouse.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import clickhouse_connect
from clickhouse_connect.driver.asyncclient import AsyncClient

from app.core.clickhouse_config import clickhouse_settings

logger = logging.getLogger(__name__)


class AnalyticsService:
    """Requêtes analytiques sur ClickHouse."""

    def __init__(self) -> None:
        self._client: AsyncClient | None = None

    async def _get_client(self) -> AsyncClient:
        if self._client is None:
            self._client = await clickhouse_connect.get_async_client(
                host=clickhouse_settings.CLICKHOUSE_HOST,
                port=clickhouse_settings.CLICKHOUSE_PORT,
                username=clickhouse_settings.CLICKHOUSE_USER,
                password=clickhouse_settings.CLICKHOUSE_PASSWORD,
                database=clickhouse_settings.CLICKHOUSE_DATABASE,
                secure=clickhouse_settings.CLICKHOUSE_SECURE,
            )
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.close()
            self._client = None

    # ═════════════════════════════════════════════════════════════════════
    # CA EN TEMPS RÉEL
    # ═════════════════════════════════════════════════════════════════════
    async def ca_temps_reel(self, tenant_id: UUID) -> dict[str, Any]:
        """CA cumulé du jour + heure en cours."""
        client = await self._get_client()
        today = date.today().isoformat()

        result = await client.query(
            """
            SELECT
                toStartOfHour(timestamp) AS heure,
                sum(amount) AS ca
            FROM events_invoices
            WHERE tenant_id = {tenant_id:String}
              AND event_type = 'invoice.created'
              AND toDate(timestamp) = {today:Date}
            GROUP BY heure
            ORDER BY heure
            """,
            parameters={"tenant_id": str(tenant_id), "today": today},
        )

        rows = result.result_rows
        ca_jour = sum(r[1] for r in rows) if rows else 0
        ca_heure = rows[-1][1] if rows else 0

        return {
            "ca_jour_xof": int(ca_jour),
            "ca_heure_xof": int(ca_heure),
            "heures": [
                {"heure": r[0].isoformat(), "montant": int(r[1])}
                for r in rows
            ],
        }

    # ═════════════════════════════════════════════════════════════════════
    # TRÉSORERIE
    # ═════════════════════════════════════════════════════════════════════
    async def tresorerie_temps_reel(self, tenant_id: UUID) -> dict[str, Any]:
        client = await self._get_client()

        result = await client.query(
            """
            SELECT
                provider,
                sumIf(amount, sens = 'credit') AS entrees,
                sumIf(amount, sens = 'debit') AS sorties,
                count() AS nb_transactions
            FROM events_mm_transactions
            WHERE tenant_id = {tenant_id:String}
              AND timestamp >= now() - INTERVAL 24 HOUR
            GROUP BY provider
            """,
            parameters={"tenant_id": str(tenant_id)},
        )

        return {
            "providers": [
                {
                    "provider": r[0],
                    "entrees_xof": int(r[1] or 0),
                    "sorties_xof": int(r[2] or 0),
                    "nb_transactions": int(r[3] or 0),
                }
                for r in result.result_rows
            ],
        }

    # ═════════════════════════════════════════════════════════════════════
    # TOP CLIENTS (temps réel)
    # ═════════════════════════════════════════════════════════════════════
    async def top_clients_temps_reel(
        self, tenant_id: UUID, limite: int = 10
    ) -> list[dict[str, Any]]:
        client = await self._get_client()
        debut_mois = date.today().replace(day=1).isoformat()

        result = await client.query(
            """
            SELECT
                customer_id,
                sum(amount) AS ca,
                count() AS nb_factures
            FROM events_invoices
            WHERE tenant_id = {tenant_id:String}
              AND event_type = 'invoice.created'
              AND toDate(timestamp) >= {debut:Date}
            GROUP BY customer_id
            ORDER BY ca DESC
            LIMIT {limite:UInt32}
            """,
            parameters={
                "tenant_id": str(tenant_id),
                "debut": debut_mois,
                "limite": limite,
            },
        )

        return [
            {
                "customer_id": r[0],
                "ca_xof": int(r[1]),
                "nb_factures": int(r[2]),
            }
            for r in result.result_rows
        ]

    # ═════════════════════════════════════════════════════════════════════
    # ANOMALIES / FRAUDE (temps réel)
    # ═════════════════════════════════════════════════════════════════════
    async def anomalies_recentes(self, tenant_id: UUID) -> list[dict[str, Any]]:
        client = await self._get_client()

        result = await client.query(
            """
            SELECT
                event_id,
                event_type,
                timestamp,
                payload
            FROM events_audit_findings
            WHERE tenant_id = {tenant_id:String}
              AND severite IN ('eleve', 'critique')
              AND timestamp >= now() - INTERVAL 1 HOUR
            ORDER BY timestamp DESC
            LIMIT 50
            """,
            parameters={"tenant_id": str(tenant_id)},
        )

        return [
            {
                "event_id": str(r[0]),
                "event_type": r[1],
                "timestamp": r[2].isoformat(),
                "payload": r[3],
            }
            for r in result.result_rows
        ]

    # ═════════════════════════════════════════════════════════════════════
    # KPI CONSOLIDÉS (dashboard dirigeant)
    # ═════════════════════════════════════════════════════════════════════
    async def kpi_consolides(self, tenant_id: UUID) -> dict[str, Any]:
        """Agrège tous les KPIs temps réel en une seule requête."""
        client = await self._get_client()
        today = date.today().isoformat()

        result = await client.query(
            """
            SELECT
                (SELECT sum(amount) FROM events_invoices
                 WHERE tenant_id = {tid:String}
                   AND event_type = 'invoice.created'
                   AND toDate(timestamp) = {today:Date}) AS ca_jour,

                (SELECT count() FROM events_invoices
                 WHERE tenant_id = {tid:String}
                   AND event_type = 'invoice.created'
                   AND toDate(timestamp) = {today:Date}) AS nb_factures_jour,

                (SELECT sum(amount) FROM events_mm_transactions
                 WHERE tenant_id = {tid:String}
                   AND sens = 'credit'
                   AND timestamp >= now() - INTERVAL 24 HOUR) AS entrees_mm,

                (SELECT count() FROM events_audit_findings
                 WHERE tenant_id = {tid:String}
                   AND severite IN ('eleve', 'critique')
                   AND timestamp >= now() - INTERVAL 24 HOUR) AS anomalies_24h,

                (SELECT count() FROM events_stock_low
                 WHERE tenant_id = {tid:String}
                   AND timestamp >= now() - INTERVAL 24 HOUR) AS ruptures_stock
            """,
            parameters={"tid": str(tenant_id), "today": today},
        )

        row = result.result_rows[0] if result.result_rows else (0, 0, 0, 0, 0)

        return {
            "ca_jour_xof": int(row[0] or 0),
            "nb_factures_jour": int(row[1] or 0),
            "entrees_mm_24h_xof": int(row[2] or 0),
            "anomalies_24h": int(row[3] or 0),
            "ruptures_stock_24h": int(row[4] or 0),
            "calcule_at": datetime.now(timezone.utc).isoformat(),
        }


analytics_service = AnalyticsService()
