"""Outil de recherche dans la base de connaissance (RAG)."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.rag_service import RAGService
from app.services.tool_registry import Tool, tool_registry


async def _recherche_documentation(
    db: AsyncSession,
    tenant_id: UUID,
    user_id: UUID,
    query: str,
    limit: int = 5,
) -> dict[str, Any]:
    """Recherche dans la base de connaissance (articles, docs, règles)."""
    rag = RAGService(db, tenant_id)
    chunks = await rag.retrieve(query, top_k=limit)

    return {
        "success": True,
        "count": len(chunks),
        "resultats": [
            {
                "titre": c["titre"],
                "extrait": c["contenu"][:500],
                "score": c["score_rrf"],
                "source_url": c.get("source_url"),
            }
            for c in chunks
        ],
    }


tool_registry.register(Tool(
    name="rechercher_documentation",
    description="Recherche dans la base de connaissance MTech (articles, procédures, "
                "règles comptables SYSCOHADA, réglementation fiscale CI).",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Requête de recherche"},
            "limit": {"type": "integer", "default": 5},
        },
        "required": ["query"],
    },
    handler=_recherche_documentation,
))
