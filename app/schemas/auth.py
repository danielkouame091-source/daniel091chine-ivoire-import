"""DTO d'authentification : login, MFA, refresh, tokens."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models.enums import UserRole


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class MfaVerifyIn(BaseModel):
    email: EmailStr
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")
    session_token: str = Field(min_length=10)


class MfaSetupOut(BaseModel):
    secret: str
    qr_code_url: str
    backup_codes: list[str] = Field(min_length=8, max_length=8)


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str | None = None
    token_type: str = "bearer"
    expires_in: int = Field(description="Durée de vie access token en secondes")
    mfa_required: bool = False
    session_token: str | None = Field(
        default=None, description="Jeton temporaire si MFA requis"
    )


class RefreshIn(BaseModel):
    refresh_token: str = Field(min_length=20)


class CurrentUserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: EmailStr
    nom_complet: str
    role: UserRole
    is_founder: bool
    tenant_id: UUID | None
    mfa_enabled: bool
    derniere_connexion: datetime | None = None


class ChangePasswordIn(BaseModel):
    ancien_motd: str = Field(alias="ancien_mot_de_passe", min_length=8)
    nouveau_motd: str = Field(alias="nouveau_mot_de_passe", min_length=12)

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("nouveau_motd")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if not any(c.isdigit() for c in v):
            raise ValueError("Le mot de passe doit contenir au moins un chiffre")
        if not any(c.isupper() for c in v):
            raise ValueError("Le mot de passe doit contenir au moins une majuscule")
        if not any(c in "!@#$%^&*()-_=+[]{};:,.<>?" for c in v):
            raise ValueError("Le mot de passe doit contenir un caractère spécial")
        return v
