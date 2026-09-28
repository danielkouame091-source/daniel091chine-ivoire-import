"""
Dépendance tenant courant — garantit qu'un endpoint est bien appelé dans le
contexte d'UN tenant (jamais cross-tenant, jamais fondateur).
"""
from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.deps import get_db
from app.dependencies.auth import CurrentUser
from app.models.enums import TenantStatut
from app.models.tenant import Tenant


async def get_current_tenant(
    request: Request,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Tenant:
    """
    Charge le tenant de l'utilisateur courant.
    - Interdit au fondateur (il n'a pas de tenant).
    - Vérifie que le tenant n'est pas archivé.
    """
    if current_user.is_founder:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le fondateur n'a pas de tenant : utilisez le cockpit.",
        )

    tenant_id = current_user.tenant_id
    if tenant_id is None:
        raise HTTPException(status_code=403, detail="Aucun tenant associé à ce compte")

    # Session non scopée ici : on doit lire le tenant AVANT que RLS ne s'applique
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if tenant is None or tenant.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Tenant introuvable")

    if tenant.statut == TenantStatut.ARCHIVE:
        raise HTTPException(status_code=403, detail="Tenant archivé")

    # Propagation au middleware / autres deps
    request.state.tenant_id = tenant.id

    return tenant


CurrentTenant = Annotated[Tenant, Depends(get_current_tenant)]
