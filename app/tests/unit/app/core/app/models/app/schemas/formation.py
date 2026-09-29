"""DTO Formation & Support."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

CategorieArt = Literal[
    "demarrage", "comptabilite", "fiscalite", "social", "stocks",
    "immobilisations", "ventes", "achats", "tresorerie", "analytique",
    "consolidation", "fne", "audit", "projets", "ia", "mobile_money",
    "securite", "abonnement", "integrations", "avance",
]
TypeContenuT = Literal["article", "tutoriel", "video", "faq", "checklist", "webinar", "changelog", "cas_usage"]
NiveauDiff = Literal["debutant", "intermediaire", "avance", "expert"]
StatutPub = Literal["brouillon", "en_revision", "publie", "deprecie", "archive"]
TypeTicketT = Literal["question", "bug", "demande_fonctionnalite", "incident", "reclamation", "amelioration"]
PrioriteT = Literal["basse", "normale", "haute", "urgente", "critique"]
StatutTicketT = Literal["nouveau", "en_cours", "en_attente_client", "resolu", "ferme", "annule", "escalade"]
CanalSupportT = Literal["interne", "email", "whatsapp", "telephone", "chatbot", "api"]


# ─────────────────────────────────────────────────────────────────────────────
# CATÉGORIES
# ─────────────────────────────────────────────────────────────────────────────
class ArticleCategoryCreate(BaseModel):
    code: str = Field(min_length=2, max_length=30)
    libelle: str = Field(min_length=2, max_length=200)
    description: str | None = None
    icone: str | None = None
    couleur: str | None = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")
    ordre: int = 0
    parent_id: UUID | None = None


class ArticleCategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    code: str
    libelle: str
    description: str | None
    icone: str | None
    couleur: str | None
    ordre: int
    parent_id: UUID | None
    actif: bool


# ─────────────────────────────────────────────────────────────────────────────
# ARTICLES
# ─────────────────────────────────────────────────────────────────────────────
class ArticleCreate(BaseModel):
    category_id: UUID
    slug: str = Field(min_length=2, max_length=120, pattern=r"^[a-z0-9][a-z0-9-]*$")
    titre: str = Field(min_length=5, max_length=200)
    resume: str | None = Field(None, max_length=500)
    contenu: str = Field(min_length=20)
    type_contenu: TypeContenuT = "article"
    niveau_difficulte: NiveauDiff = "debutant"
    roles_cibles: list[str] = Field(default_factory=lambda: ["tous"])
    tags: list[str] = Field(default_factory=list)
    modules_lies: list[str] = Field(default_factory=list)
    video_url: str | None = None
    video_duree_s: int | None = Field(None, ge=0)
    image_url: str | None = None
    ordre: int = 0
    epingle: bool = False
    obligatoire_onboarding: bool = False
    version_application: str | None = None


class ArticleUpdate(BaseModel):
    category_id: UUID | None = None
    titre: str | None = Field(None, min_length=5, max_length=200)
    resume: str | None = None
    contenu: str | None = None
    type_contenu: TypeContenuT | None = None
    niveau_difficulte: NiveauDiff | None = None
    roles_cibles: list[str] | None = None
    tags: list[str] | None = None
    modules_lies: list[str] | None = None
    video_url: str | None = None
    ordre: int | None = None
    epingle: bool | None = None
    statut: StatutPub | None = None
    version_application: str | None = None


class ArticleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID | None
    category_id: UUID
    slug: str
    titre: str
    resume: str | None
    type_contenu: str
    niveau_difficulte: str
    roles_cibles: list[str]
    tags: list[str]
    modules_lies: list[str]
    video_url: str | None
    video_duree_s: int | None
    image_url: str | None
    statut: str
    publie_at: datetime | None
    ordre: int
    epingle: bool
    obligatoire_onboarding: bool
    version: int
    nb_vues: int
    nb_utile: int
    nb_non_utile: int
    created_at: datetime
    updated_at: datetime


class ArticleDetailOut(ArticleOut):
    contenu: str
    steps: list["TutorialStepOut"] = Field(default_factory=list)
    articles_lies: list["ArticleBriefOut"] = Field(default_factory=list)


class ArticleBriefOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    slug: str
    titre: str
    resume: str | None
    type_contenu: str


class ArticleSearchResult(BaseModel):
    """Résultat de recherche full-text."""
    article: ArticleBriefOut
    score: float
    extrait: str | None = None


class ArticleFeedbackIn(BaseModel):
    utile: bool
    commentaire: str | None = Field(None, max_length=2000)


# ─────────────────────────────────────────────────────────────────────────────
# ÉTAPES DE TUTORIEL
# ─────────────────────────────────────────────────────────────────────────────
class TutorialStepCreate(BaseModel):
    ordre: int = Field(1, ge=1)
    titre: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=5)
    page_cible: str | None = None
    selecteur_css: str | None = None
    data_tour_id: str | None = None
    position: Literal["top", "bottom", "left", "right", "center"] = "bottom"
    obligatoire: bool = False
    duree_estimee_s: int = Field(30, ge=5, le=600)
    action_requise: str | None = None
    validation_type: Literal["click", "fill", "select", "navigate", "manual"] | None = None
    validation_selector: str | None = None


class TutorialStepOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    article_id: UUID
    ordre: int
    titre: str
    description: str
    page_cible: str | None
    selecteur_css: str | None
    data_tour_id: str | None
    position: str
    obligatoire: bool
    duree_estimee_s: int
    validation_type: str | None


# ─────────────────────────────────────────────────────────────────────────────
# PROGRESSION
# ─────────────────────────────────────────────────────────────────────────────
class ArticleProgressIn(BaseModel):
    note_utilite: int | None = Field(None, ge=-1, le=1)
    feedback_texte: str | None = None
    etape_actuelle: int | None = Field(None, ge=0)
    etape_completee: int | None = Field(None, ge=1)
    termine: bool | None = None
    duree_passee_s: int | None = Field(None, ge=0)


class ArticleProgressOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    user_id: UUID
    article_id: UUID
    vu: bool
    vu_at: datetime | None
    nb_vues: int
    termine: bool
    termine_at: datetime | None
    note_utilite: int | None
    etape_actuelle: int
    etapes_completees: list[int]
    duree_passee_s: int


# ─────────────────────────────────────────────────────────────────────────────
# ONBOARDING
# ─────────────────────────────────────────────────────────────────────────────
class OnboardingPathCreate(BaseModel):
    code: str = Field(min_length=2, max_length=30)
    libelle: str = Field(min_length=2, max_length=200)
    description: str | None = None
    parcours_type: Literal[
        "nouveau_tenant", "nouvel_utilisateur", "nouveau_comptable",
        "migration_excel", "activation_fne", "config_mm",
    ]
    role_cible: Literal[
        "tous", "admin_tenant", "comptable", "lecteur", "auditeur",
        "fondateur", "comptable_externe",
    ] = "tous"
    ordre: int = 0
    etapes: list[dict[str, Any]] = Field(min_length=1)


class OnboardingPathOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    code: str
    libelle: str
    description: str | None
    parcours_type: str
    role_cible: str
    ordre: int
    actif: bool
    etapes: list[dict[str, Any]]


class OnboardingProgressOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    user_id: UUID
    path_id: UUID
    demarre_at: datetime
    termine_at: datetime | None
    pourcentage: float
    etapes_completees: list[dict[str, Any]]
    derniere_etape: str | None
    affiche_banniere: bool
    masque_definitivement: bool


class OnboardingStepCompleteIn(BaseModel):
    etape_key: str = Field(min_length=1, max_length=50)


# ─────────────────────────────────────────────────────────────────────────────
# CHATBOT
# ─────────────────────────────────────────────────────────────────────────────
class ChatbotAskIn(BaseModel):
    session_id: str = Field(min_length=5, max_length=50)
    question: str = Field(min_length=3, max_length=2000)
    page_courante: str | None = None
    contexte: dict[str, Any] | None = None


class ChatbotMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    conversation_id: UUID
    role: str
    contenu: str
    articles_sources: list[str]
    score_confiance: float | None
    feedback: int | None
    created_at: datetime


class ChatbotAskOut(BaseModel):
    conversation_id: UUID
    question: str
    reponse: str
    articles_sources: list[dict[str, Any]]
    score_confiance: float
    escalade_suggeree: bool
    suggestion_creation_ticket: bool
    latence_ms: int


class ChatbotFeedbackIn(BaseModel):
    message_id: UUID
    feedback: Literal[-1, 1]


# ─────────────────────────────────────────────────────────────────────────────
# TICKETS
# ─────────────────────────────────────────────────────────────────────────────
class TicketCreate(BaseModel):
    sujet: str = Field(min_length=5, max_length=200)
    description: str = Field(min_length=10, max_length=5000)
    type_ticket: TypeTicketT = "question"
    priorite: PrioriteT = "normale"
    canal: CanalSupportT = "interne"
    categorie: str | None = None
    module_concerne: str | None = None
    email_contact: str | None = None
    pieces_jointes: list[dict[str, Any]] = Field(default_factory=list)


class TicketUpdate(BaseModel):
    sujet: str | None = Field(None, min_length=5, max_length=200)
    description: str | None = None
    priorite: PrioriteT | None = None
    statut: StatutTicketT | None = None
    assigne_a_user_id: UUID | None = None
    categorie: str | None = None


class TicketOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    reference: str
    sujet: str
    description: str
    type_ticket: str
    priorite: str
    statut: str
    canal: str
    created_by_user_id: UUID | None
    assigne_a_user_id: UUID | None
    categorie: str | None
    module_concerne: str | None
    sla_cible_at: datetime | None
    sla_depasse: bool
    premier_reponse_at: datetime | None
    resolu_at: datetime | None
    satisfaction: int | None
    created_at: datetime
    updated_at: datetime


class TicketMessageCreate(BaseModel):
    contenu: str = Field(min_length=1, max_length=10000)
    interne: bool = False
    pieces_jointes: list[dict[str, Any]] = Field(default_factory=list)


class TicketMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    ticket_id: UUID
    auteur_user_id: UUID | None
    auteur_type: str
    contenu: str
    interne: bool
    pieces_jointes: list[dict[str, Any]]
    created_at: datetime


class TicketDetailOut(TicketOut):
    messages: list[TicketMessageOut] = Field(default_factory=list)


class TicketResolveIn(BaseModel):
    resolution: str = Field(min_length=10, max_length=5000)


class TicketSatisfactionIn(BaseModel):
    note: int = Field(ge=1, le=5)
    commentaire: str | None = Field(None, max_length=1000)


# ─────────────────────────────────────────────────────────────────────────────
# ANALYTICS
# ─────────────────────────────────────────────────────────────────────────────
class SupportAnalyticsOut(BaseModel):
    tenant_id: UUID
    periode_debut: datetime
    periode_fin: datetime
    nb_tickets_crees: int
    nb_tickets_resolus: int
    nb_tickets_ouverts: int
    temps_premier_reponse_moyen_min: float
    temps_resolution_moyen_h: float
    taux_resolution_pct: float
    satisfaction_moyenne: float
    nb_conversations_chatbot: int
    taux_resolution_chatbot_pct: float
    top_articles_consultes: list[dict[str, Any]]
    top_categories_tickets: list[dict[str, Any]]
    repartition_par_priorite: dict[str, int]


class ArticleStatsOut(BaseModel):
    article_id: UUID
    slug: str
    titre: str
    nb_vues: int
    nb_utile: int
    nb_non_utile: int
    taux_utilite_pct: float
    temps_lecture_moyen_s: float


class ChatbotQuestionTopOut(BaseModel):
    question_normalisee: str
    nb_occurrences: int
    article_recommande: str | None
    taux_resolution: float
