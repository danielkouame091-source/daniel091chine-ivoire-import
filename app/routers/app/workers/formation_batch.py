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
                   
