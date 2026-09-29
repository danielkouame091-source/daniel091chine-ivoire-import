"""
Tests du module Notifications & Communications.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.notification_syscohada import Canal, Criticite
from app.schemas.notification import (
    CampaignCreate,
    PreferenceUpsert,
    SendNotificationIn,
    SuppressionCreate,
    TemplateCreate,
    TemplatePreviewIn,
)
from app.services.campaign_service import CampaignService
from app.services.notification_service import NotificationService

pytestmark = pytest.mark.integration


# ═════════════════════════════════════════════════════════════════════════════
# TESTS TEMPLATES
# ═════════════════════════════════════════════════════════════════════════════
class TestTemplates:
    async def test_seed_templates(self, db_session, tenant, admin_user):
        svc = NotificationService(db_session, tenant.id, admin_user.id)
        nb = await svc.seed_templates_defaut()
        assert nb >= 8
        # Idempotent
        nb2 = await svc.seed_templates_defaut()
        assert nb2 == 0

    async def test_creation_template_email(
        self, db_session, tenant, admin_user
    ):
        svc = NotificationService(db_session, tenant.id, admin_user.id)
        tpl = await svc.creer_template(TemplateCreate(
            code="WELCOME_TEST",
            libelle="Bienvenue",
            canal="email",
            type_template="transactionnel",
            sujet="Bienvenue {{ prenom }}",
            contenu_html="<h1>Bonjour {{ prenom }}</h1>",
        ))
        assert tpl.code == "WELCOME_TEST"
        assert tpl.version == 1
        assert tpl.statut == "brouillon"

    async def test_rendu_template(
        self, db_session, tenant, admin_user
    ):
        svc = NotificationService(db_session, tenant.id, admin_user.id)
        tpl = await svc.creer_template(TemplateCreate(
            code="TEST_RENDER",
            libelle="Test rendu",
            canal="email",
            sujet="Facture {{ numero }}",
            contenu_html="<p>Montant : {{ montant }} FCFA</p>",
        ))
        await svc.publier_template(tpl.id)
        await db_session.flush()

        preview = await svc.previsualiser_template(tpl.id, TemplatePreviewIn(
            variables={"numero": "FAC-001", "montant": 500000},
        ))
        assert "FAC-001" in preview.sujet
        assert "500000" in preview.contenu_html

    async def test_preview_variables_manquantes(
        self, db_session, tenant, admin_user
    ):
        svc = NotificationService(db_session, tenant.id, admin_user.id)
        tpl = await svc.creer_template(TemplateCreate(
            code="TEST_MISSING",
            libelle="Test manquant",
            canal="email",
            sujet="Bonjour {{ prenom }}",
            contenu_html="<p>{{ contenu_manquant }}</p>",
        ))
        preview = await svc.previsualiser_template(tpl.id, TemplatePreviewIn(
            variables={},
        ))
        assert "prenom" in preview.variables_manquantes
        assert "contenu_manquant" in preview.variables_manquantes


# ═════════════════════════════════════════════════════════════════════════════
# TESTS ENVOI
# ═════════════════════════════════════════════════════════════════════════════
class TestEnvoi:
    async def test_envoi_email_inline(self, db_session, tenant, admin_user):
        svc = NotificationService(db_session, tenant.id, admin_user.id)
        notif = await svc.envoyer(SendNotificationIn(
            destinataire_email="client@test.ci",
            canal="email",
            type_notification="welcome",
            sujet="Bienvenue",
            contenu_html="<p>Bienvenue !</p>",
            contexte={},
        ))
        assert notif.statut == "queued"
        assert notif.canal == "email"
        assert notif.destinataire_email == "client@test.ci"

    async def test_envoi_avec_template(self, db_session, tenant, admin_user):
        svc = NotificationService(db_session, tenant.id, admin_user.id)
        await svc.seed_templates_defaut()
        await db_session.flush()

        notif = await svc.envoyer(SendNotificationIn(
            destinataire_email="client@test.ci",
            canal="email",
            type_notification="welcome",
            template_code="WELCOME_USER",
            contexte={"prenom": "Kouassi", "tenant_nom": "MTech"},
        ))
        assert notif.statut == "queued"
        assert "Kouassi" in (notif.contenu_html or "")

    async def test_envoi_suppression_skip(self, db_session, tenant, admin_user):
        svc = NotificationService(db_session, tenant.id, admin_user.id)
        # Ajouter à la liste de suppression
        await svc.ajouter_suppression(SuppressionCreate(
            email="blocked@test.ci",
            motif="unsubscribe",
        ))
        await db_session.flush()

        notif = await svc.envoyer(SendNotificationIn(
            destinataire_email="blocked@test.ci",
            canal="email",
            type_notification="newsletter",
            sujet="Promo",
            contenu_html="<p>Promo</p>",
        ))
        assert notif.statut == "suppressed"

    async def test_envoi_critique_ignore_suppression(
        self, db_session, tenant, admin_user
    ):
        """Les notifications critiques passent malgré l'opt-out."""
        svc = NotificationService(db_session, tenant.id, admin_user.id)
        await svc.ajouter_suppression(SuppressionCreate(
            email="blocked@test.ci",
            motif="unsubscribe",
        ))
        await db_session.flush()

        notif = await svc.envoyer(SendNotificationIn(
            destinataire_email="blocked@test.ci",
            canal="email",
            type_notification="password_reset",   # Critique
            criticite="critique",
            sujet="Reset",
            contenu_html="<p>Reset</p>",
        ))
        assert notif.statut == "queued"

    async def test_envoi_preference_bloque(
        self, db_session, tenant, admin_user
    ):
        """Préférence utilisateur désactive un canal."""
        from fastapi import HTTPException

        svc = NotificationService(db_session, tenant.id, admin_user.id)
        await svc.upsert_preference(admin_user.id, PreferenceUpsert(
            type_notification="newsletter",
            canaux_actives=["email"],   # SMS désactivé
        ))
        await db_session.flush()

        with pytest.raises(HTTPException) as exc:
            await svc.envoyer(SendNotificationIn(
                user_id=admin_user.id,
                destinataire_telephone="+2250700000000",
                canal="sms",
                type_notification="newsletter",
                contenu_texte="Test",
            ))
        assert exc.value.status_code == 403

    async def test_rate_limit_meme_type(
        self, db_session, tenant, admin_user
    ):
        from fastapi import HTTPException
        svc = NotificationService(db_session, tenant.id, admin_user.id)

        # 5 envois → OK
        for i in range(5):
            await svc.envoyer(SendNotificationIn(
                user_id=admin_user.id,
                destinataire_email=f"x{i}@test.ci",
                canal="email",
                type_notification="bulk_test",
                sujet="Test",
                contenu_html="<p>Test</p>",
            ))
        await db_session.flush()

        # 6e → 429
        with pytest.raises(HTTPException) as exc:
            await svc.envoyer(SendNotificationIn(
                user_id=admin_user.id,
                destinataire_email="x6@test.ci",
                canal="email",
                type_notification="bulk_test",
                sujet="Test 6",
                contenu_html="<p>Test</p>",
            ))
        assert exc.value.status_code == 429


# ═════════════════════════════════════════════════════════════════════════════
# TESTS PRÉFÉRENCES
# ═════════════════════════════════════════════════════════════════════════════
class TestPreferences:
    async def test_upsert_preference(self, db_session, tenant, admin_user):
        svc = NotificationService(db_session, tenant.id, admin_user.id)
        pref = await svc.upsert_preference(admin_user.id, PreferenceUpsert(
            type_notification="marketing",
            canaux_actives=["email", "in_app"],
            canal_prefere="email",
            quiet_hours_debut=22,
            quiet_hours_fin=7,
            max_par_jour=3,
        ))
        assert pref.canal_prefere == "email"
        assert pref.quiet_hours_debut == 22

    async def test_lister_preferences(self, db_session, tenant, admin_user):
        svc = NotificationService(db_session, tenant.id, admin_user.id)
        await svc.upsert_preference(admin_user.id, PreferenceUpsert(
            type_notification="marketing", canaux_actives=["email"],
        ))
        await svc.upsert_preference(admin_user.id, PreferenceUpsert(
            type_notification="transactionnel", canaux_actives=["email", "sms"],
        ))
        prefs = await svc.lister_preferences(admin_user.id)
        assert len(prefs) == 2


# ═════════════════════════════════════════════════════════════════════════════
# TESTS IN-APP
# ═════════════════════════════════════════════════════════════════════════════
class TestInApp:
    async def test_creation_et_lecture_in_app(
        self, db_session, tenant, admin_user
    ):
        svc = NotificationService(db_session, tenant.id, admin_user.id)
        notif = await svc.envoyer(SendNotificationIn(
            user_id=admin_user.id,
            canal="in_app",
            type_notification="ecriture_validated",
            sujet="Écriture validée",
            contenu_markdown="Votre écriture a été validée.",
            contexte={},
        ))
        assert notif.canal == "in_app"

        # Compter non lus
        count = await svc.compter_non_lus(admin_user.id)
        assert count >= 1

        # Marquer lu
        marked = await svc.marquer_lu(admin_user.id, [notif.id])
        assert marked == 1

        count_after = await svc.compter_non_lus(admin_user.id)
        assert count_after == count - 1


# ═════════════════════════════════════════════════════════════════════════════
# TESTS CAMPAGNES
# ═════════════════════════════════════════════════════════════════════════════
class TestCampaigns:
    async def test_creation_campagne(self, db_session, tenant, admin_user):
        notif_svc = NotificationService(db_session, tenant.id, admin_user.id)
        tpl = await notif_svc.creer_template(TemplateCreate(
            code="CAMP_TEST",
            libelle="Template campagne",
            canal="email",
            type_template="marketing",
            sujet="Bonjour {{ prenom }}",
            contenu_html="<p>Newsletter</p>",
        ))
        await notif_svc.publier_template(tpl.id)
        await db_session.flush()

        svc = CampaignService(db_session, tenant.id, admin_user.id)
        camp = await svc.creer_campagne(CampaignCreate(
            code="CAMP-TEST-001",
            nom="Newsletter Décembre 2025",
            template_id=tpl.id,
            canal="email",
            segments={"roles": ["ADMIN_TENANT"]},
        ))
        assert camp.code == "CAMP-TEST-001"
        assert camp.statut == "brouillon"
        assert camp.nb_cibles >= 1

    async def test_lancer_campagne(self, db_session, tenant, admin_user):
        notif_svc = NotificationService(db_session, tenant.id, admin_user.id)
        tpl = await notif_svc.creer_template(TemplateCreate(
            code="CAMP_LAUNCH",
            libelle="Test lancement",
            canal="email",
            type_template="marketing",
            sujet="Test {{ prenom }}",
            contenu_html="<p>Test</p>",
        ))
        await notif_svc.publier_template(tpl.id)
        await db_session.flush()

        svc = CampaignService(db_session, tenant.id, admin_user.id)
        camp = await svc.creer_campagne(CampaignCreate(
            code="CAMP-LAUNCH-001",
            nom="Test lancement",
            template_id=tpl.id,
            canal="email",
            segments={"roles": ["ADMIN_TENANT"]},
        ))
        await db_session.flush()

        result = await svc.lancer_campagne(camp.id)
        assert result["nb_queued"] >= 1

        stats = await svc.stats_campagne(camp.id)
        assert stats["nb_envoyes"] >= 1


# ═════════════════════════════════════════════════════════════════════════════
# TESTS ANALYTICS
# ═════════════════════════════════════════════════════════════════════════════
class TestAnalytics:
    async def test_analytics_vide(self, db_session, tenant, admin_user):
        svc = NotificationService(db_session, tenant.id, admin_user.id)
        now = datetime.now(timezone.utc)
        data = await svc.analytics(
            debut=now - timedelta(days=30),
            fin=now + timedelta(hours=1),
        )
        assert data["nb_envoyes"] >= 0
        assert data["taux_delivrabilite_pct"] >= 0

    async def test_analytics_avec_envois(self, db_session, tenant, admin_user):
        svc = NotificationService(db_session, tenant.id, admin_user.id)
        for i in range(3):
            await svc.envoyer(SendNotificationIn(
                destinataire_email=f"a{i}@test.ci",
                canal="email",
                type_notification=f"test_{i}",
                sujet="Test",
                contenu_html="<p>Test</p>",
            ))
        await db_session.flush()

        now = datetime.now(timezone.utc)
        data = await svc.analytics(
            debut=now - timedelta(hours=1),
            fin=now + timedelta(hours=1),
        )
        assert data["nb_envoyes"] >= 3
        assert "email" in data["repartition_par_canal"]
