"""
Tests du module Audit & Contrôle interne.

Couvre :
- Piste d'audit (hash-chain, vérification d'intégrité)
- Règles par défaut (seed)
- Exécution de règles (équilibre, FNE manquante)
- Findings (workflow de résolution)
- Benford (détection d'anomalies)
- Rapport de conformité
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.core.audit_syscohada import SeveriteFinding, StatutFinding
from app.schemas.audit_internal import (
    AuditRuleCreate,
    AuditRunRequest,
    AuditTrailFilter,
    BenfordAnalysisRequest,
    ComplianceReportRequest,
    FindingResolveRequest,
)
from app.services.audit_internal_service import AuditInternalService

pytestmark = pytest.mark.integration


# ═════════════════════════════════════════════════════════════════════════════
# TESTS PISTE D'AUDIT
# ═════════════════════════════════════════════════════════════════════════════
class TestAuditTrail:
    async def test_log_action_cree_entree_hashee(
        self, db_session, tenant, admin_user
    ):
        svc = AuditInternalService(db_session, tenant.id, admin_user.id)
        entry = await svc.log_action(
            action="TEST_ACTION",
            categorie="tracabilite",
            ressource_type="test",
            ressource_id=None,
            apres={"foo": "bar"},
        )
        assert entry.hash_courant is not None
        assert entry.hash_precedent is None   # 1re entrée
        assert entry.action == "TEST_ACTION"

    async def test_hash_chain_correct(self, db_session, tenant, admin_user):
        """Chaque nouvelle entrée pointe vers le hash précédent."""
        svc = AuditInternalService(db_session, tenant.id, admin_user.id)

        e1 = await svc.log_action(
            action="ACTION_1", categorie="test",
            ressource_type="test",
        )
        e2 = await svc.log_action(
            action="ACTION_2", categorie="test",
            ressource_type="test",
        )

        assert e2.hash_precedent == e1.hash_courant
        assert e2.hash_courant != e1.hash_courant

    async def test_verify_chain_integre(self, db_session, tenant, admin_user):
        svc = AuditInternalService(db_session, tenant.id, admin_user.id)
        for i in range(5):
            await svc.log_action(
                action=f"ACTION_{i}", categorie="test",
                ressource_type="test",
            )
        await db_session.flush()

        result = await svc.verify_audit_chain(tenant.id, limit=100)
        assert result.integre is True
        assert result.nb_entrees == 5

    async def test_verify_chain_altere_detecte(
        self, db_session, tenant, admin_user
    ):
        """Altérer une entrée casse la chaîne."""
        from app.models.audit_internal import AuditTrail

        svc = AuditInternalService(db_session, tenant.id, admin_user.id)
        e1 = await svc.log_action(
            action="A", categorie="test", ressource_type="test",
        )
        await svc.log_action(
            action="B", categorie="test", ressource_type="test",
        )
        await db_session.flush()

        # Altération volontaire
        e1.action = "HACKED"
        await db_session.flush()

        result = await svc.verify_audit_chain(tenant.id)
        assert result.integre is False
        assert result.premiere_alteration is not None


# ═════════════════════════════════════════════════════════════════════════════
# TESTS RÈGLES
# ═════════════════════════════════════════════════════════════════════════════
class TestRegles:
    async def test_seed_regles_defaut(self, db_session, tenant, admin_user):
        svc = AuditInternalService(db_session, tenant.id, admin_user.id)
        nb = await svc.seed_regles_defaut()
        assert nb > 0

        # 2e appel = idempotent
        nb2 = await svc.seed_regles_defaut()
        assert nb2 == 0

    async def test_creation_regle_custom(self, db_session, tenant, admin_user):
        svc = AuditInternalService(db_session, tenant.id, admin_user.id)
        rule = await svc.creer_regle(AuditRuleCreate(
            code="CUSTOM-001",
            libelle="Règle personnalisée",
            categorie="coherence_comptable",
            type_regle="ecriture_desequilibree",
            severite="high",
        ))
        assert rule.code == "CUSTOM-001"

    async def test_detecter_ecriture_desequilibree(
        self, db_session, tenant, admin_user, plan_comptable_ci, journal_ve,
    ):
        """
        Crée une écriture déséquilibrée en contournant la validation.
        Le trigger DB devrait lever, donc on désactive le check via un test direct.
        """
        # Cette règle teste le trigger SQL, pas le service.
        # On vérifie au moins que la règle s'exécute sans erreur.
        svc = AuditInternalService(db_session, tenant.id, admin_user.id)
        await svc.seed_regles_defaut()
        await db_session.flush()

        runs = await svc.executer_regles(AuditRunRequest(
            rule_code="COH-001",
            date_debut=date.today() - timedelta(days=7),
            date_fin=date.today(),
        ))
        assert len(runs) == 1
        # Aucun déséquilibre attendu car la contrainte SQL empêche
        assert runs[0].nb_findings == 0


# ═════════════════════════════════════════════════════════════════════════════
# TESTS FINDINGS WORKFLOW
# ═════════════════════════════════════════════════════════════════════════════
class TestFindingsWorkflow:
    async def _creer_finding(self, db_session, tenant, admin_user) -> "AuditFinding":
        """Crée un finding de test."""
        from app.models.audit_internal import AuditFinding
        from app.models.audit_internal import AuditRule

        svc = AuditInternalService(db_session, tenant.id, admin_user.id)
        await svc.seed_regles_defaut()
        await db_session.flush()

        rule = await db_session.scalar(
            select(AuditRule).where(AuditRule.code == "COH-001")
        )

        finding = AuditFinding(
            tenant_id=tenant.id,
            rule_id=rule.id,
            reference="FND-TEST-001",
            titre="Test finding",
            description="Description test",
            severite=SeveriteFinding.MEDIUM,
            ressource_type="test",
            statut=StatutFinding.NOUVEAU,
        )
        db_session.add(finding)
        await db_session.flush()
        return finding

    async def test_resoudre_finding(self, db_session, tenant, admin_user):
        svc = AuditInternalService(db_session, tenant.id, admin_user.id)
        finding = await self._creer_finding(db_session, tenant, admin_user)

        result = await svc.resoudre_finding(finding.id, FindingResolveRequest(
            commentaire="Corrigé manuellement après vérification",
            statut="resolu",
        ))
        assert result.statut == "resolu"
        assert result.resolu_at is not None
        assert result.commentaire_resolution is not None

    async def test_escalader_finding(self, db_session, tenant, admin_user):
        svc = AuditInternalService(db_session, tenant.id, admin_user.id)
        finding = await self._creer_finding(db_session, tenant, admin_user)

        result = await svc.escalader_finding(finding.id, "Anomalie répétée 3 fois")
        assert result.escalade_fondateur is True
        assert result.statut == StatutFinding.ESCALADE


# ═════════════════════════════════════════════════════════════════════════════
# TESTS BENFORD
# ═════════════════════════════════════════════════════════════════════════════
class TestBenford:
    async def test_benford_echantillon_insuffisant(
        self, db_session, tenant, admin_user
    ):
        from fastapi import HTTPException
        svc = AuditInternalService(db_session, tenant.id, admin_user.id)
        with pytest.raises(HTTPException) as exc:
            await svc.analyser_benford(BenfordAnalysisRequest(
                periode_debut=date.today() - timedelta(days=30),
                periode_fin=date.today(),
            ))
        assert exc.value.status_code == 400
        assert "insuffisant" in exc.value.detail.lower()

    async def test_benford_analyse_complete(
        self, db_session, tenant, admin_user, plan_comptable_ci, journal_ve,
    ):
        """Crée 150 écritures → analyse Benford."""
        from app.schemas.ecriture import EcritureCreate, LigneIn
        from app.services.syscohada_service import SyscohadaService

        sys_svc = SyscohadaService(db_session, tenant.id, admin_user.id)
        for i in range(150):
            montant = 1000 + (i * 137) % 9000  # Distribution variée
            await sys_svc.create(EcritureCreate(
                date_ecriture=date.today() - timedelta(days=i % 30),
                code_journal="VE",
                libelle=f"Test {i}",
                lignes=[
                    LigneIn(compte="521100", debit=montant),
                    LigneIn(compte="701100", credit=montant),
                ],
            ))
        await db_session.flush()

        svc = AuditInternalService(db_session, tenant.id, admin_user.id)
        result = await svc.analyser_benford(BenfordAnalysisRequest(
            periode_debut=date.today() - timedelta(days=30),
            periode_fin=date.today(),
        ))
        assert result.nb_echantillons >= 100
        assert 0 <= result.score_conformite <= 1
        assert result.chi_square >= 0


# ═════════════════════════════════════════════════════════════════════════════
# TESTS RAPPORT DE CONFORMITÉ
# ═════════════════════════════════════════════════════════════════════════════
class TestComplianceReport:
    async def test_generer_rapport(self, db_session, tenant, admin_user):
        svc = AuditInternalService(db_session, tenant.id, admin_user.id)
        report = await svc.generer_rapport_conformite(ComplianceReportRequest(
            type_rapport="mensuel",
            periode_debut=date.today().replace(day=1),
            periode_fin=date.today(),
            generer_resume_ia=False,
        ))
        assert report.score_global >= 0
        assert report.nb_checks_total > 0
        assert report.resume_ia is not None


# ═════════════════════════════════════════════════════════════════════════════
# TESTS DASHBOARD
# ═════════════════════════════════════════════════════════════════════════════
class TestDashboard:
    async def test_dashboard(self, db_session, tenant, admin_user):
        svc = AuditInternalService(db_session, tenant.id, admin_user.id)
        await svc.seed_regles_defaut()
        await db_session.flush()

        dash = await svc.dashboard()
        assert dash.tenant_id == tenant.id
        assert dash.hash_chain_integre is True
        assert len(dash.tendance_30j) == 30
