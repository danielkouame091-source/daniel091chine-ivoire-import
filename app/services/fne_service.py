"""
Service FNE — Orchestration de la certification des factures.

Pipeline de certification :
1. Vérifier la configuration FNE du tenant
2. Vérifier le solde de stickers
3. Construire le payload FNE depuis la facture interne
4. Appeler l'API FNE (certifier_facture ou certifier_avoir)
5. Persister la réponse (fne_reference, qr_code_url, numéro normalisé)
6. Générer le QR code (image PNG) pour impression
7. Mettre à jour le solde de stickers
"""
from __future__ import annotations

import base64
import logging
from datetime import date, datetime, timezone
from decimal import Decimal
from io import BytesIO
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.fne_syscohada import (
    FNE_STICKER_PRIX_FNE,
    MAP_MODE_PAIEMENT_FNE,
    FNE_URLS,
    FneEnvironment,
    FneStatut,
    FneVatCode,
    formater_numero_fne,
)
from app.integrations.fne_client import FneApiError, get_fne_client
from app.models.fne import (
    FneApiLog,
    FneConfiguration,
    FneEvent,
    FneInvoice,
    FneStickerBalance,
)
from app.models.sale import CustomerInvoice, CustomerInvoiceLine, CreditNote
from app.schemas.fne import (
    FneCancelRequest,
    FneCertificationRequest,
    FneCertificationResult,
    FneConfigCreate,
    FneConfigUpdate,
    FneInvoiceOut,
    FneRefundRequest,
    FneStatsOut,
    FneStickerBalanceOut,
)
from app.services.audit_service import AuditService

logger = logging.getLogger(__name__)


class FneService:
    def __init__(self, db: AsyncSession, tenant_id: UUID, user_id: UUID) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.audit = AuditService(db)

    # ═════════════════════════════════════════════════════════════════════
    # CONFIGURATION
    # ═════════════════════════════════════════════════════════════════════
    async def creer_configuration(self, data: FneConfigCreate) -> FneConfiguration:
        existing = await self.db.scalar(
            select(FneConfiguration).where(
                FneConfiguration.tenant_id == self.tenant_id,
                FneConfiguration.active.is_(True),
            )
        )
        if existing:
            # Désactiver l'ancienne
            existing.active = False

        base_url = data.base_url or FNE_URLS.get(data.environnement, FNE_URLS[FneEnvironment.SANDBOX])

        config = FneConfiguration(
            tenant_id=self.tenant_id,
            ncc=data.ncc,
            centre_rattachement=data.centre_rattachement,
            regime_imposition=data.regime_imposition,
            environnement=data.environnement,
            base_url=base_url,
            api_key=data.api_key,   # TODO: chiffrer en DB via colonne encryptée
            entity_id=data.entity_id,
            template_defaut=data.template_defaut,
            prefixe_reference=data.prefixe_reference,
            active=True,
        )
        self.db.add(config)
        await self.db.flush()

        # Initialiser le solde stickers
        existing_sticker = await self.db.scalar(
            select(FneStickerBalance).where(FneStickerBalance.tenant_id == self.tenant_id)
        )
        if existing_sticker is None:
            self.db.add(FneStickerBalance(tenant_id=self.tenant_id))
            await self.db.flush()

        await self.audit.log(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            action="FNE_CONFIG_CREATE",
            ressource="fne_configuration",
            ressource_id=config.id,
            payload={"ncc": config.ncc, "env": config.environnement},
        )
        return config

    async def modifier_configuration(
        self, config_id: UUID, data: FneConfigUpdate
    ) -> FneConfiguration:
        config = await self._get_config(config_id)
        for k, v in data.model_dump(exclude_unset=True).items():
            setattr(config, k, v)
        await self.db.flush()
        return config

    async def get_configuration_active(self) -> FneConfiguration:
        config = await self.db.scalar(
            select(FneConfiguration).where(
                FneConfiguration.tenant_id == self.tenant_id,
                FneConfiguration.active.is_(True),
            )
        )
        if config is None:
            raise HTTPException(404, "Aucune configuration FNE active. Configurez d'abord l'interfaçage DGI.")
        return config

    # ═════════════════════════════════════════════════════════════════════
    # CERTIFICATION FACTURE
    # ═════════════════════════════════════════════════════════════════════
    async def certifier_facture(
        self, data: FneCertificationRequest
    ) -> FneCertificationResult:
        """
        Certifie une facture client auprès de la DGI.
        Idempotent : si déjà certifiée, retourne le résultat existant.
        """
        config = await self.get_configuration_active()

        # Récupérer la facture
        invoice = await self.db.scalar(
            select(CustomerInvoice).where(
                CustomerInvoice.id == data.customer_invoice_id,
                CustomerInvoice.tenant_id == self.tenant_id,
            )
        )
        if invoice is None:
            raise HTTPException(404, "Facture client introuvable")
        if invoice.statut not in ("validee", "partiellement_payee", "payee"):
            raise HTTPException(400, f"Facture en statut '{invoice.statut}' — non certifiable")

        # Idempotence
        existing = await self.db.scalar(
            select(FneInvoice).where(
                FneInvoice.tenant_id == self.tenant_id,
                FneInvoice.customer_invoice_id == invoice.id,
            )
        )
        if existing and existing.statut == FneStatut.CERTIFIEE:
            return FneCertificationResult(
                fne_invoice=FneInvoiceOut.model_validate(existing),
                success=True,
                message="Facture déjà certifiée",
                qr_code_url=existing.qr_code_url,
                numero_normalise=existing.numero_normalise,
            )

        # Vérifier solde stickers
        await self._verifier_solde_stickers(min_requis=1)

        # Construire le payload
        payload = await self._construire_payload_facture(
            invoice, config, data.template or config.template_defaut
        )

        # Créer/mettre à jour l'enregistrement FNE
        fne_inv = existing or FneInvoice(
            tenant_id=self.tenant_id,
            customer_invoice_id=invoice.id,
            configuration_id=config.id,
            document_type="invoice",
            template=payload["template"],
            annee_edition=date.today().year,
            statut=FneStatut.BROUILLON,
        )
        fne_inv.payload_envoye = payload
        fne_inv.date_soumission = datetime.now(timezone.utc)
        fne_inv.nb_tentatives += 1
        fne_inv.statut = FneStatut.EN_ATTENTE
        self.db.add(fne_inv)
        await self.db.flush()

        # Appeler l'API FNE
        correlation_id = str(uuid4())
        client = get_fne_client(
            base_url=config.base_url,
            api_key=config.api_key,
            environnement=config.environnement,
            entity_id=config.entity_id,
        )

        try:
            response = await client.certifier_facture(payload, correlation_id)
        except FneApiError as exc:
            fne_inv.statut = FneStatut.ERROR
            fne_inv.derniere_erreur = f"[{exc.status_code}] {exc}"
            await self._log_api_call(
                fne_inv, "POST", "/external/invoices", payload,
                exc.status_code, exc.payload, exc.error_code, str(exc), correlation_id,
            )
            await self.db.flush()
            raise HTTPException(
                502,
                f"Erreur FNE : {exc.payload.get('message', str(exc))}",
            )

        # Succès
        await self._appliquer_reponse_certification(fne_inv, response, config)

        await self._log_api_call(
            fne_inv, "POST", "/external/invoices", payload,
            200, response, None, None, correlation_id,
        )

        # Décrémenter les stickers
        await self._consommer_sticker(1)

        await self.audit.log(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            action="FNE_CERTIFY_INVOICE",
            ressource="fne_invoice",
            ressource_id=fne_inv.id,
            payload={
                "reference": fne_inv.fne_reference,
                "numero_normalise": fne_inv.numero_normalise,
            },
        )
        await self.db.flush()

        return FneCertificationResult(
            fne_invoice=FneInvoiceOut.model_validate(fne_inv),
            success=True,
            message="Facture certifiée avec succès",
            balance_stickers_restant=response.get("balance_sticker"),
            qr_code_url=fne_inv.qr_code_url,
            numero_normalise=fne_inv.numero_normalise,
        )

    # ═════════════════════════════════════════════════════════════════════
    # CERTIFICATION AVOIR
    # ═════════════════════════════════════════════════════════════════════
    async def certifier_avoir(
        self, data: FneRefundRequest
    ) -> FneCertificationResult:
        """
        Certifie un avoir lié à une facture déjà certifiée.
        """
        config = await self.get_configuration_active()

        credit_note = await self.db.scalar(
            select(CreditNote).where(
                CreditNote.id == data.credit_note_id,
                CreditNote.tenant_id == self.tenant_id,
            )
        )
        if credit_note is None:
            raise HTTPException(404, "Avoir introuvable")

        fne_origin = await self.db.scalar(
            select(FneInvoice).where(
                FneInvoice.id == data.fne_invoice_id,
                FneInvoice.tenant_id == self.tenant_id,
            )
        )
        if fne_origin is None or fne_origin.statut != FneStatut.CERTIFIEE:
            raise HTTPException(400, "La facture d'origine n'est pas certifiée")

        if not fne_origin.fne_id:
            raise HTTPException(500, "Facture d'origine sans identifiant FNE")

        await self._verifier_solde_stickers(min_requis=1)

        # Payload avoir
        payload = await self._construire_payload_avoir(credit_note, fne_origin)

        fne_refund = FneInvoice(
            tenant_id=self.tenant_id,
            customer_invoice_id=fne_origin.customer_invoice_id,
            configuration_id=config.id,
            document_type="refund",
            template=fne_origin.template,
            annee_edition=date.today().year,
            statut=FneStatut.EN_ATTENTE,
            payload_envoye=payload,
            date_soumission=datetime.now(timezone.utc),
            nb_tentatives=1,
        )
        self.db.add(fne_refund)
        await self.db.flush()

        correlation_id = str(uuid4())
        client = get_fne_client(
            base_url=config.base_url, api_key=config.api_key,
            environnement=config.environnement, entity_id=config.entity_id,
        )

        try:
            response = await client.certifier_avoir(fne_origin.fne_id, payload, correlation_id)
        except FneApiError as exc:
            fne_refund.statut = FneStatut.ERROR
            fne_refund.derniere_erreur = f"[{exc.status_code}] {exc}"
            await self._log_api_call(
                fne_refund, "POST", f"/external/invoices/{fne_origin.fne_id}/refund",
                payload, exc.status_code, exc.payload, exc.error_code, str(exc), correlation_id,
            )
            await self.db.flush()
            raise HTTPException(502, f"Erreur FNE avoir : {exc}")

        await self._appliquer_reponse_certification(fne_refund, response, config)
        await self._log_api_call(
            fne_refund, "POST", f"/external/invoices/{fne_origin.fne_id}/refund",
            payload, 200, response, None, None, correlation_id,
        )
        await self._consommer_sticker(1)

        await self.db.flush()
        return FneCertificationResult(
            fne_invoice=FneInvoiceOut.model_validate(fne_refund),
            success=True,
            message="Avoir certifié avec succès",
            qr_code_url=fne_refund.qr_code_url,
            numero_normalise=fne_refund.numero_normalise,
        )

    # ═════════════════════════════════════════════════════════════════════
    # ANNULATION
    # ═════════════════════════════════════════════════════════════════════
    async def annuler_facture(
        self, fne_invoice_id: UUID, data: FneCancelRequest
    ) -> FneInvoiceOut:
        config = await self.get_configuration_active()
        fne_inv = await self._get_fne_invoice(fne_invoice_id)
        if fne_inv.statut != FneStatut.CERTIFIEE:
            raise HTTPException(400, "Seule une facture certifiée peut être annulée")
        if not fne_inv.fne_id:
            raise HTTPException(500, "Facture sans identifiant FNE")

        client = get_fne_client(
            base_url=config.base_url, api_key=config.api_key,
            environnement=config.environnement, entity_id=config.entity_id,
        )
        correlation_id = str(uuid4())

        try:
            await client.annuler_facture(fne_inv.fne_id, data.motif, correlation_id)
        except FneApiError as exc:
            raise HTTPException(502, f"Erreur annulation FNE : {exc}")

        fne_inv.statut = FneStatut.ANNULEE
        fne_inv.date_annulation = datetime.now(timezone.utc)
        await self.db.flush()

        await self.audit.log(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            action="FNE_CANCEL_INVOICE",
            ressource="fne_invoice",
            ressource_id=fne_inv.id,
            payload={"motif": data.motif},
        )
        return FneInvoiceOut.model_validate(fne_inv)

    # ═════════════════════════════════════════════════════════════════════
    # CONSTRUCTION PAYLOAD
    # ═════════════════════════════════════════════════════════════════════
    async def _construire_payload_facture(
        self, invoice: CustomerInvoice, config: FneConfiguration, template: str
    ) -> dict[str, Any]:
        """
        Construit le payload JSON attendu par l'API FNE.
        Format conforme à la doc DGI (FNE-procedureapi.pdf).
        """
        # Récupérer les lignes
        lines = (
            await self.db.execute(
                select(CustomerInvoiceLine).where(
                    CustomerInvoiceLine.invoice_id == invoice.id
                ).order_by(CustomerInvoiceLine.ordre)
            )
        ).scalars().all()

        # Récupérer le client
        from app.models.sale import Customer
        customer = await self.db.scalar(
            select(Customer).where(Customer.id == invoice.customer_id)
        )

        # Construire les items
        items: list[dict[str, Any]] = []
        for l in lines:
            amount_ht = int(l.montant_ht)
            vat_amount = int(l.montant_tva)
            items.append({
                "reference": f"ITEM-{l.id}",
                "description": l.designation[:200],
                "quantity": float(l.quantite),
                "amount": amount_ht,                    # prix unitaire HT
                "discount": int(l.remise_ligne),
                "measurementUnit": l.unite,
                "taxes": [
                    {
                        "amount": float(l.taux_tva) * 100,
                        "name": "TVA normal - TVA sur HT 18,00% - A" if l.taux_tva >= 0.17
                                else "TVA réduit - 9,00%",
                        "shortName": "TVA",
                    }
                ] if l.taux_tva > 0 else [],
            })

        # Mode de paiement
        payment_method = MAP_MODE_PAIEMENT_FNE.get(
            customer.mode_encaissement_defaut if customer else "virement",
            "other",
        )

        payload = {
            "ncc": config.ncc,
            "template": template,
            "type": "invoice",
            "subtype": "normal",
            "reference": invoice.numero,
            "date": invoice.date_facture.isoformat() + "T00:00:00.000Z",
            "paymentMethod": payment_method,
            "amount": int(invoice.total_ttc),
            "vatAmount": int(invoice.total_tva),
            "fiscalStamp": 0,
            "discount": int(invoice.remise_globale),
            "clientNcc": customer.compte_contribuable if customer else None,
            "clientCompanyName": customer.raison_sociale if customer else None,
            "clientPhone": customer.telephone if customer else None,
            "clientEmail": customer.email if customer else None,
            "clientPointOfSale": None,
            "status": "paid" if invoice.solde_du == 0 else "pending",
            "description": invoice.notes or invoice.numero,
            "items": items,
        }
        return payload

    async def _construire_payload_avoir(
        self, credit_note: CreditNote, fne_origin: FneInvoice
    ) -> dict[str, Any]:
        """Payload avoir : référence la facture d'origine + lignes concernées."""
        from app.models.sale import CreditNoteLine
        lines = (
            await self.db.execute(
                select(CreditNoteLine).where(
                    CreditNoteLine.credit_note_id == credit_note.id
                )
            )
        ).scalars().all()

        items: list[dict[str, Any]] = []
        for l in lines:
            items.append({
                "id": str(l.invoice_line_id) if l.invoice_line_id else str(l.id),
                "quantity": float(l.quantite),
                "amount": int(l.montant_ht),
                "reference": f"REF-{l.id}",
                "description": l.designation[:200],
            })

        return {
            "type": "refund",
            "reference": credit_note.numero,
            "date": credit_note.date_avoir.isoformat() + "T00:00:00.000Z",
            "motif": credit_note.motif,
            "amount": int(credit_note.total_ttc),
            "vatAmount": int(credit_note.total_tva),
            "items": items,
        }

    # ═════════════════════════════════════════════════════════════════════
    # APPLICATION RÉPONSE
    # ═════════════════════════════════════════════════════════════════════
    async def _appliquer_reponse_certification(
        self, fne_inv: FneInvoice, response: dict[str, Any], config: FneConfiguration
    ) -> None:
        """Applique la réponse DGI à l'enregistrement FNE."""
        fne_inv.fne_id = response.get("id")
        fne_inv.fne_reference = response.get("reference")
        fne_inv.fne_token = response.get("token")
        fne_inv.qr_code_url = response.get("token")   # L'URL est le token
        fne_inv.fiscal_stamp = response.get("fiscalStamp")
        fne_inv.numero_normalise = response.get("reference")
        fne_inv.reponse_dgi = response
        fne_inv.statut = FneStatut.CERTIFIEE
        fne_inv.date_certification = datetime.now(timezone.utc)
        fne_inv.balance_sticker_apres = response.get("balance_sticker")
        fne_inv.sticker_consomme = True

        # Extraire la séquence si possible
        ref = response.get("reference", "")
        if ref and len(ref) >= 9:
            try:
                # NCC + AAAA + séquence
                fne_inv.sequence_annuelle = int(ref[-9:])
            except (ValueError, IndexError):
                pass

        await self.db.flush()

    # ═════════════════════════════════════════════════════════════════════
    # STICKERS
    # ═════════════════════════════════════════════════════════════════════
    async def _verifier_solde_stickers(self, min_requis: int = 1) -> FneStickerBalance:
        balance = await self.db.scalar(
            select(FneStickerBalance).where(FneStickerBalance.tenant_id == self.tenant_id)
        )
        if balance is None:
            balance = FneStickerBalance(tenant_id=self.tenant_id)
            self.db.add(balance)
            await self.db.flush()
        if balance.balance_total < min_requis:
            raise HTTPException(
                402,
                f"Solde de stickers insuffisant ({balance.balance_total}). "
                f"Rechargez votre solde sur le portail FNE.",
            )
        return balance

    async def _consommer_sticker(self, nb: int = 1) -> None:
        balance = await self.db.scalar(
            select(FneStickerBalance).where(FneStickerBalance.tenant_id == self.tenant_id)
        )
        if balance is None:
            return
        balance.balance_fne = max(0, balance.balance_fne - nb)
        balance.balance_total = balance.balance_fne + balance.balance_rne
        balance.derniere_consommation_at = datetime.now(timezone.utc)
        await self.db.flush()

    async def synchroniser_balance_stickers(self) -> FneStickerBalanceOut:
        """Récupère le solde réel depuis l'API FNE."""
        config = await self.get_configuration_active()
        client = get_fne_client(
            base_url=config.base_url, api_key=config.api_key,
            environnement=config.environnement, entity_id=config.entity_id,
        )
        try:
            response = await client.get_balance_stickers()
        except FneApiError as exc:
            raise HTTPException(502, f"Erreur sync stickers FNE : {exc}")

        balance = await self.db.scalar(
            select(FneStickerBalance).where(FneStickerBalance.tenant_id == self.tenant_id)
        )
        if balance is None:
            balance = FneStickerBalance(tenant_id=self.tenant_id)
            self.db.add(balance)

        balance.balance_fne = int(response.get("balance_fne", 0))
        balance.balance_rne = int(response.get("balance_rne", 0))
        balance.balance_total = int(response.get("balance_total",
                                                 balance.balance_fne + balance.balance_rne))
        balance.derniere_sync_at = datetime.now(timezone.utc)
        await self.db.flush()

        return FneStickerBalanceOut.model_validate(balance)

    # ═════════════════════════════════════════════════════════════════════
    # LOGS API
    # ═════════════════════════════════════════════════════════════════════
    async def _log_api_call(
        self,
        fne_inv: FneInvoice | None,
        methode: str,
        path: str,
        payload: dict[str, Any] | None,
        statut_http: int | None,
        reponse: dict[str, Any] | None,
        error_code: str | None,
        error_message: str | None,
        correlation_id: str,
        latence_ms: int | None = None,
    ) -> None:
        log = FneApiLog(
            tenant_id=self.tenant_id,
            fne_invoice_id=fne_inv.id if fne_inv else None,
            methode=methode,
            url=path,
            payload_envoye=payload,
            statut_http=statut_http,
            reponse_body=reponse,
            error_code=error_code,
            error_message=error_message,
            latence_ms=latence_ms,
            correlation_id=correlation_id,
            created_by=self.user_id,
        )
        self.db.add(log)
        await self.db.flush()

    # ═════════════════════════════════════════════════════════════════════
    # STATISTIQUES
    # ═════════════════════════════════════════════════════════════════════
    async def get_stats(self) -> FneStatsOut:
        # Compter par statut
        rows = (
            await self.db.execute(
                select(FneInvoice.statut, func.count(FneInvoice.id))
                .where(FneInvoice.tenant_id == self.tenant_id)
                .group_by(FneInvoice.statut)
            )
        ).all()
        counts = {r[0]: int(r[1]) for r in rows}

        # Stickers
        balance = await self.db.scalar(
            select(FneStickerBalance).where(FneStickerBalance.tenant_id == self.tenant_id)
        )

        # Latence moyenne
        latence = await self.db.scalar(
            select(func.avg(FneApiLog.latence_ms)).where(
                FneApiLog.tenant_id == self.tenant_id,
                FneApiLog.statut_http == 200,
            )
        )

        # Dernière certification
        derniere = await self.db.scalar(
            select(func.max(FneInvoice.date_certification)).where(
                FneInvoice.tenant_id == self.tenant_id,
            )
        )

        total_cert = counts.get("certifiee", 0) + counts.get("rejetee", 0)
        taux = (counts.get("certifiee", 0) / total_cert * 100) if total_cert else 0.0

        # Stickers consommés ce mois
        debut_mois = date.today().replace(day=1)
        stickers_mois = int(await self.db.scalar(
            select(func.count(FneInvoice.id)).where(
                FneInvoice.tenant_id == self.tenant_id,
                FneInvoice.sticker_consomme.is_(True),
                FneInvoice.date_certification >= datetime.combine(debut_mois, datetime.min.time()).replace(tzinfo=timezone.utc),
            )
        ) or 0)

        return FneStatsOut(
            tenant_id=self.tenant_id,
            nb_factures_certifiees=counts.get("certifiee", 0),
            nb_factures_en_attente=counts.get("en_attente", 0),
            nb_factures_rejetees=counts.get("rejetee", 0),
            nb_avoirs_certifies=0,   # TODO: distinguer par document_type
            stickers_consommes_mois=stickers_mois,
            balance_stickers=balance.balance_total if balance else 0,
            taux_succes_pct=round(taux, 2),
            latence_moyenne_ms=int(latence) if latence else None,
            derniere_certification_at=derniere,
        )

    # ═════════════════════════════════════════════════════════════════════
    # HELPERS
    # ═════════════════════════════════════════════════════════════════════
    async def _get_config(self, config_id: UUID) -> FneConfiguration:
        c = await self.db.scalar(
            select(FneConfiguration).where(
                FneConfiguration.id == config_id,
                FneConfiguration.tenant_id == self.tenant_id,
            )
        )
        if c is None:
            raise HTTPException(404, "Configuration FNE introuvable")
        return c

    async def _get_fne_invoice(self, fne_id: UUID) -> FneInvoice:
        f = await self.db.scalar(
            select(FneInvoice).where(
                FneInvoice.id == fne_id,
                FneInvoice.tenant_id == self.tenant_id,
            )
        )
        if f is None:
            raise HTTPException(404, "Facture FNE introuvable")
        return f
