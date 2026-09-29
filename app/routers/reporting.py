"""Endpoints Reporting & Déclarations Fiscales."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.dependencies.auth import CurrentUser, RequireComptable
from app.dependencies.subscription import RequireActiveSubscription
from app.dependencies.tenant import CurrentTenant
from app.dependencies.tenant_db import TenantDBSession
from app.schemas.reporting import (
    BilanOut,
    CnpsDeclarationOut,
    CompteResultatOut,
    DgiDeclarationOut,
    EmployeeCreate,
    EmployeeOut,
    FinancialStatementOut,
    PayslipCalculRequest,
    PayslipOut,
)
from app.services.dgi_service import DgiService
from app.services.financial_statement_service import FinancialStatementService
from app.services.payroll_service import PayrollService

router = APIRouter()


# ═════════════════════════════════════════════════════════════════════════════
# ÉTATS FINANCIERS SYSCOHADA
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/bilan/{exercice_id}", response_model=BilanOut)
async def get_bilan(
    exercice_id: UUID,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
) -> BilanOut:
    svc = FinancialStatementService(db, current_tenant.id, current_user.id)
    return BilanOut(**await svc.generer_bilan(exercice_id))


@router.get("/compte-resultat/{exercice_id}", response_model=CompteResultatOut)
async def get_compte_resultat(
    exercice_id: UUID,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
) -> CompteResultatOut:
    svc = FinancialStatementService(db, current_tenant.id, current_user.id)
    return CompteResultatOut(**await svc.generer_compte_resultat(exercice_id))


@router.post("/etats-financiers/{exercice_id}/generer", response_model=list[FinancialStatementOut])
async def generer_etats_financiers(
    exercice_id: UUID,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> list[FinancialStatementOut]:
    svc = FinancialStatementService(db, current_tenant.id, current_user.id)
    results = await svc.generer_et_sauvegarder(exercice_id)
    return [FinancialStatementOut.model_validate(fs) for fs in results]


# ═════════════════════════════════════════════════════════════════════════════
# SALARIÉS
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/employees", response_model=list[EmployeeOut])
async def list_employees(
    current_tenant: CurrentTenant,
    _: RequireComptable,
    db: TenantDBSession,
    actif_only: bool = True,
) -> list[EmployeeOut]:
    from sqlalchemy import select
    from app.models.payroll import Employee
    stmt = select(Employee).where(Employee.tenant_id == current_tenant.id)
    if actif_only:
        stmt = stmt.where(Employee.actif.is_(True))
    rows = (await db.execute(stmt)).scalars().all()
    return [EmployeeOut.model_validate(e) for e in rows]


@router.post("/employees", response_model=EmployeeOut, status_code=201)
async def create_employee(
    data: EmployeeCreate,
    current_tenant: CurrentTenant,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> EmployeeOut:
    from app.models.payroll import Employee
    emp = Employee(tenant_id=current_tenant.id, **data.model_dump())
    db.add(emp)
    await db.flush()
    return EmployeeOut.model_validate(emp)


# ═════════════════════════════════════════════════════════════════════════════
# PAIE
# ═════════════════════════════════════════════════════════════════════════════
@router.post("/payroll/calculer", response_model=PayslipOut, status_code=201)
async def calculer_bulletin(
    data: PayslipCalculRequest,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> PayslipOut:
    svc = PayrollService(db, current_tenant.id, current_user.id)
    payslip = await svc.calculer_bulletin(data.employee_id, data.periode)
    return PayslipOut.model_validate(payslip)


@router.post("/payroll/{payslip_id}/comptabiliser")
async def comptabiliser_bulletin(
    payslip_id: UUID,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> dict:
    svc = PayrollService(db, current_tenant.id, current_user.id)
    ecriture_id = await svc.comptabiliser_bulletin(payslip_id)
    return {"payslip_id": str(payslip_id), "ecriture_id": str(ecriture_id)}


# ═════════════════════════════════════════════════════════════════════════════
# DÉCLARATIONS CNPS
# ═════════════════════════════════════════════════════════════════════════════
@router.post("/cnps/declaration", response_model=CnpsDeclarationOut, status_code=201)
async def generer_declaration_cnps(
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
    annee: int = Query(..., ge=2020, le=2100),
    mois: int = Query(..., ge=1, le=12),
    trimestrielle: bool = False,
) -> CnpsDeclarationOut:
    svc = PayrollService(db, current_tenant.id, current_user.id)
    decl = await svc.generer_declaration_cnps(annee, mois, trimestrielle)
    return CnpsDeclarationOut.model_validate(decl)


# ═════════════════════════════════════════════════════════════════════════════
# DÉCLARATIONS DGI
# ═════════════════════════════════════════════════════════════════════════════
@router.post("/dgi/tva", response_model=DgiDeclarationOut, status_code=201)
async def generer_declaration_tva(
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
    annee: int = Query(..., ge=2020, le=2100),
    periode: int = Query(..., ge=1, le=12),
    trimestrielle: bool = False,
) -> DgiDeclarationOut:
    svc = DgiService(db, current_tenant.id, current_user.id)
    decl = await svc.generer_declaration_tva(annee, periode, trimestrielle)
    return DgiDeclarationOut.model_validate(decl)


@router.post("/dgi/its", response_model=DgiDeclarationOut, status_code=201)
async def generer_declaration_its(
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
    annee: int = Query(..., ge=2020, le=2100),
    trimestre: int = Query(..., ge=1, le=4),
) -> DgiDeclarationOut:
    svc = DgiService(db, current_tenant.id, current_user.id)
    decl = await svc.generer_declaration_its(annee, trimestre)
    return DgiDeclarationOut.model_validate(decl)


@router.post("/dgi/is", response_model=DgiDeclarationOut, status_code=201)
async def generer_declaration_is(
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
    exercice_id: UUID,
    chiffre_affaires_ttc: int | None = None,
) -> DgiDeclarationOut:
    svc = DgiService(db, current_tenant.id, current_user.id)
    decl = await svc.generer_declaration_is(exercice_id, chiffre_affaires_ttc)
    return DgiDeclarationOut.model_validate(decl)
