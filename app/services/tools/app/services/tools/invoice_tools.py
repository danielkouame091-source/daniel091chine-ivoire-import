"""Outils factures pour le chatbot."""
from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sale import CustomerInvoice
from app.services.tool_registry import Tool, tool_registry


async def _factures_impayees(
    db: AsyncSession,
    tenant_id: UUID,
    user_id: UUID,
    limit: int = 20,
) -> dict[str, Any]:
    """Liste les factures impayées."""
    stmt = (
        select(CustomerInvoice)
        .where(
            CustomerInvoice.tenant_id == tenant_id,
            CustomerInvoice.solde_du > 0,
            CustomerInvoice.statut.notin_(["annulee", "brouillon"]),
        )
        .order_by(CustomerInvoice.date_echeance)
        .limit(limit)
    )
    rows = (await db.execute(stmt)).scalars().all()

    total_du = sum(i.solde_du for i in rows)
    return {
        "success": True,
        "count": len(rows),
        "total_du_xof": total_du,
        "factures": [
            {
                "numero": i.numero,
                "date_echeance": i.date_echeance.isoformat(),
                "solde_du": i.solde_du,
                "client_id": str(i.customer_id),
                "jours_retard": max(0, (date.today() - i.date_echeance).days) if i.date_echeance else 0,
            }
            for i in rows
        ],
    }


async def _facture_detail(
    db: AsyncSession,
    tenant_id: UUID,
    user_id: UUID,
    numero: str,
) -> dict[str, Any]:
    """Détail d'une facture par numéro."""
    stmt = select(CustomerInvoice).where(
        CustomerInvoice.tenant_id == tenant_id,
        CustomerInvoice.numero == numero,
    )
    i = (await db.execute(stmt)).scalar_one_or_none()
    if i is None:
        return {"success": False, "error": f"Facture {numero} introuvable"}

    return {
        "success": True,
        "facture": {
            "numero": i.numero,
            "date_facture": i.date_facture.isoformat(),
            "date_echeance": i.date_echeance.isoformat(),
            "total_ttc": i.total_ttc,
            "solde_du": i.solde_du,
            "statut": i.statut,
        },
    }


# ─── ENREGISTREMENT ─────────────────────────────────────────
tool_registry.register(Tool(
    name="factures_impayees",
    description="Liste les factures clients impayées avec le total dû.",
    parameters={
        "type": "object",
        "properties": {"limit": {"type": "integer", "default": 20}},
    },
    handler=_factures_impayees,
))

tool_registry.register(Tool(
    name="detail_facture",
    description="Retourne le détail d'une facture par son numéro.",
    parameters={
        "type": "object",
        "properties": {"numero": {"type": "string"}},
        "required": ["numero"],
    },
    handler=_facture_detail,
))
