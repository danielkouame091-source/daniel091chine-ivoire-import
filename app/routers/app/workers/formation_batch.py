"""
Job batch — Analytics support + suggestions d'articles.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import desc, func, select

from app.db.session import AsyncSessionLocal
from app.models.enums import SubStatut, TenantStatut
from app.models.formation import Article, SupportTicket
from app.models.subscription import Subscription
from app.models.tenant import Tenant
from app.services.support_ticket_service import SupportTicketService

logger = logging.getLogger(__name__)


async def verifier_sla_tickets(ctx: dict[str, Any]) -> dict[str, Any]:
    """
    Vérifie les SLA des tickets ouverts pour tous les tenants actifs.
    """
    processed = 0
    total_depasses = 0

    async with AsyncSessionLocal() as db:
        tenants = (
            await db.execute(
                select(Tenant.id)
                .join(Subscription, Subscription.tenant_id == Tenant.id)
                .where(
                    Tenant.statut == TenantStatut.ACTIF,
                    Tenant.deleted_at.is_(None),
                    Subscription.statut.in_([SubStatut.TRIAL, SubStatut.ACTIF]),
                )
                .distinct()
            )
        ).scalars().all()

        for tenant_id in tenants:
            try:
                async with AsyncSessionLocal() as sub_db:
                    svc = SupportTicketService(sub_db, tenant_id, tenant_id)
                    result = await svc.verifier_sla()
                    total_depasses += result["sla_depasses_marques"]
                    await sub_db.commit()
                    processed += 1
            except Exception:
                logger.exception(f"[formation_batch] Échec SLA tenant {tenant_id}")

    return {"tenants_processed": processed, "total_sla_depasses": total_depasses}


async def suggerer_articles_manquants(ctx: dict[str, Any]) -> dict[str, Any]:
    """
    Analyse les tickets récurrents pour identifier les articles à créer.
    Génère un rapport consultable par le fondateur.
    """
    horizon = datetime.now(timezone.utc) - timedelta(days=30)

    async with AsyncSessionLocal() as db:
        # Top 20 sujets de tickets sur 30 jours
        rows = (
            await db.execute(
                select(
                    SupportTicket.sujet,
                    func.count(SupportTicket.id).label("n"),
                )
                .where(
                    SupportTicket.created_at >= horizon,
                    SupportTicket.statut.notin_(["annule", "ferme"]),
                )
                .group_by(SupportTicket.sujet)
                .order_by(desc("n"))
                .limit(20)
            )
        ).all()

        suggestions = [
            {"sujet": r.sujet, "nb_occurrences": int(r.n)}
            for r in rows if int(r.n) >= 3
        ]

        logger.info(f"[formation_batch] {len(suggestions)} sujets récurrents identifiés")

    return {"suggestions_articles": suggestions}
