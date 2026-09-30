"""Configuration RAG — Recherche hybride BM25 + vectorielle."""
from __future__ import annotations

from pydantic_settings import BaseSettings


class RAGSettings(BaseSettings):
    # ─── Chunking ───────────────────────────────────────────
    CHUNK_SIZE_TOKENS: int = 512
    CHUNK_OVERLAP_TOKENS: int = 64
    MIN_CHUNK_CHARS: int = 50

    # ─── Retrieval ──────────────────────────────────────────
    TOP_K_VECTOR: int = 10
    TOP_K_BM25: int = 10
    TOP_K_FINAL: int = 5
    SIMILARITY_THRESHOLD: float = 0.65

    # ─── Hybrid scoring ─────────────────────────────────────
    VECTOR_WEIGHT: float = 0.6
    BM25_WEIGHT: float = 0.4

    # ─── Reranking (optionnel) ──────────────────────────────
    ENABLE_RERANKING: bool = False
    RERANKER_MODEL: str = "BAAI/bge-reranker-base"

    # ─── Mémoire conversation ───────────────────────────────
    MEMORY_MAX_TURNS: int = 10             # 10 derniers échanges
    MEMORY_SUMMARIZE_AFTER: int = 20       # Résumer après 20 échanges
    MEMORY_TOKEN_BUDGET: int = 2048

    model_config = {"env_file": ".env", "extra": "ignore"}


rag_settings = RAGSettings()
