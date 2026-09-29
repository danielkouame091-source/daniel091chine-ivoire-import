"""
Tests du cycle Ventes & Clients.

Couvre :
- Création client + plafond crédit
- Cycle complet : devis → commande → BL → facture → encaissement
- Avoirs (retour, geste commercial)
- Balance âgée
- Relances progressives
- Écritures SYSCOHADA équilibrées
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.core.sale_syscohada import NiveauRelance
from app.schemas.sale import (
    CustomerCreate,
    CustomerInvoiceCreate,
    CustomerInvoiceLineCreate,
    CustomerPaymentCreate,
    CreditNoteCreate,
    CreditNoteLineCreate,
    DeliveryNoteCreate,
    DeliveryNoteLineCreate,
    QuoteCreate,
    QuoteLineCreate,
    SalesOrderCreate,
    SalesOrderLineCreate,
)
from app.services.sale_service import SaleService

pytestmark = pytest.mark.integration


# ─── Fixtures locales ───────────────────────────────────────────────────────
@pytest.fixture
async def warehouse_sale(db_session, tenant):
    from app.models.stock import Warehouse
    wh = Warehouse(
        tenant_id=tenant.id,
        code="WH-SALE",
        libelle="Entrepôt ventes",
        est_principal=True,
    )
    db_session.add(wh)
    await db_session.flush()
    return wh


@pytest.fixture
async def item_sale(db_session, tenant):
    from app.models.stock import Item
    item = Item(
        tenant_id=tenant.id,
        code="ART-SALE",
        designation="Article vente",
        unite="U",
        famille_stock="marchandises",
        methode_valorisation="cump",
        prix_achat_ht=1000,
        prix_vente_ht=1500,
    )
    db_session.add(item)
    await db_session.flush()
    # Réception initiale 1000 unités
    from app.schemas.st
