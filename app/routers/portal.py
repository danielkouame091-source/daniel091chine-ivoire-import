"""Endpoints Portail Client / Fournisseur."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy import select

from app.dependencies.tenant import CurrentTenant
from app.dependencies.tenant_db import TenantDBSession
from app.models.portal import PortalUser
from app.schemas.portal import (
    ClientInvoiceOut,
    ClientPortalDashboard,
    ClientStatementOut,
    OnlinePaymentInitIn,
    OnlinePaymentInitOut,
    OnlinePaymentOut,
    PortalConversationCreate,
    PortalConversationDetailOut,
    PortalConversationOut,
    PortalInviteIn,
    PortalLoginIn,
    PortalMagicLinkIn,
    PortalMessageCreate,
    PortalMessageOut,
    PortalNotificationOut,
    PortalPasswordSetIn,
    PortalStatsOut,
    PortalTokenOut,
    PortalUserOut,
    PortalUserUpdate,
    SharedDocumentDetailOut,
    SharedDocumentOut,
    SupplierInvoiceSubmissionIn,
    SupplierInvoiceSubmissionOut,
    SupplierOrderOut,
    SupplierPortalDashboard,
)
from app.services.portal_auth_service import PortalAuthService
from app.services.portal_client_service import PortalClientService
from app.services.portal_supplier_service import PortalSupplierService

router = APIRouter()


# ═════════════════════════════════════════════════════════════════════════════
# DÉPENDANCES PORTAIL (à mettre dans app/dependencies/portal.py en production)
# ═════════════════════════════════════════════════════════════════════════════
async def get_current_portal_user(
    request: Request,
    authorization: str | None = Header(None),
    db: TenantDBSession = None,
) -> PortalUser:
    """
    Dépendance : charge l'utilisateur portail depuis le JWT.
    Le JWT doit avoir `scope: "portal"` pour être accepté.
    """
    import jwt
    from app.core.config import settings

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Token manquant")
    token = authorization[7:]
    try:
        payload = jwt.decode(token, settings.JWT_PUBLIC_KEY, algorithms=["RS256"])
    except Exception:
        raise HTTPException(401, "Token invalide")

    if payload.get("scope") != "portal":
        raise HTTPException(403, "Token portail requis")

    portal_user_id = payload.get("sub")
    if not portal_user_id:
        raise HTTPException(401, "Token invalide")

    user = await db.scalar(
        select(PortalUser).where(PortalUser.id == UUID(portal_user_id))
    )
    if user is None or user.statut != "actif":
        raise HTTPException(403, "Compte inactif")

    return user


# ═════════════════════════════════════════════════════════════════════════════
# AUTH PORTAIL (endpoints PUBLICS)
# ═════════════════════════════════════════════════════════════════════════════
@router.post("/auth/activate", response_model=PortalUserOut)
async def activate_account(
    data: PortalPasswordSetIn,
    current_tenant: CurrentTenant,
    db: TenantDBSession,
) -> PortalUserOut:
    svc = PortalAuthService(db, current_tenant.id)
    user = await svc.activer_compte(data.token, data.password)
    return PortalUserOut.model_validate(user)


@router.post("/auth/login", response_model=PortalTokenOut)
async def portal_login(
    data: PortalLoginIn,
    request: Request,
    current_tenant: CurrentTenant,
    db: TenantDBSession,
) -> PortalTokenOut:
    svc = PortalAuthService(db, current_tenant.id)
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")
    result = await svc.login(data.email, data.password, ip, ua)
    return PortalTokenOut(**result)


@router.post("/auth/magic-link", response_model=dict)
async def request_magic_link(
    data: PortalMagicLinkIn,
    current_tenant: CurrentTenant,
    db: TenantDBSession,
) -> dict:
    svc = PortalAuthService(db, current_tenant.id)
    return await svc.demander_magic_link(data.email)


@router.post("/auth/magic-login", response_model=PortalTokenOut)
async def magic_login(
    token: str = Query(...),
    request: Request = None,
    current_tenant: CurrentTenant = None,
    db: TenantDBSession = None,
) -> PortalTokenOut:
    svc = PortalAuthService(db, current_tenant.id)
    ip = request.client.host if request and request.client else None
    ua = request.headers.get("user-agent") if request else None
    result = await svc.login_magic_link(token, ip, ua)
    return PortalTokenOut(**result)


@router.post("/auth/logout", status_code=204)
async def portal_logout(
    current_user: PortalUser = Depends(get_current_portal_user),
    db: TenantDBSession = None,
) -> None:
    # Récupérer jti depuis le token... (à améliorer en V2)
    pass


# ═════════════════════════════════════════════════════════════════════════════
# ADMIN — INVITATIONS (côté tenant)
# ═════════════════════════════════════════════════════════════════════════════
@router.post("/invitations", response_model=dict, status_code=201)
async def invite_portal_user(
    data: PortalInviteIn,
    current_tenant: CurrentTenant,
    db: TenantDBSession,
) -> dict:
    """Crée une invitation pour un client ou fournisseur."""
    svc = PortalAuthService(db, current_tenant.id)
    return await svc.inviter(data)


@router.get("/users", response_model=list[PortalUserOut])
async def list_portal_users(
    current_tenant: CurrentTenant,
    db: TenantDBSession,
    type_utilisateur: str | None = Query(None),
    statut: str | None = Query(None),
    limit: int = 200,
) -> list[PortalUserOut]:
    stmt = select(PortalUser).where(PortalUser.tenant_id == current_tenant.id)
    if type_utilisateur:
        stmt = stmt.where(PortalUser.type_utilisateur == type_utilisateur)
    if statut:
        stmt = stmt.where(PortalUser.statut == statut)
    stmt = stmt.order_by(PortalUser.created_at.desc()).limit(limit)
    users = (await db.execute(stmt)).scalars().all()
    return [PortalUserOut.model_validate(u) for u in users]


# ═════════════════════════════════════════════════════════════════════════════
# ESPACE CLIENT
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/client/dashboard", response_model=ClientPortalDashboard)
async def client_dashboard(
    current_user: PortalUser = Depends(get_current_portal_user),
    db: TenantDBSession = None,
) -> ClientPortalDashboard:
    svc = PortalClientService(db, current_user.tenant_id, current_user)
    return await svc.dashboard()


@router.get("/client/invoices", response_model=list[ClientInvoiceOut])
async def client_invoices(
    current_user: PortalUser = Depends(get_current_portal_user),
    db: TenantDBSession = None,
    statut: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
) -> list[ClientInvoiceOut]:
    svc = PortalClientService(db, current_user.tenant_id, current_user)
    return await svc.lister_factures(statut=statut, limit=limit)


@router.get("/client/invoices/{invoice_id}")
async def client_invoice_detail(
    invoice_id: UUID,
    current_user: PortalUser = Depends(get_current_portal_user),
    db: TenantDBSession = None,
) -> dict:
    svc = PortalClientService(db, current_user.tenant_id, current_user)
    return await svc.get_facture_detail(invoice_id)


@router.get("/client/statement", response_model=ClientStatementOut)
async def client_statement(
    current_user: PortalUser = Depends(get_current_portal_user),
    db: TenantDBSession = None,
    date_debut: date = Query(...),
    date_fin: date = Query(...),
) -> ClientStatementOut:
    svc = PortalClientService(db, current_user.tenant_id, current_user)
    return await svc.releve_compte(date_debut, date_fin)


@router.post("/client/payments", response_model=OnlinePaymentInitOut)
async def client_initiate_payment(
    data: OnlinePaymentInitIn,
    current_user: PortalUser = Depends(get_current_portal_user),
    db: TenantDBSession = None,
) -> OnlinePaymentInitOut:
    svc = PortalClientService(db, current_user.tenant_id, current_user)
    result = await svc.initier_paiement(data)
    return OnlinePaymentInitOut(**result)


@router.get("/client/documents", response_model=list[SharedDocumentOut])
async def client_documents(
    current_user: PortalUser = Depends(get_current_portal_user),
    db: TenantDBSession = None,
) -> list[SharedDocumentOut]:
    svc = PortalClientService(db, current_user.tenant_id, current_user)
    docs = await svc.lister_documents()
    return [SharedDocumentOut.model_validate(d) for d in docs]


# ═════════════════════════════════════════════════════════════════════════════
# ESPACE FOURNISSEUR
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/supplier/dashboard", response_model=SupplierPortalDashboard)
async def supplier_dashboard(
    current_user: PortalUser = Depends(get_current_portal_user),
    db: TenantDBSession = None,
) -> SupplierPortalDashboard:
    svc = PortalSupplierService(db, current_user.tenant_id, current_user)
    return await svc.dashboard()


@router.get("/supplier/orders", response_model=list[SupplierOrderOut])
async def supplier_orders(
    current_user: PortalUser = Depends(get_current_portal_user),
    db: TenantDBSession = None,
    statut: str | None = Query(None),
) -> list[SupplierOrderOut]:
    svc = PortalSupplierService(db, current_user.tenant_id, current_user)
    return await svc.lister_commandes(statut=statut)


@router.post("/supplier/orders/{order_id}/accuser-reception")
async def supplier_acknowledge_order(
    order_id: UUID,
    current_user: PortalUser = Depends(get_current_portal_user),
    db: TenantDBSession = None,
) -> dict:
    svc = PortalSupplierService(db, current_user.tenant_id, current_user)
    return await svc.accuser_reception_commande(order_id)


@router.post("/supplier/invoices", response_model=SupplierInvoiceSubmissionOut, status_code=201)
async def supplier_submit_invoice(
    data: SupplierInvoiceSubmissionIn,
    current_user: PortalUser = Depends(get_current_portal_user),
    db: TenantDBSession = None,
) -> SupplierInvoiceSubmissionOut:
    svc = PortalSupplierService(db, current_user.tenant_id, current_user)
    return await svc.soumettre_facture(data)


@router.get("/supplier/invoices", response_model=list[SupplierInvoiceSubmissionOut])
async def supplier_invoices(
    current_user: PortalUser = Depends(get_current_portal_user),
    db: TenantDBSession = None,
    statut: str | None = Query(None),
) -> list[SupplierInvoiceSubmissionOut]:
    svc = PortalSupplierService(db, current_user.tenant_id, current_user)
    return await svc.lister_soumissions(statut=statut)


@router.get("/supplier/payments")
async def supplier_payments(
    current_user: PortalUser = Depends(get_current_portal_user),
    db: TenantDBSession = None,
    date_debut: date | None = Query(None),
    date_fin: date | None = Query(None),
) -> list[dict]:
    svc = PortalSupplierService(db, current_user.tenant_id, current_user)
    return await svc.lister_paiements(date_debut, date_fin)


# ═════════════════════════════════════════════════════════════════════════════
# WEBHOOKS PROVIDERS DE PAIEMENT (PUBLICS)
# ═════════════════════════════════════════════════════════════════════════════
@router.post("/webhooks/payments/{provider}")
async def payment_webhook(
    provider: str,
    request: Request,
    current_tenant: CurrentTenant,
    db: TenantDBSession,
) -> dict:
    """
    Webhook générique pour les providers de paiement (Wave, Stripe, CinetPay).
    À sécuriser par HMAC selon le provider.
    """
    payload = await request.json()

    # Récupérer la référence de paiement
    reference = (
        payload.get("reference")
        or payload.get("merchant_reference")
        or payload.get("metadata", {}).get("reference")
    )
    if not reference:
        raise HTTPException(400, "Référence manquante")

    from app.models.portal import OnlinePayment
    payment = await db.scalar(
        select(OnlinePayment).where(
            OnlinePayment.reference == reference,
            OnlinePayment.tenant_id == current_tenant.id,
        )
    )
    if payment is None:
        raise HTTPException(404, "Paiement introuvable")

    # Confirmer
    svc = PortalClientService(db, current_tenant.id, PortalUser(
        tenant_id=current_tenant.id,
        type_utilisateur="client",
        customer_id=payment.customer_id,
        email="webhook@system",
        prenom="Webhook",
        nom="System",
        statut="actif",
    ))
    await svc.confirmer_paiement(
        payment.id,
        provider_reference=payload.get("provider_reference", ""),
        provider_payload=payload,
    )

    return {"ok": True, "reference": reference}
