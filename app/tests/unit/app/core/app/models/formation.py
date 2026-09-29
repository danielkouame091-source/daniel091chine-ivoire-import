"""Modèles Formation & Support — Base documentaire, Tutoriels, Chatbot, Tickets."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index,
    Integer, Numeric, String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


# ─────────────────────────────────────────────────────────────────────────────
# CATÉGORIE D'ARTICLE
# ─────────────────────────────────────────────────────────────────────────────
class ArticleCategory(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Catégorie d'articles de la base documentaire."""
    __tablename__ = "article_categories"

    code: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)
    libelle: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    icone: Mapped[str | None] = mapped_column(String(30), nullable=True)       # nom lucide-react
    couleur: Mapped[str | None] = mapped_column(String(7), nullable=True)      # #RRGGBB
    ordre: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    parent_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("article_categories.id"), nullable=True
    )
    actif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    __table_args__ = (
        Index("idx_article_cat_ordre", "ordre"),
    )

    def __repr__(self) -> str:
        return f"<ArticleCategory {self.code}>"


# ─────────────────────────────────────────────────────────────────────────────
# ARTICLE / TUTORIEL / FAQ
# ─────────────────────────────────────────────────────────────────────────────
class Article(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Article de la base documentaire (article, tutoriel, FAQ, vidéo, checklist).
    Recherche full-text via `search_vector` (tsvector PostgreSQL).
    """
    __tablename__ = "articles"

    tenant_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=True,           # NULL = article global (visible par tous les tenants)
        index=True,
    )
    category_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("article_categories.id"),
        nullable=False,
        index=True,
    )

    slug: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    titre: Mapped[str] = mapped_column(Text, nullable=False)
    resume: Mapped[str | None] = mapped_column(Text, nullable=True)
    contenu: Mapped[str] = mapped_column(Text, nullable=False)                 # Markdown

    type_contenu: Mapped[str] = mapped_column(
        String(20), nullable=False, default="article", server_default="article"
    )
    niveau_difficulte: Mapped[str] = mapped_column(
        String(20), nullable=False, default="debutant", server_default="debutant"
    )

    # Ciblage
    roles_cibles: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    tags: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    modules_lies: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )   # brique 12 → ia, brique 22 → fne, etc.

    # Média
    video_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    video_duree_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Publication
    statut: Mapped[str] = mapped_column(
        String(20), nullable=False, default="brouillon", server_default="brouillon"
    )
    publie_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deprecie_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    article_remplacant_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("articles.id"), nullable=True
    )

    # Ordre et mise en avant
    ordre: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    epingle: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    obligatoire_onboarding: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # Versioning
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    version_application: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Statistiques (dénormalisées pour performance)
    nb_vues: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    nb_utile: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    nb_non_utile: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    nb_partages: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    # Recherche full-text
    search_vector: Mapped[Any | None] = mapped_column(TSVECTOR, nullable=True)

    # Auteur
    auteur_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        Index("idx_article_tenant_statut", "tenant_id", "statut"),
        Index("idx_article_category", "category_id", "ordre"),
        Index("idx_article_slug", "slug"),
        Index("idx_article_search", "search_vector", postgresql_using="gin"),
    )

    def __repr__(self) -> str:
        return f"<Article {self.slug} — {self.titre[:50]}>"

    @property
    def taux_utilite(self) -> float:
        total = self.nb_utile + self.nb_non_utile
        if total == 0:
            return 0.0
        return self.nb_utile / total


# ─────────────────────────────────────────────────────────────────────────────
# ÉTAPE DE TUTORIEL
# ─────────────────────────────────────────────────────────────────────────────
class TutorialStep(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Étape d'un tutoriel interactif.
    Chaque étape cible un élément DOM précis (via `selecteur_css` ou `data-tour-id`).
    """
    __tablename__ = "tutorial_steps"

    article_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("articles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    ordre: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    titre: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    # Ciblage UI
    page_cible: Mapped[str | None] = mapped_column(String(100), nullable=True)  # ex: /ecritures/new
    selecteur_css: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_tour_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    position: Mapped[str] = mapped_column(
        String(20), nullable=False, default="bottom", server_default="bottom"
    )   # top | bottom | left | right | center

    # Contraintes
    obligatoire: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    duree_estimee_s: Mapped[int] = mapped_column(Integer, nullable=False, default=30, server_default="30")

    # Étape suivante conditionnelle (si l'utilisateur clique sur un bouton)
    action_requise: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Validation
    validation_type: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )   # click | fill | select | navigate | manual

    validation_selector: Mapped[str | None] = mapped_column(Text, nullable=True)

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        UniqueConstraint("article_id", "ordre", name="uq_tutorial_step_ordre"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# PROGRESSION UTILISATEUR (sur articles / tutoriels)
# ─────────────────────────────────────────────────────────────────────────────
class UserArticleProgress(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Suivi de progression d'un utilisateur sur un article/tutoriel."""
    __tablename__ = "user_article_progress"

    tenant_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    article_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("articles.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    vu: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    vu_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    nb_vues: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    termine: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    termine_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    note_utilite: Mapped[int | None] = mapped_column(Integer, nullable=True)   # 1 = utile, -1 = pas utile
    feedback_texte: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Progression tutoriel
    etape_actuelle: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    etapes_completees: Mapped[list[int]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )

    duree_passee_s: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        UniqueConstraint("user_id", "article_id", name="uq_user_article_progress"),
        Index("idx_uap_tenant_user", "tenant_id", "user_id"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# PARCOURS D'ONBOARDING
# ─────────────────────────────────────────────────────────────────────────────
class OnboardingPath(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Parcours d'onboarding (nouveau tenant, comptable, migration Excel...)."""
    __tablename__ = "onboarding_paths"

    code: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)
    libelle: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    parcours_type: Mapped[str] = mapped_column(String(30), nullable=False)
    role_cible: Mapped[str] = mapped_column(
        String(20), nullable=False, default="tous", server_default="tous"
    )

    ordre: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    actif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    # Étapes obligatoires (checklist)
    etapes: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    def __repr__(self) -> str:
        return f"<OnboardingPath {self.code}>"


class UserOnboardingProgress(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Progression d'un utilisateur sur un parcours d'onboarding."""
    __tablename__ = "user_onboarding_progress"

    tenant_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    path_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("onboarding_paths.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    demarre_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    termine_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pourcentage: Mapped[float] = mapped_column(
        Numeric(5, 2), nullable=False, default=0, server_default="0"
    )

    # Étapes complétées : [{"key": "create_tenant", "done": true, "done_at": "..."}]
    etapes_completees: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )

    derniere_etape: Mapped[str | None] = mapped_column(String(50), nullable=True)
    affiche_banniere: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    masque_definitivement: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        UniqueConstraint("user_id", "path_id", name="uq_user_onboarding_path"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# CONVERSATION CHATBOT
# ─────────────────────────────────────────────────────────────────────────────
class ChatbotConversation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Conversation avec le chatbot d'aide."""
    __tablename__ = "chatbot_conversations"

    tenant_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )
    user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    session_id: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    page_courante: Mapped[str | None] = mapped_column(String(100), nullable=True)

    nb_messages: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    resolu: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    resolu_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Si escaladé : lien vers le ticket
    escalade_ticket_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("support_tickets.id", ondelete="SET NULL"),
        nullable=True,
    )
    escalade_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Note de satisfaction
    satisfaction: Mapped[int | None] = mapped_column(Integer, nullable=True)   # 1-5
    satisfaction_commentaire: Mapped[str | None] = mapped_column(Text, nullable=True)

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    def __repr__(self) -> str:
        return f"<ChatbotConversation {self.session_id}>"


class ChatbotMessage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Message dans une conversation chatbot."""
    __tablename__ = "chatbot_messages"

    conversation_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("chatbot_conversations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    role: Mapped[str] = mapped_column(String(20), nullable=False)   # user | assistant | system
    contenu: Mapped[str] = mapped_column(Text, nullable=False)

    # Sources citées (articles liés)
    articles_sources: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    score_confiance: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)

    # Tokens & coût
    tokens_prompt: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_completion: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latence_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Feedback
    feedback: Mapped[int | None] = mapped_column(Integer, nullable=True)   # 1 = 👍, -1 = 👎

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    def __repr__(self) -> str:
        return f"<ChatbotMessage {self.role}: {self.contenu[:50]}>"


# ─────────────────────────────────────────────────────────────────────────────
# TICKET DE SUPPORT
# ─────────────────────────────────────────────────────────────────────────────
class SupportTicket(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Ticket de support client."""
    __tablename__ = "support_tickets"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    reference: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)
    sujet: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    type_ticket: Mapped[str] = mapped_column(
        String(30), nullable=False, default="question", server_default="question"
    )
    priorite: Mapped[str] = mapped_column(
        String(20), nullable=False, default="normale", server_default="normale"
    )
    statut: Mapped[str] = mapped_column(
        String(20), nullable=False, default="nouveau", server_default="nouveau"
    )
    canal: Mapped[str] = mapped_column(
        String(20), nullable=False, default="interne", server_default="interne"
    )

    # Auteur
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    email_contact: Mapped[str | None] = mapped_column(String(150), nullable=True)

    # Assignation
    assigne_a_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    # Catégorisation
    categorie: Mapped[str | None] = mapped_column(String(30), nullable=True)
    module_concerne: Mapped[str | None] = mapped_column(String(30), nullable=True)

    # Résolution
    resolu_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolu_par_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    # SLA
    sla_cible_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sla_depasse: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    premier_reponse_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Satisfaction
    satisfaction: Mapped[int | None] = mapped_column(Integer, nullable=True)   # 1-5
    satisfaction_commentaire: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Métadonnées
    pieces_jointes: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        Index("idx_ticket_tenant_statut", "tenant_id", "statut"),
        Index("idx_ticket_tenant_priorite", "tenant_id", "priorite"),
        Index("idx_ticket_assigne", "assigne_a_user_id", "statut"),
    )

    def __repr__(self) -> str:
        return f"<SupportTicket {self.reference} ({self.statut})>"


class TicketMessage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Message dans un ticket de support."""
    __tablename__ = "ticket_messages"

    ticket_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("support_tickets.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    auteur_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    auteur_type: Mapped[str] = mapped_column(
        String(20), nullable=False
    )   # client | support | system | chatbot
    contenu: Mapped[str] = mapped_column(Text, nullable=False)

    interne: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )   # Note interne non visible du client

    pieces_jointes: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    def __repr__(self) -> str:
        return f"<TicketMessage {self.auteur_type}: {self.contenu[:50]}>"
