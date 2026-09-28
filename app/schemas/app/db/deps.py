"""
Dépendances de session SQLAlchemy.

⚠️ RÈGLE D'OR :
- `get_db()`         → session neutre, réservée aux endpoints publics (login, health).
- `get_tenant_db()`  → session scopée tenant (RLS activé), OBLIGATOIRE pour tout
                       endpoint qui touche une donnée métier.
"""
from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any
from uuid import UUID

from fastapi import Depends, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Session neutre — aucune variable RLS posée."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_tenant_db(
    request: Request,
) -> AsyncGenerator[AsyncSession, None]:
    """
    Session scopée tenant — pose les variables PostgreSQL utilisées par les
    policies RLS (`app.tenant_id`, `app.read_only`, `app.frozen`).

    ⚠️ `set_config(..., true)` = portée TRANSACTIONNELLE, indispensable pour
    ne pas fuiter entre requêtes du pool de connexions.

    Le tenant_id et les flags sont résolus en amont par le middleware
    `TenancyMiddleware` et stockés dans `request.state`.
    """
    tenant_id: UUID | None = getattr(request.state, "tenant_id", None)
    read_only: bool = bool(getattr(request.state, "read_only", False))
    frozen: bool = bool(getattr(request.state, "frozen", False))

    async with AsyncSessionLocal() as session:
        try:
            # set_config(..., true) = local à la transaction courante
            await session.execute(
                text(
                    "SELECT "
                    "  set_config('app.tenant_id', :tid, true), "
                    "  set_config('app.read_only', :ro, true), "
                    "  set_config('app.frozen',    :fz, true)"
                ),
                {
                    "tid": str(tenant_id) if tenant_id else "",
                    "ro": "true" if read_only else "false",
                    "fz": "true" if frozen else "false",
                },
            )
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def current_tenant_id(request: Request) -> UUID | None:
    """Récupère le tenant_id depuis l'état de la requête (posé par le middleware)."""
    return getattr(request.state, "tenant_id", None)
