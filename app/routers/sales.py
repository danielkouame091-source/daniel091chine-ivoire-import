"""Endpoints Ventes & Clients SYSCOHADA."""
from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.dependencies.auth import CurrentUser, RequireComptable
from app.dependencies.subscription import RequireActiveSubscription
from app.dependencies.tenant import CurrentTenant
from app.dependencies.tenant_db import TenantDBSession
from app.models.sale import (
    CreditNote,
    Customer,
    CustomerInvoice,
    CustomerPayment,
    DeliveryNote,
    Quote,
    SalesOrder,
)
from app.schemas.sale import (
    BalanceAgeeClientOut,
    CreditNoteCreate,
    CreditNoteOut,
    CustomerCreate,
    CustomerInvoiceCreate,
    CustomerInvoiceOut,
    CustomerOut,
    CustomerPaymentCreate,
    CustomerPaymentOut,
    CustomerUpdate,
    DeliveryNoteCreate,
    DeliveryNoteOut,
    QuoteCreate,
    QuoteOut,
    RelancePreviewOut,
    RelanceResultOut,
    SalesOrderCreate,
    SalesOrderOut,
)
from app.services.sale_service import SaleService

router = APIRouter()


# ═════════════════════════════════════════════════════════════════════════════
# CLIENTS
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/customers", response_model=list[CustomerOut])
async def list_customers(
    current_tenant: CurrentTenant,
    _: RequireComptable,
    db: TenantDBSession,
    actif_only: bool = True,
    limit: int = 500,
) -> list[CustomerOut]:
    stmt = select(Customer).where(Customer.tenant_id == current_tenant.id)
    if actif_only:
        stmt = stmt.where(Customer.actif.is_(True))
    stmt = stmt.order_by(Customer.code).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [CustomerOut.model_validate(c) for c in rows]


@router.post("/customers", response_model=CustomerOut, status_code=201)
async def create_customer(
    data: CustomerCreate,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> CustomerOut:
    svc = SaleService(db, current_tenant.id, current_user.id)
    customer = await svc.creer_client(data)
    return CustomerOut.model_validate(customer)


@router.patch("/customers/{customer_id}", response_model=CustomerOut)
async def update_customer(
    customer_id: UUID,
    data: CustomerUpdate,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> CustomerOut:
    svc = SaleService(db, current_tenant.id, current_user.id)
    customer = await svc.modifier_client(customer_id, data)
    return CustomerOut.model_validate(customer)


# ═════════════════════════════════════════════════════════════════════════════
# DEVIS
# ═════════════════════════════════════════════════════════════════════════════
@router.post("/quotes", response_model=QuoteOut, status_code=201)
async def create_quote(
    data: QuoteCreate,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> QuoteOut:
    svc = SaleService(db, current_tenant.id, current_user.id)
    quote = await svc.creer_devis(data)
    await db.refresh(quote, ["lignes"])
    return QuoteOut.model_validate(quote)


@router.post("/quotes/{quote_id}/convertir", response_model=SalesOrderOut)
async def convert_quote(
    quote_id: UUID,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> SalesOrderOut:
    svc = SaleService(db, current_tenant.id, current_user.id)
    order = await svc.convertir_devis_en_commande(quote_id)
    await db.refresh(order, ["lignes"])
    return SalesOrderOut.model_validate(order)


# ═════════════════════════════════════════════════════════════════════════════
# COMMANDES CLIENT
# ═════════════════════════════════════════════════════════════════════════════
@router.post("/orders", response_model=SalesOrderOut, status_code=201)
async def create_order(
    data: SalesOrderCreate,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> SalesOrderOut:
    svc = SaleService(db, current_tenant.id, current_user.id)
    order = await svc.creer_commande(data)
    await db.refresh(order, ["lignes"])
    return SalesOrderOut.model_validate(order)


@router.post("/orders/{order_id}/confirmer", response_model=SalesOrderOut)
async def confirm_order(
    order_id: UUID,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> SalesOrderOut:
    svc = SaleService(db, current_tenant.id, current_user.id)
    order = await svc.confirmer_commande(order_id)
    await db.refresh(order, ["lignes"])
    return SalesOrderOut.model_validate(order)


@router.get("/orders", response_model=list[SalesOrderOut])
async def list_orders(
    current_tenant: CurrentTenant,
    _: RequireComptable,
    db: TenantDBSession,
    statut: str | None = Query(None),
    customer_id: UUID | None = Query(None),
    limit: int = 200,
) -> list[SalesOrderOut]:
    stmt = select(SalesOrder).where(SalesOrder.tenant_id == current_tenant.id)
    if statut:
        stmt = stmt.where(SalesOrder.statut == statut)
    if customer_id:
        stmt = stmt.where(SalesOrder.customer_id == customer_id)
    stmt = stmt.order_by(SalesOrder.date_commande.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    out = []
    for o in rows:
        await db.refresh(o, ["lignes"])
        out.append(SalesOrderOut.model_validate(o))
    return out


# ═════════════════════════════════════════════════════════════════════════════
# BONS DE LIVRAISON
# ═════════════════════════════════════════════════════════════════════════════
@router.post("/deliveries", response_model=DeliveryNoteOut, status_code=201)
async def create_delivery(
    data: DeliveryNoteCreate,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> DeliveryNoteOut:
    svc = SaleService(db, current_tenant.id, current_user.id)
    delivery = await svc.creer_bl(data)
    await db.refresh(delivery, ["lignes"])
    return DeliveryNoteOut.model_validate(delivery)


@router.post("/deliveries/{delivery_id}/valider", response_model=DeliveryNoteOut)
async def validate_delivery(
    delivery_id: UUID,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> DeliveryNoteOut:
    svc = SaleService(db, current_tenant.id, current_user.id)
    delivery = await svc.valider_bl(delivery_id)
    await db.refresh(delivery, ["lignes"])
    return DeliveryNoteOut.model_validate(delivery)


# ═════════════════════════════════════════════════════════════════════════════
# FACTURES CLIENT
# ═════════════════════════════════════════════════════════════════════════════
@router.post("/invoices", response_model=CustomerInvoiceOut, status_code=201)
async def create_invoice(
    data: CustomerInvoiceCreate,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> CustomerInvoiceOut:
    svc = SaleService(db, current_tenant.id, current_user.id)
    invoice = await svc.creer_facture(data)
    await db.refresh(invoice, ["lignes"])
    return CustomerInvoiceOut.model_validate(invoice)


@router.post("/invoices/{invoice_id}/valider", response_model=CustomerInvoiceOut)
async def validate_invoice(
    invoice_id: UUID,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> CustomerInvoiceOut:
    svc = SaleService(db, current_tenant.id, current_user.id)
    invoice = await svc.valider_facture(invoice_id)
    await db.refresh(invoice, ["lignes"])
    return CustomerInvoiceOut.model_validate(invoice)


@router.get("/invoices", response_model=list[CustomerInvoiceOut])
async def list_invoices(
    current_tenant: CurrentTenant,
    _: RequireComptable,
    db: TenantDBSession,
    statut: str | None = Query(None),
    customer_id: UUID | None = Query(None),
    limit: int = 200,
) -> list[CustomerInvoiceOut]:
    stmt = select(CustomerInvoice).where(CustomerInvoice.tenant_id == current_tenant.id)
    if statut:
        stmt = stmt.where(CustomerInvoice.statut == statut)
    if customer_id:
        stmt = stmt.where(CustomerInvoice.customer_id == customer_id)
    stmt = stmt.order_by(CustomerInvoice.date_facture.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    out = []
    for i in rows:
        await db.refresh(i, ["lignes"])
        out.append(CustomerInvoiceOut.model_validate(i))
    return out


# ═════════════════════════════════════════════════════════════════════════════
# ENCAISSEMENTS
# ═════════════════════════════════════════════════════════════════════════════
@router.post("/payments", response_model=CustomerPaymentOut, status_code=201)
async def create_payment(
    data: CustomerPaymentCreate,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> CustomerPaymentOut:
    svc = SaleService(db, current_tenant.id, current_user.id)
    payment = await svc.encaisser(data)
    return CustomerPaymentOut.model_validate(payment)


@router.get("/payments", response_model=list[CustomerPaymentOut])
async def list_payments(
    current_tenant: CurrentTenant,
    _: RequireComptable,
    db: TenantDBSession,
    customer_id: UUID | None = Query(None),
    limit: int = 200,
) -> list[CustomerPaymentOut]:
    stmt = select(CustomerPayment).where(CustomerPayment.tenant_id == current_tenant.id)
    if customer_id:
        stmt = stmt.where(CustomerPayment.customer_id == customer_id)
    stmt = stmt.order_by(CustomerPayment.date_encaissement.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [CustomerPaymentOut.model_validate(p) for p in rows]


# ═════════════════════════════════════════════════════════════════════════════
# AVOIRS
# ═════════════════════════════════════════════════════════════════════════════
@router.post("/credit-notes", response_model=CreditNoteOut, status_code=201)
async def create_credit_note(
    data: CreditNoteCreate,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> CreditNoteOut:
    svc = SaleService(db, current_tenant.id, current_user.id)
    cn = await svc.creer_avoir(data)
    await db.refresh(cn, ["lignes"])
    return CreditNoteOut.model_validate(cn)


@router.get("/credit-notes", response_model=list[CreditNoteOut])
async def list_credit_notes(
    current_tenant: CurrentTenant,
    _: RequireComptable,
    db: TenantDBSession,
    customer_id: UUID | None = Query(None),
    limit: int = 200,
) -> list[CreditNoteOut]:
    stmt = select(CreditNote).where(CreditNote.tenant_id == current_tenant.id)
    if customer_id:
        stmt = stmt.where(CreditNote.customer_id == customer_id)
    stmt = stmt.order_by(CreditNote.date_avoir.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    out = []
    for cn in rows:
        await db.refresh(cn, ["lignes"])
        out.append(CreditNoteOut.model_validate(cn))
    return out


# ═════════════════════════════════════════════════════════════════════════════
# BALANCE ÂGÉE
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/balance-agee", response_model=BalanceAgeeClientOut)
async def balance_agee(
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
    date_arret: date = Query(default_factory=date.today),
) -> BalanceAgeeClientOut:
    svc = SaleService(db, current_tenant.id, current_user.id)
    return await svc.balance_agee(date_arret)


# ═════════════════════════════════════════════════════════════════════════════
# RELANCES
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/relances/previsualiser", response_model=list[RelancePreviewOut])
async def preview_relances(
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
    date_arret: date = Query(default_factory=date.today),
) -> list[RelancePreviewOut]:
    svc = SaleService(db, current_tenant.id, current_user.id)
    return await svc.previsualiser_relances(date_arret)


@router.post("/relances/executer", response_model=RelanceResultOut)
async def execute_relances(
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
    date_arret: date = Query(default_factory=date.today),
) -> RelanceResultOut:
    svc = SaleService(db, current_tenant.id, current_user.id)
    return await svc.executer_relances(date_arret)
