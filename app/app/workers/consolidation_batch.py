"""
Job batch — consolidation automatique mensuelle.
À déclencher le 5 de chaque mois pour la période précédente (cron ARQ).
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.consolidation import ConsolidationGroup, GroupCompany
from app.models.enums import SubStatut, TenantStatut, UserRole, UserStatut
from app.models.subscription import Subscription
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.consolidation import ConsolidationRunRequest
from app.services.consolidation_service import ConsolidationService

logger = logging.getLogger(__name__)


async def executer_consolidations_mensuelles(ctx: dict[str, Any]) -> dict[str, Any]:
    """
    Pour chaque groupe de consolidation actif :
    1. Détermine la période (mois précédent)
    2. Lance la consolidation
    3. Log les résultats
    """
    today = date.today()
    # Mois précédent
    if today.month == 1:
        annee_prec, mois_prec = today.year - 1, 12
    else:
        annee_prec, mois_prec = today.year, today.month - 1

    date_debut = date(annee_prec, mois_prec, 1)
    if mois_prec == 12:
        date_fin = date(annee_prec, 12, 31)
    else:
        date_fin = date(annee_prec, mois_prec + 1, 1) - timedelta(days=1)

    processed = 0
    failed = 0
    runs_created = 0

    async with AsyncSessionLocal() as db:
        groups = (
            await db.execute(
                select(ConsolidationGroup).where(
                    ConsolidationGroup.actif.is_(True),
                )
            )
        ).scalars().all()

        for group in groups:
            try:
                # Trouver un admin du tenant parent
                async with AsyncSessionLocal() as sub_db:
                    admin = await sub_db.scalar(
                        select(User).where(
                            User.tenant_id == group.tenant_id,
                            User.role == UserRole.ADMIN_TENANT,
                            User.statut == UserStatut.ACTIF,
                        ).limit(1)
                    )
                    if admin is None:
                        continue

                    svc = ConsolidationService(sub_db, group.tenant_id, admin.id)
                    run = await svc.executer_consolidation(
                        group.id,
                        ConsolidationRunRequest(
                            date_debut=date_debut,
                            date_fin=date_fin,
                            appliquer_eliminations=True,
                            appliquer_retraitements=True,
                            convertir_devises=True,
                            generer_notes=True,
                        ),
                    )
                    await sub_db.commit()
                    runs_created += 1
                    processed += 1

                    logger.info(
                        f"[consolidation_batch] Run {run.reference} pour "
                        f"{group.code} : {run.nb_societes} sociétés, "
                        f"CA={run.chiffre_affaires_consolide:,} FCFA"
                    )
            except Exception:
                logger.exception(
                    f"[consolidation_batch] Échec groupe {group.code}"
                )
                failed += 1

    return {
        "period": f"{date_debut}→{date_fin}",
        "groups_processed": processed,
        "groups_failed": failed,
        "runs_created": runs_created,
    }
