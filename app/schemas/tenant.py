"""DTO Tenant — création, mise à jour, lecture."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models.enums import TenantStatut


class AdresseIn(BaseModel):
    rue: str | None = None
    commune: str | None = None
    ville: str | None = None
    bp: str | None = None
    pays: str = "Côte d'Ivoire"


class TenantCreate(BaseModel):
    slug: str = Field(min_length=3, max_length=50, pattern=r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")
    raison_sociale: str = Field(min_length=2, max_length=200)
    forme_juridique: str | None = None
    rccm: str | None = None
    compte_contribuable: str | None = Field(default=None, max_length=20)
    numero_cnps: str | None = None
    regime_fiscal: str | None = Field(
        default=None, pattern=r"^(RME|RNI|RSI|TPU|ZONE_FRANCHE)$"
    )
    centre_impots: str | None = None
    telephone: str | None = None
    email: EmailStr | None = None
    adresse: AdresseIn | None = None

    @field_validator("slug")
    @classmethod
    def slug_lowercase(cls, v: str) -> str:
        return v.lower()


class TenantUpdate(BaseModel):
    raison_sociale: str | None = Field(default=None, min_length=2, max_length=200)
    forme_juridique: str | None = None
    rccm: str | None = None
    compte_contribuable: str | None = None
    numero_cnps: str | None = None
    regime_fiscal: str | None = Field(
        default=None, pattern=r"^(RME|RNI|RSI|TPU|ZONE_FRANCHE)$"
    )
    telephone: str | None = None
    email: EmailStr | None = None
    adresse: AdresseIn | None = None
    logo_url: str | None = None


class TenantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slug: str
    raison_sociale: str
    forme_juridique: str | None
    rccm: str | None
    compte_contribuable: str | None
    regime_fiscal: str | None
    pays: str
    devise: str
    fuseau: str
    telephone: str | None
    email: EmailStr | None
    logo_url: str | None
    statut: TenantStatut
    created_at: datetime


class TenantBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slug: str
    raison_sociale: str
    statut: TenantStatut
