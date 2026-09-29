"""
Service Signature électronique — Interne + Externe par OTP.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ged_syscohada import (
    ActionGED,
    SecuritePartage,
    StatutDoc,
    StatutSignature,
    TypeSignature,
)
from app.models.ged import (
    Document,
    DocumentAccessLog,
    DocumentSignature,
)
from app.schemas.ged import (
    SignatureRefuseIn,
    SignatureRequestIn,
)
from app.services.audit_service import AuditService

logger = logging.getLogger(__name__)


class SignatureService:
    def __init__(self, db: AsyncSession, tenant_id: UUID, user_id: UUID | None) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.audit = AuditService(db)

    # ═════════════════════════════════════════════════════════════════════
    # DEMANDE DE SIGNATURE
    # ═════════════════════════════════════════════════════════════════════
    async def demander_signature(
        self, document_id: UUID, data: SignatureRequestIn
    ) -> tuple[DocumentSignature, str | None]:
        """
        Crée une demande de signature.
        - Interne : signature directe si signataire_email == user connecté
        - Externe : envoi OTP par email
        """
        doc = await self._get_document(document_id)

        if doc.statut not in (StatutDoc.BROUILLON, StatutDoc.EN_REVISION, StatutDoc.VALIDE):
            raise HTTPException(400, f"Document en statut {doc.statut} — non signable")

        # Type signataire
        signataire_type = "interne" if (self.user_id and data.signataire_email is None) else "externe"

        # Générer OTP si signature avancée externe
        otp_hash = None
        otp_expire = None
        otp_plain = None

        if data.type_signature in ("avancee", "qualifiee") and data.signataire_email:
            otp_plain = f"{secrets.randbelow(1_000_000):06d}"
            otp_hash = hashlib.sha256(otp_plain.encode()).hexdigest()
            otp_expire = datetime.now(timezone.utc) + timedelta(minutes=30)
            signataire_type = "externe"

        sig = DocumentSignature(
            tenant_id=self.tenant_id,
            document_id=doc.id,
            type_signature=data.type_signature,
            signataire_type=signataire_type,
            signataire_user_id=self.user_id if signataire_type == "interne" else None,
            signataire_email=data.signataire_email,
            signataire_nom=data.signataire_nom,
            signataire_telephone=data.signataire_telephone,
            otp_hash=otp_hash,
            otp_envoye_at=datetime.now(timezone.utc) if otp_plain else None,
            otp_expire_at=otp_expire,
            position_page=data.position_page,
            position_x=data.position_x,
            position_y=data.position_y,
            statut=StatutSignature.OTP_ENVOYE if otp_plain else StatutSignature.EN_ATTENTE,
            demande_par_user_id=self.user_id,
            message_demande=data.message_demande,
        )
        self.db.add(sig)
        await self.db.flush()

        # Mettre à jour le document
        doc.signature_requise = True
        doc.signature_statut = sig.statut
        await self.db.flush()

        # Envoyer l'OTP par email (via NotificationService)
        if otp_plain and data.signataire_email:
            try:
                from app.services.notification_service import NotificationService
                from app.schemas.notification import SendNotificationIn
                notif_svc = NotificationService(self.db, self.tenant_id, self.user_id)
                await notif_svc.envoyer(SendNotificationIn(
                    destinataire_email=data.signataire_email,
                    destinataire_nom=data.signataire_nom,
                    canal="email",
                    type_notification="signature_request",
                    criticite="haute",
                    sujet=f"Demande de signature : {doc.nom}",
                    contenu_html=(
                        f"<h1>Bonjour {data.signataire_nom},</h1>"
                        f"<p>Vous êtes invité(e) à signer le document : <strong>{doc.nom}</strong>.</p>"
                        f"<p>Votre code de vérification : <strong>{otp_plain}</strong></p>"
                        f"<p>Valable 30 minutes.</p>"
                    ),
                    contexte={"document_id": str(doc.id), "signature_id": str(sig.id)},
                ))
            except Exception:
                logger.exception("[signature] Échec envoi OTP")

        await self._log(
            document_id=doc.id,
            action=ActionGED.SIGN,
            details={"signature_id": str(sig.id), "type": data.type_signature},
        )

        return sig, otp_plain

    # ═════════════════════════════════════════════════════════════════════
    # VÉRIFICATION OTP + SIGNATURE
    # ═════════════════════════════════════════════════════════════════════
    async def verifier_otp_et_signer(
        self,
        signature_id: UUID,
        otp_code: str,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> DocumentSignature:
        """Vérifie l'OTP et marque la signature comme effective."""
        sig = await self._get_signature(signature_id)

        if sig.statut == StatutSignature.SIGNEE:
            return sig
        if sig.statut == StatutSignature.REFUSEE:
            raise HTTPException(400, "Signature déjà refusée")
        if sig.otp_expire_at and sig.otp_expire_at < datetime.now(timezone.utc):
            sig.statut = StatutSignature.EXPIREE
            await self.db.flush()
            raise HTTPException(400, "OTP expiré")

        # Vérifier OTP
        otp_hash = hashlib.sha256(otp_code.encode()).hexdigest()
        if otp_hash != sig.otp_hash:
            await self._log(
                document_id=sig.document_id,
                action=ActionGED.SIGN,
                details={"signature_id": str(sig.id), "erreur": "otp_invalide"},
                succes=False,
            )
            raise HTTPException(400, "Code OTP invalide")

        # Marquer comme signée
        doc = await self._get_document(sig.document_id)
        now = datetime.now(timezone.utc)

        # Calculer un hash de signature (preuve)
        signature_data = f"{sig.id}|{doc.hash_sha256}|{sig.signataire_email or ''}|{now.isoformat()}"
        sig_hash = hashlib.sha256(signature_data.encode()).hexdigest()

        sig.otp_verifie_at = now
        sig.signe_at = now
        sig.statut = StatutSignature.SIGNEE
        sig.ip_address = ip
        sig.user_agent = user_agent
        sig.signature_hash = sig_hash

        doc.signature_statut = "signee"
        doc.statut = StatutDoc.SIGNE

        await self.db.flush()

        await self._log(
            document_id=doc.id,
            action=ActionGED.SIGN,
            details={"signature_id": str(sig.id), "hash": sig_hash},
        )
        return sig

    async def refuser_signature(
        self, signature_id: UUID, data: SignatureRefuseIn
    ) -> DocumentSignature:
        sig = await self._get_signature(signature_id)
        sig.statut = StatutSignature.REFUSEE
        sig.refuse_at = datetime.now(timezone.utc)
        sig.motif_refus = data.motif
        await self.db.flush()

        doc = await self._get_document(sig.document_id)
        doc.signature_statut = "refusee"
        await self.db.flush()
        return sig

    # ═════════════════════════════════════════════════════════════════════
    # VÉRIFICATION DE SIGNATURE
    # ═════════════════════════════════════════════════════════════════════
    async def verifier_signature(
        self, signature_id: UUID
    ) -> dict[str, Any]:
        """Vérifie l'intégrité d'une signature."""
        sig = await self._get_signature(signature_id)

        if sig.statut != StatutSignature.SIGNEE:
            return {
                "signature_id": str(sig.id),
                "valide": False,
                "raison": f"Statut : {sig.statut}",
            }

        doc = await self._get_document(sig.document_id)

        # Recalculer le hash attendu
        expected_data = (
            f"{sig.id}|{doc.hash_sha256}|{sig.signataire_email or ''}|"
            f"{sig.signe_at.isoformat()}"
        )
        expected_hash = hashlib.sha256(expected_data.encode()).hexdigest()

        valide = expected_hash == sig.signature_hash

        await self._log(
            document_id=doc.id,
            action=ActionGED.VERIFY_SIGNATURE,
            details={"signature_id": str(sig.id), "valide": valide},
        )

        return {
            "signature_id": str(sig.id),
            "valide": valide,
            "hash_calcule": expected_hash,
            "hash_stocke": sig.signature_hash,
            "signataire": sig.signataire_nom,
            "signe_at": sig.signe_at.isoformat() if sig.signe_at else None,
        }

    # ═════════════════════════════════════════════════════════════════════
    # LISTE
    # ═════════════════════════════════════════════════════════════════════
    async def lister_signatures(
        self, document_id: UUID | None = None, statut: str | None = None
    ) -> list[DocumentSignature]:
        stmt = select(DocumentSignature).where(DocumentSignature.tenant_id == self.tenant_id)
        if document_id:
            stmt = stmt.where(DocumentSignature.document_id == document_id)
        if statut:
            stmt = stmt.where(DocumentSignature.statut == statut)
        stmt = stmt.order_by(desc(DocumentSignature.created_at))
        return list((await self.db.execute(stmt)).scalars().all())

    # ═════════════════════════════════════════════════════════════════════
    # HELPERS
    # ═════════════════════════════════════════════════════════════════════
    async def _get_signature(self, signature_id: UUID) -> DocumentSignature:
        s = await self.db.scalar(
            select(DocumentSignature).where(
                DocumentSignature.id == signature_id,
                DocumentSignature.tenant_id == self.tenant_id,
            )
        )
        if s is None:
            raise HTTPException(404, "Signature introuvable")
        return s

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

    async def _log(
        self,
        document_id: UUID,
        action: str,
        details: dict[str, Any] | None = None,
        succes: bool = True,
    ) -> None:
        self.db.add(DocumentAccessLog(
            tenant_id=self.tenant_id,
            document_id=document_id,
            user_id=self.user_id,
            action=action,
            succes=succes,
            details=details,
            created_at=datetime.now(timezone.utc),
        ))
        await self.db.flush()
