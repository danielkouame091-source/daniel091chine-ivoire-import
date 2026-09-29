"""
Service Achats & Fournisseurs SYSCOHADA.

CYCLE COMPLET :
1. Fournisseur (création + mise à jour solde)
2. Commande fournisseur (PO) — validation
3. Réception (GR) — génère les entrées de stock (module Stocks)
4. Facture fournisseur (FF) — rapprochement 3 voies (PO=GR=FF)
5. Paiement — lettrage + mise à jour balance âgée

ÉCRITURES GÉNÉRÉES :
- Facture : Débit 60x (achat) + Débit 445x (TVA) / Crédit 401x (fournisseur)
- Paiement : Débit 401x (fournisseur) / Crédit 521x (banque)
- Escompte : Crédit 765x (escompte obtenu)
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.purchase_syscohada import (
    COMPTE_RAS_A_PAYER,
    COMPTE_TVA_RECUPERABLE,
    COMPTES_ACHATS,
    COMPTES_FOURNISSEURS,
    COMPTES_TRESORERIE_PAR_MODE,
    JOURNAL_ACHAT,
    JOURNAL_OD,
    RAS_TAUX_NON_RESIDENTS,
    RAS_TAUX_SERVICES_LOCAUX,
    ResultatRapprochement,
    StatutCommande,
    StatutFactureFournisseur,
    StatutPaiement,
    StatutReception,
)
from app.models.enums import EcritureSource
from app.models.purchase import (
    GoodsReceipt,
    GoodsReceiptLine,
    PurchaseOrder,
    PurchaseOrderLine,
    Supplier,
    SupplierInvoice,
    SupplierInvoiceLine,
    SupplierPayment,
)
from app.schemas.ecriture import EcritureCreate, LigneIn
from app.schemas.purchase import (
    BalanceAgeeLigne,
    BalanceAgeeOut,
    GoodsReceiptCreate,
    PurchaseOrderCreate,
    SupplierCreate,
    SupplierInvoiceCreate,
    SupplierPaymentCreate,
    SupplierUpdate,
    ThreeWayMatchOut,
)
from app.services.audit_service import AuditService
from app.services.journal_service import JournalService
from app.services.syscohada_service import SyscohadaService

logger = logging.getLogger(__name__)


class PurchaseService:
    def __init__(self, db: AsyncSession, tenant_id: UUID, user_id: UUID) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.audit = AuditService(db)

    # ═════════════════════════════════════════════════════════════════════
    # FOURNISSEURS
    # ═════════════════════════════════════════════════════════════════════
    async def creer_fournisseur(self, data: SupplierCreate) -> Supplier:
        existing = await self.db.scalar(
            select(Supplier.id).where(
                Supplier.tenant_id == self.tenant_id,
                Supplier.code == data.code,
            )
        )
        if existing:
            raise HTTPException(409, f"Code fournisseur {data.code} déjà utilisé")

        supplier = Supplier(
            tenant_id=self.tenant_id,
            **data.model_dump(),
        )
        self.db.add(supplier)
        await self.db.flush()
        await self.audit.log(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            action="SUPPLIER_CREATE",
            ressource="supplier",
            ressource_id=supplier.id,
            payload={"code": supplier.code, "raison_sociale": supplier.raison_sociale},
        )
        return supplier

    async def modifier_fournisseur(self, supplier_id: UUID, data: SupplierUpdate) -> Supplier:
        supplier = await self._get_supplier(supplier_id)
        for k, v in data.model_dump(exclude_unset=True).items():
            setattr(supplier, k, v)
        await self.db.flush()
        return supplier

    # ═════════════════════════════════════════════════════════════════════
    # COMMANDES FOURNISSEURS
    # ═════════════════════════════════════════════════════════════════════
    async def creer_commande(self, data: PurchaseOrderCreate) -> PurchaseOrder:
        supplier = await self._get_supplier(data.supplier_id)

        numero = await self._generer_numero("PO", data.date_commande)

        # Calcul des montants
        total_ht_brut = 0
        total_tva = 0
        lignes_db: list[PurchaseOrderLine] = []

        for i, l in enumerate(data.lignes, start=1):
            montant_ht_ligne = int(Decimal(str(l.quantite)) * Decimal(l.prix_unitaire_ht)) - l.remise_ligne
            montant_tva_ligne = int(Decimal(montant_ht_ligne) * Decimal(str(l.taux_tva)))
            montant_ttc_ligne = montant_ht_ligne + montant_tva_ligne

            total_ht_brut += montant_ht_ligne
            total_tva += montant_tva_ligne

            lignes_db.append(PurchaseOrderLine(
                tenant_id=self.tenant_id,
                ordre=i,
                item_id=l.item_id,
                designation=l.designation,
                unite=l.unite,
                quantite_commandee=Decimal(str(l.quantite)),
                quantite_recue=Decimal(0),
                quantite_facturee=Decimal(0),
                prix_unitaire_ht=l.prix_unitaire_ht,
                remise_ligne=l.remise_ligne,
                taux_tva=l.taux_tva,
                montant_ht=montant_ht_ligne,
                montant_tva=montant_tva_ligne,
                montant_ttc=montant_ttc_ligne,
                famille_stock=l.famille_stock,
                compte_achat=l.compte_achat,
            ))

        total_ht = total_ht_brut - data.remise_globale
        total_ttc = total_ht + total_tva

        order = PurchaseOrder(
            tenant_id=self.tenant_id,
            supplier_id=supplier.id,
            numero=numero,
            date_commande=data.date_commande,
            date_livraison_prevue=data.date_livraison_prevue,
            statut=StatutCommande.BROUILLON,
            total_ht=total_ht,
            total_tva=total_tva,
            total_ttc=total_ttc,
            remise_globale=data.remise_globale,
            adresse_livraison=data.adresse_livraison,
            warehouse_destination_id=data.warehouse_destination_id,
            reference_interne=data.reference_interne,
            notes=data.notes,
            created_by=self.user_id,
        )
        self.db.add(order)
        await self.db.flush()

        for ligne in lignes_db:
            ligne.order_id = order.id
            self.db.add(ligne)
        await self.db.flush()

        await self.audit.log(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            action="PO_CREATE",
            ressource="purchase_order",
            ressource_id=order.id,
            payload={"numero": numero, "total_ht": total_ht},
        )
        return order

    async def valider_commande(self, order_id: UUID) -> PurchaseOrder:
        order = await self._get_order(order_id)
        if order.statut != StatutCommande.BROUILLON:
            raise HTTPException(400, f"Commande déjà {order.statut}")

        order.statut = StatutCommande.VALIDEE
        order.validee_at = datetime.now(timezone.utc)
        order.validee_par = self.user_id

        # Mettre à jour l'encours commandes du fournisseur
        supplier = await self._get_supplier(order.supplier_id)
        supplier.encours_commandes += order.total_ht
        await self.db.flush()

        await self.audit.log(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            action="PO_VALIDATE",
            ressource="purchase_order",
            ressource_id=order.id,
        )
        return order

    # ═════════════════════════════════════════════════════════════════════
    # RÉCEPTIONS
    # ═════════════════════════════════════════════════════════════════════
    async def creer_reception(
        self, data: GoodsReceiptCreate, comptabiliser_stock: bool = True
    ) -> GoodsReceipt:
        """
        Crée un bon de réception.
        Si creer_mouvements_stock=True, génère les entrées de stock (module Stocks).
        """
        supplier = await self._get_supplier(data.supplier_id)
        numero = await self._generer_numero("GR", data.date_reception)

        # Vérifier commande si fournie
        order: PurchaseOrder | None = None
        order_lines_map: dict[UUID, PurchaseOrderLine] = {}
        if data.purchase_order_id:
            order = await self._get_order(data.purchase_order_id)
            if order.supplier_id != supplier.id:
                raise HTTPException(400, "La commande n'appartient pas à ce fournisseur")
            if order.statut not in (StatutCommande.VALIDEE, StatutCommande.PARTIELLEMENT_RECUE):
                raise HTTPException(400, f"Commande en statut {order.statut} — non réceptionnable")

            order_lines = (
                await self.db.execute(
                    select(PurchaseOrderLine).where(PurchaseOrderLine.order_id == order.id)
                )
            ).scalars().all()
            order_lines_map = {l.id: l for l in order_lines}

        receipt = GoodsReceipt(
            tenant_id=self.tenant_id,
            supplier_id=supplier.id,
            purchase_order_id=data.purchase_order_id,
            warehouse_id=data.warehouse_id,
            numero=numero,
            date_reception=data.date_reception,
            numero_bl_fournisseur=data.numero_bl_fournisseur,
            statut=StatutReception.BROUILLON,
            notes=data.notes,
            created_by=self.user_id,
        )
        self.db.add(receipt)
        await self.db.flush()

        total_ht = 0
        mouvements_ids: list[str] = []

        for i, l in enumerate(data.lignes, start=1):
            montant_ht = int(Decimal(str(l.quantite_recue)) * Decimal(l.prix_unitaire_ht))
            total_ht += montant_ht

            # Quantité commandée d'origine (si lien PO)
            qte_commandee = Decimal(0)
            if l.purchase_order_line_id and l.purchase_order_line_id in order_lines_map:
                qte_commandee = order_lines_map[l.purchase_order_line_id].quantite_commandee

            gr_line = GoodsReceiptLine(
                receipt_id=receipt.id,
                tenant_id=self.tenant_id,
                purchase_order_line_id=l.purchase_order_line_id,
                item_id=l.item_id,
                ordre=i,
                designation=l.designation,
                quantite_commandee=qte_commandee,
                quantite_recue=Decimal(str(l.quantite_recue)),
                quantite_refusee=Decimal(str(l.quantite_refusee)),
                prix_unitaire_ht=l.prix_unitaire_ht,
                montant_ht=montant_ht,
                famille_stock=l.famille_stock,
                motif_refus=l.motif_refus,
            )
            self.db.add(gr_line)
            await self.db.flush()

            # Créer le mouvement de stock (brique 15)
            if (
                comptabiliser_stock
                and data.creer_mouvements_stock
                and l.item_id
                and l.quantite_recue > 0
            ):
                try:
                    from app.schemas.stock import MouvementEntreeCreate
                    from app.services.stock_service import StockService

                    stock_svc = StockService(self.db, self.tenant_id, self.user_id)
                    mv = await stock_svc.entree_stock(
                        MouvementEntreeCreate(
                            item_id=l.item_id,
                            warehouse_id=data.warehouse_id,
                            date_mouvement=data.date_reception,
                            quantite=float(l.quantite_recue),
                            prix_unitaire=l.prix_unitaire_ht,
                            libelle=f"Réception {numero} — {l.designation}",
                            reference_piece=data.numero_bl_fournisseur or numero,
                            type_mouvement="entree_achat",
                        ),
                        comptabiliser=False,  # Écriture gérée par la facture
                    )
                    gr_line.mouvement_stock_id = mv.id
                    mouvements_ids.append(str(mv.id))
                except Exception as exc:
                    logger.exception(f"[purchase] Échec création mouvement stock ligne {i}")
                    raise HTTPException(500, f"Erreur création mouvement stock : {exc}")

            # Mettre à jour la quantité reçue sur la ligne de commande
            if l.purchase_order_line_id and l.purchase_order_line_id in order_lines_map:
                pol = order_lines_map[l.purchase_order_line_id]
                pol.quantite_recue = Decimal(str(pol.quantite_recue)) + Decimal(str(l.quantite_recue))

        receipt.total_ht = total_ht
        receipt.mouvements_stock_ids = mouvements_ids

        # Mettre à jour le statut de la commande
        if order:
            all_lines = order_lines_map.values()
            tout_recu = all(
                Decimal(str(l.quantite_recue)) >= Decimal(str(l.quantite_commandee))
                for l in all_lines
            )
            partiel = any(Decimal(str(l.quantite_recue)) > 0 for l in all_lines)
            if tout_recu:
                order.statut = StatutCommande.RECUE
                supplier.encours_commandes = max(
                    0, supplier.encours_commandes - order.total_ht
                )
            elif partiel:
                order.statut = StatutCommande.PARTIELLEMENT_RECUE

        await self.db.flush()
        await self.audit.log(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            action="GR_CREATE",
            ressource="goods_receipt",
            ressource_id=receipt.id,
            payload={"numero": numero, "total_ht": total_ht, "nb_mouvements": len(mouvements_ids)},
        )
        return receipt

    async def valider_reception(self, receipt_id: UUID) -> GoodsReceipt:
        receipt = await self._get_receipt(receipt_id)
        if receipt.statut != StatutReception.BROUILLON:
            raise HTTPException(400, f"Réception déjà {receipt.statut}")
        receipt.statut = StatutReception.VALIDEE
        receipt.validee_at = datetime.now(timezone.utc)
        receipt.validee_par = self.user_id
        await self.db.flush()
        return receipt

    # ═════════════════════════════════════════════════════════════════════
    # FACTURE FOURNISSEUR
    # ═════════════════════════════════════════════════════════════════════
    async def creer_facture(
        self, data: SupplierInvoiceCreate, comptabiliser: bool = True
    ) -> SupplierInvoice:
        """
        Crée une facture fournisseur.
        Effectue le rapprochement 3 voies si PO + GR fournis.
        Génère l'écriture comptable si comptabiliser=True.
        """
        supplier = await self._get_supplier(data.supplier_id)

        # Unicité du numéro fournisseur
        existing = await self.db.scalar(
            select(SupplierInvoice.id).where(
                SupplierInvoice.tenant_id == self.tenant_id,
                SupplierInvoice.supplier_id == supplier.id,
                SupplierInvoice.numero_fournisseur == data.numero_fournisseur,
            )
        )
        if existing:
            raise HTTPException(409, f"Facture {data.numero_fournisseur} déjà enregistrée")

        numero_interne = await self._generer_numero("FF", data.date_facture)
        date_echeance = data.date_echeance or (
            data.date_facture + timedelta(days=supplier.delai_paiement_jours)
        )

        # Calcul des montants
        total_ht = 0
        total_tva = 0
        lignes_db: list[SupplierInvoiceLine] = []

        for i, l in enumerate(data.lignes, start=1):
            montant_ht_ligne = int(Decimal(str(l.quantite)) * Decimal(l.prix_unitaire_ht)) - l.remise_ligne
            montant_tva_ligne = int(Decimal(montant_ht_ligne) * Decimal(str(l.taux_tva)))
            montant_ttc_ligne = montant_ht_ligne + montant_tva_ligne

            total_ht += montant_ht_ligne
            total_tva += montant_tva_ligne

            lignes_db.append(SupplierInvoiceLine(
                tenant_id=self.tenant_id,
                ordre=i,
                purchase_order_line_id=l.purchase_order_line_id,
                goods_receipt_line_id=l.goods_receipt_line_id,
                item_id=l.item_id,
                designation=l.designation,
                unite=l.unite,
                quantite=Decimal(str(l.quantite)),
                prix_unitaire_ht=l.prix_unitaire_ht,
                remise_ligne=l.remise_ligne,
                taux_tva=l.taux_tva,
                montant_ht=montant_ht_ligne,
                montant_tva=montant_tva_ligne,
                montant_ttc=montant_ttc_ligne,
                compte_achat=l.compte_achat,
                famille_stock=l.famille_stock,
            ))

        base_ht = total_ht - data.remise_globale
        total_ttc = base_ht + total_tva

        # Retenue à la source
        ras_appliquee = 0
        if data.appliquer_ras and supplier.soumis_ras:
            taux_ras = supplier.taux_ras or (
                RAS_TAUX_NON_RESIDENTS if not supplier.est_resident else RAS_TAUX_SERVICES_LOCAUX
            )
            ras_appliquee = int(Decimal(base_ht) * Decimal(str(taux_ras)))

        montant_net_a_payer = total_ttc - ras_appliquee

        invoice = SupplierInvoice(
            tenant_id=self.tenant_id,
            supplier_id=supplier.id,
            numero_fournisseur=data.numero_fournisseur,
            numero_interne=numero_interne,
            date_facture=data.date_facture,
            date_echeance=date_echeance,
            date_reception_facture=data.date_reception_facture,
            purchase_order_id=data.purchase_order_id,
            goods_receipt_id=data.goods_receipt_id,
            statut=StatutFactureFournisseur.BROUILLON,
            total_ht=total_ht,
            remise_globale=data.remise_globale,
            base_ht=base_ht,
            total_tva=total_tva,
            total_ttc=total_ttc,
            ras_appliquee=ras_appliquee,
            montant_net_a_payer=montant_net_a_payer,
            montant_paye=0,
            solde_du=montant_net_a_payer,
            notes=data.notes,
            created_by=self.user_id,
        )
        self.db.add(invoice)
        await self.db.flush()

        for ligne in lignes_db:
            ligne.invoice_id = invoice.id
            self.db.add(ligne)
        await self.db.flush()

        # Rapprochement 3 voies
        match = await self.rapprocher_3_voies(invoice.id)
        invoice.rapprochement_resultat = match.resultat
        invoice.rapprochement_detail = {
            "ecarts": match.ecarts,
            "total_po_ht": match.total_po_ht,
            "total_gr_ht": match.total_gr_ht,
            "total_invoice_ht": match.total_invoice_ht,
        }

        # Écriture comptable
        if comptabiliser:
            ecriture_id = await self._generer_ecriture_facture(invoice, supplier)
            invoice.ecriture_id = ecriture_id

        await self.db.flush()
        await self.audit.log(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            action="SUPPLIER_INVOICE_CREATE",
            ressource="supplier_invoice",
            ressource_id=invoice.id,
            payload={
                "numero_interne": numero_interne,
                "total_ttc": total_ttc,
                "ras": ras_appliquee,
                "rapprochement": match.resultat,
            },
        )
        return invoice

    async def valider_facture(self, invoice_id: UUID) -> SupplierInvoice:
        invoice = await self._get_invoice(invoice_id)
        if invoice.statut != StatutFactureFournisseur.BROUILLON:
            raise HTTPException(400, f"Facture déjà {invoice.statut}")

        # Blocage si rapprochement en litige
        if invoice.rapprochement_resultat in (ResultatRapprochement.LITIGE,):
            raise HTTPException(
                400,
                "Facture en litige — résoudre les écarts avant validation",
            )

        invoice.statut = StatutFactureFournisseur.VALIDEE
        invoice.validee_at = datetime.now(timezone.utc)
        invoice.validee_par = self.user_id

        # Mise à jour du solde fournisseur
        supplier = await self._get_supplier(invoice.supplier_id)
        supplier.solde_comptable += invoice.solde_du

        # Marquer la commande comme facturée
        if invoice.purchase_order_id:
            order = await self._get_order(invoice.purchase_order_id)
            order.statut = StatutCommande.FACTUREE

        await self.db.flush()
        return invoice

    # ═════════════════════════════════════════════════════════════════════
    # PAIEMENT
    # ═════════════════════════════════════════════════════════════════════
    async def payer_facture(
        self, data: SupplierPaymentCreate, comptabiliser: bool = True
    ) -> SupplierPayment:
        invoice = await self._get_invoice(data.invoice_id)
        if invoice.statut in (StatutFactureFournisseur.ANNULEE, StatutFactureFournisseur.EN_LITIGE):
            raise HTTPException(400, f"Facture {invoice.statut} — non payable")

        if data.montant <= 0:
            raise HTTPException(400, "Montant doit être > 0")
        if data.montant + data.escompte_obtenu > invoice.solde_du:
            raise HTTPException(
                400,
                f"Montant ({data.montant + data.escompte_obtenu}) > solde dû ({invoice.solde_du})",
            )

        supplier = await self._get_supplier(invoice.supplier_id)
        compte_tresorerie = COMPTES_TRESORERIE_PAR_MODE.get(data.mode_paiement, "521000")
        numero = await self._generer_numero("PAY", data.date_paiement)

        payment = SupplierPayment(
            tenant_id=self.tenant_id,
            supplier_id=supplier.id,
            invoice_id=invoice.id,
            numero=numero,
            date_paiement=data.date_paiement,
            montant=data.montant,
            mode_paiement=data.mode_paiement,
            compte_tresorerie=compte_tresorerie,
            reference_paiement=data.reference_paiement,
            statut=StatutPaiement.BROUILLON,
            escompte_obtenu=data.escompte_obtenu,
            created_by=self.user_id,
        )
        self.db.add(payment)
        await self.db.flush()

        # Mise à jour de la facture
        invoice.montant_paye += data.montant + data.escompte_obtenu
        invoice.solde_du = invoice.montant_net_a_payer - invoice.montant_paye
        if invoice.solde_du <= 0:
            invoice.statut = StatutFactureFournisseur.PAYEE
            invoice.solde_du = 0
        else:
            invoice.statut = StatutFactureFournisseur.PARTIELLEMENT_PAYEE

        # Solde fournisseur
        supplier.solde_comptable = max(
            0, supplier.solde_comptable - data.montant - data.escompte_obtenu
        )

        # Écriture comptable
        if comptabiliser:
            ecriture_id = await self._generer_ecriture_paiement(payment, supplier)
            payment.ecriture_id = ecriture_id
            payment.statut = StatutPaiement.VALIDE

        await self.db.flush()
        await self.audit.log(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            action="SUPPLIER_PAYMENT",
            ressource="supplier_payment",
            ressource_id=payment.id,
            payload={
                "numero": numero,
                "montant": data.montant,
                "mode": data.mode_paiement,
                "solde_restant": invoice.solde_du,
            },
        )
        return payment

    # ═════════════════════════════════════════════════════════════════════
    # RAPPROCHEMENT 3 VOIES
    # ═════════════════════════════════════════════════════════════════════
    async def rapprocher_3_voies(self, invoice_id: UUID) -> ThreeWayMatchOut:
        """
        Compare Commande (PO) = Réception (GR) = Facture (FF).

        Règles :
        - Si pas de PO et pas de GR → résultat SANS_COMMANDE (achat direct)
        - Si PO mais pas de GR → SANS_RECEPTION (prestation de service)
        - Si PO + GR + FF → comparaison ligne par ligne :
          - écart prix (PU facture ≠ PU commande)
          - écart quantité (qté facturée ≠ qté reçue)
        - Écart < 5% toléré : OK avec mention
        - Écart ≥ 5% : LITIGE
        """
        invoice = await self._get_invoice(invoice_id)
        lines = (
            await self.db.execute(
                select(SupplierInvoiceLine)
                .where(SupplierInvoiceLine.invoice_id == invoice_id)
                .order_by(SupplierInvoiceLine.ordre)
            )
        ).scalars().all()

        ecarts: list[dict[str, Any]] = []
        total_po_ht: int | None = None
        total_gr_ht: int | None = None
        total_invoice_ht = sum(int(l.montant_ht) for l in lines)
        ecart_prix_total = 0
        ecart_qte_total = 0.0

        # Cas 1 : ni PO ni GR
        if not invoice.purchase_order_id and not invoice.goods_receipt_id:
            return ThreeWayMatchOut(
                invoice_id=invoice_id,
                purchase_order_id=None,
                goods_receipt_id=None,
                resultat=ResultatRapprochement.SANS_COMMANDE,
                ecarts=[{"type": "sans_commande", "message": "Achat direct sans PO ni GR"}],
                total_po_ht=None,
                total_gr_ht=None,
                total_invoice_ht=total_invoice_ht,
                ecart_prix_total=0,
                ecart_quantite_total=0,
            )

        # Cas 2 : PO mais pas de GR → prestation
        if invoice.purchase_order_id and not invoice.goods_receipt_id:
            order = await self._get_order(invoice.purchase_order_id)
            total_po_ht = order.total_ht
            return ThreeWayMatchOut(
                invoice_id=invoice_id,
                purchase_order_id=order.id,
                goods_receipt_id=None,
                resultat=ResultatRapprochement.SANS_RECEPTION,
                ecarts=[],
                total_po_ht=total_po_ht,
                total_gr_ht=None,
                total_invoice_ht=total_invoice_ht,
                ecart_prix_total=0,
                ecart_quantite_total=0,
            )

        # Cas 3 : PO + GR + FF → comparaison complète
        order = await self._get_order(invoice.purchase_order_id) if invoice.purchase_order_id else None
        receipt = await self._get_receipt(invoice.goods_receipt_id) if invoice.goods_receipt_id else None

        if order:
            total_po_ht = order.total_ht
        if receipt:
            total_gr_ht = receipt.total_ht

        # Charger les lignes de PO et GR
        po_lines = {}
        if order:
            po_lignes = (
                await self.db.execute(
                    select(PurchaseOrderLine).where(PurchaseOrderLine.order_id == order.id)
                )
            ).scalars().all()
            po_lines = {l.id: l for l in po_lignes}

        gr_lines = {}
        if receipt:
            gr_lignes = (
                await self.db.execute(
                    select(GoodsReceiptLine).where(GoodsReceiptLine.receipt_id == receipt.id)
                )
            ).scalars().all()
            gr_lines = {l.id: l for l in gr_lignes}

        # Comparaison ligne par ligne
        for line in lines:
            # Écart prix
            if line.purchase_order_line_id and line.purchase_order_line_id in po_lines:
                po_line = po_lines[line.purchase_order_line_id]
                if line.prix_unitaire_ht != po_line.prix_unitaire_ht:
                    ecart_prix = int(line.prix_unitaire_ht - po_line.prix_unitaire_ht)
                    ecart_pct = abs(ecart_prix) / po_line.prix_unitaire_ht * 100 if po_line.prix_unitaire_ht else 0
                    ecarts.append({
                        "type": "ecart_prix",
                        "line_id": str(line.id),
                        "designation": line.designation,
                        "prix_commande": po_line.prix_unitaire_ht,
                        "prix_facture": line.prix_unitaire_ht,
                        "ecart": ecart_prix,
                        "ecart_pct": round(ecart_pct, 2),
                    })
                    ecart_prix_total += ecart_prix * int(line.quantite)

            # Écart quantité (FF vs GR)
            if line.goods_receipt_line_id and line.goods_receipt_line_id in gr_lines:
                gr_line = gr_lines[line.goods_receipt_line_id]
                qte_ecart = float(line.quantite) - float(gr_line.quantite_recue)
                if abs(qte_ecart) > 0.001:
                    ecarts.append({
                        "type": "ecart_quantite",
                        "line_id": str(line.id),
                        "designation": line.designation,
                        "qte_recue": float(gr_line.quantite_recue),
                        "qte_facturee": float(line.quantite),
                        "ecart": qte_ecart,
                    })
                    ecart_qte_total += qte_ecart

        # Détermination du résultat
        if not ecarts:
            resultat = ResultatRapprochement.OK
        else:
            # Tolérance 5%
            ecarts_majeurs = [
                e for e in ecarts
                if e["type"] == "ecart_prix" and e.get("ecart_pct", 0) >= 5
            ]
            if ecarts_majeurs:
                resultat = ResultatRapprochement.LITIGE
            elif any(e["type"] == "ecart_prix" for e in ecarts):
                resultat = ResultatRapprochement.ECART_PRIX
            elif any(e["type"] == "ecart_quantite" for e in ecarts):
                resultat = ResultatRapprochement.ECART_QUANTITE
            else:
                resultat = ResultatRapprochement.OK

        return ThreeWayMatchOut(
            invoice_id=invoice_id,
            purchase_order_id=order.id if order else None,
            goods_receipt_id=receipt.id if receipt else None,
            resultat=resultat,
            ecarts=ecarts,
            total_po_ht=total_po_ht,
            total_gr_ht=total_gr_ht,
            total_invoice_ht=total_invoice_ht,
            ecart_prix_total=ecart_prix_total,
            ecart_quantite_total=ecart_qte_total,
        )

    # ═════════════════════════════════════════════════════════════════════
    # BALANCE ÂGÉE FOURNISSEURS
    # ═════════════════════════════════════════════════════════════════════
    async def balance_agee(
        self, date_arret: date | None = None
    ) -> BalanceAgeeOut:
        """
        Balance âgée des factures fournisseurs non payées.
        Tranches : non échu, 0-30j, 31-60j, 61-90j, >90j.
        """
        date_arret = date_arret or date.today()

        invoices = (
            await self.db.execute(
                select(SupplierInvoice)
                .where(
                    SupplierInvoice.tenant_id == self.tenant_id,
                    SupplierInvoice.statut.in_([
                        StatutFactureFournisseur.VALIDEE,
                        StatutFactureFournisseur.PARTIELLEMENT_PAYEE,
                    ]),
                    SupplierInvoice.solde_du > 0,
                )
            )
        ).scalars().all()

        # Agréger par fournisseur
        par_fournisseur: dict[UUID, dict[str, Any]] = {}

        for inv in invoices:
            sid = inv.supplier_id
            if sid not in par_fournisseur:
                supplier = await self._get_supplier(sid)
                par_fournisseur[sid] = {
                    "supplier_id": sid,
                    "code": supplier.code,
                    "raison_sociale": supplier.raison_sociale,
                    "total_du": 0,
                    "non_echu": 0,
                    "tranche_0_30": 0,
                    "tranche_31_60": 0,
                    "tranche_61_90": 0,
                    "tranche_90_plus": 0,
                    "nb_factures": 0,
                    "plus_ancienne_echeance": None,
                }

            f = par_fournisseur[sid]
            f["total_du"] += inv.solde_du
            f["nb_factures"] += 1

            # Tranche
            jours_retard = (date_arret - inv.date_echeance).days

            if jours_retard < 0:
                f["non_echu"] += inv.solde_du
            elif jours_retard <= 30:
                f["tranche_0_30"] += inv.solde_du
            elif jours_retard <= 60:
                f["tranche_31_60"] += inv.solde_du
            elif jours_retard <= 90:
                f["tranche_61_90"] += inv.solde_du
            else:
                f["tranche_90_plus"] += inv.solde_du

            # Plus ancienne échéance
            if f["plus_ancienne_echeance"] is None or inv.date_echeance < f["plus_ancienne_echeance"]:
                f["plus_ancienne_echeance"] = inv.date_echeance

        # Totaux globaux
        lignes = [BalanceAgeeLigne(**f) for f in par_fournisseur.values()]
        return BalanceAgeeOut(
            tenant_id=self.tenant_id,
            date_arret=date_arret,
            total_du=sum(l.total_du for l in lignes),
            total_non_echu=sum(l.non_echu for l in lignes),
            total_0_30=sum(l.tranche_0_30 for l in lignes),
            total_31_60=sum(l.tranche_31_60 for l in lignes),
            total_61_90=sum(l.tranche_61_90 for l in lignes),
            total_90_plus=sum(l.tranche_90_plus for l in lignes),
            fournisseurs=lignes,
        )

    # ═════════════════════════════════════════════════════════════════════
    # ÉCRITURES SYSCOHADA
    # ═════════════════════════════════════════════════════════════════════
    async def _generer_ecriture_facture(
        self, invoice: SupplierInvoice, supplier: Supplier
    ) -> UUID:
        """
        Écriture de facture fournisseur :
          Débit 60x (Achats)           base_ht
          Débit 445x (TVA récupérable) total_tva
          Crédit 401x (Fournisseur)    total_ttc
          [Crédit 447x (RAS)]          ras_appliquee
          [Crédit 409x (RRR)]          remise_globale
        """
        lignes: list[LigneIn] = []

        # Lignes d'achats (regroupées par compte)
        achats_par_compte: dict[str, int] = {}
        inv_lines = (
            await self.db.execute(
                select(SupplierInvoiceLine).where(SupplierInvoiceLine.invoice_id == invoice.id)
            )
        ).scalars().all()
        for il in inv_lines:
            achats_par_compte[il.compte_achat] = (
                achats_par_compte.get(il.compte_achat, 0) + int(il.montant_ht)
            )

        # Remise globale : répartie au prorata (simplifié : sur le 1er compte)
        for compte, montant in achats_par_compte.items():
            if montant == 0:
                continue
            lignes.append(LigneIn(
                compte=compte,
                libelle=f"Facture {invoice.numero_fournisseur} — achat",
                debit=montant,
            ))

        # Débit TVA (uniquement si fournisseur assujetti)
        if invoice.total_tva > 0 and supplier.assujetti_tva:
            lignes.append(LigneIn(
                compte=COMPTE_TVA_RECUPERABLE,
                libelle=f"TVA récupérable {invoice.numero_fournisseur}",
                debit=invoice.total_tva,
            ))

        # Crédit fournisseur (montant TTC net de RAS)
        credit_fournisseur = invoice.total_ttc - invoice.ras_appliquee
        # Remise globale déjà déduite de base_ht mais pas du crédit fournisseur TTC
        # Ajustement : si remise_globale, elle s'applique aussi au TTC
        if invoice.remise_globale > 0:
            # La remise HT a été déduite de base_ht, il faut aussi ajuster le crédit
            # (les lignes d'achat sont enregistrées au total_ht BRUT)
            pass

        lignes.append(LigneIn(
            compte=COMPTES_FOURNISSEURS[supplier.type_fournisseur].compte,
            libelle=f"Facture {invoice.numero_fournisseur}",
            credit=credit_fournisseur,
        ))

        # RAS
        if invoice.ras_appliquee > 0:
            lignes.append(LigneIn(
                compte=COMPTE_RAS_A_PAYER,
                libelle=f"RAS {invoice.numero_fournisseur}",
                credit=invoice.ras_appliquee,
            ))

        # Équilibrage si remise globale
        td = sum(l.debit for l in lignes)
        tc = sum(l.credit for l in lignes)
        if td != tc:
            # Ajuster le premier compte d'achat
            diff = td - tc
            for ligne in lignes:
                if ligne.compte.startswith("60"):
                    ligne.debit -= diff
                    break

        try:
            await JournalService(self.db, self.tenant_id).get_by_code(JOURNAL_ACHAT)
            journal_code = JOURNAL_ACHAT
        except Exception:
            journal_code = "OD"

        syscohada = SyscohadaService(self.db, self.tenant_id, self.user_id)
        e = await syscohada.create(EcritureCreate(
            numero_piece=invoice.numero_interne,
            date_ecriture=invoice.date_facture,
            code_journal=journal_code,
            libelle=f"Facture fournisseur {invoice.numero_fournisseur}",
            reference_ext=invoice.numero_fournisseur,
            source=EcritureSource.SYSTEME,
            lignes=lignes,
        ))
        return e.id

    async def _generer_ecriture_paiement(
        self, payment: SupplierPayment, supplier: Supplier
    ) -> UUID:
        """
        Écriture de paiement fournisseur :
          Débit 401x (Fournisseur)         montant + escompte
          Crédit 521x (Banque/Trésorerie)  montant
          Crédit 765x (Escompte obtenu)    escompte
        """
        lignes = [
            LigneIn(
                compte=COMPTES_FOURNISSEURS[supplier.type_fournisseur].compte,
                libelle=f"Règlement facture {payment.invoice_id}",
                debit=payment.montant + payment.escompte_obtenu,
            ),
            LigneIn(
                compte=payment.compte_tresorerie,
                libelle=f"Paiement fournisseur {payment.reference_paiement or payment.numero}",
                credit=payment.montant,
            ),
        ]
        if payment.escompte_obtenu > 0:
            lignes.append(LigneIn(
                compte="765000",
                libelle="Escompte obtenu",
                credit=payment.escompte_obtenu,
            ))

        try:
            await JournalService(self.db, self.tenant_id).get_by_code(JOURNAL_ACHAT)
            journal_code = JOURNAL_ACHAT
        except Exception:
            journal_code = "OD"

        syscohada = SyscohadaService(self.db, self.tenant_id, self.user_id)
        e = await syscohada.create(EcritureCreate(
            numero_piece=payment.numero,
            date_ecriture=payment.date_paiement,
            code_journal=journal_code,
            libelle=f"Règlement fournisseur {supplier.raison_sociale}",
            reference_ext=payment.reference_paiement,
            source=EcritureSource.SYSTEME,
            lignes=lignes,
        ))
        return e.id

    # ═════════════════════════════════════════════════════════════════════
    # HELPERS
    # ═════════════════════════════════════════════════════════════════════
    async def _get_supplier(self, supplier_id: UUID) -> Supplier:
        sup = await self.db.scalar(
            select(Supplier).where(
                Supplier.id == supplier_id,
                Supplier.tenant_id == self.tenant_id,
            )
        )
        if sup is None:
            raise HTTPException(404, "Fournisseur introuvable")
        return sup

    async def _get_order(self, order_id: UUID) -> PurchaseOrder:
        o = await self.db.scalar(
            select(PurchaseOrder).where(
                PurchaseOrder.id == order_id,
                PurchaseOrder.tenant_id == self.tenant_id,
            )
        )
        if o is None:
            raise HTTPException(404, "Commande introuvable")
        return o

    async def _get_receipt(self, receipt_id: UUID) -> GoodsReceipt:
        r = await self.db.scalar(
            select(GoodsReceipt).where(
                GoodsReceipt.id == receipt_id,
                GoodsReceipt.tenant_id == self.tenant_id,
            )
        )
        if r is None:
            raise HTTPException(404, "Réception introuvable")
        return r

    async def _get_invoice(self, invoice_id: UUID) -> SupplierInvoice:
        i = await self.db.scalar(
            select(SupplierInvoice).where(
                SupplierInvoice.id == invoice_id,
                SupplierInvoice.tenant_id == self.tenant_id,
            )
        )
        if i is None:
            raise HTTPException(404, "Facture fournisseur introuvable")
        return i

    async def _generer_numero(self, prefixe: str, d: date) -> str:
        annee = d.year
        pattern = f"{prefixe}-{annee}-%"
        # Compter par table selon préfixe
        count_stmt = None
        if prefixe == "PO":
            count_stmt = select(func.count(PurchaseOrder.id)).where(
                PurchaseOrder.tenant_id == self.tenant_id,
                PurchaseOrder.numero.like(pattern),
            )
        elif prefixe == "GR":
            count_stmt = select(func.count(GoodsReceipt.id)).where(
                GoodsReceipt.tenant_id == self.tenant_id,
                GoodsReceipt.numero.like(pattern),
            )
        elif prefixe == "FF":
            count_stmt = select(func.count(SupplierInvoice.id)).where(
                SupplierInvoice.tenant_id == self.tenant_id,
                SupplierInvoice.numero_interne.like(pattern),
            )
        elif prefixe == "PAY":
            count_stmt = select(func.count(SupplierPayment.id)).where(
                SupplierPayment.tenant_id == self.tenant_id,
                SupplierPayment.numero.like(pattern),
            )
        count = int(await self.db.scalar(count_stmt) or 0) if count_stmt is not None else 0
        return f"{prefixe}-{annee}-{count + 1:05d}"
