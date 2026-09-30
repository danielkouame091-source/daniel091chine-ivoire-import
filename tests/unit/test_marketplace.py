"""
Tests du module Marketplace & Extensions.
"""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.core.marketplace_syscohada import (
    REVENUE_SHARE_MTECH_PCT,
    StatutExtension,
    StatutInstallation,
    StatutPublisher,
)
from app.schemas.marketplace import (
    ExtensionCreateIn,
    ExtensionUpdateIn,
    InstallationCreateIn,
    PublisherRegisterIn,
    ReviewCreateIn,
)
from app.services.marketplace_service import MarketplaceService

pytestmark = pytest.mark.integration


# ─── Fixtures ───────────────────────────────────────────────────────────────
@pytest.fixture
async def publisher(db_session, admin_user):
    svc = MarketplaceService(db_session, admin_user.id)
    return await svc.enregistrer_publisher(PublisherRegisterIn(
        slug="mtech-labs",
        nom="MTech Labs",
        email="dev@mtechlabs.ci",
        type_publisher="entreprise",
        pays="CI",
    ))


@pytest.fixture
async def extension(db_session, publisher, admin_user):
    svc = MarketplaceService(db_session, admin_user.id)
    return await svc.creer_extension(publisher.id, ExtensionCreateIn(
        slug="wave-bank-sync",
        nom="Wave Bank Synchronisation",
        resume="Synchronise les transactions Wave vers MTech",
        description="Description complète du plugin. " * 5,
        type_extension="integration",
        categorie="banque",
        version_actuelle="1.0.0",
        modele_tarification="abonnement",
        prix_mensuel_xof=5000,
        permissions=["read:clients", "read:tresorerie", "write:tresorerie"],
        hooks=["invoice.created", "payment.received"],
        cgu_url="https://mtech.ci/wave-bank/cgu",
        politique_confidentialite_url="https://mtech.ci/wave-bank/privacy",
    ))


# ═════════════════════════════════════════════════════════════════════════════
# TESTS PUBLISHERS
# ═════════════════════════════════════════════════════════════════════════════
class TestPublishers:
    async def test_register_publisher(self, publisher):
        assert publisher.slug == "mtech-labs"
        assert publisher.statut == StatutPublisher.EN_ATTENTE

    async def test_slug_duplique_rejete(self, db_session, publisher, admin_user):
        from fastapi import HTTPException
        svc = MarketplaceService(db_session, admin_user.id)
        with pytest.raises(HTTPException) as exc:
            await svc.enregistrer_publisher(PublisherRegisterIn(
                slug="mtech-labs", nom="Dup", email="other@test.ci",
            ))
        assert exc.value.status_code == 409

    async def test_verification_publisher(self, db_session, publisher, admin_user):
        svc = MarketplaceService(db_session, admin_user.id)
        verified = await svc.verifier_publisher(publisher.id, "certifie")
        assert verified.statut == StatutPublisher.VERIFIE
        assert verified.certification == "certifie"


# ═════════════════════════════════════════════════════════════════════════════
# TESTS EXTENSIONS
# ═════════════════════════════════════════════════════════════════════════════
class TestExtensions:
    async def test_creation_extension(self, extension):
        assert extension.slug == "wave-bank-sync"
        assert extension.statut == StatutExtension.BROUILLON
        assert extension.prix_mensuel_xof == 5000

    async def test_workflow_soumission_approbation(
        self, db_session, extension, admin_user
    ):
        svc = MarketplaceService(db_session, admin_user.id)
        submitted = await svc.soumettre_extension(extension.id)
        assert submitted.statut == StatutExtension.EN_REVISION

        approved = await svc.approuver_extension(extension.id, "certifie")
        assert approved.statut == StatutExtension.APPROUVEE
        assert approved.certification == "certifie"

    async def test_soumission_sans_cgu_rejetee(
        self, db_session, publisher, admin_user
    ):
        from fastapi import HTTPException
        svc = MarketplaceService(db_session, admin_user.id)
        ext = await svc.creer_extension(publisher.id, ExtensionCreateIn(
            slug="test-incomplete", nom="Test", resume="Test",
            description="Description longue " * 5,
            type_extension="plugin", categorie="autre",
            version_actuelle="1.0.0", modele_tarification="gratuit",
        ))
        with pytest.raises(HTTPException) as exc:
            await svc.soumettre_extension(ext.id)
        assert exc.value.status_code == 400


# ═════════════════════════════════════════════════════════════════════════════
# TESTS INSTALLATIONS
# ═════════════════════════════════════════════════════════════════════════════
class TestInstallations:
    async def test_installation_extension_gratuite(
        self, db_session, extension, tenant, admin_user
    ):
        svc = MarketplaceService(db_session, admin_user.id)
        await svc.approuver_extension(extension.id)
        await db_session.flush()

        inst = await svc.installer(tenant.id, InstallationCreateIn(
            extension_id=extension.id,
            config={},
            accepter_cgu=True,
        ))
        assert inst.statut == StatutInstallation.ACTIVE

    async def test_installation_extension_payante_genere_transaction(
        self, db_session, extension, tenant, admin_user
    ):
        svc = MarketplaceService(db_session, admin_user.id)
        await svc.approuver_extension(extension.id)
        await db_session.flush()

        inst = await svc.installer(tenant.id, InstallationCreateIn(
            extension_id=extension.id,
            config={},
            mode_paiement="wave",
            accepter_cgu=True,
        ))
        assert inst.prix_paye_xof == 5000

        # Vérifier la transaction
        from sqlalchemy import select
        from app.models.marketplace import MarketplaceTransaction
        tx = await db_session.scalar(
            select(MarketplaceTransaction).where(
                MarketplaceTransaction.installation_id == inst.id
            )
        )
        assert tx is not None
        # Commission MTech = 30% de 5000 = 1500
        assert tx.commission_mtech_xof == int(5000 * REVENUE_SHARE_MTECH_PCT / 100)
        assert tx.montant_publisher_xof == 5000 - tx.commission_mtech_xof

    async def test_installation_double_rejetee(
        self, db_session, extension, tenant, admin_user
    ):
        from fastapi import HTTPException
        svc = MarketplaceService(db_session, admin_user.id)
        await svc.approuver_extension(extension.id)
        await db_session.flush()

        await svc.installer(tenant.id, InstallationCreateIn(
            extension_id=extension.id, config={}, accepter_cgu=True,
        ))

        with pytest.raises(HTTPException) as exc:
            await svc.installer(tenant.id, InstallationCreateIn(
                extension_id=extension.id, config={}, accepter_cgu=True,
            ))
        assert exc.value.status_code == 409

    async def test_cgu_non_acceptees_rejetees(
        self, db_session, extension, tenant, admin_user
    ):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            InstallationCreateIn(
                extension_id=extension.id,
                config={},
                accepter_cgu=False,
            )


# ═════════════════════════════════════════════════════════════════════════════
# TESTS REVIEWS
# ═════════════════════════════════════════════════════════════════════════════
class TestReviews:
    async def test_laisser_avis(
        self, db_session, extension, tenant, admin_user
    ):
        svc = MarketplaceService(db_session, admin_user.id)
        await svc.approuver_extension(extension.id)
        await db_session.flush()

        await svc.installer(tenant.id, InstallationCreateIn(
            extension_id=extension.id, config={}, accepter_cgu=True,
        ))

        review = await svc.laisser_avis(tenant.id, extension.id, ReviewCreateIn(
            note=5,
            titre="Excellent plugin",
            commentaire="Fonctionne parfaitement pour mes transactions Wave",
        ))
        assert review.note == 5
        assert review.auteur_nom is not None

    async def test_avis_sans_installation_rejete(
        self, db_session, extension, tenant, admin_user
    ):
        from fastapi import HTTPException
        svc = MarketplaceService(db_session, admin_user.id)
        await svc.approuver_extension(extension.id)
        await db_session.flush()

        with pytest.raises(HTTPException) as exc:
            await svc.laisser_avis(tenant.id, extension.id, ReviewCreateIn(
                note=5, commentaire="Test",
            ))
        assert exc.value.status_code == 400

    async def test_recalcul_note_moyenne(
        self, db_session, extension, tenant, admin_user
    ):
        svc = MarketplaceService(db_session, admin_user.id)
        await svc.approuver_extension(extension.id)
        await db_session.flush()

        await svc.installer(tenant.id, InstallationCreateIn(
            extension_id=extension.id, config={}, accepter_cgu=True,
        ))
        await svc.laisser_avis(tenant.id, extension.id, ReviewCreateIn(
            note=4, commentaire="Bien",
        ))
        await db_session.flush()

        await db_session.refresh(extension)
        assert float(extension.note_moyenne) == 4.0
        assert extension.nb_avis == 1


# ═════════════════════════════════════════════════════════════════════════════
# TESTS HOOK EXECUTION
# ═════════════════════════════════════════════════════════════════════════════
class TestHookExecution:
    async def test_execution_hook_webhook(
        self, db_session, extension, tenant, admin_user
    ):
        from app.services.plugin_runtime_service import PluginRuntimeService

        svc = MarketplaceService(db_session, admin_user.id)
        await svc.approuver_extension(extension.id)
        await db_session.flush()

        inst = await svc.installer(tenant.id, InstallationCreateIn(
            extension_id=extension.id, config={},
            webhook_url="https://plugin.external.ci/webhook",
            accepter_cgu=True,
        ))
        await db_session.flush()

        runtime = PluginRuntimeService(db_session)

        with patch("httpx.AsyncClient.post") as mock_post:
            mock_resp = AsyncMock()
            mock_resp.status_code = 200
            mock_resp.text = "OK"
            mock_post.return_value = mock_resp

            result = await runtime.executer_hook(
                inst.id, tenant.id,
                "invoice.created",
                {"numero": "FAC-001", "montant": 500_000},
            )

        assert result["ok"] is True
        assert result["status"] == 200
