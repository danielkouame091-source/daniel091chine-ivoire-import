"""Dépendances FastAPI pour l'API publique."""
from __future__ import annotations

from typing import Any, Callable

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.public_api_syscohada import Scope


def get_api_client(request: Request) -> Any:
    """Récupère le client API depuis request.state (posé par le middleware)."""
    client = getattr(request.state, "api_client", None)
    if client is None:
        raise HTTPException(401, "Authentification API requise")
    return client


def require_scope(scope: str) -> Callable:
    """
    Factory de dépendance : exige un scope spécifique.
    """
    async def _checker(request: Request) -> None:
        api_key = getattr(request.state, "api_key", None)
        if api_key is None:
            raise HTTPException(401, "Authentification requise")
        if scope not in api_key.scopes:
            raise HTTPException(
                403,
                f"Scope insuffisant : {scope} requis",
            )
    return _checker


async def with_public_db(request: Request) -> AsyncSession:
    """Session DB avec RLS tenant posée."""
    from app.db.session import AsyncSessionLocal
    from sqlalchemy import text

    tenant_id = getattr(request.state, "tenant_id", None)
    if tenant_id is None:
        raise HTTPException(401, "Tenant non résolu")

    async with AsyncSessionLocal() as db:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )
        yield db
