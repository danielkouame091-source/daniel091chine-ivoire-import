"""Endpoints Audit & Contrôle interne."""
from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Query

from app.dependencies.auth import CurrentUser, RequireAdminTenant, RequireComptable
from app.dependencies.founder import FounderUser
from app.dependencies.subscription import RequireActiveSubscription
from app.dependencies.tenant import CurrentTenant
from app.dependencies.tenant_db import TenantDBSession
from app.schemas.audit_internal import (
    AuditDashboardOut,
    AuditFindingOut,
    AuditRuleCreate,
    AuditRuleOut,
    AuditRuleUpdate,
    AuditRunOut,
    AuditRunRequest,
    AuditTrailFilter,
    AuditTrailOut,
    AuditTrailVerifyOut,
    BenfordAnalysisOut,
    BenfordAnalysisRequest,
    CircularTransactionOut,
    ComplianceReportOut,
    ComplianceReportRequest,
    FindingAssignRequest,
    FindingEscalateRequest,
    FindingResolveRequest,
    JustBelowThresholdOut,
)
from app.services.audit_internal_service import AuditInternalService

router = APIRouter()


# ═════════════════════════════════════════════════════════════════════════════
# RÈGLES
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/rules", response_model=list[AuditRuleOut])
async def list_rules(
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    db: TenantDBSession,
    active_only: bool = True,
    categorie: str | None = Query(None),
) -> list[AuditRuleOut]:
    svc = AuditInternalService(db, current_tenant.id, current_user.id)
    rules = await svc.lister_regles(active_only=active_only, categorie=categorie)
    return [AuditRuleOut.model_validate(r) for r in rules]


@router.post("/rules", response_model=AuditRuleOut, status_code=201)
async def create_rule(
    data: AuditRuleCreate,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> AuditRuleOut:
    svc = AuditInternalService(db, current_tenant.id, current_user.id)
    rule = await svc.creer_regle(data)
    return AuditRuleOut.model_validate(rule)


@router.patch("/rules/{rule_id}", response_model=AuditRuleOut)
async def update_rule(
    rule_id: UUID,
    data: AuditRuleUpdate,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> AuditRuleOut:
    svc = AuditInternalService(db, current_tenant.id, current_user.id)
    rule = await svc.modifier_regle(rule_id, data)
    return AuditRuleOut.model_validate(rule)


@router.post("/rules/seed")
async def seed_rules(
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> dict:
    """Initialise les règles par défaut (idempotent)."""
    svc = AuditInternalService(db, current_tenant.id, current_user.id)
    created = await svc.seed_regles_defaut()
    return {"rules_created": created}


# ═════════════════════════════════════════════════════════════════════════════
# EXÉCUTION
# ═════════════════════════════════════════════════════════════════════════════
@router.post("/run", response_model=list[AuditRunOut], status_code=201)
async def run_audit(
    data: AuditRunRequest,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> list[AuditRunOut]:
    """Exécute une ou toutes les règles d'audit."""
    svc = AuditInternalService(db, current_tenant.id, current_user.id)
    runs = await svc.executer_regles(data)
    return [AuditRunOut.model_validate(r) for r in runs]


# ═════════════════════════════════════════════════════════════════════════════
# FINDINGS
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/findings", response_model=list[AuditFindingOut])
async def list_findings(
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    db: TenantDBSession,
    statut: str | None = Query(None),
    severite: str | None = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> list[AuditFindingOut]:
    svc = AuditInternalService(db, current_tenant.id, current_user.id)
    return await svc.list_findings(
        statut=statut, severite=severite, limit=limit, offset=offset,
    )


@router.post("/findings/{finding_id}/resoudre", response_model=AuditFindingOut)
async def resolve_finding(
    finding_id: UUID,
    data: FindingResolveRequest,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> AuditFindingOut:
    svc = AuditInternalService(db, current_tenant.id, current_user.id)
    return await svc.resoudre_finding(finding_id, data)


@router.post("/findings/{finding_id}/escalader", response_model=AuditFindingOut)
async def escalate_finding(
    finding_id: UUID,
    data: FindingEscalateRequest,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> AuditFindingOut:
    svc = AuditInternalService(db, current_tenant.id, current_user.id)
    return await svc.escalader_finding(finding_id, data.motif)


@router.post("/findings/{finding_id}/assigner", response_model=AuditFindingOut)
async def assign_finding(
    finding_id: UUID,
    data: FindingAssignRequest,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> AuditFindingOut:
    svc = AuditInternalService(db, current_tenant.id, current_user.id)
    return await svc.assigner_finding(finding_id, data.user_id)


# ═════════════════════════════════════════════════════════════════════════════
# AUDIT TRAIL
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/trail", response_model=list[AuditTrailOut])
async def list_trail(
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    db: TenantDBSession,
    user_id: UUID | None = Query(None),
    action: str | None = Query(None),
    ressource_type: str | None = Query(None),
    date_debut: date | None = Query(None),
    date_fin: date | None = Query(None),
    succes: bool | None = Query(None),
    limit: int = Query(200, ge=1, le=2000),
    offset: int = Query(0, ge=0),
) -> list[AuditTrailOut]:
    svc = AuditInternalService(db, current_tenant.id, current_user.id)
    filters = AuditTrailFilter(
        user_id=user_id, action=action, ressource_type=ressource_type,
        date_debut=date_debut, date_fin=date_fin, succes=succes,
    )
    return await svc.list_audit_trail(filters, limit=limit, offset=offset)


@router.get("/trail/verify", response_model=AuditTrailVerifyOut)
async def verify_trail(
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    db: TenantDBSession,
) -> AuditTrailVerifyOut:
    """Vérifie l'intégrité du hash-chain de la piste d'audit."""
    svc = AuditInternalService(db, current_tenant.id, current_user.id)
    return await svc.verify_audit_chain(current_tenant.id)


# ═════════════════════════════════════════════════════════════════════════════
# BENFORD
# ═════════════════════════════════════════════════════════════════════════════
@router.post("/benford", response_model=BenfordAnalysisOut, status_code=201)
async def analyse_benford(
    data: BenfordAnalysisRequest,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireComptable,
    db: TenantDBSession,
) -> BenfordAnalysisOut:
    svc = AuditInternalService(db, current_tenant.id, current_user.id)
    return await svc.analyser_benford(data)


# ═════════════════════════════════════════════════════════════════════════════
# DÉTECTIONS SPÉCIALES
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/circulaires", response_model=list[CircularTransactionOut])
async def detect_circular(
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
    date_debut: date = Query(...),
    date_fin: date = Query(...),
    fenetre_jours: int = Query(7, ge=1, le=60),
) -> list[CircularTransactionOut]:
    svc = AuditInternalService(db, current_tenant.id, current_user.id)
    return await svc.detecter_circulaires(date_debut, date_fin, fenetre_jours)


@router.get("/seuil-suspect", response_model=JustBelowThresholdOut)
async def detect_just_below_threshold(
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
    date_debut: date = Query(...),
    date_fin: date = Query(...),
    seuil: int = Query(5_000_000, ge=100_000),
    tolerance: int = Query(1000, ge=0),
) -> JustBelowThresholdOut:
    svc = AuditInternalService(db, current_tenant.id, current_user.id)
    return await svc.detecter_montants_sous_seuil(date_debut, date_fin, seuil, tolerance)


# ═════════════════════════════════════════════════════════════════════════════
# RAPPORT DE CONFORMITÉ
# ═════════════════════════════════════════════════════════════════════════════
@router.post("/compliance/report", response_model=ComplianceReportOut, status_code=201)
async def generate_compliance_report(
    data: ComplianceReportRequest,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    _: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> ComplianceReportOut:
    svc = AuditInternalService(db, current_tenant.id, current_user.id)
    return await svc.generer_rapport_conformite(data)


# ═════════════════════════════════════════════════════════════════════════════
# DASHBOARD
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/dashboard", response_model=AuditDashboardOut)
async def get_dashboard(
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
) -> AuditDashboardOut:
    svc = AuditInternalService(db, current_tenant.id, current_user.id)
    return await svc.dashboard()
