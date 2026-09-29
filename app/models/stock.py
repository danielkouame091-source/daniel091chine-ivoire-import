"""Modèles de gestion des stocks SYSCOHADA."""
from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index,
    Integer, Numeric, String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.tenant import Tenant


# ─────────────────────────────────────────────────────────────────────────────
# Catalogue
# ─────────────────────────────────────────────────────────────────────────────
class ItemCategory(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Catégorie d'articles (famille produit)."""
    __tablename__ = "item_categories"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    libelle: Mapped[str] = mapped_column(Text, nullable=False)
    parent_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("item_categories.id"), nullable=True
    )
    actif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_item_cat_code"),
    )


class Warehouse(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Entrepôt / dépôt / magasin."""
    __tablename__ = "warehouses"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    libelle: Mapped[str] = mapped_column(Text, nullable=False)
    adresse: Mapped[str | None] = mapped_column(Text, nullable=True)
    responsable: Mapped[str | None] = mapped_column(Text, nullable=True)
    actif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    est_principal: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_warehouse_code"),
    )


class Item(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Article / produit / matière."""
    __tablename__ = "items"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    category_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("item_categories.id"), nullable=True
    )

    code: Mapped[str] = mapped_column(String(30), nullable=False)
    code_barre: Mapped[str | None] = mapped_column(String(50), nullable=True)
    designation: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Unité de mesure
    unite: Mapped[str] = mapped_column(
        String(10), nullable=False, default="U", server_default="U"
    )  # U, kg, L, m, carton...

    # Famille SYSCOHADA (pour déterminer le compte de stock)
    famille_stock: Mapped[str] = mapped_column(
        String(30), nullable=False, default="marchandises", server_default="marchandises"
    )  # marchandises | matieres_premieres | produits_finis | ...

    # Méthode de valorisation
    methode_valorisation: Mapped[str] = mapped_column(
        String(10), nullable=False, default="cump", server_default="cump"
    )  # cump | fifo | peps

    # Seuils d'alerte
    seuil_alerte: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    seuil_reappro: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    # Prix
    prix_achat_ht: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    prix_vente_ht: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    taux_tva: Mapped[float] = mapped_column(
        Numeric(4, 2), nullable=False, default=0.18, server_default="0.18"
    )

    # Gestion
    gere_en_stock: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    lot_obligatoire: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    peremption_obligatoire: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    actif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_item_code"),
        Index("idx_item_tenant_actif", "tenant_id", "actif"),
        Index("idx_item_tenant_famille", "tenant_id", "famille_stock"),
        CheckConstraint(
            "methode_valorisation IN ('cump','fifo','peps')",
            name="item_methode_valide",
        ),
    )

    def __repr__(self) -> str:
        return f"<Item {self.code} — {self.designation}>"


# ─────────────────────────────────────────────────────────────────────────────
# Niveaux de stock (cache + valorisation courante)
# ─────────────────────────────────────────────────────────────────────────────
class StockLevel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    État courant du stock par article + entrepôt.
    Mis à jour à chaque mouvement. Contient le CUMP courant (pour les articles en CUMP).
    """
    __tablename__ = "stock_levels"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    item_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    warehouse_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("warehouses.id"),
        nullable=False,
        index=True,
    )

    quantite: Mapped[float] = mapped_column(
        Numeric(18, 3), nullable=False, default=0, server_default="0"
    )
    # CUMP courant (pour méthode CUMP)
    cump: Mapped[float] = mapped_column(
        Numeric(18, 4), nullable=False, default=0, server_default="0"
    )
    # Valeur totale du stock = quantite × cump
    valeur_stock: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )

    dernier_mouvement_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "item_id", "warehouse_id", name="uq_stock_level"),
        Index("idx_stock_level_item_wh", "item_id", "warehouse_id"),
    )

    def __repr__(self) -> str:
        return f"<StockLevel item={self.item_id} wh={self.warehouse_id} qty={self.quantite}>"


# ─────────────────────────────────────────────────────────────────────────────
# Mouvements de stock
# ─────────────────────────────────────────────────────────────────────────────
class StockMovement(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Mouvement de stock (entrée, sortie, transfert)."""
    __tablename__ = "stock_movements"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    numero: Mapped[str] = mapped_column(String(30), nullable=False)
    date_mouvement: Mapped[date] = mapped_column(Date, nullable=False)
    type_mouvement: Mapped[str] = mapped_column(String(30), nullable=False)

    item_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("items.id"),
        nullable=False,
        index=True,
    )
    warehouse_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("warehouses.id"),
        nullable=False,
        index=True,
    )
    warehouse_destination_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("warehouses.id"),
        nullable=True,
    )  # pour les transferts

    quantite: Mapped[float] = mapped_column(Numeric(18, 3), nullable=False)
    prix_unitaire: Mapped[int] = mapped_column(BigInteger, nullable=False)   # prix unitaire d'entrée (HT)
    montant_ht: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Pour les sorties : valorisation selon méthode
    cump_au_moment: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    cout_unitaire_sortie: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # Pièce justificative
    reference_piece: Mapped[str | None] = mapped_column(String(50), nullable=True)
    libelle: Mapped[str] = mapped_column(Text, nullable=False)

    # Lien écriture SYSCOHADA générée
    ecriture_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("ecritures.id"), nullable=True
    )

    # Traçabilité
    created_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    annule: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    mouvement_annule_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("stock_movements.id"), nullable=True
    )

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "numero", name="uq_stock_movement_numero"),
        Index("idx_sm_tenant_date", "tenant_id", "date_mouvement"),
        Index("idx_sm_item_date", "item_id", "date_mouvement"),
        Index("idx_sm_tenant_type", "tenant_id", "type_mouvement"),
        CheckConstraint("quantite > 0", name="sm_quantite_positive"),
    )

    def __repr__(self) -> str:
        return f"<StockMovement {self.numero} {self.type_mouvement} qty={self.quantite}>"


# ─────────────────────────────────────────────────────────────────────────────
# Couches FIFO (uniquement pour méthode FIFO)
# ─────────────────────────────────────────────────────────────────────────────
class FifoLayer(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Couche FIFO — une entrée = une couche avec quantité + prix.
    Chaque sortie consomme les couches les plus anciennes.
    """
    __tablename__ = "fifo_layers"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    item_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("items.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    warehouse_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("warehouses.id"),
        nullable=False, index=True,
    )
    mouvement_entree_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("stock_movements.id"),
        nullable=False,
    )

    date_entree: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    quantite_initiale: Mapped[float] = mapped_column(Numeric(18, 3), nullable=False)
    quantite_restante: Mapped[float] = mapped_column(Numeric(18, 3), nullable=False)
    prix_unitaire: Mapped[int] = mapped_column(BigInteger, nullable=False)

    __table_args__ = (
        Index("idx_fifo_item_wh_date", "item_id", "warehouse_id", "date_entree"),
    )

    def __repr__(self) -> str:
        return f"<FifoLayer item={self.item_id} qty_rest={self.quantite_restante}>"


# ─────────────────────────────────────────────────────────────────────────────
# Inventaire physique
# ─────────────────────────────────────────────────────────────────────────────
class StockInventory(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Session d'inventaire physique (comptage)."""
    __tablename__ = "stock_inventories"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    warehouse_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("warehouses.id"),
        nullable=False, index=True,
    )

    reference: Mapped[str] = mapped_column(String(30), nullable=False)
    date_inventaire: Mapped[date] = mapped_column(Date, nullable=False)
    libelle: Mapped[str] = mapped_column(Text, nullable=False)

    statut: Mapped[str] = mapped_column(
        String(20), nullable=False, default="brouillon", server_default="brouillon"
    )  # brouillon | en_cours | valide | comptabilise

    # Totaux (remplis à la validation)
    nb_articles: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    valeur_theorique: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    valeur_physique: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    ecart_valeur: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")

    ecriture_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("ecritures.id"), nullable=True
    )
    created_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    valide_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "reference", name="uq_inventory_ref"),
    )


class StockInventoryLine(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Ligne de comptage d'inventaire."""
    __tablename__ = "stock_inventory_lines"

    inventory_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("stock_inventories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    item_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("items.id"),
        nullable=False, index=True,
    )

    # Quantités
    quantite_theorique: Mapped[float] = mapped_column(Numeric(18, 3), nullable=False)
    quantite_physique: Mapped[float] = mapped_column(Numeric(18, 3), nullable=False)
    ecart_quantite: Mapped[float] = mapped_column(Numeric(18, 3), nullable=False)

    # Valorisation
    cump_au_moment: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    ecart_valeur: Mapped[int] = mapped_column(BigInteger, nullable=False)

    motif_ecart: Mapped[str | None] = mapped_column(Text, nullable=True)
    comptabilise: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    __table_args__ = (
        UniqueConstraint("inventory_id", "item_id", name="uq_inv_line_item"),
    )
