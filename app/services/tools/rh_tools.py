"""Outils RH pour le chatbot (congés, employés)."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr import LeaveRequest
from app.models.payroll import Employee
from app.services.tool_registry import Tool, tool_registry


async def _conges_en_attente(
    db: AsyncSession,
    tenant_id: UUID,
    user_id: UUID,
) -> dict[str, Any]:
    """Liste les demandes de congé en attente de validation."""
    stmt = (
        select(LeaveRequest)
        .where(
            LeaveRequest.tenant_id == tenant_id,
            LeaveRequest.statut.in_(["soumise", "validee_manager"]),
        )
        .order_by(LeaveRequest.date_debut)
    )
    rows = (await db.execute(stmt)).scalars().all()

    return {
        "success": True,
        "count": len(rows),
        "demandes": [
            {
                "id": str(r.id),
                "employee_id": str(r.employee_id),
                "type_conge": r.type_conge,
                "date_debut": r.date_debut.isoformat(),
                "date_fin": r.date_fin.isoformat(),
                "nb_jours": float(r.nb_jours_ouvrables),
                "statut": r.statut,
            }
            for r in rows
        ],
    }


async def _effectif_actif(
    db: AsyncSession,
    tenant_id: UUID,
    user_id: UUID,
) -> dict[str, Any]:
    """Nombre d'employés actifs."""
    count = int(await db.scalar(
        select(func.count(Employee.id)).where(
            Employee.tenant_id == tenant_id,
            Employee.actif.is_(True),
        )
    ) or 0)
    return {"success": True, "effectif_actif": count}


# ─── ENREGISTREMENT ─────────────────────────────────────────
tool_registry.register(Tool(
    name="conges_en_attente",
    description="Liste les demandes de congé en attente de validation.",
    parameters={"type": "object", "properties": {}},
    handler=_conges_en_attente,
    require_admin=True,
))

tool_registry.register(Tool(
    name="effectif_actif",
    description="Retourne le nombre d'employés actifs.",
    parameters={"type": "object", "properties": {}},
    handler=_effectif_actif,
))
