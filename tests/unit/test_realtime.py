"""
Tests du module Analytics temps réel.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.realtime_syscohada import (
    KafkaTopic,
    SeveriteAlerte,
    StatutAlerte,
    TypeAlerte,
)
from app.schemas.realtime import (
    AlertRuleCreateIn,
    EventPublishIn,
)
from app.services.alert_engine_service import AlertEngineService
from app.services.kafka_producer_service import KafkaProducerService

pytestmark = pytest.mark.integration


# ═════════════════════════════════════════════════════════════════════════════
# TESTS KAFKA PRODUCER
# ═════════════════════════════════════════════════════════════════════════════
class TestKafkaProducer:
    async def test_publier_event(self, db_session, tenant, admin_user):
        svc = KafkaProducerService(db_session, tenant.id, admin_user.id)

        with patch("arq.create_pool", new=AsyncMock()):
            event = await svc.publier(
                topic=KafkaTopic.ECRITURES,
                event_type="ecriture.created",
                payload={
                    "ecriture_id": str(uuid4()),
                    "numero_piece": "VE-2025-00001",
                    "total_debit": 1_000_000,
                    "total_credit": 1_000_000,
                },
            )

        assert event.topic == KafkaTopic.ECRITURES
        assert event.published is False
        assert event.payload["tenant_id"] == str(tenant.id)

    async def test_publier_topic_inconnu_rejete(self, db_session, tenant, admin_user):
        from fastapi import HTTPException
        svc = KafkaProducerService(db_session, tenant.id, admin_user.id)
        with pytest.raises(HTTPException) as exc:
            await svc.publier(
                topic="invalid.topic",
                event_type="test",
                payload={},
            )
        assert exc.value.status_code == 400

    async def test_emit_invoice_paid(self, db_session, tenant, admin_user):
        svc = KafkaProducerService(db_session, tenant.id, admin_user.id)
        with patch("arq.create_pool", new=AsyncMock()):
            event = await svc.emit_invoice_paid(
                invoice_id=uuid4(),
                numero="FAC-2025-000
