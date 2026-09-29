"""Modèles SYSCOHADA — Achats, Fournisseurs, Rapprochement 3 voies."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index,
    Integer, Numeric, String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


# ─────────────────────────────────────────────────────────────────────────────
# FOURNISSEUR
# ─────────────────────────────────────────────────────────────────────────────
class Supplier(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Fournisseur (fiche tiers)."""
    __tablename__ = "suppliers"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    code: Mapped[str] = mapped_column(String(20), nullable=False)
    raison_sociale: Mapped[str] = mapped_column(Text, nullable=False)
    forme_juridique: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Identifiants fiscaux
    compte_contribuable: Mapped[str | None] = mapped_column(String(30), nullable=True)
    rccm: Mapped[str | None] = mapped_column(String(30), nullable=True)
    numero_cnps: Mapped[str | None] = mapped_column(String(30), nullable=True)

    # Classification SYSCOHADA
    type_fournisseur: Mapped[str] = mapped_column(
        String(20), nullable=False, default="fournisseur_local", server_default="fournisseur_local"
    )  # fournisseur_local | fournisseur_import | fournisseur_groupe

    # Contact
    telephone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    email: Mapped[str | None] = mapped_column(String(150), nullable=True)
    adresse: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # Conditions commerciales
    delai_paiement_jours: Mapped[int] = mapped_column(
        Integer, nullable=False, default=30, server_default="30"
    )
    plafond_credit: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    mode_paiement_defaut: Mapped[str] = mapped_column(
        String(20), nullable=False, default="virement", server_default="virement"
    )

    # Fiscalité
    assujetti_tva: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    soumis_ras: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )  # retenue à la source
    taux_ras: Mapped[float] = mapped_column(
        Numeric(5, 4), nullable=False, default=0, server_default="0"
    )
    est_resident: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    # État
    solde_comptable: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )  # > 0 = on doit au fournisseur
    encours_commandes: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    actif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_supplier_code"),
        Index("idx_sup_tenant_actif", "tenant_id", "actif"),
        Index("idx_sup_tenant_type", "tenant_id", "type_fournisseur"),
        CheckConstraint("delai_paiement_jours >= 0", name="sup_delai_positif"),
    )

    def __repr__(self) -> str:
        return f"<Supplier {self.code} — {self.raison_sociale}>"


# ─────────────────────────────────────────────────────────────────────────────
# COMMANDE FOURNISSEUR (PO)
# ─────────────────────────────────────────────────────────────────────────────
class PurchaseOrder(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Commande fournisseur."""
    __tablename__ = "purchase_orders"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    supplier_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("suppliers.id"),
        nullable=False,
        index=True,
    )

    numero: Mapped[str] = mapped_column(String(30), nullable=False)
    date_commande: Mapped[date] = mapped_column(Date, nullable=False)
    date_livraison_prevue: Mapped[date | None] = mapped_column(Date, nullable=True)

    statut: Mapped[str] = mapped_column(
        String(30), nullable=False, default="brouillon", server_default="brouillon"
    )

    # Montants (HT)
    total_ht: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    total_tva: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    total_ttc: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    remise_globale: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")

    # Livraison
    adresse_livraison: Mapped[str | None] = mapped_column(Text, nullable=True)
    warehouse_destination_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("warehouses.id"),
        nullable=True,
    )  # lien vers brique 15 (stocks)

    # Traçabilité
    reference_interne: Mapped[str | None] = mapped_column(String(50), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    validee_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    validee_par: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "numero", name="uq_po_numero"),
        Index("idx_po_tenant_date", "tenant_id", "date_commande"),
        Index("idx_po_tenant_statut", "tenant_id", "statut"),
        Index("idx_po_supplier", "supplier_id"),
    )

    def __repr__(self) -> str:
        return f"<PurchaseOrder {self.numero} statut={self.statut}>"


class PurchaseOrderLine(UUIDPrimaryKeyMixin, Base):
    """Ligne de commande fournisseur."""
    __tablename__ = "purchase_order_lines"

    order_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("purchase_orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    item_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("items.id"), nullable=True
    )

    ordre: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    designation: Mapped[str] = mapped_column(Text, nullable=False)
    unite: Mapped[str] = mapped_column(String(10), nullable=False, default="U", server_default="U")

    quantite_commandee: Mapped[float] = mapped_column(Numeric(18, 3), nullable=False)
    quantite_recue: Mapped[float] = mapped_column(
        Numeric(18, 3), nullable=False, default=0, server_default="0"
    )
    quantite_facturee: Mapped[float] = mapped_column(
        Numeric(18, 3), nullable=False, default=0, server_default="0"
    )

    prix_unitaire_ht: Mapped[int] = mapped_column(BigInteger, nullable=False)
    remise_ligne: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    taux_tva: Mapped[float] = mapped_column(
        Numeric(5, 4), nullable=False, default=0.18, server_default="0.18"
    )

    montant_ht: Mapped[int] = mapped_column(BigInteger, nullable=False)
    montant_tva: Mapped[int] = mapped_column(BigInteger, nullable=False)
    montant_ttc: Mapped[int] = mapped_column(BigInteger, nullable=False)

    famille_stock: Mapped[str | None] = mapped_column(String(30), nullable=True)
    compte_achat: Mapped[str | None] = mapped_column(String(10), nullable=True)

    __table_args__ = (
        Index("idx_pol_order", "order_id", "ordre"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# RÉCEPTION (GR)
# ─────────────────────────────────────────────────────────────────────────────
class GoodsReceipt(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Bon de réception fournisseur."""
    __tablename__ = "goods_receipts"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    supplier_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("suppliers.id"),
        nullable=False, index=True,
    )
    purchase_order_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("purchase_orders.id"), nullable=True
    )
    warehouse_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("warehouses.id"),
        nullable=False, index=True,
    )

    numero: Mapped[str] = mapped_column(String(30), nullable=False)
    date_reception: Mapped[date] = mapped_column(Date, nullable=False)
    numero_bl_fournisseur: Mapped[str | None] = mapped_column(String(50), nullable=True)

    statut: Mapped[str] = mapped_column(
        String(20), nullable=False, default="brouillon", server_default="brouillon"
    )

    total_ht: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")

    # Lien vers les mouvements de stock générés (brique 15)
    mouvements_stock_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    validee_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    validee_par: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "numero", name="uq_gr_numero"),
        Index("idx_gr_tenant_date", "tenant_id", "date_reception"),
    )


class GoodsReceiptLine(UUIDPrimaryKeyMixin, Base):
    """Ligne de réception."""
    __tablename__ = "goods_receipt_lines"

    receipt_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("goods_receipts.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    purchase_order_line_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("purchase_order_lines.id"), nullable=True
    )
    item_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("items.id"), nullable=True
    )

    ordre: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    designation: Mapped[str] = mapped_column(Text, nullable=False)

    quantite_commandee: Mapped[float] = mapped_column(Numeric(18, 3), nullable=False, default=0, server_default="0")
    quantite_recue: Mapped[float] = mapped_column(Numeric(18, 3), nullable=False)
    quantite_refusee: Mapped[float] = mapped_column(
        Numeric(18, 3), nullable=False, default=0, server_default="0"
    )

    prix_unitaire_ht: Mapped[int] = mapped_column(BigInteger, nullable=False)
    montant_ht: Mapped[int] = mapped_column(BigInteger, nullable=False)

    famille_stock: Mapped[str | None] = mapped_column(String(30), nullable=True)
    motif_refus: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Lien vers le mouvement de stock créé
    mouvement_stock_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("stock_movements.id"), nullable=True
    )

    __table_args__ = (
        Index("idx_grl_receipt", "receipt_id", "ordre"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# FACTURE FOURNISSEUR
# ─────────────────────────────────────────────────────────────────────────────
class SupplierInvoice(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Facture fournisseur."""
    __tablename__ = "supplier_invoices"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    supplier_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("suppliers.id"),
        nullable=False, index=True,
    )

    # Références fournisseur
    numero_fournisseur: Mapped[str] = mapped_column(String(50), nullable=False)
    numero_interne: Mapped[str] = mapped_column(String(30), nullable=False)  # FF-2025-00001

    date_facture: Mapped[date] = mapped_column(Date, nullable=False)
    date_echeance: Mapped[date] = mapped_column(Date, nullable=False)
    date_reception_facture: Mapped[date] = mapped_column(Date, nullable=False)

    # Liens
    purchase_order_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("purchase_orders.id"), nullable=True
    )
    goods_receipt_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("goods_receipts.id"), nullable=True
    )

    statut: Mapped[str] = mapped_column(
        String(30), nullable=False, default="brouillon", server_default="brouillon"
    )

    # Montants
    total_ht: Mapped[int] = mapped_column(BigInteger, nullable=False)
    remise_globale: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    base_ht: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_tva: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_ttc: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Retenue à la source
    ras_appliquee: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    montant_net_a_payer: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Solde (mis à jour à chaque paiement)
    montant_paye: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    solde_du: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Rapprochement 3 voies
    rapprochement_resultat: Mapped[str | None] = mapped_column(String(30), nullable=True)
    rapprochement_detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # Écriture comptable
    ecriture_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("ecritures.id"), nullable=True
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    validee_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    validee_par: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "numero_interne", name="uq_si_numero_interne"),
        UniqueConstraint("tenant_id", "supplier_id", "numero_fournisseur", name="uq_si_num_fourn"),
        Index("idx_si_tenant_date", "tenant_id", "date_facture"),
        Index("idx_si_tenant_echeance", "tenant_id", "date_echeance"),
        Index("idx_si_tenant_statut", "tenant_id", "statut"),
    )

    def __repr__(self) -> str:
        return f"<SupplierInvoice {self.numero_interne} statut={self.statut} du={self.solde_du}>"


class SupplierInvoiceLine(UUIDPrimaryKeyMixin, Base):
    """Ligne de facture fournisseur."""
    __tablename__ = "supplier_invoice_lines"

    invoice_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("supplier_invoices.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    purchase_order_line_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("purchase_order_lines.id"), nullable=True
    )
    goods_receipt_line_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("goods_receipt_lines.id"), nullable=True
    )
    item_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("items.id"), nullable=True
    )

    ordre: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    designation: Mapped[str] = mapped_column(Text, nullable=False)
    unite: Mapped[str] = mapped_column(String(10), nullable=False, default="U", server_default="U")

    quantite: Mapped[float] = mapped_column(Numeric(18, 3), nullable=False)
    prix_unitaire_ht: Mapped[int] = mapped_column(BigInteger, nullable=False)
    remise_ligne: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    taux_tva: Mapped[float] = mapped_column(
        Numeric(5, 4), nullable=False, default=0.18, server_default="0.18"
    )

    montant_ht: Mapped[int] = mapped_column(BigInteger, nullable=False)
    montant_tva: Mapped[int] = mapped_column(BigInteger, nullable=False)
    montant_ttc: Mapped[int] = mapped_column(BigInteger, nullable=False)

    compte_achat: Mapped[str] = mapped_column(String(10), nullable=False)
    famille_stock: Mapped[str | None] = mapped_column(String(30), nullable=True)

    __table_args__ = (
        Index("idx_sil_invoice", "invoice_id", "ordre"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# PAIEMENT FOURNISSEUR
# ─────────────────────────────────────────────────────────────────────────────
class SupplierPayment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Règlement d'une facture fournisseur."""
    __tablename__ = "supplier_payments"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    supplier_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("suppliers.id"),
        nullable=False, index=True,
    )
    invoice_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("supplier_invoices.id"),
        nullable=False, index=True,
    )

    numero: Mapped[str] = mapped_column(String(30), nullable=False)
    date_paiement: Mapped[date] = mapped_column(Date, nullable=False)

    montant: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mode_paiement: Mapped[str] = mapped_column(String(20), nullable=False)
    compte_tresorerie: Mapped[str] = mapped_column(String(10), nullable=False)
    reference_paiement: Mapped[str | None] = mapped_column(String(50), nullable=True)

    statut: Mapped[str] = mapped_column(
        String(20), nullable=False, default="brouillon", server_default="brouillon"
    )

    # Escompte obtenu pour paiement anticipé
    escompte_obtenu: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")

    ecriture_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("ecritures.id"), nullable=True
    )

    created_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "numero", name="uq_sp_numero"),
        Index("idx_sp_tenant_date", "tenant_id", "date_paiement"),
        Index("idx_sp_invoice", "invoice_id"),
    )
