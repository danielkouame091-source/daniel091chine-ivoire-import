"""
Tests Analytique & Budget.

Couvre :
- Création axes + sections
- Clés de répartition (somme = 100%)
- Imputation analytique (directe, répartie)
- Budget : création, validation, activation
- Contrôle budgétaire (OK, vigilance, alerte, dépassement)
- Résultat analytique réconcilié CG
"""
from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select

from app.core.analytical_syscohada import (
    NiveauAlerteBudget,
    TypeAxeAnalytique,
    niveau_alerte_pour,
)
from app.schemas.analytical import (
    AllocationKeyCreate,
    AllocationKeyLineCreate,
    AnalyticalAxisCreate,
    AnalyticalSectionCreate,
    BudgetCreate,
    BudgetLineCreate,
    ImputationBatchRequest,
    ImputationCreate,
)
from app.services.analytical_service import AnalyticalService

pytestmark = pytest.mark.integration


class TestAlerteBudget:
    def test_seuils_ok(self):
        assert niveau_alerte_pour(0.5) == NiveauAlerteBudget.OK
        assert niveau_alerte_pour(0.79) == NiveauAlerteBudget.OK

    def test_seuils_vigilance(self):
        assert niveau_alerte_pour(0.80) == NiveauAlerteBudget.VIGILANCE
        assert niveau_alerte_pour(0.94) == NiveauAlerteBudget.VIGILANCE

    def test_seuils_alerte(self):
        assert niveau_alerte_pour(0.95) == NiveauAlerteBudget.ALERTE
        assert niveau_alerte_pour(0.99) == NiveauAlerteBudget.ALERTE

    def test_seuils_depassement(self):
        assert niveau_alerte_pour(1.0) == NiveauAlerteBudget.DEPASSEMENT
        assert niveau_alerte_pour(1.5) == NiveauAlerteBudget.DEPASSEMENT


class TestAxesEtSections:
    async def test_creation_axe(self, db_session, tenant, admin_user):
        svc = AnalyticalService(db_session, tenant.id, admin_user.id)
        axis = await svc.creer_axe(AnalyticalAxisCreate(
            code="CTR-COUT",
            libelle="Centres de coût",
            type_axe="centre_cout",
        ))
        assert axis.code == "CTR-COUT"
        assert axis.type_axe == "centre_cout"

    async def test_creation_sections(self, db_session, tenant, admin_user):
        svc = AnalyticalService(db_session, tenant.id, admin_user.id)
        axis = await svc.creer_axe(AnalyticalAxisCreate(
            code="CTR", libelle="Centres", type_axe="centre_cout",
        ))

        for code, libelle in [("ADMIN", "Administration"), ("PROD", "Production"), ("COM", "Commercial")]:
            s = await svc.creer_section(AnalyticalSectionCreate(
                axis_id=axis.id, code=code, libelle=libelle,
            ))
            assert s.axis_id == axis.id

        sections = await svc.lister_sections(axis_id=axis.id)
        assert len(sections) == 3


class TestCleRepartition:
    async def test_creation_cle_valide(self, db_session, tenant, admin_user):
        svc = AnalyticalService(db_session, tenant.id, admin_user.id)
        axis = await svc.creer_axe(AnalyticalAxisCreate(
            code="AXE-L", libelle="Loyer", type_axe="centre_cout",
        ))
        s1 = await svc.creer_section(AnalyticalSectionCreate(
            axis_id=axis.id, code="S1", libelle="Section 1",
        ))
        s2 = await svc.creer_section(AnalyticalSectionCreate(
            axis_id=axis.id, code="S2", libelle="Section 2",
        ))

        key = await svc.creer_cle_repartition(AllocationKeyCreate(
            code="LOYER",
            libelle="Clé loyer",
            methode="fixe",
            axis_id=axis.id,
            lignes=[
                AllocationKeyLineCreate(section_id=s1.id, pourcentage=60),
                AllocationKeyLineCreate(section_id=s2.id, pourcentage=40),
            ],
        ))
        assert key.code == "LOYER"

    async def test_cle_pourcentage_invalide_rejete(self, db_session, tenant, admin_user):
        from pydantic import ValidationError
        svc = AnalyticalService(db_session, tenant.id, admin_user.id)
        axis = await svc.creer_axe(AnalyticalAxisCreate(
            code="AX", libelle="Test", type_axe="centre_cout",
        ))
        s1 = await svc.creer_section(AnalyticalSectionCreate(
            axis_id=axis.id, code="SA", libelle="SA",
        ))

        with pytest.raises(ValidationError, match="100%"):
            AllocationKeyCreate(
                code="X", libelle="X", methode="fixe", axis_id=axis.id,
                lignes=[AllocationKeyLineCreate(section_id=s1.id, pourcentage=80)],
            )

    async def test_simulation_repartition(self, db_session, tenant, admin_user):
        svc = AnalyticalService(db_session, tenant.id, admin_user.id)
        axis = await svc.creer_axe(AnalyticalAxisCreate(
            code="AX2", libelle="Test 2", type_axe="centre_cout",
        ))
        s1 = await svc.creer_section(AnalyticalSectionCreate(
            axis_id=axis.id, code="A", libelle="A",
        ))
        s2 = await svc.creer_section(AnalyticalSectionCreate(
            axis_id=axis.id, code="B", libelle="B",
        ))
        key = await svc.creer_cle_repartition(AllocationKeyCreate(
            code="K", libelle="K", methode="fixe", axis_id=axis.id,
            lignes=[
                AllocationKeyLineCreate(section_id=s1.id, pourcentage=70),
                AllocationKeyLineCreate(section_id=s2.id, pourcentage=30),
            ],
        ))
        await db_session.flush()

        result = await svc.simuler_repartition(key.id, 1_000_000)
        assert result.montant_total == 1_000_000
        parts = {r["section_code"]: r["montant_reparti"] for r in result.repartitions}
        assert parts["A"] == 700_000
        assert parts["B"] == 300_000


class TestImputation:
    async def test_imputation_directe(self, db_session, tenant, admin_user, plan_comptable_ci, journal_ve):
        from app.schemas.ecriture import EcritureCreate, LigneIn
        from app.services.syscohada_service import SyscohadaService

        # Créer une écriture
        sys_svc = SyscohadaService(db_session, tenant.id, admin_user.id)
        ecriture = await sys_svc.create(EcritureCreate(
            date_ecriture=date(2025, 3, 15),
            code_journal="VE",
            libelle="Vente test analytique",
            lignes=[
                LigneIn(compte="521100", debit=1_000_000),
                LigneIn(compte="701100", credit=1_000_000),
            ],
        ))
        await db_session.flush()

        # Créer un axe + section
        svc = AnalyticalService(db_session, tenant.id, admin_user.id)
        axis = await svc.creer_axe(AnalyticalAxisCreate(
            code="PRODUIT", libelle="Produits", type_axe="produit",
        ))
        section = await svc.creer_section(AnalyticalSectionCreate(
            axis_id=axis.id, code="P1", libelle="Produit 1",
        ))
        await db_session.flush()

        # Imputer la ligne crédit (produit) sur la section
        ligne_credit = next(l for l in ecriture.lignes if l.credit_xof > 0)
        entries = await svc.imputer_ligne(ImputationBatchRequest(
            ecriture_ligne_id=ligne_credit.id,
            imputations=[
                ImputationCreate(section_id=section.id, montant=1_000_000, type_imputation="directe"),
            ],
        ))
        assert len(entries) == 1
        assert entries[0].montant == 1_000_000

    async def test_imputation_desequilibree_rejetee(
        self, db_session, tenant, admin_user, plan_comptable_ci, journal_ve
    ):
        from fastapi import HTTPException
        from app.schemas.ecriture import EcritureCreate, LigneIn
        from app.services.syscohada_service import SyscohadaService

        sys_svc = SyscohadaService(db_session, tenant.id, admin_user.id)
        ecriture = await sys_svc.create(EcritureCreate(
            date_ecriture=date(2025, 3, 15),
            code_journal="VE",
            libelle="Test",
            lignes=[
                LigneIn(compte="521100", debit=1_000_000),
                LigneIn(compte="701100", credit=1_000_000),
            ],
        ))
        await db_session.flush()

        svc = AnalyticalService(db_session, tenant.id, admin_user.id)
        axis = await svc.creer_axe(AnalyticalAxisCreate(
            code="AX3", libelle="Test 3", type_axe="produit",
        ))
        section = await svc.creer_section(AnalyticalSectionCreate(
            axis_id=axis.id, code="P1", libelle="P1",
        ))
        await db_session.flush()

        ligne = next(l for l in ecriture.lignes if l.credit_xof > 0)

        with pytest.raises(HTTPException) as exc:
            await svc.imputer_ligne(ImputationBatchRequest(
                ecriture_ligne_id=ligne.id,
                imputations=[
                    ImputationCreate(section_id=section.id, montant=500_000),  # ≠ 1 000 000
                ],
            ))
        assert exc.value.status_code == 400
        assert "≠" in exc.value.detail or "different" in exc.value.detail.lower()


class TestBudget:
    async def test_creation_budget(self, db_session, tenant, admin_user):
        svc = AnalyticalService(db_session, tenant.id, admin_user.id)
        axis = await svc.creer_axe(AnalyticalAxisCreate(
            code="CTR-B", libelle="Centres", type_axe="centre_cout",
        ))
        section = await svc.creer_section(AnalyticalSectionCreate(
            axis_id=axis.id, code="PROD", libelle="Production",
        ))

        budget = await svc.creer_budget(BudgetCreate(
            code="BUDGET-2025",
            libelle="Budget 2025 Production",
            section_id=section.id,
            annee=2025,
            date_debut=date(2025, 1, 1),
            date_fin=date(2025, 12, 31),
            lignes=[
                BudgetLineCreate(
                    compte="601100",
                    libelle="Achats matières",
                    nature="charge",
                    mois=[1_000_000] * 12,  # 12M sur l'année
                ),
                BudgetLineCreate(
                    compte="701100",
                    libelle="Ventes",
                    nature="produit",
                    mois=[3_000_000] * 12,  # 36M
                ),
            ],
        ))
        await db_session.flush()

        assert budget.total_charges == 12_000_000
        assert budget.total_produits == 36_000_000
        assert budget.resultat_prevu == 24_000_000
        assert budget.version == 1

    async def test_validation_budget(self, db_session, tenant, admin_user):
        svc = AnalyticalService(db_session, tenant.id, admin_user.id)
        budget = await svc.creer_budget(BudgetCreate(
            code="B-2025",
            libelle="Budget",
            annee=2025,
            date_debut=date(2025, 1, 1),
            date_fin=date(2025, 12, 31),
            lignes=[
                BudgetLineCreate(
                    compte="601100", libelle="Achats", nature="charge",
                    mois=[500_000] * 12,
                ),
            ],
        ))
        await db_session.flush()

        budget = await svc.valider_budget(budget.id)
        assert budget.statut == "valide"
        assert budget.valide_at is not None

    async def test_activation_budget_desactive_ancien(
        self, db_session, tenant, admin_user
    ):
        svc = AnalyticalService(db_session, tenant.id, admin_user.id)

        # v1
        b1 = await svc.creer_budget(BudgetCreate(
            code="B-2025", libelle="Budget v1", annee=2025,
            date_debut=date(2025, 1, 1), date_fin=date(2025, 12, 31),
            lignes=[BudgetLineCreate(
                compte="601100", libelle="A", nature="charge", mois=[100_000] * 12,
            )],
        ))
        await svc.valider_budget(b1.id)
        await svc.activer_budget(b1.id)

        # v2 (même code)
        b2 = await svc.creer_budget(BudgetCreate(
            code="B-2025", libelle="Budget v2", annee=2025,
            date_debut=date(2025, 1, 1), date_fin=date(2025, 12, 31),
            lignes=[BudgetLineCreate(
                compte="601100", libelle="A", nature="charge", mois=[200_000] * 12,
            )],
        ))
        await db_session.flush()
        assert b2.version == 2

        await svc.valider_budget(b2.id)
        await svc.activer_budget(b2.id)

        # v1 doit être clôturé
        await db_session.refresh(b1)
        assert b1.statut == "cloture"
        assert b2.statut == "actif"


class TestControleBudgetaire:
    async def test_controle_budget_sans_realise(
        self, db_session, tenant, admin_user
    ):
        svc = AnalyticalService(db_session, tenant.id, admin_user.id)
        budget = await svc.creer_budget(BudgetCreate(
            code="B-CTRL", libelle="Contrôle", annee=2025,
            date_debut=date(2025, 1, 1), date_fin=date(2025, 12, 31),
            lignes=[
                BudgetLineCreate(
                    compte="601100", libelle="Achats", nature="charge",
                    mois=[1_000_000] * 12,
                ),
            ],
        ))
        await db_session.flush()

        controle = await svc.controle_budgetaire(budget.id, mois_arret=6)
        assert controle.total_charges_budget == 6_000_000  # 6 mois × 1M
        assert controle.total_charges_realise == 0
        assert controle.nb_lignes_depassement == 0
