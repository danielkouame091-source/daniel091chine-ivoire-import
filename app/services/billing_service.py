"""
Service Billing — gestion des abonnements, renouvellement, historique paiements.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import SubPlan, SubStatut
from app.models.plan import Plan
from app.models.subscription import Subscription, SubscriptionPayment
from app.schemas.subscription import SubscriptionCreate, SubscriptionRenewIn
from app.services.audit_service import AuditService


class BillingService:
    def __init__(self, db: AsyncSession, tenant_id: UUID, user_id: UUID) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.audit = AuditService(db)

    async def create_subscription(
        self, data: SubscriptionCreate
    ) -> Subscription:
        plan = await self.db.scalar(
            select(Plan).where(Plan.code == data.plan_code)
        )
        if plan is None:
            raise HTTPException(404, f"Plan {data.plan_code.value} introuvable")

        # Clôturer l'ancien abonnement actif s'il existe
        await self.db.execute(
            select(Subscription).where(Subscription.tenant_id == self.tenant_id)
        )
        anciens = (
            await self.db.execute(
                select(Subscription).where(
                    Subscription.tenant_id == self.tenant_id,
                    Subscription.statut.in_(
                        [SubStatut.TRIAL, SubStatut.ACTIF, SubStatut.IMPAYE]
                    ),
                )
            )
        ).scalars().all()
        now = datetime.now(timezone.utc)
        for a in anciens:
            a.statut = SubStatut.RESILIE

        periode_fin = now + timedelta(days=30 * data.duree_mois)
        montant = (
            plan.prix_mensuel_xof * data.duree_mois
            if data.duree_mois < 12
            else plan.prix_annuel_xof * (data.duree_mois // 12)
        )

        sub = Subscription(
            tenant_id=self.tenant_id,
            plan_id=plan.id,
            statut=SubStatut.ACTIF,
            periode_debut=now,
            periode_fin=periode_fin,
            grace_jours=7,
            montant_xof=montant,
            devise="XOF",
            mode_paiement=data.mode_paiement,
            reference_paiement=data.reference_paiement,
            auto_renouvellement=data.auto_renouvellement,
        )
        self.db.add(sub)
        await self.db.flush()

        self.db.add(
            SubscriptionPayment(
                subscription_id=sub.id,
                tenant_id=self.tenant_id,
                montant_xof=montant,
                mode_paiement=data.mode_paiement,
                reference_externe=data.reference_paiement,
                statut="confirme",
                confirme_at=now,
            )
        )
        await self.db.flush()

        await self.audit.log(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            action="SUBSCRIPTION_CREATE",
            ressource="subscription",
            ressource_id=sub.id,
            payload={"plan": plan.code.value, "duree_mois": data.duree_mois, "montant": montant},
        )
        return sub

    async def renew(self, data: SubscriptionRenewIn) -> Subscription:
        current = await self.db.scalar(
            select(Subscription)
            .where(Subscription.tenant_id == self.tenant_id)
            .order_by(Subscription.periode_fin.desc())
            .limit(1)
        )
        if current is None:
            raise HTTPException(404, "Aucun abonnement à renouveler")

        now = datetime.now(timezone.utc)
        base = max(current.periode_fin, now) if current.periode_fin.tzinfo else now
        new_fin = base + timedelta(days=30 * data.duree_mois)

        current.periode_fin = new_fin
        current.statut = SubStatut.ACTIF
        current.mode_paiement = data.mode_paiement

        self.db.add(
            SubscriptionPayment(
                subscription_id=current.id,
                tenant_id=self.tenant_id,
                montant_xof=current.montant_xof,  # MVP : prix inchangé
                mode_paiement=data.mode_paiement,
                statut="confirme",
                confirme_at=now,
            )
        )
        await self.db.flush()

        await self.audit.log(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            action="SUBSCRIPTION_RENEW",
            ressource="subscription",
            ressource_id=current.id,
            payload={"nouvelle_fin": new_fin.isoformat()},
        )
        return current

    async def list_plans(self) -> list[Plan]:
        return list(
            (await self.db.execute(select(Plan).order_by(Plan.prix_mensuel_xof))).scalars().all()
        )
