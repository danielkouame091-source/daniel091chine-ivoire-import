"""DTO Achats & Fournisseurs SYSCOHADA."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

TypeFournisseur = Literal["fournisseur_local", "fournisseur_import", "fournisseur_groupe"]
StatutPO = Literal["brouillon", "validee", "partiellement_recue", "recue", "facturee", "annulee", "cloturee"]
StatutGR = Literal["brouillon", "validee", "facturee", "annulee"]
StatutFF = Literal["brouillon", "validee", "partiellement_payee", "payee", "en_litige", "annulee"]
ModePai = Literal["virement", "cheque", "especes", "wave", "orange_money", "mtn_momo", "moov_money", "traite", "compensation"]


# ─────────────────────────────────────────────────────────────────────────────
# FOURNISSEURS
# ─────────────────────────────────────────────────────────────────────────────
class SupplierCreate(BaseModel):
    code: str = Field(min_length=1, max_length=20)
    raison_sociale: str = Field(min_length=2, max_length=200)
    forme_juridique: str | None = None
    compte_contribuable: str | None = Field(None, max_length=30)
    rccm: str | None = None
    numero_cnps: str | None = None
    type_fournisseur: TypeFournisseur = "fournisseur_local"
    telephone: str | None = None
    email: str | None = None
    adresse: dict[str, Any] | None = None
    delai_paiement_jours: int = Field(30, ge=0, le=365)
    plafond_credit: int = Field(0, ge=0)
    mode_paiement_defaut: ModePai = "virement"
    assujetti_tva: bool = True
    soumis_ras: bool = False
    taux_ras: float = Field(0, ge=0.0, le=0.5)
    est_resident: bool = True


class SupplierUpdate(BaseModel):
    raison_sociale: str | None = Field(None, min_length=2, max_length=200)
    forme_juridique: str | None = None
    telephone: str | None = None
    email: str | None = None
    adresse: dict[str, Any] | None = None
    delai_paiement_jours: int | None = Field(None, ge=0, le=365)
    plafond_credit: int | None = Field(None, ge=0)
    mode_paiement_defaut: ModePai | None = None
    assujetti_tva: bool | None = None
    soumis_ras: bool | None = None
    taux_ras: float | None = Field(None, ge=0.0, le=0.5)
    actif: bool | None = None


class SupplierOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    code: str
    raison_sociale: str
    type_fournisseur: str
    compte_contribuable: str | None
    telephone: str | None
    email: str | None
    delai_paiement_jours: int
    plafond_credit: int
    mode_paiement_defaut: str
    assujetti_tva: bool
    soumis_ras: bool
    taux_ras: float
    solde_comptable: int
    encours_commandes: int
    actif: bool
    created_at: datetime


# ─────────────────────────────────────────────────────────────────────────────
# COMMANDES
# ─────────────────────────────────────────────────────────────────────────────
class PurchaseOrderLineCreate(BaseModel):
    item_id: UUID | None = None
    designation: str = Field(min_length=1, max_length=200)
    unite: str = Field("U", max_length=10)
    quantite: float = Field(gt=0)
    prix_unitaire_ht: int = Field(gt=0)
    remise_ligne: int = Field(0, ge=0)
    taux_tva: float = Field(0.18, ge=0.0, le=0.30)
    famille_stock: str | None = None
    compte_achat: str | None = None


class PurchaseOrderCreate(BaseModel):
    supplier_id: UUID
    date_commande: date
    date_livraison_prevue: date | None = None
    remise_globale: int = Field(0, ge=0)
    adresse_livraison: str | None = None
    warehouse_destination_id: UUID | None = None
    reference_interne: str | None = None
    notes: str | None = None
    lignes: list[PurchaseOrderLineCreate] = Field(min_length=1)


class PurchaseOrderLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    ordre: int
    item_id: UUID | None
    designation: str
    unite: str
    quantite_commandee: float
    quantite_recue: float
    quantite_facturee: float
    prix_unitaire_ht: int
    montant_ht: int
    montant_tva: int
    montant_ttc: int


class PurchaseOrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    supplier_id: UUID
    numero: str
    date_commande: date
    date_livraison_prevue: date | None
    statut: str
    total_ht: int
    total_tva: int
    total_ttc: int
    remise_globale: int
    validee_at: datetime | None
    created_at: datetime
    lignes: list[PurchaseOrderLineOut] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# RÉCEPTIONS
# ─────────────────────────────────────────────────────────────────────────────
class GoodsReceiptLineCreate(BaseModel):
    purchase_order_line_id: UUID | None = None
    item_id: UUID | None = None
    designation: str = Field(min_length=1, max_length=200)
    quantite_recue: float = Field(ge=0)
    quantite_refusee: float = Field(0, ge=0)
    prix_unitaire_ht: int = Field(ge=0)
    famille_stock: str | None = None
    motif_refus: str | None = None


class GoodsReceiptCreate(BaseModel):
    supplier_id: UUID
    purchase_order_id: UUID | None = None
    warehouse_id: UUID
    date_reception: date
    numero_bl_fournisseur: str | None = None
    notes: str | None = None
    lignes: list[GoodsReceiptLineCreate] = Field(min_length=1)
    creer_mouvements_stock: bool = Field(
        True, description="Génère les entrées de stock automatiquement (module Stocks)"
    )


class GoodsReceiptLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    ordre: int
    designation: str
    quantite_commandee: float
    quantite_recue: float
    quantite_refusee: float
    prix_unitaire_ht: int
    montant_ht: int
    mouvement_stock_id: UUID | None


class GoodsReceiptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    supplier_id: UUID
    purchase_order_id: UUID | None
    warehouse_id: UUID
    numero: str
    date_reception: date
    numero_bl_fournisseur: str | None
    statut: str
    total_ht: int
    validee_at: datetime | None
    created_at: datetime
    lignes: list[GoodsReceiptLineOut] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# FACTURES FOURNISSEUR
# ─────────────────────────────────────────────────────────────────────────────
class SupplierInvoiceLineCreate(BaseModel):
    purchase_order_line_id: UUID | None = None
    goods_receipt_line_id: UUID | None = None
    item_id: UUID | None = None
    designation: str = Field(min_length=1, max_length=200)
    unite: str = Field("U", max_length=10)
    quantite: float = Field(gt=0)
    prix_unitaire_ht: int = Field(ge=0)
    remise_ligne: int = Field(0, ge=0)
    taux_tva: float = Field(0.18, ge=0.0, le=0.30)
    compte_achat: str = Field(min_length=2, max_length=10)
    famille_stock: str | None = None


class SupplierInvoiceCreate(BaseModel):
    supplier_id: UUID
    numero_fournisseur: str = Field(min_length=1, max_length=50)
    date_facture: date
    date_reception_facture: date
    date_echeance: date | None = None
    purchase_order_id: UUID | None = None
    goods_receipt_id: UUID | None = None
    remise_globale: int = Field(0, ge=0)
    notes: str | None = None
    lignes: list[SupplierInvoiceLineCreate] = Field(min_length=1)
    appliquer_ras: bool = False

    @model_validator(mode="after")
    def coherent(self):
        if self.date_facture > self.date_reception_facture:
            raise ValueError("Date de réception facture doit être ≥ date facture")
        return self


class SupplierInvoiceLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    ordre: int
    designation: str
    quantite: float
    prix_unitaire_ht: int
    montant_ht: int
    montant_tva: int
    montant_ttc: int
    compte_achat: str


class SupplierInvoiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    supplier_id: UUID
    numero_fournisseur: str
    numero_interne: str
    date_facture: date
    date_echeance: date
    date_reception_facture: date
    purchase_order_id: UUID | None
    goods_receipt_id: UUID | None
    statut: str
    total_ht: int
    total_tva: int
    total_ttc: int
    ras_appliquee: int
    montant_net_a_payer: int
    montant_paye: int
    solde_du: int
    rapprochement_resultat: str | None
    ecriture_id: UUID | None
    created_at: datetime
    lignes: list[SupplierInvoiceLineOut] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# PAIEMENTS
# ─────────────────────────────────────────────────────────────────────────────
class SupplierPaymentCreate(BaseModel):
    invoice_id: UUID
    date_paiement: date
    montant: int = Field(gt=0)
    mode_paiement: ModePai
    reference_paiement: str | None = None
    escompte_obtenu: int = Field(0, ge=0)


class SupplierPaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    supplier_id: UUID
    invoice_id: UUID
    numero: str
    date_paiement: date
    montant: int
    mode_paiement: str
    compte_tresorerie: str
    reference_paiement: str | None
    statut: str
    escompte_obtenu: int
    ecriture_id: UUID | None
    created_at: datetime


# ─────────────────────────────────────────────────────────────────────────────
# RAPPROCHEMENT 3 VOIES
# ─────────────────────────────────────────────────────────────────────────────
class ThreeWayMatchOut(BaseModel):
    invoice_id: UUID
    purchase_order_id: UUID | None
    goods_receipt_id: UUID | None
    resultat: str
    ecarts: list[dict[str, Any]]
    total_po_ht: int | None
    total_gr_ht: int | None
    total_invoice_ht: int
    ecart_prix_total: int
    ecart_quantite_total: float


# ─────────────────────────────────────────────────────────────────────────────
# BALANCE ÂGÉE
# ─────────────────────────────────────────────────────────────────────────────
class BalanceAgeeLigne(BaseModel):
    supplier_id: UUID
    code: str
    raison_sociale: str
    total_du: int
    non_echu: int
    tranche_0_30: int
    tranche_31_60: int
    tranche_61_90: int
    tranche_90_plus: int
    nb_factures: int
    plus_ancienne_echeance: date | None


class BalanceAgeeOut(BaseModel):
    tenant_id: UUID
    date_arret: date
    total_du: int
    total_non_echu: int
    total_0_30: int
    total_31_60: int
    total_61_90: int
    total_90_plus: int
    fournisseurs: list[BalanceAgeeLigne]
