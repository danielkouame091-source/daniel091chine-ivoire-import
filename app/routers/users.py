"""Endpoints de gestion des utilisateurs du tenant."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.db.deps import get_db
from app.dependencies.auth import RequireAdminTenant
from app.dependencies.tenant import CurrentTenant
from app.models.enums import UserStatut
from app.models.user import User
from app.schemas.user import UserCreate, UserOut, UserUpdate

router = APIRouter()


@router.get("", response_model=list[UserOut])
async def list_users(
    current_tenant: CurrentTenant,
    _: RequireAdminTenant,
    db: AsyncSession = Depends(get_db),
) -> list[UserOut]:
    rows = (
        await db.execute(
            select(User).where(
                User.tenant_id == current_tenant.id,
                User.deleted_at.is_(None),
            )
        )
    ).scalars().all()
    return [UserOut.model_validate(u) for u in rows]


@router.post("", response_model=UserOut, status_code=201)
async def create_user(
    data: UserCreate,
    current_tenant: CurrentTenant,
    _: RequireAdminTenant,
    db: AsyncSession = Depends(get_db),
) -> UserOut:
    if data.role.value == "SUPER_ADMIN":
        raise HTTPException(400, "Rôle SUPER_ADMIN réservé au fondateur")

    exists = await db.scalar(select(User.id).where(User.email == data.email))
    if exists:
        raise HTTPException(409, "Email déjà utilisé")

    user = User(
        tenant_id=current_tenant.id,
        email=data.email,
        nom_complet=data.nom_complet,
        telephone=data.telephone,
        role=data.role,
        statut=UserStatut.ACTIF if data.password else UserStatut.INVITE,
        password_hash=hash_password(data.password) if data.password else hash_password("*invite*"),
        is_founder=False,
    )
    db.add(user)
    await db.flush()
    return UserOut.model_validate(user)


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: UUID,
    data: UserUpdate,
    current_tenant: CurrentTenant,
    _: RequireAdminTenant,
    db: AsyncSession = Depends(get_db),
) -> UserOut:
    user = (
        await db.execute(
            select(User).where(User.id == user_id, User.tenant_id == current_tenant.id)
        )
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(404, "Utilisateur introuvable")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(user, field, value)
    await db.flush()
    return UserOut.model_validate(user)


@router.delete("/{user_id}", status_code=204)
async def delete_user(
    user_id: UUID,
    current_tenant: CurrentTenant,
    _: RequireAdminTenant,
    db: AsyncSession = Depends(get_db),
) -> None:
    from datetime import datetime, timezone
    user = (
        await db.execute(
            select(User).where(User.id == user_id, User.tenant_id == current_tenant.id)
        )
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(404, "Utilisateur introuvable")
    user.deleted_at = datetime.now(timezone.utc)
    user.statut = UserStatut.REVOQUE
    await db.flush()
