"""
Job batch — calcule les prévisions de trésorerie pour tous les tenants actifs.
À déclencher chaque nuit (cron ARQ).
"""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.enums import SubStatut, TenantStatut
from app.models.subscription import Subscription
from app.models.tenant import Tenant
from app.services.forecast_service import ForecastService

logger = logging.getLogger(__name__)


async def recalculer_toutes_les_previsions(ctx: dict[str, Any]) -> dict[str, Any]:
    """Calcule la prévision 90j pour chaque tenant actif avec abonnement valide."""
    processed = 0
    failed = 0

    async with AsyncSessionLocal() as db:
        rows = (
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

        logger.info(f"[forecast_batch] {len(rows)} tenants à traiter")

        for tenant_id in rows:
            try:
                async with AsyncSessionLocal() as sub_db:
                    # user_id = None → utilise l'admin principal du tenant
                    from app.models.enums import UserRole, UserStatut
                    from app.models.user import User
                    admin = await sub_db.scalar(
                        select(User).where(
                            User.tenant_id == tenant_id,
                            User.role == UserRole.ADMIN_TENANT,
                            User.statut == UserStatut.ACTIF,
                        ).limit(1)
                    )
                    if admin is None:
                        continue

                    svc = ForecastService(sub_db, tenant_id, admin.id)
                    await svc.calculer(horizon_jours=90)
                    await sub_db.commit()
                    processed += 1
            except Exception:
                logger.exception(f"[forecast_batch] Échec tenant {tenant_id}")
                failed += 1

    return {"processed": processed, "failed": failed}
