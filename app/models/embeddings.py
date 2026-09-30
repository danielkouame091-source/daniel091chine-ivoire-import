"""Modèles pour la base vectorielle (pgvector)."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.llm_config import llm_settings
from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class KnowledgeDocument(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Document source indexé (article, PDF, FAQ, code...)."""
    __tablename__ = "knowledge_documents"

    tenant_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=True,   # NULL = base de connaissance globale MTech
        index=True,
    )

    # Source
    source_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # article_doc | pdf_document | faq | code_source | fiche_produit | regle_metier
    source_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    titre: Mapped[str] = mapped_column(Text, nullable=False)
    categorie: Mapped[str | None] = mapped_column(String(50), nullable=True)
    tags: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")

    # Contenu complet
    contenu: Mapped[str] = mapped_column(Text, nullable=False)
    langue: Mapped[str] = mapped_column(String(5), nullable=False, default="fr", server_default="fr")

    # Versioning
    version: Mapped[str] = mapped_column(String(20), nullable=False, default="1.0", server_default="1.0")

    # Statut
    statut: Mapped[str] = mapped_column(
        String(20), nullable=False, default="publie", server_default="publie"
    )

    # Recherche full-text
    search_vector: Mapped[Any | None] = mapped_column(TSVECTOR, nullable=True)

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        Index("idx_kdoc_tenant_type", "tenant_id", "source_type"),
        Index("idx_kdoc_search", "search_vector", postgresql_using="gin"),
    )


class DocumentChunk(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Chunk d'un document + embedding vectoriel.
    Le vecteur est stocké dans pgvector avec index HNSW pour la recherche rapide.
    """
    __tablename__ = "knowledge_chunks"

    document_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    tenant_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )

    ordre: Mapped[int] = mapped_column(Integer, nullable=False)
    contenu: Mapped[str] = mapped_column(Text, nullable=False)
    nb_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    # Vecteur d'embedding (dimension = 768 pour nomic-embed-text)
    embedding: Mapped[list[float]] = mapped_column(
        Vector(llm_settings.EMBEDDING_DIMENSION), nullable=False
    )

    # Recherche full-text BM25
    search_vector: Mapped[Any | None] = mapped_column(TSVECTOR, nullable=True)

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        UniqueConstraint("document_id", "ordre", name="uq_chunk_doc_ordre"),
        Index("idx_chunk_document", "document_id", "ordre"),
        # Index HNSW pour recherche vectorielle rapide
        Index(
            "idx_chunk_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
            postgresql_with={"m": 16, "ef_construction": 64},
        ),
        Index("idx_chunk_search", "search_vector", postgresql_using="gin"),
    )
