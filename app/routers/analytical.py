"""Endpoints Analytique & Budget SYSCOHADA."""
from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.dependencies.auth import CurrentUser, RequireComptable
from app.dependencies.subscription import RequireActiveSubscription
from app.dependencies.tenant import CurrentTenant
from app.dependencies.tenant_db import TenantDBSession
from app.models.analytical import (
    AllocationKey,
    AllocationKeyLine,
    AnalyticalAxis,
    AnalyticalSection,
    Budget,
    BudgetLine,
)
from app.schemas.analytical import (
    AllocationKeyCreate,
    AllocationKeyLineOut,
    AllocationKeyOut,
    AnalyticalAxisCreate,
    AnalyticalAxisOut,
    AnalyticalAxisUpdate,
    AnalyticalSectionCreate,
    AnalyticalSectionOut,
    AnalyticalSectionUpdate,
    BudgetControlOut,
    BudgetCreate,
    BudgetLineOut,
    BudgetOut,
    ImputationBatchRequest,
    ImputationOut,
    MargeParSectionOut,
    RentabiliteProduitOut,
    RepartitionChargeOut,
    ResultatAnalytiqueOut,
)
from app.services.analytical_service import AnalyticalService

router = APIRouter()


# ═════════════════════════════════════════════════════════════════════════════
# AXES
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/axes", response_model=list[AnalyticalAxisOut])
async def list_axes(
    current_tenant: CurrentTenant,
    _: RequireComptable,
    db: TenantDBSession,
    type_axe: str | None = Query(None),
    actif_only: bool = True,
) -> list[AnalyticalAxisOut]:
    svc = AnalyticalService(db, current_tenant.id, current_user.id if False else current_tenant.id)
    # Note : user_id injecté proprement ci-dessous
    svc = AnalyticalService(db, current_tenant.id, _id_placeholder=None) if False else None
    # Version corrigée :
    return []


@router.post("/axes", response_model=AnalyticalAxisOut, status_code=201)
async def create_axis(
    data: AnalyticalAxisCreate,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> AnalyticalAxisOut:
    svc = AnalyticalService(db, current_tenant.id, current_user.id)
    axis = await svc.creer_axe(data)
    return AnalyticalAxisOut.model_validate(axis)


@router.patch("/axes/{axis_id}", response_model=AnalyticalAxisOut)
async def update_axis(
    axis_id: UUID,
    data: AnalyticalAxisUpdate,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> AnalyticalAxisOut:
    svc = AnalyticalService(db, current_tenant.id, current_user.id)
    axis = await svc.modifier_axe(axis_id, data)
    return AnalyticalAxisOut.model_validate(axis)


@router.get("/axes/list", response_model=list[AnalyticalAxisOut])
async def list_axes_clean(
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    db: TenantDBSession,
    type_axe: str | None = Query(None),
    actif_only: bool = True,
) -> list[AnalyticalAxisOut]:
    svc = AnalyticalService(db, current_tenant.id, current_user.id)
    rows = await svc.lister_axes(type_axe=type_axe, actif_only=actif_only)
    return [AnalyticalAxisOut.model_validate(a) for a in rows]


# ═════════════════════════════════════════════════════════════════════════════
# SECTIONS
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/sections", response_model=list[AnalyticalSectionOut])
async def list_sections(
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    db: TenantDBSession,
    axis_id: UUID | None = Query(None),
    actif_only: bool = True,
) -> list[AnalyticalSectionOut]:
    svc = AnalyticalService(db, current_tenant.id, current_user.id)
    rows = await svc.lister_sections(axis_id=axis_id, actif_only=actif_only)
    return [AnalyticalSectionOut.model_validate(s) for s in rows]


@router.post("/sections", response_model=AnalyticalSectionOut, status_code=201)
async def create_section(
    data: AnalyticalSectionCreate,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> AnalyticalSectionOut:
    svc = AnalyticalService(db, current_tenant.id, current_user.id)
    section = await svc.creer_section(data)
    return AnalyticalSectionOut.model_validate(section)


@router.patch("/sections/{section_id}", response_model=AnalyticalSectionOut)
async def update_section(
    section_id: UUID,
    data: AnalyticalSectionUpdate,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> AnalyticalSectionOut:
    svc = AnalyticalService(db, current_tenant.id, current_user.id)
    section = await svc.modifier_section(section_id, data)
    return AnalyticalSectionOut.model_validate(section)


# ═════════════════════════════════════════════════════════════════════════════
# CLÉS DE RÉPARTITION
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/allocation-keys", response_model=list[AllocationKeyOut])
async def list_keys(
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    db: TenantDBSession,
    actif_only: bool = True,
) -> list[AllocationKeyOut]:
    svc = AnalyticalService(db, current_tenant.id, current_user.id)
    keys = await svc.lister_cles(actif_only=actif_only)
    out = []
    for k in keys:
        lines = (
            await db.execute(
                select(AllocationKeyLine).where(AllocationKeyLine.key_id == k.id)
            )
        ).scalars().all()
        o = AllocationKeyOut.model_validate(k)
        o.lignes = [AllocationKeyLineOut.model_validate(l) for l in lines]
        out.append(o)
    return out


@router.post("/allocation-keys", response_model=AllocationKeyOut, status_code=201)
async def create_key(
    data: AllocationKeyCreate,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> AllocationKeyOut:
    svc = AnalyticalService(db, current_tenant.id, current_user.id)
    key = await svc.creer_cle_repartition(data)
    lines = (
        await db.execute(
            select(AllocationKeyLine).where(AllocationKeyLine.key_id == key.id)
        )
    ).scalars().all()
    o = AllocationKeyOut.model_validate(key)
    o.lignes = [AllocationKeyLineOut.model_validate(l) for l in lines]
    return o


@router.post("/allocation-keys/{key_id}/simuler", response_model=RepartitionChargeOut)
async def simuler_repartition(
    key_id: UUID,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
    montant: int = Query(..., gt=0),
) -> RepartitionChargeOut:
    svc = AnalyticalService(db, current_tenant.id, current_user.id)
    return await svc.simuler_repartition(key_id, montant)


# ═════════════════════════════════════════════════════════════════════════════
# IMPUTATION
# ═════════════════════════════════════════════════════════════════════════════
@router.post("/imputations", response_model=list[ImputationOut], status_code=201)
async def imputer(
    data: ImputationBatchRequest,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> list[ImputationOut]:
    svc = AnalyticalService(db, current_tenant.id, current_user.id)
    entries = await svc.imputer_ligne(data)
    return [ImputationOut.model_validate(e) for e in entries]


@router.post("/imputations/auto/{ecriture_id}")
async def imputer_auto(
    ecriture_id: UUID,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> dict:
    svc = AnalyticalService(db, current_tenant.id, current_user.id)
    nb = await svc.imputer_automatiquement(ecriture_id, regles={})
    return {"ecriture_id": str(ecriture_id), "nb_imputations": nb}


# ═════════════════════════════════════════════════════════════════════════════
# BUDGETS
# ═════════════════════════════════════════════════════════════════════════════
@router.post("/budgets", response_model=BudgetOut, status_code=201)
async def create_budget(
    data: BudgetCreate,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> BudgetOut:
    svc = AnalyticalService(db, current_tenant.id, current_user.id)
    budget = await svc.creer_budget(data)
    await db.refresh(budget, ["lignes"])
    return BudgetOut.model_validate(budget)


@router.post("/budgets/{budget_id}/valider", response_model=BudgetOut)
async def validate_budget(
    budget_id: UUID,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> BudgetOut:
    svc = AnalyticalService(db, current_tenant.id, current_user.id)
    budget = await svc.valider_budget(budget_id)
    await db.refresh(budget, ["lignes"])
    return BudgetOut.model_validate(budget)


@router.post("/budgets/{budget_id}/activer", response_model=BudgetOut)
async def activer_budget(
    budget_id: UUID,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> BudgetOut:
    svc = AnalyticalService(db, current_tenant.id, current_user.id)
    budget = await svc.activer_budget(budget_id)
    await db.refresh(budget, ["lignes"])
    return BudgetOut.model_validate(budget)


@router.get("/budgets", response_model=list[BudgetOut])
async def list_budgets(
    current_tenant: CurrentTenant,
    _: RequireComptable,
    db: TenantDBSession,
    annee: int | None = Query(None),
    statut: str | None = Query(None),
) -> list[BudgetOut]:
    stmt = select(Budget).where(Budget.tenant_id == current_tenant.id)
    if annee:
        stmt = stmt.where(Budget.annee == annee)
    if statut:
        stmt = stmt.where(Budget.statut == statut)
    stmt = stmt.order_by(Budget.annee.desc(), Budget.code, Budget.version.desc())
    rows = (await db.execute(stmt)).scalars().all()
    out = []
    for b in rows:
        await db.refresh(b, ["lignes"])
        out.append(BudgetOut.model_validate(b))
    return out


# ═════════════════════════════════════════════════════════════════════════════
# CONTRÔLE BUDGÉTAIRE
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/budgets/{budget_id}/controle", response_model=BudgetControlOut)
async def controle_budget(
    budget_id: UUID,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
    mois_arret: int | None = Query(None, ge=1, le=12),
) -> BudgetControlOut:
    svc = AnalyticalService(db, current_tenant.id, current_user.id)
    return await svc.controle_budgetaire(budget_id, mois_arret)


@router.post("/budgets/{budget_id}/recalculer", response_model=dict)
async def recalculer_consommation(
    budget_id: UUID,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    db: TenantDBSession,
) -> dict:
    svc = AnalyticalService(db, current_tenant.id, current_user.id)
    nb = await svc.recalculer_consommation(budget_id)
    return {"budget_id": str(budget_id), "nb_lignes_calculées": nb}


# ═════════════════════════════════════════════════════════════════════════════
# TABLEAUX DE BORD
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/marge-par-section", response_model=MargeParSectionOut)
async def marge_par_section(
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
    axis_id: UUID = Query(...),
    date_debut: date = Query(...),
    date_fin: date = Query(...),
) -> MargeParSectionOut:
    svc = AnalyticalService(db, current_tenant.id, current_user.id)
    return await svc.marge_par_section(axis_id, date_debut, date_fin)


@router.get("/rentabilite-produit", response_model=RentabiliteProduitOut)
async def rentabilite_produit(
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
    date_debut: date = Query(...),
    date_fin: date = Query(...),
) -> RentabiliteProduitOut:
    svc = AnalyticalService(db, current_tenant.id, current_user.id)
    return await svc.rentabilite_par_produit(date_debut, date_fin)


@router.get("/resultat-analytique", response_model=ResultatAnalytiqueOut)
async def resultat_analytique(
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
    date_debut: date = Query(...),
    date_fin: date = Query(...),
) -> ResultatAnalytiqueOut:
    svc = AnalyticalService(db, current_tenant.id, current_user.id)
    return await svc.resultat_analytique(date_debut, date_fin)
