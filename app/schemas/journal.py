"""DTO Journal comptable."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import JournalType


class JournalCreate(BaseModel):
    code: str = Field(min_length=2, max_length=5, pattern=r"^[A-Z]{2,5}$")
    libelle: str = Field(min_length=2, max_length=100)
    type_journal: JournalType
    compte_contrepartie: str | None = Field(default=None, pattern=r"^\d{2,10}$")


class JournalUpdate(BaseModel):
    libelle: str | None = None
    compte_contrepartie: str | None = None
    actif: bool | None = None


class JournalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    code: str
    libelle: str
    type_journal: JournalType
    compte_contrepartie: str | None
    actif: bool
    created_at: datetime
