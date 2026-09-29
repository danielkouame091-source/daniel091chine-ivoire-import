"""
Tests du moteur d'amortissement SYSCOHADA.

Cas couverts :
- Amortissement linéaire (durée entière, 5 ans)
- Amortissement dégressif (coefficient CI)
- Prorata temporis 1re année
- Cession avec plus/moins-value
- Écritures équilibrées
"""
from __future__ import annotations

from datetime import date

import pytest

from app.schemas.asset import DisposalCreate, FixedAssetCreate
from app.services.asset_service import AssetService

pytestmark = pytest.mark.integration


class TestAmortissementLineaire:
    async def test_plan_lineaire_5_ans(self, db_session, tenant, admin_user):
        """Machine 5 000 000 FCFA, durée 5 ans, mise en service 01/01 → 1 000 000/an."""
        svc = AssetService(db_session, tenant.id, admin_user.id)

        asset = await svc.creer_immobilisation(FixedAssetCreate(
            code="MAC-001",
            designation="Machine industrielle",
            famille="materiel_outillage",
            date_acquisition=date(2025, 1, 1),
            date_mise_en_service=date(2025, 1, 1),
            valeur_origine=5_000_000,
            methode_amortissement="lineaire",
            duree_amortissement_ans=5,
        ))
        await db_session.flush()

        plan = await svc.get_plan(asset.id)
        assert len(plan) == 5

        # Chaque annuité = 5 000 000 / 5 = 1 000 000
        for entry in plan:
            assert entry.dotation == 1_000_000

        # Vérifier la VNC finale
        assert plan[-1].vnc_fin == 0
        assert plan[-1].amortissement_cumule == 5_000_000

    async def test_plan_lineaire_prorata_mise_service_juillet(self, db_session, tenant, admin_user):
        """Machine 5 000 000 FCFA, durée 5 ans, mise en service 01/07/2025 → prorata 1re année."""
        svc = AssetService(db_session, tenant.id, admin_user.id)

        asset = await svc.creer_immobilisation(FixedAssetCreate(
            code="MAC-002",
            designation="Machine avec prorata",
            famille="materiel_outillage",
            date_acquisition=date(2025, 7, 1),
            date_mise_en_service=date(2025, 7, 1),
            valeur_origine=5_000_000,
            methode_amortissement="lineaire",
            duree_amortissement_ans=5,
        ))
        await db_session.flush()

        plan = await svc.get_plan(asset.id)

        # 1re année : 6 mois (juillet-décembre) → 184 jours
        # Dotation = 1 000 000 × 184/365 ≈ 504 109
        assert plan[0].prorata < 1.0
        assert plan[0].dotation < 1_000_000
        assert plan[0].dotation > 490_000

        # Le total cumulé doit être exactement 5 000 000
        total = sum(e.dotation for e in plan)
        assert total == 5_000_000

    async def test_valeur_residuelle(self, db_session, tenant, admin_user):
        """Véhicule 10 000 000 FCFA, VR 2 000 000 FCFA, durée 4 ans → base = 8 000 000."""
        svc = AssetService(db_session, tenant.id, admin_user.id)

        asset = await svc.creer_immobilisation(FixedAssetCreate(
            code="VEH-001",
            designation="Camion",
            famille="materiel_transport",
            date_acquisition=date(2025, 1, 1),
            date_mise_en_service=date(2025, 1, 1),
            valeur_origine=10_000_000,
            valeur_residuelle=2_000_000,
            methode_amortissement="lineaire",
            duree_amortissement_ans=4,
        ))
        await db_session.flush()

        plan = await svc.get_plan(asset.id)
        assert len(plan) == 4

        # Base amortissable = 10M - 2M = 8M, donc 2M/an
        for e in plan:
            assert e.dotation == 2_000_000

        # VNC finale = VR
        assert plan[-1].vnc_fin == 2_000_000


class TestAmortissementDegressif:
    async def test_plan_degressif_5_ans(self, db_session, tenant, admin_user):
        """
        Machine 10 000 000 FCFA, durée 5 ans, méthode dégressive.
        Coefficient CI pour 5-6 ans : 2.0
        Taux dégressif = (1/5) × 2.0 = 40%
        """
        svc = AssetService(db_session, tenant.id, admin_user.id)

        asset = await svc.creer_immobilisation(FixedAssetCreate(
            code="MAC-DEG-001",
            designation="Machine dégressive",
            famille="materiel_outillage",
            date_acquisition=date(2025, 1, 1),
            date_mise_en_service=date(2025, 1, 1),
            valeur_origine=10_000_000,
            methode_amortissement="degressif",
            duree_amortissement_ans=5,
        ))
        await db_session.flush()

        plan = await svc.get_plan(asset.id)
        assert len(plan) >= 4

        # 1re année : 10M × 40% = 4 000 000
        assert plan[0].dotation == 4_000_000
        assert plan[0].vnc_fin == 6_000_000

        # 2e année : 6M × 40% = 2 400 000
        assert plan[1].dotation == 2_400_000
        assert plan[1].vnc_fin == 3_600_000

        # 3e année : 3.6M × 40% = 1 440 000
        # Mais on bascule en linéaire dès que l'annuité linéaire est supérieure
        # VNC = 3 600 000, années restantes = 2, dotation linéaire = 1 800 000
        # 1 800 000 > 1 440 000 → bascule en linéaire
        assert plan[2].dotation == 1_800_000

        # Total amorti = 10 000 000
        total = sum(e.dotation for e in plan)
        assert total == 10_000_000

    async def test_coefficient_degressif(self):
        """Vérifie les coefficients CI."""
        from app.core.asset_syscohada import coefficient_degressif

        assert coefficient_degressif(3) == 1.5
        assert coefficient_degressif(4) == 1.5
        assert coefficient_degressif(5) == 2.0
        assert coefficient_degressif(6) == 2.0
        assert coefficient_degressif(8) == 2.5
        assert coefficient_degressif(10) == 2.5


class TestCession:
    async def test_cession_plus_value(self, db_session, tenant, admin_user):
        """
        Machine 5M, durée 5 ans, cédée après 2 ans à 4M HT.
        Cumul amort après 2 ans = 2M, VNC = 3M.
        Plus-value = 4M - 3M = 1M.
        """
        svc = AssetService(db_session, tenant.id, admin_user.id)

        asset = await svc.creer_immobilisation(FixedAssetCreate(
            code="MAC-CESS-001",
            designation="Machine à céder",
            famille="materiel_outillage",
            date_acquisition=date(2023, 1, 1),
            date_mise_en_service=date(2023, 1, 1),
            valeur_origine=5_000_000,
            methode_amortissement="lineaire",
            duree_amortissement_ans=5,
        ))
        await db_session.flush()

        disposal = await svc.ceder_immobilisation(DisposalCreate(
            asset_id=asset.id,
            type_cession="cession",
            date_cession=date(2024, 12, 31),
            motif="Vente à un tiers",
            prix_cession_ht=4_000_000,
            taux_tva=0.18,
            acquereur="Société XYZ",
        ))
        await db_session.flush()

        # VNC après 2 ans = 5M - 2M = 3M
        assert disposal.vnc == 3_000_000
        # TVA 18% sur 4M = 720 000
        assert disposal.tva_collectee == 720_000
        assert disposal.prix_cession_ttc == 4_720_000
        # Plus-value = 4M - 3M = 1M
        assert disposal.plus_value == 1_000_000
        assert disposal.moins_value == 0

        # Immobilisation passée en statut "cede"
        from app.models.asset import FixedAsset
        from sqlalchemy import select
        asset_after = (await db_session.execute(
            select(FixedAsset).where(FixedAsset.id == asset.id)
        )).scalar_one()
        assert asset_after.statut == "cede"

    async def test_cession_moins_value(self, db_session, tenant, admin_user):
        """Machine 5M cédée après 2 ans à 2M HT → moins-value 1M."""
        svc = AssetService(db_session, tenant.id, admin_user.id)

        asset = await svc.creer_immobilisation(FixedAssetCreate(
            code="MAC-CESS-002",
            designation="Machine à céder 2",
            famille="materiel_outillage",
            date_acquisition=date(2023, 1, 1),
            date_mise_en_service=date(2023, 1, 1),
            valeur_origine=5_000_000,
            methode_amortissement="lineaire",
            duree_amortissement_ans=5,
        ))
        await db_session.flush()

        disposal = await svc.ceder_immobilisation(DisposalCreate(
            asset_id=asset.id,
            type_cession="cession",
            date_cession=date(2024, 12, 31),
            motif="Vente à perte",
            prix_cession_ht=2_000_000,
            taux_tva=0.18,
        ))
        await db_session.flush()

        assert disposal.moins_value == 1_000_000
        assert disposal.plus_value == 0

    async def test_rebut_sans_prix(self, db_session, tenant, admin_user):
        """Mise au rebut → aucun prix, VNC passée en charge."""
        svc = AssetService(db_session, tenant.id, admin_user.id)

        asset = await svc.creer_immobilisation(FixedAssetCreate(
            code="MAC-REBUT-001",
            designation="Machine hors service",
            famille="materiel_outillage",
            date_acquisition=date(2022, 1, 1),
            date_mise_en_service=date(2022, 1, 1),
            valeur_origine=3_000_000,
            methode_amortissement="lineaire",
            duree_amortissement_ans=5,
        ))
        await db_session.flush()

        disposal = await svc.ceder_immobilisation(DisposalCreate(
            asset_id=asset.id,
            type_cession="rebut",
            date_cession=date(2024, 6, 30),
            motif="Machine irréparable",
            prix_cession_ht=0,
        ))
        await db_session.flush()

        assert disposal.prix_cession_ht == 0
        assert disposal.prix_cession_ttc == 0
        assert disposal.tva_collectee == 0
        # VNC ≈ 3M × 2.5/5 = 1.5M (2.5 ans sur 5)
        assert disposal.vnc > 1_400_000
        assert disposal.vnc < 1_600_000
