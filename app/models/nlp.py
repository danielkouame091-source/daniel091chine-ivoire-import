"""Modèles IA/NLP : suggestions, feedback loop, embeddings de phrases."""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    pass


class NlpSuggestion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Suggestion d'écriture générée par l'IA — en attente de validation humaine."""
    __tablename__ = "nlp_suggestions"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
    )

    # Entrée
    phrase_source: Mapped[str] = mapped_column(Text, nullable=False)
    langue: Mapped[str] = mapped_column(String(10), nullable=False, default="fr", server_default="fr")
    source_canal: Mapped[str] = mapped_column(
        String(20), nullable=False, default="web", server_default="web"
    )  # web | whatsapp | api | import

    # Sortie IA
    ecriture_proposee: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    confiance: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0")
    modele_utilise: Mapped[str | None] = mapped_column(String(50), nullable=True)
    tokens_prompt: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_completion: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latence_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Statut du cycle de vie
    statut: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="en_attente",
        server_default="en_attente",
    )  # en_attente | acceptee | rejetee | corrigee | expiree

    # Résultat après acceptation
    ecriture_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("ecritures.id"),
        nullable=True,
    )
    ecriture_corrigee: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    acceptee_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejetee_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    motif_rejet: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("idx_nlp_tenant_statut", "tenant_id", "statut"),
        Index("idx_nlp_tenant_date", "tenant_id", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<NlpSuggestion {self.id} confiance={self.confiance:.2f} statut={self.statut}>"


class NlpFeedback(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Feedback loop — capture la différence entre la suggestion IA et la
    correction humaine, pour améliorer les prompts / fine-tuning futur.
    """
    __tablename__ = "nlp_feedbacks"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    suggestion_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("nlp_suggestions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    phrase_source: Mapped[str] = mapped_column(Text, nullable=False)
    proposition_ia: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    correction_humaine: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    difference_edit_distance: Mapped[int | None] = mapped_column(Integer, nullable=True)
    accepte_sans_modification: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    score_qualite: Mapped[float | None] = mapped_column(Float, nullable=True)   # 0.0 – 1.0
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("suggestion_id", name="uq_nlp_feedback_suggestion"),
    )

    def __repr__(self) -> str:
        return f"<NlpFeedback suggestion={self.suggestion_id} accepte={self.accepte_sans_modification}>"


class NlpPattern(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Cache d'apprentissage : phrases fréquentes → écriture validée.
    Utilisé en pré-filtre AVANT l'appel OpenAI (économie + rapidité).
    """
    __tablename__ = "nlp_patterns"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    phrase_normalisee: Mapped[str] = mapped_column(Text, nullable=False)
    hash_phrase: Mapped[str] = mapped_column(String(64), nullable=False)
    ecriture_validee: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    occurrences: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    confiance_moyenne: Mapped[float] = mapped_column(
        Float, nullable=False, default=1.0, server_default="1.0"
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "hash_phrase", name="uq_nlp_pattern_hash"),
        Index("idx_nlp_pattern_tenant", "tenant_id"),
    )

    def __repr__(self) -> str:
        return f"<NlpPattern {self.hash_phrase[:8]} occ={self.occurrences}>"
