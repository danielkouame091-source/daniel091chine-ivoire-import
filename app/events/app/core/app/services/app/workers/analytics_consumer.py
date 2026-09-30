"""
Consumer Kafka — ingère les événements dans ClickHouse.
Worker ARQ indépendant, scalable horizontalement.

⚠️ Traitement par lots (batch) pour la performance ClickHouse.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

import clickhouse_connect
from aiokafka import AIOKafkaConsumer
from aiokafka.errors import KafkaError

from app.core.kafka_config import kafka_settings
from app.events.topics import KafkaTopic

logger = logging.getLogger(__name__)


# Mapping topic → table ClickHouse
TOPIC_TABLE_MAP: dict[str, str] = {
    KafkaTopic.INVOICE_CREATED.value:    "events_invoices",
    KafkaTopic.INVOICE_PAID.value:       "events_payments",
    KafkaTopic.PAYMENT_RECEIVED.value:   "events_payments",
    KafkaTopic.MM_TRANSACTION.value:     "events_mm_transactions",
    KafkaTopic.STOCK_LOW.value:          "events_stock_low",
    KafkaTopic.AUDIT_FINDING.value:      "events_audit_findings",
    KafkaTopic.ECRITURE_CREATED.value:   "events_ecritures",
    KafkaTopic.FNE_CERTIFIED.value:      "events_fne",
    KafkaTopic.FNE_REJECTED.value:       "events_fne",
    KafkaTopic.LEAVE_REQUESTED.value:    "events_hr",
    KafkaTopic.PAYSLIP_GENERATED.value:  "events_hr",
    KafkaTopic.PROJECT_MILESTONE.value:  "events_projects",
    KafkaTopic.STOCK_MOVEMENT.value:     "events_stock_movements",
    KafkaTopic.PO_CREATED.value:         "events_purchase_orders",
    KafkaTopic.BANK_TRANSACTION.value:   "events_bank_transactions",
    KafkaTopic.RECONCILIATION.value:     "events_reconciliations",
}


class AnalyticsConsumer:
    """Consumer Kafka → ClickHouse avec traitement par batch."""

    BATCH_SIZE = 500
    BATCH_TIMEOUT_S = 2.0

    def __init__(self) -> None:
        self._consumer: AIOKafkaConsumer | None = None
        self._ch_client = None
        self._running = False

    async def start(self) -> None:
        # Client ClickHouse
        self._ch_client = await clickhouse_connect.get_async_client(
            host=kafka_settings.KAFKA_BOOTSTRAP_SERVERS.split(":")[0],
            port=8123,
            username="default",
            database="mtech_analytics",
        )

        # Consumer Kafka (tous les topics)
        self._consumer = AIOKafkaConsumer(
            *TOPIC_TABLE_MAP.keys(),
            bootstrap_servers=kafka_settings.KAFKA_BOOTSTRAP_SERVERS,
            group_id=kafka_settings.KAFKA_GROUP_ID,
            auto_offset_reset=kafka_settings.KAFKA_CONSUMER_AUTO_OFFSET_RESET,
            enable_auto_commit=kafka_settings.KAFKA_CONSUMER_ENABLE_AUTO_COMMIT,
            max_poll_records=kafka_settings.KAFKA_CONSUMER_MAX_POLL_RECORDS,
            session_timeout_ms=kafka_settings.KAFKA_CONSUMER_SESSION_TIMEOUT_MS,
            heartbeat_interval_ms=kafka_settings.KAFKA_CONSUMER_HEARTBEAT_INTERVAL_MS,
        )
        await self._consumer.start()
        logger.info("[analytics_consumer] Démarré")
        self._running = True

    async def stop(self) -> None:
        self._running = False
        if self._consumer:
            await self._consumer.stop()
        if self._ch_client:
            await self._ch_client.close()
        logger.info("[analytics_consumer] Arrêté")

    async def run(self) -> None:
        """Boucle principale — consommation + insertion batch."""
        assert self._consumer is not None
        assert self._ch_client is not None

        buffers: dict[str, list[dict[str, Any]]] = {t: [] for t in TOPIC_TABLE_MAP}

        while self._running:
            try:
                batch = await asyncio.wait_for(
                    self._consumer.getmany(
                        timeout_ms=int(self.BATCH_TIMEOUT_S * 1000),
                        max_records=self.BATCH_SIZE,
                    ),
                    timeout=self.BATCH_TIMEOUT_S + 1,
                )

                for tp, messages in batch.items():
                    table = TOPIC_TABLE_MAP.get(tp.topic)
                    if not table:
                        continue

                    for msg in messages:
                        try:
                            event = json.loads(msg.value.decode("utf-8"))
                            row = self._flatten_event(event)
                            buffers[tp.topic].append(row)
                        except Exception:
                            logger.exception(f"[analytics_consumer] Erreur parsing {msg.topic}")

                # Flush par table
                for topic, rows in buffers.items():
                    if not rows:
                        continue
                    table = TOPIC_TABLE_MAP[topic]
                    try:
                        await self._ch_client.insert(
                            table=table,
                            data=rows,
                            column_names=list(rows[0].keys()),
                        )
                        logger.debug(f"[analytics_consumer] {len(rows)} rows → {table}")
                        buffers[topic] = []
                    except Exception:
                        logger.exception(f"[analytics_consumer] Erreur insert {table}")

                # Commit les offsets APRÈS insertion réussie
                await self._consumer.commit()

            except asyncio.TimeoutError:
                # Flush des buffers en cas d'inactivité
                for topic, rows in buffers.items():
                    if rows:
                        table = TOPIC_TABLE_MAP[topic]
                        try:
                            await self._ch_client.insert(
                                table=table, data=rows,
                                column_names=list(rows[0].keys()),
                            )
                            buffers[topic] = []
                        except Exception:
                            logger.exception(f"[analytics_consumer] Flush timeout {table}")
                continue

            except KafkaError:
                logger.exception("[analytics_consumer] Erreur Kafka — retry dans 5s")
                await asyncio.sleep(5)

            except Exception:
                logger.exception("[analytics_consumer] Erreur inattendue — retry dans 10s")
                await asyncio.sleep(10)

    @staticmethod
    def _flatten_event(event: dict[str, Any]) -> dict[str, Any]:
        """Aplatit l'enveloppe + le payload en une seule ligne ClickHouse."""
        payload = event.pop("payload", {}) or {}
        event.pop("version", None)
        return {**event, **payload}


async def run_analytics_consumer(ctx: dict[str, Any]) -> None:
    """Point d'entrée worker ARQ (background)."""
    consumer = AnalyticsConsumer()
    try:
        await consumer.start()
        await consumer.run()
    finally:
        await consumer.stop()


async def start_analytics_consumer(ctx: dict[str, Any]) -> dict[str, Any]:
    """
    Démarre le consumer en tâche de fond (non-bloquant pour ARQ).
    """
    consumer = AnalyticsConsumer()
    await consumer.start()
    asyncio.create_task(consumer.run())
    ctx["analytics_consumer"] = consumer
    return {"status": "started"}
