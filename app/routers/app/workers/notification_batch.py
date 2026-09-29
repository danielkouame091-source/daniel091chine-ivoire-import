"""
Worker batch — Traitement de la file de notifications + retries.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import and_, or_, select

from app.db.session import AsyncSessionLocal
from app.models.notification import Notification
from app.services.notification_dispatcher import NotificationDispatcher

logger = logging.getLogger(__name__)


async def traiter_file_notifications(
    ctx: dict[str, Any], batch_size: int = 100
) -> dict[str, Any]:
    """
    Dépile et envoie les notifications en attente.
    Appelé toutes les minutes par cron.
    """
    now = datetime.now(timezone.utc)
    sent = 0
    failed = 0

    async with AsyncSessionLocal() as db:
        # Notifications à envoyer
        stmt = (
            select(Notification)
            .where(
                or_(
                    Notification.statut == "queued",
                    and_(
                        Notification.statut == "retrying",
                        Notification.prochaine_tentative_at <= now,
                    ),
                ),
                Notification.nb_tentatives < 3,
            )
            .order_by(Notification.priorite, Notification.queued_at)
            .limit(batch_size)
        )
        rows = (await db.execute(stmt)).scalars().all()

        logger.info(f"[notif_worker] {len(rows)} notifications à traiter")

        for notif in rows:
            try:
                dispatcher = NotificationDispatcher(db, notif.tenant_id)
                result = await dispatcher.envoyer(notif.id)
                if result.get("ok"):
                    sent += 1
                else:
                    failed += 1
                await db.commit()
            except Exception:
                logger.exception(f"[notif_worker] Échec notif {notif.id}")
                await db.rollback()
                failed += 1

    return {"sent": sent, "failed": failed}


async def nettoyer_anciennes_notifications(
    ctx: dict[str, Any], jours: int = 90
) -> dict[str, Any]:
    """
    Archive (soft delete) les notifications > 90 jours pour la performance.
    """
    from datetime import timedelta
    from sqlalchemy import delete

    seuil = datetime.now(timezone.utc) - timedelta(days=jours)

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            delete(Notification).where(
                Notification.created_at < seuil,
                Notification.statut.in_(["sent", "delivered", "read", "clicked", "failed", "bounced"]),
            )
        )
        await db.commit()
        return {"supprimees": result.rowcount or 0}


async def envoyer_campagnes_planifiees(ctx: dict[str, Any]) -> dict[str, Any]:
    """
    Envoie les campagnes dont l'heure planifiée est atteinte.
    """
    from app.services.campaign_service import CampaignService

    now = datetime.now(timezone.utc)
    lancees = 0

    async with AsyncSessionLocal() as db:
        from app.models.notification import NotificationCampaign
        rows = (
            await db.execute(
                select(NotificationCampaign).where(
                    NotificationCampaign.statut == "planifiee",
                    NotificationCampaign.planifiee_at <= now,
                )
            )
        ).scalars().all()

        for camp in rows:
            try:
                svc = CampaignService(db, camp.tenant_id, None)
                result = await svc.lancer_campagne(camp.id)
                await db.commit()
                lancees += 1
                logger.info(
                    f"[notif_worker] Campagne {camp.code} lancée : "
                    f"{result
