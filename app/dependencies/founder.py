"""
Guard fondateur — accès exclusif au cockpit admin.
Double condition : is_founder=True ET MFA activé (obligatoire pour le cockpit).
"""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status

from app.dependencies.auth import CurrentUser
from app.models.user import User


async def require_founder(current_user: CurrentUser) -> User:
    if not current_user.is_founder:
        # 404 volontaire : ne pas révéler l'existence du cockpit
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ressource introuvable",
        )
    if not current_user.mfa_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="MFA obligatoire pour accéder au cockpit",
        )
    return current_user


FounderUser = Annotated[User, Depends(require_founder)]
