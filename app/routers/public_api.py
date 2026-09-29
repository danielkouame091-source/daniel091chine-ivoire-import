"""
API publique v1 — Endpoints exposés aux clients externes.
Toutes les routes sont préfixées par /api/v1/public/.
L'authentification est gérée par PublicApiAuthMiddleware.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.public_api_syscohada import Scope
from app.db.session import AsyncSessionLocal
from app.dependencies.auth import CurrentUser
from app.dependencies.public_api import (
    get_api_client,
    require_scope,
    with_public_db,
)

router = APIRouter()


# ═════════════════════════════════════════════════════════════════════════════
# HEALTH / INFO
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "MTech Public API v1"}


@router.get("/me")
async def get_me(request: Request) -> dict:
    """Informations sur le client API courant."""
    client = getattr(request.state, "api_client", None)
    api_key = getattr(request.state, "api_key", None)
    if client is None:
        raise HTTPException(401, "Client API non authentifié")

    return {
        "client_id": str(client.id),
        "code": client.code,
        "nom": client.nom,
        "type_client": client.type_client,
        "environnement": client.environnement,
        "scopes": api_key.scopes if api_key else [],
        "rate_limit_per_minute": client.rate_limit_per_minute,
    }


# ═════════════════════════════════════════════════════════════════════════════
# ÉCRITURES
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/ecritures")
async def list_ecritures(
    request: Request,
    _: None = Depends(require_scope(Scope.READ_ECRITURES)),
    date_debut: str | None = Query(None),
    date_fin: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    page: int = Query(1, ge=1),
) -> dict:
    """Liste les écritures comptables (pagination)."""
    tenant_id = request.state.tenant_id

    from datetime import date
    from sqlalchemy import func, select
    from app.models.ecriture import Ecriture
    from app.schemas.ecriture import EcritureBrief

    async with AsyncSessionLocal() as db:
        await db.execute(
            __import__("sqlalchemy").text(
                "SELECT set_config('app.tenant_id', :tid, true)"
            ),
            {"tid": str(tenant_id)},
        )

        stmt = select(Ecriture).where(Ecriture.tenant_id == tenant_id)
        if date_debut:
            stmt = stmt.where(Ecriture.date_ecriture >= date.fromisoformat(date_debut))
        if date_fin:
            stmt = stmt.where(Ecriture.date_ecriture <= date.fromisoformat(date_fin))

        total = int(await db.scalar(
            select(func.count()).select_from(stmt.subquery())
        ) or 0)

        stmt = stmt.order_by(Ecriture.date_ecriture.desc())
        stmt = stmt.offset((page - 1) * limit).limit(limit)
        rows = (await db.execute(stmt)).scalars().all()

        return {
            "data": [EcritureBrief.model_validate(e).model_dump(mode="json") for e in rows],
            "pagination": {
                "page": page, "per_page": limit, "total": total,
                "total_pages": (total + limit - 1) // limit,
            },
        }


@router.get("/ecritures/{ecriture_id}")
async def get_ecriture(
    ecriture_id: UUID,
    request: Request,
    _: None = Depends(require_scope(Scope.READ_ECRITURES)),
) -> dict:
    """Détail d'une écriture."""
    tenant_id = request.state.tenant_id

    from sqlalchemy import text
    from app.models.ecriture import Ecriture
    from app.schemas.ecriture import EcritureOut
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )
        e = await db.scalar(
            select(Ecriture).where(
                Ecriture.id == ecriture_id,
                Ecriture.tenant_id == tenant_id,
            )
        )
        if e is None:
            raise HTTPException(404, "Écriture introuvable")
        await db.refresh(e, ["lignes"])
        return EcritureOut.model_validate(e).model_dump(mode="json")


# ═════════════════════════════════════════════════════════════════════════════
# CLIENTS
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/customers")
async def list_customers(
    request: Request,
    _: None = Depends(require_scope(Scope.READ_CLIENTS)),
    limit: int = Query(50, ge=1, le=200),
    page: int = Query(1, ge=1),
) -> dict:
    """Liste les clients."""
    tenant_id = request.state.tenant_id

    from sqlalchemy import func, select, text
    from app.models.sale import Customer
    from app.schemas.sale import CustomerOut

    async with AsyncSessionLocal() as db:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )
        stmt = select(Customer).where(
            Customer.tenant_id == tenant_id,
            Customer.actif.is_(True),
        )
        total = int(await db.scalar(
            select(func.count()).select_from(stmt.subquery())
        ) or 0)
        stmt = stmt.order_by(Customer.code).offset((page - 1) * limit).limit(limit)
        rows = (await db.execute(stmt)).scalars().all()

        return {
            "data": [CustomerOut.model_validate(c).model_dump(mode="json") for c in rows],
            "pagination": {
                "page": page, "per_page": limit, "total": total,
                "total_pages": (total + limit - 1) // limit,
            },
        }


# ═════════════════════════════════════════════════════════════════════════════
# FACTURES CLIENTS
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/invoices")
async def list_invoices(
    request: Request,
    _: None = Depends(require_scope(Scope.READ_FACTURES_CLIENTS)),
    limit: int = Query(50, ge=1, le=200),
    page: int = Query(1, ge=1),
) -> dict:
    """Liste les factures clients."""
    tenant_id = request.state.tenant_id

    from sqlalchemy import func, select, text
    from app.models.sale import CustomerInvoice
    from app.schemas.sale import CustomerInvoiceOut

    async with AsyncSessionLocal() as db:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )
        stmt = select(CustomerInvoice).where(CustomerInvoice.tenant_id == tenant_id)
        total = int(await db.scalar(
            select(func.count()).select_from(stmt.subquery())
        ) or 0)
        stmt = stmt.order_by(CustomerInvoice.date_facture.desc())
        stmt = stmt.offset((page - 1) * limit).limit(limit)
        rows = (await db.execute(stmt)).scalars().all()
        return {
            "data": [CustomerInvoiceOut.model_validate(i).model_dump(mode="json") for i in rows],
            "pagination": {
                "page": page, "per_page": limit, "total": total,
                "total_pages": (total + limit - 1) // limit,
            },
        }


@router.post("/invoices", status_code=201)
async def create_invoice(
    request: Request,
    body: dict,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _: None = Depends(require_scope(Scope.WRITE_FACTURES_CLIENTS)),
) -> dict:
    """Crée une facture client. Support de l'idempotence via Idempotency-Key."""
    tenant_id = request.state.tenant_id
    client = request.state.api_client

    # Vérifier idempotence
    if idempotency_key:
        from app.services.public_api_service import PublicApiService
        async with AsyncSessionLocal() as db:
            await db.execute(
                __import__("sqlalchemy").text(
                    "SELECT set_config('app.tenant_id', :tid, true)"
                ),
                {"tid": str(tenant_id)},
            )
            svc = PublicApiService(db, tenant_id, None)
            cached = await svc.get_idempotent_response(client.id, idempotency_key)
            if cached:
                return cached["body"]

    # Créer la facture
    from app.schemas.sale import CustomerInvoiceCreate, CustomerInvoiceLineCreate
    from app.services.sale_service import SaleService
    from app.services.public_api_service import PublicApiService

    async with AsyncSessionLocal() as db:
        await db.execute(
            __import__("sqlalchemy").text(
                "SELECT set_config('app.tenant_id', :tid, true)"
            ),
            {"tid": str(tenant_id)},
        )
        svc = SaleService(db, tenant_id, None)

        try:
            invoice = await svc.creer_facture(CustomerInvoiceCreate(
                customer_id=UUID(body["customer_id"]),
                date_facture=body["date_facture"],
                date_echeance=body.get("date_echeance"),
                notes=body.get("notes"),
                lignes=[
                    CustomerInvoiceLineCreate(**l) for l in body["lignes"]
                ],
            ))
            await svc.valider_facture(invoice.id)

            response_body = {
                "id": str(invoice.id),
                "numero": invoice.numero,
                "total_ttc": invoice.total_ttc,
                "statut": invoice.statut,
            }

            # Mettre en cache pour idempotence
            if idempotency_key:
                api_svc = PublicApiService(db, tenant_id, None)
                await api_svc.save_idempotent_response(
                    client.id, idempotency_key, "/api/v1/public/invoices",
                    201, response_body,
                )

            await db.commit()

            # Dispatcher un événement webhook
            try:
                from app.services.webhook_dispatch_service import WebhookDispatchService
                async with AsyncSessionLocal() as db2:
                    await db2.execute(
                        __import__("sqlalchemy").text(
                            "SELECT set_config('app.tenant_id', :tid, true)"
                        ),
                        {"tid": str(tenant_id)},
                    )
                    wh_svc = WebhookDispatchService(db2, tenant_id, None)
                    await wh_svc.dispatcher_evenement(
                        "invoice.created", response_body,
                        source_type="customer_invoice", source_id=invoice.id,
                    )
                    await db2.commit()
            except Exception:
                pass

            return response_body

        except Exception as exc:
            await db.rollback()
            raise HTTPException(400, str(exc))


# ═════════════════════════════════════════════════════════════════════════════
# PAIEMENTS
# ═════════════════════════════════════════════════════════════════════════════
@router.post("/payments", status_code=201)
async def create_payment(
    request: Request,
    body: dict,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _: None = Depends(require_scope(Scope.WRITE_PAIEMENTS)),
) -> dict:
    """Enregistre un encaissement client."""
    tenant_id = request.state.tenant_id

    from app.schemas.sale import CustomerPaymentCreate
    from app.services.sale_service import SaleService
    import sqlalchemy as sa

    async with AsyncSessionLocal() as db:
        await db.execute(
            sa.text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )
        svc = SaleService(db, tenant_id, None)
        try:
            payment = await svc.encaisser(CustomerPaymentCreate(
                invoice_id=UUID(body["invoice_id"]),
                date_encaissement=body["date_encaissement"],
                montant=int(body["montant"]),
                mode_encaissement=body["mode_encaissement"],
                reference_encaissement=body.get("reference_encaissement"),
            ))
            await db.commit()

            result = {
                "id": str(payment.id),
                "numero": payment.numero,
                "montant": payment.montant,
                "statut": payment.statut,
            }

            # Webhook
            try:
                from app.services.webhook_dispatch_service import WebhookDispatchService
                async with AsyncSessionLocal() as db2:
                    await db2.execute(
                        sa.text("SELECT set_config('app.tenant_id', :tid, true)"),
                        {"tid": str(tenant_id)},
                    )
                    wh_svc = WebhookDispatchService(db2, tenant_id, None)
                    await wh_svc.dispatcher_evenement(
                        "payment.received", result,
                        source_type="customer_payment", source_id=payment.id,
                    )
                    await db2.commit()
            except Exception:
                pass

            return result
        except Exception as exc:
            await db.rollback()
            raise HTTPException(400, str(exc))


# ═════════════════════════════════════════════════════════════════════════════
# FOURNISSEURS
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/suppliers")
async def list_suppliers(
    request: Request,
    _: None = Depends(require_scope(Scope.READ_FOURNISSEURS)),
    limit: int = Query(50, ge=1, le=200),
    page: int = Query(1, ge=1),
) -> dict:
    tenant_id = request.state.tenant_id

    from sqlalchemy import func, select, text
    from app.models.purchase import Supplier
    from app.schemas.purchase import SupplierOut

    async with AsyncSessionLocal() as db:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )
        stmt = select(Supplier).where(
            Supplier.tenant_id == tenant_id, Supplier.actif.is_(True),
        )
        total = int(await db.scalar(
            select(func.count()).select_from(stmt.subquery())
        ) or 0)
        stmt = stmt.order_by(Supplier.code).offset((page - 1) * limit).limit(limit)
        rows = (await db.execute(stmt)).scalars().all()
        return {
            "data": [SupplierOut.model_validate(s).model_dump(mode="json") for s in rows],
            "pagination": {
                "page": page, "per_page": limit, "total": total,
                "total_pages": (total + limit - 1) // limit,
            },
        }


# ═════════════════════════════════════════════════════════════════════════════
# TRÉSORERIE
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/treasury/accounts")
async def list_treasury_accounts(
    request: Request,
    _: None = Depends(require_scope(Scope.READ_TRESORERIE)),
) -> list[dict]:
    tenant_id = request.state.tenant_id

    from sqlalchemy import select, text
    from app.models.treasury import TreasuryAccount
    from app.schemas.treasury import TreasuryAccountOut

    async with AsyncSessionLocal() as db:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )
        rows = (await db.execute(
            select(TreasuryAccount).where(
                TreasuryAccount.tenant_id == tenant_id,
                TreasuryAccount.actif.is_(True),
            )
        )).scalars().all()
        return [TreasuryAccountOut.model_validate(a).model_dump(mode="json") for a in rows]


# ═════════════════════════════════════════════════════════════════════════════
# KPI (BI)
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/kpis/{kpi_code}")
async def get_kpi(
    kpi_code: str,
    request: Request,
    periode: str = Query("this_month"),
    _: None = Depends(require_scope(Scope.READ_RAPPORTS)),
) -> dict:
    tenant_id = request.state.tenant_id

    from app.services.bi_kpi_engine import KPIEngine
    from sqlalchemy import text

    async with AsyncSessionLocal() as db:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )
        engine = KPIEngine(db, tenant_id)
        return await engine.calculer_kpi(kpi_code, {"periode": periode})


# ═════════════════════════════════════════════════════════════════════════════
# WEBHOOKS — GESTION VIA API
# ═════════════════════════════════════════════════════════════════════════════
@router.post("/webhooks/test", status_code=202)
async def test_webhook(
    request: Request,
    body: dict,
    _: None = Depends(require_scope(Scope.ADMIN_WEBHOOKS)),
) -> dict:
    """Envoie un événement de test à un endpoint."""
    tenant_id = request.state.tenant_id

    from app.schemas.public_api import WebhookTestIn
    from app.services.webhook_dispatch_service import WebhookDispatchService
    from sqlalchemy import text

    async with AsyncSessionLocal() as db:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )
        svc = WebhookDispatchService(db, tenant_id, None)
        result = await svc.tester_endpoint(
            UUID(body["endpoint_id"]),
            WebhookTestIn(
                event_type=body["event_type"],
                payload_custom=body.get("payload"),
            ),
        )
        await db.commit()
        return result


# ═════════════════════════════════════════════════════════════════════════════
# DOCS
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/docs")
async def get_docs() -> dict:
    """Documentation de l'API publique."""
    return {
        "version": "v1",
        "auth": {
            "methods": [
                {"type": "bearer", "header": "Authorization: Bearer mtech_live_xxx"},
                {"type": "api_key", "header": "X-API-Key: mtech_live_xxx"},
                {"type": "oauth2", "endpoint": "/api/v1/public/oauth/token"},
            ],
        },
        "rate_limiting": {
            "default": "1000 req/min",
            "headers": ["X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset"],
        },
        "webhooks": {
            "signature_header": "X-MTech-Signature",
            "format": "t=<timestamp>,v1=<hmac_sha256>",
            "events_doc": "/api/v1/public/webhook-events",
        },
        "versioning": {
            "current": "v1",
            "header": "X-API-Version",
        },
    }
