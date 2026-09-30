"""Endpoints Conformité RGPD / Protection des données."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query

from app.dependencies.auth import CurrentUser, RequireAdminTenant
from app.dependencies.subscription import RequireActiveSubscription
from app.dependencies.tenant import CurrentTenant
from app.dependencies.tenant_db import TenantDBSession
from app.schemas.privacy import (
    ComplianceScoreBreakdown,
    ConsentCreate,
    ConsentOut,
    ConsentRetraitIn,
    CookieConsentIn,
    CookieConsentOut,
    DPOCreate,
    DPOOut,
    DataBreachCreate,
    DataBreachNotifyAuthorityIn,
    DataBreachNotifyPersonsIn,
    DataBreachOut,
    DataBreachUpdate,
    DataProcessorCreate,
    DataProcessorOut,
    DataSubjectRequestCreate,
    DataSubjectRequestDetailOut,
    DataSubjectRequestOut,
    DSRProlongationIn,
    DSRReponseIn,
    DSRVerifyIdentityIn,
    ImpactAssessmentCreate,
    ImpactAssessmentOut,
    LegalDocumentCreate,
    LegalDocumentOut,
    PortabilityExportIn,
    PortabilityExportOut,
    PrivacyDashboardOut,
    ProcessingRecordCreate,
    ProcessingRecordOut,
    ProcessingRecordUpdate,
    RequestActionLogOut,
)
from app.services.privacy_portability_service import PortabilityService
from app.services.privacy_service import PrivacyService

router = APIRouter()


# ═════════════════════════════════════════════════════════════════════════════
# DASHBOARD
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/dashboard", response_model=PrivacyDashboardOut)
async def privacy_dashboard(
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    db: TenantDBSession,
) -> PrivacyDashboardOut:
    svc = PrivacyService(db, current_tenant.id, current_user.id)
    data = await svc.dashboard()
    return PrivacyDashboardOut(**data)


@router.get("/score", response_model=ComplianceScoreBreakdown)
async def compliance_score(
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    db: TenantDBSession,
) -> ComplianceScoreBreakdown:
    svc = PrivacyService(db, current_tenant.id, current_user.id)
    data = await svc.score_conformite_detaille()
    return ComplianceScoreBreakdown(
        registre_traitements_pct=data["registre_traitements_pct"],
        droits_personnes_pct=data["droits_personnes_pct"],
        securite_pct=data["securite_pct"],
        violations_pct=data["violations_pct"],
        consentements_pct=data["consentements_pct"],
        documentation_pct=data["documentation_pct"],
        score_global_pct=data["score_global_pct"],
        recommandations=data["recommandations"],
    )


# ═════════════════════════════════════════════════════════════════════════════
# REGISTRE DES TRAITEMENTS
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/processing-records", response_model=list[ProcessingRecordOut])
async def list_processing_records(
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    db: TenantDBSession,
    actif_only: bool = Query(True),
    finalite: str | None = Query(None),
) -> list[ProcessingRecordOut]:
    svc = PrivacyService(db, current_tenant.id, current_user.id)
    rows = await svc.lister_traitements(actif_only, finalite)
    return [ProcessingRecordOut.model_validate(r) for r in rows]


@router.post("/processing-records", response_model=ProcessingRecordOut, status_code=201)
async def create_processing_record(
    data: ProcessingRecordCreate,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    _: RequireActiveSubscription,
    db: TenantDBSession,
) -> ProcessingRecordOut:
    svc = PrivacyService(db, current_tenant.id, current_user.id)
    r = await svc.creer_traitement(data)
    return ProcessingRecordOut.model_validate(r)


@router.patch("/processing-records/{record_id}", response_model=ProcessingRecordOut)
async def update_processing_record(
    record_id: UUID,
    data: ProcessingRecordUpdate,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    _: RequireActiveSubscription,
    db: TenantDBSession,
) -> ProcessingRecordOut:
    svc = PrivacyService(db, current_tenant.id, current_user.id)
    r = await svc.modifier_traitement(record_id, data)
    return ProcessingRecordOut.model_validate(r)


# ═════════════════════════════════════════════════════════════════════════════
# DEMANDES DE DROIT (DSR)
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/requests", response_model=list[DataSubjectRequestOut])
async def list_data_requests(
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    db: TenantDBSession,
    statut: str | None = Query(None),
    type_droit: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[DataSubjectRequestOut]:
    svc = PrivacyService(db, current_tenant.id, current_user.id)
    rows = await svc.lister_demandes(statut, type_droit, limit, offset)
    return [DataSubjectRequestOut.model_validate(r) for r in rows]


@router.post("/requests", response_model=DataSubjectRequestOut, status_code=201)
async def create_data_request(
    data: DataSubjectRequestCreate,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
) -> DataSubjectRequestOut:
    svc = PrivacyService(db, current_tenant.id, current_user.id)
    r = await svc.creer_demande_droit(data)
    return DataSubjectRequestOut.model_validate(r)


@router.post("/requests/{request_id}/verifier-identite", response_model=DataSubjectRequestOut)
async def verify_identity(
    request_id: UUID,
    data: DSRVerifyIdentityIn,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    db: TenantDBSession,
) -> DataSubjectRequestOut:
    svc = PrivacyService(db, current_tenant.id, current_user.id)
    r = await svc.verifier_identite(request_id, data.methode_verification, data.commentaire)
    return DataSubjectRequestOut.model_validate(r)


@router.post("/requests/{request_id}/prolonger", response_model=DataSubjectRequestOut)
async def extend_deadline(
    request_id: UUID,
    data: DSRProlongationIn,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    db: TenantDBSession,
) -> DataSubjectRequestOut:
    svc = PrivacyService(db, current_tenant.id, current_user.id)
    r = await svc.prolonger_delai(request_id, data.motif)
    return DataSubjectRequestOut.model_validate(r)


@router.post("/requests/{request_id}/repondre", response_model=DataSubjectRequestOut)
async def respond_to_request(
    request_id: UUID,
    data: DSRReponseIn,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    _: RequireActiveSubscription,
    db: TenantDBSession,
) -> DataSubjectRequestOut:
    svc = PrivacyService(db, current_tenant.id, current_user.id)
    r = await svc.repondre_demande(
        request_id, data.reponse, data.statut, data.document_reponse_url,
    )
    return DataSubjectRequestOut.model_validate(r)


# ═════════════════════════════════════════════════════════════════════════════
# VIOLATIONS DE DONNÉES
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/breaches", response_model=list[DataBreachOut])
async def list_breaches(
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    db: TenantDBSession,
    statut: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
) -> list[DataBreachOut]:
    svc = PrivacyService(db, current_tenant.id, current_user.id)
    rows = await svc.lister_breaches(statut, limit)
    return [DataBreachOut.model_validate(b) for b in rows]


@router.post("/breaches", response_model=DataBreachOut, status_code=201)
async def declare_breach(
    data: DataBreachCreate,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    db: TenantDBSession,
) -> DataBreachOut:
    svc = PrivacyService(db, current_tenant.id, current_user.id)
    b = await svc.declarer_violation(data)
    return DataBreachOut.model_validate(b)


@router.post("/breaches/{breach_id}/notifier-autorite", response_model=DataBreachOut)
async def notify_authority(
    breach_id: UUID,
    data: DataBreachNotifyAuthorityIn,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    db: TenantDBSession,
) -> DataBreachOut:
    svc = PrivacyService(db, current_tenant.id, current_user.id)
    b = await svc.notifier_autorite(
        breach_id, data.autorite, data.contenu_notification, data.reference_autorite,
    )
    return DataBreachOut.model_validate(b)


@router.post("/breaches/{breach_id}/notifier-personnes", response_model=DataBreachOut)
async def notify_persons(
    breach_id: UUID,
    data: DataBre
