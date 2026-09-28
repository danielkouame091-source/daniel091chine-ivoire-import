"""
Jobs NLP : traitement en lot de suggestions en attente,
pré-calcul des prévisions de trésorerie (MVP : suggestions uniquement).
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.nlp import NlpSuggestion

logger = logging.getLogger(__name__)


async def traiter_suggestions_en_attente(
    ctx: dict[str, Any],
    tenant_id: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """
    Parcourt les suggestions NLP en attente pour enrichir/valider automatiquement.
    MVP : on ne fait que compter et logger (la validation reste humaine).
    Le but est de disposer d'un job prêt pour brancher un vrai pipeline IA.
    """
    async with AsyncSessionLocal() as db:
        stmt = select(NlpSuggestion).where(NlpSuggestion.statut == "en_attente")
        if tenant_id:
            stmt = stmt.where(NlpSuggestion.tenant_id == tenant_id)
        stmt = stmt.limit(limit)

        rows = (await db.execute(stmt)).scalars().all()
        logger.info(f"[nlp] {len(rows)} suggestions en attente (tenant={tenant_id or 'ALL'})")

        # Résumé par tenant
        par_tenant: dict[str, int] = {}
        for s in rows:
            par_tenant[str(s.tenant_id)] = par_tenant.get(str(s.tenant_id), 0) + 1

        return {
            "total": len(rows),
            "par_tenant": par_tenant,
        }
