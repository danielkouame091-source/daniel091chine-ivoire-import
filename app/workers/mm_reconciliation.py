"""
Jobs de rapprochement Mobile Money.
- reconcile_one     : rapproche une transaction individuelle (appel synchrone rapide).
- rapprocher_batch  : traite par lots toutes les transactions non rapprochées d'un tenant.
"""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.enums import MMStatut
from app.models.mobile_money import MmTransaction
from app.services.mobile_money_service import MobileMoneyService

logger = logging.getLogger(__name__)


async def reconcile_one(
    ctx: dict[str, Any],
    tenant_id: str,
    mm_tx_id: str,
    user_id: str | None = None,
) -> dict[str, Any]:
    """
    Rapproche UNE transaction Mobile Money.
    Utilisé pour les webhooks à haute fréquence (async).
    """
    tid = UUID(tenant_id)
    txid = UUID(mm_tx_id)
    uid = UUID(user_id) if user_id else None

    async with AsyncSessionLocal() as db:
        try:
            svc = MobileMoneyService(db, tenant_id=tid)
            if uid is None:
                # Rapprochement automatique : utilise un user système (fondateur ou admin tenant)
                # Ici on prend le premier ADMIN_TENANT du tenant
                from app.models.enums import UserRole, UserStatut
                from app.models.user import User

                admin = (
                    await db.execute(
                        select(User)
                        .where(
                            User.tenant_id == tid,
                            User.role == UserRole.ADMIN_TENANT,
                            User.statut == UserStatut.ACTIF,
                        )
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if admin is None:
                    logger.warning(f"[mm] Aucun admin tenant pour {tid}")
                    return {"ok": False, "reason": "no_admin"}
                uid = admin.id

            tx = await svc.rapprocher(txid, user_id=uid)
            await db.commit()
            return {
                "ok": True,
                "mm_tx_id": str(tx.id),
                "ecriture_id": str(tx.ecriture_id) if tx.ecriture_id else None,
            }
        except Exception as exc:
            await db.rollback()
            logger.exception(f"[mm] reconcile_one échoué pour {mm_tx_id}")
            raise


async def rapprocher_batch(
    ctx: dict[str, Any],
    tenant_id: str,
    limit: int = 500,
) -> dict[str, Any]:
    """
    Rapproche en masse toutes les transactions non rapprochées d'un tenant.
    À déclencher manuellement ou via cron nocturne.
    """
    tid = UUID(tenant_id)
    processed = 0
    succeeded = 0
    failed = 0

    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(MmTransaction.id)
                .where(
                    MmTransaction.tenant_id == tid,
                    MmTransaction.statut_rappro == MMStatut.NON_RAPPROCHE,
                )
                .order_by(MmTransaction.horodatage.asc())
                .limit(limit)
            )
        ).scalars().all()

        logger.info(f"[mm] Batch tenant={tid} : {len(rows)} à traiter")

        for mm_id in rows:
            processed += 1
            try:
                async with AsyncSessionLocal() as sub_db:
                    svc = MobileMoneyService(sub_db, tenant_id=tid)
                    # user_id = None → le service doit accepter None pour auto
                    await svc.rapprocher(mm_id, user_id=None)  # type: ignore[arg-type]
                    await sub_db.commit()
                    succeeded += 1
            except Exception:
                logger.exception(f"[mm] Échec batch sur {mm_id}")
                failed += 1

    return {
        "tenant_id": str(tid),
        "processed": processed,
        "succeeded": succeeded,
        "failed": failed,
    }
