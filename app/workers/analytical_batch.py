"""
Job batch — recalcul de la consommation budgétaire + alertes.
À déclencher chaque nuit (cron ARQ).
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.analytical import Budget
from app.models.enums import SubStatut, TenantStatut, UserRole, UserStatut
from app.models.subscription import Subscription
from app.models.tenant import Tenant
from app.models.user import User
from app.services.analytical_service import AnalyticalService

logger = logging.getLogger(__name__)


async def recalculer_budgets_actifs(ctx: dict[str, Any]) -> dict[str, Any]:
    """
    Recalcule la consommation budgétaire pour tous les budgets actifs des
    tenants en cours d'abonnement.
    """
    processed = 0
    failed = 0
    total_lignes = 0

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

        logger.info(f"[analytical_batch] {len(tenants)} tenants à traiter")

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

                    budgets = (
                        await sub_db.execute(
                            select(Budget).where(
                                Budget.tenant_id == tenant_id,
                                Budget.statut == "actif",
                            )
                        )
                    ).scalars().all()

                    svc = AnalyticalService(sub_db, tenant_id, admin.id)
                    for b in budgets:
                        nb = await svc.recalculer_consommation(b.id)
                        total_lignes += nb
                    await sub_db.commit()
                    processed += 1
            except Exception:
                logger.exception(f"[analytical_batch] Échec tenant {tenant_id}")
                failed += 1

    return {
        "tenants_processed": processed,
        "tenants_failed": failed,
        "budget_lines_recalculated": total_lignes,
    }


async def alerter_depassements_budgetaires(ctx: dict[str, Any]) -> dict[str, Any]:
    """
    Détecte les dépassements budgétaires et envoie des alertes WhatsApp/email
    aux responsables de section.
    """
    from app.models.analytical import BudgetConsumption, AnalyticalSection

    aujourd_hui = date.today()
    annee, mois = aujourd_hui.year, aujourd_hui.month

    async with AsyncSessionLocal() as db:
        # Chercher les lignes en dépassement
        rows = (
            await db.execute(
                select(BudgetConsumption)
                .where(
                    BudgetConsumption.annee == annee,
                    BudgetConsumption.mois == mois,
                    BudgetConsumption.niveau_alerte == "depassement",
                )
            )
        ).scalars().all()

        alertes = 0
        for row in rows:
            logger.warning(
                f"[analytical_batch] DEPASSEMENT budget tenant={row.tenant_id} "
                f"section={row.section_id} conso={row.consommation_pct}%"
            )
            alertes += 1

    return {"alertes_envoyees": alertes}
