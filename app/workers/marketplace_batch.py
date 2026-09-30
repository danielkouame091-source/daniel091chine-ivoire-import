"""
Worker batch — Exécution hooks plugin, suspensions auto, expirations.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import and_, select, update

from app.core.marketplace_syscohada import (
    SEUIL_ERREURS_SUSPENSION,
    SEUIL_SIGNALEMENTS_SUSPENSION,
    StatutExtension,
    StatutInstallation,
)
from app.db.session import AsyncSessionLocal
from app.models.marketplace import (
    Extension,
    ExtensionInstallation,
    ExtensionReport,
)
from app.services.plugin_runtime_service import PluginRuntimeService

logger = logging.getLogger(__name__)


async def executer_hook_plugin(
    ctx: dict[str, Any],
    installation_id: str,
    tenant_id: str,
    hook_event: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Exécution d'un hook plugin en background."""
    inst_uuid = UUID(installation_id)
    tenant_uuid = UUID(tenant_id)

    async with AsyncSessionLocal() as db:
        svc = PluginRuntimeService(db)
        result = await svc.executer_hook(
            inst_uuid, tenant_uuid, hook_event, payload,
        )
        await db.commit()

        if not result.get("ok"):
            logger.warning(
                f"[marketplace_batch] Hook {hook_event} échoué pour "
                f"installation {installation_id} : {result}"
            )
        return result


async def suspendre_extensions_problematiques(ctx: dict[str, Any]) -> dict[str, Any]:
    """
    Suspend automatiquement les extensions ayant :
    - ≥ 5 signalements non traités
    - ≥ 50 erreurs/heure cumulées
    """
    susp_count = 0

    async with AsyncSessionLocal() as db:
        # Signalements
        rows = (
            await db.execute(
                select(ExtensionReport.extension_id)
                .where(ExtensionReport.statut == "nouveau")
                .group_by(ExtensionReport.extension_id)
                .having(
                    __import__("sqlalchemy").func.count(ExtensionReport.id) >= SEUIL_SIGNALEMENTS_SUSPENSION
                )
            )
        ).all()

        for (ext_id,) in rows:
            ext = await db.scalar(select(Extension).where(Extension.id == ext_id))
            if ext and ext.statut == StatutExtension.APPROUVEE:
                ext.statut = StatutExtension.SUSPENDUE
                susp_count += 1
                logger.warning(
                    f"[marketplace_batch] Extension {ext.slug} suspendue "
                    f"({SEUIL_SIGNALEMENTS_SUSPENSION}+ signalements)"
                )

        # Erreurs
        error_threshold_installations = (
            await db.execute(
                select(ExtensionInstallation).where(
                    ExtensionInstallation.nb_erreurs_jour >= SEUIL_ERREURS_SUSPENSION,
                    ExtensionInstallation.statut == StatutInstallation.ACTIVE,
                )
            )
        ).scalars().all()

        for inst in error_threshold_installations:
            inst.statut = StatutInstallation.ERREUR
            logger.warning(
                f"[marketplace_batch] Installation {inst.id} passée en erreur "
                f"({inst.nb_erreurs_jour} erreurs/jour)"
            )

        await db.commit()

    return {"extensions_suspendues": susp_count, "installations_en_erreur": len(error_threshold_installations)}


async def reset_compteurs_quotidiens(ctx: dict[str, Any]) -> dict[str, Any]:
    """Remet à zéro les compteurs quotidiens d'appels/erreurs."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            update(ExtensionInstallation)
            .where(
                (ExtensionInstallation.nb_appels_jour > 0)
                | (ExtensionInstallation.nb_erreurs_jour > 0)
            )
            .values(nb_appels_jour=0, nb_erreurs_jour=0)
        )
        await db.commit()
        return {"compteurs_reset": result.rowcount or 0}


async def verifier_abonnements_expires(ctx: dict[str, Any]) -> dict[str, Any]:
    """Désactive les installations dont l'abonnement a expiré."""
    today = date.today()
    expires = 0

    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(ExtensionInstallation).where(
                    ExtensionInstallation.statut == StatutInstallation.ACTIVE,
                    ExtensionInstallation.abonnement_fin.isnot(None),
                    ExtensionInstallation.abonnement_fin < today,
                )
            )
        ).scalars().all()

        for inst in rows:
            # Vérifier si en période d'essai
            if inst.essai_fin and inst.essai_fin >= today:
                continue

            inst.statut = StatutInstallation.EXPIREE
            expires += 1
            logger.info(
                f"[marketplace_batch] Installation {inst.id} expirée "
                f"(fin : {inst.abonnement_fin})"
            )

        await db.commit()
        return {"installations_expirees": expires}


async def calculer_revenus_publishers(ctx: dict[str, Any]) -> dict[str, Any]:
    """
    Calcule les revenus des publishers (mensuel).
    Appelé le 1er du mois.
    """
    from sqlalchemy import func
    from app.models.marketplace import MarketplaceTransaction, Publisher
    from app.core.marketplace_syscohada import TypeTransactionMarketplace

    today = date.today()
    mois_precedent_fin = today.replace(day=1) - timedelta(days=1)
    mois_precedent_debut = mois_precedent_fin.replace(day=1)
    debut_dt = datetime.combine(mois_precedent_debut, datetime.min.time()).replace(tzinfo=timezone.utc)
    fin_dt = datetime.combine(mois_precedent_fin, datetime.max.time()).replace(tzinfo=timezone.utc)

    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(
                    MarketplaceTransaction.publisher_id,
                    func.sum(MarketplaceTransaction.montant_publisher_xof).label("total"),
                )
                .where(
                    MarketplaceTransaction.created_at.between(debut_dt, fin_dt),
                    MarketplaceTransaction.statut == "payee",
                    MarketplaceTransaction.publisher_id.isnot(None),
                )
                .group_by(MarketplaceTransaction.publisher_id)
            )
        ).all()

        for pub_id, total in rows:
            pub = await db.scalar(select(Publisher).where(Publisher.id == pub_id))
            if pub:
                logger.info(
                    f"[marketplace_batch] Publisher {pub.slug} : "
                    f"{int(total or 0):,} XOF à reverser".replace(",", " ")
                )

        await db.commit()
        return {"publishers_traites": len(rows)}
