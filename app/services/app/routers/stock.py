"""Endpoints Gestion des stocks SYSCOHADA."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.auth import CurrentUser, RequireComptable
from app.dependencies.subscription import RequireActiveSubscription
from app.dependencies.tenant import CurrentTenant
from app.dependencies.tenant_db import TenantDBSession
from app.models.stock import Item, ItemCategory, StockInventory, StockLevel, StockMovement, Warehouse
from app.schemas.stock import (
    InventaireCreate,
    InventaireOut,
    InventaireValiderRequest,
    ItemCategoryCreate,
    ItemCategoryOut,
    ItemCreate,
    ItemOut,
    ItemUpdate,
    MouvementEntreeCreate,
    MouvementSortieCreate,
    StockLevelOut,
    StockMovementOut,
    TransfertCreate,
    WarehouseCreate,
    WarehouseOut,
)
from app.services.stock_service import StockService

router = APIRouter()


# ═════════════════════════════════════════════════════════════════════════════
# CATÉGORIES
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/categories", response_model=list[ItemCategoryOut])
async def list_categories(
    current_tenant: CurrentTenant,
    _: RequireComptable,
    db: TenantDBSession,
) -> list[ItemCategoryOut]:
    rows = (
        await db.execute(
            select(ItemCategory).where(
                ItemCategory.tenant_id == current_tenant.id,
                ItemCategory.actif.is_(True),
            )
        )
    ).scalars().all()
    return [ItemCategoryOut.model_validate(c) for c in rows]


@router.post("/categories", response_model=ItemCategoryOut, status_code=201)
async def create_category(
    data: ItemCategoryCreate,
    current_tenant: CurrentTenant,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> ItemCategoryOut:
    cat = ItemCategory(tenant_id=current_tenant.id, **data.model_dump())
    db.add(cat)
    await db.flush()
    return ItemCategoryOut.model_validate(cat)


# ═════════════════════════════════════════════════════════════════════════════
# ENTREPÔTS
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/warehouses", response_model=list[WarehouseOut])
async def list_warehouses(
    current_tenant: CurrentTenant,
    _: RequireComptable,
    db: TenantDBSession,
) -> list[WarehouseOut]:
    rows = (
        await db.execute(
            select(Warehouse).where(
                Warehouse.tenant_id == current_tenant.id,
                Warehouse.actif.is_(True),
            )
        )
    ).scalars().all()
    return [WarehouseOut.model_validate(w) for w in rows]


@router.post("/warehouses", response_model=WarehouseOut, status_code=201)
async def create_warehouse(
    data: WarehouseCreate,
    current_tenant: CurrentTenant,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> WarehouseOut:
    wh = Warehouse(tenant_id=current_tenant.id, **data.model_dump())
    db.add(wh)
    await db.flush()
    return WarehouseOut.model_validate(wh)


# ═════════════════════════════════════════════════════════════════════════════
# ARTICLES
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/items", response_model=list[ItemOut])
async def list_items(
    current_tenant: CurrentTenant,
    _: RequireComptable,
    db: TenantDBSession,
    famille: str | None = Query(None),
    actif_only: bool = True,
    limit: int = 500,
) -> list[ItemOut]:
    stmt = select(Item).where(Item.tenant_id == current_tenant.id)
    if actif_only:
        stmt = stmt.where(Item.actif.is_(True))
    if famille:
        stmt = stmt.where(Item.famille_stock == famille)
    stmt = stmt.order_by(Item.code).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [ItemOut.model_validate(i) for i in rows]


@router.post("/items", response_model=ItemOut, status_code=201)
async def create_item(
    data: ItemCreate,
    current_tenant: CurrentTenant,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> ItemOut:
    item = Item(tenant_id=current_tenant.id, **data.model_dump())
    db.add(item)
    await db.flush()
    return ItemOut.model_validate(item)


@router.patch("/items/{item_id}", response_model=ItemOut)
async def update_item(
    item_id: UUID,
    data: ItemUpdate,
    current_tenant: CurrentTenant,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> ItemOut:
    item = await db.scalar(
        select(Item).where(Item.id == item_id, Item.tenant_id == current_tenant.id)
    )
    if item is None:
        from fastapi import HTTPException
        raise HTTPException(404, "Article introuvable")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(item, k, v)
    await db.flush()
    return ItemOut.model_validate(item)


# ═════════════════════════════════════════════════════════════════════════════
# NIVEAUX DE STOCK
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/levels", response_model=list[StockLevelOut])
async def list_levels(
    current_tenant: CurrentTenant,
    _: RequireComptable,
    db: TenantDBSession,
    warehouse_id: UUID | None = Query(None),
    item_id: UUID | None = Query(None),
) -> list[StockLevelOut]:
    stmt = select(StockLevel).where(StockLevel.tenant_id == current_tenant.id)
    if warehouse_id:
        stmt = stmt.where(StockLevel.warehouse_id == warehouse_id)
    if item_id:
        stmt = stmt.where(StockLevel.item_id == item_id)
    rows = (await db.execute(stmt)).scalars().all()
    return [StockLevelOut.model_validate(l) for l in rows]


# ═════════════════════════════════════════════════════════════════════════════
# MOUVEMENTS
# ═════════════════════════════════════════════════════════════════════════════
@router.post("/entrees", response_model=StockMovementOut, status_code=201)
async def entree_stock(
    data: MouvementEntreeCreate,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> StockMovementOut:
    svc = StockService(db, current_tenant.id, current_user.id)
    mv = await svc.entree_stock(data)
    return StockMovementOut.model_validate(mv)


@router.post("/sorties", response_model=StockMovementOut, status_code=201)
async def sortie_stock(
    data: MouvementSortieCreate,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> StockMovementOut:
    svc = StockService(db, current_tenant.id, current_user.id)
    mv = await svc.sortie_stock(data)
    return StockMovementOut.model_validate(mv)


@router.post("/transferts", response_model=dict, status_code=201)
async def transfert_stock(
    data: TransfertCreate,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> dict:
    svc = StockService(db, current_tenant.id, current_user.id)
    sortie, entree = await svc.transferer(data)
    return {
        "sortie": StockMovementOut.model_validate(sortie).model_dump(mode="json"),
        "entree": StockMovementOut.model_validate(entree).model_dump(mode="json"),
    }


@router.get("/mouvements", response_model=list[StockMovementOut])
async def list_mouvements(
    current_tenant: CurrentTenant,
    _: RequireComptable,
    db: TenantDBSession,
    item_id: UUID | None = Query(None),
    warehouse_id: UUID | None = Query(None),
    limit: int = 200,
) -> list[StockMovementOut]:
    stmt = select(StockMovement).where(StockMovement.tenant_id == current_tenant.id)
    if item_id:
        stmt = stmt.where(StockMovement.item_id == item_id)
    if warehouse_id:
        stmt = stmt.where(StockMovement.warehouse_id == warehouse_id)
    stmt = stmt.order_by(StockMovement.date_mouvement.desc(), StockMovement.created_at.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [StockMovementOut.model_validate(m) for m in rows]


# ═════════════════════════════════════════════════════════════════════════════
# INVENTAIRE
# ═════════════════════════════════════════════════════════════════════════════
@router.post("/inventaires", response_model=InventaireOut, status_code=201)
async def creer_inventaire(
    data: InventaireCreate,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> InventaireOut:
    svc = StockService(db, current_tenant.id, current_user.id)
    inv = await svc.creer_inventaire(data)
    return InventaireOut.model_validate(inv)


@router.post("/inventaires/{inventory_id}/valider", response_model=InventaireOut)
async def valider_inventaire(
    inventory_id: UUID,
    data: InventaireValiderRequest,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> InventaireOut:
    svc = StockService(db, current_tenant.id, current_user.id)
    inv = await svc.valider_inventaire(inventory_id, data)
    return InventaireOut.model_validate(inv)
