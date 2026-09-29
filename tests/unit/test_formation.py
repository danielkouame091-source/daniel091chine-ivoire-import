"""
Tests du module Formation & Support.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.schemas.formation import (
    ArticleCreate,
    ArticleFeedbackIn,
    ArticleProgressIn,
    ArticleUpdate,
    ChatbotAskIn,
    OnboardingPathCreate,
    OnboardingStepCompleteIn,
    TicketCreate,
    TicketMessageCreate,
    TicketResolveIn,
)
from app.services.formation_service import FormationService
from app.services.support_chatbot_service import ChatbotService
from app.services.support_ticket_service import SupportTicketService

pytestmark = pytest.mark.integration


# ─── Fixtures ───────────────────────────────────────────────────────────────
@pytest.fixture
async def category(db_session, tenant, admin_user):
    svc = FormationService(db_session, tenant.id, admin_user.id)
    await svc.seed_categories_defaut()
    from app.models.formation import ArticleCategory
    cat = await db_session.scalar(
        select(ArticleCategory).where(ArticleCategory.code == "demarrage")
    )
    return cat


@pytest.fixture
async def article(db_session, tenant, admin_user, category):
    svc = FormationService(db_session, tenant.id, admin_user.id)
    a = await svc.creer_article(ArticleCreate(
        category_id=category.id,
        slug="test-article",
        titre="Comment créer une écriture",
        contenu="# Guide complet\n\nPour créer une écriture, allez dans Écritures > Nouvelle...",
        resume="Guide pas-à-pas",
        type_contenu="tutoriel",
        tags=["écriture", "syscohada", "démarrage"],
    ))
    await svc.publier_article(a.id)
    await db_session.flush()
    return a


# ═════════════════════════════════════════════════════════════════════════════
# TESTS CATÉGORIES & ARTICLES
# ═════════════════════════════════════════════════════════════════════════════
class TestArticles:
    async def test_seed_categories(self, db_session, tenant, admin_user):
        svc = FormationService(db_session, tenant.id, admin_user.id)
        nb = await svc.seed_categories_defaut()
        assert nb >= 20
        # Idempotent
        nb2 = await svc.seed_categories_defaut()
        assert nb2 == 0

    async def test_creation_article(self, db_session, tenant, admin_user, category):
        svc = FormationService(db_session, tenant.id, admin_user.id)
        a = await svc.creer_article(ArticleCreate(
            category_id=category.id,
            slug="mon-article",
            titre="Mon premier article",
            contenu="Contenu de l'article de test",
        ))
        assert a.slug == "mon-article"
        assert a.statut == "brouillon"
        assert a.version == 1

    async def test_slug_duplique_rejete(self, db_session, tenant, admin_user, article, category):
        from fastapi import HTTPException
        svc = FormationService(db_session, tenant.id, admin_user.id)
        with pytest.raises(HTTPException) as exc:
            await svc.creer_article(ArticleCreate(
                category_id=category.id,
                slug=article.slug,
                titre="Duplicate",
                contenu="Test",
            ))
        assert exc.value.status_code == 409

    async def test_recherche_full_text(self, db_session, tenant, admin_user, article):
        svc = FormationService(db_session, tenant.id, admin_user.id)
        results = await svc.rechercher("créer écriture")
        assert len(results) > 0
        assert any("écriture" in r.article["titre"].lower() for r in results)

    async def test_article_vue_incremente(self, db_session, tenant, admin_user, article):
        svc = FormationService(db_session, tenant.id, admin_user.id)
        initial = article.nb_vues
        await svc.get_article_detail(article.slug)
        await db_session.refresh(article)
        assert article.nb_vues == initial + 1

    async def test_feedback_article(self, db_session, tenant, admin_user, article):
        svc = FormationService(db_session, tenant.id, admin_user.id)
        await svc.donner_feedback(article.id, ArticleFeedbackIn(utile=True))
        await db_session.refresh(article)
        assert article.nb_utile == 1
        assert article.taux_utilite == 1.0


# ═════════════════════════════════════════════════════════════════════════════
# TESTS ONBOARDING
# ═════════════════════════════════════════════════════════════════════════════
class TestOnboarding:
    async def test_seed_parcours(self, db_session, tenant, admin_user):
        svc = FormationService(db_session, tenant.id, admin_user.id)
        nb = await svc.seed_parcours_onboarding()
        assert nb >= 3

    async def test_demarrer_et_completer_parcours(
        self, db_session, tenant, admin_user
    ):
        svc = FormationService(db_session, tenant.id, admin_user.id)
        await svc.seed_parcours_onboarding()
        await db_session.flush()

        from app.models.formation import OnboardingPath
        path = await db_session.scalar(
            select(OnboardingPath).where(OnboardingPath.code == "ONB-NEW-TENANT")
        )

        progress = await svc.demarrer_parcours(path.id)
        assert progress.pourcentage == 0
        assert progress.termine_at is None

        # Compléter 1ère étape
        progress = await svc.completer_etape_onboarding(path.id, "profil_complet")
        assert progress.pourcentage > 0
        assert len(progress.etapes_completees) == 1

        # Compléter toutes les étapes
        for etape in path.etapes:
            progress = await svc.completer_etape_onboarding(path.id, etape["key"])

        assert progress.pourcentage == 100.0
        assert progress.termine_at is not None

    async def test_etape_inconnue_rejetee(self, db_session, tenant, admin_user):
        from fastapi import HTTPException
        svc = FormationService(db_session, tenant.id, admin_user.id)
        await svc.seed_parcours_onboarding()
        await db_session.flush()

        from app.models.formation import OnboardingPath
        path = await db_session.scalar(
            select(OnboardingPath).where(OnboardingPath.code == "ONB-NEW-TENANT")
        )

        with pytest.raises(HTTPException) as exc:
            await svc.completer_etape_onboarding(path.id, "etape_inexistante")
        assert exc.value.status_code == 400


# ═════════════════════════════════════════════════════════════════════════════
# TESTS CHATBOT (avec mock OpenAI)
# ═════════════════════════════════════════════════════════════════════════════
class TestChatbot:
    async def test_chatbot_repond_avec_contexte(
        self, db_session, tenant, admin_user, article
    ):
        """Mock OpenAI pour tester le pipeline RAG."""
        mock_response = {
            "content": {
                "reponse": "Pour créer une écriture, allez dans le menu Écritures puis cliquez sur Nouvelle.",
                "confiance": 0.92,
                "articles_cites": ["test-article"],
                "suggestion_ticket": False,
                "raisonnement": "L'article explique directement la procédure.",
            },
            "tokens_prompt": 500,
            "tokens_completion": 100,
            "latence_ms": 1200,
            "model": "gpt-4o-mini",
        }

        with patch("app.services.support_chatbot_service.get_openai_client") as mock_factory:
            mock_client = AsyncMock()
            mock_client.chat_json = AsyncMock(return_value=mock_response)
            mock_factory.return_value = mock_client

            svc = ChatbotService(db_session, tenant.id, admin_user.id)
            result = await svc.poser_question(ChatbotAskIn(
                session_id="test-session-001",
                question="Comment créer une écriture ?",
                page_courante="/ecritures/new",
            ))

        assert "écriture" in result.reponse.lower()
        assert result.score_confiance == 0.92
        assert len(result.articles_sources) == 1
        assert result.articles_sources[0]["slug"] == "test-article"

    async def test_chatbot_sans_article_pertinent(
        self, db_session, tenant, admin_user
    ):
        """Question hors-sujet → escalade suggérée."""
        mock_response = {
            "content": {
                "reponse": "Je n'ai pas cette information. Voulez-vous créer un ticket ?",
                "confiance": 0.2,
                "articles_cites": [],
                "suggestion_ticket": True,
            },
            "tokens_prompt": 100,
            "tokens_completion": 50,
            "latence_ms": 800,
            "model": "gpt-4o-mini",
        }

        with patch("app.services.support_chatbot_service.get_openai_client") as mock_factory:
            mock_client = AsyncMock()
            mock_client.chat_json = AsyncMock(return_value=mock_response)
            mock_factory.return_value = mock_client

            svc = ChatbotService(db_session, tenant.id, admin_user.id)
            result = await svc.poser_question(ChatbotAskIn(
                session_id="test-session-002",
                question="Quelle est la météo à Abidjan ?",
            ))

        assert result.suggestion_creation_ticket is True
        assert result.escalade_suggeree is True
        assert result.score_confiance < 0.7


# ═════════════════════════════════════════════════════════════════════════════
# TESTS TICKETS
# ═════════════════════════════════════════════════════════════════════════════
class TestTickets:
    async def test_creer_ticket(self, db_session, tenant, admin_user):
        svc = SupportTicketService(db_session, tenant.id, admin_user.id)
        t = await svc.creer_ticket(TicketCreate(
            sujet="Impossible de certifier une facture",
            description="Je reçois une erreur 500 quand je tente de certifier.",
            type_ticket="bug",
            priorite="haute",
        ))
        assert t.reference.startswith("TKT-")
        assert t.statut == "nouveau"
        assert t.priorite == "haute"
        assert t.sla_cible_at is not None

    async def test_cycle_de_vie_ticket(self, db_session, tenant, admin_user):
        svc = SupportTicketService(db_session, tenant.id, admin_user.id)

        # 1. Créer
        t = await svc.creer_ticket(TicketCreate(
            sujet="Test cycle",
            description="Description du test",
        ))

        # 2. Assigner
        t = await svc.assigner_ticket(t.id, admin_user.id)
        assert t.statut == "en_cours"
        assert t.assigne_a_user_id == admin_user.id

        # 3. Répondre
        msg = await svc.ajouter_message(t.id, TicketMessageCreate(
            contenu="Nous investiguons votre problème.",
        ), auteur_type="support")
        await db_session.refresh(t)
        assert t.premier_reponse_at is not None

        # 4. Résoudre
        t = await svc.resoudre_ticket(t.id, TicketResolveIn(
            resolution="Le bug a été corrigé dans la version 1.2.3."
        ))
        assert t.statut == "resolu"
        assert t.resolu_at is not None

        # 5. Fermer
        t = await svc.fermer_ticket(t.id)
        assert t.statut == "ferme"

    async def test_noter_satisfaction(self, db_session, tenant, admin_user):
        svc = SupportTicketService(db_session, tenant.id, admin_user.id)
        t = await svc.creer_ticket(TicketCreate(
            sujet="Test satisfaction",
            description="Test",
        ))
        from app.schemas.formation import TicketSatisfactionIn
        t = await svc.noter_satisfaction(t.id, TicketSatisfactionIn(
            note=5, commentaire="Résolution rapide, merci !"
        ))
        assert t.satisfaction == 5
        assert t.satisfaction_commentaire == "Résolution rapide, merci !"

    async def test_verifier_sla(self, db_session, tenant, admin_user):
        """Crée un ticket avec SLA dépassé manuellement."""
        svc = SupportTicketService(db_session, tenant.id, admin_user.id)
        t = await svc.creer_ticket(TicketCreate(
            sujet="SLA test",
            description="Test",
        ))
        # Forcer le SLA dans le passé
        t.sla_cible_at = datetime.now(timezone.utc) - timedelta(hours=1)
        await db_session.flush()

        result = await svc.verifier_sla()
        assert result["sla_depasses_marques"] == 1

        await db_session.refresh(t)
        assert t.sla_depasse is True

    async def test_analytics(self, db_session, tenant, admin_user):
        svc = SupportTicketService(db_session, tenant.id, admin_user.id)
        await svc.creer_ticket(TicketCreate(
            sujet="Question analytique",
            description="Test analytics",
            categorie="comptabilite",
        ))
        await db_session.flush()

        now = datetime.now(timezone.utc)
        stats = await svc.analytics(
            debut=now - timedelta(days=30),
            fin=now + timedelta(hours=1),
        )
        assert stats.nb_tickets_crees >= 1
        assert "normale" in stats.repartition_par_priorite
