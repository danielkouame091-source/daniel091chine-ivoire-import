"""
Service Tickets de support.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.formation_syscohada import (
    PrioriteTicket,
    StatutTicket,
    TypeTicket,
)
from app.models.formation import SupportTicket, TicketMessage
from app.models.user import User
from app.schemas.formation import (
    SupportAnalyticsOut,
    TicketCreate,
    TicketMessageCreate,
    TicketResolveIn,
    TicketSatisfactionIn,
    TicketUpdate,
)
from app.services.audit_service import AuditService

logger = logging.getLogger(__name__)


# SLA par priorité (heures de première réponse / heures de résolution)
SLA_PAR_PRIORITE: dict[str, tuple[int, int]] = {
    PrioriteTicket.BASSE: (48, 240),        # 48h / 10 jours
    PrioriteTicket.NORMALE: (24, 120),      # 24h / 5 jours
    PrioriteTicket.HAUTE: (8, 48),          # 8h / 2 jours
    PrioriteTicket.URGENTE: (4, 24),        # 4h / 1 jour
    PrioriteTicket.CRITIQUE: (1, 8),        # 1h / 8h
}


class SupportTicketService:
    def __init__(self, db: AsyncSession, tenant_id: UUID, user_id: UUID) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.audit = AuditService(db)

    # ═════════════════════════════════════════════════════════════════════
    # CRÉATION TICKET
    # ═════════════════════════════════════════════════════════════════════
    async def creer_ticket(self, data: TicketCreate) -> SupportTicket:
        # Référence auto
        count = int(await self.db.scalar(
            select(func.count(SupportTicket.id)).where(
                SupportTicket.tenant_id == self.tenant_id
            )
        ) or 0)
        year = datetime.now(timezone.utc).year
        reference = f"TKT-{year}-{count + 1:05d}"

        # SLA
        sla_h, _ = SLA_PAR_PRIORITE.get(data.priorite, (24, 120))
        sla_cible_at = datetime.now(timezone.utc) + timedelta(hours=sla_h)

        ticket = SupportTicket(
            tenant_id=self.tenant_id,
            reference=reference,
            sujet=data.sujet,
            description=data.description,
            type_ticket=data.type_ticket,
            priorite=data.priorite,
            statut=StatutTicket.NOUVEAU,
            canal=data.canal,
            categorie=data.categorie,
            module_concerne=data.module_concerne,
            email_contact=data.email_contact,
            pieces_jointes=data.pieces_jointes,
            sla_cible_at=sla_cible_at,
            created_by_user_id=self.user_id,
        )
        self.db.add(ticket)
        await self.db.flush()

        # Message initial
        self.db.add(TicketMessage(
            ticket_id=ticket.id,
            auteur_user_id=self.user_id,
            auteur_type="client",
            contenu=data.description,
            pieces_jointes=data.pieces_jointes,
        ))
        await self.db.flush()

        await self.audit.log(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            action="TICKET_CREATE",
            ressource="support_ticket",
            ressource_id=ticket.id,
            payload={
                "reference": reference,
                "priorite": ticket.priorite,
                "type": ticket.type_ticket,
            },
        )
        return ticket

    # ═════════════════════════════════════════════════════════════════════
    # LECTURE
    # ═════════════════════════════════════════════════════════════════════
    async def lister_tickets(
        self,
        statut: str | None = None,
        priorite: str | None = None,
        assigne_a: UUID | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[SupportTicket]:
        stmt = select(SupportTicket).where(SupportTicket.tenant_id == self.tenant_id)
        if statut:
            stmt = stmt.where(SupportTicket.statut == statut)
        if priorite:
            stmt = stmt.where(SupportTicket.priorite == priorite)
        if assigne_a:
            stmt = stmt.where(SupportTicket.assigne_a_user_id == assigne_a)
        stmt = stmt.order_by(desc(SupportTicket.created_at)).limit(limit).offset(offset)
        return list((await self.db.execute(stmt)).scalars().all())

    async def get_ticket_detail(self, ticket_id: UUID) -> SupportTicket:
        ticket = await self.db.scalar(
            select(SupportTicket).where(
                SupportTicket.id == ticket_id,
                SupportTicket.tenant_id == self.tenant_id,
            )
        )
        if ticket is None:
            raise HTTPException(404, "Ticket introuvable")
        return ticket

    async def lister_messages(
        self, ticket_id: UUID, inclure_interne: bool = False
    ) -> list[TicketMessage]:
        stmt = select(TicketMessage).where(TicketMessage.ticket_id == ticket_id)
        if not inclure_interne:
            stmt = stmt.where(TicketMessage.interne.is_(False))
        stmt = stmt.order_by(TicketMessage.created_at)
        return list((await self.db.execute(stmt)).scalars().all())

    # ═════════════════════════════════════════════════════════════════════
    # MISE À JOUR
    # ═════════════════════════════════════════════════════════════════════
    async def modifier_ticket(self, ticket_id: UUID, data: TicketUpdate) -> SupportTicket:
        ticket = await self.get_ticket_detail(ticket_id)

        old_priorite = ticket.priorite
        for k, v in data.model_dump(exclude_unset=True).items():
            setattr(ticket, k, v)

        # Si priorité change, recalculer le SLA
        if data.priorite and data.priorite != old_priorite:
            sla_h, _ = SLA_PAR_PRIORITE.get(data.priorite, (24, 120))
            ticket.sla_cible_at = datetime.now(timezone.utc) + timedelta(hours=sla_h)

        await self.db.flush()
        return ticket

    async def ajouter_message(
        self, ticket_id: UUID, data: TicketMessageCreate, auteur_type: str = "client"
    ) -> TicketMessage:
        ticket = await self.get_ticket_detail(ticket_id)

        msg = TicketMessage(
            ticket_id=ticket.id,
            auteur_user_id=self.user_id,
            auteur_type=auteur_type,
            contenu=data.contenu,
            interne=data.interne,
            pieces_jointes=data.pieces_jointes,
        )
        self.db.add(msg)

        # Si première réponse du support, enregistrer premier_reponse_at
        if auteur_type == "support" and ticket.premier_reponse_at is None:
            ticket.premier_reponse_at = datetime.now(timezone.utc)

        # Basculer le statut si nouveau
        if ticket.statut == StatutTicket.NOUVEAU and auteur_type == "support":
            ticket.statut = StatutTicket.EN_COURS

        await self.db.flush()
        return msg

    async def assigner_ticket(self, ticket_id: UUID, user_id: UUID) -> SupportTicket:
        ticket = await self.get_ticket_detail(ticket_id)
        ticket.assigne_a_user_id = user_id
        if ticket.statut == StatutTicket.NOUVEAU:
            ticket.statut = StatutTicket.EN_COURS
        await self.db.flush()
        return ticket

    async def resoudre_ticket(self, ticket_id: UUID, data: TicketResolveIn) -> SupportTicket:
        ticket = await self.get_ticket_detail(ticket_id)
        ticket.statut = StatutTicket.RESOLU
        ticket.resolution = data.resolution
        ticket.resolu_at = datetime.now(timezone.utc)
        ticket.resolu_par_user_id = self.user_id
        await self.db.flush()

        # Ajouter le message de résolution
        self.db.add(TicketMessage(
            ticket_id=ticket.id,
            auteur_user_id=self.user_id,
            auteur_type="system",
            contenu=f"✅ Ticket résolu : {data.resolution}",
        ))
        await self.db.flush()

        await self.audit.log(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            action="TICKET_RESOLVE",
            ressource="support_ticket",
            ressource_id=ticket.id,
            payload={"resolution": data.resolution},
        )
        return ticket

    async def fermer_ticket(self, ticket_id: UUID) -> SupportTicket:
        ticket = await self.get_ticket_detail(ticket_id)
        if ticket.statut not in (StatutTicket.RESOLU, StatutTicket.EN_ATTENTE_CLIENT):
            raise HTTPException(400, "Seul un ticket résolu peut être fermé")
        ticket.statut = StatutTicket.FERME
        await self.db.flush()
        return ticket

    async def noter_satisfaction(
        self, ticket_id: UUID, data: TicketSatisfactionIn
    ) -> SupportTicket:
        ticket = await self.get_ticket_detail(ticket_id)
        ticket.satisfaction = data.note
        ticket.satisfaction_commentaire = data.commentaire
        await self.db.flush()
        return ticket

    # ═════════════════════════════════════════════════════════════════════
    # SLA — Vérification et escalade
    # ═════════════════════════════════════════════════════════════════════
    async def verifier_sla(self) -> dict[str, int]:
        """
        Vérifie les SLA des tickets ouverts et marque ceux dépassés.
        Appelé par le worker nocturne.
        """
        now = datetime.now(timezone.utc)

        # Tickets dont le SLA est dépassé et non encore marqués
        rows = (
            await self.db.execute(
                select(SupportTicket).where(
                    SupportTicket.tenant_id == self.tenant_id,
                    SupportTicket.statut.in_([
                        StatutTicket.NOUVEAU,
                        StatutTicket.EN_COURS,
                        StatutTicket.EN_ATTENTE_CLIENT,
                    ]),
                    SupportTicket.sla_depasse.is_(False),
                    SupportTicket.sla_cible_at < now,
                )
            )
        ).scalars().all()

        for t in rows:
            t.sla_depasse = True
            logger.warning(
                f"[support] SLA DÉPASSÉ ticket {t.reference} "
                f"(priorité {t.priorite}, cible {t.sla_cible_at})"
            )

        await self.db.flush()
        return {"sla_depasses_marques": len(rows)}

    # ═════════════════════════════════════════════════════════════════════
    # ANALYTICS
    # ═════════════════════════════════════════════════════════════════════
    async def analytics(
        self, debut: datetime, fin: datetime
    ) -> SupportAnalyticsOut:
        from app.models.formation import ChatbotConversation, UserArticleProgress

        # Tickets
        nb_crees = int(await self.db.scalar(
            select(func.count(SupportTicket.id)).where(
                SupportTicket.tenant_id == self.tenant_id,
                SupportTicket.created_at.between(debut, fin),
            )
        ) or 0)
        nb_resolus = int(await self.db.scalar(
            select(func.count(SupportTicket.id)).where(
                SupportTicket.tenant_id == self.tenant_id,
                SupportTicket.resolu_at.between(debut, fin),
            )
        ) or 0)
        nb_ouverts = int(await self.db.scalar(
            select(func.count(SupportTicket.id)).where(
                SupportTicket.tenant_id == self.tenant_id,
                SupportTicket.statut.in_([StatutTicket.NOUVEAU, StatutTicket.EN_COURS]),
            )
        ) or 0)

        # Temps moyen première réponse
        tpr = await self.db.scalar(
            select(func.avg(
                func.extract("epoch", SupportTicket.premier_reponse_at - SupportTicket.created_at)
            )).where(
                SupportTicket.tenant_id == self.tenant_id,
                SupportTicket.premier_reponse_at.isnot(None),
                SupportTicket.created_at.between(debut, fin),
            )
        )
        tpr_min = float(tpr or 0) / 60

        # Temps moyen de résolution
        tr = await self.db.scalar(
            select(func.avg(
                func.extract("epoch", SupportTicket.resolu_at - SupportTicket.created_at)
            )).where(
                SupportTicket.tenant_id == self.tenant_id,
                SupportTicket.resolu_at.isnot(None),
                SupportTicket.created_at.between(debut, fin),
            )
        )
        tr_h = float(tr or 0) / 3600

        # Taux de résolution
        taux_res = (nb_resolus / nb_crees * 100) if nb_crees > 0 else 0.0

        # Satisfaction
        sat = await self.db.scalar(
            select(func.avg(SupportTicket.satisfaction)).where(
                SupportTicket.tenant_id == self.tenant_id,
                SupportTicket.satisfaction.isnot(None),
                SupportTicket.created_at.between(debut, fin),
            )
        )

        # Chatbot
        nb_conv = int(await self.db.scalar(
            select(func.count(ChatbotConversation.id)).where(
                ChatbotConversation.tenant_id == self.tenant_id,
                ChatbotConversation.created_at.between(debut, fin),
            )
        ) or 0)
        nb_conv_resolues = int(await self.db.scalar(
            select(func.count(ChatbotConversation.id)).where(
                ChatbotConversation.tenant_id == self.tenant_id,
                ChatbotConversation.resolu.is_(True),
                ChatbotConversation.created_at.between(debut, fin),
            )
        ) or 0)
        taux_chatbot = (nb_conv_resolues / nb_conv * 100) if nb_conv > 0 else 0.0

        # Top articles consultés
        top_articles_rows = (
            await self.db.execute(
                select(Article.id, Article.slug, Article.titre, Article.nb_vues)
                .where(Article.statut == "publie")
                .order_by(desc(Article.nb_vues))
                .limit(10)
            )
        ).all()
        top_articles = [
            {"id": str(r.id), "slug": r.slug, "titre": r.titre, "nb_vues": int(r.nb_vues)}
            for r in top_articles_rows
        ]

        # Top catégories de tickets
        top_cat_rows = (
            await self.db.execute(
                select(SupportTicket.categorie, func.count(SupportTicket.id).label("n"))
                .where(
                    SupportTicket.tenant_id == self.tenant_id,
                    SupportTicket.categorie.isnot(None),
                    SupportTicket.created_at.between(debut, fin),
                )
                .group_by(SupportTicket.categorie)
                .order_by(desc("n"))
                .limit(5)
            )
        ).all()
        top_cat = [{"categorie": r.categorie, "nb": int(r.n)} for r in top_cat_rows]

        # Répartition par priorité
        prio_rows = (
            await self.db.execute(
                select(SupportTicket.priorite, func.count(SupportTicket.id))
                .where(
                    SupportTicket.tenant_id == self.tenant_id,
                    SupportTicket.created_at.between(debut, fin),
                )
                .group_by(SupportTicket.priorite)
            )
        ).all()
        repartition_priorite = {r[0]: int(r[1]) for r in prio_rows}

        return SupportAnalyticsOut(
            tenant_id=self.tenant_id,
            periode_debut=debut,
            periode_fin=fin,
            nb_tickets_crees=nb_crees,
            nb_tickets_resolus=nb_resolus,
            nb_tickets_ouverts=nb_ouverts,
            temps_premier_reponse_moyen_min=round(tpr_min, 2),
            temps_resolution_moyen_h=round(tr_h, 2),
            taux_resolution_pct=round(taux_res, 2),
            satisfaction_moyenne=round(float(sat), 2) if sat else 0.0,
            nb_conversations_chatbot=nb_conv,
            taux_resolution_chatbot_pct=round(taux_chatbot, 2),
            top_articles_consultes=top_articles,
            top_categories_tickets=top_cat,
            repartition_par_priorite=repartition_priorite,
        )
