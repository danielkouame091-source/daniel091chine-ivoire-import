"""Modèles SYSCOHADA — Ventes, Clients, Devis, Commandes, BL, Factures, Avoirs."""
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
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


# ─────────────────────────────────────────────────────────────────────────────
# CLIENT
# ─────────────────────────────────────────────────────────────────────────────
class Customer(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Client (fiche tiers)."""
    __tablename__ = "customers"

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

    type_client: Mapped[str] = mapped_column(
        String(20), nullable=False, default="client_local", server_default="client_local"
    )

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
    mode_encaissement_defaut: Mapped[str] = mapped_column(
        String(20), nullable=False, default="virement", server_default="virement"
    )

    # Fiscalité
    assujetti_tva: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    exonere_tva: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    motif_exoneration: Mapped[str | None] = mapped_column(Text, nullable=True)
    soumis_ras: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # État comptable
    solde_comptable: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )  # > 0 = le client nous doit
    encours_commandes: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    depasse_plafond: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # Relances
    derniere_relance_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    niveau_relance_actuel: Mapped[str] = mapped_column(
        String(20), nullable=False, default="aucune", server_default="aucune"
    )

    actif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_customer_code"),
        Index("idx_cust_tenant_actif", "tenant_id", "actif"),
        Index("idx_cust_tenant_type", "tenant_id", "type_client"),
        Index("idx_cust_tenant_solde", "tenant_id", "solde_comptable"),
    )

    def __repr__(self) -> str:
        return f"<Customer {self.code} — {self.raison_sociale} du={self.solde_comptable}>"


# ─────────────────────────────────────────────────────────────────────────────
# DEVIS
# ─────────────────────────────────────────────────────────────────────────────
class Quote(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Devis client."""
    __tablename__ = "quotes"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    customer_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("customers.id"),
        nullable=False, index=True,
    )

    numero: Mapped[str] = mapped_column(String(30), nullable=False)
    date_devis: Mapped[date] = mapped_column(Date, nullable=False)
    date_validite: Mapped[date] = mapped_column(Date, nullable=False)

    statut: Mapped[str] = mapped_column(
        String(20), nullable=False, default="brouillon", server_default="brouillon"
    )

    total_ht: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    total_tva: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    total_ttc: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    remise_globale: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")

    conditions: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Conversion en commande
    commande_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("sales_orders.id"), nullable=True
    )

    created_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "numero", name="uq_quote_numero"),
        Index("idx_quote_tenant_date", "tenant_id", "date_devis"),
    )


class QuoteLine(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "quote_lines"

    quote_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("quotes.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
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

    compte_produit: Mapped[str | None] = mapped_column(String(10), nullable=True)
    famille_stock: Mapped[str | None] = mapped_column(String(30), nullable=True)


# ─────────────────────────────────────────────────────────────────────────────
# COMMANDE CLIENT
# ─────────────────────────────────────────────────────────────────────────────
class SalesOrder(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Commande client."""
    __tablename__ = "sales_orders"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    customer_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("customers.id"),
        nullable=False, index=True,
    )

    numero: Mapped[str] = mapped_column(String(30), nullable=False)
    date_commande: Mapped[date] = mapped_column(Date, nullable=False)
    date_livraison_prevue: Mapped[date | None] = mapped_column(Date, nullable=True)

    statut: Mapped[str] = mapped_column(
        String(30), nullable=False, default="brouillon", server_default="brouillon"
    )

    total_ht: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    total_tva: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    total_ttc: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    remise_globale: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")

    adresse_livraison: Mapped[str | None] = mapped_column(Text, nullable=True)
    warehouse_source_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("warehouses.id"), nullable=True
    )

    reference_client: Mapped[str | None] = mapped_column(String(50), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    confirmee_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmee_par: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "numero", name="uq_so_numero"),
        Index("idx_so_tenant_date", "tenant_id", "date_commande"),
        Index("idx_so_tenant_statut", "tenant_id", "statut"),
    )


class SalesOrderLine(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "sales_order_lines"

    order_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("sales_orders.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    item_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("items.id"), nullable=True
    )

    ordre: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    designation: Mapped[str] = mapped_column(Text, nullable=False)
    unite: Mapped[str] = mapped_column(String(10), nullable=False, default="U", server_default="U")

    quantite_commandee: Mapped[float] = mapped_column(Numeric(18, 3), nullable=False)
    quantite_livree: Mapped[float] = mapped_column(
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

    compte_produit: Mapped[str | None] = mapped_column(String(10), nullable=True)
    famille_stock: Mapped[str | None] = mapped_column(String(30), nullable=True)

    __table_args__ = (
        Index("idx_sol_order", "order_id", "ordre"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# BON DE LIVRAISON
# ─────────────────────────────────────────────────────────────────────────────
class DeliveryNote(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Bon de livraison client — déclenche la sortie de stock."""
    __tablename__ = "delivery_notes"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    customer_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("customers.id"),
        nullable=False, index=True,
    )
    sales_order_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("sales_orders.id"), nullable=True
    )
    warehouse_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("warehouses.id"),
        nullable=False, index=True,
    )

    numero: Mapped[str] = mapped_column(String(30), nullable=False)
    date_livraison: Mapped[date] = mapped_column(Date, nullable=False)
    adresse_livraison: Mapped[str | None] = mapped_column(Text, nullable=True)
    transporteur: Mapped[str | None] = mapped_column(Text, nullable=True)

    statut: Mapped[str] = mapped_column(
        String(20), nullable=False, default="brouillon", server_default="brouillon"
    )

    total_ht: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    mouvements_stock_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    valide_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "numero", name="uq_dn_numero"),
        Index("idx_dn_tenant_date", "tenant_id", "date_livraison"),
    )


class DeliveryNoteLine(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "delivery_note_lines"

    delivery_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("delivery_notes.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    sales_order_line_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("sales_order_lines.id"), nullable=True
    )
    item_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("items.id"), nullable=True
    )

    ordre: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    designation: Mapped[str] = mapped_column(Text, nullable=False)

    quantite_commandee: Mapped[float] = mapped_column(Numeric(18, 3), nullable=False, default=0, server_default="0")
    quantite_livree: Mapped[float] = mapped_column(Numeric(18, 3), nullable=False)
    quantite_refusee: Mapped[float] = mapped_column(
        Numeric(18, 3), nullable=False, default=0, server_default="0"
    )

    prix_unitaire_ht: Mapped[int] = mapped_column(BigInteger, nullable=False)
    montant_ht: Mapped[int] = mapped_column(BigInteger, nullable=False)

    famille_stock: Mapped[str | None] = mapped_column(String(30), nullable=True)
    motif_refus: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Sortie de stock générée
    mouvement_stock_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("stock_movements.id"), nullable=True
    )

    __table_args__ = (
        Index("idx_dnl_delivery", "delivery_id", "ordre"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# FACTURE CLIENT
# ─────────────────────────────────────────────────────────────────────────────
class CustomerInvoice(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Facture client."""
    __tablename__ = "customer_invoices"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    customer_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("customers.id"),
        nullable=False, index=True,
    )

    numero: Mapped[str] = mapped_column(String(30), nullable=False)
    numero_client: Mapped[str | None] = mapped_column(String(50), nullable=True)  # réf. client
    date_facture: Mapped[date] = mapped_column(Date, nullable=False)
    date_echeance: Mapped[date] = mapped_column(Date, nullable=False)

    # Liens
    sales_order_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("sales_orders.id"), nullable=True
    )
    delivery_note_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("delivery_notes.id"), nullable=True
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

    # RAS précomptée par le client (informatif — n'affecte pas le solde client)
    ras_precomptee: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")

    # Solde
    montant_encaisse: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    solde_du: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Relance
    derniere_relance_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    niveau_relance: Mapped[str] = mapped_column(
        String(20), nullable=False, default="aucune", server_default="aucune"
    )
    nb_relances: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    # Écriture
    ecriture_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("ecritures.id"), nullable=True
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    mentions: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)  # mentions obligatoires

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
        UniqueConstraint("tenant_id", "numero", name="uq_ci_numero"),
        Index("idx_ci_tenant_date", "tenant_id", "date_facture"),
        Index("idx_ci_tenant_echeance", "tenant_id", "date_echeance"),
        Index("idx_ci_tenant_statut", "tenant_id", "statut"),
        Index("idx_ci_tenant_solde", "tenant_id", "solde_du"),
    )

    def __repr__(self) -> str:
        return f"<CustomerInvoice {self.numero} statut={self.statut} du={self.solde_du}>"


class CustomerInvoiceLine(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "customer_invoice_lines"

    invoice_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("customer_invoices.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    sales_order_line_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("sales_order_lines.id"), nullable=True
    )
    delivery_note_line_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("delivery_note_lines.id"), nullable=True
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

    compte_produit: Mapped[str] = mapped_column(String(10), nullable=False)
    famille_stock: Mapped[str | None] = mapped_column(String(30), nullable=True)

    __table_args__ = (
        Index("idx_cil_invoice", "invoice_id", "ordre"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# ENCAISSEMENT
# ─────────────────────────────────────────────────────────────────────────────
class CustomerPayment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Encaissement client (règlement d'une facture)."""
    __tablename__ = "customer_payments"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    customer_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("customers.id"),
        nullable=False, index=True,
    )
    invoice_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("customer_invoices.id"),
        nullable=False, index=True,
    )

    numero: Mapped[str] = mapped_column(String(30), nullable=False)
    date_encaissement: Mapped[date] = mapped_column(Date, nullable=False)

    montant: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mode_encaissement: Mapped[str] = mapped_column(String(20), nullable=False)
    compte_tresorerie: Mapped[str] = mapped_column(String(10), nullable=False)
    reference_encaissement: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Lien Mobile Money (brique 2)
    mm_transaction_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("mm_transactions.id"), nullable=True
    )

    statut: Mapped[str] = mapped_column(
        String(20), nullable=False, default="brouillon", server_default="brouillon"
    )

    # Escompte accordé pour paiement anticipé
    escompte_accorde: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")

    ecriture_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("ecritures.id"), nullable=True
    )
    created_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "numero", name="uq_cp_numero"),
        Index("idx_cp_tenant_date", "tenant_id", "date_encaissement"),
        Index("idx_cp_invoice", "invoice_id"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# AVOIR CLIENT
# ─────────────────────────────────────────────────────────────────────────────
class CreditNote(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Avoir client — note de crédit (retour marchandise, geste commercial, erreur de facturation).
    Génère une écriture inverse de la facture.
    """
    __tablename__ = "credit_notes"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    customer_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("customers.id"),
        nullable=False, index=True,
    )
    invoice_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("customer_invoices.id"), nullable=True
    )

    numero: Mapped[str] = mapped_column(String(30), nullable=False)
    date_avoir: Mapped[date] = mapped_column(Date, nullable=False)
    motif: Mapped[str] = mapped_column(Text, nullable=False)
    type_avoir: Mapped[str] = mapped_column(
        String(20), nullable=False, default="retour", server_default="retour"
    )  # retour | geste_commercial | erreur_facturation

    statut: Mapped[str] = mapped_column(
        String(20), nullable=False, default="brouillon", server_default="brouillon"
    )

    total_ht: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_tva: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_ttc: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Imputation
    montant_impute: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    montant_rembourse: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    reste_a_imputer: Mapped[int] = mapped_column(BigInteger, nullable=False)

    ecriture_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("ecritures.id"), nullable=True
    )
    created_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "numero", name="uq_cn_numero"),
        Index("idx_cn_tenant_date", "tenant_id", "date_avoir"),
    )


class CreditNoteLine(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "credit_note_lines"

    credit_note_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("credit_notes.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    invoice_line_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("customer_invoice_lines.id"), nullable=True
    )
    item_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("items.id"), nullable=True
    )

    ordre: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    designation: Mapped[str] = mapped_column(Text, nullable=False)

    quantite: Mapped[float] = mapped_column(Numeric(18, 3), nullable=False)
    prix_unitaire_ht: Mapped[int] = mapped_column(BigInteger, nullable=False)
    taux_tva: Mapped[float] = mapped_column(
        Numeric(5, 4), nullable=False, default=0.18, server_default="0.18"
    )

    montant_ht: Mapped[int] = mapped_column(BigInteger, nullable=False)
    montant_tva: Mapped[int] = mapped_column(BigInteger, nullable=False)
    montant_ttc: Mapped[int] = mapped_column(BigInteger, nullable=False)

    compte_produit: Mapped[str] = mapped_column(String(10), nullable=False)
    reintegrer_stock: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    __table_args__ = (
        Index("idx_cnl_cn", "credit_note_id", "ordre"),
    )
