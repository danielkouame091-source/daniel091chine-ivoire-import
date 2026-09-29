"""
Tests du cycle Achats & Fournisseurs.

Couvre :
- Création fournisseur + solde
- Cycle complet : PO → GR → FF → Paiement
- Rapprochement 3 voies (concordance + écarts)
- Balance âgée
- Écritures SYSCOHADA équilibrées
"""
from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select

from app.core.purchase_syscohada import ResultatRapprochement
from app.schemas.purchase import (
    GoodsReceiptCreate,
    GoodsReceiptLineCreate,
    PurchaseOrderCreate,
    PurchaseOrderLineCreate,
    SupplierCreate,
    SupplierInvoiceCreate,
    SupplierInvoiceLineCreate,
    SupplierPaymentCreate,
)
from app.services.purchase_service import PurchaseService

pytestmark = pytest.mark.integration


# ─── Fixtures locales ───────────────────────────────────────────────────────
@pytest.fixture
async def warehouse(db_session, tenant):
    from app.models.stock import Warehouse
    wh = Warehouse(
        tenant_id=tenant.id,
        code="WH-PURCH",
        libelle="Entrepôt achats",
        est_principal=True,
    )
    db_session.add(wh)
    await db_session.flush()
    return wh


@pytest.fixture
async def supplier(db_session, tenant, admin_user):
    svc = PurchaseService(db_session, tenant.id, admin_user.id)
    return await svc.creer_fournisseur(SupplierCreate(
        code="FOU-001",
        raison_sociale="Fournisseur Test SARL",
        telephone="+2250700000000",
        delai_paiement_jours=30,
        assujetti_tva=True,
    ))


# ═════════════════════════════════════════════════════════════════════════════
# TESTS FOURNISSEURS
# ═════════════════════════════════════════════════════════════════════════════
class TestSupplier:
    async def test_creation_fournisseur(self, db_session, supplier):
        assert supplier.code == "FOU-001"
        assert supplier.solde_comptable == 0
        assert supplier.actif is True

    async def test_code_duplique_rejete(self, db_session, tenant, admin_user):
        from fastapi import HTTPException
        svc = PurchaseService(db_session, tenant.id, admin_user.id)
        await svc.creer_fournisseur(SupplierCreate(code="FOU-X", raison_sociale="A"))
        with pytest.raises(HTTPException) as exc:
            await svc.creer_fournisseur(SupplierCreate(code="FOU-X", raison_sociale="B"))
        assert exc.value.status_code == 409


# ═════════════════════════════════════════════════════════════════════════════
# TESTS CYCLE COMPLET
# ═════════════════════════════════════════════════════════════════════════════
class TestCycleComplet:
    async def test_cycle_po_gr_ff_paiement(
        self,
        db_session,
        tenant,
        admin_user,
        supplier,
        warehouse,
        plan_comptable_ci,
    ):
        """
        Cycle complet :
        1. PO : 100 unités × 1 000 FCFA = 100 000 HT
        2. GR : réception de 100 unités conformes
        3. FF : facture de 100 unités × 1 000 → 118 000 TTC
        4. Paiement : 118 000 par virement
        """
        svc = PurchaseService(db_session, tenant.id, admin_user.id)

        # ─── 1. PO ───────────────────────────────────────────────────
        order = await svc.creer_commande(PurchaseOrderCreate(
            supplier_id=supplier.id,
            date_commande=date(2025, 3, 1),
            warehouse_destination_id=warehouse.id,
            lignes=[
                PurchaseOrderLineCreate(
                    designation="Article A",
                    quantite=100,
                    prix_unitaire_ht=1000,
                    taux_tva=0.18,
                    famille_stock="marchandises",
                )
            ],
        ))
        assert order.total_ht == 100_000
        assert order.total_tva == 18_000
        assert order.total_ttc == 118_000

        await svc.valider_commande(order.id)

        # ─── 2. GR (sans mouvements stock pour ce test) ──────────────
        # Récupérer la ligne PO
        from app.models.purchase import PurchaseOrderLine
        po_line = (await db_session.execute(
            select(PurchaseOrderLine).where(PurchaseOrderLine.order_id == order.id)
        )).scalar_one()

        receipt = await svc.creer_reception(GoodsReceiptCreate(
            supplier_id=supplier.id,
            purchase_order_id=order.id,
            warehouse_id=warehouse.id,
            date_reception=date(2025, 3, 5),
            creer_mouvements_stock=False,  # pas de stock dans ce test
            lignes=[
                GoodsReceiptLineCreate(
                    purchase_order_line_id=po_line.id,
                    designation="Article A",
                    quantite_recue=100,
                    prix_unitaire_ht=1000,
                )
            ],
        ))
        assert receipt.total_ht == 100_000

        # Vérifier que la commande est passée en "recue"
        await db_session.refresh(order)
        assert order.statut == "recue"

        # ─── 3. FF ───────────────────────────────────────────────────
        gr_line_id = None
        from app.models.purchase import GoodsReceiptLine
        gr_line = (await db_session.execute(
            select(GoodsReceiptLine).where(GoodsReceiptLine.receipt_id == receipt.id)
        )).scalar_one()

        invoice = await svc.creer_facture(SupplierInvoiceCreate(
            supplier_id=supplier.id,
            numero_fournisseur="FF-TEST-001",
            date_facture=date(2025, 3, 6),
            date_reception_facture=date(2025, 3, 7),
            purchase_order_id=order.id,
            goods_receipt_id=receipt.id,
            lignes=[
                SupplierInvoiceLineCreate(
                    purchase_order_line_id=po_line.id,
                    goods_receipt_line_id=gr_line.id,
                    designation="Article A",
                    quantite=100,
                    prix_unitaire_ht=1000,
                    taux_tva=0.18,
                    compte_achat="601000",
                    famille_stock="marchandises",
                )
            ],
        ))
        assert invoice.total_ht == 100_000
        assert invoice.total_tva == 18_000
        assert invoice.total_ttc == 118_000
        assert invoice.solde_du == 118_000
        assert invoice.rapprochement_resultat == ResultatRapprochement.OK

        await svc.valider_facture(invoice.id)

        # Solde fournisseur mis à jour
        await db_session.refresh(supplier)
        assert supplier.solde_comptable == 118_000

        # ─── 4. Paiement ─────────────────────────────────────────────
        payment = await svc.payer_facture(SupplierPaymentCreate(
            invoice_id=invoice.id,
            date_paiement=date(2025, 4, 1),
            montant=118_000,
            mode_paiement="virement",
            reference_paiement="VIR-001",
        ))
        assert payment.statut == "valide"

        await db_session.refresh(invoice)
        assert invoice.statut == "payee"
        assert invoice.solde_du == 0

        await db_session.refresh(supplier)
        assert supplier.solde_comptable == 0


# ═════════════════════════════════════════════════════════════════════════════
# TESTS RAPPROCHEMENT 3 VOIES
# ═════════════════════════════════════════════════════════════════════════════
class TestRapprochement:
    async def _setup_po_gr(
        self, db_session, tenant, admin_user, supplier, warehouse, qte=100, pu=1000
    ):
        from app.models.purchase import GoodsReceiptLine, PurchaseOrderLine
        svc = PurchaseService(db_session, tenant.id, admin_user.id)
        order = await svc.creer_commande(PurchaseOrderCreate(
            supplier_id=supplier.id,
            date_commande=date(2025, 3, 1),
            warehouse_destination_id=warehouse.id,
            lignes=[PurchaseOrderLineCreate(
                designation="Article X", quantite=qte, prix_unitaire_ht=pu,
                taux_tva=0.18, famille_stock="marchandises",
            )],
        ))
        await svc.valider_commande(order.id)
        po_line = (await db_session.execute(
            select(PurchaseOrderLine).where(PurchaseOrderLine.order_id == order.id)
        )).scalar_one()

        receipt = await svc.creer_reception(GoodsReceiptCreate(
            supplier_id=supplier.id,
            purchase_order_id=order.id,
            warehouse_id=warehouse.id,
            date_reception=date(2025, 3, 5),
            creer_mouvements_stock=False,
            lignes=[GoodsReceiptLineCreate(
                purchase_order_line_id=po_line.id,
                designation="Article X",
                quantite_recue=qte,
                prix_unitaire_ht=pu,
            )],
        ))
        gr_line = (await db_session.execute(
            select(GoodsReceiptLine).where(GoodsReceiptLine.receipt_id == receipt.id)
        )).scalar_one()

        return order, po_line, receipt, gr_line

    async def test_rapprochement_ok(
        self, db_session, tenant, admin_user, supplier, warehouse, plan_comptable_ci
    ):
        order, po_line, receipt, gr_line = await self._setup_po_gr(
            db_session, tenant, admin_user, supplier, warehouse
        )
        svc = PurchaseService(db_session, tenant.id, admin_user.id)

        invoice = await svc.creer_facture(SupplierInvoiceCreate(
            supplier_id=supplier.id,
            numero_fournisseur="FF-OK",
            date_facture=date(2025, 3, 6),
            date_reception_facture=date(2025, 3, 7),
            purchase_order_id=order.id,
            goods_receipt_id=receipt.id,
            lignes=[SupplierInvoiceLineCreate(
                purchase_order_line_id=po_line.id,
                goods_receipt_line_id=gr_line.id,
                designation="Article X", quantite=100, prix_unitaire_ht=1000,
                taux_tva=0.18, compte_achat="601000",
            )],
        ))
        match = await svc.rapprocher_3_voies(invoice.id)
        assert match.resultat == ResultatRapprochement.OK
        assert len(match.ecarts) == 0

    async def test_ecart_prix_faible_tolerance(
        self, db_session, tenant, admin_user, supplier, warehouse, plan_comptable_ci
    ):
        """Écart prix < 5% → ECART_PRIX (pas litige)."""
        order, po_line, receipt, gr_line = await self._setup_po_gr(
            db_session, tenant, admin_user, supplier, warehouse
        )
        svc = PurchaseService(db_session, tenant.id, admin_user.id)

        # Facture à 1030 au lieu de 1000 → écart 3%
        invoice = await svc.creer_facture(SupplierInvoiceCreate(
            supplier_id=supplier.id,
            numero_fournisseur="FF-ECART-FAIBLE",
            date_facture=date(2025, 3, 6),
            date_reception_facture=date(2025, 3, 7),
            purchase_order_id=order.id,
            goods_receipt_id=receipt.id,
            lignes=[SupplierInvoiceLineCreate(
                purchase_order_line_id=po_line.id,
                goods_receipt_line_id=gr_line.id,
                designation="Article X", quantite=100, prix_unitaire_ht=1030,
                taux_tva=0.18, compte_achat="601000",
            )],
        ))
        match = await svc.rapprocher_3_voies(invoice.id)
        assert match.resultat == ResultatRapprochement.ECART_PRIX
        assert len(match.ecarts) > 0

    async def test_ecart_prix_majeur_litige(
        self, db_session, tenant, admin_user, supplier, warehouse, plan_comptable_ci
    ):
        """Écart prix > 5% → LITIGE."""
        order, po_line, receipt, gr_line = await self._setup_po_gr(
            db_session, tenant, admin_user, supplier, warehouse
        )
        svc = PurchaseService(db_session, tenant.id, admin_user.id)

        # Facture à 1200 au lieu de 1000 → écart 20%
        invoice = await svc.creer_facture(SupplierInvoiceCreate(
            supplier_id=supplier.id,
            numero_fournisseur="FF-LITIGE",
            date_facture=date(2025, 3, 6),
            date_reception_facture=date(2025, 3, 7),
            purchase_order_id=order.id,
            goods_receipt_id=receipt.id,
            lignes=[SupplierInvoiceLineCreate(
                purchase_order_line_id=po_line.id,
                goods_receipt_line_id=gr_line.id,
                designation="Article X", quantite=100, prix_unitaire_ht=1200,
                taux_tva=0.18, compte_achat="601000",
            )],
        ))
        match = await svc.rapprocher_3_voies(invoice.id)
        assert match.resultat == ResultatRapprochement.LITIGE

        # Blocage à la validation
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            await svc.valider_facture(invoice.id)
        assert "litige" in str(exc.value.detail).lower()

    async def test_ecart_quantite(
        self, db_session, tenant, admin_user, supplier, warehouse, plan_comptable_ci
    ):
        """Facture 90 unités au lieu de 100 reçues → ECART_QUANTITE."""
        order, po_line, receipt, gr_line = await self._setup_po_gr(
            db_session, tenant, admin_user, supplier, warehouse
        )
        svc = PurchaseService(db_session, tenant.id, admin_user.id)

        invoice = await svc.creer_facture(SupplierInvoiceCreate(
            supplier_id=supplier.id,
            numero_fournisseur="FF-QTE",
            date_facture=date(2025, 3, 6),
            date_reception_facture=date(2025, 3, 7),
            purchase_order_id=order.id,
            goods_receipt_id=receipt.id,
            lignes=[SupplierInvoiceLineCreate(
                purchase_order_line_id=po_line.id,
                goods_receipt_line_id=gr_line.id,
                designation="Article X", quantite=90, prix_unitaire_ht=1000,
                taux_tva=0.18, compte_achat="601000",
            )],
        ))
        match = await svc.rapprocher_3_voies(invoice.id)
        assert match.resultat == ResultatRapprochement.ECART_QUANTITE

    async def test_sans_commande_achat_direct(
        self, db_session, tenant, admin_user, supplier, plan_comptable_ci
    ):
        """Facture sans PO ni GR → SANS_COMMANDE (achat direct)."""
        svc = PurchaseService(db_session, tenant.id, admin_user.id)

        invoice = await svc.creer_facture(SupplierInvoiceCreate(
            supplier_id=supplier.id,
            numero_fournisseur="FF-DIRECT",
            date_facture=date(2025, 3, 6),
            date_reception_facture=date(2025, 3, 7),
            lignes=[SupplierInvoiceLineCreate(
                designation="Fourniture bureau", quantite=10, prix_unitaire_ht=5000,
                taux_tva=0.18, compte_achat="605200",
            )],
        ))
        match = await svc.rapprocher_3_voies(invoice.id)
        assert match.resultat == ResultatRapprochement.SANS_COMMANDE


# ═════════════════════════════════════════════════════════════════════════════
# TESTS BALANCE ÂGÉE
# ═════════════════════════════════════════════════════════════════════════════
class TestBalanceAgee:
    async def test_balance_agee_tranches(
        self, db_session, tenant, admin_user, supplier, plan_comptable_ci
    ):
        svc = PurchaseService(db_session, tenant.id, admin_user.id)

        # Facture avec échéance dans le passé (60 jours de retard)
        invoice = await svc.creer_facture(SupplierInvoiceCreate(
            supplier_id=supplier.id,
            numero_fournisseur="FF-OLD",
            date_facture=date(2025, 1, 1),
            date_reception_facture=date(2025, 1, 1),
            date_echeance=date(2025, 1, 15),
            lignes=[SupplierInvoiceLineCreate(
                designation="Article", quantite=1, prix_unitaire_ht=100_000,
                taux_tva=0.18, compte_achat="601000",
            )],
        ))
        await svc.valider_facture(invoice.id)

        balance = await svc.balance_agee(date_arret=date(2025, 3, 15))
        assert balance.total_du > 0
        assert balance.total_31_60 > 0  # 60 jours de retard
        assert len(balance.fournisseurs) == 1
