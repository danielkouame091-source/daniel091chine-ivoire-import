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
        raison_social
