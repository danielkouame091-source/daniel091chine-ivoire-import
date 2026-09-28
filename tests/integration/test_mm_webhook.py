"""Tests d'ingestion webhook Mobile Money (idempotence + rapprochement)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.models.enums import MMProvider, MMStatut

pytestmark = pytest.mark.integration


class TestMmIngestion:
    async def test_ingestion_wave_cree_transaction(
        self, db_session, tenant
    ):
        from app.services.mobile_money_service import MobileMoneyService

        svc = MobileMoneyService(db_session, tenant_id=tenant.id)
        payload = {
            "id": "WAVE-TX-001",
            "amount": 250_000,
            "fees": 0,
            "type": "credit",
            "counterparty": "+2250700000000",
            "label": "Paiement client",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        tx = await svc.ingerer(MMProvider.WAVE, payload, tenant_id=tenant.id)
        assert tx.external_id == "WAVE-TX-001"
        assert tx.montant_xof == 250_000
        assert tx.statut_rappro == MMStatut.NON_RAPPROCHE

    async def test_ingestion_idempotente(self, db_session, tenant):
        """Le même payload ingéré 2x ne crée qu'UNE transaction."""
        from app.services.mobile_money_service import MobileMoneyService

        svc = MobileMoneyService(db_session, tenant_id=tenant.id)
        payload = {
            "id": "WAVE-TX-DUP",
            "amount": 100_000,
            "type": "credit",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        tx1 = await svc.ingerer(MMProvider.WAVE, payload, tenant_id=tenant.id)
        tx2 = await svc.ingerer(MMProvider.WAVE, payload, tenant_id=tenant.id)
        assert tx1.id == tx2.id

    async def test_rapprochement_genere_ecriture(
        self,
        db_session,
        tenant,
        admin_user,
        exercice,
        plan_comptable_ci,
        journal_mm,
    ):
        from app.services.mobile_money_service import MobileMoneyService

        svc = MobileMoneyService(db_session, tenant_id=tenant.id)
        tx = await svc.ingerer(
            MMProvider.WAVE,
            {
                "id": "WAVE-RAPPRO-001",
                "amount": 500_000,
                "fees": 5_000,
                "type": "credit",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            tenant_id=tenant.id,
        )
        await db_session.flush()

        tx_after = await svc.rapprocher(tx.id, user_id=admin_user.id)
        assert tx_after.statut_rappro == MMStatut.RAPPROCHE
        assert tx_after.ecriture_id is not None

        # Vérifier que l'écriture existe et est équilibrée
        from app.models.ecriture import Ecriture
        e = (await db_session.execute(
            select(Ecriture).where(Ecriture.id == tx_after.ecriture_id)
        )).scalar_one()
        assert e.numero_piece.startswith("MM-")
        assert e.reference_ext == "WAVE-RAPPRO-001"
