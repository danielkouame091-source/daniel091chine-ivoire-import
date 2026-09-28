"""Endpoints d'authentification : login, MFA, refresh, logout, me."""
from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import jwt
import pyotp
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.crypto import encrypt
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_access_token,
    hash_password,
    sha256_hex,
    verify_password,
)
from app.db.deps import get_db
from app.dependencies.auth import CurrentUser
from app.models.enums import UserStatut
from app.models.session import Session as SessionModel
from app.models.user import User
from app.schemas.auth import (
    ChangePasswordIn,
    CurrentUserOut,
    LoginIn,
    MfaSetupOut,
    MfaVerifyIn,
    RefreshIn,
    TokenOut,
)

router = APIRouter()


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------
def _create_mfa_pending_token(user_id: UUID) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "typ": "mfa_pending",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=settings.JWT_MFA_TTL)).timestamp()),
    }
    return jwt.encode(payload, settings.JWT_PRIVATE_KEY, algorithm="RS256")


def _decode_mfa_pending_token(token: str) -> UUID:
    try:
        payload = jwt.decode(token, settings.JWT_PUBLIC_KEY, algorithms=["RS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Session MFA expirée")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Token MFA invalide")
    if payload.get("typ") != "mfa_pending":
        raise HTTPException(401, "Type de token incorrect")
    return UUID(payload["sub"])


async def _create_session(
    db: AsyncSession,
    user: User,
    request: Request,
) -> tuple[str, str]:
    """Crée une Session DB + retourne (access_token, refresh_token)."""
    jti = uuid4()
    refresh = create_refresh_token(user.id, jti=jti)
    access = create_access_token(
        user_id=user.id,
        tenant_id=user.tenant_id,
        role=user.role.value,
        is_founder=user.is_founder,
    )

    now = datetime.now(timezone.utc)
    db.add(
        SessionModel(
            user_id=user.id,
            tenant_id=user.tenant_id,
            jti=jti,
            refresh_hash=sha256_hex(refresh),
            ip=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
            expires_at=now + timedelta(seconds=settings.JWT_REFRESH_TTL),
        )
    )
    await db.flush()
    return access, refresh


# ---------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------
@router.post("/login", response_model=TokenOut, status_code=status.HTTP_200_OK)
async def login(
    data: LoginIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> TokenOut:
    user = (
        await db.execute(select(User).where(User.email == data.email, User.deleted_at.is_(None)))
    ).scalar_one_or_none()
    if user is None or not verify_password(data.password, user.password_hash):
        # Message volontairement identique (éviter l'énumération d'emails)
        raise HTTPException(401, "Identifiants invalides")

    if user.statut == UserStatut.REVOQUE:
        raise HTTPException(403, "Compte révoqué")
    if user.statut == UserStatut.GELE:
        raise HTTPException(403, "Compte gelé")

    if user.mfa_enabled:
        return TokenOut(
            access_token="",
            refresh_token=None,
            mfa_required=True,
            session_token=_create_mfa_pending_token(user.id),
            expires_in=settings.JWT_MFA_TTL,
        )

    access, refresh = await _create_session(db, user, request)
    user.derniere_connexion = datetime.now(timezone.utc)
    user.derniere_ip = request.client.host if request.client else None
    user.tentatives_echec = 0
    await db.flush()

    return TokenOut(
        access_token=access,
        refresh_token=refresh,
        expires_in=settings.JWT_ACCESS_TTL,
    )


@router.post("/mfa/verify", response_model=TokenOut)
async def mfa_verify(
    data: MfaVerifyIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> TokenOut:
    user_id = _decode_mfa_pending_token(data.session_token)
    user = (
        await db.execute(select(User).where(User.id == user_id, User.deleted_at.is_(None)))
    ).scalar_one_or_none()
    if user is None or not user.mfa_enabled or not user.mfa_secret_enc:
        raise HTTPException(401, "Utilisateur MFA invalide")

    from app.core.crypto import decrypt  # import local pour éviter cycle

    secret = decrypt(user.mfa_secret_enc)
    totp = pyotp.TOTP(secret)
    if not totp.verify(data.code, valid_window=1):
        user.tentatives_echec = (user.tentatives_echec or 0) + 1
        await db.flush()
        raise HTTPException(401, "Code MFA invalide")

    access, refresh = await _create_session(db, user, request)
    user.derniere_connexion = datetime.now(timezone.utc)
    user.tentatives_echec = 0
    await db.flush()

    return TokenOut(
        access_token=access,
        refresh_token=refresh,
        expires_in=settings.JWT_ACCESS_TTL,
    )


@router.post("/mfa/setup", response_model=MfaSetupOut)
async def mfa_setup(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> MfaSetupOut:
    if current_user.mfa_enabled:
        raise HTTPException(400, "MFA déjà activé")

    secret = pyotp.random_base32()
    totp = pyotp.TOTP(secret)
    uri = totp.provisioning_uri(
        name=current_user.email, issuer_name=settings.APP_NAME
    )

    # Backup codes (8 codes de 10 chars)
    backup_codes = [base64.b32encode(uuid4().bytes).decode()[:10] for _ in range(8)]

    # On stocke secret + backup chiffrés (mais mfa_enabled reste false jusqu'à /enable)
    current_user.mfa_secret_enc = encrypt(secret)
    current_user.mfa_backup_codes_enc = encrypt("\n".join(backup_codes))
    await db.flush()

    return MfaSetupOut(secret=secret, qr_code_url=uri, backup_codes=backup_codes)


@router.post("/mfa/enable", status_code=status.HTTP_204_NO_CONTENT)
async def mfa_enable(
    code: str,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> None:
    if current_user.mfa_enabled:
        raise HTTPException(400, "MFA déjà activé")
    if not current_user.mfa_secret_enc:
        raise HTTPException(400, "Aucun setup MFA en cours — appelez /mfa/setup d'abord")

    from app.core.crypto import decrypt

    totp = pyotp.TOTP(decrypt(current_user.mfa_secret_enc))
    if not totp.verify(code, valid_window=1):
        raise HTTPException(400, "Code MFA invalide")

    current_user.mfa_enabled = True
    await db.flush()


@router.post("/refresh", response_model=TokenOut)
async def refresh(
    data: RefreshIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> TokenOut:
    try:
        payload = jwt.decode(data.refresh_token, settings.JWT_PUBLIC_KEY, algorithms=["RS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Refresh token expiré")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Refresh token invalide")

    if payload.get("typ") != "refresh":
        raise HTTPException(401, "Type de token incorrect")

    jti = UUID(payload["jti"])
    session = (
        await db.execute(
            select(SessionModel).where(
                SessionModel.jti == jti, SessionModel.revoquee_at.is_(None)
            )
        )
    ).scalar_one_or_none()
    if session is None:
        raise HTTPException(401, "Session révoquée")

    if session.refresh_hash != sha256_hex(data.refresh_token):
        # Token rejoué / volé → révocation immédiate
        session.revoquee_at = datetime.now(timezone.utc)
        await db.flush()
        raise HTTPException(401, "Refresh token invalide (rejeu détecté)")

    user = (
        await db.execute(select(User).where(User.id == session.user_id))
    ).scalar_one_or_none()
    if user is None or user.statut != UserStatut.ACTIF:
        raise HTTPException(403, "Compte inactif")

    # Rotation : révoquer l'ancienne session, en créer une nouvelle
    session.revoquee_at = datetime.now(timezone.utc)
    access, refresh_new = await _create_session(db, user, request)
    return TokenOut(
        access_token=access,
        refresh_token=refresh_new,
        expires_in=settings.JWT_ACCESS_TTL,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> None:
    jti = getattr(request.state, "jti", None)
    if not jti:
        return
    session = (
        await db.execute(
            select(SessionModel).where(SessionModel.jti == UUID(jti))
        )
    ).scalar_one_or_none()
    if session is not None and session.revoquee_at is None:
        session.revoquee_at = datetime.now(timezone.utc)
        await db.flush()


@router.get("/me", response_model=CurrentUserOut)
async def me(current_user: CurrentUser) -> CurrentUserOut:
    return CurrentUserOut.model_validate(current_user)


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    data: ChangePasswordIn,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> None:
    if not verify_password(data.ancien_motd, current_user.password_hash):
        raise HTTPException(400, "Ancien mot de passe incorrect")
    current_user.password_hash = hash_password(data.nouveau_motd)
    await db.flush()
