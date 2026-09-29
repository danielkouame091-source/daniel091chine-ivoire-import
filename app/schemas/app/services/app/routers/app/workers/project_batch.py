"""
Job batch — Alertes projets & recalcul d'avancement.
À déclencher quotidiennement (cron ARQ).
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select

from app.core.project_syscohada import NiveauAlerteProjet, StatutProjet
from app.db.session import AsyncSessionLocal
from app.models.enums import SubStatut, TenantStatut, UserRole, UserStatut
from app.models.project import Project
from app.models.subscription import Subscription
from app.models.tenant import Tenant
from app.models.user import User
from app.services.project_service import ProjectService

logger = logging.getLogger(__name__)


async def recalculer_avancements_et_alertes(ctx: dict[str, Any]) -> dict[str, Any]:
    """
    Recalcule l'avancement de tous les projets actifs et envoie des alertes
    si nécessaire.
    """
    processed = 0
    alertes_retard = 0
    alertes_depassement = 0

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

                    svc = ProjectService(sub_db, tenant_id, admin.id)

                    # Projets actifs
                    projets = (
                        await sub_db.execute(
                            select(Project).where(
                                Project.tenant_id == tenant_id,
                                Project.statut.in_([StatutProjet.EN_COURS, StatutProjet.EN_PAUSE]),
                            )
                        )
                    ).scalars().all()

                    for p in projets:
                        await svc._recalculer_avancement_physique(p.id)
                        await svc._recalculer_alerte(p)

                        if p.est_en_retard:
                            logger.warning(
                                f"[project_batch] Projet {p.code} EN RETARD "
                                f"(échéance {p.date_fin_prevue}, avct {p.pourcentage_avancement_physique}%)"
                            )
                            alertes_retard += 1
                        if p.niveau_alerte == NiveauAlerteProjet.CRITIQUE:
                            logger.warning(
                                f"[project_batch] Projet {p.code} DÉPASSEMENT BUDGET "
                                f"({p.budget_realise}/{p.budget_previsionnel_ht})"
                            )
                            alertes_depassement += 1

                    await sub_db.commit()
                    processed += 1
            except Exception:
                logger.exception(f"[project_batch] Échec tenant {tenant_id}")

    return {
        "tenants_processed": processed,
        "alertes_retard": alertes_retard,
        "alertes_depassement": alertes_depassement,
    }


async def liberer_retenues_garantie(ctx: dict[str, Any]) -> dict[str, Any]:
    """
    Libère les retenues de garantie dont le délai de garantie est écoulé.
    """
    from datetime import timedelta as _td

    liberees = 0
    async with AsyncSessionLocal() as db:
        # Trouver les projets terminés il y a plus de 12 mois
        seuil = date.today() - _td(days=365)
        rows = (
            await db.execute(
                select(Project).where(
                    Project.statut == StatutProjet.TERMINE,
                    Project.retenue_garantie_montant > 0,
                    Project.retenue_garantie_liberee.is_(False),
                    Project.date_fin_reelle.isnot(None),
                    Project.date_fin_reelle <= seuil,
                )
            )
        ).scalars().all()

        for p in rows:
            p.retenue_garantie_liberee = True
            liberees += 1
            logger.info(
                f"[project_batch] Retenue libérée projet {p.code} : "
                f"{p.retenue_garantie_montant:,} FCFA".replace(",", " ")
            )

        await db.commit()

    return {"retenues_liberees": liberees}
