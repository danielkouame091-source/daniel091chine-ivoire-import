"""
WebSocket Analytics — push temps réel vers le client.
Le client reçoit les KPIs toutes les 5 secondes.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.analytics_service import analytics_service

logger = logging.getLogger(__name__)
router = APIRouter()


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[str, list[WebSocket]] = {}

    async def connect(self, tenant_id: str, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.setdefault(tenant_id, []).append(ws)

    def disconnect(self, tenant_id: str, ws: WebSocket) -> None:
        conns = self._connections.get(tenant_id, [])
        if ws in conns:
            conns.remove(ws)

    async def broadcast(self, tenant_id: str, message: dict) -> None:
        dead: list[WebSocket] = []
        for ws in self._connections.get(tenant_id, []):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(tenant_id, ws)


manager = ConnectionManager()


@router.websocket("/ws/analytics/{tenant_id}")
async def analytics_websocket(websocket: WebSocket, tenant_id: str) -> None:
    """
    Stream temps réel des KPIs.
    Le client se connecte à /ws/analytics/{tenant_id}?token=xxx
    """
    # Vérification du token (à adapter selon votre auth)
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4401, reason="Token manquant")
        return

    await manager.connect(tenant_id, websocket)
    logger.info(f"[ws] Client connecté tenant={tenant_id}")

    try:
        while True:
            try:
                kpis = await analytics_service.kpi_consolides(tenant_id)
                await websocket.send_json({
                    "type": "kpi_update",
                    "data": kpis,
                    "server_time": datetime.now(timezone.utc).isoformat(),
                })
            except Exception:
                logger.exception("[ws] Erreur calcul KPI")

            # Attendre le prochain cycle ou un message client
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=5.0)
            except asyncio.TimeoutError:
                pass

    except WebSocketDisconnect:
        manager.disconnect(tenant_id, websocket)
        logger.info(f"[ws] Client déconnecté tenant={tenant_id}")
    except Exception:
        manager.disconnect(tenant_id, websocket)
        logger.exception("[ws] Erreur inattendue")
