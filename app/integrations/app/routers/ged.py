"""Endpoints GED — Dossiers, Documents, OCR, Signatures, Partages."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from sqlalchemy import select

from app.dependencies.auth import CurrentUser, RequireAdminTenant, RequireComptable
from app.dependencies.subscription import RequireActiveSubscription
from app.dependencies.tenant import CurrentTenant
from app.dependencies.tenant_db import TenantDBSession
from app.models.ged import (
    Document,
    DocumentAccessLog,
    DocumentFolder,
    DocumentOCRResult,
    DocumentShare,
    DocumentSignature,
    DocumentVersion,
)
from app.schemas.ged import (
    DocumentAccessLogOut,
    DocumentBulkActionIn,
    DocumentBulkActionResult,
    DocumentDetailOut,
    DocumentMetadataUpdate,
    DocumentOut,
    DocumentSearchResult,
    DocumentUploadResult,
    DocumentVersionOut,
    FolderCreate,
    FolderOut,
    FolderTreeNode,
    FolderUpdate,
    GEDDashboardOut,
    GEDStorageUsageOut,
    OCRManualCorrectionIn,
    OCRRequeueIn,
    OCRResultOut,
    ShareCreateIn,
    ShareCreatedOut,
    ShareOut,
    ShareRevokeIn,
    SignatureOut,
    SignatureRefuseIn,
    SignatureRequestIn,
    SignatureRequestOut,
    SignatureVerifyOTPIn,
)
from app.services.ged_service import GEDService
from app.services.ged_share_service import ShareService
from app.services.ged_signature_service import SignatureService

router = APIRouter()


# ═════════════════════════════════════════════════════════════════════════════
# DASHBOARD
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/dashboard", response_model=GEDDashboardOut)
async def ged_dashboard(
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
) -> GEDDashboardOut:
    svc = GEDService(db, current_tenant.id, current_user.id)
    data = await svc.dashboard()
    return GEDDashboardOut(**data)


# ═════════════════════════════════════════════════════════════════════════════
# DOSSIERS
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/folders", response_model=list[FolderOut])
async def list_folders(
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
    parent_id: UUID | None = Query(None),
) -> list[FolderOut]:
    svc = GEDService(db, current_tenant.id, current_user.id)
    rows = await svc.lister_dossiers(parent_id=parent_id, inclure_racine=True)
    return [FolderOut.model_validate(f) for f in rows]


@router.get("/folders/tree")
async def get_folder_tree(
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
) -> list[dict]:
    svc = GEDService(db, current_tenant.id, current_user.id)
    return await svc.arbre_dossiers()


@router.post("/folders", response_model=FolderOut, status_code=201)
async def create_folder(
    data: FolderCreate,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> FolderOut:
    svc = GEDService(db, current_tenant.id, current_user.id)
    f = await svc.creer_dossier(data)
    return FolderOut.model_validate(f)


@router.patch("/folders/{folder_id}", response_model=FolderOut)
async def update_folder(
    folder_id: UUID,
    data: FolderUpdate,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> FolderOut:
    svc = GEDService(db, current_tenant.id, current_user.id)
    f = await svc.modifier_dossier(folder_id, data)
    return FolderOut.model_validate(f)


@router.delete("/folders/{folder_id}", status_code=204)
async def delete_folder(
    folder_id: UUID,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> None:
    svc = GEDService(db, current_tenant.id, current_user.id)
    await svc.supprimer_dossier(folder_id)


@router.post("/folders/seed")
async def seed_folders(
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> dict:
    svc = GEDService(db, current_tenant.id, current_user.id)
    nb = await svc.seed_dossiers_systeme()
    return {"created": nb}


# ═════════════════════════════════════════════════════════════════════════════
# DOCUMENTS — UPLOAD
# ═════════════════════════════════════════════════════════════════════════════
@router.post("/documents/upload", response_model=DocumentUploadResult, status_code=201)
async def upload_document(
    current_tenant: CurrentTenant,
    current_user: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
    file: UploadFile = File(...),
    type_document: str = Form(...),
    folder_id: UUID | None = Form(None),
    nom: str | None = Form(None),
    description: str | None = Form(None),
    date_document: str | None = Form(None),
    date_expiration: str | None = Form(None),
    montant_ht: int | None = Form(None),
    montant_tva: int | None = Form(None),
    montant_ttc: int | None = Form(None),
    tiers_type: str | None = Form(None),
    tiers_id: UUID | None = Form(None),
    ecriture_id: UUID | None = Form(None),
    facture_id: UUID | None = Form(None),
    projet_id: UUID | None = Form(None),
    employe_id: UUID | None = Form(None),
) -> DocumentUploadResult:
    from datetime import date as _d

    svc = GEDService(db, current_tenant.id, current_user.id)
    doc = await svc.uploader(
        file=file,
        type_document=type_document,
        folder_id=folder_id,
        nom=nom,
        description=description,
        date_document=_d.fromisoformat(date_document) if date_document else None,
        date_expiration=_d.fromisoformat(date_expiration) if date_expiration else None,
        montant_ht=montant_ht,
        montant_tva=montant_tva,
        montant_ttc=montant_ttc,
        tiers_type=tiers_type,
        tiers_id=tiers_id,
        ecriture_id=ecriture_id,
        facture_id=facture_id,
        projet_id=projet_id,
        employe_id=employe_id,
    )
    return DocumentUploadResult(
        document=DocumentOut.model_validate(doc),
        version_numero=doc.version_actuelle,
        ocr_queued=doc.ocr_statut == "en_attente",
        message="Document uploadé avec succès",
    )


@router.post(
    "/documents/{document_id}/versions",
    response_model=DocumentVersionOut,
    status_code=201,
)
async def upload_new_version(
    document_id: UUID,
    current_tenant: CurrentTenant,
    current_user: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
    file: UploadFile = File(...),
    commentaire: str | None = Form(None),
) -> DocumentVersionOut:
    svc = GEDService(db, current_tenant.id, current_user.id)
    v = await svc.uploader_nouvelle_version(document_id, file, commentaire)
    return DocumentVersionOut.model_validate(v)


# ═════════════════════════════════════════════════════════════════════════════
# DOCUMENTS — LECTURE
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/documents", response_model=list[DocumentOut])
async def list_documents(
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
    q: str | None = Query(None),
    type_document: str | None = Query(None),
    folder_id: UUID | None = Query(None),
    tiers_type: str | None = Query(None),
    tiers_id: UUID | None = Query(None),
    statut: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[DocumentOut]:
    svc = GEDService(db, current_tenant.id, current_user.id)
    rows, _ = await svc.rechercher(
        q=q, type_document=type_document, folder_id=folder_id,
        tiers_type=tiers_type, tiers_id=tiers_id, statut=statut,
        limit=limit, offset=offset,
    )
    return [DocumentOut.model_validate(d) for d in rows]


@router.get("/documents/search", response_model=list[DocumentSearchResult])
async def search_documents(
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
    q: str = Query(..., min_length=2),
    limit: int = Query(20, ge=1, le=50),
) -> list[DocumentSearchResult]:
    svc = GEDService(db, current_tenant.id, current_user.id)
    rows, _ = await svc.rechercher(q=q, limit=limit)
    return [
        DocumentSearchResult(
            document=DocumentOut.model_validate(d),
            score=1.0,
            extrait=None,
        )
        for d in rows
    ]


@router.get("/documents/{document_id}", response_model=DocumentDetailOut)
async def get_document(
    document_id: UUID,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
) -> DocumentDetailOut:
    svc = GEDService(db, current_tenant.id, current_user.id)
    doc = await svc._get_document(document_id)

    # Incrémenter vues
    doc.nb_vues += 1
    await db.flush()

    # Compter versions / signatures / partages
    from sqlalchemy import func as _f

    nb_versions = int(await db.scalar(
        select(_f.count(DocumentVersion.id)).where(DocumentVersion.document_id == doc.id)
    ) or 0)
    nb_sigs = int(await db.scalar(
        select(_f.count(DocumentSignature.id)).where(DocumentSignature.document_id == doc.id)
    ) or 0)
    nb_shares = int(await db.scalar(
        select(_f.count(DocumentShare.id)).where(DocumentShare.document_id == doc.id, DocumentShare.actif.is_(True))
    ) or 0)

    # OCR extraction
    ocr_extraction = None
    ocr = await db.scalar(
        select(DocumentOCRResult).where(DocumentOCRResult.document_id == doc.id)
    )
    if ocr:
        ocr_extraction = {
            "num_facture": ocr.num_facture,
            "date_facture": ocr.date_facture.isoformat() if ocr.date_facture else None,
            "nom_fournisseur": ocr.nom_fournisseur,
            "montant_ht": ocr.montant_ht,
            "montant_tva": ocr.montant_tva,
            "montant_ttc": ocr.montant_ttc,
            "score": float(ocr.score_global) if ocr.score_global else None,
        }

    base = DocumentOut.model_validate(doc).model_dump()
    return DocumentDetailOut(
        **base,
        fichier_url=doc.fichier_url,
        ocr_texte=doc.ocr_texte,
        versions_count=nb_versions,
        signatures_count=nb_sigs,
        shares_count=nb_shares,
        ocr_extraction=ocr_extraction,
    )


@router.get("/documents/{document_id}/download")
async def download_document(
    document_id: UUID,
    current_tenant: CurrentTenant,
    current_user: RequireComptable,
    db: TenantDBSession,
) -> dict:
    svc = GEDService(db, current_tenant.id, current_user.id)
    url = await svc.obtenir_url_telechargement(document_id)
    return {"url": url, "expire_minutes": 15}


@router.get("/documents/{document_id}/versions", response_model=list[DocumentVersionOut])
async def list_versions(
    document_id: UUID,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
) -> list[DocumentVersionOut]:
    rows = (
        await db.execute(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document_id)
            .order_by(DocumentVersion.numero_version.desc())
        )
    ).scalars().all()
    return [DocumentVersionOut.model_validate(v) for v in rows]


# ═════════════════════════════════════════════════════════════════════════════
# DOCUMENTS — MISE À JOUR
# ═════════════════════════════════════════════════════════════════════════════
@router.patch("/documents/{document_id}", response_model=DocumentOut)
async def update_document(
    document_id: UUID,
    data: DocumentMetadataUpdate,
    current_tenant: CurrentTenant,
    current_user: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> DocumentOut:
    svc = GEDService(db, current_tenant.id, current_user.id)
    doc = await svc.modifier_metadonnees(document_id, data)
    return DocumentOut.model_validate(doc)


@router.delete("/documents/{document_id}", status_code=204)
async def delete_document(
    document_id: UUID,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    __: RequireActiveSubscription,
    db: TenantDBSession,
    definitif: bool = Query(False),
) -> None:
    svc = GEDService(db, current_tenant.id, current_user.id)
    await svc.supprimer(document_id, definitif=definitif)


@router.post("/documents/{document_id}/restore", response_model=DocumentOut)
async def restore_document(
    document_id: UUID,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> DocumentOut:
    svc = GEDService(db, current_tenant.id, current_user.id)
    doc = await svc.restaurer(document_id)
    return DocumentOut.model_validate(doc)


@router.post("/documents/bulk", response_model=DocumentBulkActionResult)
async def bulk_action(
    data: DocumentBulkActionIn,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> DocumentBulkActionResult:
    svc = GEDService(db, current_tenant.id, current_user.id)
    result = await svc.action_masse(data)
    return DocumentBulkActionResult(**result)


# ═════════════════════════════════════════════════════════════════════════════
# OCR
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/documents/{document_id}/ocr", response_model=OCRResultOut | None)
async def get_ocr_result(
    document_id: UUID,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
) -> OCRResultOut | None:
    ocr = await db.scalar(
        select(DocumentOCRResult).where(DocumentOCRResult.document_id == document_id)
    )
    if ocr is None:
        return None
    return OCRResultOut.model_validate(ocr)


@router.post("/documents/{document_id}/ocr/corriger")
async def correct_ocr(
    document_id: UUID,
    data: OCRManualCorrectionIn,
    current_tenant: CurrentTenant,
    current_user: RequireComptable,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> dict:
    from datetime import datetime, timezone
    ocr = await db.scalar(
        select(DocumentOCRResult).where(DocumentOCRResult.document_id == document_id)
    )
    if ocr is None:
        raise __import__("fastapi").HTTPException(404, "Résultat OCR introuvable")

    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(ocr, k, v)
    ocr.corrige_manuellement = True
    ocr.corrige_par_user_id = current_user.id
    ocr.corrige_at = datetime.now(timezone.utc)
    await db.flush()
    return {"ok": True, "document_id": str(document_id)}


@router.post("/documents/{document_id}/ocr/requeue")
async def requeue_ocr(
    document_id: UUID,
    data: OCRRequeueIn,
    current_tenant: CurrentTenant,
    current_user: RequireAdminTenant,
    __: RequireActiveSubscription,
    db: TenantDBSession,
) -> dict:
    """Relance l'OCR avec un moteur différent."""
    try:
        from arq import create_pool
        from app.workers.arq_settings import WorkerSettings
        redis = await create_pool(WorkerSettings.redis_settings)
        await redis.enqueue_job(
            "executer_ocr_document",
            str(document_id), str(current_tenant.id),
            data.moteur, data.langues,
        )
        await redis.aclose()
    except Exception as exc:
        raise __import__("fastapi").HTTPException(500, f"Échec queue OCR : {exc}")
    return {"
