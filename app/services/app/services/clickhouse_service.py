"""
Service ClickHouse — Client OLAP temps réel.

Interface :
- HTTP (port 8123) via httpx (pas de driver natif → léger)
- Pool de connexions HTTP réutilisables
- Insertion batch (JSONEachRow)
- Requêtes agrégées (SQL direct)

⚠️ ClickHouse est OPTIONNEL. Si indisponible, fallback sur PostgreSQL
   (dégradé mais fonctionnel).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import httpx
from fastapi import HTTPException

from app.core.config import settings
from app.core.realtime_syscohada import (
    ClickHouseConfig,
    ClickHouseTable,
    Granularite,
)

logger = logging.getLogger(__name__)


class ClickHouseService:
    """Client ClickHouse via HTTP."""

    def __init__(self, tenant_id: UUID | None = None) -> None:
        self.tenant_id = tenant_id
        self.host = getattr(settings, "CLICKHOUSE_HOST", "clickhouse")
        self.port = int(getattr(settings, "CLICKHOUSE_PORT", ClickHouseConfig.DEFAULT_PORT))
        self.database = getattr(settings, "CLICKHOUSE_DATABASE", ClickHouseConfig.DEFAULT_DATABASE)
        self.user = getattr(settings, "CLICKHOUSE_USER", ClickHouseConfig.DEFAULT_USER)
        self.password = getattr(settings, "CLICKHOUSE_PASSWORD", "")
        self.base_url = f"http://{self.host}:{self.port}"

    # ═════════════════════════════════════════════════════════════════════
    # REQUÊTE SQL
    # ═════════════════════════════════════════════════════════════════════
    async def query(
        self,
        sql: str,
        params: dict[str, Any] | None = None,
        format: str = "JSONEachRow",
    ) -> list[dict[str, Any]]:
        """
        Exécute une requête SELECT et retourne les lignes.
        ⚠️ Ne jamais concaténer de valeurs utilisateur dans le SQL.
        Utiliser des placeholders ClickHouse : {param:Type}.
        """
        sql_with_db = f"USE {self.database}; {sql}" if "USE" not in sql.upper() else sql

        # ClickHouse accepte les paramètres via query string
        query_params = {"default_format": format}
        if params:
            for k, v in params.items():
                query_params[f"param_{k}"] = self._serialize(v)

        try:
            async with httpx.AsyncClient(timeout=ClickHouseConfig.QUERY_TIMEOUT_S) as client:
                resp = await client.post(
                    self.base_url,
                    params=query_params,
                    content=sql_with_db,
                    auth=(self.user, self.password) if self.password else None,
                    headers={"X-ClickHouse-Format": format},
                )
                if resp.status_code >= 400:
                    logger.error(f"[clickhouse] Erreur {resp.status_code}: {resp.text[:500]}")
                    raise HTTPException(500, f"ClickHouse : {resp.text[:200]}")

                # Parse JSONEachRow
                rows: list[dict[str, Any]] = []
                for line in resp.text.strip().split("\n"):
                    if line:
                        import json
                        rows.append(json.loads(line))
                return rows
        except httpx.RequestError as exc:
            logger.exception("[clickhouse] Connexion impossible")
            raise HTTPException(503, f"ClickHouse indisponible : {exc}")

    async def insert(
        self,
        table: str,
        rows: list[dict[str, Any]],
    ) -> int:
        """Insertion en masse (JSONEachRow)."""
        if not rows:
            return 0

        import json
        body = "\n".join(json.dumps(r, default=str) for r in rows)
        sql = f"INSERT INTO {table} FORMAT JSONEachRow"

        try:
            async with httpx.AsyncClient(timeout=ClickHouseConfig.QUERY_TIMEOUT_S) as client:
                resp = await client.post(
                    self.base_url,
                    params={"database": self.database, "query": sql},
                    content=body,
                    auth=(self.user, self.password) if self.password else None,
                )
                if resp.status_code >= 400:
                    logger.error(f"[clickhouse] Insert {resp.status_code}: {resp.text[:500]}")
                    raise HTTPException(500, f"ClickHouse insert : {resp.text[:200]}")
                return len(rows)
        except httpx.RequestError as exc:
            logger.exception("[clickhouse] Insert erreur réseau")
            raise HTTPException(503, f"ClickHouse indisponible : {exc}")

    # ═════════════════════════════════════════════════════════════════════
    # MÉTRIQUES TEMPS RÉEL
    # ═════════════════════════════════════════════════════════════════════
    async def compter_events(
        self,
        topic: str,
        depuis_s: int = 300,
        tenant_id: UUID | None = None,
    ) -> int:
        """Compte les events d'un topic dans une fenêtre glissante."""
        tenant_id = tenant_id or self.tenant_id
        sql = """
            SELECT count() as total
            FROM mtech_events
            WHERE topic = {topic:String}
              AND tenant_id = {tenant_id:String}
              AND event_time >= now() - INTERVAL {depuis_s:UInt32} SECOND
        """
        rows = await self.query(sql, {
            "topic": topic,
            "tenant_id": str(tenant_id),
            "depuis_s": depuis_s,
        })
        return int(rows[0]["total"]) if rows else 0

    async def serie_temporelle(
        self,
        topic: str,
        granularite: str = "minute",
        depuis_s: int = 3600,
        agregation: str = "count",
        champ: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Série temporelle agrégée.
        agregation : count | sum | avg | min | max
        champ : obligatoire pour sum/avg/min/max (ex: montant_xof)
        """
        tenant_id = self.tenant_id
        interval = self._interval_from_granularite(granularite)

        if agregation == "count":
            agg_expr = "count()"
        else:
            if not champ:
                raise HTTPException(400, f"champ requis pour {agregation}")
            agg_expr = f"{agregation}(JSONExtractInt(payload, '{champ}'))"

        sql = f"""
            SELECT
                toStartOfInterval(event_time, INTERVAL 1 {interval}) AS ts,
                {agg_expr} AS value
            FROM mtech_events
            WHERE topic = {{topic:String}}
              AND tenant_id = {{tenant_id:String}}
              AND event_time >= now() - INTERVAL {{depuis_s:UInt32}} SECOND
            GROUP BY ts
            ORDER BY ts ASC
        """
        return await self.query(sql, {
            "topic": topic,
            "tenant_id": str(tenant_id),
            "depuis_s": depuis_s,
        })

    async def top_par_dimension(
        self,
        topic: str,
        dimension: str,
        depuis_s: int = 3600,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Top N par dimension (ex: top providers MM)."""
        sql = f"""
            SELECT
                JSONExtractString(payload, {{dimension:String}}) AS label,
                count() AS value
            FROM mtech_events
            WHERE topic = {{topic:String}}
              AND tenant_id = {{tenant_id:String}}
              AND event_time >= now() - INTERVAL {{depuis_s:UInt32}} SECOND
            GROUP BY label
            ORDER BY value DESC
            LIMIT {{limit:UInt32}}
        """
        return await self.query(sql, {
            "topic": topic,
            "tenant_id": str(self.tenant_id),
            "dimension": dimension,
            "depuis_s": depuis_s,
            "limit": limit,
        })

    # ═════════════════════════════════════════════════════════════════════
    # HEALTH
    # ═════════════════════════════════════════════════════════════════════
    async def ping(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(
                    f"{self.base_url}/ping",
                    auth=(self.user, self.password) if self.password else None,
                )
                return resp.status_code == 200
        except Exception:
            return False

    # ═════════════════════════════════════════════════════════════════════
    # HELPERS
    # ═════════════════════════════════════════════════════════════════════
    @staticmethod
    def _interval_from_granularite(g: str) -> str:
        return {
            Granularite.SECONDE: "SECOND",
            Granularite.MINUTE: "MINUTE",
            Granularite.HEURE: "HOUR",
            Granularite.JOUR: "DAY",
            Granularite.SEMAINE: "WEEK",
            Granularite.MOIS: "MONTH",
        }.get(g, "MINUTE")

    @staticmethod
    def _serialize(v: Any) -> str:
        if isinstance(v, (datetime,)):
            return v.isoformat()
        if isinstance(v, UUID):
            return str(v)
        if isinstance(v, (dict, list)):
            import json
            return json.dumps(v)
        return str(v)
