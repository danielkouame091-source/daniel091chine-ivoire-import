"""Endpoints Projets & Chantiers SYSCOHADA."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.dependencies.auth import CurrentUser, RequireAdminTenant, RequireComptable
from app.dependencies.subscription import RequireActiveSubscription
from app.dependencies.tenant import CurrentTenant
from app.dependencies.tenant_db import TenantDBSession
from app.models.project import (
    ProgressBilling,
    Project,
    ProjectCost,
    ProjectMilestone,
    ProjectPhase,
    ProjectTask,
)
from app.schemas.project import (
    AvancementSituationOut,
    ProgressBillingCreate,
    ProgressBillingDetailOut,
    ProgressBillingOut,
    ProjectCostCreate,
    ProjectCostOut,
    ProjectCreate,
    ProjectDetailOut,
    ProjectMarginOut,
    ProjectMilestoneCreate,
    ProjectMilestoneOut,
    ProjectOut,
    ProjectPhaseCreate,
    ProjectPhaseOut,
    ProjectPhaseUpdate,
    ProjectPortfolioOut,
    ProjectTaskCreate,
    ProjectTaskOut,
    ProjectTaskUpdate,
    ProjectUpdate,
)
from app.services.project_service import ProjectService

router = APIRouter()


# ═════════════════════════════════════════════════════════════════════════════
# PROJETS
# ═════════════════════════════════════════════════════════════════════════════
@router.get("", response_model=list[ProjectOut])
async def list_projects(
    current_tenant: CurrentTenant,
    _: RequireComptable,
    db: TenantDBSession,
    statut: str | None = Query(None),
    limit: int = 500,
) -> list[ProjectOut]:
    stmt = select(Project).where(Project.tenant_id == current_tenant.id)
    if statut:
        stmt = stmt.where(Project.statut == statut)
    stmt = stmt.order_by(Project.code).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [ProjectOut.model_validate(p) for p in rows]


@router.post("", response_model=ProjectOut, status_code=201)
async def create_project(
    data: ProjectCreate,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> ProjectOut:
    svc = ProjectService(db, current_tenant.id, current_user.id)
    p = await svc.creer_projet(data)
    return ProjectOut.model_validate(p)


@router.get("/{project_id}", response_model=ProjectDetailOut)
async def get_project(
    project_id: UUID,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    db: TenantDBSession,
) -> ProjectDetailOut:
    svc = ProjectService(db, current_tenant.id, current_user.id)
    return await svc.detail_projet(project_id)


@router.patch("/{project_id}", response_model=ProjectOut)
async def update_project(
    project_id: UUID,
    data: ProjectUpdate,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> ProjectOut:
    svc = ProjectService(db, current_tenant.id, current_user.id)
    p = await svc.modifier_projet(project_id, data)
    return ProjectOut.model_validate(p)


@router.post("/{project_id}/lancer", response_model=ProjectOut)
async def launch_project(
    project_id: UUID,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> ProjectOut:
    svc = ProjectService(db, current_tenant.id, current_user.id)
    p = await svc.lancer_projet(project_id)
    return ProjectOut.model_validate(p)


# ═════════════════════════════════════════════════════════════════════════════
# PHASES
# ═════════════════════════════════════════════════════════════════════════════
@router.post("/{project_id}/phases", response_model=ProjectPhaseOut, status_code=201)
async def create_phase(
    project_id: UUID,
    data: ProjectPhaseCreate,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> ProjectPhaseOut:
    svc = ProjectService(db, current_tenant.id, current_user.id)
    ph = await svc.creer_phase(project_id, data)
    return ProjectPhaseOut.model_validate(ph)


@router.patch("/phases/{phase_id}", response_model=ProjectPhaseOut)
async def update_phase(
    phase_id: UUID,
    data: ProjectPhaseUpdate,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> ProjectPhaseOut:
    svc = ProjectService(db, current_tenant.id, current_user.id)
    ph = await svc.modifier_phase(phase_id, data)
    return ProjectPhaseOut.model_validate(ph)


# ═════════════════════════════════════════════════════════════════════════════
# TÂCHES
# ═════════════════════════════════════════════════════════════════════════════
@router.post("/{project_id}/tasks", response_model=ProjectTaskOut, status_code=201)
async def create_task(
    project_id: UUID,
    data: ProjectTaskCreate,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> ProjectTaskOut:
    svc = ProjectService(db, current_tenant.id, current_user.id)
    t = await svc.creer_tache(project_id, data)
    return ProjectTaskOut.model_validate(t)


@router.patch("/tasks/{task_id}", response_model=ProjectTaskOut)
async def update_task(
    task_id: UUID,
    data: ProjectTaskUpdate,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> ProjectTaskOut:
    svc = ProjectService(db, current_tenant.id, current_user.id)
    t = await svc.modifier_tache(task_id, data)
    return ProjectTaskOut.model_validate(t)


# ═════════════════════════════════════════════════════════════════════════════
# JALONS
# ═════════════════════════════════════════════════════════════════════════════
@router.post("/{project_id}/milestones", response_model=ProjectMilestoneOut, status_code=201)
async def create_milestone(
    project_id: UUID,
    data: ProjectMilestoneCreate,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> ProjectMilestoneOut:
    svc = ProjectService(db, current_tenant.id, current_user.id)
    m = await svc.creer_jalon(project_id, data)
    return ProjectMilestoneOut.model_validate(m)


@router.post("/milestones/{milestone_id}/atteindre", response_model=ProjectMilestoneOut)
async def mark_milestone_reached(
    milestone_id: UUID,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> ProjectMilestoneOut:
    svc = ProjectService(db, current_tenant.id, current_user.id)
    m = await svc.marquer_jalon_atteint(milestone_id)
    return ProjectMilestoneOut.model_validate(m)


# ═════════════════════════════════════════════════════════════════════════════
# COÛTS
# ═════════════════════════════════════════════════════════════════════════════
@router.post("/{project_id}/costs", response_model=ProjectCostOut, status_code=201)
async def add_cost(
    project_id: UUID,
    data: ProjectCostCreate,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> ProjectCostOut:
    svc = ProjectService(db, current_tenant.id, current_user.id)
    c = await svc.imputer_cout(project_id, data)
    return ProjectCostOut.model_validate(c)


@router.get("/{project_id}/costs", response_model=list[ProjectCostOut])
async def list_costs(
    project_id: UUID,
    current_tenant: CurrentTenant,
    _: RequireComptable,
    db: TenantDBSession,
) -> list[ProjectCostOut]:
    rows = (
        await db.execute(
            select(ProjectCost)
            .where(
                ProjectCost.project_id == project_id,
                ProjectCost.tenant_id == current_tenant.id,
            )
            .order_by(ProjectCost.date_cout.desc())
        )
    ).scalars().all()
    return [ProjectCostOut.model_validate(c) for c in rows]


# ═════════════════════════════════════════════════════════════════════════════
# SITUATIONS DE TRAVAUX
# ═════════════════════════════════════════════════════════════════════════════
@router.post("/situations", response_model=ProgressBillingOut, status_code=201)
async def create_progress_billing(
    data: ProgressBillingCreate,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> ProgressBillingOut:
    svc = ProjectService(db, current_tenant.id, current_user.id)
    b = await svc.creer_situation(data)
    return ProgressBillingOut.model_validate(b)


@router.get("/situations/{billing_id}", response_model=ProgressBillingDetailOut)
async def get_progress_billing(
    billing_id: UUID,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    db: TenantDBSession,
) -> ProgressBillingDetailOut:
    from sqlalchemy import select as _select
    from app.models.project import ProgressBillingLine

    b = await db.scalar(
        _select(ProgressBilling).where(
            ProgressBilling.id == billing_id,
            ProgressBilling.tenant_id == current_tenant.id,
        )
    )
    if b is None:
        from fastapi import HTTPException
        raise HTTPException(404, "Situation introuvable")

    lignes = (
        await db.execute(
            _select(ProgressBillingLine).where(ProgressBillingLine.billing_id == b.id)
            .order_by(ProgressBillingLine.ordre)
        )
    ).scalars().all()

    out = ProgressBillingDetailOut.model_validate(b)
    from app.schemas.project import ProgressBillingLineOut
    out.lignes = [ProgressBillingLineOut.model_validate(l) for l in lignes]
    return out


@router.post("/situations/{billing_id}/valider", response_model=ProgressBillingOut)
async def validate_progress_billing(
    billing_id: UUID,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
    par_client: bool = Query(False),
) -> ProgressBillingOut:
    svc = ProjectService(db, current_tenant.id, current_user.id)
    b = await svc.valider_situation(billing_id, par_client)
    return ProgressBillingOut.model_validate(b)


@router.post("/situations/{billing_id}/facturer")
async def invoice_progress_billing(
    billing_id: UUID,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> dict:
    svc = ProjectService(db, current_tenant.id, current_user.id)
    b, invoice_id = await svc.facturer_situation(billing_id)
    return {
        "billing_id": str(b.id),
        "invoice_id": str(invoice_id),
        "statut": b.statut,
    }


# ═════════════════════════════════════════════════════════════════════════════
# AVANCEMENT & RENTABILITÉ
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/{project_id}/avancement-a-facturer", response_model=AvancementSituationOut)
async def get_avancement(
    project_id: UUID,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
) -> AvancementSituationOut:
    svc = ProjectService(db, current_tenant.id, current_user.id)
    return await svc.calculer_avancement_a_facturer(project_id)


@router.get("/{project_id}/marge", response_model=ProjectMarginOut)
async def get_project_margin(
    project_id: UUID,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
) -> ProjectMarginOut:
    svc = ProjectService(db, current_tenant.id, current_user.id)
    return await svc.marge_projet(project_id)


@router.get("/portfolio/global", response_model=ProjectPortfolioOut)
async def get_portfolio(
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
    statut: str | None = Query(None),
) -> ProjectPortfolioOut:
    svc = ProjectService(db, current_tenant.id, current_user.id)
    return await svc.portefeuille(statut)
