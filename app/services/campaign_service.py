"""
Service Campagnes — Envoi groupé de notifications marketing.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.notification_syscohada import (
    Canal,
    StatutCampagne,
    TypeTemplate,
)
from app.models.notification import (
    Notification,
    NotificationCampaign,
    NotificationTemplate,
)
from app.models.user import User
from app.schemas.notification import CampaignCreate, CampaignUpdate
from app.services.audit_service import AuditService
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)


class CampaignService:
    def __init__(self, db: AsyncSession, tenant_id: UUID, user_id: UUID) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.audit = AuditService(db)
        self.notif_svc = NotificationService(db, tenant_id, user_id)

    # ═════════════════════════════════════════════════════════════════════
    # CRÉATION
    # ═════════════════════════════════════════════════════════════════════
    async def creer_campagne(self, data: CampaignCreate) -> NotificationCampaign:
        # Vérifier template
        tpl = await self.db.scalar(
            select(NotificationTemplate).where(
                NotificationTemplate.id == data.template_id,
                or_(
                    NotificationTemplate.tenant_id == self.tenant_id,
                    NotificationTemplate.tenant_id.is_(None),
                ),
            )
        )
        if tpl is None:
            raise HTTPException(404, "Template introuvable")

        # Vérifier code unique
        existing = await self.db.scalar(
            select(NotificationCampaign.id).where(
                NotificationCampaign.tenant_id == self.tenant_id,
                NotificationCampaign.code == data.code,
            )
        )
        if existing:
            raise HTTPException(409, f"Campagne {data.code} déjà existante")

        campaign = NotificationCampaign(
            tenant_id=self.tenant_id,
            statut=StatutCampagne.BROUILLON,
            created_by_user_id=self.user_id,
            **data.model_dump(),
        )
        self.db.add(campaign)
        await self.db.flush()

        # Compter les cibles
        cibles = await self._resoudre_cibles(campaign)
        campaign.nb_cibles = len(cibles)

        await self.audit.log(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            action="CAMPAIGN_CREATE",
            ressource="notification_campaign",
            ressource_id=campaign.id,
            payload={"code": campaign.code, "nb_cibles": campaign.nb_cibles},
        )
        await self.db.flush()
        return campaign

    async def modifier_campagne(
        self, campaign_id: UUID, data: CampaignUpdate
    ) -> NotificationCampaign:
        c = await self._get_campaign(campaign_id)
        if c.statut == StatutCampagne.TERMINEE:
            raise HTTPException(400, "Campagne terminée — non modifiable")

        for k, v in data.model_dump(exclude_unset=True).items():
            setattr(c, k, v)

        # Recalculer les cibles si segments modifiés
        if data.segments is not None:
            cibles = await self._resoudre_cibles(c)
            c.nb_cibles = len(cibles)

        await self.db.flush()
        return c

    # ═════════════════════════════════════════════════════════════════════
    # ENVOI
    # ═════════════════════════════════════════════════════════════════════
    async def lancer_campagne(
        self, campaign_id: UUID, batch_size: int = 500
    ) -> dict[str, Any]:
        """
        Lance une campagne : crée les notifications pour chaque cible.
        Traitement par lots pour éviter les timeouts.
        """
        campaign = await self._get_campaign(campaign_id)
        if campaign.statut not in (StatutCampagne.BROUILLON, StatutCampagne.PLANIFIEE, StatutCampagne.PAUSE):
            raise HTTPException(400, f"Campagne {campaign.statut} — non lançable")

        campaign.statut = StatutCampagne.EN_COURS
        campaign.demarree_at = datetime.now(timezone.utc)
        await self.db.flush()

        # Résoudre les cibles
        cibles = await self._resoudre_cibles(campaign)
        campaign.nb_cibles = len(cibles)

        # Template
        tpl = await self.db.scalar(
            select(NotificationTemplate).where(NotificationTemplate.id == campaign.template_id)
        )
        if tpl is None:
            raise HTTPException(404, "Template introuvable")

        nb_queued = 0
        nb_erreurs = 0
        nb_suppressed = 0

        for i, cible in enumerate(cibles):
            try:
                contexte = self._construire_contexte(cible, campaign)
                from app.schemas.notification import SendNotificationIn
                notif = await self.notif_svc.envoyer(SendNotificationIn(
                    user_id=cible.get("user_id"),
                    canal=campaign.canal,
                    type_notification=tpl.type_notification or "campaign",
                    criticite="info",   # Marketing = info
                    template_code=tpl.code,
                    contexte=contexte,
                    cible_type="campaign",
                    cible_id=campaign.id,
                ))
                notif.campaign_id = campaign.id
                if notif.statut == "suppressed":
                    nb_suppressed += 1
                else:
                    nb_queued += 1
            except HTTPException as exc:
                if exc.status_code == 429:
                    # Rate limit → arrêter et reprendre plus tard
                    logger.warning(f"[campaign] Rate limit atteint après {i} cibles")
                    break
                nb_erreurs += 1
            except Exception:
                logger.exception(f"[campaign] Échec cible {cible.get('user_id')}")
                nb_erreurs += 1

        campaign.nb_envoyes = nb_queued
        campaign.nb_erreurs = nb_erreurs
        campaign.nb_desabonnements = nb_suppressed

        # Marquer terminée
        if nb_queued + nb_erreurs + nb_suppressed >= campaign.nb_cibles:
            campaign.statut = StatutCampagne.TERMINEE
            campaign.terminee_at = datetime.now(timezone.utc)

        await self.db.flush()

        await self.audit.log(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            action="CAMPAIGN_LAUNCH",
            ressource="notification_campaign",
            ressource_id=campaign.id,
            payload={
                "nb_queued": nb_queued,
                "nb_erreurs": nb_erreurs,
                "nb_suppressed": nb_suppressed,
            },
        )

        return {
            "campaign_id": str(campaign.id),
            "nb_cibles": campaign.nb_cibles,
            "nb_queued": nb_queued,
            "nb_suppressed": nb_suppressed,
            "nb_erreurs": nb_erreurs,
        }

    async def pause_campagne(self, campaign_id: UUID) -> NotificationCampaign:
        c = await self._get_campaign(campaign_id)
        if c.statut != StatutCampagne.EN_COURS:
            raise HTTPException(400, "Seule une campagne en cours peut être mise en pause")
        c.statut = StatutCampagne.PAUSE
        await self.db.flush()
        return c

    async def annuler_campagne(self, campaign_id: UUID) -> NotificationCampaign:
        c = await self._get_campaign(campaign_id)
        if c.statut == StatutCampagne.TERMINEE:
            raise HTTPException(400, "Campagne déjà terminée")
        c.statut = StatutCampagne.ANNULEE
        await self.db.flush()
        return c

    # ═════════════════════════════════════════════════════════════════════
    # CIBLAGE
    # ═════════════════════════════════════════════════════════════════════
    async def _resoudre_cibles(self, campaign: NotificationCampaign) -> list[dict[str, Any]]:
        """
        Résout la liste des destinataires selon les segments.
        Supporte : rôles, statut, dernière connexion, plan abonnement...
        """
        segments = campaign.segments or {}
        stmt = select(User).where(
            User.tenant_id == self.tenant_id,
            User.deleted_at.is_(None),
        )

        # Filtre par rôle
        if roles := segments.get("roles"):
            stmt = stmt.where(User.role.in_(roles))

        # Filtre par statut
        if statut := segments.get("statut"):
            stmt = stmt.where(User.statut == statut)

        # Filtre par date de connexion
        if apres := segments.get("derniere_connexion_apres"):
            stmt = stmt.where(User.derniere_connexion >= apres)

        # Filtre opt-in marketing
        if segments.get("marketing_opt_in", True):
            # À terme : jointure sur consentements
            pass

        # Limite
        limit = segments.get("limit", 10000)
        stmt = stmt.limit(limit)

        users = list((await self.db.execute(stmt)).scalars().all())
        return [{"user_id": u.id, "user": u} for u in users]

    def _construire_contexte(
        self, cible: dict[str, Any], campaign: NotificationCampaign
    ) -> dict[str, Any]:
        user = cible.get("user")
        return {
            "prenom": user.nom_complet.split()[0] if user and user.nom_complet else "Client",
            "nom": user.nom_complet if user else "",
            "email": user.email if user else "",
            "lien_desabonnement": f"https://app.mtech.ci/unsubscribe?uid={user.id if user else ''}",
            **(campaign.metadata_ or {}),
        }

    # ═════════════════════════════════════════════════════════════════════
    # STATS
    # ═════════════════════════════════════════════════════════════════════
    async def stats_campagne(self, campaign_id: UUID) -> dict[str, Any]:
        c = await self._get_campaign(campaign_id)
        # Recalculer les stats réelles depuis les notifications
        rows = (
            await self.db.execute(
                select(
                    func.count(Notification.id).label("total"),
                    func.count(Notification.delivered_at).label("livres"),
                    func.count(Notification.read_at).label("ouverts"),
                    func.count(Notification.clicked_at).label("clics"),
                    func.count(Notification.failed_at).label("erreurs"),
                    func.coalesce(func.sum(Notification.cout_xof), 0).label("cout"),
                )
                .where(Notification.campaign_id == campaign_id)
            )
        ).one()

        total = int(rows.total or 0)
        livres = int(rows.livres or 0)
        ouverts = int(rows.ouverts or 0)
        clics = int(rows.clics or 0)
        erreurs = int(rows.erreurs or 0)
        cout = int(rows.cout or 0)

        return {
            "campaign_id": str(campaign_id),
            "nb_cibles": c.nb_cibles,
            "nb_envoyes": total,
            "nb_livres": livres,
            "nb_ouverts": ouverts,
            "nb_clics": clics,
            "nb_erreurs": erreurs,
            "taux_delivrabilite_pct": round(livres / total * 100, 2) if total else 0.0,
            "taux_ouverture_pct": round(ouverts / livres * 100, 2) if livres else 0.0,
            "taux_clic_pct": round(clics / ouverts * 100, 2) if ouverts else 0.0,
            "taux_erreur_pct": round(erreurs / total * 100, 2) if total else 0.0,
            "cout_total_xof": cout,
            "cout_par_envoi_xof": round(cout / total, 2) if total else 0.0,
        }

    # ═════════════════════════════════════════════════════════════════════
    # HELPERS
    # ═════════════════════════════════════════════════════════════════════
    async def _get_campaign(self, campaign_id: UUID) -> NotificationCampaign:
        c = await self.db.scalar(
            select(NotificationCampaign).where(
                NotificationCampaign.id == campaign_id,
                NotificationCampaign.tenant_id == self.tenant_id,
            )
        )
        if c is None:
            raise HTTPException(404, "Campagne introuvable")
        return c
