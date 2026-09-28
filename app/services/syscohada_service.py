"""
Service SYSCOHADA — moteur d'écritures en partie double.
Contient : création, validation, hash-chain, lettrage, ventilation exercice.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import chain_hash
from app.models.ecriture import Ecriture, EcritureLigne
from app.models.enums import EcritureSource, EcritureStatut
from app.models.exercice import Exercice
from app.models.journal import Journal
from app.models.plan_comptable import PlanComptable
from app.schemas.ecriture import EcritureCreate, EcritureFilter, EcritureUpdate
from app.services.audit_service import AuditService
from app.services.journal_service import JournalService
from app.services.plan_comptable_service import PlanComptableService


class SyscohadaService:
    def __init__(self, db: AsyncSession, tenant_id: UUID, user_id: UUID) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.journaux = JournalService(db, tenant_id)
        self.plan = PlanComptableService(db, tenant_id)
        self.audit = AuditService(db)

    # ------------------------------------------------------------------
    # Création d'écriture
    # ------------------------------------------------------------------
    async def create(self, data: EcritureCreate) -> Ecriture:
        # 1. Journal
        journal = await self.journaux.get_by_code(data.code_journal)

        # 2. Exercice correspondant à la date
        exercice = await self._resolve_exercice(data.date_ecriture)
        if exercice.cloture:
            raise HTTPException(400, f"Exercice {exercice.libelle} clôturé")

        # 3. Résolution de tous les comptes en une requête
        comptes_codes = [l.compte for l in data.lignes]
        rows = (
            await self.db.execute(
                select(PlanComptable).where(
                    PlanComptable.tenant_id == self.tenant_id,
                    PlanComptable.compte.in_(comptes_codes),
                    PlanComptable.actif.is_(True),
                )
            )
        ).scalars().all()
        map_comptes = {c.compte: c for c in rows}

        manquants = [code for code in comptes_codes if code not in map_comptes]
        if manquants:
            raise HTTPException(
                400, f"Comptes SYSCOHADA introuvables : {', '.join(sorted(set(manquants)))}"
            )

        # 4. Numéro de pièce auto si absent
        numero_piece = data.numero_piece or await self._generer_numero_piece(
            journal.code, data.date_ecriture
        )

        # 5. Hash-chain : chaîner à la dernière écriture du tenant
        precedent = await self.db.scalar(
            select(Ecriture.hash_chain)
            .where(Ecriture.tenant_id == self.tenant_id)
            .order_by(Ecriture.created_at.desc())
            .limit(1)
        )
        contenu = self._serialize_for_hash(data, numero_piece)
        hash_chain = chain_hash(precedent, contenu)

        # 6. Création entête + lignes
        ecriture = Ecriture(
            tenant_id=self.tenant_id,
            exercice_id=exercice.id,
            journal_id=journal.id,
            numero_piece=numero_piece,
            date_ecriture=data.date_ecriture,
            date_saisie=datetime.now(timezone.utc),
            libelle=data.libelle,
            reference_ext=data.reference_ext,
            source=data.source,
            statut=EcritureStatut.VALIDEE,
            validee_at=datetime.now(timezone.utc),
            validee_par=self.user_id,
            hash_chain=hash_chain,
            hash_precedent=precedent,
            created_by=self.user_id,
        )
        self.db.add(ecriture)
        await self.db.flush()

        for i, ligne in enumerate(data.lignes, start=1):
            self.db.add(
                EcritureLigne(
                    ecriture_id=ecriture.id,
                    tenant_id=self.tenant_id,
                    compte_id=map_comptes[ligne.compte].id,
                    libelle=ligne.libelle or data.libelle,
                    debit_xof=ligne.debit,
                    credit_xof=ligne.credit,
                    ordre=i,
                )
            )
        await self.db.flush()

        # 7. Audit
        await self.audit.log(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            action="ECRITURE_CREATE",
            ressource="ecriture",
            ressource_id=ecriture.id,
            payload={
                "numero_piece": numero_piece,
                "total_debit": sum(l.debit for l in data.lignes),
                "total_credit": sum(l.credit for l in data.lignes),
                "hash_chain": hash_chain,
            },
        )

        # 8. Recharger avec relations pour la réponse
        return await self.get(ecriture.id)

    # ------------------------------------------------------------------
    # Lecture
    # ------------------------------------------------------------------
    async def get(self, ecriture_id: UUID) -> Ecriture:
        obj = await self.db.scalar(
            select(Ecriture).where(
                Ecriture.id == ecriture_id,
                Ecriture.tenant_id == self.tenant_id,
            )
        )
        if obj is None:
            raise HTTPException(404, "Écriture introuvable")
        # Forcer le chargement des lignes
        await self.db.refresh(obj, ["lignes"])
        return obj

    async def list(
        self, filters: EcritureFilter, limit: int = 100, offset: int = 0
    ) -> tuple[list[Ecriture], int]:
        stmt = select(Ecriture).where(Ecriture.tenant_id == self.tenant_id)
        count_stmt = select(func.count(Ecriture.id)).where(
            Ecriture.tenant_id == self.tenant_id
        )

        if filters.date_debut:
            stmt = stmt.where(Ecriture.date_ecriture >= filters.date_debut)
            count_stmt = count_stmt.where(Ecriture.date_ecriture >= filters.date_debut)
        if filters.date_fin:
            stmt = stmt.where(Ecriture.date_ecriture <= filters.date_fin)
            count_stmt = count_stmt.where(Ecriture.date_ecriture <= filters.date_fin)
        if filters.statut:
            stmt = stmt.where(Ecriture.statut == filters.statut)
            count_stmt = count_stmt.where(Ecriture.statut == filters.statut)
        if filters.source:
            stmt = stmt.where(Ecriture.source == filters.source)
            count_stmt = count_stmt.where(Ecriture.source == filters.source)
        if filters.numero_piece:
            stmt = stmt.where(Ecriture.numero_piece.ilike(f"%{filters.numero_piece}%"))
            count_stmt = count_stmt.where(
                Ecriture.numero_piece.ilike(f"%{filters.numero_piece}%")
            )
        if filters.journal_code:
            journal = await self.db.scalar(
                select(Journal).where(
                    Journal.tenant_id == self.tenant_id,
                    Journal.code == filters.journal_code,
                )
            )
            if journal is None:
                return [], 0
            stmt = stmt.where(Ecriture.journal_id == journal.id)
            count_stmt = count_stmt.where(Ecriture.journal_id == journal.id)
        if filters.compte:
            sub = select(EcritureLigne.ecriture_id).join(
                PlanComptable, PlanComptable.id == EcritureLigne.compte_id
            ).where(
                EcritureLigne.tenant_id == self.tenant_id,
                PlanComptable.compte == filters.compte,
            )
            stmt = stmt.where(Ecriture.id.in_(sub))
            count_stmt = count_stmt.where(Ecriture.id.in_(sub))

        stmt = stmt.order_by(Ecriture.date_ecriture.desc(), Ecriture.created_at.desc())
        stmt = stmt.limit(limit).offset(offset)

        rows = (await self.db.execute(stmt)).scalars().all()
        total = int(await self.db.scalar(count_stmt) or 0)
        return list(rows), total

    # ------------------------------------------------------------------
    # Mise à jour (brouillon uniquement)
    # ------------------------------------------------------------------
    async def update(self, ecriture_id: UUID, data: EcritureUpdate) -> Ecriture:
        obj = await self.get(ecriture_id)
        if obj.statut != EcritureStatut.BROUILLON:
            raise HTTPException(
                400, f"Écriture {obj.statut} — seule une écriture brouillon est modifiable"
            )

        if data.libelle is not None:
            obj.libelle = data.libelle
        if data.reference_ext is not None:
            obj.reference_ext = data.reference_ext

        if data.lignes is not None:
            comptes_codes = [l.compte for l in data.lignes]
            rows = (
                await self.db.execute(
                    select(PlanComptable).where(
                        PlanComptable.tenant_id == self.tenant_id,
                        PlanComptable.compte.in_(comptes_codes),
                        PlanComptable.actif.is_(True),
                    )
                )
            ).scalars().all()
            map_comptes = {c.compte: c for c in rows}
            manquants = [c for c in comptes_codes if c not in map_comptes]
            if manquants:
                raise HTTPException(400, f"Comptes introuvables : {manquants}")

            # Supprimer les anciennes lignes
            for ligne in list(obj.lignes):
                await self.db.delete(ligne)
            await self.db.flush()

            for i, ligne in enumerate(data.lignes, start=1):
                self.db.add(
                    EcritureLigne(
                        ecriture_id=obj.id,
                        tenant_id=self.tenant_id,
                        compte_id=map_comptes[ligne.compte].id,
                        libelle=ligne.libelle or obj.libelle,
                        debit_xof=ligne.debit,
                        credit_xof=ligne.credit,
                        ordre=i,
                    )
                )

        await self.db.flush()
        await self.audit.log(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            action="ECRITURE_UPDATE",
            ressource="ecriture",
            ressource_id=obj.id,
        )
        return await self.get(obj.id)

    # ------------------------------------------------------------------
    # Validation (brouillon → validée)
    # ------------------------------------------------------------------
    async def validate(self, ecriture_id: UUID) -> Ecriture:
        obj = await self.get(ecriture_id)
        if obj.statut != EcritureStatut.BROUILLON:
            raise HTTPException(400, "Seule une écriture brouillon peut être validée")
        if not obj.est_equilibree:
            raise HTTPException(
                400,
                f"Écriture déséquilibrée : D={obj.total_debit} C={obj.total_credit}",
            )
        obj.statut = EcritureStatut.VALIDEE
        obj.validee_at = datetime.now(timezone.utc)
        obj.validee_par = self.user_id
        await self.db.flush()
        await self.audit.log(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            action="ECRITURE_VALIDATE",
            ressource="ecriture",
            ressource_id=obj.id,
        )
        return obj

    # ------------------------------------------------------------------
    # Lettrage (rapprochement bancaire / tiers)
    # ------------------------------------------------------------------
    async def lettrer(
        self, ligne_ids: list[UUID], code: str | None = None
    ) -> str:
        if len(ligne_ids) < 2:
            raise HTTPException(400, "Le lettrage nécessite au moins 2 lignes")

        lignes = (
            await self.db.execute(
                select(EcritureLigne).where(
                    EcritureLigne.id.in_(ligne_ids),
                    EcritureLigne.tenant_id == self.tenant_id,
                )
            )
        ).scalars().all()
        if len(lignes) != len(ligne_ids):
            raise HTTPException(404, "Une ou plusieurs lignes introuvables")

        total_d = sum(l.debit_xof for l in lignes)
        total_c = sum(l.credit_xof for l in lignes)
        if total_d != total_c:
            raise HTTPException(
                400, f"Lettrage déséquilibré : D={total_d} C={total_c}"
            )

        code_final = code or f"L{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        now = datetime.now(timezone.utc)
        for l in lignes:
            l.lettrage_code = code_final
            l.lettrage_at = now
        await self.db.flush()

        await self.audit.log(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            action="ECRITURE_LETTRAGE",
            ressource="ecriture_ligne",
            payload={"code": code_final, "nb_lignes": len(lignes)},
        )
        return code_final

    # ------------------------------------------------------------------
    # Internes
    # ------------------------------------------------------------------
    async def _resolve_exercice(self, d: date) -> Exercice:
        obj = await self.db.scalar(
            select(Exercice).where(
                Exercice.tenant_id == self.tenant_id,
                Exercice.date_debut <= d,
                Exercice.date_fin >= d,
            )
        )
        if obj is None:
            raise HTTPException(
                400, f"Aucun exercice comptable ne couvre la date {d.isoformat()}"
            )
        return obj

    async def _generer_numero_piece(self, code_journal: str, d: date) -> str:
        prefix = f"{code_journal}-{d.year}-"
        last = await self.db.scalar(
            select(func.max(Ecriture.numero_piece)).where(
                Ecriture.tenant_id == self.tenant_id,
                Ecriture.numero_piece.like(f"{prefix}%"),
            )
        )
        if last is None:
            seq = 1
        else:
            try:
                seq = int(last.split("-")[-1]) + 1
            except (ValueError, IndexError):
                seq = 1
        return f"{prefix}{seq:05d}"

    @staticmethod
    def _serialize_for_hash(data: EcritureCreate, numero_piece: str) -> str:
        lignes = "|".join(
            f"{l.compte}:{l.debit}:{l.credit}" for l in data.lignes
        )
        return f"{numero_piece}|{data.date_ecriture.isoformat()}|{data.libelle}|{lignes}"
