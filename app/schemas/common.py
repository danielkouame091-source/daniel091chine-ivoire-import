"""Types et DTO transverses : pagination, réponses génériques, montants XOF."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")

# Montant XOF : entier strictement positif ou nul, pas de décimales
MontantXOF = Annotated[int, Field(ge=0, le=10**15, description="Montant en francs CFA (entier)")]

# Identifiant UUID côté API
UUIDStr = Annotated[UUID, Field(description="UUID v4")]


class ORMModel(BaseModel):
    """Base pour tous les schémas lus depuis SQLAlchemy."""
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class TimestampedOut(ORMModel):
    created_at: datetime
    updated_at: datetime | None = None


class PaginationParams(BaseModel):
    page: int = Field(1, ge=1)
    page_size: int = Field(50, ge=1, le=200)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    total_pages: int = Field(ge=0)


class ApiError(BaseModel):
    code: str
    message: str
    details: dict | None = None


class ApiResponse(BaseModel, Generic[T]):
    success: bool = True
    data: T | None = None
    error: ApiError | None = None
