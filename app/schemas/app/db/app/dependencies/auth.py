"""
Dépendances d'authentification : extraction du JWT, chargement du user,
vérification du statut, guards de rôle.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_access_token
from app.db.deps import get_db
from app.models.enums import UserRole, UserStatut
from app.models.user import User

# Schéma Bearer standard (header "Authorization: Bearer <jwt>")
bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """
    Charge l'utilisateur courant depuis le JWT.
    - Vérifie la signature RS256, l'expiration, le type de token.
    - Vérifie que l'utilisateur existe et n'est pas révoqué.
    - Vérifie que la session (jti) n'est pas révoquée.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token d'authentification manquant",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    payload = decode_access_token(token)  # lève 401 si invalide/expiré

    user_id: UUID | None = payload.get("sub")
    jti: str | None = payload.get("jti")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token invalide : sub manquant")

    # ⚠️ Lecture tenant-agnostique : le user peut être fondateur (tenant_id=NULL)
    result = await db.execute(select(User).where(User.id == user_id, User.deleted_at.is_(None)))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=401, detail="Utilisateur inconnu")

    if user.statut == UserStatut.REVOQUE:
        raise HTTPException(status_code=403, detail="Compte révoqué")
    if user.statut == UserStatut.GELE:
        raise HTTPException(status_code=403, detail="Compte gelé")

    # Vérification jti (session révocable) — chargé seulement si présent
    if jti:
        from app.models.session import Session as SessionModel
        sess = await db.execute(
            select(SessionModel).where(
                SessionModel.jti == UUID(jti),
                SessionModel.revoquee_at.is_(None),
            )
        )
        if sess.scalar_one_or_none() is None:
            raise HTTPException(status_code=401, detail="Session révoquée ou expirée")

    # On expose le user + les infos utiles dans request.state (utilisé par middleware)
    request.state.user = user
    request.state.jti = jti

    # Informations tenant pour le middleware (le fondateur a tenant_id=NULL)
    if not user.is_founder:
        request.state.tenant_id = user.tenant_id

    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


# ---------------------------------------------------------------------------
# Guards de rôle
# ---------------------------------------------------------------------------
def require_role(*roles: UserRole) -> Callable[[User], User]:
    """
    Factory de dépendance : exige que l'utilisateur ait l'un des rôles fournis.
    Le SUPER_ADMIN (fondateur) est toujours autorisé.
    """
    allowed = set(roles)

    async def _checker(current_user: CurrentUser) -> User:
        if current_user.is_founder or current_user.role == UserRole.SUPER_ADMIN:
            return current_user
        if current_user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Rôle insuffisant (requis : {sorted(r.value for r in allowed)})",
            )
        return current_user

    return _checker


# Raccourcis prêts à l'emploi
RequireAdminTenant = Annotated[User, Depends(require_role(UserRole.ADMIN_TENANT))]
RequireComptable = Annotated[User, Depends(require_role(UserRole.ADMIN_TENANT, UserRole.COMPTABLE))]
RequireAuditeur = Annotated[User, Depends(require_role(UserRole.ADMIN_TENANT, UserRole.AUDITEUR))]
