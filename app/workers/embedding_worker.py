"""
Worker ARQ — indexation asynchrone des nouveaux documents.
Déclenché automatiquement quand un document est créé/mis à jour.
"""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from app.db.session import AsyncSessionLocal
from app.services.embedding_service import EmbeddingService

logger = logging.getLogger(__name__)


async def indexer_document_async(
    ctx: dict[str, Any],
    tenant_id: str | None,
    titre: str,
    contenu: str,
    source_type: str,
    source_id: str | None = None,
    categorie: str | None = None,
    langue: str = "fr",
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Indexe un document en arrière-plan."""
    tid = UUID(tenant_id) if tenant_id else None

    async with AsyncSessionLocal() as db:
        svc = EmbeddingService(db, tenant_id=tid)
        doc = await svc.indexer_document(
            titre=titre,
            contenu=contenu,
            source_type=source_type,
            source_id=UUID(source_id) if source_id else None,
            categorie=categorie,
            langue=langue,
            tags=tags,
        )
        await db.commit()
        return {"ok": True, "document_id": str(doc.id)}
