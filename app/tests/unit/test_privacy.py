"""
Tests du module Conformité RGPD / Protection des données.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core.privacy_syscohada import (
    DELAI_REPONSE_DROIT_JOURS,
    StatutDemandeDroit,
    StatutIncident,
    TypeDroit,
)
from app.schemas.privacy import (
    ConsentCreate,
    CookieConsentIn,
    DPOCreate,
    DataBreachCreate,
    DataProcessorCreate,
    DataSubjectRequestCreate,
    ImpactAssessmentCreate,
    LegalDocumentCreate,
    ProcessingRecordCreate,
)
from app.services.privacy_service import PrivacyService

pytestmark = pytest.mark.integration


# ═════════════════════════════════════════════════════════════════════════════
# TESTS REGISTRE DES TRAITEMENTS
# ═════════════════════════════════════════════════════════════════════════════
class TestProcessingRecords:
    async def test_creation_traitement(self, db_session, tenant, admin_user):
        svc = PrivacyService(db_session, tenant.id, admin_user.id)
        rec = await svc.creer_traitement(ProcessingRecordCreate(
            code="GEST-CLIENTS",
            nom="Gestion des clients",
            description="Traitement des données clients pour facturation et relances",
            finalite="gestion_clients",
            base_legale="contrat",
            categories_personnes=["clients"],
            categories_donnees=["identite", "contact", "financier"],
            mesures_securite=["chiffrement_repos", "rls_multi_tenant", "audit_trail"],
            duree_conservation_mois=120,
        ))
        assert rec.code == "GEST-CLIENTS"
        assert rec.base_legale == "contrat"

    async def test_donnees_sensibles_imposent_aipd(
        self, db_session, tenant, admin_user
    ):
        svc = PrivacyService(db_session, tenant.id, admin_user.id)
        rec = await svc.creer_traitement(ProcessingRecordCreate(
            code="SANTE",
            nom="Traitement données de santé",
            description="Gestion des certificats médicaux des employés",
            finalite="gestion_sociale",
            base_legale="obligation_legale",
            categories_donnees=["sensible_sante"],
            contient_donnees_sensibles=True,
            aipd_requise=False,   # Sera forcé à True
            mesures_securite=["chiffrement_repos"],
        ))
        assert rec.aipd_requise is True   # Forcé automatiquement

    async def test_code_duplique_rejete(self, db_session, tenant, admin_user):
        from fastapi import HTTPException
        svc = PrivacyService(db_session, tenant.id, admin_user.id)
        await svc.creer_traitement(ProcessingRecordCreate(
            code="DUP", nom="Test 1", description="Description 1",
            finalite="gestion_clients", base_legale="contrat",
        ))
        with pytest.raises(HTTPException) as exc:
            await svc.creer_traitement(ProcessingRecordCreate(
                code="DUP", nom="Test 2", description="Description 2",
                finalite="gestion_clients", base_legale="contrat",
            ))
        assert exc.value.status_code == 409


# ═════════════════════════════════════════════════════════════════════════════
# TESTS DEMANDES DE DROIT
# ═════════════════════════════════════════════════════════════════════════════
class TestDataSubjectRequests:
    async def test_creation_demande_acces(self, db_session, tenant, admin_user):
        svc = PrivacyService(db_session, tenant.id, admin_user.id)
        dsr = await svc.creer_demande_droit(DataSubjectRequestCreate(
            email="client@test.ci",
            nom_complet="Koné Moussa",
            type_droit="acces",
            description_demande="Je souhaite obtenir une copie de mes données personnelles",
        ))
        assert dsr.reference.startswith("DSR-")
        assert dsr.statut == "recue"
        assert dsr.date_limite == date.today() + timedelta(days=DELAI_REPONSE_DROIT_JOURS)

    async def test_workflow_complet_demande(
        self, db_session, tenant, admin_user
    ):
        svc = PrivacyService(db_session, tenant.id, admin_user.id)
        dsr = await svc.creer_demande_droit(DataSubjectRequestCreate(
            email="client@test.ci",
            nom_complet="Client Test",
            type_droit="effacement",
            description_demande="Je souhaite exercer mon droit à l'oubli",
        ))

        # Vérifier identité
        dsr = await svc.verifier_identite(dsr.id, "piece_identite", "CNI fournie")
        assert dsr.identite_verifiee is True
        assert dsr.statut == "en_cours"

        # Répondre
        dsr = await svc.repondre_demande(
            dsr.id,
            "Vos données ont été effacées conformément à votre demande.",
            "acceptee",
        )
        assert dsr.statut == "acceptee"
        assert dsr.traite_at is not None

    async def test_prolongation_delai(self, db_session, tenant, admin_user):
        svc = PrivacyService(db_session, tenant.id, admin_user.id)
        dsr = await svc.creer_demande_droit(DataSubjectRequestCreate(
            email="client@test.ci", nom_complet="Client",
            type_droit="portabilite", description_demande="Export de toutes mes données",
        ))
        dsr = await svc.prolonger_delai(dsr.id, "Demande complexe nécessitant une analyse")
        assert dsr.prolongation is True
        assert dsr.nouvelle_date_limite == dsr.date_limite + timedelta(days=30)

    async def test_double_prolongation_rejetee(self, db_session, tenant, admin_user):
        from fastapi import HTTPException
        svc = PrivacyService(db_session, tenant.id, admin_user.id)
        dsr = await svc.creer_demande_droit(DataSubjectRequestCreate(
            email="client@test.ci", nom_complet="Client",
            type_droit="acces", description_demande="Accès données",
        ))
        await svc.prolonger_delai(dsr.id, "Motif 1")
        with pytest.raises(HTTPException) as exc:
            await svc.prolonger_delai(dsr.id, "Motif 2")
        assert exc.value.status_code == 400


# ═════════════════════════════════════════════════════════════════════════════
# TESTS VIOLATIONS
# ═════════════════════════════════════════════════════════════════════════════
class TestDataBreach:
    async def test_declarer_violation_critique(self, db_session, tenant, admin_user):
        svc = PrivacyService(db_session, tenant.id, admin_user.id)
        breach = await svc.declarer_violation(DataBreachCreate(
            titre="Fuite de données clients",
            description="Accès non autorisé détecté sur la base clients",
            type_incident="acces_non_autorise",
            gravite="critique",
            categories_donnees_affectees=["identite", "contact", "financier"],
            nb_personnes_affectees=1500,
            detecte_at=datetime.now(timezone.utc),
        ))
        assert breach.reference.startswith("BREACH-")
        assert breach.notification_autorite_requise is True
        assert breach.notification_personnes_requise is True

    async def test_notification_autorite_artci(self, db_session, tenant, admin_user):
        svc = PrivacyService(db_session, tenant.id, admin_user.id)
        breach = await svc.declarer_violation(DataBreachCreate(
            titre="Test notification",
            description="Test",
            type_incident="divulgation",
            gravite="eleve",
            detecte_at=datetime.now(timezone.utc),
        ))
        breach = await svc.notifier_autorite(
            breach.id, "artci", "Notification officielle à ARTCI", "ARTCI-2025-001",
        )
        assert breach.autorite_notifiee == "artci"
        assert breach.reference_autorite == "ARTCI-2025-001"
        assert breach.statut == "notifie_autorite"


# ═════════════════════════════════════════════════════════════════════════════
# TESTS DPO
# ═════════════════════════════════════════════════════════════════════════════
class TestDPO:
    async def test_creation_dpo(self, db_session, tenant, admin_user):
        svc = PrivacyService(db_session, tenant.id, admin_user.id)
        dpo = await svc.creer_dpo({
            "type_dpo": "externe",
            "nom_complet": "Cabinet DPO-CI",
            "email": "dpo@cabinet.ci",
            "telephone": "+2250700000000",
            "organisation": "Cabinet DPO Côte d'Ivoire",
            "date_debut": date.today(),
        })
        assert dpo.nom_complet == "Cabinet DPO-CI"
        assert dpo.actif is True

    async def test_nouveau_dpo_desactive_ancien(
        self, db_session, tenant, admin_user
    ):
        svc = PrivacyService(db_session, tenant.id, admin_user.id)
        await svc.creer_dpo({
            "type_dpo": "interne", "nom_complet": "DPO 1",
            "email": "dpo1@test.ci", "date_debut": date.today(),
        })
        await svc.creer_dpo({
            "type_dpo": "interne", "nom_complet": "DPO 2",
            "email": "dpo2@test.ci", "date_debut": date.today(),
        })

        dpo_actif = await svc.get_dpo_actif()
        assert dpo_actif.nom_complet == "DPO 2"


# ═════════════════════════════════════════════════════════════════════════════
# TESTS DOCUMENTS LÉGAUX
# ═════════════════════════════════════════════════════════════════════════════
class TestLegalDocuments:
    async def test_creation_document_legal(self, db_session, tenant, admin_user):
        svc = PrivacyService(db_session, tenant.id, admin_user.id)
        doc = await svc.creer_document_legal(LegalDocumentCreate(
            type_document="politique_confidentialite",
            version="1.0",
            titre="Politique de confidentialité",
            contenu="# Politique de confidentialité\n\n" + "Contenu long. " * 20,
            date_effet=date.today(),
        ))
        assert doc.version == "1.0"
        assert doc.est_version_actuelle is True

    async def test_nouvelle_version_desactive_ancienne(
        self, db_session, tenant, admin_user
    ):
        svc = PrivacyService(db_session, tenant.id, admin_user.id)
        v1 = await svc.creer_document_legal(LegalDocumentCreate(
            type_document="politique_confidentialite",
            version="1.0", titre="Politique v1",
            contenu="Contenu v1 " * 30, date_effet=date.today(),
        ))
        v2 = await svc.creer_document_legal(LegalDocumentCreate(
            type_document="politique_confidentialite",
            version="2.0", titre="Politique v2",
            contenu="Contenu v2 " * 30, date_effet=date.today(),
        ))
        await db_session.refresh(v1)

        assert v1.est_version_actuelle is False
        assert v2.est_version_actuelle is True

        actif = await svc.get_document_legal_actif("politique_confidentialite")
        assert actif.version == "2.0"


# ═════════════════════════════════════════════════════════════════════════════
# TESTS COOKIES
# ═════════════════════════════════════════════════════════════════════════════
class TestCookies:
    async def test_consentement_cookies(self, db_session, tenant, admin_user):
        svc = PrivacyService(db_session, tenant.id, admin_user.id)
        consent = await svc.enregistrer_consentement_cookies("session-abc-123", {
            "essentiels": True,
            "fonctionnels": True,
            "analytiques": False,
            "marketing": False,
            "reseaux_sociaux": False,
            "version_politique": "1.0",
        })
        assert consent.session_id == "session-abc-123"
        assert consent.essentiels is True
        assert consent.marketing is False


# ═════════════════════════════════════════════════════════════════════════════
# TESTS SCORE CONFORMITÉ
# ═════════════════════════════════════════════════════════════════════════════
class TestComplianceScore:
    async def test_score_initial_faible(self, db_session, tenant, admin_user):
        svc = PrivacyService(db_session, tenant.id, admin_user.id)
        score = await svc.score_conformite_detaille()
        # Tenant vide → score faible
        assert score["score_global_pct"] < 50
        assert len(score["recommandations"]) > 0
        # Recommandation DPO obligatoire
        assert any("DPO" in r for r in score["recommandations"])

    async def test_score_ameliore_avec_traitements(
        self, db_session, tenant, admin_user
    ):
        svc = PrivacyService(db_session, tenant.id, admin_user.id)
        # Créer 5 traitements
        for i in range(5):
            await svc.creer_traitement(ProcessingRecordCreate(
                code=f"PROC-{i:03d}",
                nom=f"Traitement {i}",
                description=f"Description du traitement {i}",
                finalite="gestion_clients",
                base_legale="contrat",
                mesures_securite=["chiffrement_repos", "rls_multi_tenant", "audit_trail"],
            ))

        score = await svc.score_conformite_detaille()
        assert score["registre_traitements_pct"] >= 50
