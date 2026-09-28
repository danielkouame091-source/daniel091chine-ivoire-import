"""Tests de la bascule automatique en lecture seule."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models.enums import SubStatut
from app.models.subscription import Subscription

pytestmark = pytest.mark.integration


class TestSubscriptionStatus:
    async def test_abonnement_actif_non_readonly(
        self, db_session, tenant, admin_user, active_subscription
    ):
        from app.dependencies.subscription import get_subscription_status
        from types import SimpleNamespace

        request = SimpleNamespace(state=SimpleNamespace())
        status = await get_subscription_status(
            request=request,
            current_user=admin_user,
            db=db_session,
        )
        assert status is not None
        assert status.force_read_only is False
        assert status.jours_restants > 0
        assert status.est_expiree is False

    async def test_abonnement_expire_force_readonly(
        self, db_session, tenant, admin_user, expired_subscription
    ):
        from app.dependencies.subscription import get_subscription_status
        from types import SimpleNamespace

        request = SimpleNamespace(state=SimpleNamespace())
        status = await get_subscription_status(
            request=request,
            current_user=admin_user,
            db=db_session,
        )
        assert status is not None
        assert status.force_read_only is True
        assert status.est_expiree is True

    async def test_abonnement_inexistant_force_readonly(
        self, db_session, tenant, admin_user
    ):
        """Aucun abonnement → read-only d'office."""
        from app.dependencies.subscription import get_subscription_status
        from types import SimpleNamespace

        request = SimpleNamespace(state=SimpleNamespace())
        status = await get_subscription_status(
            request=request,
            current_user=admin_user,
            db=db_session,
        )
        assert status is not None
        assert status.force_read_only is True
        assert status.statut == SubStatut.EXPRE

    async def test_grace_periode_active(
        self, db_session, tenant, admin_user, plan_starter
    ):
        """Abonnement expiré il y a 3 jours, grâce 7 jours → read-only=True (notre règle)."""
        now = datetime.now(timezone.utc)
        sub = Subscription(
            tenant_id=tenant.id,
            plan_id=plan_starter.id,
            statut=SubStatut.ACTIF,
            periode_debut=now - timedelta(days=33),
            periode_fin=now - timedelta(days=3),
            grace_jours=7,
            montant_xof=15000,
            devise="XOF",
            mode_paiement="wave",
        )
        db_session.add(sub)
        await db_session.flush()

        from app.dependencies.subscription import get_subscription_status
        from types import SimpleNamespace

        request = SimpleNamespace(state=SimpleNamespace())
        status = await get_subscription_status(
            request=request,
            current_user=admin_user,
            db=db_session,
        )
        # Dans notre implémentation, grace ne suspend PAS le read-only
        assert status.est_en_grace is True
        assert status.force_read_only is True
