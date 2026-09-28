"""Endpoints IA/NLP : suggestions, feedback, prévisions."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends

from app.dependencies.auth import CurrentUser, RequireComptable
from app.dependencies.subscription import RequireActiveSubscription
from app.dependencies.tenant import CurrentTenant
from app.dependencies.tenant_db import TenantDBSession
from app.schemas.nlp import (
    ForecastOut,
    ForecastRequest,
    NlpStatsOut,
    NlpSuggestionAccept,
    NlpSuggestionOut,
    SuggestionRequest,
)
from app.services.forecast_service import ForecastService
from app.services.nlp_service import NlpService

router = APIRouter()


# ─── Suggestions NLP ──────────────────────────────────────────────────────
@router.post("/suggerer", response_model=NlpSuggestionOut, status_code=201)
async def suggerer(
    data: SuggestionRequest,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> NlpSuggestionOut:
    svc = NlpService(db, current_tenant.id, current_user.id)
    return await svc.suggerer(data)


@router.post("/suggestions/{suggestion_id}/accepter")
async def accepter_suggestion(
    suggestion_id: UUID,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
    data: NlpSuggestionAccept | None = None,
) -> dict:
    svc = NlpService(db, current_tenant.id, current_user.id)
    return await svc.accepter(suggestion_id, data)


@router.post("/suggestions/{suggestion_id}/rejeter", status_code=204)
async def rejeter_suggestion(
    suggestion_id: UUID,
    motif: str,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> None:
    svc = NlpService(db, current_tenant.id, current_user.id)
    await svc.rejeter(suggestion_id, motif)


@router.get("/stats", response_model=NlpStatsOut)
async def stats_nlp(
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
) -> NlpStatsOut:
    svc = NlpService(db, current_tenant.id, current_user.id)
    return NlpStatsOut(**await svc.get_stats())


# ─── Prévision trésorerie ─────────────────────────────────────────────────
@router.post("/forecast", response_model=ForecastOut)
async def calculer_prevision(
    data: ForecastRequest,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
) -> ForecastOut:
    svc = ForecastService(db, current_tenant.id, current_user.id)
    f = await svc.calculer(horizon_jours=data.horizon_jours)
    return ForecastOut.model_validate(f)


@router.get("/forecast/dernier", response_model=ForecastOut | None)
async def dernier_forecast(
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
) -> ForecastOut | None:
    svc = ForecastService(db, current_tenant.id, current_user.id)
    f = await svc.dernier()
    return ForecastOut.model_validate(f) if f else None
