"""
WebSocket Manager — Diffusion temps réel aux clients connectés.

Architecture :
- In-memory registry des connexions (par tenant + topics)
- Broadcast fanout via Redis Pub/Sub (multi-instance)
- Chaque message est un JSON typé
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import WebSocket

from app.core.realtime_syscohada import WebSocketConfig

logger = logging.getLogger(__name__)


class WebSocketManager:
    """
    Singleton in-memory + Redis Pub/Sub.
    """

    _instance: "WebSocketManager | None" = None

    def __new__(cls) -> "WebSocketManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return

        # tenant_id → list[(websocket, topics)]
        self._connections: dict[str, list[tuple[WebSocket, set[str]]]] = defaultdict(list)
        self._lock = asyncio.Lock()
        self._initialized = True

    # ═════════════════════════════════════════════════════════════════════
    # CONNEXION
    # ═════════════════════════════════════════════════════════════════════
    async def connect(
        self,
        websocket: WebSocket,
        tenant_id: str,
        topics: list[str] | None = None,
    ) -> None:
        await websocket.accept()

        async with self._lock:
            # Quota par tenant
            current = self._connections.get(tenant_id, [])
            if len(current) >= WebSocketConfig.MAX_CONNECTIONS_PER_TENANT:
                await websocket.close(code=4003, reason="Trop de connexions actives")
                return

            self._connections[tenant_id].append((websocket, set(topics or [])))

        logger.info(f"[ws] Tenant {tenant_id} connecté (total {len(self._connections[tenant_id])})")

        # Message de bienvenue
        await self._send(websocket, {
            "type": "subscribed",
            "payload": {"topics": list(topics or [])},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    async def disconnect(self, websocket: WebSocket, tenant_id: str) -> None:
        async with self._lock:
            conns = self._connections.get(tenant_id, [])
            self._connections[tenant_id] = [(ws, t) for ws, t in conns if ws is not websocket]
            if not self._connections[tenant_id]:
                del self._connections[tenant_id]

        logger.info(f"[ws] Tenant {tenant_id} déconnecté")

    # ═════════════════════════════════════════════════════════════════════
    # SUBSCRIPTION
    # ═════════════════════════════════════════════════════════════════════
    async def subscribe(
        self, websocket: WebSocket, tenant_id: str, topics: list[str]
    ) -> None:
        async with self._lock:
            conns = self._connections.get(tenant_id, [])
            for i, (ws, t) in enumerate(conns):
                if ws is websocket:
                    conns[i] = (ws, t | set(topics))
                    break

    async def unsubscribe(
        self, websocket: WebSocket, tenant_id: str, topics: list[str]
    ) -> None:
        async with self._lock:
            conns = self._connections.get(tenant_id, [])
            for i, (ws, t) in enumerate(conns):
                if ws is websocket:
                    conns[i] = (ws, t - set(topics))
                    break

    # ═════════════════════════════════════════════════════════════════════
    # BROADCAST
    # ═════════════════════════════════════════════════════════════════════
    async def broadcast_to_tenant(
        self,
        tenant_id: str,
        message: dict[str, Any],
        topics: list[str] | None = None,
    ) -> int:
        """
        Diffuse un message à toutes les connexions d'un tenant.
        Si topics est fourni, ne diffuse qu'aux connexions abonnées.
        """
        async with self._lock:
            conns = list(self._connections.get(tenant_id, []))

        sent = 0
        dead: list[WebSocket] = []

        for ws, subs in conns:
            # Filtre topics
            if topics and subs and not (subs & set(topics)):
                continue

            try:
                await self._send(ws, message)
                sent += 1
            except Exception:
                dead.append(ws)

        # Nettoyage
        for ws in dead:
            await self.disconnect(ws, tenant_id)

        return sent

    async def broadcast_global(self, message: dict[str, Any]) -> int:
        """Diffuse à tous les tenants (cockpit fondateur)."""
        async with self._lock:
            tenants = list(self._connections.keys())

        total = 0
        for tid in tenants:
            total += await self.broadcast_to_tenant(tid, message)
        return total

    # ═════════════════════════════════════════════════════════════════════
    # REDIS PUB/SUB (multi-instance)
    # ═════════════════════════════════════════════════════════════════════
    async def publish_to_redis(
        self, tenant_id: str, message: dict[str, Any]
    ) -> None:
        """Publie sur Redis pour diffusion multi-instance."""
        try:
            import redis.asyncio as aioredis
            from app.core.config import settings
            r = aioredis.from_url(settings.REDIS_URL)
            channel = f"mtech:ws:{tenant_id}"
            await r.publish(channel, json.dumps(message, default=str))
            await r.aclose()
        except Exception:
            logger.exception("[ws] Échec publish Redis")

    # ═════════════════════════════════════════════════════════════════════
    # STATS
    # ═════════════════════════════════════════════════════════════════════
    async def count_connections(self, tenant_id: str | None = None) -> int:
        async with self._lock:
            if tenant_id:
                return len(self._connections.get(tenant_id, []))
            return sum(len(v) for v in self._connections.values())

    # ═════════════════════════════════════════════════════════════════════
    # HELPERS
    # ═════════════════════════════════════════════════════════════════════
    async def _send(self, ws: WebSocket, message: dict[str, Any]) -> None:
        await ws.send_text(json.dumps(message, default=str))


# Singleton
ws_manager = WebSocketManager()
