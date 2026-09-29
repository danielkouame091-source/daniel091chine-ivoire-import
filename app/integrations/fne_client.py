"""
Client HTTP FNE — Facture Normalisée Électronique (DGI Côte d'Ivoire).

Abstraction bas niveau de l'API REST/JSON FNE.
Gère :
- Authentification Bearer JWT
- Retry automatique avec backoff exponentiel
- Timeout
- Logs détaillés
- Détection des erreurs
"""
from __future__ import annotations

import logging
import time
from typing import Any
from uuid import UUID, uuid4

import httpx

from app.core.fne_syscohada import (
    FNE_RETRY_DELAY_BASE_S,
    FNE_RETRY_ERRORS,
    FNE_RETRY_MAX,
    FNE_TIMEOUT_S,
    FNE_URLS,
    FneDocumentType,
    FneEnvironment,
)

logger = logging.getLogger(__name__)


class FneApiError(Exception):
    """Erreur retournée par l'API FNE."""
    def __init__(
        self,
        status_code: int,
        message: str,
        error_code: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self.status_code = status_code
        self.error_code = error_code
        self.payload = payload or {}
        super().__init__(message)


class FneClient:
    """
    Client API FNE.
    Une instance par tenant/config (état : token, base_url).
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        environnement: str = FneEnvironment.SANDBOX,
        entity_id: str | None = None,
        bearer_token: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.environnement = environnement
        self.entity_id = entity_id
        self._bearer_token = bearer_token
        self._token_expires_at: float = 0.0

    # ═════════════════════════════════════════════════════════════════════
    # Authentification
    # ═════════════════════════════════════════════════════════════════════
    async def _get_headers(self) -> dict[str, str]:
        """Retourne les headers HTTP incluant le Bearer token."""
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self._bearer_token:
            headers["Authorization"] = f"Bearer {self._bearer_token}"
        elif self.api_key:
            # Fallback : clé API en Bearer
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def authenticate(self, client_id: str, client_secret: str) -> str:
        """
        Authentification OAuth 2.0 (si l'API FNE le supporte).
        Retourne un Bearer JWT.
        """
        async with httpx.AsyncClient(timeout=FNE_TIMEOUT_S) as client:
            r = await client.post(
                f"{self.base_url}/oauth/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
            )
            if r.status_code != 200:
                raise FneApiError(r.status_code, "Échec authentification FNE")
            data = r.json()
            self._bearer_token = data.get("access_token")
            self._token_expires_at = time.time() + int(data.get("expires_in", 3600)) - 60
            return self._bearer_token

    # ═════════════════════════════════════════════════════════════════════
    # Appels API
    # ═════════════════════════════════════════════════════════════════════
    async def _request(
        self,
        method: str,
        path: str,
        json_payload: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> tuple[dict[str, Any], int, int]:
        """
        Requête HTTP avec retry exponentiel.
        Retourne (body, status_http, latence_ms).
        Lève FneApiError si erreur définitive.
        """
        url = f"{self.base_url}{path}"
        headers = await self._get_headers()
        correlation_id = correlation_id or str(uuid4())
        headers["X-Correlation-ID"] = correlation_id

        last_exc: Exception | None = None

        for tentative in range(1, FNE_RETRY_MAX + 1):
            started = time.monotonic()
            try:
                async with httpx.AsyncClient(timeout=FNE_TIMEOUT_S) as client:
                    r = await client.request(
                        method, url, json=json_payload, headers=headers
                    )
                latence_ms = int((time.monotonic() - started) * 1000)

                if r.status_code < 400:
                    body = r.json() if r.content else {}
                    return body, r.status_code, latence_ms

                # Erreur HTTP
                try:
                    error_body = r.json()
                except Exception:
                    error_body = {"raw": r.text[:500]}

                if r.status_code in FNE_RETRY_ERRORS and tentative < FNE_RETRY_MAX:
                    delay = FNE_RETRY_DELAY_BASE_S * (5 ** (tentative - 1))
                    logger.warning(
                        f"[fne] {method} {path} → {r.status_code} "
                        f"(tentative {tentative}/{FNE_RETRY_MAX}), retry dans {delay}s"
                    )
                    import asyncio
                    await asyncio.sleep(delay)
                    last_exc = FneApiError(
                        r.status_code,
                        error_body.get("message", "Erreur FNE"),
                        error_body.get("error"),
                        error_body,
                    )
                    continue

                raise FneApiError(
                    r.status_code,
                    error_body.get("message", f"Erreur HTTP {r.status_code}"),
                    error_body.get("error"),
                    error_body,
                )

            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                last_exc = exc
                if tentative < FNE_RETRY_MAX:
                    delay = FNE_RETRY_DELAY_BASE_S * (5 ** (tentative - 1))
                    logger.warning(
                        f"[fne] {method} {path} → timeout/connexion "
                        f"(tentative {tentative}/{FNE_RETRY_MAX}), retry dans {delay}s"
                    )
                    import asyncio
                    await asyncio.sleep(delay)
                    continue
                raise FneApiError(0, f"Erreur réseau FNE : {exc}")

        if last_exc:
            raise last_exc
        raise FneApiError(0, "Échec après tous les retries")

    # ═════════════════════════════════════════════════════════════════════
    # Endpoints métier
    # ═════════════════════════════════════════════════════════════════════
    async def certifier_facture(
        self, payload: dict[str, Any], correlation_id: str | None = None
    ) -> dict[str, Any]:
        """
        Certifie une facture de vente.
        POST /external/invoices
        """
        body, status, latence = await self._request(
            "POST", "/external/invoices", payload, correlation_id
        )
        logger.info(f"[fne] Facture certifiée : {body.get('reference')} ({latence}ms)")
        return body

    async def certifier_avoir(
        self, invoice_id: str, payload: dict[str, Any],
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Certifie une facture d'avoir.
        POST /external/invoices/{id}/refund
        """
        body, status, latence = await self._request(
            "POST", f"/external/invoices/{invoice_id}/refund",
            payload, correlation_id,
        )
        logger.info(f"[fne] Avoir certifié : {body.get('reference')} ({latence}ms)")
        return body

    async def annuler_facture(
        self, invoice_id: str, motif: str | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        """POST /external/invoices/{id}/cancel"""
        payload = {"motif": motif} if motif else {}
        body, _, _ = await self._request(
            "POST", f"/external/invoices/{invoice_id}/cancel",
            payload, correlation_id,
        )
        return body

    async def get_facture(
        self, invoice_id: str, correlation_id: str | None = None
    ) -> dict[str, Any]:
        """GET /external/invoices/{id}"""
        body, _, _ = await self._request(
            "GET", f"/external/invoices/{invoice_id}", None, correlation_id
        )
        return body

    async def get_facture_par_reference(
        self, reference: str, correlation_id: str | None = None
    ) -> dict[str, Any]:
        """GET /external/invoices/{reference}"""
        body, _, _ = await self._request(
            "GET", f"/external/invoices/{reference}", None, correlation_id
        )
        return body

    async def get_balance_stickers(
        self, correlation_id: str | None = None
    ) -> dict[str, Any]:
        """
        GET /external/invoices/balance-stickers
        Retourne : {"balance_fne": int, "balance_rne": int, "balance_total": int}
        """
        body, _, _ = await self._request(
            "GET", "/external/invoices/balance-stickers", None, correlation_id
        )
        return body

    async def health_check(self) -> bool:
        """Vérifie la disponibilité de l'API FNE."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(f"{self.base_url}/health")
                return r.status_code < 500
        except Exception:
            return False


def get_fne_client(
    base_url: str,
    api_key: str,
    environnement: str = FneEnvironment.SANDBOX,
    entity_id: str | None = None,
) -> FneClient:
    """Factory."""
    return FneClient(
        base_url=base_url,
        api_key=api_key,
        environnement=environnement,
        entity_id=entity_id,
    )
