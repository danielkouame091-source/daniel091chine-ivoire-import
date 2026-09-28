"""
Client WhatsApp — abstraction Meta Cloud API / Twilio.
Utilisé pour : notifications (abonnement, alertes) et bot de saisie comptable.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class WhatsAppClient:
    def __init__(self) -> None:
        if not settings.whatsapp_enabled:
            raise RuntimeError("WhatsApp non configuré")
        self.provider = settings.WHATSAPP_PROVIDER

    async def send_text(self, to: str, text: str) -> dict[str, Any]:
        if self.provider == "meta":
            return await self._send_meta_text(to, text)
        if self.provider == "twilio":
            return await self._send_twilio_text(to, text)
        raise RuntimeError(f"Provider inconnu : {self.provider}")

    async def _send_meta_text(self, to: str, text: str) -> dict[str, Any]:
        url = f"https://graph.facebook.com/v20.0/{settings.WHATSAPP_META_PHONE_ID}/messages"
        headers = {
            "Authorization": f"Bearer {settings.WHATSAPP_META_TOKEN}",
            "Content-Type": "application/json",
        }
        payload = {
            "messaging_product": "whatsapp",
            "to": to.lstrip("+"),
            "type": "text",
            "text": {"body": text},
        }
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(url, json=payload, headers=headers)
            r.raise_for_status()
            return r.json()

    async def _send_twilio_text(self, to: str, text: str) -> dict[str, Any]:
        url = f"https://api.twilio.com/2010-04-01/Accounts/{settings.WHATSAPP_TWILIO_SID}/Messages.json"
        data = {
            "From": settings.WHATSAPP_TWILIO_FROM,
            "To": to,
            "Body": text,
        }
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                url, data=data,
                auth=(settings.WHATSAPP_TWILIO_SID, settings.WHATSAPP_TWILIO_TOKEN),
            )
            r.raise_for_status()
            return r.json()


def get_whatsapp_client() -> WhatsAppClient:
    return WhatsAppClient()
