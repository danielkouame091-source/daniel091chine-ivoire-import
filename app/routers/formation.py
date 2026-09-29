"""Endpoints Formation & Support."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.dependencies.auth import CurrentUser, RequireAdminTenant, RequireComptable
from app.dependencies.subscription import RequireActiveSubscription
from app.dependencies.tenant import CurrentTenant
from app.dependencies.tenant_db import TenantDBSession
from app.models.formation import (
    Article,
    ArticleCategory,
    ChatbotConversation,
    ChatbotMessage,
    OnboardingPath,
    SupportTicket,
    TutorialStep,
    UserOnboardingProgress,
)
from app.schemas.formation import (
    ArticleCategoryCreate,
    ArticleCategoryOut,
    ArticleCreate,
    ArticleDetailOut,
    ArticleFeedbackIn,
    ArticleOut,
    ArticleProgressIn,
    ArticleProgressOut,
    ArticleSearchResult,
    ArticleStatsOut,
    ArticleUpdate,
    ChatbotAskIn,
    ChatbotAskOut,
    ChatbotFeedbackIn,
    ChatbotMessageOut,
    OnboardingPathCreate,
    OnboardingPathOut,
    OnboardingProgressOut,
    OnboardingStepCompleteIn,
    SupportAnalyticsOut,
    TicketCreate,
    TicketDetailOut,
    TicketMessageCreate,
    TicketMessageOut,
    TicketOut,
    TicketResolveIn,
    TicketSatisfactionIn,
    TicketUpdate,
    TutorialStepCreate,
    TutorialStepOut,
)
from app.services.formation_service import FormationService
from app.services.support_chatbot_service import ChatbotService
from app.services.support_ticket_service import SupportTicketService

router = APIRouter()


# ═════════════════════════════════════════════════════════════════════════════
# CATÉGORIES
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/categories", response_model=list[ArticleCategoryOut])
async def list_categories(
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
) -> list[ArticleCategoryOut]:
    svc = FormationService(db, current_tenant.id, current_user.id)
    cats = await svc.lister_categories()
    return [ArticleCategoryOut.model_validate(c) for c in cats]


@router.post("/categories", response_model=ArticleCategoryOut, status_code=201)
async def create_category(
    data: ArticleCategoryCreate,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    db: TenantDBSession,
) -> ArticleCategoryOut:
    svc = FormationService(db, current_tenant.id, current_user.id)
    cat = await svc.creer_categorie(data)
    return ArticleCategoryOut.model_validate(cat)


# ═════════════════════════════════════════════════════════════════════════════
# ARTICLES
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/articles", response_model=list[ArticleOut])
async def list_articles(
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
    categorie: str | None = Query(None),
    epingle_only: bool = Query(False),
    limit: int = Query(100, ge=1, le=500),
) -> list[ArticleOut]:
    svc = FormationService(db, current_tenant.id, current_user.id)
    role = current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role)
    articles = await svc.lister_articles(categorie=categorie, role=role, epingle_only=epingle_only, limit=limit)
    return [ArticleOut.model_validate(a) for a in articles]


@router.get("/articles/search", response_model=list[ArticleSearchResult])
async def search_articles(
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
    q: str = Query(..., min_length=2),
    categorie: str | None = Query(None),
    limit: int = Query(20, ge=1, le=50),
) -> list[ArticleSearchResult]:
    svc = FormationService(db, current_tenant.id, current_user.id)
    return await svc.rechercher(q, categorie, limit)


@router.get("/articles/{slug}", response_model=ArticleDetailOut)
async def get_article(
    slug: str,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
) -> ArticleDetailOut:
    svc = FormationService(db, current_tenant.id, current_user.id)
    article = await svc.get_article_detail(slug)
    steps = await svc.lister_etapes(article.id)
    out = ArticleDetailOut.model_validate(article)
    out.steps = [TutorialStepOut.model_validate(s) for s in steps]
    return out


@router.post("/articles", response_model=ArticleOut, status_code=201)
async def create_article(
    data: ArticleCreate,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    db: TenantDBSession,
) -> ArticleOut:
    svc = FormationService(db, current_tenant.id, current_user.id)
    a = await svc.creer_article(data)
    return ArticleOut.model_validate(a)


@router.patch("/articles/{article_id}", response_model=ArticleOut)
async def update_article(
    article_id: UUID,
    data: ArticleUpdate,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    db: TenantDBSession,
) -> ArticleOut:
    svc = FormationService(db, current_tenant.id, current_user.id)
    a = await svc.modifier_article(article_id, data)
    return ArticleOut.model_validate(a)


@router.post("/articles/{article_id}/publier", response_model=ArticleOut)
async def publish_article(
    article_id: UUID,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    db: TenantDBSession,
) -> ArticleOut:
    svc = FormationService(db, current_tenant.id, current_user.id)
    a = await svc.publier_article(article_id)
    return ArticleOut.model_validate(a)


@router.post("/articles/{article_id}/feedback", response_model=dict)
async def feedback_article(
    article_id: UUID,
    data: ArticleFeedbackIn,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
) -> dict:
    svc = FormationService(db, current_tenant.id, current_user.id)
    article = await svc.donner_feedback(article_id, data)
    return {
        "article_id": str(article.id),
        "nb_utile": article.nb_utile,
        "nb_non_utile": article.nb_non_utile,
        "taux_utilite": article.taux_utilite,
    }


@router.post("/articles/{article_id}/progress", response_model=ArticleProgressOut)
async def update_progress(
    article_id: UUID,
    data: ArticleProgressIn,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
) -> ArticleProgressOut:
    svc = FormationService(db, current_tenant.id, current_user.id)
    progress = await svc.mettre_a_jour_progression(article_id, data)
    return ArticleProgressOut.model_validate(progress)


# ═════════════════════════════════════════════════════════════════════════════
# ÉTAPES TUTORIEL
# ═════════════════════════════════════════════════════════════════════════════
@router.post("/articles/{article_id}/steps", response_model=TutorialStepOut, status_code=201)
async def create_step(
    article_id: UUID,
    data: TutorialStepCreate,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    db: TenantDBSession,
) -> TutorialStepOut:
    svc = FormationService(db, current_tenant.id, current_user.id)
    s = await svc.creer_etape(article_id, data)
    return TutorialStepOut.model_validate(s)


# ═════════════════════════════════════════════════════════════════════════════
# ONBOARDING
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/onboarding/paths", response_model=list[OnboardingPathOut])
async def list_onboarding_paths(
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
    type_parcours: str | None = Query(None),
) -> list[OnboardingPathOut]:
    svc = FormationService(db, current_tenant.id, current_user.id)
    role = current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role)
    paths = await svc.lister_parcours(role=role, type_parcours=type_parcours)
    return [OnboardingPathOut.model_validate(p) for p in paths]


@router.post("/onboarding/paths", response_model=OnboardingPathOut, status_code=201)
async def create_onboarding_path(
    data: OnboardingPathCreate,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    db: TenantDBSession,
) -> OnboardingPathOut:
    svc = FormationService(db, current_tenant.id, current_user.id)
    p = await svc.creer_parcours(data)
    return OnboardingPathOut.model_validate(p)


@router.post("/onboarding/paths/{path_id}/demarrer", response_model=OnboardingProgressOut)
async def start_onboarding(
    path_id: UUID,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
) -> OnboardingProgressOut:
    svc = FormationService(db, current_tenant.id, current_user.id)
    progress = await svc.demarrer_parcours(path_id)
    return OnboardingProgressOut.model_validate(progress)


@router.post("/onboarding/paths/{path_id}/etape", response_model=OnboardingProgressOut)
async def complete_step(
    path_id: UUID,
    data: OnboardingStepCompleteIn,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
) -> OnboardingProgressOut:
    svc = FormationService(db, current_tenant.id, current_user.id)
    progress = await svc.completer_etape_onboarding(path_id, data.etape_key)
    return OnboardingProgressOut.model_validate(progress)


@router.get("/onboarding/progressions", response_model=list[OnboardingProgressOut])
async def list_onboarding_progress(
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
) -> list[OnboardingProgressOut]:
    svc = FormationService(db, current_tenant.id, current_user.id)
    rows = await svc.lister_progressions_onboarding()
    return [OnboardingProgressOut.model_validate(p) for p in rows]


# ═════════════════════════════════════════════════════════════════════════════
# CHATBOT
# ═════════════════════════════════════════════════════════════════════════════
@router.post("/chatbot/ask", response_model=ChatbotAskOut)
async def chatbot_ask(
    data: ChatbotAskIn,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
) -> ChatbotAskOut:
    svc = ChatbotService(db, current_tenant.id, current_user.id)
    return await svc.poser_question(data)


@router.get("/chatbot/historique/{session_id}", response_model=list[ChatbotMessageOut])
async def chatbot_history(
    session_id: str,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
) -> list[ChatbotMessageOut]:
    svc = ChatbotService(db, current_tenant.id, current_user.id)
    msgs = await svc.get_historique(session_id)
    return [ChatbotMessageOut.model_validate(m) for m in msgs]


@router.post("/chatbot/feedback")
async def chatbot_feedback(
    data: ChatbotFeedbackIn,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
) -> dict:
    svc = ChatbotService(db, current_tenant.id, current_user.id)
    msg = await svc.feedback_message(data)
    return {"message_id": str(msg.id), "feedback": msg.feedback}


@router.post("/chatbot/satisfaction/{session_id}")
async def chatbot_satisfaction(
    session_id: str,
    satisfaction: int = Query(..., ge=1, le=5),
    commentaire: str | None = Query(None),
    current_tenant: CurrentTenant = None,
    current_user: CurrentUser = None,
    db: TenantDBSession = None,
) -> dict:
    svc = ChatbotService(db, current_tenant.id, current_user.id)
    conv = await svc.marquer_satisfaction(session_id, satisfaction, commentaire)
    return {"session_id": conv.session_id, "satisfaction": conv.satisfaction}


# ═════════════════════════════════════════════════════════════════════════════
# TICKETS
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/tickets", response_model=list[TicketOut])
async def list_tickets(
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
    statut: str | None = Query(None),
    priorite: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[TicketOut]:
    svc = SupportTicketService(db, current_tenant.id, current_user.id)
    tickets = await svc.lister_tickets(statut=statut, priorite=priorite, limit=limit, offset=offset)
    return [TicketOut.model_validate(t) for t in tickets]


@router.post("/tickets", response_model=TicketOut, status_code=201)
async def create_ticket(
    data: TicketCreate,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
) -> TicketOut:
    svc = SupportTicketService(db, current_tenant.id, current_user.id)
    t = await svc.creer_ticket(data)
    return TicketOut.model_validate(t)


@router.get("/tickets/{ticket_id}", response_model=TicketDetailOut)
async def get_ticket(
    ticket_id: UUID,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
) -> TicketDetailOut:
    svc = SupportTicketService(db, current_tenant.id, current_user.id)
    ticket = await svc.get_ticket_detail(ticket_id)
    messages = await svc.lister_messages(ticket_id)
    out = TicketDetailOut.model_validate(ticket)
    out.messages = [TicketMessageOut.model_validate(m) for m in messages]
    return out


@router.patch("/tickets/{ticket_id}", response_model=TicketOut)
async def update_ticket(
    ticket_id: UUID,
    data: TicketUpdate,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    db: TenantDBSession,
) -> TicketOut:
    svc = SupportTicketService(db, current_tenant.id, current_user.id)
    t = await svc.modifier_ticket(ticket_id, data)
    return TicketOut.model_validate(t)


@router.post("/tickets/{ticket_id}/messages", response_model=TicketMessageOut, status_code=201)
async def add_message(
    ticket_id: UUID,
    data: TicketMessageCreate,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
) -> TicketMessageOut:
    svc = SupportTicketService(db, current_tenant.id, current_user.id)
    # Déterminer auteur_type selon le rôle
    role = current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role)
    auteur = "support" if role in ("SUPER_ADMIN", "ADMIN_TENANT") else "client"
    m = await svc.ajouter_message(ticket_id, data, auteur_type=auteur)
    return TicketMessageOut.model_validate(m)


@router.post("/tickets/{ticket_id}/assigner")
async def assign_ticket(
    ticket_id: UUID,
    user_id: UUID,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    db: TenantDBSession,
) -> dict:
    svc = SupportTicketService(db, current_tenant.id, current_user.id)
    t = await svc.assigner_ticket(ticket_id, user_id)
    return {"ticket_id": str(t.id), "assigne_a": str(t.assigne_a_user_id)}


@router.post("/tickets/{ticket_id}/resoudre", response_model=TicketOut)
async def resolve_ticket(
    ticket_id: UUID,
    data: TicketResolveIn,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    db: TenantDBSession,
) -> TicketOut:
    svc = SupportTicketService(db, current_tenant.id, current_user.id)
    t = await svc.resoudre_ticket(ticket_id, data)
    return TicketOut.model_validate(t)


@router.post("/tickets/{ticket_id}/fermer", response_model=TicketOut)
async def close_ticket(
    ticket_id: UUID,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    db: TenantDBSession,
) -> TicketOut:
    svc = SupportTicketService(db, current_tenant.id, current_user.id)
    t = await svc.fermer_ticket(ticket_id)
    return TicketOut.model_validate(t)


@router.post("/tickets/{ticket_id}/satisfaction", response_model=TicketOut)
async def ticket_satisfaction(
    ticket_id: UUID,
    data: TicketSatisfactionIn,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
) -> TicketOut:
    svc = SupportTicketService(db, current_tenant.id, current_user.id)
    t = await svc.noter_satisfaction(ticket_id, data)
    return TicketOut.model_validate(t)


# ═════════════════════════════════════════════════════════════════════════════
# ANALYTICS
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/analytics/support", response_model=SupportAnalyticsOut)
async def support_analytics(
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    db: TenantDBSession,
    jours: int = Query(30, ge=1, le=365),
) -> SupportAnalyticsOut:
    svc = SupportTicketService(db, current_tenant.id, current_user.id)
    fin = datetime.now(timezone.utc)
    debut = fin - timedelta(days=jours)
    return await svc.analytics(debut, fin)


# ═════════════════════════════════════════════════════════════════════════════
# SEED
# ═════════════════════════════════════════════════════════════════════════════
@router.post("/seed")
async def seed_formation(
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    db: TenantDBSession,
) -> dict:
    """Initialise catégories, articles de démarrage et parcours d'onboarding."""
    svc = FormationService(db, current_tenant.id, current_user.id)
    cat_created = await svc.seed_categories_defaut()
    art_created = await svc.seed_articles_demarrage()
    path_created = await svc.seed_parcours_onboarding()
    return {
        "categories_created": cat_created,
        "articles_created": art_created,
        "paths_created": path_created,
    }
