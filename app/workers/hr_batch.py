"""
Job batch — Alertes RH : fins de CDD, périodes d'essai, anniversaires, congés.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select

from app.core.hr_syscohada import (
    JOURS_ALERTE_FIN_CDD,
    JOURS_ALERTE_FIN_PERIODE_ESSAI,
    JOURS_ALERTE_SOLDE_CONGES,
    StatutDemandeConge,
)
from app.db.session import AsyncSessionLocal
from app.models.enums import SubStatut, TenantStatut, UserRole, UserStatut
from app.models.hr import EmploymentContract, LeaveBalance, LeaveRequest
from app.models.payroll import Employee
from app.models.subscription import Subscription
from app.models.tenant import Tenant
from app.models.user import User

logger = logging.getLogger(__name__)


async def _iter_active_tenants_with_admin():
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
            admin = await db.scalar(
                select(User).where(
                    User.tenant_id == tenant_id,
                    User.role == UserRole.ADMIN_TENANT,
                    User.statut == UserStatut.ACTIF,
                ).limit(1)
            )
            if admin:
                yield tenant_id, admin.id


async def alerte_fins_cdd_et_periodes_essai(ctx: dict[str, Any]) -> dict[str, Any]:
    """
    Alerte 30j avant fin de CDD, 7j avant fin de période d'essai.
    """
    today = date.today()
    seuil_cdd = today + timedelta(days=JOURS_ALERTE_FIN_CDD)
    seuil_pe = today + timedelta(days=JOURS_ALERTE_FIN_PERIODE_ESSAI)
    alertes = 0

    async with AsyncSessionLocal() as db:
        # Fins de CDD dans 30j
        cdd_rows = (
            await db.execute(
                select(EmploymentContract).where(
                    EmploymentContract.statut == "actif",
                    EmploymentContract.date_fin.isnot(None),
                    EmploymentContract.date_fin.between(today, seuil_cdd),
                )
            )
        ).scalars().all()

        for c in cdd_rows:
            logger.warning(
                f"[hr_batch] ⚠️ Fin CDD {c.numero} dans "
                f"{(c.date_fin - today).days} jours (employé {c.employee_id})"
            )
            alertes += 1

        # Fins de période d'essai dans 7j
        pe_rows = (
            await db.execute(
                select(EmploymentContract).where(
                    EmploymentContract.statut == "actif",
                    EmploymentContract.date_fin_periode_essai.isnot(None),
                    EmploymentContract.date_fin_periode_essai.between(today, seuil_pe),
                )
            )
        ).scalars().all()

        for c in pe_rows:
            logger.warning(
                f"[hr_batch] ⚠️ Fin période d'essai {c.numero} dans "
                f"{(c.date_fin_periode_essai - today).days} jours"
            )
            alertes += 1

    return {"alertes_fins_contrat": alertes}


async def alerte_soldes_conges_faibles(ctx: dict[str, Any]) -> dict[str, Any]:
    """Alerte quand un employé a moins de 5 jours de congés restants."""
    today = date.today()
    annee = today.year
    alertes = 0

    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(LeaveBalance).where(
                    LeaveBalance.annee == annee,
                    LeaveBalance.conges_annuels_solde < JOURS_ALERTE_SOLDE_CONGES,
                )
            )
        ).scalars().all()

        for b in rows:
            logger.info(
                f"[hr_batch] Solde congés faible employé {b.employee_id} : "
                f"{float(b.conges_annuels_solde)} jours"
            )
            alertes += 1

    return {"alertes_soldes_faibles": alertes}


async def initialiser_soldes_conges_annee(ctx: dict[str, Any]) -> dict[str, Any]:
    """
    Le 1er janvier : initialise les soldes de congés pour la nouvelle année.
    """
    today = date.today()
    if today.month != 1 or today.day != 1:
        return {"skipped": True, "reason": "Not January 1st"}

    from app.services.hr_service import HRService
    processed = 0

    async with AsyncSessionLocal() as db:
        tenants = (
            await db.execute(
                select(Tenant.id)
                .join(Subscription, Subscription.tenant_id == Tenant.id)
                .where(
                    Tenant.statut == TenantStatut.ACTIF,
                    Tenant.deleted_at.is_(None),
                )
                .distinct()
            )
        ).scalars().all()

        for tenant_id in tenants:
            try:
                async with AsyncSessionLocal() as sub_db:
                    employees = (
                        await sub_db.execute(
                            select(Employee).where(
                                Employee.tenant_id == tenant_id,
                                Employee.actif.is_(True),
                            )
                        )
                    ).scalars().all()

                    svc = HRService(sub_db, tenant_id, None)
                    for emp in employees:
                        try:
                            await svc._initialiser_solde_conges(emp.id, today.year)
                        except Exception:
                            logger.exception(
                                f"[hr_batch] Échec init solde {emp.id}"
                            )
                    await sub_db.commit()
                    processed += 1
            except Exception:
                logger.exception(f"[hr_batch] Échec tenant {tenant_id}")

    return {"tenants_processed": processed, "year": today.year}
