"""
Service Audit — journal immuable, chaîné par hash SHA-256.
Chaque entrée chaîne la précédente ; toute altération casse la chaîne.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import sha256_hex
from app.models.audit import AuditLog


class AuditService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def log(
        self,
        *,
        tenant_id: UUID | None,
        user_id: UUID | None,
        action: str,
        ressource: str,
        ressource_id: UUID | None = None,
        ip: str | None = None,
        user_agent: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> AuditLog:
        """Insère une entrée d'audit chaînée à la précédente (par tenant)."""
        # Dernier hash connu pour ce tenant (ou global si tenant_id est NULL)
        stmt = (
            select(AuditLog.hash_courant)
            .where(AuditLog.tenant_id == tenant_id if tenant_id else AuditLog.tenant_id.is_(None))
            .order_by(desc(AuditLog.id))
            .limit(1)
        )
        precedent = (await self.db.execute(stmt)).scalar_one_or_none()

        contenu = "|".join([
            str(tenant_id or ""),
            str(user_id or ""),
            action,
            ressource,
            str(ressource_id or ""),
            str(payload or {}),
        ])
        hash_courant = sha256_hex(f"{precedent or 'GENESIS'}|{contenu}")

        entry = AuditLog(
            tenant_id=tenant_id,
            user_id=user_id,
            action=action,
            ressource=ressource,
            ressource_id=ressource_id,
            ip=ip,
            user_agent=user_agent,
            payload=payload,
            hash_precedent=precedent,
            hash_courant=hash_courant,
            created_at=datetime.now(timezone.utc),
        )
        self.db.add(entry)
        await self.db.flush()
        return entry

    async def verify_chain(
        self, tenant_id: UUID | None, limit: int = 1000
    ) -> tuple[bool, int]:
        """
        Vérifie l'intégrité de la chaîne. Retourne (valide, nb_entrées_vérifiées).
        Utilisé par le cockpit admin pour détecter toute altération.
        """
        stmt = (
            select(AuditLog)
            .where(AuditLog.tenant_id == tenant_id if tenant_id else AuditLog.tenant_id.is_(None))
            .order_by(AuditLog.id.asc())
            .limit(limit)
        )
        entries = (await self.db.execute(stmt)).scalars().all()
        precedent: str | None = None
        for e in entries:
            contenu = "|".join([
                str(e.tenant_id or ""),
                str(e.user_id or ""),
                e.action,
                e.ressource,
                str(e.ressource_id or ""),
                str(e.payload or {}),
            ])
            attendu = sha256_hex(f"{precedent or 'GENESIS'}|{contenu}")
            if attendu != e.hash_courant or e.hash_precedent != precedent:
                return False, 0
            precedent = e.hash_courant
        return True, len(entries)
