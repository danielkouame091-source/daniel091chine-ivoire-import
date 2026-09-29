"""DTO Stocks SYSCOHADA."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

FamilleStock = Literal[
    "marchandises", "matieres_premieres", "autres_appro",
    "produits_en_cours", "produits_finis", "produits_residuels",
    "stocks_en_route", "stocks_en_depot",
]
MethodeValo = Literal["cump", "fifo", "peps"]


# ─────────────────────────────────────────────────────────────────────────────
# Catalogue
# ─────────────────────────────────────────────────────────────────────────────
class ItemCategoryCreate(BaseModel):
    code: str = Field(min_length=1, max_length=20)
    libelle: str = Field(min_length=2, max_length=200)
    parent_id: UUID | None = None


class ItemCategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    code: str
    libelle: str
    parent_id: UUID | None
    actif: bool


class WarehouseCreate(BaseModel):
    code: str = Field(min_length=1, max_length=20)
    libelle: str = Field(min_length=2, max_length=200)
    adresse: str | None = None
    responsable: str | None = None
    est_principal: bool = False


class WarehouseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    code: str
    libelle: str
    adresse: str | None
    responsable: str | None
    est_principal: bool
    actif: bool


class ItemCreate(BaseModel):
    code: str = Field(min_length=1, max_length=30)
    designation: str = Field(min_length=2, max_length=200)
    description: str | None = None
    category_id: UUID | None = None
    code_barre: str | None = None
    unite: str = Field("U", max_length=10)
    famille_stock: FamilleStock = "marchandises"
    methode_valorisation: MethodeValo = "cump"
    seuil_alerte: int = Field(0, ge=0)
    seuil_reappro: int = Field(0, ge=0)
    prix_achat_ht: int = Field(0, ge=0)
    prix_vente_ht: int = Field(0, ge=0)
    taux_tva: float = Field(0.18, ge=0.0, le=1.0)
    gere_en_stock: bool = True


class ItemUpdate(BaseModel):
    designation: str | None = None
    description: str | None = None
    category_id: UUID | None = None
    unite: str | None = None
    seuil_alerte: int | None = Field(None, ge=0)
    seuil_reappro: int | None = Field(None, ge=0)
    prix_achat_ht: int | None = Field(None, ge=0)
    prix_vente_ht: int | None = Field(None, ge=0)
    taux_tva: float | None = Field(None, ge=0.0, le=1.0)
    actif: bool | None = None


class ItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    code: str
    code_barre: str | None
    designation: str
    description: str | None
    category_id: UUID | None
    unite: str
    famille_stock: str
    methode_valorisation: str
    seuil_alerte: int
    seuil_reappro: int
    prix_achat_ht: int
    prix_vente_ht: int
    taux_tva: float
    gere_en_stock: bool
    actif: bool


# ─────────────────────────────────────────────────────────────────────────────
# Mouvements
# ─────────────────────────────────────────────────────────────────────────────
class MouvementEntreeCreate(BaseModel):
    item_id: UUID
    warehouse_id: UUID
    date_mouvement: date
    quantite: float = Field(gt=0)
    prix_unitaire: int = Field(gt=0, description="Prix unitaire HT en XOF")
    libelle: str = Field(min_length=2, max_length=200)
    reference_piece: str | None = None
    type_mouvement: Literal[
        "entree_achat", "entree_retour", "entree_production", "entree_ajustement"
    ] = "entree_achat"


class MouvementSortieCreate(BaseModel):
    item_id: UUID
    warehouse_id: UUID
    date_mouvement: date
    quantite: float = Field(gt=0)
    libelle: str = Field(min_length=2, max_length=200)
    reference_piece: str | None = None
    type_mouvement: Literal[
        "sortie_vente", "sortie_conso", "sortie_perte", "sortie_ajustement"
    ] = "sortie_vente"


class TransfertCreate(BaseModel):
    item_id: UUID
    warehouse_source_id: UUID
    warehouse_destination_id: UUID
    date_mouvement: date
    quantite: float = Field(gt=0)
    libelle: str = Field(min_length=2, max_length=200)

    @model_validator(mode="after")
    def wh_differents(self):
        if self.warehouse_source_id == self.warehouse_destination_id:
            raise ValueError("Source et destination doivent être différents")
        return self


class StockMovementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    numero: str
    date_mouvement: date
    type_mouvement: str
    item_id: UUID
    warehouse_id: UUID
    warehouse_destination_id: UUID | None
    quantite: float
    prix_unitaire: int
    montant_ht: int
    cump_au_moment: float | None
    cout_unitaire_sortie: int | None
    libelle: str
    reference_piece: str | None
    ecriture_id: UUID | None
    created_at: datetime


class StockLevelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    item_id: UUID
    warehouse_id: UUID
    quantite: float
    cump: float
    valeur_stock: int
    dernier_mouvement_at: datetime | None


# ─────────────────────────────────────────────────────────────────────────────
# Inventaire
# ─────────────────────────────────────────────────────────────────────────────
class InventaireCreate(BaseModel):
    warehouse_id: UUID
    date_inventaire: date
    libelle: str = Field(min_length=2, max_length=200)
    reference: str | None = None


class InventaireLigneCreate(BaseModel):
    item_id: UUID
    quantite_physique: float = Field(ge=0)
    motif_ecart: str | None = None


class InventaireValiderRequest(BaseModel):
    lignes: list[InventaireLigneCreate] = Field(min_length=1)
    comptabiliser: bool = True


class InventaireLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    item_id: UUID
    quantite_theorique: float
    quantite_physique: float
    ecart_quantite: float
    cump_au_moment: float
    ecart_valeur: int
    motif_ecart: str | None
    comptabilise: bool


class InventaireOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    warehouse_id: UUID
    reference: str
    date_inventaire: date
    libelle: str
    statut: str
    nb_articles: int
    valeur_theorique: int
    valeur_physique: int
    ecart_valeur: int
    ecriture_id: UUID | None
    created_at: datetime
