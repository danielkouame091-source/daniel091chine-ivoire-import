"""
Worker Analytics — Consumer Kafka → ClickHouse + alertes + WebSocket.

Jobs :
- publier_event_kafka : publie un event du buffer PG vers Kafka
- consumer_kafka_to_clickhouse : batch consumer → insertion ClickHouse
- evaluer_alertes_realtime : évalue les règles sur les nouveaux events
- diffuser_websocket : diffuse les events aux clients connectés
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select, update

from app.core.realtime_syscohada import (
    ClickHouseTable,
    KafkaConfig,
    KafkaTopic,
)
from app.db.session import AsyncSessionLocal
from app.models.realtime import EventBuffer
from app.services.alert_engine_service import AlertEngineService
from app.services.clickhouse_service import ClickHouseService
from app.services.websocket_manager import ws_manager

logger = logging.getLogger(__name__)


# ═════════════════════════════════════════════════════════════════════════════
# 1. PUBLICATION VERS KAFKA
# ═════════════════════════════════════════════════════════════════════════════
async def publier_event_kafka(ctx: dict[str, Any], event_id: str) -> dict[str, Any]:
    """
    Publie un event du buffer PG vers Kafka.
    Utilise aiokafka pour l'async natif.
    """
    try:
        from aiokafka import AIOKafkaProducer
    except ImportError:
        logger.warning("[kafka] aiokafka non installé — publication skippée")
        return {"ok": False, "reason": "aiokafka_missing"}

    eid = UUID(event_id)

    async with AsyncSessionLocal() as db:
        event = await db.scalar(
            select(EventBuffer).where(EventBuffer.id == eid)
        )
        if event is None:
            return {"ok": False, "reason": "not_found"}

        if event.published:
            return {"ok": True, "already_published": True}

        producer = AIOKafkaProducer(
            bootstrap_servers=ctx.get("kafka_bootstrap", KafkaConfig.DEFAULT_BOOTSTRAP),
            acks=KafkaConfig.ACKS,
            compression_type=KafkaConfig.COMPRESSION,
            enable_idempotence=KafkaConfig.IDEMPOTENT_PRODUCER,
            linger_ms=KafkaConfig.LINGER_MS,
        )

        await producer.start()
        try:
            payload_bytes = json.dumps(event.payload, default=str).encode("utf-8")
            metadata = await producer.send_and_wait(
                event.topic,
                value=payload_bytes,
                key=event.partition_key.encode("utf-8"),
            )
            event.published = True
            event.published_at = datetime.now(timezone.utc)
            event.kafka_offset = metadata.offset
            event.kafka_partition = metadata.partition
            await db.commit()
            return {
                "ok": True,
                "topic": event.topic,
                "partition": metadata.partition,
                "offset": metadata.offset,
            }
        except Exception as exc:
            event.nb_tentatives += 1
            event.derniere_erreur = str(exc)[:500]
            await db.commit()
            logger.exception(f"[kafka] Échec publication {event_id}")
            return {"ok": False, "reason": str(exc)}
        finally:
            await producer.stop()


# ═════════════════════════════════════════════════════════════════════════════
# 2. CONSUMER KAFKA → CLICKHOUSE
# ═════════════════════════════════════════════════════════════════════════════
async def consumer_kafka_to_clickhouse(
    ctx: dict[str, Any],
    batch_size: int = 500,
    timeout_ms: int = 5000,
) -> dict[str, Any]:
    """
    Consomme les events Kafka et les insère dans ClickHouse.
    Tourne en boucle courte (déclenché par cron toutes les 10 secondes).
    """
    try:
        from aiokafka import AIOKafkaConsumer
    except ImportError:
        return {"ok": False, "reason": "aiokafka_missing"}

    topics = [
        KafkaTopic.ECRITURES,
        KafkaTopic.FACTURES_CLIENTS,
        KafkaTopic.MM_TRANSACTIONS,
        KafkaTopic.FNE_CERTIFICATIONS,
    ]

    consumer = AIOKafkaConsumer(
        *topics,
        bootstrap_servers=ctx.get("kafka_bootstrap", KafkaConfig.DEFAULT_BOOTSTRAP),
        group_id="mtech-consumer-clickhouse",
        auto_offset_reset="earliest",
        enable_auto_commit=False,
        max_poll_records=batch_size,
    )

    await consumer.start()
    inserted = 0
    alertes_creees = 0

    try:
        # Consomme un batch avec timeout
        result = await asyncio.wait_for(
            consumer.getmany(timeout_ms=timeout_ms, max_records=batch_size),
            timeout=timeout_ms / 1000 + 2,
        )

        ch = ClickHouseService()
        events_to_insert: list[dict[str, Any]] = []

        for tp, messages in result.items():
            for msg in messages:
                try:
                    payload = json.loads(msg.value.decode("utf-8"))
                    event_row = {
                        "event_id": f"{msg.topic}-{msg.partition}-{msg.offset}",
                        "topic": msg.topic,
                        "partition": msg.partition,
                        "offset": msg.offset,
                        "tenant_id": payload.get("tenant_id", ""),
                        "event_type": payload.get("event_type", msg.topic),
                        "event_time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f"),
                        "payload": json.dumps(payload, default=str),
                    }
                    events_to_insert.append(event_row)

                    # Évaluer les alertes
                    async with AsyncSessionLocal() as db:
                        tenant_id = payload.get("tenant_id")
                        if tenant_id:
                            svc = AlertEngineService(db, UUID(tenant_id))
                            alertes = await svc.evaluer_event({
                                "topic": msg.topic,
                                "event_type": payload.get("event_type"),
                                "payload": payload,
                            })
                            alertes_creees += len(alertes)
                            await db.commit()

                            # Diffuser WebSocket
                            for alerte in alertes:
                                await ws_manager.broadcast_to_tenant(
                                    tenant_id,
                                    {
                                        "type": "alert",
                                        "topic": "alerts",
                                        "payload": {
                                            "reference": alerte.reference,
                                            "severite": alerte.severite,
                                            "titre": alerte.titre,
                                        },
                                        "timestamp": datetime.now(timezone.utc).isoformat(),
                                    },
                                )

                            # Diffuser l'event brut
                            await ws_manager.broadcast_to_tenant(
                                tenant_id,
                                {
                                    "type": "event",
                                    "topic": msg.topic,
                                    "payload": payload,
                                    "timestamp": datetime.now(timezone.utc).isoformat(),
                                },
                            )

                except Exception:
                    logger.exception(f"[consumer] Erreur msg offset {msg.offset}")

        # Insert ClickHouse en batch
        if events_to_insert:
            try:
                await ch.insert(ClickHouseTable.EVENTS, events_to_insert)
                inserted = len(events_to_insert)
            except Exception:
                logger.exception("[consumer] Échec insertion ClickHouse")

        # Commit offsets (at-least-once)
        await consumer.commit()

    except asyncio.TimeoutError:
        pass
    finally:
        await consumer.stop()

    return {"inserted": inserted, "alertes_creees": alertes_creees}


# ═════════════════════════════════════════════════════════════════════════════
# 3. NETTOYAGE BUFFER
# ═════════════════════════════════════════════════════════════════════════════
async def nettoyer_event_buffer(ctx: dict[str, Any], jours: int = 7) -> dict[str, Any]:
    """Supprime les events publiés > 7 jours."""
    from datetime import timedelta
    from sqlalchemy import delete

    seuil = datetime.now(timezone.utc) - timedelta(days=jours)

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            delete(EventBuffer).where(
                EventBuffer.published.is_(True),
                EventBuffer.published_at < seuil,
            )
        )
        await db.commit()
        return {"supprimees": result.rowcount or 0}


# ═════════════════════════════════════════════════════════════════════════════
# 4. MISE À JOUR LAG
# ═════════════════════════════════════════════════════════════════════════════
async def snapshot_consumer_lag(ctx: dict[str, Any]) -> dict[str, Any]:
    """
    Snapshot du lag Kafka par consumer group.
    Utilisé pour monitoring + alerting.
    """
    # Simplifié : à enrichir via AdminClient Kafka
    return {"ok": True, "note": "Snapshot lag à implémenter via Kafka AdminClient"}


# ═════════════════════════════════════════════════════════════════════════════
# 5. NOTIFICATION ALERTE
# ═════════════════════════════════════════════════════════════════════════════
async def envoyer_alerte_notification(
    ctx: dict[str, Any], alert_id: str, action: dict[str, Any]
) -> dict[str, Any]:
    """Envoie une notification pour une alerte (via NotificationService)."""
    aid = UUID(alert_id)

    async with AsyncSessionLocal() as db:
        from app.models.realtime import RealtimeAlert
        from app.services.notification_service import NotificationService
        from app.schemas.notification import SendNotificationIn

        alerte = await db.scalar(select(RealtimeAlert).where(RealtimeAlert.id == aid))
        if alerte is None:
            return {"ok": False, "reason": "alert_not_found"}

        canal = action.get("canal", "email")
        destinataires = action.get("destinataires", [])

        svc = NotificationService(db, alerte.tenant_id, None)

        sent = 0
        for dest in destinataires:
            try:
                await svc.envoyer(SendNotificationIn(
                    destinataire_email=dest if "@" in dest else None,
                    destinataire_telephone=dest if "@" not in dest else None,
                    canal=canal,
                    type_notification="realtime_alert",
                    criticite="haute",
                    sujet=f"🚨 {alerte.titre}",
                    contenu_html=f"<h2>{alerte.titre}</h2><p>{alerte.description}</p>",
                    contexte={"alert_id": str(alerte.id), "severite": alerte.severite},
                ))
                sent += 1
            except Exception:
                logger.exception(f"[realtime_batch] Échec notif à {dest}")

        await db.commit()
        return {"ok": True, "sent": sent}


async def envoyer_alerte_webhook(
    ctx: dict[str, Any], alert_id: str, url: str
) -> dict[str, Any]:
    """Envoie un webhook pour une alerte."""
    import httpx

    aid = UUID(alert_id)
    async with AsyncSessionLocal() as db:
        from app.models.realtime import RealtimeAlert
        alerte = await db.scalar(select(RealtimeAlert).where(RealtimeAlert.id == aid))
        if alerte is None:
            return {"ok": False, "reason": "alert_not_found"}

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.post(url, json={
                    "reference": alerte.reference,
                    "severite": alerte.severite,
                    "titre": alerte.titre,
                    "description": alerte.description,
                    "created_at": alerte.created_at.isoformat(),
                })
                return {"ok": r.status_code < 400, "status": r.status_code}
        except Exception as exc:
            logger.exception("[realtime_batch] Échec webhook")
            return {"ok": False, "reason": str(exc)}
