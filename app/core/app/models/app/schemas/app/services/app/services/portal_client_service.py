"""
Service Espace Client — Consultation factures, relevés, paiement en ligne.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.portal_syscohada import (
    FRAIS_PAIEMENT_CARTE_PCT,
    FRAIS_PAIEMENT_MOBILE_MONEY_PCT,
    SEUIL_MONTANT_PAIEMENT_EN_LIGNE,
    StatutPaiementPortail,
)
from app.models.portal import (
    OnlinePayment,
    PortalNotification,
    PortalUser,
    SharedDocument,
)
from app.models.sale import (
    Customer,
    CustomerInvoice,
    CustomerPayment,
)
from app.schemas.portal import (
    ClientInvoiceOut,
    ClientPortalDashboard,
    ClientStatementOut,
    OnlinePaymentInitIn,
    OnlinePaymentOut,
)
from app.services.audit_service import AuditService

logger = logging.getLogger(__name__)


class PortalClientService:
    def __init__(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        portal_user: PortalUser,
    ) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self.portal_user = portal_user
        self.customer_id = portal_user.customer_id

        if self.customer_id is None:
            raise HTTPException(403, "Utilisateur portail non rattaché à un client")

    # ═════════════════════════════════════════════════════════════════════
    # DASHBOARD
    # ═════════════════════════════════════════════════════════════════════
    async def dashboard(self) -> ClientPortalDashboard:
        """Vue d'ensemble du client connecté."""
        customer = await self._get_customer()
        today = date.today()

        # Solde dû
        solde_du = int(await self.db.scalar(
            select(func.coalesce(func.sum(CustomerInvoice.solde_du), 0))
            .where(
                CustomerInvoice.tenant_id == self.tenant_id,
                CustomerInvoice.customer_id == self.customer_id,
                CustomerInvoice.statut.in_(["validee", "partiellement_payee", "en_retard"]),
            )
        ) or 0)

        # Factures impayées
        nb_impayees = int(await self.db.scalar(
            select(func.count(CustomerInvoice.id)).where(
                CustomerInvoice.tenant_id == self.tenant_id,
                CustomerInvoice.customer_id == self.customer_id,
                CustomerInvoice.solde_du > 0,
                CustomerInvoice.statut.in_(["validee", "partiellement_payee", "en_retard"]),
            )
        ) or 0)

        # Factures en retard
        nb_retard = int(await self.db.scalar(
            select(func.count(CustomerInvoice.id)).where(
                CustomerInvoice.tenant_id == self.tenant_id,
                CustomerInvoice.customer_id == self.customer_id,
                CustomerInvoice.solde_du > 0,
                CustomerInvoice.date_echeance < today,
            )
        ) or 0)

        montant_retard = int(await self.db.scalar(
            select(func.coalesce(func.sum(CustomerInvoice.solde_du), 0)).where(
                CustomerInvoice.tenant_id == self.tenant_id,
                CustomerInvoice.customer_id == self.customer_id,
                CustomerInvoice.solde_du > 0,
                CustomerInvoice.date_echeance < today,
            )
        ) or 0)

        # Factures du mois
        debut_mois = today.replace(day=1)
        nb_mois = int(await self.db.scalar(
            select(func.count(CustomerInvoice.id)).where(
                CustomerInvoice.tenant_id == self.tenant_id,
                CustomerInvoice.customer_id == self.customer_id,
                CustomerInvoice.date_facture >= debut_mois,
            )
        ) or 0)

        montant_mois = int(await self.db.scalar(
            select(func.coalesce(func.sum(CustomerInvoice.total_ttc), 0)).where(
                CustomerInvoice.tenant_id == self.tenant_id,
                CustomerInvoice.customer_id == self.customer_id,
                CustomerInvoice.date_facture >= debut_mois,
            )
        ) or 0)

        # Dernière facture
        derniere_facture = await self.db.scalar(
            select(CustomerInvoice)
            .where(
                CustomerInvoice.tenant_id == self.tenant_id,
                CustomerInvoice.customer_id == self.customer_id,
            )
            .order_by(CustomerInvoice.date_facture.desc())
            .limit(1)
        )

        # Dernier paiement
        dernier_paiement = await self.db.scalar(
            select(CustomerPayment)
            .where(
                CustomerPayment.tenant_id == self.tenant_id,
                CustomerPayment.customer_id == self.customer_id,
            )
            .order_by(CustomerPayment.date_encaissement.desc())
            .limit(1)
        )

        # Prochaine échéance
        prochaine_echeance = await self.db.scalar(
            select(func.min(CustomerInvoice.date_echeance)).where(
                CustomerInvoice.tenant_id == self.tenant_id,
                CustomerInvoice.customer_id == self.customer_id,
                CustomerInvoice.solde_du > 0,
                CustomerInvoice.date_echeance >= today,
            )
        )

        return ClientPortalDashboard(
            customer_id=self.customer_id,
            customer_nom=customer.raison_sociale,
            solde_du_xof=solde_du,
            nb_factures_impayees=nb_impayees,
            nb_factures_en_retard=nb_retard,
            montant_en_retard_xof=montant_retard,
            nb_factures_mois_courant=nb_mois,
            montant_facture_mois_xof=montant_mois,
            derniere_facture=self._serialize_invoice_brief(derniere_facture) if derniere_facture else None,
            dernier_paiement=self._serialize_payment_brief(dernier_paiement) if dernier_paiement else None,
            prochaine_echeance=prochaine_echeance,
        )

    # ═════════════════════════════════════════════════════════════════════
    # FACTURES
    # ═════════════════════════════════════════════════════════════════════
    async def lister_factures(
        self, statut: str | None = None, limit: int = 100, offset: int = 0
    ) -> list[ClientInvoiceOut]:
        """
        Liste les factures du client — isolation stricte via customer_id.
        """
        stmt = select(CustomerInvoice).where(
            CustomerInvoice.tenant_id == self.tenant_id,
            CustomerInvoice.customer_id == self.customer_id,
        )
        if statut:
            stmt = stmt.where(CustomerInvoice.statut == statut)
        stmt = stmt.order_by(CustomerInvoice.date_facture.desc()).limit(limit).offset(offset)
        invoices = list((await self.db.execute(stmt)).scalars().all())

        today = date.today()
        results = []
        for inv in invoices:
            jours_retard = max(0, (today - inv.date_echeance).days) if inv.solde_du > 0 else 0
            peut_payer = (
                inv.solde_du >= SEUIL_MONTANT_PAIEMENT_EN_LIGNE
                and inv.statut not in ("annulee", "en_litige")
            )

            # Récupérer la FNE si certifiée
            fne_ref, qr_url = await self._get_fne_info(inv.id)

            results.append(ClientInvoiceOut(
                id=inv.id,
                numero=inv.numero,
                date_facture=inv.date_facture,
                date_echeance=inv.date_echeance,
                total_ht=inv.total_ht,
                total_tva=inv.total_tva,
                total_ttc=inv.total_ttc,
                montant_encaisse=inv.montant_encaisse,
                solde_du=inv.solde_du,
                statut=inv.statut,
                jours_retard=jours_retard,
                peut_payer_en_ligne=peut_payer,
                fne_reference=fne_ref,
                qr_code_url=qr_url,
                document_url=f"/api/v1/portal/client/invoices/{inv.id}/pdf",
            ))
        return results

    async def get_facture_detail(self, invoice_id: UUID) -> dict[str, Any]:
        """Détail d'une facture (vérification stricte d'appartenance)."""
        invoice = await self.db.scalar(
            select(CustomerInvoice).where(
                CustomerInvoice.id == invoice_id,
                CustomerInvoice.tenant_id == self.tenant_id,
                CustomerInvoice.customer_id == self.customer_id,   # ⚠️ ISOLATION
            )
        )
        if invoice is None:
            raise HTTPException(404, "Facture introuvable")

        # Lignes
        from app.models.sale import CustomerInvoiceLine
        lines = (
            await self.db.execute(
                select(CustomerInvoiceLine)
                .where(CustomerInvoiceLine.invoice_id == invoice.id)
                .order_by(CustomerInvoiceLine.ordre)
            )
        ).scalars().all()

        today = date.today()
        jours_retard = max(0, (today - invoice.date_echeance).days) if invoice.solde_du > 0 else 0

        fne_ref, qr_url = await self._get_fne_info(invoice.id)

        return {
            "id": str(invoice.id),
            "numero": invoice.numero,
            "date_facture": invoice.date_facture.isoformat(),
            "date_echeance": invoice.date_echeance.isoformat(),
            "total_ht": invoice.total_ht,
            "total_tva": invoice.total_tva,
            "total_ttc": invoice.total_ttc,
            "montant_encaisse": invoice.montant_encaisse,
            "solde_du": invoice.solde_du,
            "statut": invoice.statut,
            "jours_retard": jours_retard,
            "notes": invoice.notes,
            "lignes": [
                {
                    "designation": l.designation,
                    "quantite": float(l.quantite),
                    "prix_unitaire_ht": l.prix_unitaire_ht,
                    "montant_ht": l.montant_ht,
                    "montant_tva": l.montant_tva,
                    "montant_ttc": l.montant_ttc,
                }
                for l in lines
            ],
            "fne_reference": fne_ref,
            "qr_code_url": qr_url,
            "peut_payer_en_ligne": (
                invoice.solde_du >= SEUIL_MONTANT_PAIEMENT_EN_LIGNE
                and invoice.statut not in ("annulee", "en_litige")
            ),
            "pdf_url": f"/api/v1/portal/client/invoices/{invoice.id}/pdf",
        }

    async def _get_fne_info(self, invoice_id: UUID) -> tuple[str | None, str | None]:
        """Récupère la référence FNE et le QR code si certifiée."""
        try:
            from app.models.fne import FneInvoice
            fne = await self.db.scalar(
                select(FneInvoice).where(
                    FneInvoice.customer_invoice_id == invoice_id,
                    FneInvoice.statut == "certifiee",
                )
            )
            if fne:
                return fne.fne_reference, fne.qr_code_url
        except Exception:
            pass
        return None, None

    # ═════════════════════════════════════════════════════════════════════
    # RELEVÉ DE COMPTE
    # ═════════════════════════════════════════════════════════════════════
    async def releve_compte(
        self, date_debut: date, date_fin: date
    ) -> ClientStatementOut:
        """Relevé de compte sur une période."""
        # Solde d'ouverture (avant date_debut)
        total_facture_avant = int(await self.db.scalar(
            select(func.coalesce(func.sum(CustomerInvoice.total_ttc), 0)).where(
                CustomerInvoice.tenant_id == self.tenant_id,
                CustomerInvoice.customer_id == self.customer_id,
                CustomerInvoice.date_facture < date_debut,
                CustomerInvoice.statut.notin_(["annulee"]),
            )
        ) or 0)
        total_paye_avant = int(await self.db.scalar(
            select(func.coalesce(func.sum(CustomerPayment.montant), 0)).where(
                CustomerPayment.tenant_id == self.tenant_id,
                CustomerPayment.customer_id == self.customer_id,
                CustomerPayment.date_encaissement < date_debut,
                CustomerPayment.statut == "valide",
            )
        ) or 0)
        solde_ouverture = total_facture_avant - total_paye_avant

        # Mouvements de la période
        total_facture = int(await self.db.scalar(
            select(func.coalesce(func.sum(CustomerInvoice.total_ttc), 0)).where(
                CustomerInvoice.tenant_id == self.tenant_id,
                CustomerInvoice.customer_id == self.customer_id,
                CustomerInvoice.date_facture.between(date_debut, date_fin),
                CustomerInvoice.statut.notin_(["annulee"]),
            )
        ) or 0)

        total_paye = int(await self.db.scalar(
            select(func.coalesce(func.sum(CustomerPayment.montant), 0)).where(
                CustomerPayment.tenant_id == self.tenant_id,
                CustomerPayment.customer_id == self.customer_id,
                CustomerPayment.date_encaissement.between(date_debut, date_fin),
                CustomerPayment.statut == "valide",
            )
        ) or 0)

        nb_factures = int(await self.db.scalar(
            select(func.count(CustomerInvoice.id)).where(
                CustomerInvoice.tenant_id == self.tenant_id,
                CustomerInvoice.customer_id == self.customer_id,
                CustomerInvoice.date_facture.between(date_debut, date_fin),
                CustomerInvoice.statut.notin_(["annulee"]),
            )
        ) or 0)

        nb_paiements = int(await self.db.scalar(
            select(func.count(CustomerPayment.id)).where(
                CustomerPayment.tenant_id == self.tenant_id,
                CustomerPayment.customer_id == self.customer_id,
                CustomerPayment.date_encaissement.between(date_debut, date_fin),
                CustomerPayment.statut == "valide",
            )
        ) or 0)

        return ClientStatementOut(
            customer_id=self.customer_id,
            date_debut=date_debut,
            date_fin=date_fin,
            solde_ouverture=solde_ouverture,
            total_facture=total_facture,
            total_paye=total_paye,
            solde_fin=solde_ouverture + total_facture - total_paye,
            nb_factures=nb_factures,
            nb_paiements=nb_paiements,
            pdf_url=f"/api/v1/portal/client/statement/pdf?debut={date_debut}&fin={date_fin}",
        )

    # ═════════════════════════════════════════════════════════════════════
    # PAIEMENT EN LIGNE
    # ═════════════════════════════════════════════════════════════════════
    async def initier_paiement(self, data: OnlinePaymentInitIn) -> dict[str, Any]:
        """
        Initie un paiement en ligne pour une ou plusieurs factures.
        """
        # Vérifier que les factures appartiennent au client
        invoices = (
            await self.db.execute(
                select(CustomerInvoice).where(
                    CustomerInvoice.id.in_(data.invoice_ids),
                    CustomerInvoice.tenant_id == self.tenant_id,
                    CustomerInvoice.customer_id == self.customer_id,   # ISOLATION
                )
            )
        ).scalars().all()

        if len(invoices) != len(data.invoice_ids):
            raise HTTPException(404, "Une ou plusieurs factures introuvables")

        # Calculer le montant total
        montant_total = sum(inv.solde_du for inv in invoices)
        if montant_total <= 0:
            raise HTTPException(400, "Aucun solde à payer sur ces factures")
        if montant_total < SEUIL_MONTANT_PAIEMENT_EN_LIGNE:
            raise HTTPException(
                400,
                f"Le montant minimum pour un paiement en ligne est de "
                f"{SEUIL_MONTANT_PAIEMENT_EN_LIGNE:,} FCFA".replace(",", " "),
            )

        # Calculer les frais selon le moyen
        frais_pct = (
            FRAIS_PAIEMENT_MOBILE_MONEY_PCT if data.moyen == "mobile_money"
            else FRAIS_PAIEMENT_CARTE_PCT if data.moyen == "carte_bancaire"
            else 0.0
        )
        frais = int(montant_total * frais_pct)
        montant_total_avec_frais = montant_total + frais

        # Créer le paiement
        reference = f"PAY-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid4().hex[:8].upper()}"

        payment = OnlinePayment(
            tenant_id=self.tenant_id,
            portal_user_id=self.portal_user.id,
            customer_id=self.customer_id,
            reference=reference,
            montant_xof=montant_total,
            frais_xof=frais,
            montant_total_xof=montant_total_avec_frais,
            moyen=data.moyen,
            provider=data.provider,
            statut=StatutPaiementPortail.INITIE,
            invoice_ids=[str(i.id) for i in invoices],
            initie_at=datetime.now(timezone.utc),
        )
        self.db.add(payment)
        await self.db.flush()

        # Déclencher le provider (Wave, Stripe, etc.)
        checkout_url, instructions = await self._declencher_provider(payment, data)

        payment.provider_url = checkout_url
        await self.db.flush()

        return {
            "payment": OnlinePaymentOut.model_validate(payment),
            "checkout_url": checkout_url,
            "instructions": instructions,
        }

    async def _declencher_provider(
        self, payment: OnlinePayment, data: OnlinePaymentInitIn
    ) -> tuple[str | None, str | None]:
        """
        Intègre avec le provider de paiement.
        À terme : appel API Wave / Stripe / CinetPay.
        """
        # Placeholder : à implémenter selon le provider
        if data.moyen == "mobile_money" and data.provider == "wave":
            # Génération d'un lien Wave
            checkout_url = f"https://pay.wave.com/m/{payment.reference}"
            instructions = (
                f"Composez le *155# sur votre téléphone, "
                f"puis suivez les instructions. Montant : {payment.montant_total_xof:,} FCFA"
                .replace(",", " ")
            )
            return checkout_url, instructions

        if data.moyen == "mobile_money" and data.provider == "orange_money":
            checkout_url = f"https://om.orange.ci/pay/{payment.reference}"
            instructions = f"Composez #144# pour valider le paiement de {payment.montant_total_xof:,} FCFA".replace(",", " ")
            return checkout_url, instructions

        if data.moyen == "carte_bancaire":
            # Redirection Stripe / CinetPay
            checkout_url = f"https://checkout.mtech.ci/{payment.reference}"
            return checkout_url, "Vous allez être redirigé vers la page de paiement sécurisée."

        return None, "Contactez votre fournisseur pour finaliser le paiement."

    async def confirmer_paiement(
        self, payment_id: UUID, provider_reference: str, provider_payload: dict[str, Any]
    ) -> OnlinePayment:
        """
        Confirme un paiement (appelé par le webhook du provider).
        Génère un CustomerPayment officiel dans la comptabilité.
        """
        payment = await self.db.scalar(
            select(OnlinePayment).where(
                OnlinePayment.id == payment_id,
                OnlinePayment.tenant_id == self.tenant_id,
            )
        )
        if payment is None:
            raise HTTPException(404, "Paiement introuvable")
        if payment.statut == StatutPaiementPortail.CONFIRME:
            return payment

        payment.statut = StatutPaiementPortail.CONFIRME
        payment.confirme_at = datetime.now(timezone.utc)
        payment.provider_reference = provider_reference
        payment.provider_payload = provider_payload
        await self.db.flush()

        # Créer les paiements comptables (via SaleService)
        from app.services.sale_service import SaleService
        sale_svc = SaleService(self.db, self.tenant_id, None)  # User_id = None (système)

        # Répartir le montant sur les factures (FIFO sur échéance)
        invoices = (
            await self.db.execute(
                select(CustomerInvoice)
                .where(CustomerInvoice.id.in_([UUID(i) for i in payment.invoice_ids]))
                .order_by(CustomerInvoice.date_echeance)
            )
        ).scalars().all()

        montant_restant = payment.montant_xof
        for inv in invoices:
            if montant_restant <= 0:
                break
            montant_a_appliquer = min(montant_restant, inv.solde_du)
            from app.schemas.sale import CustomerPaymentCreate
            try:
                await sale_svc.encaisser(CustomerPaymentCreate(
                    invoice_id=inv.id,
                    date_encaissement=date.today(),
                    montant=montant_a_appliquer,
                    mode_encaissement="wave" if payment.provider == "wave" else (
                        "orange_money" if payment.provider == "orange_money" else "carte"
                    ),
                    reference_encaissement=payment.reference,
                ))
            except Exception:
                logger.exception(f"[portal] Échec encaissement facture {inv.id}")
            montant_restant -= montant_a_appliquer

        # Notification au tenant
        self.db.add(PortalNotification(
            tenant_id=self.tenant_id,
            portal_user_id=payment.portal_user_id,
            event_type="paiement_recu",
            canal="email",
            sujet=f"Paiement confirmé — {payment.reference}",
            contenu_texte=(
                f"Votre paiement de {payment.montant_xof:,} FCFA a été confirmé. "
                f"Référence : {payment.reference}"
            ).replace(",", " "),
            envoye=True,
            envoye_at=datetime.now(timezone.utc),
        ))

        await self.db.flush()
        return payment

    # ═════════════════════════════════════════════════════════════════════
    # DOCUMENTS
    # ═════════════════════════════════════════════════════════════════════
    async def lister_documents(self, limit: int = 100) -> list[SharedDocument]:
        stmt = (
            select(SharedDocument)
            .where(
                SharedDocument.tenant_id == self.tenant_id,
                SharedDocument.customer_id == self.customer_id,
                SharedDocument.actif.is_(True),
            )
            .order_by(SharedDocument.created_at.desc())
            .limit(limit)
        )
        return list((await self.db.execute(stmt)).scalars().all())

    # ═════════════════════════════════════════════════════════════════════
    # HELPERS
    # ═════════════════════════════════════════════════════════════════════
    async def _get_customer(self) -> Customer:
        c = await self.db.scalar(
            select(Customer).where(
                Customer.id == self.customer_id,
                Customer.tenant_id == self.tenant_id,
            )
        )
        if c is None:
            raise HTTPException(404, "Client introuvable")
        return c

    @staticmethod
    def _serialize_invoice_brief(inv: CustomerInvoice) -> dict[str, Any]:
        return {
            "id": str(inv.id),
            "numero": inv.numero,
            "date_facture": inv.date_facture.isoformat(),
            "date_echeance": inv.date_echeance.isoformat(),
            "total_ttc": inv.total_ttc,
            "solde_du": inv.solde_du,
            "statut": inv.statut,
        }

    @staticmethod
    def _serialize_payment_brief(p: CustomerPayment) -> dict[str, Any]:
        return {
            "id": str(p.id),
            "numero": p.numero,
            "date_encaissement": p.date_encaissement.isoformat(),
            "montant": p.montant,
            "mode_encaissement": p.mode_encaissement,
        }
