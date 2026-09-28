"""Tests du flow d'authentification."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


class TestAuthFlow:
    async def test_login_sans_mfa(self, client, admin_user):
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": admin_user.email, "password": "MotDePasse!2025"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["access_token"]
        assert data["refresh_token"]
        assert data["mfa_required"] is False

    async def test_login_mauvais_password(self, client, admin_user):
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": admin_user.email, "password": "mauvais"},
        )
        assert r.status_code == 401

    async def test_login_email_inexistant(self, client):
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": "inconnu@test.ci", "password": "MotDePasse!2025"},
        )
        assert r.status_code == 401

    async def test_me_avec_token(self, client, admin_user, auth_headers):
        r = await client.get(
            "/api/v1/auth/me",
            headers=auth_headers(admin_user),
        )
        assert r.status_code == 200
        data = r.json()
        assert data["email"] == admin_user.email
        assert data["is_founder"] is False

    async def test_me_sans_token(self, client):
        r = await client.get("/api/v1/auth/me")
        assert r.status_code == 401

    async def test_cockpit_refuse_non_founder(self, client, admin_user, auth_headers):
        r = await client.get(
            "/api/v1/cockpit/tenants",
            headers=auth_headers(admin_user),
        )
        # 404 volontaire (ne pas révéler le cockpit)
        assert r.status_code == 404

    async def test_cockpit_accepte_founder(
        self, client, founder_user, auth_headers
    ):
        r = await client.get(
            "/api/v1/cockpit/tenants",
            headers=auth_headers(founder_user),
        )
        assert r.status_code == 200
