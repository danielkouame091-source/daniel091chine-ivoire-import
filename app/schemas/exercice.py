"""DTO Exercice comptable."""
from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ExerciceCreate(BaseModel):
    libelle: str = Field(min_length=4, max_length=50)
    date_debut: date
    date_fin: date

    @model_validator(mode="after")
    def dates_coherentes(self):
        if self.date_fin <= self.date_debut:
            raise ValueError("date_fin doit être strictement postérieure à date_debut")
        if (self.date_fin - self.date_debut).days > 400:
            raise ValueError("Un exercice ne peut excéder 400 jours")
        return self


class ExerciceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    libelle: str
    date_debut: date
    date_fin: date
    cloture: bool
    cloture_at: datetime | None
    created_at: datetime
