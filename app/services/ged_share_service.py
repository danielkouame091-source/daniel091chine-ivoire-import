"""
Service Partage sécurisé — Liens tokenisés pour partage externe.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ged_syscohada import (
    ActionGED,
    SecuritePartage,
)
from app.models.ged import (
    Document,
    DocumentAccessLog,
    DocumentShare,
)
from app.schemas.ged import ShareCreateIn, ShareRevokeIn
from app.services.audit_service import AuditService

logger = logging.getLogger(__name__)


class ShareService:
    def __init__(self, db: AsyncSession, tenant_id: UUID, user_id: UUID) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.audit = AuditService(db)

    async def creer_partage(
        self, document_id: UUID, data: ShareCreateIn
    ) -> tuple[DocumentShare, str]:
        """Crée un partage avec token."""
        doc = await self._get_document(document_id)

        # Générer le token
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        token_prefix = token[:12]

        # Hash mot de passe si fourni
        mdp_hash = None
        if data.mot_de_passe:
            mdp_hash = hashlib.sha256(data.mot_de_passe.encode()).hexdigest()

        expire_at = datetime.now(timezone.utc) + timedelta(hours=data.expire_dans_heures)

        share = DocumentShare(
            tenant_id=self.tenant_id,
            document_id=doc.id,
            token_hash=token_hash,
            token_prefix=token_prefix,
            destinataire_email=data.destinataire_email,
            destinataire_nom=data.destinataire_nom,
            peut_telecharger=data.peut_telecharger,
            peut_signer=data.peut_signer,
            protege_par_mot_de_passe=bool(data.mot_de_passe),
            mot_de_passe_hash=mdp_hash,
            expire_at=expire_at,
            max_telechargements=data.max_telechargements,
            actif=True,
            created_by_user_id=self.user_id,
        )
        self.db.add(share)
        await self.db.flush()

        await self._log(
            document_id=doc.id,
            action=ActionGED.SHARE,
            details={
                "share_id": str(share.id),
                "expire_at": expire_at.isoformat(),
                "destinataire": data.destinataire_email,
            },
        )

        return share, token

    async def acceder_par_token(
        self,
        token: str,
        mot_de_passe: str | None = None,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> Document:
        """Accède à un document via token (public)."""
        token_hash = hashlib.sha256(token.encode()).hexdigest()

        share = await self.db.scalar(
            select(DocumentShare).where(DocumentShare.token_hash == token_hash)
        )
        if share is None:
            raise HTTPException(404, "Lien invalide")

        if not share.actif:
            raise HTTPException(410, "Lien révoqué")
        if share.expire_at and share.expire_at < datetime.now(timezone.utc):
            raise HTTPException(410, "Lien expiré")
        if share.max_telechargements and share.nb_telechargements >= share.max_telechargements:
            raise HTTPException(410, "Limite de téléchargements atteinte")

        # Vérifier mot de passe
        if share.protege_par_mot_de_passe:
            if not mot_de_passe:
                raise HTTPException(401, "Mot de passe requis")
            mdp_hash = hashlib.sha256(mot_de_passe.encode()).hexdigest()
            if mdp_hash != share.mot_de_passe_hash:
                await self._log(
                    document_id=share.document_id,
                    action=ActionGED.VIEW,
                    details={"share_id": str(share.id), "erreur": "mot_de_passe_invalide"},
                    succes=False,
                )
                raise HTTPException(401, "Mot de passe incorrect")

        # Incrémenter le compteur
        share.nb_vues += 1
        share.derniere_utilisation_at = datetime.now(timezone.utc)

        doc = await self._get_document(share.document_id)

        await self._log(
            document_id=doc.id,
            action=ActionGED.VIEW,
            details={"share_id": str(share.id)},
        )

        return doc

    async def telecharger_par_token(
        self, token: str, mot_de_passe: str | None = None
    ) -> str:
        """Retourne l'URL signée après vérification du token."""
        doc = await self.acceder_par_token(token, mot_de_passe)

        # Vérifier permission téléchargement
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        share = await self.db.scalar(
            select(DocumentShare).where(DocumentShare.token_hash == token_hash)
        )
        if share and not share.peut_telecharger:
            raise HTTPException(403, "Téléchargement non autorisé")

        if share:
            share.nb_telechargements += 1
            await self.db.flush()

        # Incrémenter compteur doc
        doc.nb_telechargements += 1
        await self.db.flush()

        # Générer URL signée
        from app.services.storage_service import StorageService
        storage = StorageService()
        url = await storage.get_signed_url(doc.fichier_url, 15)

        await self._log(
            document_id=doc.id,
            action=ActionGED.DOWNLOAD,
            details={"share_id": str(share.id) if share else None},
        )
        return url

    async def revoquer_partage(
        self, share_id: UUID, data: ShareRevokeIn
    ) -> DocumentShare:
        share = await self.db.scalar(
            select(DocumentShare).where(
                DocumentShare.id == share_id,
                DocumentShare.tenant_id == self.tenant_id,
            )
        )
        if share is None:
            raise HTTPException(404, "Partage introuvable")
        share.actif = False
        share.revoque_at = datetime.now(timezone.utc)
        share.motif_revocation = data.motif
        await self.db.flush()

        await self._log(
            document_id=share.document_id,
            action=ActionGED.REVOKE_SHARE,
            details={"share_id": str(share.id), "motif": data.motif},
        )
        return share

    async def lister_partages(self, document_id: UUID) -> list[DocumentShare]:
        stmt = select(DocumentShare).where(
            DocumentShare.tenant_id == self.tenant_id,
            DocumentShare.document_id == document_id,
        ).order_by(desc(DocumentShare.created_at))
        return list((await self.db.execute(stmt)).scalars().all())

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
