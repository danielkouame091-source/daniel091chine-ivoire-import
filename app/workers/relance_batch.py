"""
Job batch — relances clients automatiques.
À déclencher chaque jour ouvré (cron ARQ).
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.enums import SubStatut, TenantStatut, UserRole, UserStatut
from app.models.subscription import Subscription
from app.models.tenant import Tenant
from app.models.user import User
from app.services.sale_service import SaleService

logger = logging.getLogger(__name__)


async def executer_relances_quotidiennes(ctx: dict[str, Any]) -> dict[str, Any]:
    """
    Parcourt tous les tenants actifs et exécute les relances clients
    pour les factures échues depuis ≥ 3 jours.
    """
    processed = 0
    failed = 0
    total_relances = 0
    by_niveau_global: dict[str, int] = {}

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

        logger.info(f"[relance_batch] {len(tenants)} tenants à traiter")

        for tenant_id in tenants:
            try:
                async with AsyncSessionLocal() as sub_db:
                    admin = await sub_db.scalar(
                        select(User).where(
                            User.tenant_id == tenant_id,
                            User.role == UserRole.ADMIN_TENANT,
                            User.statut == UserStatut.ACTIF,
                        ).limit(1)
                    )
                    if admin is None:
                        continue

                    svc = SaleService(sub_db, tenant_id, admin.id)
                    result = await svc.executer_relances(date.today())
                    await sub_db.commit()

                    total_relances += result.invoices_relanced
                    for niveau, count in result.by_niveau.items():
                        by_niveau_global[niveau] = by_niveau_global.get(niveau, 0) + count
                    processed += 1
            except Exception:
                logger.exception(f"[relance_batch] Échec tenant {tenant_id}")
                failed += 1

    logger.info(
        f"[relance_batch] {processed} tenants traités, "
        f"{total_relances} relances, by_niveau={by_niveau_global}"
    )
    return {
        "tenants_processed": processed,
        "tenants_failed": failed,
        "total_relances": total_relances,
        "by_niveau": by_niveau_global,
    }
