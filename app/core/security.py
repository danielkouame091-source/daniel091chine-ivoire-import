"""
Sécurité : JWT RS256, argon2id, TOTP, hash SHA-256.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import HTTPException, status

from app.core.config import settings

# ---------------------------------------------------------------------------
# Argon2id
# ---------------------------------------------------------------------------
_hasher = PasswordHasher(
    time_cost=3, memory_cost=65536, parallelism=4,
    hash_len=32, salt_len=16,
)


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        _hasher.verify(hashed, password)
        return True
    except VerifyMismatchError:
        return False
    except Exception:
        return False


def needs_rehash(hashed: str) -> bool:
    return _hasher.check_needs_rehash(hashed)


# ---------------------------------------------------------------------------
# JWT RS256
# ---------------------------------------------------------------------------
def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_access_token(
    user_id: UUID,
    tenant_id: UUID | None,
    role: str,
    is_founder: bool,
    extra: dict[str, Any] | None = None,
) -> str:
    now = _now()
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "tenant_id": str(tenant_id) if tenant_id else None,
        "role": role,
        "is_founder": is_founder,
        "jti": str(uuid4()),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=settings.JWT_ACCESS_TTL)).timestamp()),
        "typ": "access",
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.JWT_PRIVATE_KEY, algorithm="RS256")


def create_refresh_token(user_id: UUID, jti: UUID | None = None) -> str:
    now = _now()
    jti = jti or uuid4()
    payload = {
        "sub": str(user_id),
        "jti": str(jti),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=settings.JWT_REFRESH_TTL)).timestamp()),
        "typ": "refresh",
    }
    return jwt.encode(payload, settings.JWT_PRIVATE_KEY, algorithm="RS256")


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(
            token, settings.JWT_PUBLIC_KEY, algorithms=["RS256"],
            options={"require": ["exp", "sub", "typ"]},
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expiré")
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail=f"Token invalide : {exc}")
    if payload.get("typ") != "access":
        raise HTTPException(status_code=401, detail="Type de token incorrect")
    return payload


def decode_access_token_unsafe(token: str) -> dict[str, Any] | None:
    """Décodage best-effort pour le middleware (aucune exception levée)."""
    try:
        return jwt.decode(
            token, settings.JWT_PUBLIC_KEY, algorithms=["RS256"],
            options={"verify_exp": False},
        )
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Hash chaînage (audit / écritures)
# ---------------------------------------------------------------------------
def sha256_hex(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def chain_hash(previous_hash: str | None, content: str) -> str:
    prev = previous_hash or "GENESIS"
    return sha256_hex(f"{prev}|{content}")
