"""
Endpoints Analytics temps réel + WebSocket.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import (
    APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status,
)

from app.core.realtime_syscohada import (
    DASHBOARDS_TEMPS_REEL,
    KafkaTopic,
    TOUS_TOPICS,
)
from app.core.security import decode_access_token_unsafe
from app.db.session import AsyncSessionLocal
from app.dependencies.auth import CurrentUser, RequireAdminTenant
from app.dependencies.tenant import CurrentTenant
from app.dependencies.tenant_db import TenantDBSession
from app.schemas.realtime import (
    AlertAcquitIn,
    AlertEscalateIn,
    AlertResolveIn,
    AlertRuleCreateIn,
    AlertRuleOut,
    AlertRuleUpdateIn,
    ConsumerLagOut,
    EventPublishIn,
    EventPublishedOut,
    MaterializedViewCreateIn,
    MaterializedViewOut,
    PipelineOut,
    RealtimeAlertOut,
    RealtimeAnalyticsOut,
    RealtimeDashboardOut,
    RealtimeQueryIn,
    RealtimeQueryOut,
    WebSocketMessageOut,
    WebSocketSubscribeIn,
)
from app.services.alert_engine_service import AlertEngineService
from app.services.clickhouse_service import ClickHouseService
from app.services.kafka_producer_service import KafkaProducerService
from app.services.websocket_manager import ws_manager

logger = logging.getLogger(__name__)
router = APIRouter()


# ═════════════════════════════════════════════════════════════════════════════
# PUBLICATION EVENT (interne / API)
# ═════════════════════════════════════════════════════════════════════════════
@router.post("/events", response_model=EventPublishedOut, status_code=202)
async def publish_event(
    data: EventPublishIn,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    db: TenantDBSession,
) -> EventPublishedOut:
    """Publie un événement dans le bus Kafka (interne)."""
    svc = KafkaProducerService(db, current_tenant.id, current_user.id)
    event = await svc.publier(
        topic=data.topic,
        event_type=data.event_type,
        payload=data.payload,
        partition_key=data.partition_key,
    )
    return EventPublishedOut(
        event_id=event.id,
        topic=event.topic,
        partition=None,
        offset=None,
        published=event.published,
    )


# ═════════════════════════════════════════════════════════════════════════════
# ALERT RULES
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/alert-rules", response_model=list[AlertRuleOut])
async def list_alert_rules(
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    db: TenantDBSession,
    active_only: bool = Query(True),
) -> list[AlertRuleOut]:
    svc = AlertEngineService(db, current_tenant.id, current_user.id)
    rows = await svc.lister_regles(active_only)
    return [AlertRuleOut.model_validate(r) for r in rows]


@router.post("/alert-rules", response_model=AlertRuleOut, status_code=201)
async def create_alert_rule(
    data: AlertRuleCreateIn,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    db: TenantDBSession,
) -> AlertRuleOut:
    svc = AlertEngineService(db, current_tenant.id, current_user.id)
    rule = await svc.creer_regle(data)
    return AlertRuleOut.model_validate(rule)


@router.patch("/alert-rules/{rule_id}", response_model=AlertRuleOut)
async def update_alert_rule(
    rule_id: UUID,
    data: AlertRuleUpdateIn,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    db: TenantDBSession,
) -> AlertRuleOut:
    svc = AlertEngineService(db, current_tenant.id, current_user.id)
    rule = await svc.modifier_regle(rule_id, data)
    return AlertRuleOut.model_validate(rule)


# ═════════════════════════════════════════════════════════════════════════════
# ALERTS
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/alerts", response_model=list[RealtimeAlertOut])
async def list_alerts(
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    db: TenantDBSession,
    statut: str | None = Query(None),
    severite: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    svc = AlertEngineService(db, current_tenant.id, current_user.id)
    rows = await svc.lister_alertes(statut, severite, limit, offset)
    return [RealtimeAlertOut.model_validate(a) for a in rows]


@router.post("/alerts/{alert_id}/acquitter", response_model=RealtimeAlertOut)
async def acknowledge_alert(
    alert_id: UUID,
    data: AlertAcquitIn,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    db: TenantDBSession,
) -> RealtimeAlertOut:
    svc = AlertEngineService(db, current_tenant.id, current_user.id)
    a = await svc.acquitter_alerte(alert_id, data.commentaire)
    return RealtimeAlertOut.model_validate(a)


@router.post("/alerts/{alert_id}/resoudre", response_model=RealtimeAlertOut)
async def resolve_alert(
    alert_id: UUID,
    data: AlertResolveIn,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    db: TenantDBSession,
) -> RealtimeAlertOut:
    svc = AlertEngineService(db, current_tenant.id, current_user.id)
    a = await svc.resoudre_alerte(alert_id, data.resolution)
    return RealtimeAlertOut.model_validate(a)


@router.post("/alerts/{alert_id}/escalader", response_model=RealtimeAlertOut)
async def escalate_alert(
    alert_id: UUID,
    data: AlertEscalateIn,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    db: TenantDBSession,
) -> RealtimeAlertOut:
    svc = AlertEngineService(db, current_tenant.id, current_user.id)
    a = await svc.escalader_alerte(alert_id, data.escaladee_a_user_id, data.motif)
    return RealtimeAlertOut.model_validate(a)


# ═════════════════════════════════════════════════════════════════════════════
# QUERY ANALYTICS
# ═════════════════════════════════════════════════════════════════════════════
@router.post("/query", response_model=RealtimeQueryOut)
async def run_realtime_query(
    data: RealtimeQueryIn,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    db: TenantDBSession,
) -> RealtimeQueryOut:
    """Requête analytics en temps réel."""
    import time
    started = time.monotonic()

    ch = ClickHouseService(current_tenant.id)
    try:
        rows = await ch.serie_temporelle(
            topic=data.metric,
            granularite=data.granularite,
            depuis_s=data.depuis_s,
        )
    except HTTPException:
        raise

    points = [
        {
            "timestamp": r["ts"],
            "value": float(r["value"]),
            "labels": {},
        }
        for r in rows
    ]
    valeurs = [p["value"] for p in points] or [0.0]

    return RealtimeQueryOut(
        metric=data.metric,
        granularite=data.granularite,
        depuis_s=data.depuis_s,
        points=points,
        total=sum(valeurs),
        minimum=min(valeurs),
        maximum=max(valeurs),
        moyenne=sum(valeurs) / len(valeurs),
        duree_requete_ms=int((time.monotonic() - started) * 1000),
    )


# ═════════════════════════════════════════════════════════════════════════════
# DASHBOARDS TEMPS RÉEL (préconfigurés)
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/dashboards", response_model=list[dict])
async def list_realtime_dashboards(
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
) -> list[dict]:
    return DASHBOARDS_TEMPS_REEL


@router.get("/dashboards/{code}", response_model=RealtimeDashboardOut)
async def get_realtime_dashboard(
    code: str,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    db: TenantDBSession,
) -> RealtimeDashboardOut:
    """Charge un dashboard temps réel avec ses données."""
    dash = next((d for d in DASHBOARDS_TEMPS_REEL if d["code"] == code), None)
    if dash is None:
        raise HTTPException(404, "Dashboard introuvable")

    data: dict[str, Any] = {}
    ch = ClickHouseService(current_tenant.id)

    try:
        if code == "flux_ventes":
            data["nb_factures_5min"] = await ch.compter_events(
                KafkaTopic.FACTURES_CLIENTS, 300, current_tenant.id
            )
            data["montant_ttc_par_minute"] = await ch.serie_temporelle(
                KafkaTopic.FACTURES_CLIENTS, "minute", 3600, "sum", "total_ttc"
            )

        elif code == "mobile_money":
            data["nb_transactions_5min"] = await ch.compter_events(
                KafkaTopic.MM_TRANSACTIONS, 300, current_tenant.id
            )
            data["repartition_par_provider"] = await ch.top_par_dimension(
                KafkaTopic.MM_TRANSACTIONS, "provider", 3600
            )

        elif code == "alertes_securite":
            from sqlalchemy import func, select
            from app.models.realtime import RealtimeAlert
            data["nb_alertes_actives"] = int(await db.scalar(
                select(func.count(RealtimeAlert.id)).where(
                    RealtimeAlert.tenant_id == current_tenant.id,
                    RealtimeAlert.statut == "active",
                )
            ) or 0)

        elif code == "system_health":
            # Métriques système via ClickHouse
            data["requetes_par_seconde"] = await ch.serie_temporelle(
                KafkaTopic.SYSTEM_METRICS, "minute", 3600
            )

    except HTTPException as exc:
        if exc.status_code == 503:
            data["error"] = "ClickHouse indisponible"

    return RealtimeDashboardOut(
        code=dash["code"],
        nom=dash["nom"],
        description=dash["description"],
        widgets=dash["widgets"],
        data=data,
        refresh_at=datetime.now(timezone.utc),
    )


# ═════════════════════════════════════════════════════════════════════════════
# PIPELINES (monitoring)
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/pipelines", response_model=list[PipelineOut])
async def list_pipelines(
    current_user: RequireAdminTenant,
    db: TenantDBSession,
):
    from sqlalchemy import select
    from app.models.realtime import DataPipeline
    rows = (await db.execute(select(DataPipeline))).scalars().all()
    return [PipelineOut.model_validate(p) for p in rows]


@router.get("/consumer-lags", response_model=list[ConsumerLagOut])
async def list_consumer_lags(
    current_user: RequireAdminTenant,
    db: TenantDBSession,
    limit: int = Query(100, ge=1, le=500),
):
    from sqlalchemy import desc, select
    from app.models.realtime import ConsumerLagSnapshot
    rows = (
        await db.execute(
            select(ConsumerLagSnapshot)
            .order_by(desc(ConsumerLagSnapshot.created_at))
            .limit(limit)
        )
    ).scalars().all()
    return [ConsumerLagOut.model_validate(r) for r in rows]


# ═════════════════════════════════════════════════════════════════════════════
# ANALYTICS FONDATEUR
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/analytics", response_model=RealtimeAnalyticsOut)
async def realtime_analytics(
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    db: TenantDBSession,
) -> RealtimeAnalyticsOut:
    """Vue agrégée analytics temps réel (fondateur)."""
    from sqlalchemy import func, select
    from app.models.realtime import RealtimeAlert

    now = datetime.now(timezone.utc)
    il_y_a_24h = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # Alertes
    nb_alertes_actives = int(await db.scalar(
        select(func.count(RealtimeAlert.id)).where(
            RealtimeAlert.tenant_id == current_tenant.id,
            RealtimeAlert.statut == "active",
        )
    ) or 0)

    nb_alertes_critiques = int(await db.scalar(
        select(func.count(RealtimeAlert.id)).where(
            RealtimeAlert.tenant_id == current_tenant.id,
            RealtimeAlert.statut == "active",
            RealtimeAlert.severite.in_(["critical", "emergency"]),
        )
    ) or 0)

    nb_alertes_24h = int(await db.scalar(
        select(func.count(RealtimeAlert.id)).where(
            RealtimeAlert.tenant_id == current_tenant.id,
            RealtimeAlert.created_at >= il_y_a_24h,
        )
    ) or 0)

    # WebSocket stats
    nb_ws = await ws_manager.count_connections(str(current_tenant.id))

    return RealtimeAnalyticsOut(
        date_arret=now,
        nb_events_24h=0,       # À enrichir via ClickHouse
        nb_events_1h=0,
        events_par_seconde=0.0,
        kafka_lag_total=0,
        kafka_topics_actifs=len(TOUS_TOPICS),
        nb_alertes_actives=nb_alertes_actives,
        nb_alertes_critiques=nb_alertes_critiques,
        nb_alertes_24h=nb_alertes_24h,
        latence_p50_ms=0.0,
        latence_p95_ms=0.0,
        latence_p99_ms=0.0,
        nb_connexions_actives=nb_ws,
        nb_messages_envoyes_24h=0,
        top_topics=[],
        top_tenants=[],
    )


# ═════════════════════════════════════════════════════════════════════════════
# WEBSOCKET
# ═════════════════════════════════════════════════════════════════════════════
@router.websocket("/ws/{tenant_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    tenant_id: str,
    token: str = Query(...),
):
    """
    Endpoint WebSocket pour diffusion temps réel.
    Auth via query param token (JWT).
    """
    # Valider le JWT
    payload = decode_access_token_unsafe(token)
    if not payload or payload.get("tenant_id") != tenant_id:
        await websocket.close(code=4001, reason="Auth invalide")
        return

    user_id = payload.get("sub")

    # Enregistrer la session
    async with AsyncSessionLocal() as db:
        try:
            from app.models.realtime import WebSocketSession
            from datetime import datetime, timezone

            session = WebSocketSession(
                tenant_id=UUID(tenant_id),
                user_id=UUID(user_id) if user_id else None,
                session_id=f"ws-{UUID(tenant_id).hex[:8]}-{datetime.now().timestamp()}",
                topics_abonnes=[],
                ip_address=websocket.client.host if websocket.client else None,
                user_agent=websocket.headers.get("user-agent"),
                connecte_at=datetime.now(timezone.utc),
                derniere_activite_at=datetime.now(timezone.utc),
            )
            db.add(session)
            await db.commit()
        except Exception:
            logger.exception("[ws] Échec enregistrement session")

    # Connecter au manager
    await ws_manager.connect(websocket, tenant_id, [])

    try:
        while True:
            # Recevoir les messages du client
            raw = await asyncio.wait_for(
                websocket.receive_text(),
                timeout=60,   # 60s timeout → ping
            )

            try:
                msg = json.loads(raw)
                msg_type = msg.get("type")

                if msg_type == "subscribe":
                    topics = msg.get("topics", [])
                    await ws_manager.subscribe(websocket, tenant_id, topics)
                    await websocket.send_json({
                        "type": "subscribed",
                        "payload": {"topics": topics},
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })

                elif msg_type == "unsubscribe":
                    topics = msg.get("topics", [])
                    await ws_manager.unsubscribe(websocket, tenant_id, topics)

                elif msg_type == "ping":
                    await websocket.send_json({
                        "type": "ping",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })

            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "payload": {"message": "JSON invalide"}})

    except asyncio.TimeoutError:
        logger.info(f"[ws] Tenant {tenant_id} timeout")
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception(f"[ws] Erreur pour tenant {tenant_id}")
    finally:
        await ws_manager.disconnect(websocket, tenant_id)
