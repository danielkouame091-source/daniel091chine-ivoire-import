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
    data: DataBreachNotifyPersonsIn,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    db: TenantDBSession,
) -> DataBreachOut:
    svc = PrivacyService(db, current_tenant.id, current_user.id)
    b = await svc.notifier_personnes(breach_id, data.contenu_notification)
    return DataBreachOut.model_validate(b)


@router.post("/breaches/{breach_id}/cloturer", response_model=DataBreachOut)
async def close_breach(
    breach_id: UUID,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    db: TenantDBSession,
) -> DataBreachOut:
    svc = PrivacyService(db, current_tenant.id, current_user.id)
    b = await svc.cloturer_breach(breach_id)
    return DataBreachOut.model_validate(b)


# ═════════════════════════════════════════════════════════════════════════════
# DPO
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/dpo", response_model=DPOOut | None)
async def get_dpo(
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
) -> DPOOut | None:
    svc = PrivacyService(db, current_tenant.id, current_user.id)
    dpo = await svc.get_dpo_actif()
    return DPOOut.model_validate(dpo) if dpo else None


@router.post("/dpo", response_model=DPOOut, status_code=201)
async def create_dpo(
    data: DPOCreate,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    _: RequireActiveSubscription,
    db: TenantDBSession,
) -> DPOOut:
    svc = PrivacyService(db, current_tenant.id, current_user.id)
    dpo = await svc.creer_dpo(data.model_dump())
    return DPOOut.model_validate(dpo)


# ═════════════════════════════════════════════════════════════════════════════
# DOCUMENTS LÉGAUX
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/legal-documents/{type_document}", response_model=LegalDocumentOut | None)
async def get_legal_document(
    type_document: str,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
    langue: str = Query("fr"),
) -> LegalDocumentOut | None:
    svc = PrivacyService(db, current_tenant.id, current_user.id)
    doc = await svc.get_document_legal_actif(type_document, langue)
    return LegalDocumentOut.model_validate(doc) if doc else None


@router.post("/legal-documents", response_model=LegalDocumentOut, status_code=201)
async def create_legal_document(
    data: LegalDocumentCreate,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    _: RequireActiveSubscription,
    db: TenantDBSession,
) -> LegalDocumentOut:
    svc = PrivacyService(db, current_tenant.id, current_user.id)
    doc = await svc.creer_document_legal(data)
    return LegalDocumentOut.model_validate(doc)


# ═════════════════════════════════════════════════════════════════════════════
# COOKIES
# ═════════════════════════════════════════════════════════════════════════════
@router.post("/cookies/consent", response_model=CookieConsentOut)
async def cookie_consent(
    data: CookieConsentIn,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
) -> CookieConsentOut:
    svc = PrivacyService(db, current_tenant.id, current_user.id)
    consent = await svc.enregistrer_consentement_cookies(
        data.session_id, data.model_dump(exclude={"session_id"})
    )
    return CookieConsentOut.model_validate(consent)


# ═════════════════════════════════════════════════════════════════════════════
# SOUS-TRAITANTS
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/processors", response_model=list[DataProcessorOut])
async def list_processors(
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    db: TenantDBSession,
    actif_only: bool = Query(True),
) -> list[DataProcessorOut]:
    svc = PrivacyService(db, current_tenant.id, current_user.id)
    rows = await svc.lister_sous_traitants(actif_only)
    return [DataProcessorOut.model_validate(p) for p in rows]


@router.post("/processors", response_model=DataProcessorOut, status_code=201)
async def create_processor(
    data: DataProcessorCreate,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    _: RequireActiveSubscription,
    db: TenantDBSession,
) -> DataProcessorOut:
    svc = PrivacyService(db, current_tenant.id, current_user.id)
    p = await svc.creer_sous_traitant(data)
    return DataProcessorOut.model_validate(p)


# ═════════════════════════════════════════════════════════════════════════════
# AIPD
# ═════════════════════════════════════════════════════════════════════════════
@router.post("/impact-assessments", response_model=ImpactAssessmentOut, status_code=201)
async def create_aipd(
    data: ImpactAssessmentCreate,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    _: RequireActiveSubscription,
    db: TenantDBSession,
) -> ImpactAssessmentOut:
    svc = PrivacyService(db, current_tenant.id, current_user.id)
    a = await svc.creer_aipd(data)
    return ImpactAssessmentOut.model_validate(a)


# ═════════════════════════════════════════════════════════════════════════════
# PORTABILITÉ
# ═════════════════════════════════════════════════════════════════════════════
@router.post("/portability/export", response_model=PortabilityExportOut)
async def export_portability(
    data: PortabilityExportIn,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    _: RequireActiveSubscription,
    db: TenantDBSession,
) -> PortabilityExportOut:
    """Export des données personnelles (JSON/CSV/XLSX) pour portabilité."""
    svc = PortabilityService(db, current_tenant.id, current_user.id)
    return await svc.exporter(data)
