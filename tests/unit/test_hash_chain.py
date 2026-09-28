"""Tests de la chaîne cryptographique (audit + écritures)."""
from __future__ import annotations

import pytest

from app.core.security import chain_hash, sha256_hex

pytestmark = pytest.mark.unit


class TestChainHash:
    def test_premier_hash_sans_precedent(self):
        h = chain_hash(None, "contenu1")
        assert h == sha256_hex("GENESIS|contenu1")

    def test_hash_chaine_depend_du_precedent(self):
        h1 = chain_hash(None, "contenu1")
        h2 = chain_hash(h1, "contenu2")
        h3 = chain_hash(h2, "contenu3")

        # Si on altère contenu1, toute la chaîne change
        h1_altere = chain_hash(None, "contenu1_ALTERE")
        h2_altere = chain_hash(h1_altere, "contenu2")
        assert h2_altere != h2
        assert h3 != chain_hash(h2_altere, "contenu3")

    def test_hash_deterministe(self):
        assert chain_hash(None, "abc") == chain_hash(None, "abc")

    def test_hash_sensible_au_contenu(self):
        assert chain_hash(None, "abc") != chain_hash(None, "abd")


@pytest.mark.integration
class TestAuditChainDB:
    async def test_chaine_audit_intacte(self, db_session, tenant, admin_user):
        from app.services.audit_service import AuditService

        svc = AuditService(db_session)
        await svc.log(
            tenant_id=tenant.id,
            user_id=admin_user.id,
            action="TEST_1",
            ressource="test",
            payload={"n": 1},
        )
        await svc.log(
            tenant_id=tenant.id,
            user_id=admin_user.id,
            action="TEST_2",
            ressource="test",
            payload={"n": 2},
        )
        await svc.log(
            tenant_id=tenant.id,
            user_id=admin_user.id,
            action="TEST_3",
            ressource="test",
            payload={"n": 3},
        )
        await db_session.flush()

        valide, nb = await svc.verify_chain(tenant.id)
        assert valide is True
        assert nb == 3

    async def test_chaine_audit_alteree_detectee(
        self, db_session, tenant, admin_user
    ):
        from sqlalchemy import update
        from app.models.audit import AuditLog
        from app.services.audit_service import AuditService

        svc = AuditService(db_session)
        await svc.log(
            tenant_id=tenant.id,
            user_id=admin_user.id,
            action="TEST_1",
            ressource="test",
            payload={"n": 1},
        )
        entry = await svc.log(
            tenant_id=tenant.id,
            user_id=admin_user.id,
            action="TEST_2",
            ressource="test",
            payload={"n": 2},
        )
        await db_session.flush()

        # Altération volontaire (attaque)
        await db_session.execute(
            update(AuditLog)
            .where(AuditLog.id == entry.id)
            .values(payload={"n": 999})
        )
        await db_session.flush()

        valide, _ = await svc.verify_chain(tenant.id)
        assert valide is False
