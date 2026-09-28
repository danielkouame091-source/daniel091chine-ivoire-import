"""DTO Plan comptable SYSCOHADA."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import CompteType


class PlanComptableCreate(BaseModel):
    compte: str = Field(min_length=2, max_length=10, pattern=r"^\d{2,10}$")
    libelle: str = Field(min_length=2, max_length=200)
    classe: int = Field(ge=1, le=9)
    type_compte: CompteType
    collectif: bool = False
    lettrable: bool = True
    auxiliaire: bool = False

    @field_validator("classe")
    @classmethod
    def classe_coherente_avec_compte(cls, v: int, info):
        compte = info.data.get("compte")
        if compte and int(compte[0]) != v:
            raise ValueError(
                f"La classe {v} ne correspond pas au 1er chiffre du compte '{compte}'"
            )
        return v


class PlanComptableUpdate(BaseModel):
    libelle: str | None = Field(default=None, min_length=2, max_length=200)
    collectif: bool | None = None
    lettrable: bool | None = None
    auxiliaire: bool | None = None
    actif: bool | None = None


class PlanComptableOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    compte: str
    libelle: str
    classe: int
    type_compte: CompteType
    collectif: bool
    lettrable: bool
    auxiliaire: bool
    actif: bool
    created_at: datetime


class PlanComptableImportRow(BaseModel):
    """Ligne d'import CSV — validation stricte."""
    compte: str
    libelle: str
    type_compte: CompteType

    @field_validator("compte")
    @classmethod
    def compte_valide(cls, v: str) -> str:
        v = v.strip()
        if not v.isdigit() or not (2 <= len(v) <= 10):
            raise ValueError(f"Compte invalide : {v}")
        return v
