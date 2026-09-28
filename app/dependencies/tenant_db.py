"""
Raccourci : combine `get_current_tenant` + session RLS scopée.
À utiliser dans TOUS les endpoints métier (écritures, plan comptable, MM...).
"""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.deps import get_tenant_db
from app.dependencies.auth import CurrentUser
from app.dependencies.subscription import SubscriptionStatus
from app.dependencies.tenant import CurrentTenant

# Session RLS tenant — l'ordre des deps garantit que request.state est posé avant.
TenantDBSession = Annotated[AsyncSession, Depends(get_tenant_db)]

__all__ = [
    "CurrentTenant",
    "CurrentUser",
    "SubscriptionStatus",
    "TenantDBSession",
]
