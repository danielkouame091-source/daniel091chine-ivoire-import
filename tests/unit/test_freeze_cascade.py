"""Tests du protocole de gel en cascade."""
from __future__ import annotations

from datetime import date

import pytest

from app.models.enums import EcritureStatut, FreezeCible, FreezeStatut, TenantStatut, UserStatut
from app.schemas.ecriture import EcritureCreate, LigneIn
from app.schemas.freeze import FreezeRequest

pytestmark = pytest.mark.integration


async def _creer_ecriture(db_session, tenant, admin_user, plan_comptable_ci, journal_ve, montant=100_000):
    from app.services.syscohada_service import SyscohadaService

    svc = SyscohadaService(db_session, tenant.id, admin_user.id)
    return await svc.create(EcritureCreate(
        date_ecriture=date(2025, 3, 15),
        code_journal="VE",
        libelle=f"Vente {montant}",
        lignes=[
            LigneIn(compte="521100", debit=montant),
            LigneIn(compte="701100", credit=montant),
        ],
    ))


class TestFreezeCascade:
    async def test_gel_tenant_cascade_users(
        self,
        db_session,
        tenant,
        admin_user,
        exercice,
        plan_comptable_ci,
        journal_ve,
    ):
        from app.services.freeze_service import FreezeService
        from sqlalchemy import select
        from app.models.user import User

        # Crée 3 écritures
        for i in range(3):
            await _creer_ecriture(db_session, tenant, admin_user, plan_comptable_ci, journal_ve, 100_000 + i)

        svc = FreezeService(db_session, tenant.id, admin_user.id)
        result = await svc.geler(
            FreezeRequest(
                cible_type=FreezeCible.TENANT,
                cible_id=tenant.id,
                motif="Fraude suspectée — blocage immédiat",
                cascade=True,
            )
        )
        await db_session.flush()

        assert result.event.cible_type == FreezeCible.TENANT
        assert result.total_cibles >= 1

        # Vérifier que le tenant est gelé
        from app.models.tenant import Tenant
        t = (await db_session.execute(
            select(Tenant).where(Tenant.id == tenant.id)
        )).scalar_one()
        assert t.statut == TenantStatut.GELE

        # Vérifier que l'admin est gelé
        u = (await db_session.execute(
            select(User).where(User.id == admin_user.id)
        )).scalar_one()
        assert u.statut == UserStatut.GELE

    async def test_gel_ecriture_unique(
        self,
        db_session,
        tenant,
        admin_user,
        exercice,
        plan_comptable_ci,
        journal_ve,
    ):
        from app.services.freeze_service import FreezeService
        from sqlalchemy import select
        from app.models.ecriture import Ecriture

        e = await _creer_ecriture(db_session, tenant, admin_user, plan_comptable_ci, journal_ve)

        svc = FreezeService(db_session, tenant.id, admin_user.id)
        await svc.geler(
            FreezeRequest(
                cible_type=FreezeCible.ECRITURE,
                cible_id=e.id,
                motif="Écriture suspecte",
                cascade=False,
            )
        )
        await db_session.flush()

        e_after = (await db_session.execute(
            select(Ecriture).where(Ecriture.id == e.id)
        )).scalar_one()
        assert e_after.statut == EcritureStatut.GELEE

    async def test_levee_gel(
        self,
        db_session,
        tenant,
        admin_user,
        exercice,
        plan_comptable_ci,
        journal_ve,
    ):
        from app.services.freeze_service import FreezeService

        svc = FreezeService(db_session, tenant.id, admin_user.id)
        result = await svc.geler(
            FreezeRequest(
                cible_type=FreezeCible.TENANT,
                cible_id=tenant.id,
                motif="Test levée",
                cascade=True,
            )
        )
        await db_session.flush()

        event = await svc.lever(result.event.id, "Fausse alerte")
        assert event.statut == FreezeStatut.LEVE
