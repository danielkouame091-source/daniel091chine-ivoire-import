"""DTO Gel en cascade — requêtes et réponses."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import FreezeCible, FreezeStatut


class FreezeRequest(BaseModel):
    cible_type: FreezeCible
    cible_id: UUID
    motif: str = Field(min_length=10, max_length=500)
    details: dict | None = None
    cascade: bool = Field(
        default=True,
        description="Si False, seule la cible directe est gelée",
    )


class UnfreezeRequest(BaseModel):
    freeze_event_id: UUID
    motif_levee: str = Field(min_length=10, max_length=500)


class FreezeTargetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    cible_type: FreezeCible
    cible_id: UUID
    niveau_profondeur: int
    raison: str
    statut: FreezeStatut
    gele_at: datetime
    leve_at: datetime | None


class FreezeEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    cible_type: FreezeCible
    cible_id: UUID
    motif: str
    details: dict
    declencheur_user_id: UUID | None
    cascade_profondeur: int
    statut: FreezeStatut
    leve_at: datetime | None
    leve_par: UUID | None
    created_at: datetime
    targets: list[FreezeTargetOut] = Field(default_factory=list)


class FreezeResultOut(BaseModel):
    """Résultat complet d'une opération de gel — utilisé par l'API."""
    event: FreezeEventOut
    cibles_atteintes: list[FreezeTargetOut]
    total_cibles: int = Field(ge=0)


class TenantFreezeStateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tenant_id: UUID
    gele: bool
    freeze_event_id: UUID | None
    motif: str | None
    gele_at: datetime | None
    updated_at: datetime


class FreezeCascadeRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_type: FreezeCible
    cible_type: FreezeCible
    propagation: str
    blocage_ecriture: bool
    description: str | None
