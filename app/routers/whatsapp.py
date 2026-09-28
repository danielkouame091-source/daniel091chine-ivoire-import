"""Endpoints WhatsApp : webhook entrant + liaison de compte."""
from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.deps import get_db
from app.dependencies.auth import CurrentUser
from app.dependencies.subscription import RequireActiveSubscription
from app.dependencies.tenant import CurrentTenant
from app.dependencies.tenant_db import TenantDBSession
from app.schemas.nlp import (
    WhatsAppLinkOut,
    WhatsAppLinkRequest,
    WhatsAppVerifyRequest,
)
from app.services.whatsapp_service import WhatsAppService

logger = logging.getLogger(__name__)
router = APIRouter()


# ─────────────────────────────────────────────────────────────────────────────
# Webhook Meta Cloud API
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/webhook")
async def verify_webhook(
    hub_mode: str = Query(alias="hub.mode"),
    hub_challenge: str = Query(alias="hub.challenge"),
    hub_verify_token: str = Query(alias="hub.verify_token"),
) -> Response:
    """Vérification du webhook par Meta (une seule fois à la config)."""
    if hub_mode == "subscribe" and hub_verify_token == settings.WHATSAPP_META_VERIFY_TOKEN:
        return Response(content=hub_challenge, media_type="text/plain")
    raise HTTPException(403, "Verify token invalide")


@router.post("/webhook")
async def receive_webhook(request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    """Reçoit les messages entrants de Meta."""
    payload = await request.json()
    try:
        entry = payload.get("entry", [])
        if not entry:
            return {"ok": True}
        changes = entry[0].get("changes", [])
        if not changes:
            return {"ok": True}

        value = changes[0].get("value", {})
        messages = value.get("messages", [])
        if not messages:
            return {"ok": True}

        msg = messages[0]
        phone_from = msg.get("from", "")
        msg_type = msg.get("type", "text")
        external_id = msg.get("id")

        if msg_type == "text":
            contenu = msg["text"]["body"]
        elif msg_type == "audio":
            # TODO : intégrer Whisper pour la transcription
            contenu = ""
            logger.warning("[whatsapp] Audio reçu — transcription non implémentée")
        else:
            contenu = ""

        if not contenu:
            return {"ok": True}

        svc = WhatsAppService(db)
        # Vérifier d'abord si c'est une réponse à une suggestion en attente
        reponse = await svc.traiter_reponse_suggestion(phone_from, contenu)
        if reponse is None:
            await svc.traiter_message_entrant(phone_from, contenu, external_id, msg_type, payload)

        await db.commit()
    except Exception:
        logger.exception("[whatsapp:webhook] Erreur traitement")
        await db.rollback()
    return {"ok": True}


# ─────────────────────────────────────────────────────────────────────────────
# Liaison de compte
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/link", response_model=WhatsAppLinkOut, status_code=201)
async def initier_liaison(
    data: WhatsAppLinkRequest,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireActiveSubscription,
    db: TenantDBSession,
) -> WhatsAppLinkOut:
    svc = WhatsAppService(db)
    link = await svc.initier_liaison(
        tenant_id=current_tenant.id,
        user_id=current_user.id,
        phone=data.phone_number,
    )
    return WhatsAppLinkOut.model_validate(link)
