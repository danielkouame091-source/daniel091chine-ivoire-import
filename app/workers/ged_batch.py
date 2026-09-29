"""
Worker batch GED — OCR + archivage PDF/A + nettoyage.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.core.ged_syscohada import ActionGED, StatutOCR
from app.db.session import AsyncSessionLocal
from app.integrations.ocr_client import get_ocr_client
from app.models.ged import Document, DocumentOCRResult
from app.services.ged_service import GEDService
from app.services.storage_service import StorageService

logger = logging.getLogger(__name__)


async def executer_ocr_document(
    ctx: dict[str, Any],
    document_id: str,
    tenant_id: str,
    moteur: str = "tesseract",
    langues: list[str] | None = None,
) -> dict[str, Any]:
    """
    Exécute l'OCR sur un document et persiste le résultat.
    Appelé async après chaque upload.
    """
    doc_uuid = UUID(document_id)
    tenant_uuid = UUID(tenant_id)
    langues = langues or ["fra", "eng"]

    async with AsyncSessionLocal() as db:
        doc = await db.scalar(
            select(Document).where(Document.id == doc_uuid)
        )
        if doc is None:
            return {"ok": False, "reason": "not_found"}

        doc.ocr_statut = StatutOCR.EN_COURS
        await db.commit()

        # Télécharger le fichier depuis S3
        try:
            storage = StorageService()
            contenu = await storage.download(doc.fichier_url)
        except Exception as exc:
            logger.exception(f"[ged_ocr] Échec download {doc.id}")
            doc.ocr_statut = StatutOCR.ECHEC
            doc.ocr_erreur = f"Download S3 : {exc}"
            doc.ocr_at = datetime.now(timezone.utc)
            await db.commit()
            return {"ok": False, "reason": "download_failed"}

        # OCR
        try:
            client = get_ocr_client(moteur)
            result = await client.extraire_texte(contenu, doc.mime_type, langues)
        except Exception as exc:
            logger.exception(f"[ged_ocr] Échec OCR {doc.id}")
            doc.ocr_statut = StatutOCR.ECHEC
            doc.ocr_erreur = f"OCR : {exc}"
            doc.ocr_at = datetime.now(timezone.utc)
            await db.commit()
            return {"ok": False, "reason": "ocr_failed"}

        # Persister le résultat
        svc = GEDService(db, tenant_uuid, None)
        await svc.enregistrer_ocr(
            document_id=doc.id,
            texte=result.get("texte"),
            statut=StatutOCR.TERMINE,
            confiance=result.get("confiance"),
            extraction=result.get("extraction"),
        )

        # Créer / mettre à jour DocumentOCRResult
        extraction = result.get("extraction", {})
        existing = await db.scalar(
            select(DocumentOCRResult).where(DocumentOCRResult.document_id == doc.id)
        )
        if existing is None:
            from datetime import date as _d
            ocr_result = DocumentOCRResult(
                tenant_id=tenant_uuid,
                document_id=doc.id,
                moteur=result.get("moteur", moteur),
                langues=result.get("langues", langues),
                num_facture=extraction.get("num_facture"),
                nom_fournisseur=extraction.get("nom_fournisseur"),
                numero_contribuable=extraction.get("numero_contribuable"),
                montant_ht=extraction.get("montant_ht"),
                montant_tva=extraction.get("montant_tva"),
                montant_ttc=extraction.get("montant_ttc"),
                iban=extraction.get("iban"),
                score_global=result.get("confiance"),
                suggestions=None,
            )
            if extraction.get("date_facture"):
                try:
                    ocr_result.date_facture = _d.fromisoformat(extraction["date_facture"])
                except Exception:
                    pass
            db.add(ocr_result)

        await db.commit()

        logger.info(
            f"[ged_ocr] OCR terminé pour {doc.reference} "
            f"(confiance : {result.get('confiance')})"
        )
        return {"ok": True, "document_id": str(doc.id)}


async def convertir_pdf_a(ctx: dict[str, Any], limite: int = 20) -> dict[str, Any]:
    """
    Convertit les PDF standards en PDF/A-2b pour archivage légal.
    Appelé quotidiennement.
    """
    # Implémentation simplifiée — nécessite Ghostscript ou une lib PDF/A
    return {"convertis": 0, "note": "Conversion PDF/A à implémenter en V2"}


async def alerter_documents_expires(ctx: dict[str, Any]) -> dict[str, Any]:
    """Alerte sur les documents expirés (date_expiration dépassée)."""
    from datetime import date as _d
    today = _d.today()
    alertes = 0

    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(Document).where(
                    Document.date_expiration.isnot(None),
                    Document.date_expiration < today,
                    Document.supprime.is_(False),
                    Document.statut.notin_(["archive", "expire"]),
                )
            )
        ).scalars().all()

        for doc in rows:
            doc.statut = "expire"
            alertes += 1
            logger.warning(f"[ged_batch] Document expiré : {doc.reference} ({doc.nom})")

        await db.commit()

    return {"documents_expires_marques": alertes}


async def nettoyer_partages_expires(ctx: dict[str, Any]) -> dict[str, Any]:
    """Désactive les partages expirés."""
    from app.models.ged import DocumentShare
    now = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(DocumentShare).where(
                    DocumentShare.actif.is_(True),
                    DocumentShare.expire_at.isnot(None),
                    DocumentShare.expire_at < now,
                )
            )
        ).scalars().all()

        for s in rows:
            s.actif = False
        await db.commit()
        return {"partages_expires": len(rows)}


async def alerter_destruction_proche(ctx: dict[str, Any]) -> dict[str, Any]:
    """
    Alerte J-30 avant la destruction d'un document (rétention OHADA).
    """
    from datetime import date as _d
    today = _d.today()
    dans_30j = today + timedelta(days=30)
    alertes = 0

    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(Document).where(
                    Document.date_destruction_prevue.isnot(None),
                    Document.date_destruction_prevue.between(today, dans_30j),
                    Document.supprime.is_(False),
                )
            )
        ).scalars().all()

        for doc in rows:
            alertes += 1
            logger.info(
                f"[ged_batch] Destruction prévue dans "
                f"{(doc.date_destruction_prevue - today).days}j : "
                f"{doc.reference}"
            )

    return {"alertes_destruction": alertes}
