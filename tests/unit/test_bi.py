"""
Tests du module Business Intelligence.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.core.bi_syscohada import KPIS_STANDARD
from app.schemas.bi import (
    DashboardCreate,
    DashboardDuplicateIn,
    ReportCreate,
    ReportRunIn,
    WidgetCreate,
)
from app.services.bi_kpi_engine import KPIEngine
from app.services.bi_service import BIService

pytestmark = pytest.mark.integration


# ─── Fixtures ───────────────────────────────────────────────────────────────
@pytest.fixture
async def dashboard(db_session, tenant, admin_user):
    svc = BIService(db_session, tenant.id, admin_user.id)
    return await svc.creer_dashboard(DashboardCreate(
        code="TEST-DASH",
        nom="Dashboard Test",
        categorie="general",
    ))


@pytest.fixture
async def tenant_with_data(
    db_session, tenant, admin_user, customer, plan_comptable_ci, journal_ve
):
    """Crée une facture + écriture pour tester les KPIs."""
    from datetime import date as _date
    from app.schemas.ecriture import EcritureCreate, LigneIn
    from app.schemas.sale import CustomerInvoiceCreate, CustomerInvoiceLineCreate
    from app.services.sale_service import SaleService
    from app.services.syscohada_service import SyscohadaService

    # Écriture de vente
    sys_svc = SyscohadaService(db_session, tenant.id, admin_user.id)
    await sys_svc.create(EcritureCreate(
        date_ecriture=_date.today(),
        code_journal="VE",
        libelle="Vente test KPI",
        lignes=[
            LigneIn(compte="521100", debit=1_180_000),
            LigneIn(compte="701100", credit=1_000_000),
            LigneIn(compte="443100", credit=180_000),
        ],
    ))

    # Facture client
    sale_svc = SaleService(db_session, tenant.id, admin_user.id)
    inv = await sale_svc.creer_facture(CustomerInvoiceCreate(
        customer_id=customer.id,
        date_facture=_date.today(),
        lignes=[CustomerInvoiceLineCreate(
            designation="Test BI", quantite=1, prix_unitaire_ht=1_000_000,
            taux_tva=0.18, compte_produit="701100",
        )],
    ))
    await sale_svc.valider_facture(inv.id)
    await db_session.flush()
    return tenant


# ═════════════════════════════════════════════════════════════════════════════
# TESTS CATALOGUE
# ═════════════════════════════════════════════════════════════════════════════
class TestCatalogue:
    async def test_liste_kpis_standards(self, db_session, tenant, admin_user):
        assert len(KPIS_STANDARD) > 20
        codes = [k.code for k in KPIS_STANDARD]
        assert "CA_MENSUEL" in codes
        assert "TRESORERIE" in codes
        assert "MARGE_BRUTE" in codes


# ═════════════════════════════════════════════════════════════════════════════
# TESTS KPI ENGINE
# ═════════════════════════════════════════════════════════════════════════════
class TestKPIEngine:
    async def test_ca_mensuel(self, db_session, tenant_with_data):
        engine = KPIEngine(db_session, tenant_with_data.id)
        result = await engine.calculer_kpi("CA_MENSUEL", {"periode": "this_month"})
        assert result["valeur"] >= 1_000_000
        assert result["kpi_code"] == "CA_MENSUEL"

    async def test_tresorerie(self, db_session, tenant_with_data):
        engine = KPIEngine(db_session, tenant_with_data.id)
        result = await engine.calculer_kpi("TRESORERIE")
        assert result["valeur"] >= 0

    async def test_marge_brute(self, db_session, tenant_with_data):
        engine = KPIEngine(db_session, tenant_with_data.id)
        result = await engine.calculer_kpi("MARGE_BRUTE")
        # CA (1M) - Achats (0) = 1M
        assert result["valeur"] >= 1_000_000

    async def test_kpi_avec_comparaison(self, db_session, tenant_with_data):
        engine = KPIEngine(db_session, tenant_with_data.id)
        result = await engine.calculer_kpi("CA_MENSUEL", comparer_precedent=True)
        assert "valeur_precedente" in result
        assert "variation_pct" in result

    async def test_kpi_cache_hit(self, db_session, tenant_with_data):
        engine = KPIEngine(db_session, tenant_with_data.id)
        # 1ère fois → depuis_cache = False
        r1 = await engine.calculer_kpi("CA_MENSUEL", utiliser_cache=True)
        assert r1["depuis_cache"] is False

        # 2e fois → depuis_cache = True
        r2 = await engine.calculer_kpi("CA_MENSUEL", utiliser_cache=True)
        assert r2["depuis_cache"] is True
        assert r2["valeur"] == r1["valeur"]

    async def test_kpi_inconnu_rejete(self, db_session, tenant, admin_user):
        from fastapi import HTTPException
        engine = KPIEngine(db_session, tenant.id)
        with pytest.raises(HTTPException) as exc:
            await engine.calculer_kpi("KPI_INEXISTANT")
        assert exc.value.status_code == 404

    async def test_serie_temporelle(self, db_session, tenant_with_data):
        engine = KPIEngine(db_session, tenant_with_data.id)
        points = await engine.calculer_serie_temporelle(
            "CA_MENSUEL",
            date_debut=date.today().replace(day=1) - timedelta(days=90),
            date_fin=date.today(),
            granularite="month",
        )
        assert len(points) >= 2
        assert all("date" in p and "valeur" in p for p in points)

    async def test_snapshot_creation(self, db_session, tenant_with_data):
        engine = KPIEngine(db_session, tenant_with_data.id)
        snap = await engine.creer_snapshot("CA_MENSUEL")
        assert snap.kpi_code == "CA_MENSUEL"
        assert snap.date_snapshot == date.today()

    async def test_tendance(self, db_session, tenant_with_data):
        engine = KPIEngine(db_session, tenant_with_data.id)
        await engine.creer_snapshot("CA_MENSUEL")
        await db_session.flush()

        trend = await engine.get_tendance("CA_MENSUEL", jours=7)
        assert trend["kpi_code"] == "CA_MENSUEL"
        assert "points" in trend


# ═════════════════════════════════════════════════════════════════════════════
# TESTS DASHBOARDS
# ═════════════════════════════════════════════════════════════════════════════
class TestDashboards:
    async def test_creation_dashboard(self, dashboard):
        assert dashboard.code == "TEST-DASH"
        assert dashboard.actif is True

    async def test_code_duplique_rejete(self, db_session, tenant, admin_user, dashboard):
        from fastapi import HTTPException
        svc = BIService(db_session, tenant.id, admin_user.id)
        with pytest.raises(HTTPException) as exc:
            await svc.creer_dashboard(DashboardCreate(
                code="TEST-DASH", nom="Dupliqué",
            ))
        assert exc.value.status_code == 409

    async def test_ajout_widget(self, db_session, tenant, admin_user, dashboard):
        svc = BIService(db_session, tenant.id, admin_user.id)
        w = await svc.ajouter_widget(dashboard.id, WidgetCreate(
            titre="CA du mois",
            type_widget="kpi_card",
            source="balance",
            kpi_code="CA_MENSUEL",
            position_x=0, position_y=0, largeur=3, hauteur=2,
        ))
        assert w.titre == "CA du mois"
        assert w.kpi_code == "CA_MENSUEL"

    async def test_widget_position_invalide_rejete(self, db_session, tenant, admin_user, dashboard):
        from fastapi import HTTPException
        svc = BIService(db_session, tenant.id, admin_user.id)
        with pytest.raises(HTTPException) as exc:
            await svc.ajouter_widget(dashboard.id, WidgetCreate(
                titre="Invalide",
                type_widget="kpi_card",
                source="balance",
                kpi_code="CA_MENSUEL",
                position_x=10, largeur=5,   # 10 + 5 > 12
            ))
        assert exc.value.status_code == 422

    async def test_execution_dashboard(
        self, db_session, tenant_with_data, admin_user
    ):
        svc = BIService(db_session, tenant_with_data.id, admin_user.id)
        dash = await svc.creer_dashboard(DashboardCreate(
            code="EXEC-TEST", nom="Test exécution",
        ))
        await svc.ajouter_widget(dash.id, WidgetCreate(
            titre="CA", type_widget="kpi_card", source="balance",
            kpi_code="CA_MENSUEL",
        ))
        await db_session.flush()

        result = await svc.executer_dashboard(dash.id, {"periode": "this_month"})
        assert result["dashboard_id"] == dash.id
        assert len(result["kpis"]) >= 1
        assert result["duree_ms"] >= 0

    async def test_duplication_dashboard(
        self, db_session, tenant, admin_user, dashboard
    ):
        svc = BIService(db_session, tenant.id, admin_user.id)
        await svc.ajouter_widget(dashboard.id, WidgetCreate(
            titre="Test", type_widget="kpi_card", source="balance",
            kpi_code="CA_MENSUEL",
        ))
        await db_session.flush()

        new_dash = await svc.dupliquer_dashboard(dashboard.id, DashboardDuplicateIn(
            code="TEST-DASH-2", nom="Copie",
        ))
        assert new_dash.code == "TEST-DASH-2"

        # Vérifier que les widgets ont été copiés
        detail = await svc.get_dashboard_detail(new_dash.id)
        assert len(detail.__dict__.get("widgets", [])) == 1

    async def test_partage_dashboard(
        self, db_session, tenant, admin_user, dashboard
    ):
        from app.schemas.bi import DashboardPartageIn
        svc = BIService(db_session, tenant.id, admin_user.id)
        result = await svc.partager_dashboard(dashboard.id, DashboardPartageIn())
        assert "partage_token" in result
        assert result["partage_url"].startswith("https://")

    async def test_seed_dashboards_defaut(self, db_session, tenant, admin_user):
        svc = BIService(db_session, tenant.id, admin_user.id)
        nb = await svc.seed_dashboards_defaut()
        assert nb >= 5
        # Idempotent
        nb2 = await svc.seed_dashboards_defaut()
        assert nb2 == 0


# ═════════════════════════════════════════════════════════════════════════════
# TESTS RAPPORTS
# ═════════════════════════════════════════════════════════════════════════════
class TestReports:
    async def test_creation_rapport(self, db_session, tenant, admin_user):
        svc = BIService(db_session, tenant.id, admin_user.id)
        r = await svc.creer_rapport(ReportCreate(
            code="REPORT-FACTURES",
            nom="Factures clients",
            source="factures_clients",
            config={"columns": [{"key": "numero", "label": "N°"}], "filters": []},
        ))
        assert r.code == "REPORT-FACTURES"

    async def test_execution_rapport_factures(
        self, db_session, tenant_with_data, admin_user
    ):
        svc = BIService(db_session, tenant_with_data.id, admin_user.id)
        r = await svc.creer_rapport(ReportCreate(
            code="RPT-FAC",
            nom="Factures",
            source="factures_clients",
            config={"columns": []},
        ))
        await db_session.flush()

        result = await svc.executer_rapport(r.id, limit=10, page=1)
        assert "lignes" in result
        assert result["total"] >= 1
        assert len(result["lignes"]) >= 1
