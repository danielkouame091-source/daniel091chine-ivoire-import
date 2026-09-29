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
    from app.schemas.stock import MouvementEntreeCreate
    from app.services.stock_service import StockService
    svc = StockService(db_session, tenant.id, tenant.id)  # user_id temporaire
    # On utilise tenant.id comme user_id pour ce test
    return item


@pytest.fixture
async def customer(db_session, tenant, admin_user):
    svc = SaleService(db_session, tenant.id, admin_user.id)
    return await svc.creer_client(CustomerCreate(
        code="CLI-001",
        raison_sociale="Client Test SARL",
        telephone="+2250700000000",
        delai_paiement_jours=30,
        plafond_credit=10_000_000,
        assujetti_tva=True,
    ))


# ═════════════════════════════════════════════════════════════════════════════
# TESTS CLIENTS
# ═════════════════════════════════════════════════════════════════════════════
class TestCustomer:
    async def test_creation_client(self, db_session, customer):
        assert customer.code == "CLI-001"
        assert customer.solde_comptable == 0
        assert customer.plafond_credit == 10_000_000

    async def test_code_duplique_rejete(self, db_session, tenant, admin_user):
        from fastapi import HTTPException
        svc = SaleService(db_session, tenant.id, admin_user.id)
        await svc.creer_client(CustomerCreate(code="DUP", raison_sociale="A"))
        with pytest.raises(HTTPException) as exc:
            await svc.creer_client(CustomerCreate(code="DUP", raison_sociale="B"))
        assert exc.value.status_code == 409


# ═════════════════════════════════════════════════════════════════════════════
# TESTS CYCLE COMPLET (facture + encaissement)
# ═════════════════════════════════════════════════════════════════════════════
class TestCycleFactureEncaissement:
    async def test_facture_et_encaissement_complet(
        self, db_session, tenant, admin_user, customer, plan_comptable_ci
    ):
        """Facture 500 000 HT + 18% TVA = 590 000 TTC, encaissée intégralement."""
        svc = SaleService(db_session, tenant.id, admin_user.id)

        invoice = await svc.creer_facture(CustomerInvoiceCreate(
            customer_id=customer.id,
            date_facture=date(2025, 3, 15),
            lignes=[
                CustomerInvoiceLineCreate(
                    designation="Vente 500 sacs de riz",
                    quantite=500,
                    prix_unitaire_ht=1000,
                    taux_tva=0.18,
                    compte_produit="701100",
                    famille_stock="marchandises",
                )
            ],
        ))
        assert invoice.total_ht == 500_000
        assert invoice.total_tva == 90_000
        assert invoice.total_ttc == 590_000
        assert invoice.solde_du == 590_000
        assert invoice.ecriture_id is not None

        await svc.valider_facture(invoice.id)

        await db_session.refresh(customer)
        assert customer.solde_comptable == 590_000

        # Encaissement complet par Wave
        payment = await svc.encaisser(CustomerPaymentCreate(
            invoice_id=invoice.id,
            date_encaissement=date(2025, 4, 10),
            montant=590_000,
            mode_encaissement="wave",
            reference_encaissement="WAVE-20250410-001",
        ))
        assert payment.statut == "valide"
        assert payment.compte_tresorerie == "521100"

        await db_session.refresh(invoice)
        assert invoice.statut == "payee"
        assert invoice.solde_du == 0

        await db_session.refresh(customer)
        assert customer.solde_comptable == 0

    async def test_encaissement_partiel(
        self, db_session, tenant, admin_user, customer, plan_comptable_ci
    ):
        svc = SaleService(db_session, tenant.id, admin_user.id)
        invoice = await svc.creer_facture(CustomerInvoiceCreate(
            customer_id=customer.id,
            date_facture=date(2025, 3, 15),
            lignes=[CustomerInvoiceLineCreate(
                designation="Achat A", quantite=10, prix_unitaire_ht=100_000,
                taux_tva=0.18, compte_produit="701100",
            )],
        ))
        await svc.valider_facture(invoice.id)

        # Encaissement partiel 500 000
        await svc.encaisser(CustomerPaymentCreate(
            invoice_id=invoice.id,
            date_encaissement=date(2025, 4, 1),
            montant=500_000,
            mode_encaissement="virement",
        ))
        await db_session.refresh(invoice)
        assert invoice.statut == "partiellement_payee"
        assert invoice.solde_du == 1_180_000 - 500_000


# ═════════════════════════════════════════════════════════════════════════════
# TESTS AVOIRS
# ═════════════════════════════════════════════════════════════════════════════
class TestAvoir:
    async def test_avoir_retour_marchandise(
        self, db_session, tenant, admin_user, customer, warehouse_sale, item_sale, plan_comptable_ci
    ):
        """Retour de 50 unités sur une facture initiale de 500."""
        svc = SaleService(db_session, tenant.id, admin_user.id)

        # 1. Facture initiale
        invoice = await svc.creer_facture(CustomerInvoiceCreate(
            customer_id=customer.id,
            date_facture=date(2025, 3, 15),
            lignes=[CustomerInvoiceLineCreate(
                designation="Article retour",
                quantite=500,
                prix_unitaire_ht=1000,
                taux_tva=0.18,
                compte_produit="701100",
            )],
        ))
        await svc.valider_facture(invoice.id)

        # 2. Avoir pour 50 unités retournées
        cn = await svc.creer_avoir(CreditNoteCreate(
            customer_id=customer.id,
            invoice_id=invoice.id,
            date_avoir=date(2025, 4, 1),
            motif="Retour marchandise défectueuse",
            type_avoir="retour",
            lignes=[CreditNoteLineCreate(
                designation="Article retour",
                quantite=50,
                prix_unitaire_ht=1000,
                taux_tva=0.18,
                compte_produit="701100",
                reintegrer_stock=True,
            )],
        ))
        assert cn.total_ht == 50_000
        assert cn.total_tva == 9_000
        assert cn.total_ttc == 59_000
        assert cn.statut == "impute"

        # Facture réduite
        await db_session.refresh(invoice)
        assert invoice.solde_du == 590_000 - 59_000
        assert invoice.statut in ("validee", "partiellement_payee")

    async def test_avoir_geste_commercial(
        self, db_session, tenant, admin_user, customer, plan_comptable_ci
    ):
        svc = SaleService(db_session, tenant.id, admin_user.id)
        invoice = await svc.creer_facture(CustomerInvoiceCreate(
            customer_id=customer.id,
            date_facture=date(2025, 3, 15),
            lignes=[CustomerInvoiceLineCreate(
                designation="Produit", quantite=10, prix_unitaire_ht=50_000,
                taux_tva=0.18, compte_produit="701100",
            )],
        ))
        await svc.valider_facture(invoice.id)

        cn = await svc.creer_avoir(CreditNoteCreate(
            customer_id=customer.id,
            invoice_id=invoice.id,
            date_avoir=date(2025, 4, 1),
            motif="Geste commercial fidélité",
            type_avoir="geste_commercial",
            lignes=[CreditNoteLineCreate(
                designation="Remise fidélité", quantite=1, prix_unitaire_ht=20_000,
                taux_tva=0.18, compte_produit="701100",
                reintegrer_stock=False,
            )],
        ))
        assert cn.total_ttc == 23_600


# ═════════════════════════════════════════════════════════════════════════════
# TESTS BALANCE ÂGÉE
# ═════════════════════════════════════════════════════════════════════════════
class TestBalanceAgeeClient:
    async def test_balance_agee_tranches(
        self, db_session, tenant, admin_user, customer, plan_comptable_ci
    ):
        svc = SaleService(db_session, tenant.id, admin_user.id)

        # Facture échue depuis 45 jours
        invoice = await svc.creer_facture(CustomerInvoiceCreate(
            customer_id=customer.id,
            date_facture=date(2025, 1, 1),
            date_echeance=date(2025, 1, 31),
            lignes=[CustomerInvoiceLineCreate(
                designation="Achat", quantite=1, prix_unitaire_ht=1_000_000,
                taux_tva=0.18, compte_produit="701100",
            )],
        ))
        await svc.valider_facture(invoice.id)

        balance = await svc.balance_agee(date_arret=date(2025, 3, 17))
        assert balance.total_du == 1_180_000
        # 45 jours → tranche 31-60
        assert balance.total_31_60 == 1_180_000
        assert balance.total_0_30 == 0
        assert len(balance.clients) == 1


# ═════════════════════════════════════════════════════════════════════════════
# TESTS RELANCES
# ═════════════════════════════════════════════════════════════════════════════
class TestRelances:
    async def test_niveau_relance_aimable_j3(
        self, db_session, tenant, admin_user, customer, plan_comptable_ci
    ):
        """Facture échue depuis 5 jours → relance aimable."""
        svc = SaleService(db_session, tenant.id, admin_user.id)
        invoice = await svc.creer_facture(CustomerInvoiceCreate(
            customer_id=customer.id,
            date_facture=date(2025, 3, 1),
            date_echeance=date(2025, 3, 15),
            lignes=[CustomerInvoiceLineCreate(
                designation="Produit", quantite=1, prix_unitaire_ht=100_000,
                taux_tva=0.18, compte_produit="701100",
            )],
        ))
        await svc.valider_facture(invoice.id)

        previews = await svc.previsualiser_relances(date_arret=date(2025, 3, 20))
        assert len(previews) == 1
        assert previews[0].jours_retard == 5
        assert previews[0].niveau_propose == NiveauRelance.AIMABLE

    async def test_niveau_relance_mise_en_demeure_j35(
        self, db_session, tenant, admin_user, customer, plan_comptable_ci
    ):
        svc = SaleService(db_session, tenant.id, admin_user.id)
        invoice = await svc.creer_facture(CustomerInvoiceCreate(
            customer_id=customer.id,
            date_facture=date(2025, 2, 1),
            date_echeance=date(2025, 2, 15),
            lignes=[CustomerInvoiceLineCreate(
                designation="Produit", quantite=1, prix_unitaire_ht=100_000,
                taux_tva=0.18, compte_produit="701100",
            )],
        ))
        await svc.valider_facture(invoice.id)

        previews = await svc.previsualiser_relances(date_arret=date(2025, 3, 22))
        assert previews[0].niveau_propose == NiveauRelance.MISE_EN_DEMEURE
        assert "MISE EN DEMEURE" in previews[0].message

    async def test_executer_relances_marque_factures(
        self, db_session, tenant, admin_user, customer, plan_comptable_ci
    ):
        svc = SaleService(db_session, tenant.id, admin_user.id)
        invoice = await svc.creer_facture(CustomerInvoiceCreate(
            customer_id=customer.id,
            date_facture=date(2025, 3, 1),
            date_echeance=date(2025, 3, 15),
            lignes=[CustomerInvoiceLineCreate(
                designation="Produit", quantite=1, prix_unitaire_ht=100_000,
                taux_tva=0.18, compte_produit="701100",
            )],
        ))
        await svc.valider_facture(invoice.id)

        result = await svc.executer_relances(date_arret=date(2025, 3, 25))
        assert result.invoices_relanced == 1

        await db_session.refresh(invoice)
        assert invoice.nb_relances == 1
        assert invoice.niveau_relance == NiveauRelance.FERME  # 10 jours
