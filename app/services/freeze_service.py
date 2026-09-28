"""
Service Freeze — protocole de gel en cascade (rigueur bancaire).
Le graphe de propagation est déclaré dans `freeze_cascade_rules`.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ecriture import Ecriture
from app.models.enums import (
    EcritureStatut,
    FreezeCible,
    FreezeStatut,
    MMStatut,
    TenantStatut,
    UserStatut,
)
from app.models.freeze import (
    FreezeCascadeRule,
    FreezeEvent,
    FreezeTarget,
    TenantFreezeState,
)
from app.models.mobile_money import MmTransaction
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.freeze import FreezeRequest, FreezeResultOut
from app.services.audit_service import AuditService


class FreezeService:
    def __init__(self, db: AsyncSession, tenant_id: UUID, user_id: UUID) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.audit = AuditService(db)

    # ------------------------------------------------------------------
    # Gel
    # ------------------------------------------------------------------
    async def geler(self, req: FreezeRequest, ip: str | None = None) -> FreezeResultOut:
        now = datetime.now(timezone.utc)

        # 1. Créer l'événement racine
        event = FreezeEvent(
            tenant_id=self.tenant_id,
            cible_type=req.cible_type,
            cible_id=req.cible_id,
            motif=req.motif,
            details=req.details or {},
            declencheur_user_id=self.user_id,
            declencheur_ip=ip,
            cascade_profondeur=0,
            statut=FreezeStatut.ACTIF,
        )
        self.db.add(event)
        await self.db.flush()

        # 2. Matérialiser la racine
        targets: list[FreezeTarget] = []
        racine = FreezeTarget(
            freeze_event_id=event.id,
            tenant_id=self.tenant_id,
            cible_type=req.cible_type,
            cible_id=req.cible_id,
            niveau_profondeur=0,
            raison="racine",
            statut=FreezeStatut.ACTIF,
            gele_at=now,
        )
        self.db.add(racine)
        targets.append(racine)

        # 3. Cascade si demandée
        if req.cascade:
            cascade = await self._propager(event, req.cible_type, req.cible_id, now, niveau=1)
            targets.extend(cascade)

        # 4. Appliquer les effets métier (UPDATE sur les tables)
        await self._appliquer_effets(req.cible_type, req.cible_id, targets, now)

        # 5. Mettre à jour le cache chaud
        await self._sync_cache_chaud(event, targets)

        # 6. Audit
        await self.audit.log(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            action="FREEZE_CASCADE",
            ressource=req.cible_type.value,
            ressource_id=req.cible_id,
            payload={
                "motif": req.motif,
                "nb_cibles": len(targets),
                "freeze_event_id": str(event.id),
            },
            ip=ip,
        )

        await self.db.flush()
        # Recharger les targets avec leurs ids
        return FreezeResultOut(
            event=event,  # type: ignore[arg-type]
            cibles_atteintes=targets,  # type: ignore[arg-type]
            total_cibles=len(targets),
        )

    # ------------------------------------------------------------------
    # Levée
    # ------------------------------------------------------------------
    async def lever(self, freeze_event_id: UUID, motif_levee: str) -> FreezeEvent:
        event = await self.db.scalar(
            select(FreezeEvent).where(
                FreezeEvent.id == freeze_event_id,
                FreezeEvent.tenant_id == self.tenant_id,
            )
        )
        if event is None:
            raise HTTPException(404, "Événement de gel introuvable")
        if event.statut == FreezeStatut.LEVE:
            return event

        now = datetime.now(timezone.utc)
        event.statut = FreezeStatut.LEVE
        event.leve_at = now
        event.leve_par = self.user_id

        targets = (
            await self.db.execute(
                select(FreezeTarget).where(FreezeTarget.freeze_event_id == event.id)
            )
        ).scalars().all()
        for t in targets:
            t.statut = FreezeStatut.LEVE
            t.leve_at = now

        await self._sync_cache_chaud(event, [])
        await self.audit.log(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            action="FREEZE_LEVE",
            ressource=event.cible_type.value,
            ressource_id=event.cible_id,
            payload={"motif_levee": motif_levee, "freeze_event_id": str(event.id)},
        )
        await self.db.flush()
        return event

    # ------------------------------------------------------------------
    # Propagation (graphe déclaratif)
    # ------------------------------------------------------------------
    async def _propager(
        self,
        event: FreezeEvent,
        source_type: FreezeCible,
        source_id: UUID,
        now: datetime,
        niveau: int,
        visited: set[tuple[str, str]] | None = None,
        max_depth: int = 5,
    ) -> list[FreezeTarget]:
        if niveau > max_depth:
            return []
        visited = visited or set()
        key = (source_type.value, str(source_id))
        if key in visited:
            return []
        visited.add(key)

        # Récupérer les règles actives pour ce type source
        rules = (
            await self.db.execute(
                select(FreezeCascadeRule).where(FreezeCascadeRule.source_type == source_type)
            )
        ).scalars().all()

        nouveaux: list[FreezeTarget] = []
        for rule in rules:
            cibles_ids = await self._cibles_liees(source_type, source_id, rule.cible_type)
            for cid in cibles_ids:
                k2 = (rule.cible_type.value, str(cid))
                if k2 in visited:
                    continue
                visited.add(k2)
                t = FreezeTarget(
                    freeze_event_id=event.id,
                    tenant_id=self.tenant_id,
                    cible_type=rule.cible_type,
                    cible_id=cid,
                    niveau_profondeur=niveau,
                    raison=f"cascade_{source_type.value}",
                    statut=FreezeStatut.ACTIF,
                    gele_at=now,
                )
                self.db.add(t)
                nouveaux.append(t)
                # Récursion
                sous = await self._propager(
                    event, rule.cible_type, cid, now,
                    niveau=niveau + 1, visited=visited, max_depth=max_depth,
                )
                nouveaux.extend(sous)
        return nouveaux

    async def _cibles_liees(
        self, source_type: FreezeCible, source_id: UUID, cible_type: FreezeCible
    ) -> list[UUID]:
        """Résolution des cibles liées selon le couple (source → cible)."""
        if source_type == FreezeCible.TENANT and cible_type == FreezeCible.USER:
            rows = await self.db.execute(
                select(User.id).where(User.tenant_id == source_id)
            )
            return [r[0] for r in rows.all()]

        if source_type == FreezeCible.TENANT and cible_type == FreezeCible.ECRITURE:
            rows = await self.db.execute(
                select(Ecriture.id).where(
                    Ecriture.tenant_id == source_id,
                    Ecriture.statut != EcritureStatut.GELEE,
                )
            )
            return [r[0] for r in rows.all()]

        if source_type == FreezeCible.TENANT and cible_type == FreezeCible.MM_TRANSACTION:
            rows = await self.db.execute(
                select(MmTransaction.id).where(
                    MmTransaction.tenant_id == source_id,
                    MmTransaction.statut_rappro != MMStatut.GELE,
                )
            )
            return [r[0] for r in rows.all()]

        if source_type == FreezeCible.USER and cible_type == FreezeCible.ECRITURE:
            rows = await self.db.execute(
                select(Ecriture.id).where(
                    Ecriture.tenant_id == self.tenant_id,
                    Ecriture.created_by == source_id,
                    Ecriture.statut != EcritureStatut.GELEE,
                )
            )
            return [r[0] for r in rows.all()]

        if source_type == FreezeCible.ECRITURE and cible_type == FreezeCible.MM_TRANSACTION:
            rows = await self.db.execute(
                select(MmTransaction.id).where(
                    MmTransaction.ecriture_id == source_id,
                    MmTransaction.statut_rappro != MMStatut.GELE,
                )
            )
            return [r[0] for r in rows.all()]

        if source_type == FreezeCible.MM_TRANSACTION and cible_type == FreezeCible.ECRITURE:
            ecriture_id = await self.db.scalar(
                select(MmTransaction.ecriture_id).where(MmTransaction.id == source_id)
            )
            return [ecriture_id] if ecriture_id else []

        return []

    # ------------------------------------------------------------------
    # Effets métier (UPDATE tables)
    # ------------------------------------------------------------------
    async def _appliquer_effets(
        self,
        cible_type: FreezeCible,
        cible_id: UUID,
        targets: list[FreezeTarget],
        now: datetime,
    ) -> None:
        if cible_type == FreezeCible.TENANT:
            await self.db.execute(
                update(Tenant).where(Tenant.id == cible_id).values(statut=TenantStatut.GELE)
            )
            await self.db.execute(
                update(User)
                .where(User.tenant_id == cible_id, User.statut == UserStatut.ACTIF)
                .values(statut=UserStatut.GELE)
            )
            await self.db.execute(
                update(Ecriture)
                .where(
                    Ecriture.tenant_id == cible_id,
                    Ecriture.statut != EcritureStatut.GELEE,
                )
                .values(statut=EcritureStatut.GELEE)
            )
            await self.db.execute(
                update(MmTransaction)
                .where(
                    MmTransaction.tenant_id == cible_id,
                    MmTransaction.statut_rappro != MMStatut.GELE,
                )
                .values(statut_rappro=MMStatut.GELE)
            )
        elif cible_type == FreezeCible.USER:
            await self.db.execute(
                update(User).where(User.id == cible_id).values(statut=UserStatut.GELE)
            )
        elif cible_type == FreezeCible.ECRITURE:
            await self.db.execute(
                update(Ecriture)
                .where(Ecriture.id == cible_id)
                .values(statut=EcritureStatut.GELEE)
            )
        elif cible_type == FreezeCible.MM_TRANSACTION:
            await self.db.execute(
                update(MmTransaction)
                .where(MmTransaction.id == cible_id)
                .values(statut_rappro=MMStatut.GELE)
            )

        # Effets pour chaque cible de la cascade (hors racine déjà traitée)
        for t in targets:
            if t.cible_id == cible_id and t.cible_type == cible_type:
                continue
            if t.cible_type == FreezeCible.ECRITURE:
                await self.db.execute(
                    update(Ecriture)
                    .where(Ecriture.id == t.cible_id)
                    .values(statut=EcritureStatut.GELEE)
                )
            elif t.cible_type == FreezeCible.MM_TRANSACTION:
                await self.db.execute(
                    update(MmTransaction)
                    .where(MmTransaction.id == t.cible_id)
                    .values(statut_rappro=MMStatut.GELE)
                )
            elif t.cible_type == FreezeCible.USER:
                await self.db.execute(
                    update(User).where(User.id == t.cible_id).values(statut=UserStatut.GELE)
                )

    # ------------------------------------------------------------------
    # Cache chaud (tenant_freeze_state)
    # ------------------------------------------------------------------
    async def _sync_cache_chaud(
        self, event: FreezeEvent, targets: list[FreezeTarget]
    ) -> None:
        # Détermine si le tenant entier est gelé
        gele = event.cible_type == FreezeCible.TENANT and event.statut == FreezeStatut.ACTIF
        if not gele:
            return

        now = datetime.now(timezone.utc)
        existing = await self.db.scalar(
            select(TenantFreezeState).where(TenantFreezeState.tenant_id == self.tenant_id)
        )
        if existing is None:
            self.db.add(
                TenantFreezeState(
                    tenant_id=self.tenant_id,
                    gele=True,
                    freeze_event_id=event.id,
                    motif=event.motif,
                    gele_at=now,
                )
            )
        else:
            existing.gele = True
            existing.freeze_event_id = event.id
            existing.motif = event.motif
            existing.gele_at = now
