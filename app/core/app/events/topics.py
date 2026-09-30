"""
Définition des topics Kafka — Convention : mtech.{domaine}.{entité}.{action}
Partitionnement : par tenant_id (garantit l'ordre par tenant).
"""
from __future__ import annotations

from enum import Enum


class KafkaTopic(str, Enum):
    # ─── Écritures comptables ──────────────────────────────
    ECRITURE_CREATED     = "mtech.comptabilite.ecriture.created"
    ECRITURE_VALIDATED   = "mtech.comptabilite.ecriture.validated"

    # ─── Ventes ─────────────────────────────────────────────
    INVOICE_CREATED      = "mtech.ventes.invoice.created"
    INVOICE_PAID         = "mtech.ventes.invoice.paid"
    PAYMENT_RECEIVED     = "mtech.ventes.payment.received"

    # ─── Achats ─────────────────────────────────────────────
    PO_CREATED           = "mtech.achats.purchase_order.created"
    SUPPLIER_INVOICE     = "mtech.achats.supplier_invoice.created"

    # ─── Trésorerie ─────────────────────────────────────────
    MM_TRANSACTION       = "mtech.tresorerie.mobile_money.transaction"
    BANK_TRANSACTION     = "mtech.tresorerie.bank.transaction"
    RECONCILIATION       = "mtech.tresorerie.reconciliation.done"

    # ─── Stocks ─────────────────────────────────────────────
    STOCK_MOVEMENT       = "mtech.stocks.movement"
    STOCK_LOW            = "mtech.stocks.low"

    # ─── RH ─────────────────────────────────────────────────
    LEAVE_REQUESTED      = "mtech.rh.leave.requested"
    PAYSLIP_GENERATED    = "mtech.rh.payslip.generated"

    # ─── FNE / Fiscal ───────────────────────────────────────
    FNE_CERTIFIED        = "mtech.fne.certified"
    FNE_REJECTED         = "mtech.fne.rejected"

    # ─── Projets ────────────────────────────────────────────
    PROJECT_MILESTONE    = "mtech.projets.milestone.reached"

    # ─── Audit ──────────────────────────────────────────────
    AUDIT_FINDING        = "mtech.audit.finding.detected"


# Nombre de partitions par topic (à ajuster selon le volume attendu)
TOPIC_PARTITIONS: dict[str, int] = {
    KafkaTopic.ECRITURE_CREATED: 12,
    KafkaTopic.ECRITURE_VALIDATED: 12,
    KafkaTopic.INVOICE_CREATED: 12,
    KafkaTopic.INVOICE_PAID: 12,
    KafkaTopic.PAYMENT_RECEIVED: 12,
    KafkaTopic.PO_CREATED: 6,
    KafkaTopic.SUPPLIER_INVOICE: 6,
    KafkaTopic.MM_TRANSACTION: 24,       # Volume élevé
    KafkaTopic.BANK_TRANSACTION: 12,
    KafkaTopic.RECONCILIATION: 6,
    KafkaTopic.STOCK_MOVEMENT: 12,
    KafkaTopic.STOCK_LOW: 6,
    KafkaTopic.LEAVE_REQUESTED: 3,
    KafkaTopic.PAYSLIP_GENERATED: 6,
    KafkaTopic.FNE_CERTIFIED: 12,
    KafkaTopic.FNE_REJECTED: 6,
    KafkaTopic.PROJECT_MILESTONE: 6,
    KafkaTopic.AUDIT_FINDING: 6,
}

TOPIC_REPLICATION_FACTOR = 3   # Production : 3 brokers minimum
