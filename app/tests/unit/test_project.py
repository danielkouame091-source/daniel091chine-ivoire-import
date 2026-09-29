"""
Tests du module Projets & Chantiers.

Couvre :
- Création projet
- Phases, tâches, jalons
- Imputation de coûts (avec écritures)
- Situation de travaux (décompte)
- Avancement à facturer (méthode SYSCOHADA)
- Calcul de marge
- Portefeuille
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.core.project_syscohada import (
    NiveauAlerteProjet,
    StatutSituation,
)
from app.schemas.project import (
    ProgressBillingCreate,
    ProgressBillingLineCreate,
    ProjectCostCreate,
    ProjectCreate,
    ProjectMilestoneCreate,
    ProjectPhaseCreate,
    ProjectTaskCreate,
    ProjectTaskUpdate,
)
from app.services.project_service import ProjectService

pytestmark = pytest.mark.integration


# ─── Fixtures locales ───────────────────────────────────────────────────────
@pytest.fixture
async def project(db_session, tenant, admin_user):
    svc = ProjectService(db_session, tenant.id, admin_user.id)
    return await svc.creer_projet(ProjectCreate(
        code="PROJ-001",
        libelle="Construction immeuble R+3",
        type_projet="chantier_btp",
        date_debut_prevue=date(2025, 1, 1),
        date_fin_prevue=date(2025, 12, 31),
        montant_marche_ht=100_000_000,
        taux_tva=0.18,
        budget_previsionnel_ht=70_000_000,
        retenue_garantie_taux=0.05,
        avance_demarrage_pct=10.0,
        compte_projet="231000",
    ))


# ═════════════════════════════════════════════════════════════════════════════
# TESTS CRÉATION
# ═════════════════════════════════════════════════════════════════════════════
class TestCreation:
    async def test_creation_projet(self, project):
        assert project.code == "PROJ-001"
        assert project.statut == "brouillon"
        assert project.montant_marche_ht == 100_000_000
        assert project.montant_marche_ttc == 118_000_000
        assert project.avance_demarrage_montant == 10_000_000   # 10% de 100M

    async def test_code_duplique_rejete(self, db_session, tenant, admin_user):
        from fastapi import HTTPException
        svc = ProjectService(db_session, tenant.id, admin_user.id)
        await svc.creer_projet(ProjectCreate(
            code="DUP", libelle="Test", type_projet="autre",
            date_debut_prevue=date(2025, 1, 1),
            date_fin_prevue=date(2025, 12, 31),
            compte_projet="231000",
        ))
        with pytest.raises(HTTPException) as exc:
            await svc.creer_projet(ProjectCreate(
                code="DUP", libelle="Test 2", type_projet="autre",
                date_debut_prevue=date(2025, 1, 1),
                date_fin_prevue=date(2025, 12, 31),
                compte_projet="231000",
            ))
        assert exc.value.status_code == 409

    async def test_lancer_projet(self, db_session, tenant, admin_user, project):
        svc = ProjectService(db_session, tenant.id, admin_user.id)
        p = await svc.lancer_projet(project.id)
        assert p.statut == "en_cours"
        assert p.date_debut_reelle is not None


# ═════════════════════════════════════════════════════════════════════════════
# TESTS PHASES & TÂCHES
# ═════════════════════════════════════════════════════════════════════════════
class TestPhasesEtTaches:
    async def test_creation_phase(self, db_session, tenant, admin_user, project):
        svc = ProjectService(db_session, tenant.id, admin_user.id)
        ph = await svc.creer_phase(project.id, ProjectPhaseCreate(
            code="PH-01",
            libelle="Fondations",
            type_phase="execution",
            date_debut_prevue=date(2025, 1, 1),
            date_fin_prevue=date(2025, 3, 31),
            budget_ht=20_000_000,
            poids=30.0,
        ))
        assert ph.code == "PH-01"
        assert float(ph.budget_ht) == 20_000_000

    async def test_creation_tache(self, db_session, tenant, admin_user, project):
        svc = ProjectService(db_session, tenant.id, admin_user.id)
        t = await svc.creer_tache(project.id, ProjectTaskCreate(
            code="T-001",
            libelle="Coulage dalle",
            date_debut_prevue=date(2025, 2, 1),
            date_fin_prevue=date(2025, 2, 15),
            budget_ht=5_000_000,
        ))
        assert t.statut == "a_faire"
        assert float(t.budget_ht) == 5_000_000

    async def test_task_terminer_recalcule_avancement(
        self, db_session, tenant, admin_user, project
    ):
        svc = ProjectService(db_session, tenant.id, admin_user.id)
        t = await svc.creer_tache(project.id, ProjectTaskCreate(
            code="T-002", libelle="Test",
            date_debut_prevue=date(2025, 2, 1),
            date_fin_prevue=date(2025, 2, 15),
            budget_ht=1_000_000,
        ))
        await db_session.flush()

        t2 = await svc.modifier_tache(t.id, ProjectTaskUpdate(statut="terminee"))
        assert t2.statut == "terminee"
        assert t2.pourcentage_avancement == 100
        assert t2.date_fin_reelle is not None


# ═════════════════════════════════════════════════════════════════════════════
# TESTS COÛTS
# ═════════════════════════════════════════════════════════════════════════════
class TestCouts:
    async def test_imputer_cout(
        self, db_session, tenant, admin_user, project, plan_comptable_ci
    ):
        svc = ProjectService(db_session, tenant.id, admin_user.id)
        c = await svc.imputer_cout(project.id, ProjectCostCreate(
            date_cout=date(2025, 2, 15),
            libelle="Achat ciment",
            type_cout="achat",
            montant_ht=5_000_000,
            montant_tva=900_000,
            compte_comptable="601000",
        ))
        assert c.montant_ht == 5_000_000
        assert c.ecriture_id is not None

        # Budget réalisé mis à jour
        await db_session.refresh(project)
        assert project.budget_realise == 5_000_000

    async def test_alerte_depassement(
        self, db_session, tenant, admin_user, project, plan_comptable_ci
    ):
        svc = ProjectService(db_session, tenant.id, admin_user.id)
        # Imputer 75M sur un budget de 70M → critique
        await svc.imputer_cout(project.id, ProjectCostCreate(
            date_cout=date(2025, 6, 1),
            libelle="Dépassement",
            type_cout="achat",
            montant_ht=75_000_000,
            montant_tva=13_500_000,
            compte_comptable="601000",
        ))
        await db_session.refresh(project)
        assert project.niveau_alerte == NiveauAlerteProjet.CRITIQUE


# ═════════════════════════════════════════════════════════════════════════════
# TESTS SITUATIONS DE TRAVAUX
# ═════════════════════════════════════════════════════════════════════════════
class TestSituations:
    async def test_creation_situation(
        self, db_session, tenant, admin_user, project, plan_comptable_ci
    ):
        svc = ProjectService(db_session, tenant.id, admin_user.id)
        await svc.lancer_projet(project.id)

        b = await svc.creer_situation(ProgressBillingCreate(
            project_id=project.id,
            date_situation=date(2025, 3, 31),
            libelle="Situation n°1 — Mars 2025",
            pourcentage_avancement_cumule=25.0,
            taux_tva=0.18,
            lignes=[
                ProgressBillingLineCreate(
                    designation="Fondations",
                    unite="ENS",
                    quantite_marche=1,
                    quantite_cumulee_precedente=0,
                    quantite_cumulee_actuelle=1,
                    prix_unitaire_ht=25_000_000,
                    compte_produit="705000",
                ),
            ],
        ))
        assert b.numero_situation == 1
        assert b.montant_situation_ht == 25_000_000
        assert b.montant_tva == 4_500_000
        # Retenue 5% = 1 250 000
        assert b.retenue_garantie_montant == 1_250_000
        # Avance remboursée = 10M × 25% = 2 500 000
        assert b.avance_remboursee_situation == 2_500_000
        # Net = 25M + 4.5M - 1.25M - 2.5M = 25 750 000
        assert b.montant_net_a_payer == 25_750_000
        assert b.ecriture_id is not None

    async def test_situation_2_cumule_precedente(
        self, db_session, tenant, admin_user, project, plan_comptable_ci
    ):
        svc = ProjectService(db_session, tenant.id, admin_user.id)
        await svc.lancer_projet(project.id)

        # Situation 1 : 25M
        await svc.creer_situation(ProgressBillingCreate(
            project_id=project.id,
            date_situation=date(2025, 3, 31),
            libelle="Sit 1",
            pourcentage_avancement_cumule=25.0,
            lignes=[ProgressBillingLineCreate(
                designation="Fondations",
                quantite_marche=1, quantite_cumulee_precedente=0,
                quantite_cumulee_actuelle=1, prix_unitaire_ht=25_000_000,
                compte_produit="705000",
           
