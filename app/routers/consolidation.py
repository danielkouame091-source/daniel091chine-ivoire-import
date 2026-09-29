"""Endpoints Consolidation & Groupes OHADA."""
from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.dependencies.auth import CurrentUser, RequireAdminTenant, RequireComptable
from app.dependencies.subscription import RequireActiveSubscription
from app.dependencies.tenant import CurrentTenant
from app.dependencies.tenant_db import TenantDBSession
from app.models.consolidation import (
    AdjustmentEntry,
    ConsolidationGroup,
    ConsolidationRun,
    EliminationEntry,
    IntercompanyTransaction,
)
from app.schemas.consolidation import (
    AdjustmentCreate,
    AdjustmentOut,
    BilanConsolideOut,
    CompteResultatConsolideOut,
    ConsolidationGroupCreate,
    ConsolidationGroupOut,
    ConsolidationGroupUpdate,
    ConsolidationRunDetailOut,
    ConsolidationRunOut,
    ConsolidationRunRequest,
    DetectionIntercosResult,
    EliminationAutoRequest,
    EliminationAutoResult,
    EliminationCreate,
    EliminationOut,
    ExchangeRateCreate,
    ExchangeRateOut,
    GroupCompanyCreate,
    GroupCompanyOut,
    GroupCompanyUpdate,
    IntercompanyTransactionCreate,
    IntercompanyTransactionOut,
    NotesAnnexesOut,
    PerimetreOut,
    TAFIREConsolideOut,
)
from app.services.consolidation_service import ConsolidationService

router = APIRouter()


# ═════════════════════════════════════════════════════════════════════════════
# GROUPES
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/groups", response_model=list[ConsolidationGroupOut])
async def list_groups(
    current_tenant: CurrentTenant,
    _: RequireComptable,
    db: TenantDBSession,
    actif_only: bool = True,
) -> list[ConsolidationGroupOut]:
    svc = ConsolidationService(db, current_tenant.id, current_tenant.id)
    groups = await svc.lister_groupes(actif_only=actif_only)
    return [ConsolidationGroupOut.model_validate(g) for g in groups]


@router.post("/groups", response_model=ConsolidationGroupOut, status_code=201)
async def create_group(
    data: ConsolidationGroupCreate,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> ConsolidationGroupOut:
    svc = ConsolidationService(db, current_tenant.id, current_user.id)
    group = await svc.creer_groupe(data)
    return ConsolidationGroupOut.model_validate(group)


@router.patch("/groups/{group_id}", response_model=ConsolidationGroupOut)
async def update_group(
    group_id: UUID,
    data: ConsolidationGroupUpdate,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> ConsolidationGroupOut:
    svc = ConsolidationService(db, current_tenant.id, current_user.id)
    group = await svc.modifier_groupe(group_id, data)
    return ConsolidationGroupOut.model_validate(group)


# ═════════════════════════════════════════════════════════════════════════════
# SOCIÉTÉS MEMBRES
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/groups/{group_id}/companies", response_model=list[GroupCompanyOut])
async def list_companies(
    group_id: UUID,
    current_tenant: CurrentTenant,
    _: RequireComptable,
    db: TenantDBSession,
) -> list[GroupCompanyOut]:
    svc = ConsolidationService(db, current_tenant.id, current_tenant.id)
    companies = await svc.lister_societes(group_id)
    return [GroupCompanyOut.model_validate(c) for c in companies]


@router.post("/groups/{group_id}/companies", response_model=GroupCompanyOut, status_code=201)
async def add_company(
    group_id: UUID,
    data: GroupCompanyCreate,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> GroupCompanyOut:
    svc = ConsolidationService(db, current_tenant.id, current_user.id)
    company = await svc.ajouter_societe(group_id, data)
    return GroupCompanyOut.model_validate(company)


@router.patch("/companies/{company_id}", response_model=GroupCompanyOut)
async def update_company(
    company_id: UUID,
    data: GroupCompanyUpdate,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> GroupCompanyOut:
    svc = ConsolidationService(db, current_tenant.id, current_user.id)
    company = await svc.modifier_societe(company_id, data)
    return GroupCompanyOut.model_validate(company)


# ═════════════════════════════════════════════════════════════════════════════
# PÉRIMÈTRE
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/groups/{group_id}/perimetre", response_model=PerimetreOut)
async def get_perimetre(
    group_id: UUID,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
    date_arret: date = Query(default_factory=date.today),
) -> PerimetreOut:
    svc = ConsolidationService(db, current_tenant.id, current_user.id)
    return await svc.determiner_perimetre(group_id, date_arret)


# ═════════════════════════════════════════════════════════════════════════════
# TRANSACTIONS INTRAGROUPE
# ═════════════════════════════════════════════════════════════════════════════
@router.post("/groups/{group_id}/intercos", response_model=IntercompanyTransactionOut, status_code=201)
async def create_interco(
    group_id: UUID,
    data: IntercompanyTransactionCreate,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> IntercompanyTransactionOut:
    svc = ConsolidationService(db, current_tenant.id, current_user.id)
    ico = await svc.creer_transaction_interco(group_id, data)
    return IntercompanyTransactionOut.model_validate(ico)


@router.post("/groups/{group_id}/intercos/detecter", response_model=DetectionIntercosResult)
async def detect_intercos(
    group_id: UUID,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
    date_debut: date = Query(...),
    date_fin: date = Query(...),
) -> DetectionIntercosResult:
    svc = ConsolidationService(db, current_tenant.id, current_user.id)
    return await svc.detecter_intercos_auto(group_id, date_debut, date_fin)


# ═════════════════════════════════════════════════════════════════════════════
# ÉLIMINATIONS
# ═════════════════════════════════════════════════════════════════════════════
@router.post("/groups/{group_id}/eliminations", response_model=EliminationOut, status_code=201)
async def create_elimination(
    group_id: UUID,
    data: EliminationCreate,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> EliminationOut:
    svc = ConsolidationService(db, current_tenant.id, current_user.id)
    elim = await svc.creer_elimination(group_id, data)
    return EliminationOut.model_validate(elim)


@router.post("/groups/{group_id}/eliminations/auto", response_model=EliminationAutoResult)
async def auto_eliminations(
    group_id: UUID,
    data: EliminationAutoRequest,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> EliminationAutoResult:
    svc = ConsolidationService(db, current_tenant.id, current_user.id)
    return await svc.generer_eliminations_auto(group_id, data)


# ═════════════════════════════════════════════════════════════════════════════
# RETRAITEMENTS
# ═════════════════════════════════════════════════════════════════════════════
@router.post("/groups/{group_id}/adjustments", response_model=AdjustmentOut, status_code=201)
async def create_adjustment(
    group_id: UUID,
    data: AdjustmentCreate,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> AdjustmentOut:
    svc = ConsolidationService(db, current_tenant.id, current_user.id)
    adj = await svc.creer_retraitement(group_id, data)
    return AdjustmentOut.model_validate(adj)


# ═════════════════════════════════════════════════════════════════════════════
# TAUX DE CHANGE
# ═════════════════════════════════════════════════════════════════════════════
@router.post("/exchange-rates", response_model=ExchangeRateOut, status_code=201)
async def create_exchange_rate(
    data: ExchangeRateCreate,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> ExchangeRateOut:
    svc = ConsolidationService(db, current_tenant.id, current_user.id)
    fx = await svc.creer_taux_change(
        data.devise_source, data.devise_cible, data.date_taux,
        data.taux_cloture, data.taux_moyen, data.source,
    )
    return ExchangeRateOut.model_validate(fx)


# ═════════════════════════════════════════════════════════════════════════════
# EXÉCUTION DE CONSOLIDATION
# ═════════════════════════════════════════════════════════════════════════════
@router.post("/groups/{group_id}/runs", response_model=ConsolidationRunOut, status_code=201)
async def execute_run(
    group_id: UUID,
    data: ConsolidationRunRequest,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> ConsolidationRunOut:
    svc = ConsolidationService(db, current_tenant.id, current_user.id)
    run = await svc.executer_consolidation(group_id, data)
    return ConsolidationRunOut.model_validate(run)


@router.post("/runs/{run_id}/valider", response_model=ConsolidationRunOut)
async def validate_run(
    run_id: UUID,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> ConsolidationRunOut:
    svc = ConsolidationService(db, current_tenant.id, current_user.id)
    run = await svc.valider_run(run_id)
    return ConsolidationRunOut.model_validate(run)


@router.get("/groups/{group_id}/runs", response_model=list[ConsolidationRunOut])
async def list_runs(
    group_id: UUID,
    current_tenant: CurrentTenant,
    _: RequireComptable,
    db: TenantDBSession,
    limit: int = 50,
) -> list[ConsolidationRunOut]:
    stmt = (
        select(ConsolidationRun)
        .where(ConsolidationRun.group_id == group_id)
        .order_by(ConsolidationRun.date_fin.desc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [ConsolidationRunOut.model_validate(r) for r in rows]


# ═════════════════════════════════════════════════════════════════════════════
# COMPTES CONSOLIDÉS
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/runs/{run_id}/bilan", response_model=BilanConsolideOut)
async def get_bilan(
    run_id: UUID,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
) -> BilanConsolideOut:
    svc = ConsolidationService(db, current_tenant.id, current_user.id)
    return await svc.get_bilan_consolide(run_id)


@router.get("/runs/{run_id}/compte-resultat", response_model=CompteResultatConsolideOut)
async def get_compte_resultat(
    run_id: UUID,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
) -> CompteResultatConsolideOut:
    svc = ConsolidationService(db, current_tenant.id, current_user.id)
    return await svc.get_compte_resultat_consolide(run_id)


@router.get("/runs/{run_id}/notes", response_model=NotesAnnexesOut)
async def get_notes(
    run_id: UUID,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
) -> NotesAnnexesOut:
    svc = ConsolidationService(db, current_tenant.id, current_user.id)
    return await svc.get_notes_annexes(run_id)
