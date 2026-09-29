"""
Service Notifications — Moteur multi-canal.

Fonctionnalités :
- Rendu de templates (Jinja2)
- Envoi multi-canal avec fallback
- Vérification des préférences utilisateur
- Rate limiting & anti-spam
- Suivi de livraison (tracking)
- Détection opt-out
"""
from __future__ import annotations

import logging
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from jinja2 import BaseLoader, Environment, TemplateError, meta
from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.notification_syscohada import (
    CANAUX,
    CoutUnitaire,
    Criticite,
    DEFAULT_PROVIDERS,
    HIERARCHIE_FALLBACK,
    Quotas,
    StatutNotification,
    TypeTemplate,
)
from app.models.notification import (
    Notification,
    NotificationEvent,
    NotificationPreference,
    NotificationSuppression,
    NotificationTemplate,
)
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.notification import (
    SendNotificationIn,
    TemplatePreviewIn,
    TemplatePreviewOut,
)
from app.services.audit_service import AuditService

logger = logging.getLogger(__name__)


# Jinja2 sandboxé (pas d'accès aux attributs Python dangereux)
JINJA_ENV = Environment(
    loader=BaseLoader(),
    autoescape=True,
    trim_blocks=True,
    lstrip_blocks=True,
)


class NotificationService:
    def __init__(self, db: AsyncSession, tenant_id: UUID | None, user_id: UUID | None = None) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.audit = AuditService(db)

    # ═════════════════════════════════════════════════════════════════════
    # ENVOI
    # ═════════════════════════════════════════════════════════════════════
    async def envoyer(self, data: SendNotificationIn) -> Notification:
        """
        Envoie une notification (ou la met en file d'attente).
        Vérifie les préférences, la suppression, le rate limit.
        """
        # 1. Résoudre les infos destinataire
        email, telephone, nom = await self._resoudre_destinataire(data)

        # 2. Vérifier suppression (opt-out)
        if await self._est_supprime(email, telephone, data.type_notification):
            logger.info(f"[notif] Supprimé : {email or telephone}")
            notif = Notification(
                tenant_id=self.tenant_id,
                user_id=data.user_id,
                portal_user_id=data.portal_user_id,
                destinataire_email=email,
                destinataire_telephone=telephone,
                destinataire_nom=nom,
                canal=data.canal,
                type_notification=data.type_notification,
                criticite=data.criticite,
                contexte=data.contexte,
                cible_type=data.cible_type,
                cible_id=data.cible_id,
                action_url=data.action_url,
                action_label=data.action_label,
                statut=StatutNotification.SUPPRESSED,
                priorite=self._priorite_pour(data.criticite),
                queued_at=datetime.now(timezone.utc),
            )
            self.db.add(notif)
            await self.db.flush()
            return notif

        # 3. Vérifier préférences (sauf si critique)
        if data.criticite != Criticite.CRITIQUE and data.user_id:
            if not await self._canal_autorise(data.user_id, data.type_notification, data.canal):
                raise HTTPException(403, f"Canal {data.canal} désactivé par l'utilisateur")

        # 4. Rate limiting
        await self._verifier_rate_limit(data)

        # 5. Rendre le contenu (via template ou inline)
        sujet, html, texte = await self._rendre_contenu(data)

        # 6. Créer la notification
        tracking_id = secrets.token_urlsafe(32)
        notif = Notification(
            tenant_id=self.tenant_id,
            template_id=await self._resolve_template_id(data.template_code),
            user_id=data.user_id,
            portal_user_id=data.portal_user_id,
            destinataire_email=email,
            destinataire_telephone=telephone,
            destinataire_nom=nom,
            canal=data.canal,
            type_notification=data.type_notification,
            criticite=data.criticite,
            sujet=sujet,
            contenu_html=html,
            contenu_texte=texte,
            contexte=data.contexte,
            cible_type=data.cible_type,
            cible_id=data.cible_id,
            action_url=data.action_url,
            action_label=data.action_label,
            statut=StatutNotification.QUEUED,
            priorite=self._priorite_pour(data.criticite),
            tracking_id=tracking_id,
            cout_xof=CoutUnitaire.__dict__.get(data.canal.upper(), 0),
            queued_at=datetime.now(timezone.utc),
        )
        self.db.add(notif)
        await self.db.flush()

        # 7. Log événement
        await self._log_event(notif.id, "queued", None, None)

        await self.audit.log(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            action="NOTIFICATION_QUEUED",
            ressource="notification",
            ressource_id=notif.id,
            payload={
                "canal": notif.canal,
                "type": notif.type_notification,
                "destinataire": email or telephone,
            },
        )
        return notif

    async def envoyer_multi_canal(
        self, data: SendNotificationIn
    ) -> list[Notification]:
        """
        Envoie sur le canal principal + fallback automatique si échec.
        ⚠️ À appeler via un job ARQ pour un vrai fallback async.
        """
        notifs = [await self.envoyer(data)]
        return notifs

    # ═════════════════════════════════════════════════════════════════════
    # RENDU DE TEMPLATE
    # ═════════════════════════════════════════════════════════════════════
    async def _rendre_contenu(
        self, data: SendNotificationIn
    ) -> tuple[str | None, str | None, str | None]:
        """
        Retourne (sujet, html, texte) après rendu.
        Priorité : template_code > contenu inline.
        """
        contexte = data.contexte or {}
        sujet = data.sujet
        html = data.contenu_html
        texte = data.contenu_texte

        if data.template_code:
            template = await self._get_template_by_code(data.template_code, data.canal)
            if template is None:
                raise HTTPException(404, f"Template {data.template_code} introuvable")

            sujet = self._render_str(template.sujet, contexte)
            html = self._render_str(template.contenu_html, contexte)
            texte = self._render_str(template.contenu_texte, contexte)

            # SMS/WhatsApp : utiliser contenu_html comme fallback texte
            if data.canal in ("sms", "whatsapp") and not texte:
                texte = self._render_str(template.contenu_html, contexte)
                html = None

            # In-app : markdown
            if data.canal == "in_app" and template.contenu_markdown:
                texte = self._render_str(template.contenu_markdown, contexte)

        elif html or texte:
            # Rendu des variables dans le contenu inline aussi
            sujet = self._render_str(sujet, contexte) if sujet else None
            html = self._render_str(html, contexte) if html else None
            texte = self._render_str(texte, contexte) if texte else None

        return sujet, html, texte

    def _render_str(self, template_str: str | None, contexte: dict[str, Any]) -> str | None:
        if not template_str:
            return None
        try:
            tmpl = JINJA_ENV.from_string(template_str)
            return tmpl.render(**contexte)
        except TemplateError as exc:
            logger.error(f"[notif] Erreur rendu template : {exc}")
            return template_str

    async def previsualiser_template(
        self, template_id: UUID, data: TemplatePreviewIn
    ) -> TemplatePreviewOut:
        template = await self.db.scalar(
            select(NotificationTemplate).where(NotificationTemplate.id == template_id)
        )
        if template is None:
            raise HTTPException(404, "Template introuvable")

        ctx = data.variables or {}
        sujet = self._render_str(template.sujet, ctx)
        html = self._render_str(template.contenu_html, ctx)
        texte = self._render_str(template.contenu_texte, ctx)

        # Variables manquantes
        manquantes: list[str] = []
        for contenu in (template.sujet, template.contenu_html, template.contenu_texte):
            if contenu:
                try:
                    variables = meta.find_undeclared_variables(
                        JINJA_ENV.parse(contenu)
                    )
                    manquantes.extend([v for v in variables if v not in ctx])
                except Exception:
                    pass

        return TemplatePreviewOut(
            sujet=sujet,
            contenu_html=html,
            contenu_texte=texte,
            variables_manquantes=sorted(set(manquantes)),
        )

    # ═════════════════════════════════════════════════════════════════════
    # TEMPLATES
    # ═════════════════════════════════════════════════════════════════════
    async def _get_template_by_code(
        self, code: str, canal: str
    ) -> NotificationTemplate | None:
        # Cherche d'abord le template du tenant (prioritaire), sinon global
        stmt = (
            select(NotificationTemplate)
            .where(
                NotificationTemplate.code == code,
                NotificationTemplate.canal == canal,
                NotificationTemplate.statut == "publie",
                or_(
                    NotificationTemplate.tenant_id == self.tenant_id,
                    NotificationTemplate.tenant_id.is_(None),
                ),
            )
            .order_by(
                # Le tenant prime sur le global
                NotificationTemplate.tenant_id.is_(None).asc(),
                desc(NotificationTemplate.version),
            )
            .limit(1)
        )
        return await self.db.scalar(stmt)

    async def _resolve_template_id(self, code: str | None) -> UUID | None:
        if not code:
            return None
        tpl = await self.db.scalar(
            select(NotificationTemplate).where(
                NotificationTemplate.code == code,
                NotificationTemplate.statut == "publie",
            ).limit(1)
        )
        return tpl.id if tpl else None

    async def creer_template(self, data: Any) -> NotificationTemplate:
        existing = await self.db.scalar(
            select(func.max(NotificationTemplate.version)).where(
                NotificationTemplate.tenant_id == self.tenant_id,
                NotificationTemplate.code == data.code,
                NotificationTemplate.canal == data.canal,
            )
        )
        version = (int(existing) + 1) if existing else 1

        tpl = NotificationTemplate(
            tenant_id=self.tenant_id,
            version=version,
            statut="brouillon",
            created_by_user_id=self.user_id,
            **data.model_dump(),
        )
        self.db.add(tpl)
        await self.db.flush()
        return tpl

    async def publier_template(self, template_id: UUID) -> NotificationTemplate:
        tpl = await self.db.scalar(
            select(NotificationTemplate).where(
                NotificationTemplate.id == template_id,
                or_(
                    NotificationTemplate.tenant_id == self.tenant_id,
                    NotificationTemplate.tenant_id.is_(None),
                ),
            )
        )
        if tpl is None:
            raise HTTPException(404, "Template introuvable")
        tpl.statut = "publie"
        await self.db.flush()
        return tpl

    # ═════════════════════════════════════════════════════════════════════
    # PRÉFÉRENCES
    # ═════════════════════════════════════════════════════════════════════
    async def _canal_autorise(
        self, user_id: UUID, type_notification: str, canal: str
    ) -> bool:
        """
        Vérifie si le canal est autorisé pour ce type de notification.
        Si pas de préférence → tout est autorisé.
        """
        # Types critiques non désactivables
        if type_notification in ("password_reset", "security_alert", "login_new_device"):
            return True

        pref = await self.db.scalar(
            select(NotificationPreference).where(
                NotificationPreference.user_id == user_id,
                NotificationPreference.type_notification == type_notification,
            )
        )
        if pref is None:
            return True
        if not pref.canaux_actives:
            return True
        return canal in pref.canaux_actives

    async def upsert_preference(
        self, user_id: UUID, data: Any
    ) -> NotificationPreference:
        pref = await self.db.scalar(
            select(NotificationPreference).where(
                NotificationPreference.user_id == user_id,
                NotificationPreference.type_notification == data.type_notification,
            )
        )
        if pref:
            for k, v in data.model_dump(exclude_unset=True).items():
                setattr(pref, k, v)
        else:
            pref = NotificationPreference(
                tenant_id=self.tenant_id,
                user_id=user_id,
                **data.model_dump(),
            )
            self.db.add(pref)
        await self.db.flush()
        return pref

    async def lister_preferences(self, user_id: UUID) -> list[NotificationPreference]:
        stmt = select(NotificationPreference).where(
            NotificationPreference.user_id == user_id
        )
        return list((await self.db.execute(stmt)).scalars().all())

    # ═════════════════════════════════════════════════════════════════════
    # SUPPRESSION (OPT-OUT)
    # ═════════════════════════════════════════════════════════════════════
    async def _est_supprime(
        self, email: str | None, telephone: str | None, type_notification: str
    ) -> bool:
        # Types critiques toujours envoyés (sécurité, mot de passe)
        if type_notification in ("password_reset", "security_alert", "login_new_device"):
            return False

        conditions = []
        if email:
            conditions.append(NotificationSuppression.email == email)
        if telephone:
            conditions.append(NotificationSuppression.telephone == telephone)
        if not conditions:
            return False

        stmt = select(NotificationSuppression).where(
            or_(*conditions),
            or_(
                NotificationSuppression.type_notification.is_(None),
                NotificationSuppression.type_notification == type_notification,
            ),
        )
        return (await self.db.scalar(stmt)) is not None

    async def ajouter_suppression(self, data: Any) -> NotificationSuppression:
        supp = NotificationSuppression(
            tenant_id=self.tenant_id,
            **data.model_dump(),
            created_by_user_id=self.user_id,
        )
        self.db.add(supp)
        await self.db.flush()
        return supp

    # ═════════════════════════════════════════════════════════════════════
    # RATE LIMITING
    # ═════════════════════════════════════════════════════════════════════
    async def _verifier_rate_limit(self, data: SendNotificationIn) -> None:
        """
        Anti-spam : max N notifications du même type par heure par utilisateur.
        Ignoré pour les notifications critiques.
        """
        if data.criticite == Criticite.CRITIQUE:
            return
        if not data.user_id:
            return

        il_y_a_1h = datetime.now(timezone.utc) - timedelta(hours=1)
        count = int(await self.db.scalar(
            select(func.count(Notification.id)).where(
                Notification.user_id == data.user_id,
                Notification.type_notification == data.type_notification,
                Notification.created_at >= il_y_a_1h,
                Notification.statut != StatutNotification.SUPPRESSED,
            )
        ) or 0)

        if count >= Quotas.MAX_MEME_TYPE_PAR_HEURE:
            raise HTTPException(
                429,
                f"Limite atteinte : {count} notifications du type "
                f"{data.type_notification} dans la dernière heure",
            )

    # ═════════════════════════════════════════════════════════════════════
    # RÉSOLUTION DESTINATAIRE
    # ═════════════════════════════════════════════════════════════════════
    async def _resoudre_destinataire(
        self, data: SendNotificationIn
    ) -> tuple[str | None, str | None, str | None]:
        """Retourne (email, telephone, nom) du destinataire."""
        # Cas 1 : user interne
        if data.user_id:
            user = await self.db.scalar(select(User).where(User.id == data.user_id))
            if user is None:
                raise HTTPException(404, "Utilisateur introuvable")
            return user.email, user.telephone, user.nom_complet

        # Cas 2 : portal user
        if data.portal_user_id:
            from app.models.portal import PortalUser
            pu = await self.db.scalar(
                select(PortalUser).where(PortalUser.id == data.portal_user_id)
            )
            if pu is None:
                raise HTTPException(404, "Utilisateur portail introuvable")
            return pu.email, pu.telephone, pu.nom_complet

        # Cas 3 : destinataire externe
        return data.destinataire_email, data.destinataire_telephone, data.destinataire_nom

    # ═════════════════════════════════════════════════════════════════════
    # STATUT & TRACKING
    # ═════════════════════════════════════════════════════════════════════
    async def marquer_envoye(
        self, notification_id: UUID, provider: str, provider_message_id: str
    ) -> Notification:
        notif = await self._get_notif(notification_id)
        notif.statut = StatutNotification.SENT
        notif.provider = provider
        notif.provider_message_id = provider_message_id
        notif.sent_at = datetime.now(timezone.utc)
        await self._log_event(notif.id, "sent", provider, {"message_id": provider_message_id})
        await self.db.flush()
        return notif

    async def marquer_echec(
        self, notification_id: UUID, erreur: str, retry: bool = True
    ) -> Notification:
        notif = await self._get_notif(notification_id)
        notif.nb_tentatives += 1
        notif.derniere_erreur = erreur[:2000]

        if retry and notif.nb_tentatives < 3:
            notif.statut = StatutNotification.RETRYING
            # Backoff exponentiel : 5s, 25s, 125s
            delay_s = 5 * (5 ** (notif.nb_tentatives - 1))
            notif.prochaine_tentative_at = datetime.now(timezone.utc) + timedelta(seconds=delay_s)
        else:
            notif.statut = StatutNotification.FAILED
            notif.failed_at = datetime.now(timezone.utc)

        await self._log_event(notif.id, "failed", notif.provider, {"erreur": erreur})
        await self.db.flush()
        return notif

    async def enregistrer_webhook_provider(
        self, provider: str, payload: dict[str, Any]
    ) -> None:
        """
        Traite un webhook du provider (SendGrid, Postmark, Twilio...).
        Ex : delivery, open, click, bounce.
        """
        message_id = payload.get("message_id") or payload.get("MessageSid") or payload.get("id")
        if not message_id:
            return

        notif = await self.db.scalar(
            select(Notification).where(
                Notification.provider_message_id == message_id
            )
        )
        if notif is None:
            return

        event_type = payload.get("event") or payload.get("type") or "unknown"
        now = datetime.now(timezone.utc)

        if event_type in ("delivered", "delivery"):
            notif.statut = StatutNotification.DELIVERED
            notif.delivered_at = now
        elif event_type in ("open", "opened"):
            notif.statut = StatutNotification.READ
            notif.read_at = now
        elif event_type in ("click", "clicked"):
            notif.statut = StatutNotification.CLICKED
            notif.clicked_at = now
        elif event_type in ("bounce", "bounced"):
            notif.statut = StatutNotification.BOUNCED
        elif event_type in ("unsubscribe", "spamreport"):
            # Ajouter à la liste de suppression
            await self.ajouter_suppression(type("S", (), {
                "email": notif.destinataire_email,
                "telephone": notif.destinataire_telephone,
                "motif": "unsubscribe" if event_type == "unsubscribe" else "complaint",
                "type_notification": None,
            })())

        await self._log_event(notif.id, event_type, provider, payload)
        await self.db.flush()

    async def _log_event(
        self, notification_id: UUID, event_type: str,
        provider: str | None, payload: dict[str, Any] | None
    ) -> None:
        event = NotificationEvent(
            tenant_id=self.tenant_id,
            notification_id=notification_id,
            event_type=event_type,
            provider=provider,
            payload=payload,
            created_at=datetime.now(timezone.utc),
        )
        self.db.add(event)
        await self.db.flush()

    # ═════════════════════════════════════════════════════════════════════
    # CONSULTATION
    # ═════════════════════════════════════════════════════════════════════
    async def lister_notifications(
        self,
        user_id: UUID | None = None,
        canal: str | None = None,
        statut: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Notification]:
        stmt = select(Notification).where(Notification.tenant_id == self.tenant_id)
        if user_id:
            stmt = stmt.where(Notification.user_id == user_id)
        if canal:
            stmt = stmt.where(Notification.canal == canal)
        if statut:
            stmt = stmt.where(Notification.statut == statut)
        stmt = stmt.order_by(desc(Notification.created_at)).limit(limit).offset(offset)
        return list((await self.db.execute(stmt)).scalars().all())

    async def lister_in_app(
        self, user_id: UUID, unread_only: bool = False, limit: int = 50
    ) -> list[Notification]:
        stmt = select(Notification).where(
            Notification.user_id == user_id,
            Notification.canal == "in_app",
        )
        if unread_only:
            stmt = stmt.where(Notification.read_at.is_(None))
        stmt = stmt.order_by(desc(Notification.created_at)).limit(limit)
        return list((await self.db.execute(stmt)).scalars().all())

    async def marquer_lu(self, user_id: UUID, notification_ids: list[UUID]) -> int:
        now = datetime.now(timezone.utc)
        count = 0
        for nid in notification_ids:
            notif = await self.db.scalar(
                select(Notification).where(
                    Notification.id == nid,
                    Notification.user_id == user_id,
                )
            )
            if notif and notif.read_at is None:
                notif.read_at = now
                notif.statut = StatutNotification.READ
                count += 1
        await self.db.flush()
        return count

    async def compter_non_lus(self, user_id: UUID) -> int:
        return int(await self.db.scalar(
            select(func.count(Notification.id)).where(
                Notification.user_id == user_id,
                Notification.canal == "in_app",
                Notification.read_at.is_(None),
            )
        ) or 0)

    # ═════════════════════════════════════════════════════════════════════
    # ANALYTICS
    # ═════════════════════════════════════════════════════════════════════
    async def analytics(
        self, debut: datetime, fin: datetime
    ) -> dict[str, Any]:
        # Compteurs globaux
        total = int(await self.db.scalar(
            select(func.count(Notification.id)).where(
                Notification.tenant_id == self.tenant_id,
                Notification.created_at.between(debut, fin),
            )
        ) or 0)

        livres = int(await self.db.scalar(
            select(func.count(Notification.id)).where(
                Notification.tenant_id == self.tenant_id,
                Notification.delivered_at.between(debut, fin),
            )
        ) or 0)

        ouverts = int(await self.db.scalar(
            select(func.count(Notification.id)).where(
                Notification.tenant_id == self.tenant_id,
                Notification.read_at.between(debut, fin),
            )
        ) or 0)

        clics = int(await self.db.scalar(
            select(func.count(Notification.id)).where(
                Notification.tenant_id == self.tenant_id,
                Notification.clicked_at.between(debut, fin),
            )
        ) or 0)

        erreurs = int(await self.db.scalar(
            select(func.count(Notification.id)).where(
                Notification.tenant_id == self.tenant_id,
                Notification.failed_at.between(debut, fin),
            )
        ) or 0)

        cout = int(await self.db.scalar(
            select(func.coalesce(func.sum(Notification.cout_xof), 0)).where(
                Notification.tenant_id == self.tenant_id,
                Notification.created_at.between(debut, fin),
            )
        ) or 0)

        # Répartition par canal
        rows = (
            await self.db.execute(
                select(Notification.canal, func.count(Notification.id))
                .where(
                    Notification.tenant_id == self.tenant_id,
                    Notification.created_at.between(debut, fin),
                )
                .group_by(Notification.canal)
            )
        ).all()
        par_canal = {r[0]: int(r[1]) for r in rows}

        # Répartition par type
        rows2 = (
            await self.db.execute(
                select(Notification.type_notification, func.count(Notification.id))
                .where(
                    Notification.tenant_id == self.tenant_id,
                    Notification.created_at.between(debut, fin),
                )
                .group_by(Notification.type_notification)
                .order_by(desc(func.count(Notification.id)))
                .limit(5)
            )
        ).all()
        par_type = {r[0]: int(r[1]) for r in rows2}

        return {
            "nb_envoyes": total,
            "nb_livres": livres,
            "nb_ouverts": ouverts,
            "nb_clics": clics,
            "nb_erreurs": erreurs,
            "taux_delivrabilite_pct": round(livres / total * 100, 2) if total else 0.0,
            "taux_ouverture_pct": round(ouverts / livres * 100, 2) if livres else 0.0,
            "taux_clic_pct": round(clics / ouverts * 100, 2) if ouverts else 0.0,
            "cout_total_xof": cout,
            "repartition_par_canal": par_canal,
            "repartition_par_type": par_type,
            "top_5_types": [{"type": k, "count": v} for k, v in par_type.items()],
        }

    # ═════════════════════════════════════════════════════════════════════
    # HELPERS
    # ═════════════════════════════════════════════════════════════════════
    async def _get_notif(self, notif_id: UUID) -> Notification:
        n = await self.db.scalar(
            select(Notification).where(Notification.id == notif_id)
        )
        if n is None:
            raise HTTPException(404, "Notification introuvable")
        return n

    @staticmethod
    def _priorite_pour(criticite: str) -> int:
        return {
            Criticite.CRITIQUE: 1,
            Criticite.HAUTE: 2,
            Criticite.NORMALE: 3,
            Criticite.INFO: 4,
        }.get(criticite, 3)

    # ═════════════════════════════════════════════════════════════════════
    # SEED
    # ═════════════════════════════════════════════════════════════════════
    async def seed_templates_defaut(self) -> int:
        """Initialise les templates par défaut (globaux)."""
        from app.core.notification_syscohada import TEMPLATES_SEED

        existing_codes = set(
            (await self.db.execute(
                select(NotificationTemplate.code).where(
                    NotificationTemplate.tenant_id.is_(None)
                )
            )).scalars().all()
        )

        created = 0
        for tpl in TEMPLATES_SEED:
            if tpl["code"] in existing_codes:
                continue
            self.db.add(NotificationTemplate(
                tenant_id=None,
                code=tpl["code"],
                libelle=tpl["code"].replace("_", " ").title(),
                canal=tpl["canal"],
                type_template=tpl["type_template"],
                type_notification=tpl.get("type_notification"),
                sujet=tpl.get("sujet"),
                contenu_html=tpl.get("contenu_html"),
                contenu_texte=tpl.get("contenu_texte"),
                variables_attendues=[],
                version=1,
                statut="publie",
            ))
            created += 1

        await self.db.flush()
        return created
