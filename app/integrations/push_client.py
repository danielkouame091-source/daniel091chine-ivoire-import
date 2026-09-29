"""
Client Push — Firebase Cloud Messaging (FCM).
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class PushClient:
    """Client FCM pour notifications push."""

    def __init__(self) -> None:
        self.server_key = getattr(settings, "FCM_SERVER_KEY", "")
        if not self.server_key:
            raise RuntimeError("FCM_SERVER_KEY manquante")

    async def envoyer(
        self,
        device_token: str,
        titre: str,
        corps: str,
        data: dict[str, str] | None = None,
        action_url: str | None = None,
    ) -> dict[str, Any]:
        """Envoie une notification push à un device."""
        payload: dict[str, Any] = {
            "to": device_token,
            "notification": {
                "title": titre,
                "body": corps,
                "sound": "default",
            },
            "data": data or {},
            "priority": "high",
        }
        if action_url:
            payload["data"]["url"] = action_url
            payload["notification"]["click_action"] = action_url

        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(
                "https://fcm.googleapis.com/fcm/send",
                json=payload,
                headers={
                    "Authorization": f"key={self.server_key}",
                    "Content-Type": "application/json",
                },
            )
            if r.status_code >= 400:
                raise RuntimeError(f"FCM {r.status_code}: {r.text[:500]}")
            data_resp = r.json()
            return {
                "provider_message_id": str(data_resp.get("multicast_id", "")),
                "provider": "fcm",
                "success": data_resp.get("success", 0),
                "failure": data_resp.get("failure", 0),
            }


def get_push_client() -> PushClient:
    return PushClient()
