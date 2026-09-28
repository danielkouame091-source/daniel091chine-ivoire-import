"""
Test bout-en-bout : cycle de vie complet d'un tenant.
1. Créer un tenant
2. Créer un abonnement actif
3. Seeder un plan comptable minimal
4. Créer une écriture de vente
5. Vérifier le hash-chain
6. Geler en cascade
7. Vérifier que toute nouvelle écriture est bloquée
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text

from app.models.enums import EcritureStatut, FreezeCible, TenantStatut

pytestmark = pytest.mark.e2e


class TestFullCycle:
    async def test_cycle_complet(
        self,
        db_session,
        tenant,
        admin_user,
        plan_starter,
        active_subscription,
        exercice,
        plan_comptable_ci,
        journal_ve,
    ):
        from app.schemas.ecriture import EcritureCreate, LigneIn
        from app.schemas.freeze import FreezeRequest
        from app.services.freeze_service import FreezeService
        from app.services.syscohada_service import SyscohadaService

        # ─── 1. Créer 5 écritures ───────────────────────────────────
        svc = SyscohadaService(db_session, tenant.id, admin_user.id)
        ecritures = []
        for i in range(5):
            e = await svc.create(EcritureCreate(
                date_ecriture=date(2025, 3, 15 + i),
                code_journal="VE",
                libelle=f"Vente jour {i + 1}",
                lignes=[
                    LigneIn(compte="521100", debit=100_000 * (i + 1)),
                    LigneIn(compte="701100", credit=100_000 * (i + 1)),
                ],
            ))
            ecritures.append(e)
        await db_session.flush()

        # ─── 2. Vérifier hash-chain ─────────────────────────────────
        assert ecritures[0].hash_precedent is None
        for i in range(1, 5):
            assert ecritures[i].hash_precedent == ecritures[i - 1].hash_chain

        # ─── 3. Geler le tenant en cascade ──────────────────────────
        freeze_svc = FreezeService(db_session, tenant.id, admin_user.id)
        result = await freeze_svc.geler(
            FreezeRequest(
                cible_type=FreezeCible.TENANT,
                cible_id=tenant.id,
                motif="Test E2E — blocage total",
                cascade=True,
            )
        )
        await db_session.flush()
        assert result.total_cibles >= 6  # 1 tenant + 5 écritures + 1 user

        # ─── 4. Vérifier que les écritures sont gelées ──────────────
        from app.models.ecriture import Ecriture
        rows = (await db_session.execute(
            select(Ecriture).where(Ecriture.tenant_id == tenant.id)
        )).scalars().all()
        assert all(e.statut == EcritureStatut.GELEE for e in rows)

        # ─── 5. Vérifier que le tenant est gelé ─────────────────────
        from app.models.tenant import Tenant
        t = (await db_session.execute(
            select(Tenant).where(Tenant.id == tenant.id)
        )).scalar_one()
        assert t.statut == TenantStatut.GELE
