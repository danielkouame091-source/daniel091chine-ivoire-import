"""
Moteur d'alertes temps réel — consomme Kafka et déclenche des alertes
basées sur des règles configurables.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from uuid import UUID

from aiokafka import AIOKafkaConsumer

from app.core.kafka_config import kafka_settings
from app.events.topics import KafkaTopic

logger = logging.getLogger(__name__)


# Règle = (nom, condition, action)
class AlertRule:
    def __init__(
        self,
        nom: str,
        topic: str,
        condition: Callable[[dict[str, Any]], bool],
        severite: str = "moyenne",
        cooldown_minutes: int = 15,
    ) -> None:
        self.nom = nom
        self.topic = topic
        self.condition = condition
        self.severite = severite
        self.cooldown = timedelta(minutes=cooldown_minutes)
        self._last_fired: dict[str, datetime] = {}

    def can_fire(self, key: str) -> bool:
        last = self._last_fired.get(key)
        if last is None:
            return True
        return datetime.now(timezone.utc) - last > self.cooldown

    def mark_fired(self, key: str) -> None:
        self._last_fired[key] = datetime.now(timezone.utc)


# ═════════════════════════════════════════════════════════════════════════════
# Règles prédéfinies
# ═════════════════════════════════════════════════════════════════════════════
ALERT_RULES: list[AlertRule] = [
    AlertRule(
        nom="grosse_transaction_mm",
        topic=KafkaTopic.MM_TRANSACTION.value,
        condition=lambda e: e.get("montant", 0) > 5_000_000,
        severite="haute",
        cooldown_minutes=5,
    ),
    AlertRule(
        nom="anomalie_critique",
        topic=KafkaTopic.AUDIT_FINDING.value,
        condition=lambda e: e.get("severite") == "critique",
        severite="critique",
        cooldown_minutes=0,   # Pas de cooldown pour le critique
    ),
    AlertRule(
        nom="rupture_stock",
        topic=KafkaTopic.STOCK_LOW.value,
        condition=lambda e: e.get("quantite", 1) == 0,
        severite="haute",
        cooldown_minutes=60,
    ),
]


class AlertEngine:
    """Consomme Kafka et déclenche les alertes."""

    def __init__(self) -> None:
        self._consumer: AIOKafkaConsumer | None = None
        self._running = False
        self._rules_by_topic: dict[str, list[AlertRule]] = {}
        for rule in ALERT_RULES:
            self._rules_by_topic.setdefault(rule.topic, []).append(rule)

    async def start(self) -> None:
        self._consumer = AIOKafkaConsumer(
            *self._rules_by_topic.keys(),
            bootstrap_servers=kafka_settings.KAFKA_BOOTSTRAP_SERVERS,
            group_id=f"{kafka_settings.KAFKA_GROUP_ID}-alerts",
            auto_offset_reset="latest",  # Alertes temps réel uniquement
            enable_auto_commit=True,
        )
        await self._consumer.start()
        self._running = True
        logger.info("[alert_engine] Démarré")

    async def stop(self) -> None:
        self._running = False
        if self._consumer:
            await self._consumer.stop()

    async def run(self) -> None:
        assert self._consumer is not None

        while self._running:
            try:
                batch = await asyncio.wait_for(
                    self._consumer.getmany(timeout_ms=1000),
                    timeout=2.0,
                )

                for tp, messages in batch.items():
                    rules = self._rules_by_topic.get(tp.topic, [])
                    for msg in messages:
                        try:
                            event = json.loads(msg.value.decode("utf-8"))
                            payload = event.get("payload", {}) or {}
                            merged = {**event, **payload}

                            for rule in rules:
                                if rule.condition(merged):
                                    key = f"{event.get('tenant_id')}:{rule.nom}"
                                    if rule.can_fire(key):
                                        rule.mark_fired(key)
                                        await self._fire(rule, merged)
                        except Exception:
                            logger.exception("[alert_engine] Erreur traitement message")

            except asyncio.TimeoutError:
                continue
            except Exception:
                logger.exception("[alert_engine] Erreur boucle")
                await asyncio.sleep(5)

    async def _fire(self, rule: AlertRule, event: dict[str, Any]) -> None:
        """Déclenche une alerte (log + notification + webhook)."""
        logger.warning(
            f"[alert] 🔔 {rule.nom} ({rule.severite}) — "
            f"tenant={event.get('tenant_id')} — {event}"
        )

        # Publier une notification dans Kafka (consommée par le service de notif)
        from app.events.producer import kafka_producer
        from app.events.schemas import EventBase

        try:
            await kafka_producer.publish(
                topic=KafkaTopic.AUDIT_FINDING,
                event=EventBase(
                    event_type=f"alert.{rule.nom}",
                    tenant_id=UUID(event["tenant_id"]),
                    payload={
                        "rule": rule.nom,
                        "severite": rule.severite,
                        "event": event,
                    },
                    source="alert_engine",
                ),
            )
        except Exception:
            logger.exception("[alert_engine] Échec publication alerte")


alert_engine = AlertEngine()
