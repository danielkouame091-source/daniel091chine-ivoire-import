"""
Service Kafka Producer — Publication d'events métier vers Redpanda.

Architecture :
1. Écriture synchrone dans `realtime_event_buffer` (PG) → durabilité
2. Publication async vers Kafka (via worker ARQ)
3. Marque published=True + offset Kafka

Avantages :
- Zéro perte si Kafka down (buffer PG)
- At-least-once delivery
- Idempotent (event_id unique)
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.realtime_syscohada import (
    KafkaConfig,
    KafkaTopic,
    SCHEMAS_EVENEMENTS,
    TOUS_TOPICS,
)
from app.models.realtime import EventBuffer, TopicSchema
from app.services.audit_service import AuditService

logger = logging.getLogger(__name__)


class KafkaProducerService:
    """
    Producteur Kafka (buffer en PG + publication async).
    """

    def __init__(self, db: AsyncSession, tenant_id: UUID, user_id: UUID | None = None) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.audit = AuditService(db)

    # ═════════════════════════════════════════════════════════════════════
    # PUBLICATION
    # ═════════════════════════════════════════════════════════════════════
    async def publier(
        self,
        topic: str,
        event_type: str,
        payload: dict[str, Any],
        partition_key: str | None = None,
        valider_schema: bool = True,
    ) -> EventBuffer:
        """
        Publie un événement :
        1. Valide le schéma (si activé)
        2. Écrit dans le buffer PG
        3. Enqueue un job ARQ pour publication Kafka
        """
        if topic not in TOUS_TOPICS:
            raise HTTPException(400, f"Topic inconnu : {topic}")

        # Toujours ajouter tenant_id au payload
        full_payload = {**payload, "tenant_id": str(self.tenant_id)}

        if valider_schema:
            await self._valider_schema(topic, event_type, full_payload)

        # Partition key : par défaut tenant_id (garantit l'ordre par tenant)
        pkey = partition_key or str(self.tenant_id)

        event = EventBuffer(
            tenant_id=self.tenant_id,
            topic=topic,
            event_type=event_type,
            partition_key=pkey,
            payload=full_payload,
            payload_size_kb=len(str(full_payload)) // 1024,
            published=False,
            created_at=datetime.now(timezone.utc),
        )
        self.db.add(event)
        await self.db.flush()

        # Enqueue publication async (non bloquant)
        try:
            from arq import create_pool
            from app.workers.arq_settings import WorkerSettings
            redis = await create_pool(WorkerSettings.redis_settings)
            await redis.enqueue_job("publier_event_kafka", str(event.id))
            await redis.aclose()
        except Exception:
            logger.exception("[kafka] Échec enqueue publication (buffer conservé en PG)")

        return event

    async def publier_batch(
        self, events: list[dict[str, Any]]
    ) -> list[EventBuffer]:
        """
        Publication groupée optimisée.
        events = [{"topic": ..., "event_type": ..., "payload": ...}, ...]
        """
        buffers: list[EventBuffer] = []
        now = datetime.now(timezone.utc)

        for e in events:
            topic = e["topic"]
            if topic not in TOUS_TOPICS:
                continue
            full_payload = {**e["payload"], "tenant_id": str(self.tenant_id)}
            buffer = EventBuffer(
                tenant_id=self.tenant_id,
                topic=topic,
                event_type=e["event_type"],
                partition_key=e.get("partition_key", str(self.tenant_id)),
                payload=full_payload,
                published=False,
                created_at=now,
            )
            buffers.append(buffer)

        self.db.add_all(buffers)
        await self.db.flush()

        # Enqueue batch
        try:
            from arq import create_pool
            from app.workers.arq_settings import WorkerSettings
            redis = await create_pool(WorkerSettings.redis_settings)
            for b in buffers:
                await redis.enqueue_job("publier_event_kafka", str(b.id))
            await redis.aclose()
        except Exception:
            logger.exception("[kafka] Échec enqueue batch")

        return buffers

    # ═════════════════════════════════════════════════════════════════════
    # VALIDATION SCHÉMA
    # ═════════════════════════════════════════════════════════════════════
    async def _valider_schema(
        self, topic: str, event_type: str, payload: dict[str, Any]
    ) -> None:
        """Valide le payload contre le schéma du topic (si défini)."""
        # Chercher le schéma actif
        schema = await self.db.scalar(
            select(TopicSchema).where(
                TopicSchema.topic == topic,
                TopicSchema.actif.is_(True),
            )
        )
        if schema is None:
            return  # Pas de schéma → pas de validation

        # Vérifier champs requis
        for champ in schema.champs_requis or []:
            if champ not in payload:
                raise HTTPException(
                    400, f"Champ requis manquant : {champ} (topic {topic})"
                )

    # ═════════════════════════════════════════════════════════════════════
    # HELPERS MÉTIER
    # ═════════════════════════════════════════════════════════════════════
    async def emit_ecriture_created(
        self, ecriture_id: UUID, numero_piece: str,
        date_ecriture: str, total_debit: int, total_credit: int,
        journal_code: str | None = None,
    ) -> EventBuffer:
        """Émet un événement de création d'écriture."""
        return await self.publier(
            topic=KafkaTopic.ECRITURES,
            event_type="ecriture.created",
            payload={
                "ecriture_id": str(ecriture_id),
                "numero_piece": numero_piece,
                "date_ecriture": date_ecriture,
                "total_debit": total_debit,
                "total_credit": total_credit,
                "journal_code": journal_code,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

    async def emit_invoice_paid(
        self, invoice_id: UUID, numero: str,
        total_ttc: int, date_paiement: str,
    ) -> EventBuffer:
        return await self.publier(
            topic=KafkaTopic.FACTURES_CLIENTS,
            event_type="invoice.paid",
            payload={
                "invoice_id": str(invoice_id),
                "numero": numero,
                "total_ttc": total_ttc,
                "date_paiement": date_paiement,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

    async def emit_mm_transaction(
        self, provider: str, external_id: str,
        montant_xof: int, sens: str,
        numero_tiers: str | None = None,
    ) -> EventBuffer:
        return await self.publier(
            topic=KafkaTopic.MM_TRANSACTIONS,
            event_type="mm.transaction.received",
            payload={
                "provider": provider,
                "external_id": external_id,
                "montant_xof": montant_xof,
                "sens": sens,
                "numero_tiers": numero_tiers,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            partition_key=f"{self.tenant_id}:{provider}",
        )

    async def emit_alert(
        self, alert_id: UUID, severite: str, titre: str,
    ) -> EventBuffer:
        return await self.publier(
            topic=KafkaTopic.ALERTS,
            event_type="alert.triggered",
            payload={
                "alert_id": str(alert_id),
                "severite": severite,
                "titre": titre,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )
