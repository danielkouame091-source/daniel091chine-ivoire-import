"""
Producteur Kafka asynchrone — singleton.
Utilise aiokafka pour l'I/O non-bloquant.

⚠️ Idempotence activée : les doublons sont évités côté broker
   via le sequence number du producer.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from aiokafka import AIOKafkaProducer
from aiokafka.errors import KafkaError

from app.core.kafka_config import kafka_settings
from app.events.schemas import EventBase
from app.events.topics import KafkaTopic

logger = logging.getLogger(__name__)


class KafkaEventProducer:
    """Producteur Kafka — initialisé au startup, fermé au shutdown."""

    def __init__(self) -> None:
        self._producer: AIOKafkaProducer | None = None

    async def start(self) -> None:
        if self._producer is not None:
            return

        self._producer = AIOKafkaProducer(
            bootstrap_servers=kafka_settings.KAFKA_BOOTSTRAP_SERVERS,
            client_id=kafka_settings.KAFKA_CLIENT_ID,
            acks=kafka_settings.KAFKA_PRODUCER_ACKS,
            retries=kafka_settings.KAFKA_PRODUCER_RETRIES,
            linger_ms=kafka_settings.KAFKA_PRODUCER_LINGER_MS,
            compression_type=kafka_settings.KAFKA_PRODUCER_COMPRESSION,
            enable_idempotence=kafka_settings.KAFKA_PRODUCER_IDEMPOTENT,
            value_serializer=lambda v: json.dumps(v, default=str).encode("utf-8"),
            key_serializer=lambda k: str(k).encode("utf-8") if k else None,
        )
        await self._producer.start()
        logger.info("[kafka] Producer démarré")

    async def stop(self) -> None:
        if self._producer is not None:
            await self._producer.stop()
            self._producer = None
            logger.info("[kafka] Producer arrêté")

    async def publish(
        self,
        topic: KafkaTopic,
        event: EventBase,
        key: str | None = None,
    ) -> None:
        """
        Publie un événement sur un topic Kafka.
        La clé est le tenant_id (garantit l'ordre par tenant).
        """
        if self._producer is None:
            logger.warning("[kafka] Producer non initialisé — event ignoré")
            return

        # Clé = tenant_id (ordre garanti par partition)
        partition_key = key or str(event.tenant_id)

        try:
            await self._producer.send_and_wait(
                topic=topic.value,
                value=event.to_kafka(),
                key=partition_key,
                headers=[
                    ("event_type", event.event_type.encode()),
                    ("event_id", str(event.event_id).encode()),
                    ("tenant_id", str(event.tenant_id).encode()),
                ],
            )
            logger.debug(f"[kafka] Publié {event.event_type} → {topic.value}")
        except KafkaError as exc:
            logger.exception(f"[kafka] Échec publication {topic.value}")
            raise

    async def publish_batch(
        self, topic: KafkaTopic, events: list[EventBase]
    ) -> None:
        """Publication en lot (performant pour les imports massifs)."""
        if self._producer is None:
            return

        for event in events:
            await self._producer.send(
                topic=topic.value,
                value=event.to_kafka(),
                key=str(event.tenant_id),
            )
        await self._producer.flush()


# Singleton
kafka_producer = KafkaEventProducer()


async def get_producer() -> KafkaEventProducer:
    """Dépendance FastAPI."""
    return kafka_producer
