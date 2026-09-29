"""
Dispatcher de notifications — route chaque notification vers le bon provider.
Appelé par le worker ARQ.
"""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.notification_syscohada import Canal
from app.integrations.email_client import get_email_client
from app.integrations.push_client import get_push_client
from app.integrations.sms_client import get_sms_client
from app.integrations.whatsapp import get_whatsapp_client
from app.models.notification import Notification, PushDevice
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)


class NotificationDispatcher:
    def __init__(self, db: AsyncSession, tenant_id: UUID | None) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self.notif_svc = NotificationService(db, tenant_id)

    async def envoyer(self, notification_id: UUID) -> dict[str, Any]:
        """Envoie une notification via le bon provider selon son canal."""
        notif = await self.db.scalar(
            select(Notification).where(Notification.id == notification_id)
        )
        if notif is None:
            return {"ok": False, "reason": "not_found"}

        try:
            if notif.canal == Canal.EMAIL:
                result = await self._envoyer_email(notif)
            elif notif.canal == Canal.SMS:
                result = await self._envoyer_sms(notif)
            elif notif.canal == Canal.WHATSAPP:
                result = await self._envoyer_whatsapp(notif)
            elif notif.canal == Canal.PUSH:
                result = await self._envoyer_push(notif)
            elif notif.canal == Canal.IN_APP:
                result = {"provider_message_id": "", "provider": "internal"}
            else:
                return await self._fail(notif, f"Canal inconnu : {notif.canal}")

            await self.notif_svc.marquer_envoye(
                notif.id, result.get("provider", ""),
                result.get("provider_message_id", ""),
            )
            return {"ok": True, "notification_id": str(notif.id)}

        except Exception as exc:
            logger.exception(f"[dispatcher] Échec envoi {notif.id}")
            await self.notif_svc.marquer_echec(notif.id, str(exc), retry=True)
            return {"ok": False, "reason": str(exc)}

    async def _envoyer_email(self, notif: Notification) -> dict[str, Any]:
        if not notif.destinataire_email:
            raise ValueError("Email destinataire manquant")
        client = get_email_client()
        return await client.envoyer(
            destinataire=notif.destinataire_email,
            sujet=notif.sujet or "Notification",
            contenu_html=notif.contenu_html or notif.contenu_texte or "",
            contenu_texte=notif.contenu_texte,
            nom_destinataire=notif.destinataire_nom,
            tracking_id=notif.tracking_id,
        )

    async def _envoyer_sms(self, notif: Notification) -> dict[str, Any]:
        if not notif.destinataire_telephone:
            raise ValueError("Téléphone manquant")
        contenu = notif.contenu_texte or notif.contenu_html or ""
        # Tronquer à 160 caractères (SMS standard)
        if len(contenu) > 160:
            contenu = contenu[:157] + "..."
        client = get_sms_client()
        return await client.envoyer(
            destinataire=notif.destinataire_telephone,
            contenu=contenu,
            tracking_id=notif.tracking_id,
        )

    async def _envoyer_whatsapp(self, notif: Notification) -> dict[str, Any]:
        if not notif.destinataire_telephone:
            raise ValueError("Téléphone manquant")
        client = get_whatsapp_client()
        contenu = notif.contenu_texte or notif.contenu_html or ""
        return await client.send_text(notif.destinataire_telephone, contenu)

    async def _envoyer_push(self, notif: Notification) -> dict[str, Any]:
        if not notif.user_id:
            raise ValueError("Push nécessite user_id")
        devices = (
            await self.db.execute(
                select(PushDevice).where(
                    PushDevice.user_id == notif.user_id,
                    PushDevice.actif.is_(True),
                )
            )
        ).scalars().all()
        if not devices:
            raise ValueError("Aucun device actif")

        client = get_push_client()
        sent = 0
        for d in devices:
            try:
                await client.envoyer(
                    device_token=d.device_token,
                    titre=notif.sujet or "MTech",
                    corps=notif.contenu_texte or "",
                    action_url=notif.action_url,
                )
                sent += 1
            except Exception:
                logger.exception(f"[dispatcher] Push échec device {d.id}")
        return {"provider_message_id": "", "provider": "fcm", "sent": sent}

    async def _fail(self, notif: Notification, raison: str) -> dict[str, Any]:
        await self.notif_svc.marquer_echec(notif.id, raison, retry=False)
        return {"ok": False, "reason": raison}
