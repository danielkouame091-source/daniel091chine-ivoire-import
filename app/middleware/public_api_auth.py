"""
Middleware d'authentification pour l'API publique.

Détecte les routes /api/v1/public/* et :
1. Extrait la clé API (header Authorization ou X-API-Key)
2. Valide la clé
3. Vérifie les scopes
4. Applique le rate limiting
5. Pose les infos du client dans request.state
6. Log l'usage
"""
from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.core.public_api_syscohada import (
    APIErrorCode,
    API_VERSION,
    AuthMethod,
    VERSION_DEFAUT,
    VERSION_HEADER,
)

logger = logging.getLogger(__name__)


class PublicApiAuthMiddleware(BaseHTTPMiddleware):
    """
    Middleware d'auth pour l'API publique.
    Ne s'applique qu'aux routes commençant par /api/v1/public/.
    """

    PREFIX = "/api/v1/public/"

    # Routes publiques sans auth (docs, health)
    EXEMPT_PATHS = (
        "/api/v1/public/docs",
        "/api/v1/public/health",
        "/api/v1/public/oauth/token",
    )

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Ne s'applique qu'aux routes publiques
        if not path.startswith(self.PREFIX):
            return await call_next(request)

        # Exemptions
        if any(path.startswith(p) for p in self.EXEMPT_PATHS):
            return await call_next(request)

        # Version API
        version = request.headers.get(VERSION_HEADER, VERSION_DEFAUT)

        # Extraire la clé API
        api_key_plain = self._extraire_cle(request)
        if not api_key_plain:
            return self._erreur(
                status.HTTP_401_UNAUTHORIZED,
                APIErrorCode.UNAUTHORIZED,
                "Clé API manquante. Utilisez Authorization: Bearer <key> ou X-API-Key.",
            )

        # Valider la clé (via service)
        start = time.monotonic()
        try:
            from app.db.session import AsyncSessionLocal
            from app.services.public_api_service import PublicApiService

            async with AsyncSessionLocal() as db:
                svc = PublicApiService(db, None)  # tenant_id résolu depuis la clé
                try:
                    api_key, client = await svc.valider_cle(
                        api_key_plain,
                        ip=request.client.host if request.client else None,
                    )
                except Exception as exc:
                    await db.rollback()
                    # Gérer les erreurs HTTP proprement
                    detail = getattr(exc, "detail", str(exc))
                    status_code = getattr(exc, "status_code", 401)
                    return self._erreur(status_code, APIErrorCode.INVALID_API_KEY, detail)

                # Vérifier rate limit
                try:
                    await svc.verifier_rate_limit(client, api_key)
                except Exception as exc:
                    await db.rollback()
                    detail = getattr(exc, "detail", str(exc))
                    return self._erreur(
                        status.HTTP_429_TOO_MANY_REQUESTS,
                        APIErrorCode.RATE_LIMIT_EXCEEDED,
                        detail,
                    )

                # Poser les infos dans request.state
                request.state.api_client = client
                request.state.api_key = api_key
                request.state.api_version = version
                request.state.tenant_id = client.tenant_id

                await db.commit()

            # Continuer vers la route
            response = await call_next(request)

            # Logger l'usage
            latence_ms = int((time.monotonic() - start) * 1000)
            await self._log_usage(
                request=request,
                statut_http=response.status_code,
                latence_ms=latence_ms,
            )

            return response

        except Exception as exc:
            logger.exception("[public_api] Erreur middleware")
            return self._erreur(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                APIErrorCode.INTERNAL_ERROR,
                "Erreur interne",
            )

    @staticmethod
    def _extraire_cle(request: Request) -> str | None:
        """Extrait la clé depuis Authorization ou X-API-Key."""
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            return auth[7:].strip()
        api_key = request.headers.get("X-API-Key", "")
        return api_key.strip() or None

    @staticmethod
    def _erreur(
        status_code: int, code: str, message: str, details: dict | None = None
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status_code,
            content={
                "error": {
                    "code": code,
                    "message": message,
                    "details": details or {},
                }
            },
        )

    async def _log_usage(
        self,
        request: Request,
        statut_http: int,
        latence_ms: int,
    ) -> None:
        """Enregistre l'usage dans api_usage_logs."""
        client = getattr(request.state, "api_client", None)
        key = getattr(request.state, "api_key", None)
        if client is None:
            return

        try:
            from app.db.session import AsyncSessionLocal
            from app.services.public_api_service import PublicApiService

            async with AsyncSessionLocal() as db:
                svc = PublicApiService(db, client.tenant_id)
                await svc.log_usage_publique(
                    api_client_id=client.id,
                    api_key_id=key.id if key else None,
                    methode=request.method,
                    endpoint=request.url.path,
                    statut_http=statut_http,
                    ip=request.client.host if request.client else None,
                    user_agent=request.headers.get("user-agent"),
                    request_id=request.headers.get("X-Request-Id"),
                    latence_ms=latence_ms,
                    error_code=None if statut_http < 400 else "api_error",
                )
                await db.commit()
        except Exception:
            logger.exception("[public_api] Échec log usage")
