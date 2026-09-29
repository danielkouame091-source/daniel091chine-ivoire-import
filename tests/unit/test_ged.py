"""
Tests du module GED.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from io import BytesIO
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import UploadFile
from sqlalchemy import select

from app.core.ged_syscohada import ActionGED, StatutDoc, StatutOCR
from app.schemas.ged import (
    DocumentMetadataUpdate,
    FolderCreate,
    ShareCreateIn,
    SignatureRequestIn,
)
from app.services.ged_service import GEDService
from app.services.ged_share_service import ShareService
from app.services.ged_signature_service import SignatureService

pytestmark = pytest.mark.integration


# ─── Fixtures ───────────────────────────────────────────────────────────────
@pytest.fixture
async def folder(db_session, tenant, admin_user):
    svc = GEDService(db_session, tenant.id, admin_user.id)
    return await svc.creer_dossier(FolderCreate(
        nom="Comptabilité 2025",
        type_dossier="custom",
    ))


# ═════════════════════════════════════════════════════════════════════════════
# TESTS DOSSIERS
# ═════════════════════════════════════════════════════════════════════════════
class TestFolders:
    async def test_creation_dossier(self, folder):
        assert folder.nom == "Comptabilité 2025"
        assert folder.type_dossier == "custom"
        assert folder.nb_documents == 0

    async def test_seed_dossiers_systeme(self, db_session, tenant, admin_user):
        svc = GEDService(db_session, tenant.id, admin_user.id)
        nb = await svc.seed_dossiers_systeme()
        assert nb >= 10
        # Idempotent
        nb2 = await svc.seed_dossiers_systeme()
        assert nb2 == 0

    async def test_arbre_dossiers(self, db_session, tenant, admin_user, folder):
        svc = GEDService(db_session, tenant.id, admin_user.id)
        # Créer un sous-dossier
        await svc.creer_dossier(FolderCreate(
            nom="Factures",
            parent_id=folder.id,
        ))
        await db_session.flush()

        arbre = await svc.arbre_dossiers()
        assert len(arbre) >= 1
        # Le dossier parent doit contenir un enfant
        parent_node = next(a for a in arbre if a["id"] == str(folder.id))
        assert len(parent_node["enfants"]) == 1


# ═════════════════════════════════════════════════════════════════════════════
# TESTS UPLOAD DOCUMENT
# ═════════════════════════════════════════════════════════════════════════════
class TestUpload:
    async def test_upload_pdf(self, db_session, tenant, admin_user, folder):
        svc = GEDService(db_session, tenant.id, admin_user.id)

        content = b"%PDF-1.4\n%fake pdf content for test\n"
        file = UploadFile(
            filename="facture.pdf",
            file=BytesIO(content),
            headers={"content-type": "application/pdf"},
        )

        with patch.object(svc.storage, "upload", new=AsyncMock(return_value="s3://bucket/key")):
            doc = await svc.uploader(
                file=file,
                type_document="facture_fournisseur",
                folder_id=folder.id,
                nom="Facture EDF",
                montant_ttc=500_000,
            )

        assert doc.nom == "Facture EDF"
        assert doc.type_document == "facture_fournisseur"
        assert doc.version_actuelle == 1
        assert doc.hash_sha256 is not None
        assert doc.montant_ttc == 500_000
        assert doc.retention_annees == 10
        assert doc.date_destruction_prevue is not None

    async def test_upload_rejette_fichier_vide(self, db_session, tenant, admin_user, folder):
        from fastapi import HTTPException
        svc = GEDService(db_session, tenant.id, admin_user.id)
        file = UploadFile(filename="empty.pdf", file=BytesIO(b""))
        with pytest.raises(HTTPException) as exc:
            await svc.uploader(file=file, type_document="autre", folder_id=folder.id)
        assert exc.value.status_code == 400

    async def test_upload_mime_inconnu_rejete(self, db_session, tenant, admin_user, folder):
        from fastapi import HTTPException
        svc = GEDService(db_session, tenant.id, admin_user.id)
        file = UploadFile(
            filename="script.exe",
            file=BytesIO(b"MZ\x90\x00"),
            headers={"content-type": "application/x-msdownload"},
        )
        with pytest.raises(HTTPException) as exc:
            await svc.uploader(file=file, type_document="autre", folder_id=folder.id)
        assert exc.value.status_code == 400

    async def test_deduplication_hash(self, db_session, tenant, admin_user, folder):
        """Uploader 2x le même fichier → même document retourné."""
        svc = GEDService(db_session, tenant.id, admin_user.id)
        content = b"identical content"

        with patch.object(svc.storage, "upload", new=AsyncMock(return_value="s3://bucket/key1")):
            file1 = UploadFile(filename="a.pdf", file=BytesIO(content),
                              headers={"content-type": "application/pdf"})
            doc1 = await svc.uploader(file=file1, type_document="autre", folder_id=folder.id)

            file2 = UploadFile(filename="b.pdf", file=BytesIO(content),
                              headers={"content-type": "application/pdf"})
            doc2 = await svc.uploader(file=file2, type_document="autre", folder_id=folder.id)

        assert doc1.id == doc2.id   # Déduplication


# ═════════════════════════════════════════════════════════════════════════════
# TESTS VERSIONING
# ═════════════════════════════════════════════════════════════════════════════
class TestVersioning:
    async def test_nouvelle_version(self, db_session, tenant, admin_user, folder):
        svc = GEDService(db_session, tenant.id, admin_user.id)
        content1 = b"version 1"
        with patch.object(svc.storage, "upload", new=AsyncMock(return_value="s3://bucket/v1")):
            file1 = UploadFile(filename="doc.pdf", file=BytesIO(content1),
                              headers={"content-type": "application/pdf"})
            doc = await svc.uploader(file=file1, type_document="autre", folder_id=folder.id)

        content2 = b"version 2 modified"
        with patch.object(svc.storage, "upload", new=AsyncMock(return_value="s3://bucket/v2")):
            file2 = UploadFile(filename="doc_v2.pdf", file=BytesIO(content2),
                              headers={"content-type": "application/pdf"})
            v2 = await svc.uploader_nouvelle_version(doc.id, file2, "Correction montant")

        await db_session.refresh(doc)
        assert doc.version_actuelle == 2
        assert v2.numero_version == 2
        assert v2.commentaire == "Correction montant"
        assert v2.est_version_actuelle is True


# ═════════════════════════════════════════════════════════════════════════════
# TESTS RECHERCHE
# ═════════════════════════════════════════════════════════════════════════════
class TestSearch:
    async def test_recherche_par_nom(self, db_session, tenant, admin_user, folder):
        svc = GEDService(db_session, tenant.id, admin_user.id)
        with patch.object(svc.storage, "upload", new=AsyncMock(return_value="s3://b/k")):
            file = UploadFile(filename="test.pdf", file=BytesIO(b"content"),
                            headers={"content-type": "application/pdf"})
            await svc.uploader(
                file=file, type_document="autre", folder_id=folder.id,
                nom="Rapport annuel 2025",
            )
        await db_session.flush()

        rows, total = await svc.rechercher(q="Rapport annuel")
        assert total >= 1
        assert any("Rapport" in d.nom for d in rows)

    async def test_recherche_par_type(self, db_session, tenant, admin_user, folder):
        svc = GEDService(db_session, tenant.id, admin_user.id)
        with patch.object(svc.storage, "upload", new=AsyncMock(return_value="s3://b/k")):
            file = UploadFile(filename="f.pdf", file=BytesIO(b"content"),
                            headers={"content-type": "application/pdf"})
            await svc.uploader(
                file=file, type_document="facture_fournisseur", folder_id=folder.id,
            )
        await db_session.flush()

        rows, total = await svc.rechercher(type_document="facture_fournisseur")
        assert total >= 1


# ═════════════════════════════════════════════════════════════════════════════
# TESTS MISE À JOUR MÉTADONNÉES
# ═════════════════════════════════════════════════════════════════════════════
class TestMetadata:
    async def test_modification_nom(self, db_session, tenant, admin_user, folder):
        svc = GEDService(db_session, tenant.id, admin_user.id)
        with patch.object(svc.storage, "upload", new=AsyncMock(return_value="s3://b/k")):
            file = UploadFile(filename="x.pdf", file=BytesIO(b"content"),
                            headers={"content-type": "application/pdf"})
            doc = await svc.uploader(file=file, type_document="autre", folder_id=folder.id)

        updated = await svc.modifier_metadonnees(doc.id, DocumentMetadataUpdate(
            nom="Nouveau nom",
            statut=StatutDoc.VALIDE,
            tags=["important", "2025"],
        ))
        assert updated.nom == "Nouveau nom"
        assert updated.statut == StatutDoc.VALIDE
        assert "important" in updated.tags


# ═════════════════════════════════════════════════════════════════════════════
# TESTS SUPPRESSION
# ═════════════════════════════════════════════════════════════════════════════
class TestDelete:
    async def test_soft_delete(self, db_session, tenant, admin_user, folder):
        svc = GEDService(db_session, tenant.id, admin_user.id)
        with patch.object(svc.storage, "upload", new=AsyncMock(return_value="s3://b/k")):
            file = UploadFile(filename="d.pdf", file=BytesIO(b"content"),
                            headers={"content-type": "application/pdf"})
            doc = await svc.uploader(file=file, type_document="autre", folder_id=folder.id)

        await svc.supprimer(doc.id, definitif=False)
        await db_session.refresh(doc)
        assert doc.supprime is True

    async def test_suppression_definitive_bloquee_par_retention(
        self, db_session, tenant, admin_user, folder
    ):
        """Document récent ne peut pas être supprimé définitivement (rétention 10 ans)."""
        from fastapi import HTTPException
        svc = GEDService(db_session, tenant.id, admin_user.id)
        with patch.object(svc.storage, "upload", new=AsyncMock(return_value="s3://b/k")):
            file = UploadFile(filename="d.pdf", file=BytesIO(b"content"),
                            headers={"content-type": "application/pdf"})
            doc = await svc.uploader(
                file=file, type_document="facture_fournisseur", folder_id=folder.id,
                date_document=date.today(),
            )

        with pytest.raises(HTTPException) as exc:
            await svc.supprimer(doc.id, definitif=True)
        assert exc.value.status_code == 400
        assert "rétention" in exc.value.detail.lower()

    async def test_restauration(self, db_session, tenant, admin_user, folder):
        svc = GEDService(db_session, tenant.id, admin_user.id)
        with patch.object(svc.storage, "upload", new=AsyncMock(return_value="s3://b/k")):
            file = UploadFile(filename="d.pdf", file=BytesIO(b"content"),
                            headers={"content-type": "application/pdf"})
            doc = await svc.uploader(file=file, type_document="autre", folder_id=folder.id)

        await svc.supprimer(doc.id, definitif=False)
        restored = await svc.restaurer(doc.id)
        assert restored.supprime is False


# ═════════════════════════════════════════════════════════════════════════════
# TESTS SIGNATURE
# ═════════════════════════════════════════════════════════════════════════════
class TestSignature:
    async def test_signature_interne(self, db_session, tenant, admin_user, folder):
        svc = GEDService(db_session, tenant.id, admin_user.id)
        with patch.object(svc.storage, "upload", new=AsyncMock(return_value="s3://b/k")):
            file = UploadFile(filename="c.pdf", file=BytesIO(b"contract"),
                            headers={"content-type": "application/pdf"})
            doc = await svc.uploader(file=file, type_document="autre", folder_id=folder.id)

        sig_svc = SignatureService(db_session, tenant.id, admin_user.id)
        sig, otp = await sig_svc.demander_signature(doc.id, SignatureRequestIn(
            type_signature="simple",
            signataire_nom="Signataire Interne",
        ))
        assert sig.statut == "en_attente"
        assert otp is None   # Pas d'OTP pour signature simple interne

    async def test_signature_externe_avec_otp(self, db_session, tenant, admin_user, folder):
        svc = GEDService(db_session, tenant.id, admin_user.id)
        with patch.object(svc.storage, "upload", new=AsyncMock(return_value="s3://b/k")):
            file = UploadFile(filename="c.pdf", file=BytesIO(b"contract"),
                            headers={"content-type": "application/pdf"})
            doc = await svc.uploader(file=file, type_document="autre", folder_id=folder.id)

        sig_svc = SignatureService(db_session, tenant.id, admin_user.id)
        with patch("app.services.notification_service.NotificationService.envoyer", new=AsyncMock()):
            sig, otp = await sig_svc.demander_signature(doc.id, SignatureRequestIn(
                type_signature="avancee",
                signataire_email="client@test.ci",
                signataire_nom="Client Externe",
            ))
        assert sig.statut == "otp_envoye"
        assert otp is not None
        assert len(otp) == 6
        assert otp.isdigit()

    async def test_verification_otp_et_signature(
        self, db_session, tenant, admin_user, folder
    ):
        svc = GEDService(db_session, tenant.id, admin_user.id)
        with patch.object(svc.storage, "upload", new=AsyncMock(return_value="s3://b/k")):
            file = UploadFile(filename="c.pdf", file=BytesIO(b"contract"),
                            headers={"content-type": "application/pdf"})
            doc = await svc.uploader(file=file, type_document="autre", folder_id=folder.id)

        sig_svc = SignatureService(db_session, tenant.id, admin_user.id)
        with patch("app.services.notification_service.NotificationService.envoyer", new=AsyncMock()):
            sig, otp_plain = await sig_svc.demander_signature(doc.id, SignatureRequestIn(
                type_signature="avancee",
                signataire_email="client@test.ci",
                signataire_nom="Client Externe",
            ))

        sig_signe = await sig_svc.verifier_otp_et_signer(sig.id, otp_plain)
        assert sig_signe.statut == "signee"
        assert sig_signe.signature_hash is not None

        # Vérifier l'intégrité
        verify = await sig_svc.verifier_signature(sig.id)
        assert verify["valide"] is True

    async def test_otp_invalide_rejete(self, db_session, tenant, admin_user, folder):
        from fastapi import HTTPException
        svc = GEDService(db_session, tenant.id, admin_user.id)
        with patch.object(svc.storage, "upload", new=AsyncMock(return_value="s3://b/k")):
            file = UploadFile(filename="c.pdf", file=BytesIO(b"contract"),
                            headers={"content-type": "application/pdf"})
            doc = await svc.uploader(file=file, type_document="autre", folder_id=folder.id)

        sig_svc = SignatureService(db_session, tenant.id, admin_user.id)
        with patch("app.services.notification_service.NotificationService.envoyer", new=AsyncMock()):
            sig, _ = await sig_svc.demander_signature(doc.id, SignatureRequestIn(
                type_signature="avancee",
                signataire_email="client@test.ci",
                signataire_nom="Client",
            ))

        with pytest.raises(HTTPException) as exc:
            await sig_svc.verifier_otp_et_signer(sig.id, "000000")
        assert exc.value.status_code == 400


# ═════════════════════════════════════════════════════════════════════════════
# TESTS PARTAGE
# ═════════════════════════════════════════════════════════════════════════════
class TestShare:
    async def test_creation_partage(self, db_session, tenant, admin_user, folder):
        svc = GEDService(db_session, tenant.id, admin_user.id)
        with patch.object(svc.storage, "upload", new=AsyncMock(return_value="s3://b/k")):
            file = UploadFile(filename="c.pdf", file=BytesIO(b"contract"),
                            headers={"content-type": "application/pdf"})
            doc = await svc.uploader(file=file, type_document="autre", folder_id=folder.id)

        share_svc = ShareService(db_session, tenant.id, admin_user.id)
        share, token = await share_svc.creer_partage(doc.id, ShareCreateIn(
            destinataire_email="client@test.ci",
            expire_dans_heures=48,
        ))
        assert share.actif is True
        assert token is not None
        assert len(token) > 20
        assert share.token_prefix == token[:12]

    async def test_acces_via_token(self, db_session, tenant, admin_user, folder):
        svc = GEDService(db_session, tenant.id, admin_user.id)
        with patch.object(svc.storage, "upload", new=AsyncMock(return_value="s3://b/k")):
            file = UploadFile(filename="c.pdf", file=BytesIO(b"contract"),
                            headers={"content-type": "application/pdf"})
            doc = await svc.uploader(file=file, type_document="autre", folder_id=folder.id)

        share_svc = ShareService(db_session, tenant.id, admin_user.id)
        _, token = await share_svc.creer_partage(doc.id, ShareCreateIn())
        await db_session.flush()

        accessed = await share_svc.acceder_par_token(token)
        assert accessed.id == doc.id

    async def test_partage_protege_par_mot_de_passe(
        self, db_session, tenant, admin_user, folder
    ):
        from fastapi import HTTPException
        svc = GEDService(db_session, tenant.id, admin_user.id)
        with patch.object(svc.storage, "upload", new=AsyncMock(return_value="s3://b/k")):
            file = UploadFile(filename="c.pdf", file=BytesIO(b"contract"),
                            headers={"content-type": "application/pdf"})
            doc = await svc.uploader(file=file, type_document="autre", folder_id=folder.id)

        share_svc = ShareService(db_session, tenant.id, admin_user.id)
        _, token = await share_svc.creer_partage(doc.id, ShareCreateIn(
            mot_de_passe="Secret123!",
        ))
        await db_session.flush()

        # Sans mot de passe → 401
        with pytest.raises(HTTPException) as exc:
            await share_svc.acceder_par_token(token)
        assert exc.value.status_code == 401

        # Mauvais mot de passe → 401
        with pytest.raises(HTTPException):
            await share_svc.acceder_par_token(token, mot_de_passe="wrong")

        # Bon mot de passe → OK
        doc2 = await share_svc.acceder_par_token(token, mot_de_passe="Secret123!")
        assert doc2.id == doc.id

    async def test_revocation_partage(self, db_session, tenant, admin_user, folder):
        from fastapi import HTTPException
        from app.schemas.ged import ShareRevokeIn

        svc = GEDService(db_session, tenant.id, admin_user.id)
        with patch.object(svc.storage, "upload", new=AsyncMock(return_value="s3://b/k")):
            file = UploadFile(filename="c.pdf", file=BytesIO(b"contract"),
                            headers={"content-type": "application/pdf"})
            doc = await svc.uploader(file=file, type_document="autre", folder_id=folder.id)

        share_svc = ShareService(db_session, tenant.id, admin_user.id)
        share, token = await share_svc.creer_partage(doc.id, ShareCreateIn())
        await db_session.flush()

        await share_svc.revoquer_partage(share.id, ShareRevokeIn(motif="Plus nécessaire"))

        with pytest.raises(HTTPException) as exc:
            await share_svc.acceder_par_token(token)
        assert exc.value.status_code == 410


# ═════════════════════════════════════════════════════════════════════════════
# TESTS DASHBOARD
# ═════════════════════════════════════════════════════════════════════════════
class TestDashboard:
    async def test_dashboard_vide(self, db_session, tenant, admin_user):
        svc = GEDService(db_session, tenant.id, admin_user.id)
        dash = await svc.dashboard()
        assert dash["nb_documents_total"] == 0
        assert dash["nb_dossiers_total"] == 0

    async def test_dashboard_avec_docs(self, db_session, tenant, admin_user, folder):
        svc = GEDService(db_session, tenant.id, admin_user.id)
        with patch.object(svc.storage, "upload", new=AsyncMock(return_value="s3://b/k")):
            for i in range(3):
                file = UploadFile(filename=f"doc{i}.pdf", file=BytesIO(f"content{i}".encode()),
                                headers={"content-type": "application/pdf"})
                await svc.uploader(file=file, type_document="facture_fournisseur", folder_id=folder.id)
        await db_session.flush()

        dash = await svc.dashboard()
        assert dash["nb_documents_total"] == 3
        assert dash["repartition_par_type"].get("facture_fournisseur") == 3
