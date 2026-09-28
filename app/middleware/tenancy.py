"""
Middleware tenancy — pose les flags tenant/read_only/frozen dans request.state
AVANT l'exécution des dépendances FastAPI.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import Request
from sqlalchemy import select
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.core.security import decode_access_token_unsafe
from app.db.session import AsyncSessionLocal
from app.models.enums import SubStatut, TenantStatut
from app.models.subscription import Subscription
from app.models.tenant import Tenant
from app.models.user import User


class TenancyMiddleware(BaseHTTPMiddleware):
    """
    Ne lève JAMAIS d'exception : si le token est absent/invalide, on laisse
    les dépendances `get_current_user` gérer le 401. Ce middleware ne fait
    que PRÉ-REMPLIR les flags pour le RLS.
    """

    EXEMPT_PREFIXES = (
        "/health",
        "/docs",
        "/openapi.json",
        "/redoc",
        "/api/v1/auth",
        "/api/v1/webhooks",  # les webhooks MM n'ont pas de user
    )

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        # Valeurs par défaut : isolation maximale tant qu'on n'a rien prouvé
        request.state.tenant_id = None
        request.state.read_only = True
        request.state.frozen = False
        request.state.user = None

        # Exemptions : pas de tenancy à appliquer
        path = request.url.path
        if any(path.startswith(p) for p in self.EXEMPT_PREFIXES):
            return await call_next(request)

        # Extraction best-effort du JWT (pas de vérif stricte ici)
        auth_header = request.headers.get("Authorization", "")
        token = auth_header[7:] if auth_header.startswith("Bearer ") else None
        if not token:
            return await call_next(request)

        payload = decode_access_token_unsafe(token)
        if not payload:
            return await call_next(request)

        user_id = payload.get("sub")
        if not user_id:
            return await call_next(request)

        # Charger user + tenant + subscription en une passe
        async with AsyncSessionLocal() as db:
            user = (
                await db.execute(select(User).where(User.id == user_id))
            ).scalar_one_or_none()
            if user is None or user.is_founder:
                # Fondateur : tenant_id reste None → RLS bypass (voir policy SQL)
                return await call_next(request)

            request.state.user = user
            request.state.tenant_id = user.tenant_id
            request.state.read_only = False

            if user.tenant_id is None:
                return await call_next(request)

            tenant = (
                await db.execute(select(Tenant).where(Tenant.id == user.tenant_id))
            ).scalar_one_or_none()
            if tenant is None or tenant.statut in (TenantStatut.GELE, TenantStatut.ARCHIVE):
                request.state.read_only = True
                if tenant is not None and tenant.statut == TenantStatut.GELE:
                    request.state.frozen = True
                return await call_next(request)

            sub = (
                await db.execute(
                    select(Subscription)
                    .where(
                        Subscription.tenant_id == user.tenant_id,
                        Subscription.statut.in_(
                            [SubStatut.TRIAL, SubStatut.ACTIF, SubStatut.IMPAYE]
                        ),
                    )
                    .order_by(Subscription.periode_fin.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()

            if sub is None:
                request.state.read_only = True
            else:
                periode_fin = sub.periode_fin
                if periode_fin.tzinfo is None:
                    periode_fin = periode_fin.replace(tzinfo=timezone.utc)
                now = datetime.now(timezone.utc)
                expiree = periode_fin < now
                if expiree or sub.statut in (
                    SubStatut.EXPIRE, SubStatut.SUSPENDU, SubStatut.RESILIE
                ):
                    request.state.read_only = True

        return await call_next(request)
