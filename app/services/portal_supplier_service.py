"""
Service Espace Fournisseur — Consultation commandes, soumission factures.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.portal_syscohada import StatutSoumissionFacture
from app.models.portal import (
    PortalNotification,
    PortalUser,
    SupplierInvoiceSubmission,
)
from app.models.purchase import (
    PurchaseOrder,
    Supplier,
    SupplierInvoice,
    SupplierPayment,
)
from app.schemas.portal import (
    SupplierInvoiceSubmissionIn,
    SupplierInvoiceSubmissionOut,
    SupplierOrderOut,
    SupplierPortalDashboard,
)
from app.services.audit_service import AuditService

logger = logging.getLogger(__name__)


class PortalSupplierService:
    def __init__(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        portal_user: PortalUser,
    ) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self.portal_user = portal_user
        self.supplier_id = portal_user.supplier_id

        if self.supplier_id is None:
            raise HTTPException(403, "Utilisateur portail non rattaché à un fournisseur")

    # ═════════════════════════════════════════════════════════════════════
    # DASHBOARD
    # ═════════════════════════════════════════════════════════════════════
    async def dashboard(self) -> SupplierPortalDashboard:
        supplier = await self._get_supplier()
        today = date.today()

        # Commandes en cours
        nb_commandes = int(await self.db.scalar(
            select(func.count(PurchaseOrder.id)).where(
                PurchaseOrder.tenant_id == self.tenant_id,
                PurchaseOrder.supplier_id == self.supplier_id,
                PurchaseOrder.statut.in_(["validee", "partiellement_recue"]),
            )
        ) or 0)

        montant_commandes = int(await self.db.scalar(
            select(func.coalesce(func.sum(PurchaseOrder.total_ht), 0)).where(
                PurchaseOrder.tenant_id == self.tenant_id,
                PurchaseOrder.supplier_id == self.supplier_id,
                PurchaseOrder.statut.in_(["validee", "partiellement_recue"]),
            )
        ) or 0)

        # Factures en attente (soumissions)
        nb_attente = int(await self.db.scalar(
            select(func.count(SupplierInvoiceSubmission.id)).where(
                SupplierInvoiceSubmission.tenant_id == self.tenant_id,
                SupplierInvoiceSubmission.supplier_id == self.supplier_id,
                SupplierInvoiceSubmission.statut.in_(["soumise", "en_revision"]),
            )
        ) or 0)

        montant_attente = int(await self.db.scalar(
            select(func.coalesce(func.sum(SupplierInvoiceSubmission.montant_ht), 0)).where(
                SupplierInvoiceSubmission.tenant_id == self.tenant_id,
                SupplierInvoiceSubmission.supplier_id == self.supplier_id,
                SupplierInvoiceSubmission.statut.in_(["soumise", "en_revision"]),
            )
        ) or 0)

        # Paiements reçus ce mois
        debut_mois = today.replace(day=1)
        nb_payes = int(await self.db.scalar(
            select(func.count(SupplierPayment.id)).where(
                SupplierPayment.tenant_id == self.tenant_id,
                SupplierPayment.supplier_id == self.supplier_id,
                SupplierPayment.date_paiement >= debut_mois,
                SupplierPayment.statut == "valide",
            )
        ) or 0)

        montant_recu = int(await self.db.scalar(
            select(func.coalesce(func.sum(SupplierPayment.montant), 0)).where(
                SupplierPayment.tenant_id == self.tenant_id,
                SupplierPayment.supplier_id == self.supplier_id,
                SupplierPayment.date_paiement >= debut_mois,
                SupplierPayment.statut == "valide",
            )
        ) or 0)

        # Prochaine livraison
        prochaine_livraison = await self.db.scalar(
            select(func.min(PurchaseOrder.date_livraison_prevue)).where(
                PurchaseOrder.tenant_id == self.tenant_id,
                PurchaseOrder.supplier_id == self.supplier_id,
                PurchaseOrder.statut.in_(["validee", "partiellement_recue"]),
                PurchaseOrder.date_livraison_prevue >= today,
            )
        )

        # Dernière commande
        derniere_commande = await self.db.scalar(
            select(PurchaseOrder)
            .where(
                PurchaseOrder.tenant_id == self.tenant_id,
                PurchaseOrder.supplier_id == self.supplier_id,
            )
            .order_by(PurchaseOrder.date_commande.desc())
            .limit(1)
        )

        return SupplierPortalDashboard(
            supplier_id=self.supplier_id,
            supplier_nom=supplier.raison_sociale,
            nb_commandes_en_cours=nb_commandes,
            montant_commandes_en_cours_xof=montant_commandes,
            nb_factures_en_attente=nb_attente,
            montant_factures_en_attente_xof=montant_attente,
            nb_factures_payees_mois=nb_payes,
            montant_recu_mois_xof=montant_recu,
            prochaine_livraison_date=prochaine_livraison,
            derniere_commande={
                "id": str(derniere_commande.id),
                "numero": derniere_commande.numero,
                "date_commande": derniere_commande.date_commande.isoformat(),
                "total_ht": derniere_commande.total_ht,
                "statut": derniere_commande.statut,
            } if derniere_commande else None,
        )

    # ═════════════════════════════════════════════════════════════════════
    # COMMANDES
    # ═════════════════════════════════════════════════════════════════════
    async def lister_commandes(
        self, statut: str | None = None, limit: int = 100
    ) -> list[SupplierOrderOut]:
        stmt = select(PurchaseOrder).where(
            PurchaseOrder.tenant_id == self.tenant_id,
            PurchaseOrder.supplier_id == self.supplier_id,
        )
        if statut:
            stmt = stmt.where(PurchaseOrder.statut == statut)
        stmt = stmt.order_by(PurchaseOrder.date_commande.desc()).limit(limit)
        orders = list((await self.db.execute(stmt)).scalars().all())

        results = []
        for o in orders:
            nb_lignes = int(await self.db.scalar(
                select(func.count()).select_from(
                    select(PurchaseOrder.id).where(PurchaseOrder.id == o.id).subquery()
                )
            ) or 0)
            # Compter les lignes réelles
            from app.models.purchase import PurchaseOrderLine
            nb_lignes = int(await self.db.scalar(
                select(func.count(PurchaseOrderLine.id)).where(PurchaseOrderLine.order_id == o.id)
            ) or 0)

            results.append(SupplierOrderOut(
                id=o.id,
                numero=o.numero,
                date_commande=o.date_commande,
                date_livraison_prevue=o.date_livraison_prevue,
                statut=o.statut,
                total_ht=o.total_ht,
                total_ttc=o.total_ttc,
                nb_lignes=nb_lignes,
                peut_accuser_reception=o.statut == "validee",
                document_url=f"/api/v1/portal/supplier/orders/{o.id}/pdf",
            ))
        return results

    async def accuser_reception_commande(self, order_id: UUID) -> dict[str, Any]:
        """Le fournisseur accuse réception d'une commande."""
        order = await self.db.scalar(
            select(PurchaseOrder).where(
                PurchaseOrder.id == order_id,
                PurchaseOrder.tenant_id == self.tenant_id,
                PurchaseOrder.supplier_id == self.supplier_id,
            )
        )
        if order is None:
            raise HTTPException(404, "Commande introuvable")

        # Marquer metadata
        if order.metadata_ is None:
            order.metadata_ = {}
        order.metadata_["reception_accusee_at"] = datetime.now(timezone.utc).isoformat()
        order.metadata_["reception_accusee_par"] = str(self.portal_user.id)
        await self.db.flush()

        # Notifier le tenant
        self.db.add(PortalNotification(
            tenant_id=self.tenant_id,
            portal_user_id=self.portal_user.id,
            event_type="nouvelle_commande",
            canal="email",
            sujet=f"Commande {order.numero} — réception accusée",
            contenu_texte=f"Le fournisseur {self.portal_user.nom_complet} a accusé réception.",
            envoye=True,
            envoye_at=datetime.now(timezone.utc),
        ))
        await self.db.flush()

        return {"order_id": str(order.id), "accuse_at": order.metadata_["reception_accusee_at"]}

    # ═════════════════════════════════════════════════════════════════════
    # SOUMISSION FACTURE
    # ═════════════════════════════════════════════════════════════════════
    async def soumettre_facture(
        self, data: SupplierInvoiceSubmissionIn
    ) -> SupplierInvoiceSubmissionOut:
        """
        Le fournisseur soumet une facture depuis le portail.
        Elle sera traitée par le tenant (acceptation → SupplierInvoice officielle).
        """
        # Vérifier la commande si fournie
        if data.purchase_order_id:
            order = await self.db.scalar(
                select(PurchaseOrder).where(
                    PurchaseOrder.id == data.purchase_order_id,
                    PurchaseOrder.tenant_id == self.tenant_id,
                    PurchaseOrder.supplier_id == self.supplier_id,   # ISOLATION
                )
            )
            if order is None:
                raise HTTPException(404, "Commande introuvable")

        # Vérifier unicité (numero_fournisseur)
        existing = await self.db.scalar(
            select(SupplierInvoiceSubmission.id).where(
                SupplierInvoiceSubmission.tenant_id == self.tenant_id,
                SupplierInvoiceSubmission.supplier_id == self.supplier_id,
                SupplierInvoiceSubmission.numero_fournisseur == data.numero_fournisseur,
            )
        )
        if existing:
            raise HTTPException(409, f"Facture {data.numero_fournisseur} déjà soumise")

        montant_ttc = data.montant_ht + data.montant_tva

        submission = SupplierInvoiceSubmission(
            tenant_id=self.tenant_id,
            portal_user_id=self.portal_user.id,
            supplier_id=self.supplier_id,
            numero_fournisseur=data.numero_fournisseur,
            purchase_order_id=data.purchase_order_id,
            date_facture=data.date_facture,
            date_echeance=data.date_echeance,
            montant_ht=data.montant_ht,
            montant_tva=data.montant_tva,
            montant_ttc=montant_ttc,
            fichier_url=data.fichier_url,
            fichier_nom=data.fichier_nom,
            lignes=data.lignes,
            statut=StatutSoumissionFacture.SOUMISE,
        )
        self.db.add(submission)
        await self.db.flush()

        # Notifier le tenant (via worker email)
        self.db.add(PortalNotification(
            tenant_id=self.tenant_id,
            portal_user_id=self.portal_user.id,
            event_type="facture_soumise",
            canal="email",
            sujet=f"Nouvelle facture fournisseur : {data.numero_fournisseur}",
            contenu_texte=(
                f"Le fournisseur {self.portal_user.nom_complet} a soumis la facture "
                f"{data.numero_fournisseur} pour {montant_ttc:,} FCFA.".replace(",", " ")
            ),
            action_url=f"/purchases/submissions/{submission.id}",
            action_label="Traiter la facture",
            envoye=True,
            envoye_at=datetime.now(timezone.utc),
        ))
        await self.db.flush()

        return SupplierInvoiceSubmissionOut.model_validate(submission)

    async def lister_soumissions(
        self, statut: str | None = None, limit: int = 100
    ) -> list[SupplierInvoiceSubmissionOut]:
        stmt = select(SupplierInvoiceSubmission).where(
            SupplierInvoiceSubmission.tenant_id == self.tenant_id,
            SupplierInvoiceSubmission.supplier_id == self.supplier_id,
        )
        if statut:
            stmt = stmt.where(SupplierInvoiceSubmission.statut == statut)
        stmt = stmt.order_by(SupplierInvoiceSubmission.created_at.desc()).limit(limit)
        rows = (await self.db.execute(stmt)).scalars().all()
        return [SupplierInvoiceSubmissionOut.model_validate(r) for r in rows]

    # ═════════════════════════════════════════════════════════════════════
    # PAIEMENTS REÇUS
    # ═════════════════════════════════════════════════════════════════════
    async def lister_paiements(
        self, date_debut: date | None = None, date_fin: date | None = None
    ) -> list[dict[str, Any]]:
        stmt = select(SupplierPayment).where(
            SupplierPayment.tenant_id == self.tenant_id,
            SupplierPayment.supplier_id == self.supplier_id,
            SupplierPayment.statut == "valide",
        )
        if date_debut:
            stmt = stmt.where(SupplierPayment.date_paiement >= date_debut)
        if date_fin:
            stmt = stmt.where(SupplierPayment.date_paiement <= date_fin)
        stmt = stmt.order_by(SupplierPayment.date_paiement.desc()).limit(200)

        rows = (await self.db.execute(stmt)).scalars().all()
        return [
            {
                "id": str(p.id),
                "numero": p.numero,
                "date_paiement": p.date_paiement.isoformat(),
                "montant": p.montant,
                "mode_paiement": p.mode_paiement,
                "reference_paiement": p.reference_paiement,
            }
            for p in rows
        ]

    # ═════════════════════════════════════════════════════════════════════
    # HELPERS
    # ═════════════════════════════════════════════════════════════════════
    async def _get_supplier(self) -> Supplier:
        s = await self.db.scalar(
            select(Supplier).where(
                Supplier.id == self.supplier_id,
                Supplier.tenant_id == self.tenant_id,
            )
        )
        if s is None:
            raise HTTPException(404, "Fournisseur introuvable")
        return s
