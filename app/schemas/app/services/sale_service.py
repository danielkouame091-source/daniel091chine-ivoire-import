"""
Service Ventes & Clients SYSCOHADA.

CYCLE COMPLET :
1. Client (création + vérification plafond crédit)
2. Devis (facultatif) → conversion en commande
3. Commande client → confirmation
4. Bon de livraison (BL) → sortie de stock automatique
5. Facture client → écriture SYSCOHADA + mise à jour solde
6. Encaissement → lettrage + produit trésorerie
7. Avoir → écriture inverse + réintégration stock

RELANCES AUTOMATIQUES :
- J+3  : aimable
- J+15 : ferme
- J+30 : mise en demeure
- J+60 : contentieux
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

from app.core.sale_syscohada import (
    COMPTE_TVA_COLLECTEE,
    COMPTES_CLIENTS,
    COMPTES_PRODUITS,
    COMPTES_TRESORERIE_PAR_MODE,
    JOURNAL_AVOIR,
    JOURNAL_OD,
    JOURNAL_VENTE,
    NiveauRelance,
    StatutBL,
    StatutCommandeClient,
    StatutDevis,
    StatutEncaissement,
    StatutFactureClient,
    niveau_relance_pour,
)
from app.models.enums import EcritureSource
from app.models.sale import (
    CreditNote,
    CreditNoteLine,
    Customer,
    CustomerInvoice,
    CustomerInvoiceLine,
    CustomerPayment,
    DeliveryNote,
    DeliveryNoteLine,
    Quote,
    QuoteLine,
    SalesOrder,
    SalesOrderLine,
)
from app.schemas.ecriture import EcritureCreate, LigneIn
from app.schemas.sale import (
    BalanceAgeeClientLigne,
    BalanceAgeeClientOut,
    CreditNoteCreate,
    CustomerCreate,
    CustomerInvoiceCreate,
    CustomerPaymentCreate,
    CustomerUpdate,
    DeliveryNoteCreate,
    QuoteCreate,
    RelancePreviewOut,
    RelanceResultOut,
    SalesOrderCreate,
)
from app.services.audit_service import AuditService
from app.services.journal_service import JournalService
from app.services.syscohada_service import SyscohadaService

logger = logging.getLogger(__name__)


class SaleService:
    def __init__(self, db: AsyncSession, tenant_id: UUID, user_id: UUID) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.audit = AuditService(db)

    # ═════════════════════════════════════════════════════════════════════
    # CLIENTS
    # ═════════════════════════════════════════════════════════════════════
    async def creer_client(self, data: CustomerCreate) -> Customer:
        existing = await self.db.scalar(
            select(Customer.id).where(
                Customer.tenant_id == self.tenant_id,
                Customer.code == data.code,
            )
        )
        if existing:
            raise HTTPException(409, f"Code client {data.code} déjà utilisé")

        customer = Customer(tenant_id=self.tenant_id, **data.model_dump())
        self.db.add(customer)
        await self.db.flush()
        await self.audit.log(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            action="CUSTOMER_CREATE",
            ressource="customer",
            ressource_id=customer.id,
            payload={"code": customer.code, "raison_sociale": customer.raison_sociale},
        )
        return customer

    async def modifier_client(self, customer_id: UUID, data: CustomerUpdate) -> Customer:
        customer = await self._get_customer(customer_id)
        for k, v in data.model_dump(exclude_unset=True).items():
            setattr(customer, k, v)
        await self.db.flush()
        return customer

    # ═════════════════════════════════════════════════════════════════════
    # DEVIS
    # ═════════════════════════════════════════════════════════════════════
    async def creer_devis(self, data: QuoteCreate) -> Quote:
        await self._get_customer(data.customer_id)
        numero = await self._generer_numero("DEV", data.date_devis)

        total_ht_brut = 0
        total_tva = 0
        lignes_db: list[QuoteLine] = []

        for i, l in enumerate(data.lignes, start=1):
            montant_ht = int(Decimal(str(l.quantite)) * Decimal(l.prix_unitaire_ht)) - l.remise_ligne
            montant_tva = int(Decimal(montant_ht) * Decimal(str(l.taux_tva)))
            total_ht_brut += montant_ht
            total_tva += montant_tva

            lignes_db.append(QuoteLine(
                tenant_id=self.tenant_id,
                ordre=i,
                item_id=l.item_id,
                designation=l.designation,
                unite=l.unite,
                quantite=Decimal(str(l.quantite)),
                prix_unitaire_ht=l.prix_unitaire_ht,
                remise_ligne=l.remise_ligne,
                taux_tva=l.taux_tva,
                montant_ht=montant_ht,
                montant_tva=montant_tva,
                montant_ttc=montant_ht + montant_tva,
                compte_produit=l.compte_produit,
                famille_stock=l.famille_stock,
            ))

        total_ht = total_ht_brut - data.remise_globale
        total_ttc = total_ht + total_tva

        quote = Quote(
            tenant_id=self.tenant_id,
            customer_id=data.customer_id,
            numero=numero,
            date_devis=data.date_devis,
            date_validite=data.date_validite,
            statut=StatutDevis.BROUILLON,
            total_ht=total_ht,
            total_tva=total_tva,
            total_ttc=total_ttc,
            remise_globale=data.remise_globale,
            conditions=data.conditions,
            notes=data.notes,
            created_by=self.user_id,
        )
        self.db.add(quote)
        await self.db.flush()

        for ligne in lignes_db:
            ligne.quote_id = quote.id
            self.db.add(ligne)
        await self.db.flush()
        return quote

    async def convertir_devis_en_commande(self, quote_id: UUID) -> SalesOrder:
        """Convertit un devis accepté en commande client."""
        quote = await self.db.scalar(
            select(Quote).where(
                Quote.id == quote_id,
                Quote.tenant_id == self.tenant_id,
            )
        )
        if quote is None:
            raise HTTPException(404, "Devis introuvable")
        if quote.statut not in (StatutDevis.ACCEPTE, StatutDevis.ENVOYE):
            raise HTTPException(400, f"Devis {quote.statut} — non convertible")

        # Charger les lignes du devis
        quote_lines = (
            await self.db.execute(
                select(QuoteLine).where(QuoteLine.quote_id == quote.id).order_by(QuoteLine.ordre)
            )
        ).scalars().all()

        # Créer la commande
        from app.schemas.sale import SalesOrderLineCreate
        order = await self.creer_commande(SalesOrderCreate(
            customer_id=quote.customer_id,
            date_commande=date.today(),
            remise_globale=quote.remise_globale,
            notes=f"Converti depuis devis {quote.numero}",
            lignes=[
                SalesOrderLineCreate(
                    item_id=ql.item_id,
                    designation=ql.designation,
                    unite=ql.unite,
                    quantite=float(ql.quantite),
                    prix_unitaire_ht=ql.prix_unitaire_ht,
                    remise_ligne=ql.remise_ligne,
                    taux_tva=float(ql.taux_tva),
                    compte_produit=ql.compte_produit,
                    famille_stock=ql.famille_stock,
                )
                for ql in quote_lines
            ],
        ))

        quote.statut = StatutDevis.CONVERTI
        quote.commande_id = order.id
        await self.db.flush()
        return order

    # ═════════════════════════════════════════════════════════════════════
    # COMMANDES CLIENT
    # ═════════════════════════════════════════════════════════════════════
    async def creer_commande(self, data: SalesOrderCreate) -> SalesOrder:
        customer = await self._get_customer(data.customer_id)
        numero = await self._generer_numero("SO", data.date_commande)

        total_ht_brut = 0
        total_tva = 0
        lignes_db: list[SalesOrderLine] = []

        for i, l in enumerate(data.lignes, start=1):
            montant_ht = int(Decimal(str(l.quantite)) * Decimal(l.prix_unitaire_ht)) - l.remise_ligne
            montant_tva = int(Decimal(montant_ht) * Decimal(str(l.taux_tva)))
            total_ht_brut += montant_ht
            total_tva += montant_tva

            lignes_db.append(SalesOrderLine(
                tenant_id=self.tenant_id,
                ordre=i,
                item_id=l.item_id,
                designation=l.designation,
                unite=l.unite,
                quantite_commandee=Decimal(str(l.quantite)),
                quantite_livree=Decimal(0),
                quantite_facturee=Decimal(0),
                prix_unitaire_ht=l.prix_unitaire_ht,
                remise_ligne=l.remise_ligne,
                taux_tva=l.taux_tva,
                montant_ht=montant_ht,
                montant_tva=montant_tva,
                montant_ttc=montant_ht + montant_tva,
                compte_produit=l.compte_produit,
                famille_stock=l.famille_stock,
            ))

        total_ht = total_ht_brut - data.remise_globale
        total_ttc = total_ht + total_tva

        order = SalesOrder(
            tenant_id=self.tenant_id,
            customer_id=customer.id,
            numero=numero,
            date_commande=data.date_commande,
            date_livraison_prevue=data.date_livraison_prevue,
            statut=StatutCommandeClient.BROUILLON,
            total_ht=total_ht,
            total_tva=total_tva,
            total_ttc=total_ttc,
            remise_globale=data.remise_globale,
            adresse_livraison=data.adresse_livraison,
            warehouse_source_id=data.warehouse_source_id,
            reference_client=data.reference_client,
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
            action="SO_CREATE",
            ressource="sales_order",
            ressource_id=order.id,
            payload={"numero": numero, "total_ht": total_ht},
        )
        return order

    async def confirmer_commande(self, order_id: UUID) -> SalesOrder:
        """
        Confirme la commande :
        - Vérifie le plafond de crédit du client
        - Passe le statut à 'confirmee'
        - Met à jour l'encours commandes
        """
        order = await self._get_order(order_id)
        if order.statut != StatutCommandeClient.BROUILLON:
            raise HTTPException(400, f"Commande déjà {order.statut}")

        customer = await self._get_customer(order.customer_id)

        # Vérification plafond crédit
        if customer.plafond_credit > 0:
            nouveau_solde = customer.solde_comptable + customer.encours_commandes + order.total_ttc
            if nouveau_solde > customer.plafond_credit:
                customer.depasse_plafond = True
                raise HTTPException(
                    400,
                    f"Plafond de crédit dépassé : {nouveau_solde:,} > {customer.plafond_credit:,} FCFA"
                    .replace(",", " "),
                )

        order.statut = StatutCommandeClient.CONFIRMEE
        order.confirmee_at = datetime.now(timezone.utc)
        order.confirmee_par = self.user_id

        customer.encours_commandes += order.total_ht
        await self.db.flush()

        await self.audit.log(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            action="SO_CONFIRM",
            ressource="sales_order",
            ressource_id=order.id,
        )
        return order

    # ═════════════════════════════════════════════════════════════════════
    # BON DE LIVRAISON
    # ═════════════════════════════════════════════════════════════════════
    async def creer_bl(
        self, data: DeliveryNoteCreate, sortir_stock: bool = True
    ) -> DeliveryNote:
        """Crée un BL + sortie de stock (module Stocks) + MAJ commande."""
        customer = await self._get_customer(data.customer_id)
        numero = await self._generer_numero("BL", data.date_livraison)

        # Vérifier la commande si fournie
        order: SalesOrder | None = None
        order_lines_map: dict[UUID, SalesOrderLine] = {}
        if data.sales_order_id:
            order = await self._get_order(data.sales_order_id)
            if order.customer_id != customer.id:
                raise HTTPException(400, "La commande n'appartient pas à ce client")
            if order.statut not in (StatutCommandeClient.CONFIRMEE, StatutCommandeClient.PARTIELLEMENT_LIVREE):
                raise HTTPException(400, f"Commande {order.statut} — non livrable")

            lines = (
                await self.db.execute(
                    select(SalesOrderLine).where(SalesOrderLine.order_id == order.id)
                )
            ).scalars().all()
            order_lines_map = {l.id: l for l in lines}

        delivery = DeliveryNote(
            tenant_id=self.tenant_id,
            customer_id=customer.id,
            sales_order_id=data.sales_order_id,
            warehouse_id=data.warehouse_id,
            numero=numero,
            date_livraison=data.date_livraison,
            adresse_livraison=data.adresse_livraison,
            transporteur=data.transporteur,
            statut=StatutBL.BROUILLON,
            notes=data.notes,
            created_by=self.user_id,
        )
        self.db.add(delivery)
        await self.db.flush()

        total_ht = 0
        mouvements_ids: list[str] = []

        for i, l in enumerate(data.lignes, start=1):
            montant_ht = int(Decimal(str(l.quantite_livree)) * Decimal(l.prix_unitaire_ht))
            total_ht += montant_ht

            qte_commandee = Decimal(0)
            if l.sales_order_line_id and l.sales_order_line_id in order_lines_map:
                qte_commandee = order_lines_map[l.sales_order_line_id].quantite_commandee

            dn_line = DeliveryNoteLine(
                delivery_id=delivery.id,
                tenant_id=self.tenant_id,
                sales_order_line_id=l.sales_order_line_id,
                item_id=l.item_id,
                ordre=i,
                designation=l.designation,
                quantite_commandee=qte_commandee,
                quantite_livree=Decimal(str(l.quantite_livree)),
                quantite_refusee=Decimal(str(l.quantite_refusee)),
                prix_unitaire_ht=l.prix_unitaire_ht,
                montant_ht=montant_ht,
                famille_stock=l.famille_stock,
                motif_refus=l.motif_refus,
            )
            self.db.add(dn_line)
            await self.db.flush()

            # Sortie de stock
            if sortir_stock and data.sortir_stock and l.item_id and l.quantite_livree > 0:
                try:
                    from app.schemas.stock import MouvementSortieCreate
                    from app.services.stock_service import StockService

                    stock_svc = StockService(self.db, self.tenant_id, self.user_id)
                    mv = await stock_svc.sortie_stock(
                        MouvementSortieCreate(
                            item_id=l.item_id,
                            warehouse_id=data.warehouse_id,
                            date_mouvement=data.date_livraison,
                            quantite=float(l.quantite_livree),
                            libelle=f"Livraison {numero} — {l.designation}",
                            reference_piece=numero,
                            type_mouvement="sortie_vente",
                        ),
                        comptabiliser=False,  # écriture via facture
                    )
                    dn_line.mouvement_stock_id = mv.id
                    mouvements_ids.append(str(mv.id))
                except Exception as exc:
                    logger.exception(f"[sale] Échec sortie stock ligne {i}")
                    raise HTTPException(500, f"Erreur sortie de stock : {exc}")

            # MAJ quantité livrée commande
            if l.sales_order_line_id and l.sales_order_line_id in order_lines_map:
                sol = order_lines_map[l.sales_order_line_id]
                sol.quantite_livree = Decimal(str(sol.quantite_livree)) + Decimal(str(l.quantite_livree))

        delivery.total_ht = total_ht
        delivery.mouvements_stock_ids = mouvements_ids

        # MAJ statut commande
        if order:
            all_lines = order_lines_map.values()
            tout_livre = all(
                Decimal(str(l.quantite_livree)) >= Decimal(str(l.quantite_commandee))
                for l in all_lines
            )
            partiel = any(Decimal(str(l.quantite_livree)) > 0 for l in all_lines)
            if tout_livre:
                order.statut = StatutCommandeClient.LIVREE
                customer.encours_commandes = max(
                    0, customer.encours_commandes - order.total_ht
                )
            elif partiel:
                order.statut = StatutCommandeClient.PARTIELLEMENT_LIVREE

        await self.db.flush()
        await self.audit.log(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            action="DN_CREATE",
            ressource="delivery_note",
            ressource_id=delivery.id,
            payload={"numero": numero, "total_ht": total_ht, "nb_mouvements": len(mouvements_ids)},
        )
        return delivery

    async def valider_bl(self, delivery_id: UUID) -> DeliveryNote:
        delivery = await self._get_delivery(delivery_id)
        if delivery.statut != StatutBL.BROUILLON:
            raise HTTPException(400, f"BL déjà {delivery.statut}")
        delivery.statut = StatutBL.VALIDE
        delivery.valide_at = datetime.now(timezone.utc)
        await self.db.flush()
        return delivery

    # ═════════════════════════════════════════════════════════════════════
    # FACTURE CLIENT
    # ═════════════════════════════════════════════════════════════════════
    async def creer_facture(
        self, data: CustomerInvoiceCreate, comptabiliser: bool = True
    ) -> CustomerInvoice:
        """Crée une facture client + écriture SYSCOHADA + MAJ solde."""
        customer = await self._get_customer(data.customer_id)
        numero = await self._generer_numero("FAC", data.date_facture)
        date_echeance = data.date_echeance or (
            data.date_facture + timedelta(days=customer.delai_paiement_jours)
        )

        # Calcul montants
        total_ht = 0
        total_tva = 0
        lignes_db: list[CustomerInvoiceLine] = []

        for i, l in enumerate(data.lignes, start=1):
            montant_ht = int(Decimal(str(l.quantite)) * Decimal(l.prix_unitaire_ht)) - l.remise_ligne
            # Exonération TVA
            if customer.exonere_tva:
                montant_tva = 0
            else:
                montant_tva = int(Decimal(montant_ht) * Decimal(str(l.taux_tva)))

            total_ht += montant_ht
            total_tva += montant_tva

            lignes_db.append(CustomerInvoiceLine(
                tenant_id=self.tenant_id,
                ordre=i,
                sales_order_line_id=l.sales_order_line_id,
                delivery_note_line_id=l.delivery_note_line_id,
                item_id=l.item_id,
                designation=l.designation,
                unite=l.unite,
                quantite=Decimal(str(l.quantite)),
                prix_unitaire_ht=l.prix_unitaire_ht,
                remise_ligne=l.remise_ligne,
                taux_tva=l.taux_tva if not customer.exonere_tva else 0,
                montant_ht=montant_ht,
                montant_tva=montant_tva,
                montant_ttc=montant_ht + montant_tva,
                compte_produit=l.compte_produit,
                famille_stock=l.famille_stock,
            ))

        base_ht = total_ht - data.remise_globale
        total_ttc = base_ht + total_tva

        invoice = CustomerInvoice(
            tenant_id=self.tenant_id,
            customer_id=customer.id,
            numero=numero,
            numero_client=data.numero_client,
            date_facture=data.date_facture,
            date_echeance=date_echeance,
            sales_order_id=data.sales_order_id,
            delivery_note_id=data.delivery_note_id,
            statut=StatutFactureClient.BROUILLON,
            total_ht=total_ht,
            remise_globale=data.remise_globale,
            base_ht=base_ht,
            total_tva=total_tva,
            total_ttc=total_ttc,
            ras_precomptee=0,
            montant_encaisse=0,
            solde_du=total_ttc,
            notes=data.notes,
            created_by=self.user_id,
        )
        self.db.add(invoice)
        await self.db.flush()

        for ligne in lignes_db:
            ligne.invoice_id = invoice.id
            self.db.add(ligne)
        await self.db.flush()

        if comptabiliser:
            ecriture_id = await self._generer_ecriture_facture(invoice, customer)
            invoice.ecriture_id = ecriture_id

        await self.db.flush()
        await self.audit.log(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            action="CI_CREATE",
            ressource="customer_invoice",
            ressource_id=invoice.id,
            payload={"numero": numero, "total_ttc": total_ttc},
        )
        return invoice

    async def valider_facture(self, invoice_id: UUID) -> CustomerInvoice:
        invoice = await self._get_invoice(invoice_id)
        if invoice.statut != StatutFactureClient.BROUILLON:
            raise HTTPException(400, f"Facture déjà {invoice.statut}")

        invoice.statut = StatutFactureClient.VALIDEE
        invoice.validee_at = datetime.now(timezone.utc)
        invoice.validee_par = self.user_id

        customer = await self._get_customer(invoice.customer_id)
        customer.solde_comptable += invoice.solde_du

        # Marquer la commande comme facturée
        if invoice.sales_order_id:
            order = await self._get_order(invoice.sales_order_id)
            order.statut = StatutCommandeClient.FACTUREE

        # Marquer le BL comme facturé
        if invoice.delivery_note_id:
            bl = await self._get_delivery(invoice.delivery_note_id)
            bl.statut = StatutBL.FACTURE

        await self.db.flush()
        return invoice

    # ═════════════════════════════════════════════════════════════════════
    # ENCAISSEMENT
    # ═════════════════════════════════════════════════════════════════════
    async def encaisser(
        self, data: CustomerPaymentCreate, comptabiliser: bool = True
    ) -> CustomerPayment:
        """
        Enregistre un encaissement.
        Supporte les flux Mobile Money (Wave, Orange, MTN, Moov).
        """
        invoice = await self._get_invoice(data.invoice_id)
        if invoice.statut in (StatutFactureClient.ANNULEE, StatutFactureClient.EN_LITIGE):
            raise HTTPException(400, f"Facture {invoice.statut} — non encaissable")
        if data.montant <= 0:
            raise HTTPException(400, "Montant doit être > 0")
        if data.montant + data.escompte_accorde > invoice.solde_du:
            raise HTTPException(
                400,
                f"Montant ({data.montant + data.escompte_accorde}) > solde dû ({invoice.solde_du})",
            )

        customer = await self._get_customer(invoice.customer_id)
        compte_tresorerie = COMPTES_TRESORERIE_PAR_MODE.get(data.mode_encaissement, "521000")
        numero = await self._generer_numero("ENC", data.date_encaissement)

        payment = CustomerPayment(
            tenant_id=self.tenant_id,
            customer_id=customer.id,
            invoice_id=invoice.id,
            numero=numero,
            date_encaissement=data.date_encaissement,
            montant=data.montant,
            mode_encaissement=data.mode_encaissement,
            compte_tresorerie=compte_tresorerie,
            reference_encaissement=data.reference_encaissement,
            mm_transaction_id=data.mm_transaction_id,
            statut=StatutEncaissement.BROUILLON,
            escompte_accorde=data.escompte_accorde,
            created_by=self.user_id,
        )
        self.db.add(payment)
        await self.db.flush()

        # MAJ facture
        invoice.montant_encaisse += data.montant + data.escompte_accorde
        invoice.solde_du = invoice.total_ttc - invoice.montant_encaisse
        if invoice.solde_du <= 0:
            invoice.statut = StatutFactureClient.PAYEE
            invoice.solde_du = 0
        else:
            invoice.statut = StatutFactureClient.PARTIELLEMENT_PAYEE

        # MAJ client
        customer.solde_comptable = max(
            0, customer.solde_comptable - data.montant - data.escompte_accorde
        )

        if comptabiliser:
            ecriture_id = await self._generer_ecriture_encaissement(payment, customer)
            payment.ecriture_id = ecriture_id
            payment.statut = StatutEncaissement.VALIDE

        await self.db.flush()
        await self.audit.log(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            action="CI_PAYMENT",
            ressource="customer_payment",
            ressource_id=payment.id,
            payload={
                "numero": numero,
                "montant": data.montant,
                "mode": data.mode_encaissement,
                "solde_restant": invoice.solde_du,
            },
        )
        return payment

    # ═════════════════════════════════════════════════════════════════════
    # AVOIR
    # ═════════════════════════════════════════════════════════════════════
    async def creer_avoir(
        self, data: CreditNoteCreate, comptabiliser: bool = True, reintegrer_stock: bool = True
    ) -> CreditNote:
        customer = await self._get_customer(data.customer_id)
        numero = await self._generer_numero("AV", data.date_avoir)

        # Vérifier facture source si fournie
        invoice = None
        if data.invoice_id:
            invoice = await self._get_invoice(data.invoice_id)
            if invoice.customer_id != customer.id:
                raise HTTPException(400, "Facture n'appartient pas à ce client")

        total_ht = 0
        total_tva = 0
        lignes_db: list[CreditNoteLine] = []

        for i, l in enumerate(data.lignes, start=1):
            montant_ht = int(Decimal(str(l.quantite)) * Decimal(l.prix_unitaire_ht))
            montant_tva = int(Decimal(montant_ht) * Decimal(str(l.taux_tva)))
            total_ht += montant_ht
            total_tva += montant_tva

            lignes_db.append(CreditNoteLine(
                tenant_id=self.tenant_id,
                ordre=i,
                invoice_line_id=l.invoice_line_id,
                item_id=l.item_id,
                designation=l.designation,
                quantite=Decimal(str(l.quantite)),
                prix_unitaire_ht=l.prix_unitaire_ht,
                taux_tva=l.taux_tva,
                montant_ht=montant_ht,
                montant_tva=montant_tva,
                montant_ttc=montant_ht + montant_tva,
                compte_produit=l.compte_produit,
                reintegrer_stock=l.reintegrer_stock,
            ))

        total_ttc = total_ht + total_tva

        credit_note = CreditNote(
            tenant_id=self.tenant_id,
            customer_id=customer.id,
            invoice_id=data.invoice_id,
            numero=numero,
            date_avoir=data.date_avoir,
            motif=data.motif,
            type_avoir=data.type_avoir,
            statut=StatutDevis.BROUILLON if False else "brouillon",
            total_ht=total_ht,
            total_tva=total_tva,
            total_ttc=total_ttc,
            montant_impute=0,
            montant_rembourse=0,
            reste_a_imputer=total_ttc,
            created_by=self.user_id,
        )
        self.db.add(credit_note)
        await self.db.flush()

        for ligne in lignes_db:
            ligne.credit_note_id = credit_note.id
            self.db.add(ligne)
        await self.db.flush()

        if comptabiliser:
            ecriture_id = await self._generer_ecriture_avoir(credit_note, customer)
            credit_note.ecriture_id = ecriture_id
            credit_note.statut = "valide"

        # Imputation sur facture + réintégration stock
        if invoice is not None:
            await self._imputer_avoir_sur_facture(credit_note, invoice)

        if reintegrer_stock:
            await self._reintegrer_stock_avoir(credit_note, data)

        # MAJ solde client (l'avoir diminue la créance)
        customer.solde_comptable = max(0, customer.solde_comptable - credit_note.reste_a_imputer)

        await self.db.flush()
        await self.audit.log(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            action="CREDIT_NOTE_CREATE",
            ressource="credit_note",
            ressource_id=credit_note.id,
            payload={"numero": numero, "total_ttc": total_ttc, "type": data.type_avoir},
        )
        return credit_note

    async def _imputer_avoir_sur_facture(
        self, credit_note: CreditNote, invoice: CustomerInvoice
    ) -> None:
        """Impute l'avoir sur la facture d'origine."""
        montant_imputable = min(credit_note.reste_a_imputer, invoice.solde_du)
        credit_note.montant_impute = montant_imputable
        credit_note.reste_a_imputer -= montant_imputable

        invoice.montant_encaisse += montant_imputable
        invoice.solde_du -= montant_imputable
        if invoice.solde_du <= 0:
            invoice.statut = StatutFactureClient.PAYEE
            invoice.solde_du = 0

        if credit_note.reste_a_imputer == 0:
            credit_note.statut = "impute"

    async def _reintegrer_stock_avoir(
        self, credit_note: CreditNote, data: CreditNoteCreate
    ) -> None:
        """Réintègre en stock les articles retournés."""
        from app.schemas.stock import MouvementEntreeCreate
        from app.services.stock_service import StockService

        # Trouver un entrepôt par défaut
        from app.models.stock import Warehouse
        warehouse = await self.db.scalar(
            select(Warehouse).where(
                Warehouse.tenant_id == self.tenant_id,
                Warehouse.est_principal.is_(True),
                Warehouse.actif.is_(True),
            )
        )
        if warehouse is None:
            logger.warning("[sale] Aucun entrepôt principal — pas de réintégration stock")
            return

        stock_svc = StockService(self.db, self.tenant_id, self.user_id)
        for l in data.lignes:
            if not l.reintegrer_stock or not l.item_id:
                continue
            try:
                await stock_svc.entree_stock(
                    MouvementEntreeCreate(
                        item_id=l.item_id,
                        warehouse_id=warehouse.id,
                        date_mouvement=credit_note.date_avoir,
                        quantite=l.quantite,
                        prix_unitaire=l.prix_unitaire_ht,
                        libelle=f"Retour avoir {credit_note.numero}",
                        reference_piece=credit_note.numero,
                        type_mouvement="entree_retour",
                    ),
                    comptabiliser=False,
                )
            except Exception:
                logger.exception(f"[sale] Échec réintégration stock ligne {l.designation}")

    # ═════════════════════════════════════════════════════════════════════
    # BALANCE ÂGÉE CLIENTS
    # ═════════════════════════════════════════════════════════════════════
    async def balance_agee(
        self, date_arret: date | None = None
    ) -> BalanceAgeeClientOut:
        """Balance âgée des factures clients non payées."""
        date_arret = date_arret or date.today()

        invoices = (
            await self.db.execute(
                select(CustomerInvoice)
                .where(
                    CustomerInvoice.tenant_id == self.tenant_id,
                    CustomerInvoice.statut.in_([
                        StatutFactureClient.VALIDEE,
                        StatutFactureClient.PARTIELLEMENT_PAYEE,
                        StatutFactureClient.EN_RETARD,
                    ]),
                    CustomerInvoice.solde_du > 0,
                )
            )
        ).scalars().all()

        par_client: dict[UUID, dict[str, Any]] = {}

        for inv in invoices:
            cid = inv.customer_id
            if cid not in par_client:
                customer = await self._get_customer(cid)
                par_client[cid] = {
                    "customer_id": cid,
                    "code": customer.code,
                    "raison_sociale": customer.raison_sociale,
                    "total_du": 0,
                    "non_echu": 0,
                    "tranche_0_30": 0,
                    "tranche_31_60": 0,
                    "tranche_61_90": 0,
                    "tranche_90_plus": 0,
                    "nb_factures": 0,
                    "plus_ancienne_echeance": None,
                    "niveau_relance": customer.niveau_relance_actuel,
                    "depasse_plafond": customer.depasse_plafond,
                }

            f = par_client[cid]
            f["total_du"] += inv.solde_du
            f["nb_factures"] += 1

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

            if f["plus_ancienne_echeance"] is None or inv.date_echeance < f["plus_ancienne_echeance"]:
                f["plus_ancienne_echeance"] = inv.date_echeance

        lignes = [BalanceAgeeClientLigne(**f) for f in par_client.values()]
        return BalanceAgeeClientOut(
            tenant_id=self.tenant_id,
            date_arret=date_arret,
            total_du=sum(l.total_du for l in lignes),
            total_non_echu=sum(l.non_echu for l in lignes),
            total_0_30=sum(l.tranche_0_30 for l in lignes),
            total_31_60=sum(l.tranche_31_60 for l in lignes),
            total_61_90=sum(l.tranche_61_90 for l in lignes),
            total_90_plus=sum(l.tranche_90_plus for l in lignes),
            clients=lignes,
        )

    # ═════════════════════════════════════════════════════════════════════
    # RELANCES AUTOMATIQUES
    # ═════════════════════════════════════════════════════════════════════
    async def previsualiser_relances(
        self, date_arret: date | None = None
    ) -> list[RelancePreviewOut]:
        """Liste les factures à relancer (sans les envoyer)."""
        date_arret = date_arret or date.today()

        invoices = (
            await self.db.execute(
                select(CustomerInvoice)
                .where(
                    CustomerInvoice.tenant_id == self.tenant_id,
                    CustomerInvoice.statut.in_([
                        StatutFactureClient.VALIDEE,
                        StatutFactureClient.PARTIELLEMENT_PAYEE,
                        StatutFactureClient.EN_RETARD,
                    ]),
                    CustomerInvoice.solde_du > 0,
                    CustomerInvoice.date_echeance < date_arret,
                )
                .order_by(CustomerInvoice.date_echeance)
            )
        ).scalars().all()

        previews: list[RelancePreviewOut] = []
        for inv in invoices:
            jours_retard = (date_arret - inv.date_echeance).days
            niveau_propose = niveau_relance_pour(jours_retard)
            if niveau_propose == NiveauRelance.AUCUNE:
                continue

            customer = await self._get_customer(inv.customer_id)
            previews.append(RelancePreviewOut(
                invoice_id=inv.id,
                numero=inv.numero,
                customer_id=customer.id,
                customer_code=customer.code,
                customer_name=customer.raison_sociale,
                date_echeance=inv.date_echeance,
                jours_retard=jours_retard,
                solde_du=inv.solde_du,
                niveau_actuel=inv.niveau_relance,
                niveau_propose=niveau_propose,
                message=self._formuler_relance(customer, inv, jours_retard, niveau_propose),
            ))
        return previews

    async def executer_relances(
        self, date_arret: date | None = None
    ) -> RelanceResultOut:
        """Exécute les relances et marque les factures."""
        previews = await self.previsualiser_relances(date_arret)
        now = datetime.now(timezone.utc)
        by_niveau: dict[str, int] = {}
        invoice_ids: list[UUID] = []
        total_du = 0

        for p in previews:
            inv = await self._get_invoice(p.invoice_id)
            inv.derniere_relance_at = now
            inv.niveau_relance = p.niveau_propose
            inv.nb_relances += 1

            customer = await self._get_customer(p.customer_id)
            customer.derniere_relance_at = now
            customer.niveau_relance_actuel = p.niveau_propose

            by_niveau[p.niveau_propose] = by_niveau.get(p.niveau_propose, 0) + 1
            invoice_ids.append(inv.id)
            total_du += inv.solde_du

        await self.db.flush()
        await self.audit.log(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            action="RELANCE_EXECUTE",
            ressource="customer_invoice",
            payload={"nb_relances": len(invoice_ids), "by_niveau": by_niveau},
        )
        return RelanceResultOut(
            invoices_relanced=len(invoice_ids),
            by_niveau=by_niveau,
            total_montant_du=total_du,
            invoice_ids=invoice_ids,
        )

    def _formuler_relance(
        self, customer: Customer, invoice: CustomerInvoice, jours: int, niveau: str
    ) -> str:
        if niveau == NiveauRelance.AIMABLE:
            return (
                f"Bonjour {customer.raison_sociale},\n\n"
                f"Sauf erreur, nous n'avons pas reçu le règlement de la facture "
                f"{invoice.numero} d'un montant de {invoice.solde_du:,} FCFA, "
                f"échue depuis {jours} jours.\n\n"
                f"Nous vous remercions de bien vouloir procéder au paiement.\n"
                f"Cordialement."
            ).replace(",", " ")
        if niveau == NiveauRelance.FERME:
            return (
                f"Bonjour {customer.raison_sociale},\n\n"
                f"Malgré notre relance précédente, la facture {invoice.numero} "
                f"({invoice.solde_du:,} FCFA) reste impayée ({jours} jours de retard).\n\n"
                f"Nous vous demandons de régulariser sous 8 jours.\n"
                f"À défaut, nous serons contraints de suspendre vos livraisons."
            ).replace(",", " ")
        if niveau == NiveauRelance.MISE_EN_DEMEURE:
            return (
                f"MISE EN DEMEURE\n\n"
                f"{customer.raison_sociale},\n\n"
                f"La facture {invoice.numero} ({invoice.solde_du:,} FCFA) est impayée "
                f"depuis {jours} jours. Nous vous mettons en demeure de régler sous 8 jours.\n\n"
                f"Passé ce délai, nous engagerons une procédure de recouvrement."
            ).replace(",", " ")
        if niveau == NiveauRelance.CONTENTIEUX:
            return (
                f"DOSSIER CONTENTIEUX\n\n"
                f"{customer.raison_sociale},\n\n"
                f"Votre dette de {invoice.solde_du:,} FCFA (facture {invoice.numero}) "
                f"est impayée depuis {jours} jours. Votre dossier est transmis à notre "
                f"service contentieux."
            ).replace(",", " ")
        return ""

    # ═════════════════════════════════════════════════════════════════════
    # ÉCRITURES SYSCOHADA
    # ═════════════════════════════════════════════════════════════════════
    async def _generer_ecriture_facture(
        self, invoice: CustomerInvoice, customer: Customer
    ) -> UUID:
        """
        Écriture de facture client :
          Débit 411x (Client)             total_ttc
          Crédit 70x (Produits)           base_ht
          Crédit 443x (TVA collectée)     total_tva
        """
        lignes: list[LigneIn] = []

        # Ligne client
        lignes.append(LigneIn(
            compte=COMPTES_CLIENTS[customer.type_client].compte,
            libelle=f"Facture {invoice.numero} — {customer.raison_sociale}",
            debit=invoice.total_ttc,
        ))

        # Produits regroupés par compte
        produits_par_compte: dict[str, int] = {}
        inv_lines = (
            await self.db.execute(
                select(CustomerInvoiceLine).where(CustomerInvoiceLine.invoice_id == invoice.id)
            )
        ).scalars().all()
        for il in inv_lines:
            produits_par_compte[il.compte_produit] = (
                produits_par_compte.get(il.compte_produit, 0) + int(il.montant_ht)
            )

        for compte, montant in produits_par_compte.items():
            if montant == 0:
                continue
            lignes.append(LigneIn(
                compte=compte,
                libelle=f"Vente {invoice.numero}",
                credit=montant,
            ))

        # TVA collectée
        if invoice.total_tva > 0:
            lignes.append(LigneIn(
                compte=COMPTE_TVA_COLLECTEE,
                libelle=f"TVA collectée {invoice.numero}",
                credit=invoice.total_tva,
            ))

        try:
            await JournalService(self.db, self.tenant_id).get_by_code(JOURNAL_VENTE)
            journal_code = JOURNAL_VENTE
        except Exception:
            journal_code = "OD"

        syscohada = SyscohadaService(self.db, self.tenant_id, self.user_id)
        e = await syscohada.create(EcritureCreate(
            numero_piece=invoice.numero,
            date_ecriture=invoice.date_facture,
            code_journal=journal_code,
            libelle=f"Vente {customer.raison_sociale}",
            source=EcritureSource.SYSTEME,
            lignes=lignes,
        ))
        return e.id

    async def _generer_ecriture_encaissement(
        self, payment: CustomerPayment, customer: Customer
    ) -> UUID:
        """
        Écriture d'encaissement :
          Débit 521x/571x (Trésorerie)    montant
          Crédit 411x (Client)            montant + escompte
          Débit 665x (Escompte accordé)   escompte
        """
        lignes = [
            LigneIn(
                compte=payment.compte_tresorerie,
                libelle=f"Encaissement {payment.reference_encaissement or payment.numero}",
                debit=payment.montant,
            ),
        ]
        if payment.escompte_accorde > 0:
            lignes.append(LigneIn(
                compte="665000",
                libelle="Escompte accordé",
                debit=payment.escompte_accorde,
            ))
        lignes.append(LigneIn(
            compte=COMPTES_CLIENTS[customer.type_client].compte,
            libelle=f"Règlement client {customer.raison_sociale}",
            credit=payment.montant + payment.escompte_accorde,
        ))

        try:
            await JournalService(self.db, self.tenant_id).get_by_code(JOURNAL_VENTE)
            journal_code = JOURNAL_VENTE
        except Exception:
            journal_code = "OD"

        syscohada = SyscohadaService(self.db, self.tenant_id, self.user_id)
        e = await syscohada.create(EcritureCreate(
            numero_piece=payment.numero,
            date_ecriture=payment.date_encaissement,
            code_journal=journal_code,
            libelle=f"Encaissement {customer.raison_sociale}",
            reference_ext=payment.reference_encaissement,
            source=EcritureSource.SYSTEME,
            lignes=lignes,
        ))
        return e.id

    async def _generer_ecriture_avoir(
        self, credit_note: CreditNote, customer: Customer
    ) -> UUID:
        """
        Écriture d'avoir (inverse de facture) :
          Débit 70x (Produits)          total_ht
          Débit 443x (TVA collectée)    total_tva
          Crédit 411x (Client)          total_ttc
        """
        lignes: list[LigneIn] = []

        # Débit produits (inverse)
        cn_lines = (
            await self.db.execute(
                select(CreditNoteLine).where(CreditNoteLine.credit_note_id == credit_note.id)
            )
        ).scalars().all()
        produits_par_compte: dict[str, int] = {}
        for cl in cn_lines:
            produits_par_compte[cl.compte_produit] = (
                produits_par_compte.get(cl.compte_produit, 0) + int(cl.montant_ht)
            )

        for compte, montant in produits_par_compte.items():
            lignes.append(LigneIn(
                compte=compte,
                libelle=f"Avoir {credit_note.numero}",
                debit=montant,
            ))

        if credit_note.total_tva > 0:
            lignes.append(LigneIn(
                compte=COMPTE_TVA_COLLECTEE,
                libelle=f"TVA avoir {credit_note.numero}",
                debit=credit_note.total_tva,
            ))

        lignes.append(LigneIn(
            compte=COMPTES_CLIENTS[customer.type_client].compte,
            libelle=f"Avoir {credit_note.numero} — {customer.raison_sociale}",
            credit=credit_note.total_ttc,
        ))

        try:
            await JournalService(self.db, self.tenant_id).get_by_code(JOURNAL_AVOIR)
            journal_code = JOURNAL_AVOIR
        except Exception:
            try:
                await JournalService(self.db, self.tenant_id).get_by_code(JOURNAL_VENTE)
                journal_code = JOURNAL_VENTE
            except Exception:
                journal_code = "OD"

        syscohada = SyscohadaService(self.db, self.tenant_id, self.user_id)
        e = await syscohada.create(EcritureCreate(
            numero_piece=credit_note.numero,
            date_ecriture=credit_note.date_avoir,
            code_journal=journal_code,
            libelle=f"Avoir {customer.raison_sociale} — {credit_note.motif}",
            source=EcritureSource.SYSTEME,
            lignes=lignes,
        ))
        return e.id

    # ═════════════════════════════════════════════════════════════════════
    # HELPERS
    # ═════════════════════════════════════════════════════════════════════
    async def _get_customer(self, customer_id: UUID) -> Customer:
        c = await self.db.scalar(
            select(Customer).where(
                Customer.id == customer_id,
                Customer.tenant_id == self.tenant_id,
            )
        )
        if c is None:
            raise HTTPException(404, "Client introuvable")
        return c

    async def _get_order(self, order_id: UUID) -> SalesOrder:
        o = await self.db.scalar(
            select(SalesOrder).where(
                SalesOrder.id == order_id,
                SalesOrder.tenant_id == self.tenant_id,
            )
        )
        if o is None:
            raise HTTPException(404, "Commande introuvable")
        return o

    async def _get_delivery(self, delivery_id: UUID) -> DeliveryNote:
        d = await self.db.scalar(
            select(DeliveryNote).where(
                DeliveryNote.id == delivery_id,
                DeliveryNote.tenant_id == self.tenant_id,
            )
        )
        if d is None:
            raise HTTPException(404, "BL introuvable")
        return d

    async def _get_invoice(self, invoice_id: UUID) -> CustomerInvoice:
        i = await self.db.scalar(
            select(CustomerInvoice).where(
                CustomerInvoice.id == invoice_id,
                CustomerInvoice.tenant_id == self.tenant_id,
            )
        )
        if i is None:
            raise HTTPException(404, "Facture client introuvable")
        return i

    async def _generer_numero(self, prefixe: str, d: date) -> str:
        annee = d.year
        pattern = f"{prefixe}-{annee}-%"
        mapping = {
            "DEV": (Quote, Quote.numero),
            "SO": (SalesOrder, SalesOrder.numero),
            "BL": (DeliveryNote, DeliveryNote.numero),
            "FAC": (CustomerInvoice, CustomerInvoice.numero),
            "ENC": (CustomerPayment, CustomerPayment.numero),
            "AV": (CreditNote, CreditNote.numero),
        }
        model, col = mapping[prefixe]
        count = int(await self.db.scalar(
            select(func.count(model.id)).where(
                model.tenant_id == self.tenant_id,
                col.like(pattern),
            )
        ) or 0)
        return f"{prefixe}-{annee}-{count + 1:05d}"
