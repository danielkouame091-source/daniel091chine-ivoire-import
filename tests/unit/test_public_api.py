"""
Tests du module API publique & Webhooks sortants.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.core.public_api_syscohada import Scope, WebhookEvent
from app.schemas.public_api import (
    ApiClientCreate,
    ApiKeyCreate,
    WebhookEndpointCreate,
    WebhookTestIn,
)
from app.services.public_api_service import PublicApiService
from app.services.webhook_dispatch_service import WebhookDispatchService

pytestmark = pytest.mark.integration


# ═════════════════════════════════════════════════════════════════════════════
# FIXTURES
# ═════════════════════════════════════════════════════════════════════════════
@pytest.fixture
async def api_client(db_session, tenant, admin_user):
    svc = PublicApiService(db_session, tenant.id, admin_user.id)
    return await svc.creer_client(ApiClientCreate(
        code="partenaire-test",
        nom="Partenaire Test",
        type_client="partenaire",
        contact_email="dev@partenaire.ci",
        organisation="Partenaire CI",
    ))


# ═════════════════════════════════════════════════════════════════════════════
# TESTS CLIENTS API
# ═════════════════════════════════════════════════════════════════════════════
class TestClientsAPI:
    async def test_creation_client(self, api_client):
        assert api_client.code == "partenaire-test"
        assert api_client.type_client == "partenaire"
        assert api_client.actif is True

    async def test_code_duplique_rejete(self, db_session, tenant, admin_user, api_client):
        from fastapi import HTTPException
        svc = PublicApiService(db_session, tenant.id, admin_user.id)
        with pytest.raises(HTTPException) as exc:
            await svc.creer_client(ApiClientCreate(
                code="partenaire-test",
                nom="Dupliqué",
                type_client="partenaire",
            ))
        assert exc.value.status_code == 409


# ═════════════════════════════════════════════════════════════════════════════
# TESTS CLÉS API
# ═════════════════════════════════════════════════════════════════════════════
class TestApiKeys:
    async def test_creation_cle(self, db_session, tenant, admin_user, api_client):
        svc = PublicApiService(db_session, tenant.id, admin_user.id)
        key, key_plain = await svc.creer_cle(api_client.id, ApiKeyCreate(
            nom="Production key",
            scopes=[Scope.READ_ECRITURES, Scope.READ_CLIENTS],
        ))
        assert key.prefix.startswith("mtech_live_")
        assert key_plain.startswith("mtech_live_")
        assert key.statut == "active"
        assert key.scopes == [Scope.READ_ECRITURES, Scope.READ_CLIENTS]

    async def test_scope_invalide_rejete(self, db_session, tenant, admin_user, api_client):
        from fastapi import HTTPException
        svc = PublicApiService(db_session, tenant.id, admin_user.id)
        with pytest.raises(HTTPException) as exc:
            await svc.creer_cle(api_client.id, ApiKeyCreate(
                nom="Test", scopes=["invalid:scope"],
            ))
        assert exc.value.status_code == 400

    async def test_validation_cle(self, db_session, tenant, admin_user, api_client):
        svc = PublicApiService(db_session, tenant.id, admin_user.id)
        _, key_plain = await svc.creer_cle(api_client.id, ApiKeyCreate(
            nom="Test", scopes=[Scope.READ_CLIENTS],
        ))
        await db_session.flush()

        # Valider
        validated_key, validated_client = await svc.valider_cle(key_plain)
        assert validated_key.id is not None
        assert validated_client.id == api_client.id
        assert validated_key.derniere_utilisation_at is not None

    async def test_validation_cle_invalide(self, db_session, tenant, admin_user):
        from fastapi import HTTPException
        svc = PublicApiService(db_session, tenant.id, admin_user.id)
        with pytest.raises(HTTPException) as exc:
            await svc.valider_cle("mtech_live_invalid_key_xyz")
        assert exc.value.status_code == 401

    async def test_revocation_cle(self, db_session, tenant, admin_user, api_client):
        from fastapi import HTTPException
        svc = PublicApiService(db_session, tenant.id, admin_user.id)
        key, key_plain = await svc.creer_cle(api_client.id, ApiKeyCreate(
            nom="Test", scopes=[Scope.READ_CLIENTS],
        ))
        await db_session.flush()

        await svc.revoquer_cle(key.id, "Compromission suspectée")

        with pytest.raises(HTTPException) as exc:
            await svc.valider_cle(key_plain)
        assert exc.value.status_code == 403

    async def test_rotation_cle(self, db_session, tenant, admin_user, api_client):
        svc = PublicApiService(db_session, tenant.id, admin_user.id)
        ancienne, _ = await svc.creer_cle(api_client.id, ApiKeyCreate(
            nom="À roter", scopes=[Scope.READ_CLIENTS],
        ))
        await db_session.flush()

        from app.schemas.public_api import ApiKeyRotateIn
        nouvelle, _, key_plain = await svc.roter_cle(ancienne.id, ApiKeyRotateIn(
            grace_period_hours=24,
        ))
        assert nouvelle.id != ancienne.id
        assert nouvelle.remplace_cle_id == ancienne.id
        assert ancienne.remplacee_par_cle_id == nouvelle.id
        assert ancienne.expire_at is not None

    async def test_verifier_scope(self, db_session, tenant, admin_user, api_client):
        from fastapi import HTTPException
        svc = PublicApiService(db_session, tenant.id, admin_user.id)
        key, _ = await svc.creer_cle(api_client.id, ApiKeyCreate(
            nom="Test", scopes=[Scope.READ_CLIENTS],
        ))
        # OK
        svc.verifier_scope(key, Scope.READ_CLIENTS)
        # KO
        with pytest.raises(HTTPException) as exc:
            svc.verifier_scope(key, Scope.WRITE_ECRITURES)
        assert exc.value.status_code == 403


# ═════════════════════════════════════════════════════════════════════════════
# TESTS RATE LIMITING
# ═════════════════════════════════════════════════════════════════════════════
class TestRateLimit:
    async def test_rate_limit_non_atteint(self, db_session, tenant, admin_user, api_client):
        svc = PublicApiService(db_session, tenant.id, admin_user.id)
        # Ne doit pas lever
        await svc.verifier_rate_limit(api_client)

    async def test_rate_limit_atteint(self, db_session, tenant, admin_user, api_client):
        from fastapi import HTTPException
        from app.models.public_api import ApiUsageLog

        # Créer 100 logs récents
        now = datetime.now(timezone.utc)
        for i in range(100):
            db_session.add(ApiUsageLog(
                tenant_id=tenant.id,
                api_client_id=api_client.id,
                methode="GET",
                endpoint="/test",
                statut_http=200,
                created_at=now,
            ))
        # Modifier le rate limit pour test (client développeur = 100)
        api_client.type_client = "developpeur"
        api_client.rate_limit_per_minute = 50
        await db_session.flush()

        svc = PublicApiService(db_session, tenant.id, admin_user.id)
        with pytest.raises(HTTPException) as exc:
            await svc.verifier_rate_limit(api_client)
        assert exc.value.status_code == 429


# ═════════════════════════════════════════════════════════════════════════════
# TESTS WEBHOOKS ENDPOINTS
# ═════════════════════════════════════════════════════════════════════════════
class TestWebhookEndpoints:
    async def test_creation_endpoint(self, db_session, tenant, admin_user, api_client):
        svc = WebhookDispatchService(db_session, tenant.id, admin_user.id)
        endpoint, secret = await svc.creer_endpoint(api_client.id, WebhookEndpointCreate(
            nom="Webhook production",
            url="https://partenaire.ci/webhooks/mtech",
            events=[WebhookEvent.INVOICE_CREATED, WebhookEvent.PAYMENT_RECEIVED],
        ))
        assert endpoint.nom == "Webhook production"
        assert len(secret) > 20
        assert WebhookEvent.INVOICE_CREATED in endpoint.events

    async def test_evenement_invalide_rejete(self, db_session, tenant, admin_user, api_client):
        from fastapi import HTTPException
        svc = WebhookDispatchService(db_session, tenant.id, admin_user.id)
        with pytest.raises(HTTPException) as exc:
            await svc.creer_endpoint(api_client.id, WebhookEndpointCreate(
                nom="Test",
                url="https://test.ci/hook",
                events=["invalid.event"],
            ))
        assert exc.value.status_code == 400

    async def test_url_dupliquee_rejetee(self, db_session, tenant, admin_user, api_client):
        from fastapi import HTTPException
        svc = WebhookDispatchService(db_session, tenant.id, admin_user.id)
        await svc.creer_endpoint(api_client.id, WebhookEndpointCreate(
            nom="Test 1", url="https://test.ci/hook",
            events=[WebhookEvent.INVOICE_CREATED],
        ))
        with pytest.raises(HTTPException) as exc:
            await svc.creer_endpoint(api_client.id, WebhookEndpointCreate(
                nom="Test 2", url="https://test.ci/hook",
                events=[WebhookEvent.PAYMENT_RECEIVED],
            ))
        assert exc.value.status_code == 409


# ═════════════════════════════════════════════════════════════════════════════
# TESTS DISPATCH D'ÉVÉNEMENT
# ═════════════════════════════════════════════════════════════════════════════
class TestDispatch:
    async def test_dispatcher_evenement(self, db_session, tenant, admin_user, api_client):
        svc = WebhookDispatchService(db_session, tenant.id, admin_user.id)
        await svc.creer_endpoint(api_client.id, WebhookEndpointCreate(
            nom="Test",
            url="https://test.ci/hook",
            events=[WebhookEvent.INVOICE_CREATED],
        ))
        await db_session.flush()

        # Dispatcher
        deliveries = await svc.dispatcher_evenement(
            WebhookEvent.INVOICE_CREATED,
            {"numero": "FAC-001", "total_ttc": 1_180_000},
            source_type="customer_invoice",
        )
        assert len(deliveries) == 1
        assert deliveries[0].statut == "pending"
        assert deliveries[0].event_type == "invoice.created"

    async def test_dispatcher_aucun_endpoint_abonne(
        self, db_session, tenant, admin_user, api_client
    ):
        svc = WebhookDispatchService(db_session, tenant.id, admin_user.id)
        await svc.creer_endpoint(api_client.id, WebhookEndpointCreate(
            nom="Test",
            url="https://test.ci/hook",
            events=[WebhookEvent.INVOICE_CREATED],
        ))
        await db_session.flush()

        # Événement non souscrit
        deliveries = await svc.dispatcher_evenement(
            WebhookEvent.PAYMENT_RECEIVED,
            {"montant": 500_000},
        )
        assert len(deliveries) == 0


# ═════════════════════════════════════════════════════════════════════════════
# TESTS LIVRAISON (avec mock HTTP)
# ═════════════════════════════════════════════════════════════════════════════
class TestDelivery:
    async def test_livraison_succes(self, db_session, tenant, admin_user, api_client):
        svc = WebhookDispatchService(db_session, tenant.id, admin_user.id)
        ep, _ = await svc.creer_endpoint(api_client.id, WebhookEndpointCreate(
            nom="Test",
            url="https://test.ci/hook",
            events=[WebhookEvent.INVOICE_CREATED],
        ))
        await db_session.flush()

        deliveries = await svc.dispatcher_evenement(
            WebhookEvent.INVOICE_CREATED, {"numero": "FAC-001"},
        )
        await db_session.flush()
        delivery = deliveries[0]

        # Mock HTTP 200
        with patch("httpx.AsyncClient.post") as mock_post:
            mock_response = AsyncMock()
            mock_response.status_code = 200
            mock_response.text = "OK"
            mock_post.return_value = mock_response

            result = await svc.livrer(delivery.id)

        assert result["ok"] is True
        await db_session.refresh(delivery)
        assert delivery.statut == "success"
        assert delivery.response_status == 200

    async def test_livraison_echec_programme_retry(
        self, db_session, tenant, admin_user, api_client
    ):
        svc = WebhookDispatchService(db_session, tenant.id, admin_user.id)
        ep, _ = await svc.creer_endpoint(api_client.id, WebhookEndpointCreate(
            nom="Test", url="https://test.ci/hook",
            events=[WebhookEvent.INVOICE_CREATED],
        ))
        await db_session.flush()

        deliveries = await svc.dispatcher_evenement(
            WebhookEvent.INVOICE_CREATED, {"numero": "FAC-001"},
        )
        await db_session.flush()
        delivery = deliveries[0]

        # Mock HTTP 500
        with patch("httpx.AsyncClient.post") as mock_post:
            mock_response = AsyncMock()
            mock_response.status_code = 500
            mock_response.text = "Internal Error"
            mock_post.return_value = mock_response

            result = await svc.livrer(delivery.id)

        assert result["ok"] is False
        await db_session.refresh(delivery)
        assert delivery.statut == "retrying"
        assert delivery.nb_tentatives == 1
        assert delivery.prochaine_tentative_at is not None


# ═════════════════════════════════════════════════════════════════════════════
# TESTS SIGNATURE HMAC
# ═════════════════════════════════════════════════════════════════════════════
class TestSignature:
    def test_signature_deterministe(self):
        svc = WebhookDispatchService(None, None, None)
        payload = {"event": "test", "data": {"x": 1}}
        sig1 = svc._signer_payload(payload, 1700000000, "secret_hash")
        sig2 = svc._signer_payload(payload, 1700000000, "secret_hash")
        assert sig1 == sig2
        assert len(sig1) == 64   # SHA-256 hex

    def test_signature_varie_avec_timestamp(self):
        svc = WebhookDispatchService(None, None, None)
        payload = {"event": "test"}
        sig1 = svc._signer_payload(payload, 1700000000, "secret")
        sig2 = svc._signer_payload(payload, 1700000001, "secret")
        assert sig1 != sig2

    def test_signature_varie_avec_secret(self):
        svc = WebhookDispatchService(None, None, None)
        payload = {"event": "test"}
        sig1 = svc._signer_payload(payload, 1700000000, "secret1")
        sig2 = svc._signer_payload(payload, 1700000000, "secret2")
        assert sig1 != sig2


# ═════════════════════════════════════════════════════════════════════════════
# TESTS IDEMPOTENCE
# ═════════════════════════════════════════════════════════════════════════════
class TestIdempotence:
    async def test_save_et_get_idempotent(self, db_session, tenant, admin_user, api_client):
        svc = PublicApiService(db_session, tenant.id, admin_user.id)
        await svc.save_idempotent_response(
            api_client.id, "key-123", "/api/v1/public/invoices",
            201, {"id": "inv-1", "numero": "FAC-001"},
        )
        await db_session.flush()

        cached = await svc.get_idempotent_response(api_client.id, "key-123")
        assert cached is not None
        assert cached["status"] == 201
        assert cached["body"]["numero"] == "FAC-001"

    async def test_get_idempotent_inexistant(self, db_session, tenant, admin_user, api_client):
        svc = PublicApiService(db_session, tenant.id, admin_user.id)
        cached = await svc.get_idempotent_response(api_client.id, "unknown-key")
        assert cached is None
