"""
Job batch — gestion FNE :
1. Retry des certifications en échec (statut ERROR ou EN_ATTENTE)
2. Synchronisation des soldes de stickers
3. Alerte si solde faible
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.core.fne_syscohada import FneStatut
from app.db.session import AsyncSessionLocal
from app.models.enums import SubStatut, TenantStatut, UserRole, UserStatut
from app.models.fne import FneInvoice, FneStickerBalance
from app.models.subscription import Subscription
from app.models.tenant import Tenant
from app.models.user import User
from app.services.fne_service import FneService

logger = logging.getLogger(__name__)


async def retry_certifications_fne(ctx: dict[str, Any]) -> dict[str, Any]:
    """
    Reprend les certifications en échec ou en attente depuis plus de 5 minutes.
    """
    processed = 0
    succeeded = 0
    failed = 0

    async with AsyncSessionLocal() as db:
        # Certifications en échec ou en attente
        stmt = select(FneInvoice).where(
            FneInvoice.statut.in_([FneStatut.ERROR, FneStatut.EN_ATTENTE]),
            FneInvoice.nb_tentatives < 5,
            FneInvoice.date_soumission <= datetime.now(timezone.utc) - timedelta(minutes=5),
        ).limit(100)

        rows = (await db.execute(stmt)).scalars().all()
        logger.info(f"[fne_batch] {len(rows)} certifications à retenter")

        for fne_inv in rows:
            try:
                # Trouver un admin du tenant
                admin = await db.scalar(
                    select(User).where(
                        User.tenant_id == fne_inv.tenant_id,
                        User.role == UserRole.ADMIN_TENANT,
                        User.statut == UserStatut.ACTIF,
                    ).limit(1)
                )
                if admin is None:
                    continue

                svc = FneService(db, fne_inv.tenant_id, admin.id)
                # Reconstruire le payload et retenter
                # (on réutilise le payload stocké)
                from app.integrations.fne_client import get_fne_client, FneApiError
                config = await svc.get_configuration_active()
                client = get_fne_client(
                    base_url=config.base_url, api_key=config.api_key,
                    environnement=config.environnement, entity_id=config.entity_id,
                )

                payload = fne_inv.payload_envoye or {}
                fne_inv.nb_tentatives += 1

                try:
                    response = await client.certifier_facture(payload)
                    await svc._appliquer_reponse_certification(fne_inv, response, config)
                    await svc._consommer_sticker(1)
                    succeeded += 1
                except FneApiError as exc:
                    fne_inv.derniere_erreur = f"[{exc.status_code}] {exc}"
                    failed += 1

                await db.commit()
                processed += 1
            except Exception:
                logger.exception(f"[fne_batch] Échec retry {fne_inv.id}")
                await db.rollback()
                failed += 1

    return {"processed": processed, "succeeded": succeeded, "failed": failed}


async def sync_stickers_et_alerter(ctx: dict[str, Any]) -> dict[str, Any]:
    """
    Synchronise les soldes de stickers de tous les tenants actifs
    et alerte si le solde est bas.
    """
    synced = 0
    alerts = 0

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

                    svc = FneService(sub_db, tenant_id, admin.id)
                    try:
                        balance = await svc.synchroniser_balance_stickers()
                        synced += 1
                        if balance.balance_total <= balance.seuil_alerte:
                            logger.warning(
                                f"[fne_batch] ⚠️ Solde stickers faible "
                                f"tenant={tenant_id} : {balance.balance_total}"
                            )
                            alerts += 1
                    except Exception:
                        logger.debug(f"[fne_batch] Pas de config FNE pour {tenant_id}")
                    await sub_db.commit()
            except Exception:
                logger.exception(f"[fne_batch] Échec sync tenant {tenant_id}")

    return {"tenants_synced": synced, "alerts_envoyees": alerts}
