"""
Service Mobile Money — ingestion webhooks (Wave, Orange, MTN, Moov)
+ rapprochement automatique avec génération d'écriture SYSCOHADA.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import (
    EcritureSource,
    MMProvider,
    MMSens,
    MMStatut,
)
from app.models.mobile_money import MmTransaction
from app.models.tenant import Tenant
from app.schemas.ecriture import EcritureCreate, LigneIn
from app.services.audit_service import AuditService
from app.services.syscohada_service import SyscohadaService

# Comptes SYSCOHADA par défaut (configurable par tenant à terme)
COMPTE_TRESORERIE_MM = "521100"   # Banque — Mobile Money
COMPTE_ATTENTE = "471800"         # Compte d'attente (à ventiler)
COMPTE_FRAIS_BANCAIRES = "631800"


class MobileMoneyService:
    def __init__(self, db: AsyncSession, tenant_id: UUID | None = None) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self.audit = AuditService(db)

    # ------------------------------------------------------------------
    # Ingestion webhook (idempotente)
    # ------------------------------------------------------------------
    async def ingerer(
        self,
        provider: MMProvider,
        payload: dict[str, Any],
        tenant_id: UUID,
    ) -> MmTransaction:
        external_id = str(payload.get("id") or payload.get("transaction_id") or "")
        if not external_id:
            raise HTTPException(400, "external_id manquant dans le payload")

        # Idempotence : ON CONFLICT DO NOTHING sur (tenant, provider, external_id)
        existing = await self.db.scalar(
            select(MmTransaction).where(
                MmTransaction.tenant_id == tenant_id,
                MmTransaction.provider == provider,
                MmTransaction.external_id == external_id,
            )
        )
        if existing:
            return existing

        sens = MMSens.DEBIT if str(payload.get("type", "credit")) == "debit" else MMSens.CREDIT

        tx = MmTransaction(
            tenant_id=tenant_id,
            provider=provider,
            external_id=external_id,
            montant_xof=int(payload.get("amount", 0)),
            frais_xof=int(payload.get("fees", 0) or 0),
            sens=sens,
            numero_tiers=payload.get("counterparty") or payload.get("msisdn"),
            libelle=payload.get("label") or payload.get("payer_message"),
            horodatage=self._parse_dt(payload.get("timestamp")),
            raw_payload=payload,
            statut_rappro=MMStatut.NON_RAPPROCHE,
        )
        self.db.add(tx)
        try:
            await self.db.flush()
        except IntegrityError:
            await self.db.rollback()
            # Relire (race condition webhook)
            return await self.db.scalar(
                select(MmTransaction).where(
                    MmTransaction.tenant_id == tenant_id,
                    MmTransaction.provider == provider,
                    MmTransaction.external_id == external_id,
                )
            )

        await self.audit.log(
            tenant_id=tenant_id,
            user_id=None,
            action="MM_INGEST",
            ressource="mm_transaction",
            ressource_id=tx.id,
            payload={
                "provider": provider.value,
                "external_id": external_id,
                "montant": tx.montant_xof,
            },
        )
        return tx

    # ------------------------------------------------------------------
    # Rapprochement automatique
    # ------------------------------------------------------------------
    async def rapprocher(self, mm_tx_id: UUID, user_id: UUID) -> MmTransaction:
        tx = await self.db.scalar(
            select(MmTransaction).where(
                MmTransaction.id == mm_tx_id,
                MmTransaction.tenant_id == self.tenant_id,
            )
        )
        if tx is None:
            raise HTTPException(404, "Transaction MM introuvable")
        if tx.statut_rappro in (MMStatut.RAPPROCHE, MMStatut.GELE):
            return tx

        # Génération écriture SYSCOHADA (partie double)
        lignes: list[LigneIn] = []
        if tx.sens == MMSens.CREDIT:
            lignes.append(LigneIn(compte=COMPTE_TRESORERIE_MM, debit=tx.montant_xof))
            lignes.append(LigneIn(compte=COMPTE_ATTENTE, credit=tx.montant_xof))
        else:
            lignes.append(LigneIn(compte=COMPTE_ATTENTE, debit=tx.montant_xof))
            lignes.append(LigneIn(compte=COMPTE_TRESORERIE_MM, credit=tx.montant_xof))

        if tx.frais_xof > 0:
            lignes.append(LigneIn(compte=COMPTE_FRAIS_BANCAIRES, debit=tx.frais_xof))
            lignes.append(LigneIn(compte=COMPTE_TRESORERIE_MM, credit=tx.frais_xof))

        syscohada = SyscohadaService(self.db, self.tenant_id, user_id)
        ecriture = await syscohada.create(
            EcritureCreate(
                numero_piece=f"MM-{tx.provider.value.upper()}-{tx.external_id}",
                date_ecriture=tx.horodatage.date(),
                code_journal="MM",
                libelle=f"Mobile Money {tx.provider.value} — {tx.libelle or tx.external_id}",
                reference_ext=tx.external_id,
                source=EcritureSource.MOBILE_MONEY,
                lignes=lignes,
            )
        )

        tx.ecriture_id = ecriture.id
        tx.statut_rappro = MMStatut.RAPPROCHE
        tx.rapproche_at = datetime.now(timezone.utc)
        await self.db.flush()

        await self.audit.log(
            tenant_id=self.tenant_id,
            user_id=user_id,
            action="MM_RAPPROCHE",
            ressource="mm_transaction",
            ressource_id=tx.id,
            payload={"ecriture_id": str(ecriture.id)},
        )
        return tx

    # ------------------------------------------------------------------
    # Lecture
    # ------------------------------------------------------------------
    async def list(
        self,
        statut: MMStatut | None = None,
        provider: MMProvider | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[MmTransaction], int]:
        from sqlalchemy import func
        stmt = select(MmTransaction).where(MmTransaction.tenant_id == self.tenant_id)
        count_stmt = select(func.count(MmTransaction.id)).where(
            MmTransaction.tenant_id == self.tenant_id
        )
        if statut:
            stmt = stmt.where(MmTransaction.statut_rappro == statut)
            count_stmt = count_stmt.where(MmTransaction.statut_rappro == statut)
        if provider:
            stmt = stmt.where(MmTransaction.provider == provider)
            count_stmt = count_stmt.where(MmTransaction.provider == provider)

        stmt = stmt.order_by(MmTransaction.horodatage.desc()).limit(limit).offset(offset)
        rows = (await self.db.execute(stmt)).scalars().all()
        total = int(await self.db.scalar(count_stmt) or 0)
        return list(rows), total

    # ------------------------------------------------------------------
    # Internes
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_dt(value: Any) -> datetime:
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        if isinstance(value, str):
            try:
                dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
                return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            except ValueError:
                pass
        return datetime.now(timezone.utc)

    async def resoudre_tenant(self, provider: MMProvider, merchant_id: str) -> UUID | None:
        """
        Résolution du tenant depuis le merchant_id du provider.
        À terme : table `mm_merchant_mapping(tenant_id, provider, merchant_id)`.
        MVP : on cherche un tenant dont le slug correspond au merchant_id.
        """
        return await self.db.scalar(
            select(Tenant.id).where(Tenant.slug == merchant_id)
        )
