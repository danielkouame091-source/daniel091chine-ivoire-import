"""DTO Mobile Money — payloads providers + réponses internes."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import MMProvider, MMSens, MMStatut


class MmTransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    provider: MMProvider
    external_id: str
    montant_xof: int
    frais_xof: int
    sens: MMSens
    numero_tiers: str | None
    libelle: str | None
    horodatage: datetime
    statut_rappro: MMStatut
    ecriture_id: UUID | None
    rapproche_at: datetime | None
    created_at: datetime


class MmRapprochementIn(BaseModel):
    """Rapprochement manuel d'une transaction Mobile Money."""
    ecriture_id: UUID | None = Field(
        default=None,
        description="Si absent, une écriture d'attente est générée automatiquement",
    )
    compte_contrepartie: str | None = Field(
        default=None, pattern=r"^\d{2,10}$"
    )


# ---------------------------------------------------------------------
# Payloads providers (contrats webhooks — à ajuster selon les specs API)
# ---------------------------------------------------------------------
class WaveWebhookPayload(BaseModel):
    id: str
    amount: int
    fees: int = 0
    type: str = "credit"
    counterparty: str | None = None
    label: str | None = None
    timestamp: datetime
    currency: str = "XOF"


class OrangeMoneyWebhookPayload(BaseModel):
    transaction_id: str
    amount: int
    fees: int = 0
    type: str = "credit"
    msisdn: str | None = None
    label: str | None = None
    timestamp: datetime


class MtnMomoWebhookPayload(BaseModel):
    transaction_id: str
    amount: int
    fees: int = 0
    type: str = "credit"
    payer_message: str | None = None
    payee_note: str | None = None
    timestamp: datetime
