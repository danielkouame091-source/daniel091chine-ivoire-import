"""
Client Email multi-provider (SendGrid, Postmark, SMTP).
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class EmailClient:
    """Client Email unifié."""

    def __init__(self, provider: str = "sendgrid") -> None:
        self.provider = provider

    async def envoyer(
        self,
        destinataire: str,
        sujet: str,
        contenu_html: str,
        contenu_texte: str | None = None,
        nom_destinataire: str | None = None,
        reply_to: str | None = None,
        from_email: str | None = None,
        from_name: str = "MTech",
        tracking_id: str | None = None,
    ) -> dict[str, Any]:
        """Retourne {"provider_message_id": str, "provider": str}"""
        if self.provider == "sendgrid":
            return await self._sendgrid(
                destinataire, sujet, contenu_html, contenu_texte,
                nom_destinataire, reply_to, from_email, from_name, tracking_id,
            )
        if self.provider == "postmark":
            return await self._postmark(
                destinataire, sujet, contenu_html, contenu_texte,
                nom_destinataire, reply_to, from_email, from_name,
            )
        if self.provider == "smtp":
            return await self._smtp(
                destinataire, sujet, contenu_html, contenu_texte,
                nom_destinataire, reply_to, from_email, from_name,
            )
        raise ValueError(f"Provider email inconnu : {self.provider}")

    async def _sendgrid(
        self, dest: str, sujet: str, html: str, texte: str | None,
        nom_dest: str | None, reply_to: str | None,
        from_email: str | None, from_name: str,
        tracking_id: str | None,
    ) -> dict[str, Any]:
        api_key = getattr(settings, "SENDGRID_API_KEY", "")
        if not api_key:
            raise RuntimeError("SENDGRID_API_KEY manquante")

        payload = {
            "personalizations": [{
                "to": [{"email": dest, "name": nom_dest or ""}],
                "custom_args": {"tracking_id": tracking_id} if tracking_id else {},
            }],
            "from": {"email": from_email or "noreply@mtech.ci", "name": from_name},
            "subject": sujet,
            "content": [],
        }
        if texte:
            payload["content"].append({"type": "text/plain", "value": texte})
        payload["content"].append({"type": "text/html", "value": html})
        if reply_to:
            payload["reply_to"] = {"email": reply_to}

        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                "https://api.sendgrid.com/v3/mail/send",
                json=payload,
                headers={"Authorization": f"Bearer {api_key}"},
            )
            if r.status_code >= 400:
                raise RuntimeError(f"SendGrid {r.status_code}: {r.text[:500]}")

            message_id = r.headers.get("X-Message-Id") or ""
            return {"provider_message_id": message_id, "provider": "sendgrid"}

    async def _postmark(
        self, dest: str, sujet: str, html: str, texte: str | None,
        nom_dest: str | None, reply_to: str | None,
        from_email: str | None, from_name: str,
    ) -> dict[str, Any]:
        token = getattr(settings, "POSTMARK_TOKEN", "")
        if not token:
            raise RuntimeError("POSTMARK_TOKEN manquant")

        payload = {
            "From": f"{from_name} <{from_email or 'noreply@mtech.ci'}>",
            "To": f"{nom_dest} <{dest}>" if nom_dest else dest,
            "Subject": sujet,
            "HtmlBody": html,
            "TextBody": texte or "",
        }
        if reply_to:
            payload["ReplyTo"] = reply_to

        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                "https://api.postmarkapp.com/email",
                json=payload,
                headers={"X-Postmark-Server-Token": token, "Accept": "application/json"},
            )
            if r.status_code >= 400:
                raise RuntimeError(f"Postmark {r.status_code}: {r.text[:500]}")
            data = r.json()
            return {"provider_message_id": data.get("MessageID", ""), "provider": "postmark"}

    async def _smtp(
        self, dest: str, sujet: str, html: str, texte: str | None,
        nom_dest: str | None, reply_to: str | None,
        from_email: str | None, from_name: str,
    ) -> dict[str, Any]:
        import smtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        msg = MIMEMultipart("alternative")
        msg["Subject"] = sujet
        msg["From"] = f"{from_name} <{from_email or settings.SMTP_USER}>"
        msg["To"] = dest
        if reply_to:
            msg["Reply-To"] = reply_to

        if texte:
            msg.attach(MIMEText(texte, "plain", "utf-8"))
        msg.attach(MIMEText(html, "html", "utf-8"))

        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
            server.starttls()
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.send_message(msg)

        return {"provider_message_id": "", "provider": "smtp"}


def get_email_client(provider: str = "sendgrid") -> EmailClient:
    return EmailClient(provider)
