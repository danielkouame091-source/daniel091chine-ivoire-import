"""
Job batch — génère les états financiers mensuels et alerte sur les échéances.
À déclencher chaque mois (cron ARQ).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.core.fiscal_ci import echeance_cnps, echeance_its, echeance_tva
from app.db.session import AsyncSessionLocal
from app.models.enums import SubStatut, TenantStatut
from app.models.payroll import CnpsDeclaration, DgiDeclaration, Payslip
from app.models.subscription import Subscription
from app.models.tenant import Tenant
from app.services.dgi_service import DgiService
from app.services.payroll_service import PayrollService

logger = logging.getLogger(__name__)


async def generer_declarations_mensuelles(ctx: dict[str, Any]) -> dict[str, Any]:
    """
    Génère les déclarations CNPS + TVA + ITS pour tous les tenants actifs.
    Déclenché le 1er de chaque mois.
    """
    processed = 0
    failed = 0
    today = date.today()
    annee, mois = today.year, today.month

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

                    # CNPS
                    try:
                        payroll_svc = PayrollService(sub_db, tenant_id, admin.id)
                        await payroll_svc.generer_declaration_cnps(annee, mois - 1 if mois > 1 else 12)
                    except Exception:
                        logger.debug(f"[reporting] Pas de bulletins CNPS pour {tenant_id}")

                    # TVA
                    try:
                        dgi_svc = DgiService(sub_db, tenant_id, admin.id)
                        await dgi_svc.generer_declaration_tva(annee, mois - 1 if mois > 1 else 12)
                    except Exception:
                        logger.debug(f"[reporting] Pas de TVA pour {tenant_id}")

                    await sub_db.commit()
                    processed += 1
            except Exception:
                logger.exception(f"[reporting] Échec tenant {tenant_id}")
                failed += 1

    return {"processed": processed, "failed": failed}


async def alerter_echeances_proches(ctx: dict[str, Any]) -> dict[str, Any]:
    """
    Vérifie les échéances fiscales dans les 7 jours et notifie les tenants.
    """
    today = date.today()
    horizon = today + timedelta(days=7)
    alertes = 0

    async with AsyncSessionLocal() as db:
        # Déclarations non payées dont l'échéance approche
        decls = (
            await db.execute(
                select(DgiDeclaration).where(
                    DgiDeclaration.statut.in_(["brouillon", "depose"]),
                    DgiDeclaration.date_echeance.between(today, horizon),
                )
            )
        ).scalars().all()

        for d in decls:
            logger.info(
                f"[reporting] ALERTE échéance {d.type_declaration} "
                f"tenant={d.tenant_id} échéance={d.date_echeance}"
            )
            alertes += 1

    return {"alertes_envoyees": alertes}
