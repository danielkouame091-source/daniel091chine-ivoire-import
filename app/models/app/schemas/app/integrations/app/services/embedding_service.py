"""Service Embeddings — génération + stockage des vecteurs."""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.ollama_client import ollama_client
from app.models.embeddings import DocumentChunk, KnowledgeDocument

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Génère et stocke les embeddings dans pgvector."""

    def __init__(self, db: AsyncSession, tenant_id: UUID | None = None) -> None:
        self.db = db
        self.tenant_id = tenant_id

    async def indexer_document(
        self,
        titre: str,
        contenu: str,
        source_type: str,
        source_id: UUID | None = None,
        categorie: str | None = None,
        langue: str = "fr",
        tags: list[str] | None = None,
    ) -> KnowledgeDocument:
        """
        Indexe un document : découpe en chunks + génère les embeddings + stocke.
        """
        # 1. Créer le document
        doc = KnowledgeDocument(
            tenant_id=self.tenant_id,
            source_type=source_type,
            source_id=source_id,
            titre=titre,
            categorie=categorie,
            contenu=contenu,
            langue=langue,
            tags=tags or [],
        )
        self.db.add(doc)
        await self.db.flush()

        # 2. Chunker
        chunks = self._chunker(contenu)

        # 3. Générer les embeddings en batch
        logger.info(f"[embedding] {len(chunks)} chunks à indexer pour '{titre}'")
        embeddings = await ollama_client.embed_batch(chunks)

        # 4. Insérer les chunks
        for i, (chunk_text, embedding) in enumerate(zip(chunks, embeddings)):
            chunk = DocumentChunk(
                document_id=doc.id,
                tenant_id=self.tenant_id,
                ordre=i,
                contenu=chunk_text,
                nb_tokens=len(chunk_text.split()),
                embedding=embedding,
            )
            self.db.add(chunk)

        await self.db.flush()

        # 5. Mettre à jour le tsvector pour BM25
        await self.db.execute(
            text("""
                UPDATE knowledge_chunks
                SET search_vector = to_tsvector('french', contenu)
                WHERE document_id = :doc_id
            """),
            {"doc_id": doc.id},
        )

        await self.db.flush()
        logger.info(f"[embedding] Document indexé : {doc.id}")
        return doc

    async def recherche_vectorielle(
        self,
        query: str,
        limit: int = 10,
        seuil_similarite: float = 0.65,
    ) -> list[dict[str, Any]]:
        """
        Recherche les chunks les plus similaires par cosinus.
        Utilise l'index HNSW pour la performance.
        """
        # 1. Embedding de la requête
        query_embedding = await ollama_client.embed(query)

        # 2. Requête pgvector — distance cosinus
        # score = 1 - distance_cosinus
        stmt = (
            select(
                DocumentChunk,
                KnowledgeDocument.titre,
                KnowledgeDocument.source_type,
                KnowledgeDocument.source_url,
                (1 - DocumentChunk.embedding.cosine_distance(query_embedding)).label("score"),
            )
            .join(KnowledgeDocument, KnowledgeDocument.id == DocumentChunk.document_id)
            .where(
                (DocumentChunk.tenant_id == self.tenant_id) | (DocumentChunk.tenant_id.is_(None)),
                DocumentChunk.embedding.cosine_distance(query_embedding) < (1 - seuil_similarite),
            )
            .order_by(DocumentChunk.embedding.cosine_distance(query_embedding))
            .limit(limit)
        )

        rows = (await self.db.execute(stmt)).all()
        return [
            {
                "chunk_id": r[0].id,
                "document_id": r[0].document_id,
                "contenu": r[0].contenu,
                "titre": r[1],
                "source_type": r[2],
                "source_url": r[3],
                "score": float(r[4]),
            }
            for r in rows
        ]

    async def recherche_bm25(
        self,
        query: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """
        Recherche full-text BM25 (via ts_rank PostgreSQL).
        Complète la recherche vectorielle pour la précision sur les termes exacts.
        """
        stmt = (
            select(
                DocumentChunk,
                KnowledgeDocument.titre,
                KnowledgeDocument.source_type,
                KnowledgeDocument.source_url,
                text("ts_rank(search_vector, plainto_tsquery('french', :q))").label("score"),
            )
            .join(KnowledgeDocument, KnowledgeDocument.id == DocumentChunk.document_id)
            .where(
                (DocumentChunk.tenant_id == self.tenant_id) | (DocumentChunk.tenant_id.is_(None)),
                DocumentChunk.search_vector.op("@@")(text("plainto_tsquery('french', :q)")),
            )
            .params(q=query)
            .order_by(text("score DESC"))
            .limit(limit)
        )

        rows = (await self.db.execute(stmt)).all()
        return [
            {
                "chunk_id": r[0].id,
                "document_id": r[0].document_id,
                "contenu": r[0].contenu,
                "titre": r[1],
                "source_type": r[2],
                "source_url": r[3],
                "score": float(r[4]),
            }
            for r in rows
        ]

    # ═════════════════════════════════════════════════════════════════════
    # CHUNKING
    # ═════════════════════════════════════════════════════════════════════
    @staticmethod
    def _chunker(texte: str, taille: int = 512, overlap: int = 64) -> list[str]:
        """
        Découpe un texte en chunks avec overlap.
        Approche : split par phrases, puis regroupement jusqu'à taille cible.
        """
        # Découpage par phrases (naïf mais efficace en FR)
        import re
        phrases = re.split(r"(?<=[.!?])\s+", texte)
        phrases = [p.strip() for p in phrases if len(p.strip()) >= 20]

        chunks: list[str] = []
        courant = ""
        for phrase in phrases:
            # Approximation : 1 token ≈ 4 caractères
            if len(courant) + len(phrase) > taille * 4 and courant:
                chunks.append(courant.strip())
                # Overlap : garder les derniers mots
                mots = courant.split()
                courant = " ".join(mots[-overlap:]) + " " + phrase
            else:
                courant = f"{courant} {phrase}".strip()

        if courant:
            chunks.append(courant.strip())

        return [c for c in chunks if len(c) >= 50]
