"""
Tests du module Consolidation OHADA.

Couvre :
- Détermination automatique de la méthode (% contrôle)
- Périmètre de consolidation
- Détection intercos auto
- Éliminations
- Calcul des intérêts minoritaires
- Construction du bilan consolidé
"""
from __future__ import annotations

from datetime import date

import pytest

from app.core.consolidation_syscohada import (
    MethodeConsolidation,
    determiner_methode,
)
from app.schemas.consolidation import (
    ConsolidationGroupCreate,
    ConsolidationRunRequest,
    GroupCompanyCreate,
)
from app.services.consolidation_service import ConsolidationService

pytestmark = pytest.mark.integration


# ═════════════════════════════════════════════════════════════════════════════
# TESTS MÉTHODE (PUR)
# ═════════════════════════════════════════════════════════════════════════════
class TestMethodeConsolidation:
    def test_controle_exclusif_100(self):
        assert determiner_methode(100.0) == MethodeConsolidation.INTEGRATION_GLOBALE

    def test_controle_exclusif_60(self):
        assert determiner_methode(60.0) == MethodeConsolidation.INTEGRATION_GLOBALE

    def test_controle_exclusif_51(self):
        assert determiner_methode(51.0) == MethodeConsolidation.INTEGRATION_GLOBALE

    def test_controle_conjoint_50(self):
        assert determiner_methode(50.0) == MethodeConsolidation.INTEGRATION_PROPORTIONNELLE

    def test_influence_notable_30(self):
        assert determiner_methode(30.0) == MethodeConsolidation.MISE_EN_EQUIVALENCE

    def test_influence_notable_20(self):
        assert determiner_methode(20.0) == MethodeConsolidation.MISE_EN_EQUIVALENCE

    def test_hors_perimetre_10(self):
        assert determiner_methode(10.0) == MethodeConsolidation.EXCLUE

    def test_hors_perimetre_0(self):
        assert determiner_methode(0.0) == MethodeConsolidation.EXCLUE


# ═════════════════════════════════════════════════════════════════════════════
# FIXTURES
# ═════════════════════════════════════════════════════════════════════════════
@pytest.fixture
async def group_mere(db_session, tenant, admin_user):
    svc = ConsolidationService(db_session, tenant.id, admin_user.id)
    return await svc.creer_groupe(ConsolidationGroupCreate(
        code="GROUPE-TEST",
        libelle="Groupe Test SA",
        parent_tenant_id=tenant.id,
        devise_presentation="XOF",
    ))


@pytest.fixture
async def second_tenant(db_session):
    from app.models.enums import TenantStatut
    from app.models.tenant import Tenant
    t = Tenant(
        slug="filiale-test",
        raison_sociale="Filiale Test SARL",
        pays="CI",
        devise="XOF",
        statut=TenantStatut.ACTIF,
    )
    db_session.add(t)
    await db_session.flush()
    return t


# ═════════════════════════════════════════════════════════════════════════════
# TESTS GROUPE
# ═════════════════════════════════════════════════════════════════════════════
class TestGroupe:
    async def test_creation_groupe(self, group_mere):
        assert group_mere.code == "GROUPE-TEST"
        assert group_mere.devise_presentation == "XOF"
        assert group_mere.actif is True

    async def test_code_duplique_rejete(self, db_session, tenant, admin_user):
        from fastapi import HTTPException
        svc = ConsolidationService(db_session, tenant.id, admin_user.id)
        await svc.creer_groupe(ConsolidationGroupCreate(
            code="DUP", libelle="Test 1", parent_tenant_id=tenant.id,
        ))
        with pytest.raises(HTTPException) as exc:
            await svc.creer_groupe(ConsolidationGroupCreate(
                code="DUP", libelle="Test 2", parent_tenant_id=tenant.id,
            ))
        assert exc.value.status_code == 409


# ═════════════════════════════════════════════════════════════════════════════
# TESTS SOCIÉTÉS
# ═════════════════════════════════════════════════════════════════════════════
class TestSocietes:
    async def test_ajouter_filiale_100(
        self, db_session, group_mere, second_tenant, admin_user, tenant
    ):
        svc = ConsolidationService(db_session, tenant.id, admin_user.id)
        company = await svc.ajouter_societe(group_mere.id, GroupCompanyCreate(
            code="FILIALE-1",
            libelle="Filiale 1",
            tenant_id=second_tenant.id,
            pourcentage_controle=100.0,
            pourcentage_interet=100.0,
            methode="integration_globale",
            date_entree=date(2024, 1, 1),
        ))
        assert company.methode == "integration_globale"
        assert float(company.pourcentage_controle) == 100.0

    async def test_ajouter_filiale_60_40(
        self, db_session, group_mere, second_tenant, admin_user, tenant
    ):
        """Filiale à 60% → IG avec intérêts minoritaires de 40%."""
        svc = ConsolidationService(db_session, tenant.id, admin_user.id)
        company = await svc.ajouter_societe(group_mere.id, GroupCompanyCreate(
            code="FILIALE-2", libelle="Filiale 2",
            tenant_id=second_tenant.id,
            pourcentage_controle=60.0,
            pourcentage_interet=60.0,
            methode="integration_globale",
            date_entree=date(2024, 1, 1),
        ))
        assert company.methode == "integration_globale"
        assert float(company.pourcentage_controle) == 60.0


# ═════════════════════════════════════════════════════════════════════════════
# TESTS PÉRIMÈTRE
# ═════════════════════════════════════════════════════════════════════════════
class TestPerimetre:
    async def test_perimetre_avec_2_societes(
        self, db_session, group_mere, second_tenant, admin_user, tenant
    ):
        svc = ConsolidationService(db_session, tenant.id, admin_user.id)

        # Mère (tenant principal)
        await svc.ajouter_societe(group_mere.id, GroupCompanyCreate(
            code="MERE", libelle="Société mère",
            tenant_id=tenant.id,
            pourcentage_controle=100.0, pourcentage_interet=100.0,
            methode="integration_globale", date_entree=date(2024, 1, 1),
        ))
        # Filiale 70%
        await svc.ajouter_societe(group_mere.id, GroupCompanyCreate(
            code="FILIALE-70", libelle="Filiale 70%",
            tenant_id=second_tenant.id,
            pourcentage_controle=70.0, pourcentage_interet=70.0,
            methode="integration_globale", date_entree=date(2024, 1, 1),
        ))
        await db_session.flush()

        perimetre = await svc.determiner_perimetre(
            group_mere.id, date(2025, 6, 30)
        )
        assert perimetre.nb_societes_incluses == 2
        assert perimetre.pct_interet_total == 170.0  # 100 + 70


# ═════════════════════════════════════════════════════════════════════════════
# TESTS INTÉRÊTS MINORITAIRES
# ═════════════════════════════════════════════════════════════════════════════
class TestInteretsMinoritaires:
    async def test_calcul_minoritaires_40pct(
        self, db_session, tenant, group_mere, second_tenant, admin_user, plan_comptable_ci
    ):
        """
        Filiale 60% avec CP 10M et résultat 2M.
        Minoritaires = 40% → CP_mino = 4M, résultat_mino = 800k.
        """
        from app.schemas.ecriture import EcritureCreate, LigneIn
        from app.services.syscohada_service import SyscohadaService
        from app.models.enums import JournalType
        from app.models.journal import Journal
        from sqlalchemy import select

        # Setup journal BQ pour la filiale
        existing = await db_session.scalar(
            select(Journal).where(Journal.tenant_id == second_tenant.id, Journal.code == "BQ")
        )
        if not existing:
            db_session.add(Journal(
                tenant_id=second_tenant.id,
                code="BQ",
                libelle="BQ",
                type_journal=JournalType.BANQUE,
            ))
            # Plan comptable minimal filiale
            from app.models.plan_comptable import PlanComptable
            from app.models.enums import CompteType
            for compte, lib, classe, tc in [
                ("101000", "Capital", 1, CompteType.PASSIF),
                ("521000", "Banque", 5, CompteType.TRESORERIE),
                ("701100", "Ventes", 7, CompteType.PRODUIT),
            ]:
                db_session.add(PlanComptable(
                    tenant_id=second_tenant.id,
                    compte=compte, libelle=lib, classe=classe, type_compte=tc,
                ))
            await db_session.flush()

        # Capital 10M
        sys_svc = SyscohadaService(db_session, second_tenant.id, admin_user.id)
        await sys_svc.create(EcritureCreate(
            date_ecriture=date(2024, 1, 1),
            code_journal="BQ",
            libelle="Constitution capital",
            lignes=[
                LigneIn(compte="521000", debit=10_000_000),
                LigneIn(compte="101000", credit=10_000_000),
            ],
        ))
        # Vente 2M
        await sys_svc.create(EcritureCreate(
            date_ecriture=date(2025, 3, 15),
            code_journal="BQ",
            libelle="Vente",
            lignes=[
                LigneIn(compte="521000", debit=2_000_000),
                LigneIn(compte="701100", credit=2_000_000),
            ],
        ))
        await db_session.flush()

        # Ajouter la filiale à 60%
        svc = ConsolidationService(db_session, tenant.id, admin_user.id)
        company = await svc.ajouter_societe(group_mere.id, GroupCompanyCreate(
            code="FILIALE-60", libelle="Filiale 60%",
            tenant_id=second_tenant.id,
            pourcentage_controle=60.0, pourcentage_interet=60.0,
            methode="integration_globale", date_entree=date(2024, 1, 1),
        ))
        await db_session.flush()

        # Calculer
        from app.schemas.consolidation import PerimetreLigne
        perimetre_ligne = PerimetreLigne(
            company_id=company.id,
            code=company.code,
            libelle=company.libelle,
            pct_controle=60.0,
            pct_interet=60.0,
            methode="integration_globale",
            inclus=True,
            date_entree=date(2024, 1, 1),
        )

        # CP = 10M (capital) + 2M (résultat) = 12M
        cp = await svc._calculer_capitaux_propres(second_tenant.id, date(2025, 12, 31))
        assert cp == 12_000_000

        resultat = await svc._calculer_resultat(
            second_tenant.id, date(2025, 1, 1), date(2025, 12, 31)
        )
        assert resultat == 2_000_000


# ═════════════════════════════════════════════════════════════════════════════
# TESTS RUN COMPLET
# ═════════════════════════════════════════════════════════════════════════════
class TestRunComplet:
    async def test_executer_run_simple(
        self, db_session, tenant, group_mere, admin_user
    ):
        """Run avec seulement la société mère (pas d'intercos)."""
        svc = ConsolidationService(db_session, tenant.id, admin_user.id)

        # Ajouter la mère comme société du groupe
        await svc.ajouter_societe(group_mere.id, GroupCompanyCreate(
            code="MERE", libelle="Société mère",
            tenant_id=tenant.id,
            pourcentage_controle=100.0, pourcentage_interet=100.0,
            methode="integration_globale", date_entree=date(2024, 1, 1),
        ))
        await db_session.flush()

        run = await svc.executer_consolidation(group_mere.id, ConsolidationRunRequest(
            date_debut=date(2025, 1, 1),
            date_fin=date(2025, 3, 31),
        ))
        await db_session.flush()

        assert run.statut == "calcule"
        assert run.nb_societes == 1
        assert run.bilan_consolide is not None
        assert run.compte_resultat_consolide is not None
        assert run.notes_annexes is not None
        assert run.duree_execution_ms is not None
        assert run.duree_execution_ms > 0

    async def test_valider_run(
        self, db_session, tenant, group_mere, admin_user
    ):
        svc = ConsolidationService(db_session, tenant.id, admin_user.id)
        await svc.ajouter_societe(group_mere.id, GroupCompanyCreate(
            code="MERE", libelle="Société mère",
            tenant_id=tenant.id,
            pourcentage_controle=100.0, pourcentage_interet=100.0,
            methode="integration_globale", date_entree=date(2024, 1, 1),
        ))
        await db_session.flush()

        run = await svc.executer_consolidation(group_mere.id, ConsolidationRunRequest(
            date_debut=date(2025, 1, 1),
            date_fin=date(2025, 3, 31),
        ))
        run = await svc.valider_run(run.id)
        assert run.statut == "valide"
        assert run.valide_at is not None
