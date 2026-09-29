"""
Middleware de capture automatique de la piste d'audit.

Intercepte toutes les requêtes mutantes (POST/PUT/PATCH/DELETE) et
logge automatiquement dans `audit_trails`.
"""
from __future__ import annotations

import logging
from uuid import UUID

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)


MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
EXCLUDED_PATHS = (
    "/health",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/api/v1/auth/login",       # loggué manuellement avec plus de contexte
    "/api/v1/auth/refresh",
    "/api/v1/webhooks",         # loggués dans le service concerné
)


class AuditCaptureMiddleware(BaseHTTPMiddleware):
    """
    Capture les mutations HTTP pour enrichir la piste d'audit.
    Ne remplace PAS les logs métier (fait par chaque service).
    Sert de filet de sécurité pour les routes non instrumentées.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        method = request.method

        # Filtrer
        if method not in MUTATING_METHODS:
            return await call_next(request)
        if any(path.startswith(p) for p in EXCLUDED_PATHS):
            return await call_next(request)

        # Récupérer user_id (posé par TenancyMiddleware ou get_current_user)
        user = getattr(request.state, "user", None)
        user_id = user.id if user else None
        tenant_id = getattr(request.state, "tenant_id", None)

        response = await call_next(request)

        # Logguer (asynchrone, non bloquant)
        if tenant_id and response.status_code < 500:
            try:
                from app.db.session import AsyncSessionLocal
                from app.services.audit_internal_service import AuditInternalService

                async with AsyncSessionLocal() as db:
                    svc = AuditInternalService(db, tenant_id, user_id)
                    await svc.log_action(
                        action=f"HTTP_{method}_{path.replace('/', '_')[:40]}",
                        categorie="tracabilite",
                        ressource_type="http_request",
                        ressource_ref=path,
                        succes=response.status_code < 400,
                        code_erreur=str(response.status_code) if response.status_code >= 400 else None,
                        ip_address=request.client.host if request.client else None,
                        user_agent=request.headers.get("user-agent"),
                        endpoint=path,
                        methode_http=method,
                        request_id=request.headers.get("x-request-id"),
                    )
                    await db.commit()
            except Exception:
                logger.exception("[audit_capture] Échec log middleware")

        return response
