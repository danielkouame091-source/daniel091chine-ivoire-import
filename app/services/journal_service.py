"""Service Journal comptable."""
from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.journal import Journal
from app.schemas.journal import JournalCreate, JournalUpdate


class JournalService:
    def __init__(self, db: AsyncSession, tenant_id: UUID) -> None:
        self.db = db
        self.tenant_id = tenant_id

    async def create(self, data: JournalCreate) -> Journal:
        exists = await self.db.scalar(
            select(Journal.id).where(
                Journal.tenant_id == self.tenant_id,
                Journal.code == data.code,
            )
        )
        if exists:
            raise HTTPException(status.HTTP_409_CONFLICT, f"Journal {data.code} existant")

        obj = Journal(tenant_id=self.tenant_id, **data.model_dump())
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def get_by_code(self, code: str) -> Journal:
        obj = await self.db.scalar(
            select(Journal).where(
                Journal.tenant_id == self.tenant_id,
                Journal.code == code,
                Journal.actif.is_(True),
            )
        )
        if obj is None:
            raise HTTPException(404, f"Journal {code} introuvable ou inactif")
        return obj

    async def list(self, actif_only: bool = True) -> list[Journal]:
        stmt = select(Journal).where(Journal.tenant_id == self.tenant_id)
        if actif_only:
            stmt = stmt.where(Journal.actif.is_(True))
        return list((await self.db.execute(stmt.order_by(Journal.code))).scalars().all())

    async def update(self, journal_id: UUID, data: JournalUpdate) -> Journal:
        obj = await self.db.scalar(
            select(Journal).where(
                Journal.id == journal_id, Journal.tenant_id == self.tenant_id
            )
        )
        if obj is None:
            raise HTTPException(404, "Journal introuvable")
        for k, v in data.model_dump(exclude_unset=True).items():
            setattr(obj, k, v)
        await self.db.flush()
        return obj
