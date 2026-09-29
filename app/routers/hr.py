"""Endpoints RH — Départements, Contrats, Congés, Évaluations, Formations."""
from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.dependencies.auth import CurrentUser, RequireAdminTenant, RequireComptable
from app.dependencies.subscription import RequireActiveSubscription
from app.dependencies.tenant import CurrentTenant
from app.dependencies.tenant_db import TenantDBSession
from app.models.hr import (
    Department,
    EmployeeDocument,
    EmploymentContract,
    LeaveRequest,
    PerformanceReview,
    Training,
    TrainingParticipant,
)
from app.schemas.hr import (
    AbsenceCreate,
    AbsenceOut,
    ContractCreate,
    ContractOut,
    ContractRuptureIn,
    ContractUpdate,
    DepartmentCreate,
    DepartmentOut,
    DepartmentUpdate,
    EmployeeDocumentCreate,
    EmployeeDocumentOut,
    HRDashboardOut,
    LeaveApprovalIn,
    LeaveBalanceOut,
    LeaveCancelIn,
    LeaveRefuseIn,
    LeaveRequestCreate,
    LeaveRequestOut,
    LeaveSummaryOut,
    OffboardingOut,
    ReviewCreate,
    ReviewFinalizeIn,
    ReviewOut,
    ReviewUpdate,
    SanctionCreate,
    SanctionOut,
    TimeEntryCreate,
    TimeEntryOut,
    TrainingCreate,
    TrainingOut,
    TrainingParticipantCreate,
    TrainingParticipantOut,
    TrainingParticipantUpdate,
    TurnoverAnalysisOut,
)
from app.services.hr_service import HRService

router = APIRouter()


# ═════════════════════════════════════════════════════════════════════════════
# DÉPARTEMENTS
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/departments", response_model=list[DepartmentOut])
async def list_departments(
    current_tenant: CurrentTenant,
    _: RequireComptable,
    db: TenantDBSession,
    actif_only: bool = True,
) -> list[DepartmentOut]:
    svc = HRService(db, current_tenant.id, current_tenant.id)
    rows = await svc.lister_departements(actif_only)
    return [DepartmentOut.model_validate(d) for d in rows]


@router.post("/departments", response_model=DepartmentOut, status_code=201)
async def create_department(
    data: DepartmentCreate,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> DepartmentOut:
    svc = HRService(db, current_tenant.id, current_user.id)
    dept = await svc.creer_departement(data)
    return DepartmentOut.model_validate(dept)


@router.post("/departments/seed")
async def seed_departments(
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    _: RequireComptable,
    db: TenantDBSession,
) -> dict:
    svc = HRService(db, current_tenant.id, current_user.id)
    nb = await svc.seed_departements_defaut()
    return {"created": nb}


# ═════════════════════════════════════════════════════════════════════════════
# CONTRATS
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/contracts", response_model=list[ContractOut])
async def list_contracts(
    current_tenant: CurrentTenant,
    _: RequireComptable,
    db: TenantDBSession,
    employee_id: UUID | None = Query(None),
    statut: str | None = Query(None),
    limit: int = 200,
) -> list[ContractOut]:
    stmt = select(EmploymentContract).where(EmploymentContract.tenant_id == current_tenant.id)
    if employee_id:
        stmt = stmt.where(EmploymentContract.employee_id == employee_id)
    if statut:
        stmt = stmt.where(EmploymentContract.statut == statut)
    stmt = stmt.order_by(EmploymentContract.date_debut.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [ContractOut.model_validate(c) for c in rows]


@router.post("/contracts", response_model=ContractOut, status_code=201)
async def create_contract(
    data: ContractCreate,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> ContractOut:
    svc = HRService(db, current_tenant.id, current_user.id)
    c = await svc.creer_contrat(data)
    return ContractOut.model_validate(c)


@router.patch("/contracts/{contract_id}", response_model=ContractOut)
async def update_contract(
    contract_id: UUID,
    data: ContractUpdate,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> ContractOut:
    svc = HRService(db, current_tenant.id, current_user.id)
    c = await svc.modifier_contrat(contract_id, data)
    return ContractOut.model_validate(c)


@router.post("/contracts/{contract_id}/rompre", response_model=OffboardingOut)
async def terminate_contract(
    contract_id: UUID,
    data: ContractRuptureIn,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> OffboardingOut:
    svc = HRService(db, current_tenant.id, current_user.id)
    o = await svc.rompre_contrat(contract_id, data)
    return OffboardingOut.model_validate(o)


# ═════════════════════════════════════════════════════════════════════════════
# CONGÉS
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/leave-balance/{employee_id}", response_model=LeaveBalanceOut)
async def get_leave_balance(
    employee_id: UUID,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    annee: int | None = Query(None),
    db: TenantDBSession = None,
) -> LeaveBalanceOut:
    svc = HRService(db, current_tenant.id, current_user.id)
    return await svc.get_solde_conges(employee_id, annee)


@router.get("/leave-requests", response_model=list[LeaveRequestOut])
async def list_leave_requests(
    current_tenant: CurrentTenant,
    _: RequireComptable,
    db: TenantDBSession,
    employee_id: UUID | None = Query(None),
    statut: str | None = Query(None),
    limit: int = 200,
) -> list[LeaveRequestOut]:
    svc = HRService(db, current_tenant.id, current_tenant.id)
    rows = await svc.lister_conges(employee_id, statut, limit)
    return [LeaveRequestOut.model_validate(r) for r in rows]


@router.post("/leave-requests", response_model=LeaveRequestOut, status_code=201)
async def create_leave_request(
    data: LeaveRequestCreate,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
) -> LeaveRequestOut:
    svc = HRService(db, current_tenant.id, current_user.id)
    r = await svc.creer_demande_conge(data)
    return LeaveRequestOut.model_validate(r)


@router.post("/leave-requests/{leave_id}/valider-manager", response_model=LeaveRequestOut)
async def approve_leave_manager(
    leave_id: UUID,
    data: LeaveApprovalIn,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
) -> LeaveRequestOut:
    svc = HRService(db, current_tenant.id, current_user.id)
    r = await svc.valider_conge_manager(leave_id, data)
    return LeaveRequestOut.model_validate(r)


@router.post("/leave-requests/{leave_id}/valider-rh", response_model=LeaveRequestOut)
async def approve_leave_rh(
    leave_id: UUID,
    data: LeaveApprovalIn,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    db: TenantDBSession,
) -> LeaveRequestOut:
    svc = HRService(db, current_tenant.id, current_user.id)
    r = await svc.valider_conge_rh(leave_id, data)
    return LeaveRequestOut.model_validate(r)


@router.post("/leave-requests/{leave_id}/annuler", response_model=LeaveRequestOut)
async def cancel_leave(
    leave_id: UUID,
    data: LeaveCancelIn,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
) -> LeaveRequestOut:
    svc = HRService(db, current_tenant.id, current_user.id)
    r = await svc.annuler_conge(leave_id, data)
    return LeaveRequestOut.model_validate(r)


# ═════════════════════════════════════════════════════════════════════════════
# ABSENCES
# ═════════════════════════════════════════════════════════════════════════════
@router.post("/absences", response_model=AbsenceOut, status_code=201)
async def create_absence(
    data: AbsenceCreate,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> AbsenceOut:
    svc = HRService(db, current_tenant.id, current_user.id)
    a = await svc.creer_absence(data)
    return AbsenceOut.model_validate(a)


# ═════════════════════════════════════════════════════════════════════════════
# ÉVALUATIONS
# ═════════════════════════════════════════════════════════════════════════════
@router.post("/reviews", response_model=ReviewOut, status_code=201)
async def create_review(
    data: ReviewCreate,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> ReviewOut:
    svc = HRService(db, current_tenant.id, current_user.id)
    r = await svc.creer_evaluation(data)
    return ReviewOut.model_validate(r)


@router.post("/reviews/{review_id}/finaliser", response_model=ReviewOut)
async def finalize_review(
    review_id: UUID,
    data: ReviewFinalizeIn,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    _: RequireComptable,
    db: TenantDBSession,
) -> ReviewOut:
    svc = HRService(db, current_tenant.id, current_user.id)
    r = await svc.finaliser_evaluation(review_id, data)
    return ReviewOut.model_validate(r)


# ═════════════════════════════════════════════════════════════════════════════
# FORMATIONS
# ═════════════════════════════════════════════════════════════════════════════
@router.post("/trainings", response_model=TrainingOut, status_code=201)
async def create_training(
    data: TrainingCreate,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> TrainingOut:
    svc = HRService(db, current_tenant.id, current_user.id)
    t = await svc.creer_formation(data)
    return TrainingOut.model_validate(t)


@router.post("/trainings/{training_id}/participants", response_model=TrainingParticipantOut, status_code=201)
async def enroll_participant(
    training_id: UUID,
    data: TrainingParticipantCreate,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> TrainingParticipantOut:
    svc = HRService(db, current_tenant.id, current_user.id)
    p = await svc.inscrire_participant(training_id, data)
    return TrainingParticipantOut.model_validate(p)


@router.patch("/training-participants/{participant_id}", response_model=TrainingParticipantOut)
async def update_participant(
    participant_id: UUID,
    data: TrainingParticipantUpdate,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> TrainingParticipantOut:
    svc = HRService(db, current_tenant.id, current_user.id)
    p = await svc.update_participant(participant_id, data)
    return TrainingParticipantOut.model_validate(p)


# ═════════════════════════════════════════════════════════════════════════════
# DOCUMENTS
# ═════════════════════════════════════════════════════════════════════════════
@router.post("/documents", response_model=EmployeeDocumentOut, status_code=201)
async def add_document(
    data: EmployeeDocumentCreate,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> EmployeeDocumentOut:
    svc = HRService(db, current_tenant.id, current_user.id)
    doc = await svc.ajouter_document(data)
    return EmployeeDocumentOut.model_validate(doc)


@router.get("/documents/{employee_id}", response_model=list[EmployeeDocumentOut])
async def list_documents(
    employee_id: UUID,
    current_tenant: CurrentTenant,
    _: RequireComptable,
    db: TenantDBSession,
    type_document: str | None = Query(None),
) -> list[EmployeeDocumentOut]:
    svc = HRService(db, current_tenant.id, current_tenant.id)
    docs = await svc.lister_documents(employee_id, type_document)
    return [EmployeeDocumentOut.model_validate(d) for d in docs]


# ═════════════════════════════════════════════════════════════════════════════
# SANCTIONS
# ═════════════════════════════════════════════════════════════════════════════
@router.post("/sanctions", response_model=SanctionOut, status_code=201)
async def create_sanction(
    data: SanctionCreate,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> SanctionOut:
    svc = HRService(db, current_tenant.id, current_user.id)
    s = await svc.creer_sanction(data)
    return SanctionOut.model_validate(s)


# ═════════════════════════════════════════════════════════════════════════════
# POINTAGE
# ═════════════════════════════════════════════════════════════════════════════
@router.post("/time-entries", response_model=TimeEntryOut, status_code=201)
async def create_time_entry(
    data: TimeEntryCreate,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
) -> TimeEntryOut:
    svc = HRService(db, current_tenant.id, current_user.id)
    e = await svc.saisir_temps(data)
    return TimeEntryOut.model_validate(e)


# ═════════════════════════════════════════════════════════════════════════════
# ANALYTICS
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/dashboard", response_model=HRDashboardOut)
async def hr_dashboard(
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    db: TenantDBSession,
) -> HRDashboardOut:
    svc = HRService(db, current_tenant.id, current_user.id)
    return await svc.dashboard()


@router.get("/analytics/leave-summary", response_model=LeaveSummaryOut)
async def leave_summary(
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    db: TenantDBSession,
    annee: int | None = Query(None),
) -> LeaveSummaryOut:
    svc = HRService(db, current_tenant.id, current_user.id)
    return await svc.resume_conges(annee)
