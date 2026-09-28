"""DTO User — invitation, création, mise à jour, lecture."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.enums import UserRole, UserStatut


class UserCreate(BaseModel):
    email: EmailStr
    nom_complet: str = Field(min_length=2, max_length=150)
    telephone: str | None = None
    role: UserRole = UserRole.LECTEUR
    password: str | None = Field(
        default=None, min_length=12, description="Si absent, un email d'invitation est envoyé"
    )


class UserInviteIn(BaseModel):
    email: EmailStr
    role: UserRole = UserRole.LECTEUR
    nom_complet: str | None = None


class UserUpdate(BaseModel):
    nom_complet: str | None = Field(default=None, min_length=2, max_length=150)
    telephone: str | None = None
    role: UserRole | None = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID | None
    email: EmailStr
    nom_complet: str
    telephone: str | None
    role: UserRole
    statut: UserStatut
    is_founder: bool
    mfa_enabled: bool
    derniere_connexion: datetime | None
    created_at: datetime


class UserBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: EmailStr
    nom_complet: str
    role: UserRole
    statut: UserStatut
