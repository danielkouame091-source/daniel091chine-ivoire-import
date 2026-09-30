"""Outils pour les écritures comptables (création, consultation)."""
from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ecriture import Ecriture
from app.services.syscohada_service import SyscohadaService
from app.services.tool_registry import Tool, tool_registry


async def _create_ecriture(
    db: AsyncSession,
    tenant_id: UUID,
    user_id: UUID,
    date_ecriture: str,
    code_journal: str,
    libelle: str,
    lignes: list[dict[str, Any]],
) -> dict[str, Any]:
    """Crée une écriture comptable SYSCOHADA."""
    from app.schemas.ecriture import EcritureCreate, LigneIn

    try:
        lignes_pyd = [
            LigneIn(
                compte=l["compte"],
                debit=int(l.get("debit", 0)),
                credit=int(l.get("credit", 0)),
            )
            for l in lignes
        ]

        svc = SyscohadaService(db, tenant_id, user_id)
        ecriture = await svc.create(EcritureCreate(
            date_ecriture=date.fromisoformat(date_ecriture),
            code_journal=code_journal,
            libelle=libelle,
            source="ia_nlp",
            lignes=lignes_pyd,
        ))

        return {
            "success": True,
            "ecriture_id": str(ecriture.id),
            "numero_piece": ecriture.numero_piece,
            "message": f"Écriture {ecriture.numero_piece} créée avec succès.",
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


async def _search_ecritures(
    db: AsyncSession,
    tenant_id: UUID,
    user_id: UUID,
    query: str | None = None,
    date_debut: str | None = None,
    date_fin: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Recherche des écritures."""
    stmt = select(Ecriture).where(Ecriture.tenant_id == tenant_id)
    if query:
        stmt = stmt.where(Ecriture.libelle.ilike(f"%{query}%"))
    if date_debut:
        stmt = stmt.where(Ecriture.date_ecriture >= date.fromisoformat(date_debut))
    if date_fin:
        stmt = stmt.where(Ecriture.date_ecriture <= date.fromisoformat(date_fin))

    stmt = stmt.order_by(Ecriture.date_ecriture.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()

    return {
        "success": True,
        "count": len(rows),
        "ecritures": [
            {
                "numero": e.numero_piece,
                "date": e.date_ecriture.isoformat(),
                "libelle": e.libelle,
                "statut": e.statut.value if hasattr(e.statut, "value") else str(e.statut),
            }
            for e in rows
        ],
    }


async def _sum_ecritures(
    db: AsyncSession,
    tenant_id: UUID,
    user_id: UUID,
    compte_prefixe: str,
    date_debut: str,
    date_fin: str,
) -> dict[str, Any]:
    """Somme des mouvements sur un préfixe de compte."""
    from app.models.ecriture import EcritureLigne
    from app.models.plan_comptable import PlanComptable

    stmt = (
        select(
            func.coalesce(func.sum(EcritureLigne.debit_xof), 0),
            func.coalesce(func.sum(EcritureLigne.credit_xof), 0),
        )
        .join(PlanComptable, PlanComptable.id == EcritureLigne.compte_id)
        .join(Ecriture, Ecriture.id == EcritureLigne.ecriture_id)
        .where(
            EcritureLigne.tenant_id == tenant_id,
            PlanComptable.compte.like(f"{compte_prefixe}%"),
            Ecriture.date_ecriture.between(
                date.fromisoformat(date_debut), date.fromisoformat(date_fin)
            ),
        )
    )
    row = (await db.execute(stmt)).one()
    debit = int(row[0] or 0)
    credit = int(row[1] or 0)

    return {
        "success": True,
        "compte_prefixe": compte_prefixe,
        "debit_xof": debit,
        "credit_xof": credit,
        "solde_xof": debit - credit,
    }


# ─── ENREGISTREMENT ─────────────────────────────────────────
tool_registry.register(Tool(
    name="creer_ecriture",
    description="Crée une écriture comptable SYSCOHADA en partie double. "
                "Utilise cet outil quand l'utilisateur demande d'enregistrer une opération.",
    parameters={
        "type": "object",
        "properties": {
            "date_ecriture": {"type": "string", "description": "Date au format YYYY-MM-DD"},
            "code_journal": {
                "type": "string",
                "enum": ["VE", "AC", "BQ", "CA", "OD", "MM"],
                "description": "Code du journal (VE=vente, AC=achat, BQ=banque, CA=caisse, MM=mobile money)",
            },
            "libelle": {"type": "string", "description": "Libellé de l'opération"},
            "lignes": {
                "type": "array",
                "minItems": 2,
                "items": {
                    "type": "object",
                    "properties": {
                        "compte": {"type": "string"},
                        "debit": {"type": "integer"},
                        "credit": {"type": "integer"},
                    },
                    "required": ["compte"],
                },
            },
        },
        "required": ["date_ecriture", "code_journal", "libelle", "lignes"],
    },
    handler=_create_ecriture,
))

tool_registry.register(Tool(
    name="rechercher_ecritures",
    description="Recherche des écritures comptables par libellé ou période.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "date_debut": {"type": "string"},
            "date_fin": {"type": "string"},
            "limit": {"type": "integer", "default": 10},
        },
    },
    handler=_search_ecritures,
))

tool_registry.register(Tool(
    name="somme_comptes",
    description="Calcule la somme des mouvements sur un préfixe de compte (ex: 70 pour CA).",
    parameters={
        "type": "object",
        "properties": {
            "compte_prefixe": {"type": "string"},
            "date_debut": {"type": "string"},
            "date_fin": {"type": "string"},
        },
        "required": ["compte_prefixe", "date_debut", "date_fin"],
    },
    handler=_sum_ecritures,
))
