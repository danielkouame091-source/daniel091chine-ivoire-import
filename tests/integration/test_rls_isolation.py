"""
⚠️ TEST CRITIQUE : vérifie que les policies RLS PostgreSQL empêchent
réellement un tenant A de voir les données du tenant B, même en cas de bug
applicatif.

Ce test utilise une connexion directe avec un rôle NON-SUPERUSER, car les
superusers bypassent les policies RLS.
"""
from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select, text

from app.models.enums import EcritureStatut
from app.schemas.ecriture import EcritureCreate, LigneIn

pytestmark = [pytest.mark.integration, pytest.mark.rls]


async def _creer_ecriture_pour(
    db_session, tenant, admin_user, plan_comptable_ci, journal_ve, libelle
):
    from app.services.syscohada_service import SyscohadaService

    svc = SyscohadaService(db_session, tenant.id, admin_user.id)
    return await svc.create(EcritureCreate(
        date_ecriture=date(2025, 3, 15),
        code_journal="VE",
        libelle=libelle,
        lignes=[
            LigneIn(compte="521100", debit=100_000),
            LigneIn(compte="701100", credit=100_000),
        ],
    ))


class TestRLSIsolation:
    """
    ⚠️ Ces tests exigent un utilisateur PostgreSQL non-superuser, sinon RLS
    est bypassé. Le conftest doit se connecter avec un rôle dédié.
    """

    async def test_tenant_a_ne_voit_pas_ecritures_tenant_b(
        self,
        db_session,
        tenant,
        tenant_b,
        admin_user,
        admin_user_b,
        plan_comptable_ci,
        journal_ve,
    ):
        """Un tenant A ne doit JAMAIS voir les écritures du tenant B."""
        # Créer une écriture pour tenant A
        e_a = await _creer_ecriture_pour(
            db_session, tenant, admin_user, plan_comptable_ci, journal_ve, "TENANT_A"
        )
        # Créer une écriture pour tenant B
        e_b = await _creer_ecriture_pour(
            db_session, tenant_b, admin_user_b, plan_comptable_ci, journal_ve, "TENANT_B"
        )
        await db_session.commit()

        # ─── Simulation : on se positionne sur tenant A ─────────────────
        await db_session.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant.id)},
        )
        from app.models.ecriture import Ecriture

        rows = (await db_session.execute(
            select(Ecriture).where(Ecriture.tenant_id.in_([tenant.id, tenant_b.id]))
        )).scalars().all()

        # Le RLS ne doit laisser passer QUE les écritures de tenant A
        assert len(rows) == 1, f"RLS KO : {len(rows)} écritures visibles (attendu 1)"
        assert rows[0].id == e_a.id
        assert rows[0].id != e_b.id

    async def test_fondateur_voit_tout(
        self,
        db_session,
        tenant,
        tenant_b,
        admin_user,
        admin_user_b,
        plan_comptable_ci,
        journal_ve,
        founder_user,
    ):
        """Le fondateur (app.tenant_id NULL) voit tous les tenants."""
        await _creer_ecriture_pour(
            db_session, tenant, admin_user, plan_comptable_ci, journal_ve, "A"
        )
        await _creer_ecriture_pour(
            db_session, tenant_b, admin_user_b, plan_comptable_ci, journal_ve, "B"
        )
        await db_session.commit()

        # Positionnement "fondateur" : tenant_id vide → policy autorise
        await db_session.execute(
            text("SELECT set_config('app.tenant_id', '', true)")
        )
        from app.models.ecriture import Ecriture

        rows = (await db_session.execute(
            select(Ecriture).where(Ecriture.tenant_id.in_([tenant.id, tenant_b.id]))
        )).scalars().all()
        assert len(rows) == 2

    async def test_read_only_bloque_insertion(
        self,
        db_session,
        tenant,
        admin_user,
        plan_comptable_ci,
        journal_ve,
    ):
        """En mode read_only=true, l'INSERT est rejeté par RLS."""
        await db_session.execute(
            text(
                "SELECT set_config('app.tenant_id', :tid, true), "
                "       set_config('app.read_only', 'true', true)"
            ),
            {"tid": str(tenant.id)},
        )
        from app.models.ecriture import Ecriture

        # Tentative d'INSERT direct (contourne Pydantic)
        from datetime import datetime, timezone
        e = Ecriture(
            tenant_id=tenant.id,
            exercice_id=None,       # sera rempli plus bas
            journal_id=None,
            numero_piece="TEST-READONLY-001",
            date_ecriture=date(2025, 3, 15),
            date_saisie=datetime.now(timezone.utc),
            libelle="Tentative en read-only",
            source="manuel",
            statut=EcritureStatut.BROUILLON,
            hash_chain="a" * 64,
        )
        db_session.add(e)
        with pytest.raises(Exception) as exc:
            await db_session.flush()
        # RLS lève une erreur de policy (message variable selon PG)
        assert "policy" in str(exc.value).lower() or "row-level" in str(exc.value).lower()

    async def test_frozen_bloque_insertion(
        self,
        db_session,
        tenant,
        admin_user,
        plan_comptable_ci,
        journal_ve,
    ):
        """En mode frozen=true, l'INSERT est rejeté."""
        await db_session.execute(
            text(
                "SELECT set_config('app.tenant_id', :tid, true), "
                "       set_config('app.frozen', 'true', true)"
            ),
            {"tid": str(tenant.id)},
        )
        from app.models.ecriture import Ecriture
        from datetime import datetime, timezone

        e = Ecriture(
            tenant_id=tenant.id,
            exercice_id=None,
            journal_id=None,
            numero_piece="TEST-FROZEN-001",
            date_ecriture=date(2025, 3, 15),
            date_saisie=datetime.now(timezone.utc),
            libelle="Tentative gelée",
            source="manuel",
            statut=EcritureStatut.BROUILLON,
            hash_chain="b" * 64,
        )
        db_session.add(e)
        with pytest.raises(Exception):
            await db_session.flush()
