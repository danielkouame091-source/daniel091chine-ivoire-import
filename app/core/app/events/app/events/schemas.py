"""
Schémas d'événements — validation stricte à l'entrée/sortie Kafka.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class EventBase(BaseModel):
    """Enveloppe standard de tout événement MTech."""
    model_config = ConfigDict(from_attributes=True)

    event_id: UUID = Field(default_factory=uuid4)
    event_type: str
    tenant_id: UUID
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source: str = "api"
    version: str = "1.0"
    payload: dict[str, Any] = Field(default_factory=dict)

    def to_kafka(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


# ═════════════════════════════════════════════════════════════════════════════
# ÉVÉNEMENTS COMPTABLES
# ═════════════════════════════════════════════════════════════════════════════
class EcritureCreatedEvent(EventBase):
    event_type: Literal["ecriture.created"] = "ecriture.created"

    @classmethod
    def build(
        cls, tenant_id: UUID, ecriture_id: UUID,
        numero_piece: str, montant: int, journal: str, source: str = "api",
    ) -> "EcritureCreatedEvent":
        return cls(
            tenant_id=tenant_id,
            source=source,
            payload={
                "ecriture_id": str(ecriture_id),
                "numero_piece": numero_piece,
                "montant_total_xof": montant,
                "journal": journal,
            },
        )


# ═════════════════════════════════════════════════════════════════════════════
# ÉVÉNEMENTS VENTES
# ═════════════════════════════════════════════════════════════════════════════
class InvoiceCreatedEvent(EventBase):
    event_type: Literal["invoice.created"] = "invoice.created"

    @classmethod
    def build(
        cls, tenant_id: UUID, invoice_id: UUID,
        numero: str, total_ttc: int, customer_id: UUID | None = None,
    ) -> "InvoiceCreatedEvent":
        return cls(
            tenant_id=tenant_id,
            payload={
                "invoice_id": str(invoice_id),
                "numero": numero,
                "total_ttc": total_ttc,
                "customer_id": str(customer_id) if customer_id else None,
            },
        )


class PaymentReceivedEvent(EventBase):
    event_type: Literal["payment.received"] = "payment.received"

    @classmethod
    def build(
        cls, tenant_id: UUID, payment_id: UUID,
        montant: int, mode: str, invoice_id: UUID | None = None,
    ) -> "PaymentReceivedEvent":
        return cls(
            tenant_id=tenant_id,
            payload={
                "payment_id": str(payment_id),
                "montant": montant,
                "mode": mode,
                "invoice_id": str(invoice_id) if invoice_id else None,
            },
        )


# ═════════════════════════════════════════════════════════════════════════════
# ÉVÉNEMENTS MOBILE MONEY
# ═════════════════════════════════════════════════════════════════════════════
class MMTransactionEvent(EventBase):
    event_type: Literal["mobile_money.transaction"] = "mobile_money.transaction"

    @classmethod
    def build(
        cls, tenant_id: UUID, provider: str,
        montant: int, sens: str, external_id: str,
    ) -> "MMTransactionEvent":
        return cls(
            tenant_id=tenant_id,
            payload={
                "provider": provider,
                "montant": montant,
                "sens": sens,
                "external_id": external_id,
            },
        )


# ═════════════════════════════════════════════════════════════════════════════
# ÉVÉNEMENTS AUDIT
# ═════════════════════════════════════════════════════════════════════════════
class AuditFindingEvent(EventBase):
    event_type: Literal["audit.finding.detected"] = "audit.finding.detected"

    @classmethod
    def build(
        cls, tenant_id: UUID, finding_id: UUID,
        severite: str, regle: str,
    ) -> "AuditFindingEvent":
        return cls(
            tenant_id=tenant_id,
            payload={
                "finding_id": str(finding_id),
                "severite": severite,
                "regle": regle,
            },
        )
