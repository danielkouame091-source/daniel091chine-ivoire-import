"""Endpoints Achats & Fournisseurs SYSCOHADA."""
from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.dependencies.auth import CurrentUser, RequireComptable
from app.dependencies.subscription import RequireActiveSubscription
from app.dependencies.tenant import CurrentTenant
from app.dependencies.tenant_db import TenantDBSession
from app.models.purchase import (
    GoodsReceipt,
    PurchaseOrder,
    Supplier,
    SupplierInvoice,
    SupplierPayment,
)
from app.schemas.purchase import (
    BalanceAgeeOut,
    GoodsReceiptCreate,
    GoodsReceiptOut,
    PurchaseOrderCreate,
    PurchaseOrderOut,
    SupplierCreate,
    SupplierInvoiceCreate,
    SupplierInvoiceOut,
    SupplierOut,
    SupplierPaymentCreate,
    SupplierPaymentOut,
    SupplierUpdate,
    ThreeWayMatchOut,
)
from app.services.purchase_service import PurchaseService

router = APIRouter()


# ═════════════════════════════════════════════════════════════════════════════
# FOURNISSEURS
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/suppliers", response_model=list[SupplierOut])
async def list_suppliers(
    current_tenant: CurrentTenant,
    _: RequireComptable,
    db: TenantDBSession,
    actif_only: bool = True,
    limit: int = 500,
) -> list[SupplierOut]:
    stmt = select(Supplier).where(Supplier.tenant_id == current_tenant.id)
    if actif_only:
        stmt = stmt.where(Supplier.actif.is_(True))
    stmt = stmt.order_by(Supplier.code).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [SupplierOut.model_validate(s) for s in rows]


@router.post("/suppliers", response_model=SupplierOut, status_code=201)
async def create_supplier(
    data: SupplierCreate,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> SupplierOut:
    svc = PurchaseService(db, current_tenant.id, current_user.id)
    supplier = await svc.creer_fournisseur(data)
    return SupplierOut.model_validate(supplier)


@router.patch("/suppliers/{supplier_id}", response_model=SupplierOut)
async def update_supplier(
    supplier_id: UUID,
    data: SupplierUpdate,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> SupplierOut:
    svc = PurchaseService(db, current_tenant.id, current_user.id)
    supplier = await svc.modifier_fournisseur(supplier_id, data)
    return SupplierOut.model_validate(supplier)


# ═════════════════════════════════════════════════════════════════════════════
# COMMANDES
# ═════════════════════════════════════════════════════════════════════════════
@router.post("/orders", response_model=PurchaseOrderOut, status_code=201)
async def create_order(
    data: PurchaseOrderCreate,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> PurchaseOrderOut:
    svc = PurchaseService(db, current_tenant.id, current_user.id)
    order = await svc.creer_commande(data)
    await db.refresh(order, ["lignes"])
    return PurchaseOrderOut.model_validate(order)


@router.post("/orders/{order_id}/valider", response_model=PurchaseOrderOut)
async def valider_order(
    order_id: UUID,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> PurchaseOrderOut:
    svc = PurchaseService(db, current_tenant.id, current_user.id)
    order = await svc.valider_commande(order_id)
    await db.refresh(order, ["lignes"])
    return PurchaseOrderOut.model_validate(order)


@router.get("/orders", response_model=list[PurchaseOrderOut])
async def list_orders(
    current_tenant: CurrentTenant,
    _: RequireComptable,
    db: TenantDBSession,
    statut: str | None = Query(None),
    supplier_id: UUID | None = Query(None),
    limit: int = 200,
) -> list[PurchaseOrderOut]:
    stmt = select(PurchaseOrder).where(PurchaseOrder.tenant_id == current_tenant.id)
    if statut:
        stmt = stmt.where(PurchaseOrder.statut == statut)
    if supplier_id:
        stmt = stmt.where(PurchaseOrder.supplier_id == supplier_id)
    stmt = stmt.order_by(PurchaseOrder.date_commande.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    out = []
    for o in rows:
        await db.refresh(o, ["lignes"])
        out.append(PurchaseOrderOut.model_validate(o))
    return out


# ═════════════════════════════════════════════════════════════════════════════
# RÉCEPTIONS
# ═════════════════════════════════════════════════════════════════════════════
@router.post("/receipts", response_model=GoodsReceiptOut, status_code=201)
async def create_receipt(
    data: GoodsReceiptCreate,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> GoodsReceiptOut:
    svc = PurchaseService(db, current_tenant.id, current_user.id)
    receipt = await svc.creer_reception(data)
    await db.refresh(receipt, ["lignes"])
    return GoodsReceiptOut.model_validate(receipt)


@router.post("/receipts/{receipt_id}/valider", response_model=GoodsReceiptOut)
async def valider_receipt(
    receipt_id: UUID,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> GoodsReceiptOut:
    svc = PurchaseService(db, current_tenant.id, current_user.id)
    receipt = await svc.valider_reception(receipt_id)
    await db.refresh(receipt, ["lignes"])
    return GoodsReceiptOut.model_validate(receipt)


@router.get("/receipts", response_model=list[GoodsReceiptOut])
async def list_receipts(
    current_tenant: CurrentTenant,
    _: RequireComptable,
    db: TenantDBSession,
    supplier_id: UUID | None = Query(None),
    limit: int = 200,
) -> list[GoodsReceiptOut]:
    stmt = select(GoodsReceipt).where(GoodsReceipt.tenant_id == current_tenant.id)
    if supplier_id:
        stmt = stmt.where(GoodsReceipt.supplier_id == supplier_id)
    stmt = stmt.order_by(GoodsReceipt.date_reception.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    out = []
    for r in rows:
        await db.refresh(r, ["lignes"])
        out.append(GoodsReceiptOut.model_validate(r))
    return out


# ═════════════════════════════════════════════════════════════════════════════
# FACTURES FOURNISSEUR
# ═════════════════════════════════════════════════════════════════════════════
@router.post("/invoices", response_model=SupplierInvoiceOut, status_code=201)
async def create_invoice(
    data: SupplierInvoiceCreate,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> SupplierInvoiceOut:
    svc = PurchaseService(db, current_tenant.id, current_user.id)
    invoice = await svc.creer_facture(data)
    await db.refresh(invoice, ["lignes"])
    return SupplierInvoiceOut.model_validate(invoice)


@router.post("/invoices/{invoice_id}/valider", response_model=SupplierInvoiceOut)
async def valider_invoice(
    invoice_id: UUID,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> SupplierInvoiceOut:
    svc = PurchaseService(db, current_tenant.id, current_user.id)
    invoice = await svc.valider_facture(invoice_id)
    await db.refresh(invoice, ["lignes"])
    return SupplierInvoiceOut.model_validate(invoice)


@router.get("/invoices", response_model=list[SupplierInvoiceOut])
async def list_invoices(
    current_tenant: CurrentTenant,
    _: RequireComptable,
    db: TenantDBSession,
    statut: str | None = Query(None),
    supplier_id: UUID | None = Query(None),
    limit: int = 200,
) -> list[SupplierInvoiceOut]:
    stmt = select(SupplierInvoice).where(SupplierInvoice.tenant_id == current_tenant.id)
    if statut:
        stmt = stmt.where(SupplierInvoice.statut == statut)
    if supplier_id:
        stmt = stmt.where(SupplierInvoice.supplier_id == supplier_id)
    stmt = stmt.order_by(SupplierInvoice.date_facture.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    out = []
    for i in rows:
        await db.refresh(i, ["lignes"])
        out.append(SupplierInvoiceOut.model_validate(i))
    return out


# ═════════════════════════════════════════════════════════════════════════════
# RAPPROCHEMENT 3 VOIES
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/invoices/{invoice_id}/rapprochement", response_model=ThreeWayMatchOut)
async def rapprochement_3_voies(
    invoice_id: UUID,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
) -> ThreeWayMatchOut:
    svc = PurchaseService(db, current_tenant.id, current_user.id)
    return await svc.rapprocher_3_voies(invoice_id)


# ═════════════════════════════════════════════════════════════════════════════
# PAIEMENTS
# ═════════════════════════════════════════════════════════════════════════════
@router.post("/payments", response_model=SupplierPaymentOut, status_code=201)
async def create_payment(
    data: SupplierPaymentCreate,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> SupplierPaymentOut:
    svc = PurchaseService(db, current_tenant.id, current_user.id)
    payment = await svc.payer_facture(data)
    return SupplierPaymentOut.model_validate(payment)


@router.get("/payments", response_model=list[SupplierPaymentOut])
async def list_payments(
    current_tenant: CurrentTenant,
    _: RequireComptable,
    db: TenantDBSession,
    supplier_id: UUID | None = Query(None),
    limit: int = 200,
) -> list[SupplierPaymentOut]:
    stmt = select(SupplierPayment).where(SupplierPayment.tenant_id == current_tenant.id)
    if supplier_id:
        stmt = stmt.where(SupplierPayment.supplier_id == supplier_id)
    stmt = stmt.order_by(SupplierPayment.date_paiement.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [SupplierPaymentOut.model_validate(p) for p in rows]


# ═════════════════════════════════════════════════════════════════════════════
# BALANCE ÂGÉE
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/balance-agee", response_model=BalanceAgeeOut)
async def balance_agee(
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
    date_arret: date = Query(default_factory=date.today),
) -> BalanceAgeeOut:
    svc = PurchaseService(db, current_tenant.id, current_user.id)
    return await svc.balance_agee(date_arret)
