"""Endpoints Trésorerie & Rapprochement bancaire SYSCOHADA."""
from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, File, Query, UploadFile
from sqlalchemy import select

from app.dependencies.auth import CurrentUser, RequireComptable
from app.dependencies.subscription import RequireActiveSubscription
from app.dependencies.tenant import CurrentTenant
from app.dependencies.tenant_db import TenantDBSession
from app.models.treasury import (
    BankStatement,
    BankStatementLine,
    ReconciliationSession,
    TreasuryAccount,
)
from app.schemas.treasury import (
    BankStatementDetailOut,
    BankStatementLineOut,
    BankStatementOut,
    CashDashboard13WeeksOut,
    CashPositionOut,
    EtatRapprochementOut,
    RapprochementAutoRequest,
    RapprochementAutoResultOut,
    RapprochementManuelRequest,
    ReconciliationSessionOut,
    TreasuryAccountCreate,
    TreasuryAccountOut,
    TreasuryAccountUpdate,
)
from app.services.treasury_service import TreasuryService

router = APIRouter()


# ═════════════════════════════════════════════════════════════════════════════
# COMPTES DE TRÉSORERIE
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/accounts", response_model=list[TreasuryAccountOut])
async def list_accounts(
    current_tenant: CurrentTenant,
    _: RequireComptable,
    db: TenantDBSession,
    actif_only: bool = True,
) -> list[TreasuryAccountOut]:
    stmt = select(TreasuryAccount).where(TreasuryAccount.tenant_id == current_tenant.id)
    if actif_only:
        stmt = stmt.where(TreasuryAccount.actif.is_(True))
    stmt = stmt.order_by(TreasuryAccount.code)
    rows = (await db.execute(stmt)).scalars().all()
    return [TreasuryAccountOut.model_validate(a) for a in rows]


@router.post("/accounts", response_model=TreasuryAccountOut, status_code=201)
async def create_account(
    data: TreasuryAccountCreate,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> TreasuryAccountOut:
    svc = TreasuryService(db, current_tenant.id, current_user.id)
    acc = await svc.creer_compte(data)
    return TreasuryAccountOut.model_validate(acc)


@router.patch("/accounts/{acc_id}", response_model=TreasuryAccountOut)
async def update_account(
    acc_id: UUID,
    data: TreasuryAccountUpdate,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> TreasuryAccountOut:
    svc = TreasuryService(db, current_tenant.id, current_user.id)
    acc = await svc.modifier_compte(acc_id, data)
    return TreasuryAccountOut.model_validate(acc)


@router.post("/accounts/{acc_id}/recalculer", response_model=dict)
async def recalc_solde(
    acc_id: UUID,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    db: TenantDBSession,
) -> dict:
    svc = TreasuryService(db, current_tenant.id, current_user.id)
    solde = await svc.recalculer_solde(acc_id)
    return {"account_id": str(acc_id), "solde": solde}


# ═════════════════════════════════════════════════════════════════════════════
# RELEVÉS BANCAIRES
# ═════════════════════════════════════════════════════════════════════════════
@router.post("/statements/import", response_model=BankStatementOut, status_code=201)
async def import_statement(
    treasury_account_id: UUID,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
    file: UploadFile = File(...),
    format: str = Query("csv", pattern=r"^(csv|ofx|mt940)$"),
    reference: str | None = Query(None),
) -> BankStatementOut:
    svc = TreasuryService(db, current_tenant.id, current_user.id)
    stmt = await svc.importer_releve(
        treasury_account_id=treasury_account_id,
        file=file,
        format_source=format,
        reference=reference,
    )
    return BankStatementOut.model_validate(stmt)


@router.get("/statements", response_model=list[BankStatementOut])
async def list_statements(
    current_tenant: CurrentTenant,
    _: RequireComptable,
    db: TenantDBSession,
    treasury_account_id: UUID | None = Query(None),
    limit: int = 100,
) -> list[BankStatementOut]:
    stmt = select(BankStatement).where(BankStatement.tenant_id == current_tenant.id)
    if treasury_account_id:
        stmt = stmt.where(BankStatement.treasury_account_id == treasury_account_id)
    stmt = stmt.order_by(BankStatement.date_fin.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [BankStatementOut.model_validate(s) for s in rows]


@router.get("/statements/{stmt_id}", response_model=BankStatementDetailOut)
async def get_statement_detail(
    stmt_id: UUID,
    current_tenant: CurrentTenant,
    _: RequireComptable,
    db: TenantDBSession,
) -> BankStatementDetailOut:
    stmt = await db.scalar(
        select(BankStatement).where(
            BankStatement.id == stmt_id,
            BankStatement.tenant_id == current_tenant.id,
        )
    )
    if stmt is None:
        from fastapi import HTTPException
        raise HTTPException(404, "Relevé introuvable")
    lines = (
        await db.execute(
            select(BankStatementLine)
            .where(BankStatementLine.statement_id == stmt.id)
            .order_by(BankStatementLine.date_operation)
        )
    ).scalars().all()
    out = BankStatementDetailOut.model_validate(stmt)
    out.lignes = [BankStatementLineOut.model_validate(l) for l in lines]
    return out


# ═════════════════════════════════════════════════════════════════════════════
# RAPPROCHEMENT
# ═════════════════════════════════════════════════════════════════════════════
@router.post("/statements/{stmt_id}/rapprocher-auto", response_model=RapprochementAutoResultOut)
async def rapprocher_auto(
    stmt_id: UUID,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
    data: RapprochementAutoRequest | None = None,
) -> RapprochementAutoResultOut:
    payload = data or RapprochementAutoRequest(statement_id=stmt_id)
    payload.statement_id = stmt_id
    svc = TreasuryService(db, current_tenant.id, current_user.id)
    return await svc.rapprocher_automatique(payload)


@router.post("/statements/lines/{line_id}/rapprocher-manuel", response_model=BankStatementLineOut)
async def rapprocher_manuel(
    line_id: UUID,
    data: RapprochementManuelRequest,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> BankStatementLineOut:
    svc = TreasuryService(db, current_tenant.id, current_user.id)
    bl = await svc.rapprocher_manuel(
        statement_line_id=line_id,
        ecriture_ligne_id=data.ecriture_ligne_id,
        creer_ecriture=data.creer_ecriture,
    )
    return BankStatementLineOut.model_validate(bl)


@router.get("/statements/{stmt_id}/etat", response_model=EtatRapprochementOut)
async def etat_rapprochement(
    stmt_id: UUID,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
) -> EtatRapprochementOut:
    svc = TreasuryService(db, current_tenant.id, current_user.id)
    return await svc.generer_etat_rapprochement(stmt_id)


@router.post("/statements/{stmt_id}/cloturer", response_model=ReconciliationSessionOut)
async def cloturer_rapprochement(
    stmt_id: UUID,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> ReconciliationSessionOut:
    svc = TreasuryService(db, current_tenant.id, current_user.id)
    session = await svc.creer_session_rapprochement(stmt_id)
    return ReconciliationSessionOut.model_validate(session)


# ═════════════════════════════════════════════════════════════════════════════
# TABLEAU DE BORD
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/position", response_model=CashPositionOut)
async def position_actuelle(
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
) -> CashPositionOut:
    svc = TreasuryService(db, current_tenant.id, current_user.id)
    return await svc.calculer_position_actuelle()


@router.get("/dashboard-13-weeks", response_model=CashDashboard13WeeksOut)
async def dashboard_13_weeks(
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
) -> CashDashboard13WeeksOut:
    svc = TreasuryService(db, current_tenant.id, current_user.id)
    return await svc.calculer_previsions_13_semaines()
