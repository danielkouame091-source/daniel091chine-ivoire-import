"""
Tests du moteur de valorisation des stocks.

Vérifie les deux méthodes SYSCOHADA :
- CUMP : (valeur_avant + valeur_entrée) / (qté_avant + qté_entrée)
- FIFO : consommation des couches les plus anciennes
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.schemas.stock import (
    ItemCreate,
    MouvementEntreeCreate,
    MouvementSortieCreate,
    WarehouseCreate,
)
from app.services.stock_service import StockService

pytestmark = pytest.mark.integration


class TestCUMP:
    async def test_entree_unique_cump_egal_prix(self, db_session, tenant, admin_user):
        """Une seule entrée → CUMP = prix unitaire."""
        svc = StockService(db_session, tenant.id, admin_user.id)

        item = await self._create_item(db_session, tenant, admin_user, method="cump")
        wh = await self._create_warehouse(db_session, tenant)

        mv = await svc.entree_stock(
            MouvementEntreeCreate(
                item_id=item.id,
                warehouse_id=wh.id,
                date_mouvement=date(2025, 3, 15),
                quantite=100,
                prix_unitaire=1000,
                libelle="Entrée initiale",
            ),
            comptabiliser=False,
        )
        await db_session.flush()

        from app.models.stock import StockLevel
        from sqlalchemy import select
        level = (await db_session.execute(
            select(StockLevel).where(StockLevel.item_id == item.id)
        )).scalar_one()

        assert float(level.quantite) == 100
        assert float(level.cump) == 1000
        assert level.valeur_stock == 100_000

    async def test_deuxieme_entree_recalcule_cump(self, db_session, tenant, admin_user):
        """Deux entrées à prix différents → CUMP pondéré."""
        svc = StockService(db_session, tenant.id, admin_user.id)
        item = await self._create_item(db_session, tenant, admin_user, method="cump")
        wh = await self._create_warehouse(db_session, tenant)

        await svc.entree_stock(MouvementEntreeCreate(
            item_id=item.id, warehouse_id=wh.id,
            date_mouvement=date(2025, 3, 1), quantite=100, prix_unitaire=1000,
            libelle="Entrée 1",
        ), comptabiliser=False)

        await svc.entree_stock(MouvementEntreeCreate(
            item_id=item.id, warehouse_id=wh.id,
            date_mouvement=date(2025, 3, 5), quantite=50, prix_unitaire=1200,
            libelle="Entrée 2",
        ), comptabiliser=False)
        await db_session.flush()

        from app.models.stock import StockLevel
        from sqlalchemy import select
        level = (await db_session.execute(
            select(StockLevel).where(StockLevel.item_id == item.id)
        )).scalar_one()

        # CUMP = (100×1000 + 50×1200) / 150 = 160 000 / 150 = 1066.666...
        assert float(level.quantite) == 150
        assert abs(float(level.cump) - 1066.6667) < 0.001
        assert level.valeur_stock == 160_000

    async def test_sortie_valorisee_au_cump(self, db_session, tenant, admin_user):
        """Sortie valorisée au CUMP courant."""
        svc = StockService(db_session, tenant.id, admin_user.id)
        item = await self._create_item(db_session, tenant, admin_user, method="cump")
        wh = await self._create_warehouse(db_session, tenant)

        await svc.entree_stock(MouvementEntreeCreate(
            item_id=item.id, warehouse_id=wh.id,
            date_mouvement=date(2025, 3, 1), quantite=100, prix_unitaire=1000,
            libelle="Entrée 1",
        ), comptabiliser=False)
        await svc.entree_stock(MouvementEntreeCreate(
            item_id=item.id, warehouse_id=wh.id,
            date_mouvement=date(2025, 3, 5), quantite=50, prix_unitaire=1200,
            libelle="Entrée 2",
        ), comptabiliser=False)

        # Sortie 30 unités au CUMP courant (1066.67)
        mv = await svc.sortie_stock(MouvementSortieCreate(
            item_id=item.id, warehouse_id=wh.id,
            date_mouvement=date(2025, 3, 10), quantite=30,
            libelle="Sortie 1",
        ), comptabiliser=False)
        await db_session.flush()

        # Coût unitaire = 1067 (arrondi)
        assert mv.cout_unitaire_sortie == 1067
        # Montant = 30 × 1067 = 32 010
        assert mv.montant_ht == 30 * 1067

    async def test_sortie_stock_insuffisant(self, db_session, tenant, admin_user):
        svc = StockService(db_session, tenant.id, admin_user.id)
        item = await self._create_item(db_session, tenant, admin_user, method="cump")
        wh = await self._create_warehouse(db_session, tenant)

        await svc.entree_stock(MouvementEntreeCreate(
            item_id=item.id, warehouse_id=wh.id,
            date_mouvement=date(2025, 3, 1), quantite=10, prix_unitaire=1000,
            libelle="Entrée",
        ), comptabiliser=False)

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            await svc.sortie_stock(MouvementSortieCreate(
                item_id=item.id, warehouse_id=wh.id,
                date_mouvement=date(2025, 3, 5), quantite=20,
                libelle="Sortie trop grande",
            ), comptabiliser=False)
        assert "insuffisant" in str(exc.value.detail).lower()

    # ─────────────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────────────
    @staticmethod
    async def _create_item(db_session, tenant, admin_user, method="cump"):
        from app.models.stock import Item
        item = Item(
            tenant_id=tenant.id,
            code=f"ART-{method.upper()}",
            designation=f"Article test {method}",
            unite="U",
            famille_stock="marchandises",
            methode_valorisation=method,
            prix_achat_ht=1000,
            prix_vente_ht=1500,
        )
        db_session.add(item)
        await db_session.flush()
        return item

    @staticmethod
    async def _create_warehouse(db_session, tenant):
        from app.models.stock import Warehouse
        wh = Warehouse(
            tenant_id=tenant.id,
            code="WH01",
            libelle="Entrepôt principal",
            est_principal=True,
        )
        db_session.add(wh)
        await db_session.flush()
        return wh


class TestFIFO:
    async def test_fifo_consomme_couche_ancienne(self, db_session, tenant, admin_user):
        """FIFO : la sortie consomme en priorité la couche la plus ancienne."""
        svc = StockService(db_session, tenant.id, admin_user.id)
        item = await self._create_item(db_session, tenant, admin_user, method="fifo")
        wh = await self._create_warehouse(db_session, tenant)

        # Couche 1 : 50 unités à 1000
        await svc.entree_stock(MouvementEntreeCreate(
            item_id=item.id, warehouse_id=wh.id,
            date_mouvement=date(2025, 3, 1), quantite=50, prix_unitaire=1000,
            libelle="Couche 1",
        ), comptabiliser=False)
        # Couche 2 : 50 unités à 1200
        await svc.entree_stock(MouvementEntreeCreate(
            item_id=item.id, warehouse_id=wh.id,
            date_mouvement=date(2025, 3, 5), quantite=50, prix_unitaire=1200,
            libelle="Couche 2",
        ), comptabiliser=False)

        # Sortie 30 unités → doit prendre 30 dans la couche 1 (à 1000)
        mv = await svc.sortie_stock(MouvementSortieCreate(
            item_id=item.id, warehouse_id=wh.id,
            date_mouvement=date(2025, 3, 10), quantite=30,
            libelle="Sortie FIFO 30",
        ), comptabiliser=False)
        await db_session.flush()

        assert mv.cout_unitaire_sortie == 1000
        assert mv.montant_ht == 30_000

    async def test_fifo_traverse_couches(self, db_session, tenant, admin_user):
        """FIFO : une sortie qui dépasse la 1re couche entame la 2e."""
        svc = StockService(db_session, tenant.id, admin_user.id)
        item = await self._create_item(db_session, tenant, admin_user, method="fifo")
        wh = await self._create_warehouse(db_session, tenant)

        await svc.entree_stock(MouvementEntreeCreate(
            item_id=item.id, warehouse_id=wh.id,
            date_mouvement=date(2025, 3, 1), quantite=50, prix_unitaire=1000,
            libelle="Couche 1",
        ), comptabiliser=False)
        await svc.entree_stock(MouvementEntreeCreate(
            item_id=item.id, warehouse_id=wh.id,
            date_mouvement=date(2025, 3, 5), quantite=50, prix_unitaire=1200,
            libelle="Couche 2",
        ), comptabiliser=False)

        # Sortie 70 unités : 50 à 1000 + 20 à 1200 = 50 000 + 24 000 = 74 000
        mv = await svc.sortie_stock(MouvementSortieCreate(
            item_id=item.id, warehouse_id=wh.id,
            date_mouvement=date(2025, 3, 10), quantite=70,
            libelle="Sortie FIFO 70",
        ), comptabiliser=False)
        await db_session.flush()

        assert mv.montant_ht == 74_000
        # Coût unitaire moyen pondéré = 74 000 / 70 = 1057 (arrondi)
        assert mv.cout_unitaire_sortie == 1057

    async def test_fifo_valeur_stock_apres_sortie(self, db_session, tenant, admin_user):
        svc = StockService(db_session, tenant.id, admin_user.id)
        item = await self._create_item(db_session, tenant, admin_user, method="fifo")
        wh = await self._create_warehouse(db_session, tenant)

        await svc.entree_stock(MouvementEntreeCreate(
            item_id=item.id, warehouse_id=wh.id,
            date_mouvement=date(2025, 3, 1), quantite=50, prix_unitaire=1000,
            libelle="Couche 1",
        ), comptabiliser=False)
        await svc.entree_stock(MouvementEntreeCreate(
            item_id=item.id, warehouse_id=wh.id,
            date_mouvement=date(2025, 3, 5), quantite=50, prix_unitaire=1200,
            libelle="Couche 2",
        ), comptabiliser=False)

        await svc.sortie_stock(MouvementSortieCreate(
            item_id=item.id, warehouse_id=wh.id,
            date_mouvement=date(2025, 3, 10), quantite=30,
            libelle="Sortie",
        ), comptabiliser=False)
        await db_session.flush()

        from app.models.stock import StockLevel
        from sqlalchemy import select
        level = (await db_session.execute(
            select(StockLevel).where(StockLevel.item_id == item.id)
        )).scalar_one()

        # Reste : 20 à 1000 + 50 à 1200 = 20 000 + 60 000 = 80 000
        assert level.valeur_stock == 80_000
        assert float(level.quantite) == 70

    # Helpers réutilisés
    _create_item = TestCUMP._create_item
    _create_warehouse = TestCUMP._create_warehouse
