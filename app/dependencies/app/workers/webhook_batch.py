"""
Worker batch — Livraison des webhooks en attente + nettoyage.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, delete, or_, select

from app.db.session import AsyncSessionLocal
from app.models.public_api import (
    ApiUsageAggregate,
    IdempotencyKey,
    WebhookDelivery,
)
from app.core.public_api_syscohada import StatutWebhookDelivery
from app.services.webhook_dispatch_service import WebhookDispatchService

logger = logging.getLogger(__name__)


async def traiter_livraisons_webhook(ctx: dict[str, Any], batch_size: int = 200) -> dict[str, Any]:
    """
    Traite les livraisons en attente (pending + retrying).
    Appelé toutes les minutes par cron.
    """
    now = datetime.now(timezone.utc)
    traitees = 0
    succes = 0
    echecs = 0

    async with AsyncSessionLocal() as db:
        # Sélectionner les livraisons à traiter
        stmt = (
            select(WebhookDelivery.id, WebhookDelivery.tenant_id)
            .where(
                or_(
                    WebhookDelivery.statut == StatutWebhookDelivery.PENDING,
                    and_(
                        WebhookDelivery.statut == StatutWebhookDelivery.RETRYING,
                        WebhookDelivery.prochaine_tentative_at <= now,
                    ),
                ),
            )
            .order_by(WebhookDelivery.prochaine_tentative_at)
            .limit(batch_size)
        )
        rows = (await db.execute(stmt)).all()

        logger.info(f"[webhook_batch] {len(rows)} livraisons à traiter")

    for delivery_id, tenant_id in rows:
        try:
            async with AsyncSessionLocal() as db:
                svc = WebhookDispatchService(db, tenant_id, None)
                result = await svc.livrer(delivery_id)
                await db.commit()
                traitees += 1
                if result.get("ok"):
                    succes += 1
                else:
                    echecs += 1
        except Exception:
            logger.exception(f"[webhook_batch] Échec livraison {delivery_id}")
            echecs += 1

    return {"traitees": traitees, "succes": succes, "echecs": echecs}


async def nettoyer_anciennes_livraisons(ctx: dict[str, Any], jours: int = 90) -> dict[str, Any]:
    """
    Supprime les livraisons webhook > 90 jours (sauf échecs non résolus).
    """
    seuil = datetime.now(timezone.utc) - timedelta(days=jours)

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            delete(WebhookDelivery).where(
                WebhookDelivery.created_at < seuil,
                WebhookDelivery.statut.in_([
                    StatutWebhookDelivery.SUCCESS,
                    StatutWebhookDelivery.FAILED,
                ]),
            )
        )
        await db.commit()
        return {"supprimees": result.rowcount or 0}


async def nettoyer_idempotency_expire(ctx: dict[str, Any]) -> dict[str, Any]:
    """Supprime les clés d'idempotence expirées."""
    now = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            delete(IdempotencyKey).where(IdempotencyKey.expire_at < now)
        )
        await db.commit()
        return {"supprimees": result.rowcount or 0}


async def agreger_usage_api(ctx: dict[str, Any]) -> dict[str, Any]:
    """
    Agrège les logs d'usage par heure (pour analytics + facturation).
    Tourne chaque heure.
    """
    # Simplification MVP : à compléter en production
    return {"status": "ok", "note": "Agrégation à implémenter en V2"}
