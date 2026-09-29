"""Endpoints Immobilisations & Amortissements SYSCOHADA."""
from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.dependencies.auth import CurrentUser, RequireComptable
from app.dependencies.subscription import RequireActiveSubscription
from app.dependencies.tenant import CurrentTenant
from app.dependencies.tenant_db import TenantDBSession
from app.models.asset import AssetDisposal, AssetRevaluation, DepreciationEntry, FixedAsset
from app.schemas.asset import (
    AmortissementPlanOut,
    DepreciationEntryOut,
    DisposalCreate,
    DisposalOut,
    DotationExerciceOut,
    FixedAssetCreate,
    FixedAssetOut,
    FixedAssetUpdate,
    RevaluationCreate,
    RevaluationOut,
    TableauImmobilisationsOut,
)
from app.services.asset_service import AssetService

router = APIRouter()


# ═════════════════════════════════════════════════════════════════════════════
# IMMOBILISATIONS
# ═════════════════════════════════════════════════════════════════════════════
@router.get("", response_model=list[FixedAssetOut])
async def list_assets(
    current_tenant: CurrentTenant,
    _: RequireComptable,
    db: TenantDBSession,
    statut: str | None = Query(None),
    famille: str | None = Query(None),
    limit: int = 500,
) -> list[FixedAssetOut]:
    stmt = select(FixedAsset).where(FixedAsset.tenant_id == current_tenant.id)
    if statut:
        stmt = stmt.where(FixedAsset.statut == statut)
    if famille:
        stmt = stmt.where(FixedAsset.famille == famille)
    stmt = stmt.order_by(FixedAsset.code).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [FixedAssetOut.model_validate(a) for a in rows]


@router.post("", response_model=FixedAssetOut, status_code=201)
async def create_asset(
    data: FixedAssetCreate,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
    comptabiliser_acquisition: bool = Query(False),
) -> FixedAssetOut:
    svc = AssetService(db, current_tenant.id, current_user.id)
    asset = await svc.creer_immobilisation(data, comptabiliser_acquisition)
    return FixedAssetOut.model_validate(asset)


@router.get("/{asset_id}", response_model=FixedAssetOut)
async def get_asset(
    asset_id: UUID,
    current_tenant: CurrentTenant,
    _: RequireComptable,
    db: TenantDBSession,
) -> FixedAssetOut:
    asset = await db.scalar(
        select(FixedAsset).where(
            FixedAsset.id == asset_id,
            FixedAsset.tenant_id == current_tenant.id,
        )
    )
    if asset is None:
        from fastapi import HTTPException
        raise HTTPException(404, "Immobilisation introuvable")
    return FixedAssetOut.model_validate(asset)


@router.patch("/{asset_id}", response_model=FixedAssetOut)
async def update_asset(
    asset_id: UUID,
    data: FixedAssetUpdate,
    current_tenant: CurrentTenant,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> FixedAssetOut:
    asset = await db.scalar(
        select(FixedAsset).where(
            FixedAsset.id == asset_id,
            FixedAsset.tenant_id == current_tenant.id,
        )
    )
    if asset is None:
        from fastapi import HTTPException
        raise HTTPException(404, "Immobilisation introuvable")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(asset, k, v)
    await db.flush()
    return FixedAssetOut.model_validate(asset)


# ═════════════════════════════════════════════════════════════════════════════
# PLAN D'AMORTISSEMENT
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/{asset_id}/plan", response_model=AmortissementPlanOut)
async def get_plan(
    asset_id: UUID,
    current_tenant: CurrentTenant,
    _: RequireComptable,
    db: TenantDBSession,
) -> AmortissementPlanOut:
    asset = await db.scalar(
        select(FixedAsset).where(
            FixedAsset.id == asset_id,
            FixedAsset.tenant_id == current_tenant.id,
        )
    )
    if asset is None:
        from fastapi import HTTPException
        raise HTTPException(404, "Immobilisation introuvable")

    rows = (
        await db.execute(
            select(DepreciationEntry)
            .where(DepreciationEntry.asset_id == asset_id)
            .order_by(DepreciationEntry.exercice)
        )
    ).scalars().all()

    return AmortissementPlanOut(
        asset_id=asset.id,
        valeur_origine=asset.valeur_origine,
        valeur_residuelle=asset.valeur_residuelle,
        base_amortissable=asset.base_amortissable,
        methode=asset.methode_amortissement,
        duree_ans=asset.duree_amortissement_ans,
        taux=asset.taux_amortissement,
        entrees=[DepreciationEntryOut.model_validate(e) for e in rows],
    )


# ═════════════════════════════════════════════════════════════════════════════
# COMPTABILISATION DES DOTATIONS
# ═════════════════════════════════════════════════════════════════════════════
@router.post("/dotations/{exercice}/comptabiliser", response_model=dict)
async def comptabiliser_dotations(
    exercice: int,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
    asset_id: UUID | None = Query(None),
) -> dict:
    svc = AssetService(db, current_tenant.id, current_user.id)
    return await svc.comptabiliser_dotations(exercice, asset_id)


# ═════════════════════════════════════════════════════════════════════════════
# CESSION / REBUT
# ═════════════════════════════════════════════════════════════════════════════
@router.post("/cessions", response_model=DisposalOut, status_code=201)
async def ceder_immobilisation(
    data: DisposalCreate,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> DisposalOut:
    svc = AssetService(db, current_tenant.id, current_user.id)
    disposal = await svc.ceder_immobilisation(data)
    return DisposalOut.model_validate(disposal)


@router.get("/cessions/list", response_model=list[DisposalOut])
async def list_disposals(
    current_tenant: CurrentTenant,
    _: RequireComptable,
    db: TenantDBSession,
    limit: int = 200,
) -> list[DisposalOut]:
    rows = (
        await db.execute(
            select(AssetDisposal)
            .where(AssetDisposal.tenant_id == current_tenant.id)
            .order_by(AssetDisposal.date_cession.desc())
            .limit(limit)
        )
    ).scalars().all()
    return [DisposalOut.model_validate(d) for d in rows]


# ═════════════════════════════════════════════════════════════════════════════
# RÉÉVALUATION
# ═════════════════════════════════════════════════════════════════════════════
@router.post("/revaluations", response_model=RevaluationOut, status_code=201)
async def reevaluer(
    data: RevaluationCreate,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> RevaluationOut:
    svc = AssetService(db, current_tenant.id, current_user.id)
    reval = await svc.reevaluer(data)
    return RevaluationOut.model_validate(reval)


# ═════════════════════════════════════════════════════════════════════════════
# REPORTING
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/tableau", response_model=TableauImmobilisationsOut)
async def tableau_immobilisations(
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
    date_arret: date = Query(default_factory=date.today),
) -> TableauImmobilisationsOut:
    svc = AssetService(db, current_tenant.id, current_user.id)
    data = await svc.tableau_immobilisations(date_arret)
    return TableauImmobilisationsOut(tenant_id=current_tenant.id, **data)
