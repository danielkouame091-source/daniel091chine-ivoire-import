"""
Jobs de notification : WhatsApp via Meta Cloud API / Twilio, email via SMTP.
MVP : le client WhatsApp est isolé dans app/integrations/whatsapp.py.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.enums import SubStatut
from app.models.subscription import Subscription
from app.models.tenant import Tenant
from app.models.user import User

logger = logging.getLogger(__name__)


async def envoyer_whatsapp(
    ctx: dict[str, Any],
    destinataire: str,       # numéro international, ex "+2250700000000"
    message: str,
) -> dict[str, Any]:
    """Envoie un message WhatsApp. Échec non bloquant : loggé et retourné."""
    try:
        from app.integrations.whatsapp import WhatsAppClient

        client = WhatsAppClient()
        await client.send_text(destinataire, message)
        return {"ok": True, "to": destinataire}
    except Exception:
        logger.exception(f"[whatsapp] Échec envoi à {destinataire}")
        return {"ok": False, "to": destinataire}


async def notifier_expiration_abonnement(
    ctx: dict[str, Any],
    tenant_id: str,
) -> dict[str, Any]:
    """
    Notifie l'admin tenant que son abonnement expire bientôt.
    Déclenché par cron J-7, J-3, J-1.
    """
    tid = UUID(tenant_id)
    async with AsyncSessionLocal() as db:
        tenant = (
            await db.execute(select(Tenant).where(Tenant.id == tid))
        ).scalar_one_or_none()
        if tenant is None:
            return {"ok": False, "reason": "tenant_not_found"}

        sub = (
            await db.execute(
                select(Subscription)
                .where(
                    Subscription.tenant_id == tid,
                    Subscription.statut.in_([SubStatut.TRIAL, SubStatut.ACTIF, SubStatut.IMPAYE]),
                )
                .order_by(Subscription.periode_fin.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if sub is None:
            return {"ok": False, "reason": "no_active_sub"}

        # Récupère l'admin pour notification
        admin = (
            await db.execute(
                select(User)
                .where(User.tenant_id == tid)
                .order_by(User.created_at.asc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if admin is None or not admin.telephone:
            return {"ok": False, "reason": "no_admin_phone"}

        fin = sub.periode_fin
        if fin.tzinfo is None:
            fin = fin.replace(tzinfo=timezone.utc)
        jours = max(0, (fin - datetime.now(timezone.utc)).days)

        message = (
            f"Bonjour {admin.nom_complet},\n"
            f"Votre abonnement {tenant.raison_sociale} expire dans {jours} jour(s) "
            f"({fin.strftime('%d/%m/%Y')}).\n"
            f"Renouvelez pour éviter la bascule en lecture seule : "
            f"https://app.mtech.ci/billing/renew"
        )

        await envoyer_whatsapp(ctx, admin.telephone, message)
        return {"ok": True, "tenant_id": str(tid), "jours_restants": jours}
