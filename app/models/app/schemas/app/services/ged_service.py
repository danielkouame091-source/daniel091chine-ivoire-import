"""
Service GED — Gestion documentaire complète.

Fonctionnalités :
- Upload avec checksum SHA-256 et versioning
- Dossiers hiérarchiques
- Recherche full-text (nom + description + OCR)
- OCR asynchrone (via worker)
- Soft delete + restauration
- Conformité OHADA (rétention 10 ans)
"""
from __future__ import annotations

import hashlib
import logging
import mimetypes
import secrets
from datetime import date, datetime, timedelta, timezone
from typing import Any, BinaryIO
from uuid import UUID

from fastapi import HTTPException, UploadFile
from sqlalchemy import and_, desc, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ged_syscohada import (
    ActionGED,
    DOSSIERS_SYSTEME,
    HASH_ALGO,
    MIME_TYPES_ACCEPTES,
    Retention,
    StatutDoc,
    StatutOCR,
    TAILLE_MAX_MO,
    TypeDocGED,
    TypeDossier,
)
from app.models.ged import (
    Document,
    DocumentAccessLog,
    DocumentFolder,
    DocumentVersion,
)
from app.schemas.ged import (
    DocumentBulkActionIn,
    DocumentMetadataUpdate,
    FolderCreate,
    FolderUpdate,
)
from app.services.audit_service import AuditService
from app.services.storage_service import StorageService

logger = logging.getLogger(__name__)


class GEDService:
    def __init__(self, db: AsyncSession, tenant_id: UUID, user_id: UUID) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.audit = AuditService(db)
        self.storage = StorageService()

    # ═════════════════════════════════════════════════════════════════════
    # DOSSIERS
    # ═════════════════════════════════════════════════════════════════════
    async def creer_dossier(self, data: FolderCreate) -> DocumentFolder:
        if data.parent_id:
            await self._get_folder(data.parent_id)

        folder = DocumentFolder(
            tenant_id=self.tenant_id,
            **data.model_dump(),
            created_by_user_id=self.user_id,
        )
        self.db.add(folder)
        await self.db.flush()

        await self._log_access(
            document_id=None,
            action=ActionGED.FOLDER_CREATE,
            details={"folder_id": str(folder.id), "nom": folder.nom},
        )
        return folder

    async def modifier_dossier(
        self, folder_id: UUID, data: FolderUpdate
    ) -> DocumentFolder:
        folder = await self._get_folder(folder_id)
        for k, v in data.model_dump(exclude_unset=True).items():
            setattr(folder, k, v)
        await self.db.flush()
        return folder

    async def lister_dossiers(
        self, parent_id: UUID | None = None, inclure_racine: bool = True
    ) -> list[DocumentFolder]:
        stmt = select(DocumentFolder).where(DocumentFolder.tenant_id == self.tenant_id)
        if parent_id is None and not inclure_racine:
            stmt = stmt.where(DocumentFolder.parent_id.isnot(None))
        else:
            stmt = stmt.where(DocumentFolder.parent_id == parent_id)
        stmt = stmt.order_by(DocumentFolder.ordre, DocumentFolder.nom)
        return list((await self.db.execute(stmt)).scalars().all())

    async def arbre_dossiers(self) -> list[dict[str, Any]]:
        """Retourne l'arborescence complète des dossiers."""
        all_folders = (
            await self.db.execute(
                select(DocumentFolder)
                .where(DocumentFolder.tenant_id == self.tenant_id)
                .order_by(DocumentFolder.ordre, DocumentFolder.nom)
            )
        ).scalars().all()

        # Construire l'arbre
        by_id = {f.id: {"folder": f, "enfants": []} for f in all_folders}
        roots = []
        for f in all_folders:
            node = by_id[f.id]
            if f.parent_id and f.parent_id in by_id:
                by_id[f.parent_id]["enfants"].append(node)
            else:
                roots.append(node)

        def serialize(node: dict) -> dict[str, Any]:
            f = node["folder"]
            return {
                "id": str(f.id),
                "nom": f.nom,
                "code": f.code,
                "type_dossier": f.type_dossier,
                "icone": f.icone,
                "couleur": f.couleur,
                "nb_documents": f.nb_documents,
                "enfants": [serialize(c) for c in node["enfants"]],
            }

        return [serialize(r) for r in roots]

    async def supprimer_dossier(self, folder_id: UUID) -> None:
        folder = await self._get_folder(folder_id)
        # Vérifier qu'il est vide
        nb_docs = int(await self.db.scalar(
            select(func.count(Document.id)).where(
                Document.folder_id == folder.id,
                Document.supprime.is_(False),
            )
        ) or 0)
        nb_enfants = int(await self.db.scalar(
            select(func.count(DocumentFolder.id)).where(
                DocumentFolder.parent_id == folder.id
            )
        ) or 0)
        if nb_docs > 0 or nb_enfants > 0:
            raise HTTPException(400, "Dossier non vide (documents ou sous-dossiers)")
        await self.db.delete(folder)
        await self.db.flush()

    async def seed_dossiers_systeme(self) -> int:
        """Crée les dossiers système par défaut."""
        existing_codes = set(
            (await self.db.execute(
                select(DocumentFolder.code).where(
                    DocumentFolder.tenant_id == self.tenant_id,
                    DocumentFolder.type_dossier == "systeme",
                )
            )).scalars().all()
        )

        created = 0
        for d in DOSSIERS_SYSTEME:
            if d["code"] in existing_codes:
                continue
            self.db.add(DocumentFolder(
                tenant_id=self.tenant_id,
                code=d["code"],
                nom=d["nom"],
                type_dossier="systeme",
                icone=d["icone"],
                ordre=d["ordre"],
                created_by_user_id=self.user_id,
            ))
            created += 1

        await self.db.flush()
        return created

    # ═════════════════════════════════════════════════════════════════════
    # DOCUMENTS — UPLOAD
    # ═════════════════════════════════════════════════════════════════════
    async def uploader(
        self,
        file: UploadFile,
        type_document: str,
        folder_id: UUID | None = None,
        nom: str | None = None,
        description: str | None = None,
        tags: list[str] | None = None,
        date_document: date | None = None,
        date_expiration: date | None = None,
        montant_ht: int | None = None,
        montant_tva: int | None = None,
        montant_ttc: int | None = None,
        tiers_type: str | None = None,
        tiers_id: UUID | None = None,
        ecriture_id: UUID | None = None,
        facture_id: UUID | None = None,
        projet_id: UUID | None = None,
        employe_id: UUID | None = None,
    ) -> Document:
        """
        Upload d'un nouveau document.
        - Calcule le hash SHA-256 pour intégrité
        - Upload vers S3/MinIO
        - Enregistre en DB avec version 1
        - Queue OCR si nécessaire
        """
        # Vérifier le dossier
        if folder_id:
            await self._get_folder(folder_id)

        # Valider le MIME
        mime = file.content_type or "application/octet-stream"
        if mime not in MIME_TYPES_ACCEPTES:
            # Tentative de détection par extension
            ext = "." + file.filename.split(".")[-1].lower() if "." in file.filename else ""
            detected_mime, _ = mimetypes.guess_type(file.filename or "")
            if detected_mime and detected_mime in MIME_TYPES_ACCEPTES:
                mime = detected_mime
            else:
                raise HTTPException(400, f"Type de fichier non supporté : {mime}")

        # Lire le contenu
        content = await file.read()
        taille_ko = len(content) // 1024

        if taille_ko == 0:
            raise HTTPException(400, "Fichier vide")
        if taille_ko > TAILLE_MAX_MO * 1024:
            raise HTTPException(400, f"Fichier trop volumineux (max {TAILLE_MAX_MO} Mo)")

        # Hash SHA-256
        hash_sha256 = hashlib.sha256(content).hexdigest()

        # Vérifier si le même fichier existe déjà (déduplication)
        existing = await self.db.scalar(
            select(Document).where(
                Document.tenant_id == self.tenant_id,
                Document.hash_sha256 == hash_sha256,
                Document.supprime.is_(False),
            )
        )
        if existing:
            logger.info(f"[ged] Fichier déjà existant : {existing.reference}")
            # Retourner l'existant au lieu de créer un doublon
            return existing

        # Générer la référence
        reference = await self._generer_reference(type_document)

        # Upload vers S3
        storage_key = f"tenant_{self.tenant_id}/documents/{reference}/{file.filename}"
        try:
            url = await self.storage.upload(storage_key, content, mime)
        except Exception as exc:
            logger.exception("[ged] Échec upload S3")
            raise HTTPException(500, f"Erreur de stockage : {exc}")

        # Créer le document
        doc = Document(
            tenant_id=self.tenant_id,
            folder_id=folder_id,
            reference=reference,
            nom=nom or (file.filename or "Document"),
            description=description,
            type_document=type_document,
            tags=tags or [],
            version_actuelle=1,
            fichier_url=url,
            fichier_nom_original=file.filename or "document",
            fichier_taille_kb=taille_ko,
            mime_type=mime,
            hash_sha256=hash_sha256,
            ocr_statut=StatutOCR.EN_ATTENTE,
            date_document=date_document,
            date_expiration=date_expiration,
            montant_ht=montant_ht,
            montant_tva=montant_tva,
            montant_ttc=montant_ttc,
            tiers_type=tiers_type,
            tiers_id=tiers_id,
            ecriture_id=ecriture_id,
            facture_id=facture_id,
            projet_id=projet_id,
            employe_id=employe_id,
            retention_annees=self._retenue_par_type(type_document),
            date_destruction_prevue=self._calculer_date_destruction(
                date_document or date.today(), type_document
            ),
            statut=StatutDoc.BROUILLON,
            uploaded_by_user_id=self.user_id,
        )
        self.db.add(doc)
        await self.db.flush()

        # Créer la première version
        version = DocumentVersion(
            tenant_id=self.tenant_id,
            document_id=doc.id,
            numero_version=1,
            fichier_url=url,
            fichier_nom_original=file.filename or "document",
            fichier_taille_kb=taille_ko,
            mime_type=mime,
            hash_sha256=hash_sha256,
            est_version_actuelle=True,
            uploaded_by_user_id=self.user_id,
        )
        self.db.add(version)

        # Mettre à jour les stats du dossier
        if folder_id:
            folder = await self._get_folder(folder_id)
            folder.nb_documents += 1
            folder.taille_totale_mo = float(folder.taille_totale_mo) + (taille_ko / 1024)

        await self.db.flush()

        # Indexer pour la recherche full-text
        await self._update_search_vector(doc.id)

        # Audit
        await self._log_access(
            document_id=doc.id,
            action=ActionGED.UPLOAD,
            details={
                "reference": reference,
                "taille_ko": taille_ko,
                "mime": mime,
                "hash": hash_sha256,
            },
        )

        await self.audit.log(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            action="GED_DOCUMENT_UPLOAD",
            ressource="document",
            ressource_id=doc.id,
            payload={"reference": reference, "type": type_document, "taille_ko": taille_ko},
        )

        # Queue OCR (si PDF ou image)
        if mime in ("application/pdf", "image/jpeg", "image/png", "image/tiff"):
            try:
                from arq import create_pool
                from app.workers.arq_settings import WorkerSettings
                redis = await create_pool(WorkerSettings.redis_settings)
                await redis.enqueue_job(
                    "executer_ocr_document",
                    str(doc.id), str(self.tenant_id),
                )
                await redis.aclose()
            except Exception:
                logger.exception("[ged] Échec enqueue OCR (non bloquant)")

        return doc

    async def uploader_nouvelle_version(
        self,
        document_id: UUID,
        file: UploadFile,
        commentaire: str | None = None,
    ) -> DocumentVersion:
        """
        Upload d'une nouvelle version d'un document existant.
        """
        doc = await self._get_document(document_id)

        content = await file.read()
        taille_ko = len(content) // 1024
        if taille_ko == 0:
            raise HTTPException(400, "Fichier vide")

        hash_sha256 = hashlib.sha256(content).hexdigest()
        mime = file.content_type or "application/octet-stream"

        # Nouveau numéro de version
        nouveau_numero = doc.version_actuelle + 1

        # Upload
        storage_key = f"tenant_{self.tenant_id}/documents/{doc.reference}/v{nouveau_numero}/{file.filename}"
        url = await self.storage.upload(storage_key, content, mime)

        # Marquer les anciennes versions comme non actuelles
        await self.db.execute(
            DocumentVersion.__table__.update()
            .where(
                DocumentVersion.document_id == doc.id,
                DocumentVersion.est_version_actuelle.is_(True),
            )
            .values(est_version_actuelle=False)
        )

        version = DocumentVersion(
            tenant_id=self.tenant_id,
            document_id=doc.id,
            numero_version=nouveau_numero,
            fichier_url=url,
            fichier_nom_original=file.filename or "document",
            fichier_taille_kb=taille_ko,
            mime_type=mime,
            hash_sha256=hash_sha256,
            commentaire=commentaire,
            est_version_actuelle=True,
            uploaded_by_user_id=self.user_id,
        )
        self.db.add(version)

        # Mettre à jour le document
        doc.version_actuelle = nouveau_numero
        doc.fichier_url = url
        doc.fichier_nom_original = file.filename or "document"
        doc.fichier_taille_kb = taille_ko
        doc.mime_type = mime
        doc.hash_sha256 = hash_sha256
        doc.ocr_statut = StatutOCR.EN_ATTENTE
        doc.ocr_texte = None   # Reset OCR

        await self.db.flush()

        # Reindexer
        await self._update_search_vector(doc.id)

        await self._log_access(
            document_id=doc.id,
            action=ActionGED.VERSION_CREATE,
            details={"version": nouveau_numero, "taille_ko": taille_ko},
        )

        # Queue OCR
        try:
            from arq import create_pool
            from app.workers.arq_settings import WorkerSettings
            redis = await create_pool(WorkerSettings.redis_settings)
            await redis.enqueue_job("executer_ocr_document", str(doc.id), str(self.tenant_id))
            await redis.aclose()
        except Exception:
            pass

        return version

    # ═════════════════════════════════════════════════════════════════════
    # RECHERCHE
    # ═════════════════════════════════════════════════════════════════════
    async def rechercher(
        self,
        q: str | None = None,
        type_document: str | None = None,
        folder_id: UUID | None = None,
        tiers_type: str | None = None,
        tiers_id: UUID | None = None,
        date_debut: date | None = None,
        date_fin: date | None = None,
        tags: list[str] | None = None,
        statut: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Document], int]:
        """Recherche multi-critères + full-text."""
        stmt = select(Document).where(
            Document.tenant_id == self.tenant_id,
            Document.supprime.is_(False),
        )
        count_stmt = select(func.count(Document.id)).where(
            Document.tenant_id == self.tenant_id,
            Document.supprime.is_(False),
        )

        # Full-text
        if q and q.strip():
            search_query = q.strip()
            sql_filter = text(
                "id IN (SELECT id FROM documents "
                "WHERE search_vector @@ plainto_tsquery('french', :q))"
            )
            stmt = stmt.where(sql_filter.bindparams(q=search_query))
            count_stmt = count_stmt.where(sql_filter.bindparams(q=search_query))

        if type_document:
            stmt = stmt.where(Document.type_document == type_document)
            count_stmt = count_stmt.where(Document.type_document == type_document)

        if folder_id:
            stmt = stmt.where(Document.folder_id == folder_id)
            count_stmt = count_stmt.where(Document.folder_id == folder_id)

        if tiers_type:
            stmt = stmt.where(Document.tiers_type == tiers_type)
            count_stmt = count_stmt.where(Document.tiers_type == tiers_type)

        if tiers_id:
            stmt = stmt.where(Document.tiers_id == tiers_id)
            count_stmt = count_stmt.where(Document.tiers_id == tiers_id)

        if date_debut:
            stmt = stmt.where(Document.date_document >= date_debut)
            count_stmt = count_stmt.where(Document.date_document >= date_debut)

        if date_fin:
            stmt = stmt.where(Document.date_document <= date_fin)
            count_stmt = count_stmt.where(Document.date_document <= date_fin)

        if statut:
            stmt = stmt.where(Document.statut == statut)
            count_stmt = count_stmt.where(Document.statut == statut)

        if tags:
            # Contient au moins un des tags
            stmt = stmt.where(Document.tags.op("?|")(tags))
            count_stmt = count_stmt.where(Document.tags.op("?|")(tags))

        total = int(await self.db.scalar(count_stmt) or 0)

        stmt = stmt.order_by(
            Document.epingle.desc(),
            Document.created_at.desc(),
        ).limit(limit).offset(offset)

        rows = list((await self.db.execute(stmt)).scalars().all())
        return rows, total

    async def _update_search_vector(self, document_id: UUID) -> None:
        """Met à jour le tsvector pour la recherche full-text."""
        await self.db.execute(
            text("""
                UPDATE documents
                SET search_vector = to_tsvector('french',
                    COALESCE(nom, '') || ' ' ||
                    COALESCE(description, '') || ' ' ||
                    COALESCE(ocr_texte, '') || ' ' ||
                    COALESCE(reference, '') || ' ' ||
                    COALESCE(array_to_string(tags, ' '), '')
                )
                WHERE id = :doc_id
            """),
            {"doc_id": document_id},
        )

    # ═════════════════════════════════════════════════════════════════════
    # MISE À JOUR MÉTADONNÉES
    # ═════════════════════════════════════════════════════════════════════
    async def modifier_metadonnees(
        self, document_id: UUID, data: DocumentMetadataUpdate
    ) -> Document:
        doc = await self._get_document(document_id)

        # Vérifier nouveau folder
        if data.folder_id:
            await self._get_folder(data.folder_id)

        # Mise à jour folder : mettre à jour les stats des 2 dossiers
        if data.folder_id is not None and data.folder_id != doc.folder_id:
            # Retirer du dossier source
            if doc.folder_id:
                old_folder = await self._get_folder(doc.folder_id)
                old_folder.nb_documents = max(0, old_folder.nb_documents - 1)
                old_folder.taille_totale_mo = max(
                    0, float(old_folder.taille_totale_mo) - (doc.fichier_taille_kb / 1024)
                )
            # Ajouter au dossier cible
            new_folder = await self._get_folder(data.folder_id)
            new_folder.nb_documents += 1
            new_folder.taille_totale_mo = float(new_folder.taille_totale_mo) + (doc.fichier_taille_kb / 1024)

        for k, v in data.model_dump(exclude_unset=True).items():
            setattr(doc, k, v)

        # Recalculer date de destruction si retention modifiée
        if data.retention_annees:
            date_ref = doc.date_document or date.today()
            doc.date_destruction_prevue = date(
                date_ref.year + data.retention_annees, date_ref.month, date_ref.day
            )

        await self.db.flush()
        await self._update_search_vector(doc.id)

        await self._log_access(
            document_id=doc.id,
            action=ActionGED.UPDATE_METADATA,
            details={"fields": list(data.model_dump(exclude_unset=True).keys())},
        )
        return doc

    # ═════════════════════════════════════════════════════════════════════
    # SUPPRESSION / RESTAURATION
    # ═════════════════════════════════════════════════════════════════════
    async def supprimer(self, document_id: UUID, definitif: bool = False) -> None:
        doc = await self._get_document(document_id)

        if definitif:
            # Vérifier la rétention légale
            if doc.date_destruction_prevue and doc.date_destruction_prevue > date.today():
                raise HTTPException(
                    400,
                    f"Suppression impossible : rétention légale jusqu'au "
                    f"{doc.date_destruction_prevue.isoformat()}",
                )

            # Supprimer le fichier S3
            try:
                await self.storage.delete(doc.fichier_url)
            except Exception:
                logger.exception("[ged] Échec suppression S3")

            await self.db.delete(doc)
        else:
            doc.supprime = True
            doc.supprime_at = datetime.now(timezone.utc)
            doc.supprime_par = self.user_id

        await self.db.flush()
        await self._log_access(
            document_id=doc.id,
            action=ActionGED.DELETE,
            details={"definitif": definitif},
        )

    async def restaurer(self, document_id: UUID) -> Document:
        doc = await self._get_document(document_id)
        if not doc.supprime:
            raise HTTPException(400, "Document non supprimé")
        doc.supprime = False
        doc.supprime_at = None
        doc.supprime_par = None
        await self.db.flush()
        await self._log_access(document_id=doc.id, action=ActionGED.RESTORE)
        return doc

    # ═════════════════════════════════════════════════════════════════════
    # ACTIONS EN MASSE
    # ═════════════════════════════════════════════════════════════════════
    async def action_masse(
        self, data: DocumentBulkActionIn
    ) -> dict[str, Any]:
        traites = 0
        erreurs = 0
        details = []

        for doc_id in data.document_ids:
            try:
                if data.action == "move" and data.folder_id:
                    await self.modifier_metadonnees(doc_id, DocumentMetadataUpdate(
                        folder_id=data.folder_id,
                    ))
                elif data.action == "delete":
                    await self.supprimer(doc_id, definitif=False)
                elif data.action == "restore":
                    await self.restaurer(doc_id)
                elif data.action == "archive":
                    await self.modifier_metadonnees(doc_id, DocumentMetadataUpdate(
                        statut=StatutDoc.ARCHIVE,
                    ))
                elif data.action == "add_tags":
                    doc = await self._get_document(doc_id)
                    new_tags = list(set(doc.tags + data.tags))
                    await self.modifier_metadonnees(doc_id, DocumentMetadataUpdate(tags=new_tags))

                traites += 1
            except Exception as exc:
                erreurs += 1
                details.append({"document_id": str(doc_id), "erreur": str(exc)})

        return {"nb_traites": traites, "nb_erreurs": erreurs, "details": details}

    # ═════════════════════════════════════════════════════════════════════
    # TÉLÉCHARGEMENT
    # ═════════════════════════════════════════════════════════════════════
    async def obtenir_url_telechargement(
        self, document_id: UUID, expiration_minutes: int = 15
    ) -> str:
        doc = await self._get_document(document_id)

        # Incrémenter compteur
        doc.nb_telechargements += 1
        doc.derniere_consultation_at = datetime.now(timezone.utc)
        await self.db.flush()

        # Générer URL signée
        url = await self.storage.get_signed_url(doc.fichier_url, expiration_minutes)

        await self._log_access(
            document_id=doc.id,
            action=ActionGED.DOWNLOAD,
            details={"expiration_min": expiration_minutes},
        )
        return url

    # ═════════════════════════════════════════════════════════════════════
    # OCR — Enregistrement du résultat
    # ═════════════════════════════════════════════════════════════════════
    async def enregistrer_ocr(
        self,
        document_id: UUID,
        texte: str | None,
        statut: str,
        confiance: float | None = None,
        erreur: str | None = None,
        extraction: dict[str, Any] | None = None,
    ) -> Document:
        """Appelé par le worker OCR pour persister le résultat."""
        doc = await self._get_document(document_id)
        doc.ocr_statut = statut
        doc.ocr_texte = texte
        doc.ocr_confiance = confiance
        doc.ocr_at = datetime.now(timezone.utc)
        doc.ocr_erreur = erreur

        # Mettre à jour les métadonnées extraites si disponibles
        if extraction:
            if extraction.get("date_facture") and not doc.date_document:
                try:
                    from datetime import date as _d
                    d = extraction["date_facture"]
                    if isinstance(d, str):
                        doc.date_document = _d.fromisoformat(d)
                except Exception:
                    pass
            if extraction.get("montant_ht") and not doc.montant_ht:
                doc.montant_ht = extraction["montant_ht"]
            if extraction.get("montant_tva") and not doc.montant_tva:
                doc.montant_tva = extraction["montant_tva"]
            if extraction.get("montant_ttc") and not doc.montant_ttc:
                doc.montant_ttc = extraction["montant_ttc"]

        await self.db.flush()
        await self._update_search_vector(doc.id)

        await self._log_access(
            document_id=doc.id,
            action=ActionGED.OCR_DONE,
            details={"statut": statut, "confiance": confiance, "has_extraction": bool(extraction)},
        )
        return doc

    # ═════════════════════════════════════════════════════════════════════
    # DASHBOARD
    # ═════════════════════════════════════════════════════════════════════
    async def dashboard(self) -> dict[str, Any]:
        today = date.today()

        nb_docs = int(await self.db.scalar(
            select(func.count(Document.id)).where(
                Document.tenant_id == self.tenant_id,
                Document.supprime.is_(False),
            )
        ) or 0)

        nb_folders = int(await self.db.scalar(
            select(func.count(DocumentFolder.id)).where(
                DocumentFolder.tenant_id == self.tenant_id,
            )
        ) or 0)

        taille_totale_ko = int(await self.db.scalar(
            select(func.coalesce(func.sum(Document.fichier_taille_kb), 0)).where(
                Document.tenant_id == self.tenant_id,
                Document.supprime.is_(False),
            )
        ) or 0)

        nb_ocr_attente = int(await self.db.scalar(
            select(func.count(Document.id)).where(
                Document.tenant_id == self.tenant_id,
                Document.ocr_statut.in_(["en_attente", "en_cours"]),
                Document.supprime.is_(False),
            )
        ) or 0)

        nb_sig_attente = 0   # À enrichir avec DocumentSignature
        nb_partages = 0      # À enrichir avec DocumentShare

        nb_expires = int(await self.db.scalar(
            select(func.count(Document.id)).where(
                Document.tenant_id == self.tenant_id,
                Document.date_expiration.isnot(None),
                Document.date_expiration < today,
                Document.supprime.is_(False),
            )
        ) or 0)

        dans_30j = today + timedelta(days=30)
        nb_a_detruire = int(await self.db.scalar(
            select(func.count(Document.id)).where(
                Document.tenant_id == self.tenant_id,
                Document.date_destruction_prevue.isnot(None),
                Document.date_destruction_prevue <= dans_30j,
                Document.supprime.is_(False),
            )
        ) or 0)

        # Répartition par type
        rows = (
            await self.db.execute(
                select(Document.type_document, func.count(Document.id))
                .where(
                    Document.tenant_id == self.tenant_id,
                    Document.supprime.is_(False),
                )
                .group_by(Document.type_document)
            )
        ).all()
        par_type = {r[0]: int(r[1]) for r in rows}

        # Documents récents
        recents_rows = (
            await self.db.execute(
                select(
                    Document.id, Document.nom, Document.reference,
                    Document.type_document, Document.created_at,
                )
                .where(
                    Document.tenant_id == self.tenant_id,
                    Document.supprime.is_(False),
                )
                .order_by(desc(Document.created_at))
                .limit(10)
            )
        ).all()
        recents = [
            {
                "id": str(r[0]), "nom": r[1], "reference": r[2],
                "type_document": r[3], "created_at": r[4].isoformat(),
            }
            for r in recents_rows
        ]

        return {
            "tenant_id": self.tenant_id,
            "date_arret": today,
            "nb_documents_total": nb_docs,
            "nb_dossiers_total": nb_folders,
            "taille_totale_mo": round(taille_totale_ko / 1024, 2),
            "nb_ocr_en_attente": nb_ocr_attente,
            "nb_signatures_attente": nb_sig_attente,
            "nb_partages_actifs": nb_partages,
            "nb_documents_expires": nb_expires,
            "nb_documents_a_detruire_30j": nb_a_detruire,
            "repartition_par_type": par_type,
            "documents_recents": recents,
            "top_documents_consultes": [],
        }

    # ═════════════════════════════════════════════════════════════════════
    # HELPERS
    # ═════════════════════════════════════════════════════════════════════
    async def _get_document(self, document_id: UUID) -> Document:
        d = await self.db.scalar(
            select(Document).where(
                Document.id == document_id,
                Document.tenant_id == self.tenant_id,
            )
        )
        if d is None:
            raise HTTPException(404, "Document introuvable")
        return d

    async def _get_folder(self, folder_id: UUID) -> DocumentFolder:
        f = await self.db.scalar(
            select(DocumentFolder).where(
                DocumentFolder.id == folder_id,
                DocumentFolder.tenant_id == self.tenant_id,
            )
        )
        if f is None:
            raise HTTPException(404, "Dossier introuvable")
        return f

    async def _generer_reference(self, type_document: str) -> str:
        """Génère une référence unique de type DOC-FACT-2025-00001."""
        year = date.today().year
        prefix = type_document[:4].upper()
        count = int(await self.db.scalar(
            select(func.count(Document.id)).where(
                Document.tenant_id == self.tenant_id,
                Document.reference.like(f"DOC-{prefix}-{year}-%"),
            )
        ) or 0)
        return f"DOC-{prefix}-{year}-{count + 1:05d}"

    def _retenue_par_type(self, type_document: str) -> int:
        if "social" in type_document or "cnps" in type_document:
            return Retention.SOCIAL_ANNEES
        if "contrat" in type_document or "travail" in type_document:
            return Retention.CONTRATS_ANNEES
        if "fiscal" in type_document or "dgi" in type_document:
            return Retention.FISCAL_ANNEES
        return Retention.DEFAULT_ANNEES

    def _calculer_date_destruction(self, date_ref: date, type_document: str) -> date:
        annees = self._retenue_par_type(type_document)
        try:
            return date(date_ref.year + annees, date_ref.month, date_ref.day)
        except ValueError:
            # 29 février → 28
            return date(date_ref.year + annees, date_ref.month, 28)

    async def _log_access(
        self,
        document_id: UUID | None,
        action: str,
        details: dict[str, Any] | None = None,
        succes: bool = True,
    ) -> None:
        log = DocumentAccessLog(
            tenant_id=self.tenant_id,
            document_id=document_id,
            user_id=self.user_id,
            action=action,
            succes=succes,
            details=details,
            created_at=datetime.now(timezone.utc),
        )
        self.db.add(log)
        await self.db.flush()
