"""
Runtime d'exécution des plugins — Sandbox sécurisé.

Chaque hook est envoyé via HTTP POST au webhook_url configuré par le plugin.
Le plugin peut aussi exposer des "scheduled tasks" exécutées par cron.

Le sandbox impose :
- Timeout strict (10s)
- Payload maximum (512 Ko)
- Signature HMAC
- Rate limiting
- Retry avec backoff
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.marketplace_syscohada import (
    LimitesExecution,
    StatutInstallation,
)
from app.models.marketplace import (
    ExtensionInstallation,
    HookExecution,
    InstallationSecret,
)
from app.services.crypto_service import CryptoService

logger = logging.getLogger(__name__)


# Politique de retry
RETRY_DELAYS_S = [5, 30, 120]


class PluginRuntimeService:
    """
    Exécution d'un hook plugin en sandbox.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.crypto = CryptoService()

    async def executer_hook(
        self,
        installation_id: UUID,
        tenant_id: UUID,
        hook_event: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Exécute un hook pour une installation donnée.
        Retourne {ok, status, latence_ms, erreur}.
        """
        inst = await self.db.scalar(
            select(ExtensionInstallation).where(
                ExtensionInstallation.id == installation_id,
                ExtensionInstallation.tenant_id == tenant_id,
            )
        )
        if inst is None:
            return {"ok": False, "reason": "installation_not_found"}

        if inst.statut != StatutInstallation.ACTIVE:
            return {"ok": False, "reason": f"installation_{inst.statut}"}

        if not inst.webhook_url:
            # Plugin purement passif (pas de webhook)
            return {"ok": True, "reason": "no_webhook"}

        # Vérifier rate limit
        if inst.nb_appels_jour >= LimitesExecution.MAX_CALLS_PER_DAY:
            logger.warning(
                f"[plugin_runtime] Rate limit journalier atteint "
                f"pour installation {installation_id}"
            )
            return {"ok": False, "reason": "daily_quota_exceeded"}

        # Préparer le payload complet
        full_payload = {
            "id": f"hook_{int(time.time() * 1000)}",
            "event": hook_event,
            "tenant_id": str(tenant_id),
            "installation_id": str(installation_id),
            "created": int(time.time()),
            "data": payload,
        }

        # Signature
        timestamp = int(time.time())
        signature = await self._signer_payload(inst, full_payload, timestamp)

        # Headers
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "MTech-Plugin-Runtime/1.0",
            "X-MTech-Event": hook_event,
            "X-MTech-Timestamp": str(timestamp),
            "X-MTech-Signature": signature,
            "X-MTech-Installation-Id": str(installation_id),
        }

        # Vérifier taille payload
        body = json.dumps(full_payload, separators=(",", ":"), ensure_ascii=False)
        if len(body.encode("utf-8")) > LimitesExecution.MAX_PAYLOAD_KB * 1024:
            logger.warning(f"[plugin_runtime] Payload trop gros pour {hook_event}")
            await self._log_execution(
                inst, hook_event, full_payload, "failed",
                erreur=f"Payload > {LimitesExecution.MAX_PAYLOAD_KB} Ko",
            )
            return {"ok": False, "reason": "payload_too_large"}

        # HTTP POST
        started = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=LimitesExecution.TIMEOUT_HOOK_S) as client:
                r = await client.post(inst.webhook_url, content=body, headers=headers)
            latence_ms = int((time.monotonic() - started) * 1000)

            statut = "success" if 200 <= r.status_code < 300 else "failed"

            # Mettre à jour les compteurs
            inst.nb_appels_jour += 1
            inst.dernier_appel_at = datetime.now(timezone.utc)
            if statut == "failed":
                inst.nb_erreurs_jour += 1
                inst.derniere_erreur_at = datetime.now(timezone.utc)
                inst.derniere_erreur = f"HTTP {r.status_code}: {r.text[:200]}"

            await self._log_execution(
                inst, hook_event, full_payload, statut,
                response_status=r.status_code,
                response_body=r.text[:2000],
                latence_ms=latence_ms,
            )
            await self.db.flush()

            return {
                "ok": statut == "success",
                "status": r.status_code,
                "latence_ms": latence_ms,
            }

        except httpx.TimeoutException:
            await self._log_execution(
                inst, hook_event, full_payload, "failed",
                erreur="Timeout",
            )
            inst.nb_erreurs_jour += 1
            await self.db.flush()
            return {"ok": False, "reason": "timeout"}

        except Exception as exc:
            logger.exception(f"[plugin_runtime] Erreur {hook_event}")
            await self._log_execution(
                inst, hook_event, full_payload, "failed",
                erreur=str(exc)[:500],
            )
            inst.nb_erreurs_jour += 1
            await self.db.flush()
            return {"ok": False, "reason": str(exc)}

    async def _signer_payload(
        self, inst: ExtensionInstallation, payload: dict[str, Any], timestamp: int
    ) -> str:
        """
        Signature HMAC-SHA256.
        Format : HMAC(secret, "{timestamp}.{body}")
        """
        # Récupérer le secret du webhook
        secret = "default_secret_change_me"
        if inst.webhook_secret_enc:
            try:
                secret = self.crypto.decrypt(inst.webhook_secret_enc)
            except Exception:
                logger.exception("[plugin_runtime] Erreur déchiffrement secret")

        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        signed = f"{timestamp}.{body}"
        return hmac.new(secret.encode(), signed.encode(), hashlib.sha256).hexdigest()

    async def _log_execution(
        self,
        inst: ExtensionInstallation,
        hook_event: str,
        payload: dict[str, Any],
        statut: str,
        response_status: int | None = None,
        response_body: str | None = None,
        latence_ms: int | None = None,
        erreur: str | None = None,
        nb_tentatives: int = 1,
    ) -> None:
        log = HookExecution(
            tenant_id=inst.tenant_id,
            installation_id=inst.id,
            hook_event=hook_event,
            trigger_type="webhook",
            payload=payload,
            payload_size_kb=len(json.dumps(payload).encode()) // 1024,
            statut=statut,
            response_status=response_status,
            response_body=response_body,
            latence_ms=latence_ms,
            erreur=erreur,
            nb_tentatives=nb_tentatives,
            created_at=datetime.now(timezone.utc),
        )
        self.db.add(log)
        await self.db.flush()

    async def get_secret(self, installation_id: UUID, cle: str) -> str | None:
        """Récupère un secret déchiffré pour un plugin."""
        secret = await self.db.scalar(
            select(InstallationSecret).where(
                InstallationSecret.installation_id == installation_id,
                InstallationSecret.cle == cle,
            )
        )
        if secret is None:
            return None
        try:
            return self.crypto.decrypt(secret.valeur_chiffree)
        except Exception:
            logger.exception("[plugin_runtime] Erreur déchiffrement secret")
            return None
