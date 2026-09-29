"""
Job batch — snapshot quotidien de trésorerie + prévisions 13 semaines.
À déclencher chaque nuit (cron ARQ).
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.enums import SubStatut, TenantStatut, UserRole, UserStatut
from app.models.subscription import Subscription
from app.models.tenant import Tenant
from app.models.user import User
from app.services.treasury_service import TreasuryService

logger = logging.getLogger(__name__)


async def snapshot_quotidien(ctx: dict[str, Any]) -> dict[str, Any]:
    """
    Calcule la position de trésorerie et les prévisions 13 semaines
    pour tous les tenants actifs.
    """
    processed = 0
    failed = 0

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
                    admin = await sub_db.scalar(
                        select(User).where(
                            User.tenant_id == tenant_id,
                            User.role == UserRole.ADMIN_TENANT,
                            User.statut == UserStatut.ACTIF,
                        ).limit(1)
                    )
                    if admin is None:
                        continue

                    svc = TreasuryService(sub_db, tenant_id, admin.id)
                    # Snapshot position
                    await svc.calculer_position_actuelle()
                    # Prévisions 13 semaines
                    dashboard = await svc.calculer_previsions_13_semaines()
                    await sub_db.commit()

                    # Alerte si creux négatif
                    if dashboard.premiere_semaine_negative:
                        logger.warning(
                            f"[treasury] Tenant {tenant_id} : "
                            f"prévision négative à partir de {dashboard.premiere_semaine_negative}"
                        )
                    processed += 1
            except Exception:
                logger.exception(f"[treasury] Échec tenant {tenant_id}")
                failed += 1

    return {"processed": processed, "failed": failed}
