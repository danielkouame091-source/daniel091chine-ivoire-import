"""
Jobs de propagation async du gel en cascade.
Utile pour les tenants volumineux : le gel est déclenché en synchrone pour la
racine, mais les effets sur des dizaines de milliers d'écritures se font en
background pour ne pas bloquer la requête HTTP.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select, update

from app.db.session import AsyncSessionLocal
from app.models.ecriture import Ecriture
from app.models.enums import EcritureStatut, MMStatut
from app.models.freeze import FreezeEvent, FreezeTarget
from app.models.mobile_money import MmTransaction

logger = logging.getLogger(__name__)


async def propager_gel(
    ctx: dict[str, Any],
    freeze_event_id: str,
) -> dict[str, Any]:
    """
    Applique en background les effets d'un gel (UPDATE en masse).
    Appelé après la création synchrone de l'événement + cibles.
    """
    eid = UUID(freeze_event_id)
    now = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as db:
        event = (
            await db.execute(select(FreezeEvent).where(FreezeEvent.id == eid))
        ).scalar_one_or_none()
        if event is None:
            logger.warning(f"[freeze] Event {eid} introuvable")
            return {"ok": False, "reason": "event_not_found"}

        targets = (
            await db.execute(
                select(FreezeTarget).where(FreezeTarget.freeze_event_id == eid)
            )
        ).scalars().all()

        ecriture_ids = [t.cible_id for t in targets if t.cible_type.value == "ecriture"]
        mm_ids = [t.cible_id for t in targets if t.cible_type.value == "mm_transaction"]

        applied_ecr = 0
        applied_mm = 0

        if ecriture_ids:
            res = await db.execute(
                update(Ecriture)
                .where(
                    Ecriture.id.in_(ecriture_ids),
                    Ecriture.statut != EcritureStatut.GELEE,
                )
                .values(statut=EcritureStatut.GELEE)
            )
            applied_ecr = res.rowcount or 0

        if mm_ids:
            res = await db.execute(
                update(MmTransaction)
                .where(
                    MmTransaction.id.in_(mm_ids),
                    MmTransaction.statut_rappro != MMStatut.GELE,
                )
                .values(statut_rappro=MMStatut.GELE)
            )
            applied_mm = res.rowcount or 0

        await db.commit()

        logger.info(
            f"[freeze] Event {eid} : {applied_ecr} écritures + {applied_mm} MM gelés"
        )
        return {
            "freeze_event_id": str(eid),
            "ecritures_gelees": applied_ecr,
            "mm_gelee": applied_mm,
        }


async def appliquer_effets_cascade(
    ctx: dict[str, Any],
    tenant_id: str,
    source_type: str,
    source_id: str,
) -> dict[str, Any]:
    """
    Applique les effets métier d'une cascade spécifique (user → écritures).
    Appelé par FreezeService après création de l'événement racine si le volume
    est important.
    """
    tid = UUID(tenant_id)
    sid = UUID(source_id)

    async with AsyncSessionLocal() as db:
        if source_type == "user":
            res = await db.execute(
                update(Ecriture)
                .where(
                    Ecriture.tenant_id == tid,
                    Ecriture.created_by == sid,
                    Ecriture.statut != EcritureStatut.GELEE,
                )
                .values(statut=EcritureStatut.GELEE)
            )
            await db.commit()
            return {"user_id": str(sid), "ecritures_gelees": res.rowcount or 0}

        if source_type == "compte":
            from app.models.plan_comptable import PlanComptable
            from app.models.ecriture import EcritureLigne

            sub = (
                select(EcritureLigne.ecriture_id)
                .join(PlanComptable, PlanComptable.id == EcritureLigne.compte_id)
                .where(
                    EcritureLigne.tenant_id == tid,
                    PlanComptable.compte == str(sid),
                )
            )
            res = await db.execute(
                update(Ecriture)
                .where(
                    Ecriture.id.in_(sub),
                    Ecriture.statut != EcritureStatut.GELEE,
                )
                .values(statut=EcritureStatut.GELEE)
            )
            await db.commit()
            return {"compte": str(sid), "ecritures_gelees": res.rowcount or 0}

    return {"ok": False, "reason": "unsupported_source"}
