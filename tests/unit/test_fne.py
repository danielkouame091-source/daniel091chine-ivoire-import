"""
Tests du module FNE (Facture Normalisée Électronique).

Couvre :
- Format de numérotation DGI
- Mapping modes de paiement
- Configuration FNE
- Certification (avec mock HTTP)
- Gestion des stickers
- Gestion des erreurs
"""
from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

from app.core.fne_syscohada import (
    MAP_MODE_PAIEMENT_FNE,
    FnePaymentMethod,
    FneStatut,
    formater_numero_fne,
)
from app.integrations.fne_client import FneApiError
from app.schemas.fne import FneCertificationRequest, FneConfigCreate
from app.services.fne_service import FneService

pytestmark = pytest.mark.integration


# ═════════════════════════════════════════════════════════════════════════════
# TESTS UNITAIRES (PURS)
# ═════════════════════════════════════════════════════════════════════════════
class TestNumeroFne:
    def test_format_facture_vente(self):
        n = formater_numero_fne("9606123E", 2025, 19)
        assert n == "9606123E25000000019"
        assert len(n) == 19

    def test_format_facture_avoir(self):
        n = formater_numero_fne("9606123E", 2025, 6, avoir=True)
        assert n == "A9606123E25000000006"
        assert n.startswith("A")

    def test_sequence_zero_padded(self):
        assert formater_numero_fne("NCC", 2025, 1).endswith("000000001")


class TestMappingPaiement:
    def test_wave_to_mobile_money(self):
        assert MAP_MODE_PAIEMENT_FNE["wave"] == FnePaymentMethod.MOBILE_MONEY

    def test_orange_to_mobile_money(self):
        assert MAP_MODE_PAIEMENT_FNE["orange_money"] == FnePaymentMethod.MOBILE_MONEY

    def test_especes_to_cash(self):
        assert MAP_MODE_PAIEMENT_FNE["especes"] == FnePaymentMethod.CASH

    def test_virement_to_transfer(self):
        assert MAP_MODE_PAIEMENT_FNE["virement"] == FnePaymentMethod.TRANSFER


# ═════════════════════════════════════════════════════════════════════════════
# FIXTURES
# ═════════════════════════════════════════════════════════════════════════════
@pytest.fixture
async def fne_config(db_session, tenant, admin_user):
    svc = FneService(db_session, tenant.id, admin_user.id)
    return await svc.creer_configuration(FneConfigCreate(
        ncc="9606123E",
        environnement="sandbox",
        base_url="https://www.services.fne.dgi.gouv.ci",
        api_key="test-api-key-12345",
        template_defaut="B2F",
    ))


@pytest.fixture
async def invoice_validee(
    db_session, tenant, admin_user, customer, plan_comptable_ci
):
    """Crée une facture validée prête à être certifiée."""
    from app.schemas.sale import CustomerInvoiceCreate, CustomerInvoiceLineCreate
    from app.services.sale_service import SaleService

    svc = SaleService(db_session, tenant.id, admin_user.id)
    inv = await svc.creer_facture(CustomerInvoiceCreate(
        customer_id=customer.id,
        date_facture=date(2025, 3, 15),
        lignes=[CustomerInvoiceLineCreate(
            designation="Sac de riz 50kg",
            quantite=50,
            prix_unitaire_ht=10_000,
            taux_tva=0.18,
            compte_produit="701100",
        )],
    ))
    await svc.valider_facture(inv.id)
    await db_session.flush()
    return inv


# ═════════════════════════════════════════════════════════════════════════════
# TESTS CONFIGURATION
# ═════════════════════════════════════════════════════════════════════════════
class TestFneConfig:
    async def test_creation_config(self, fne_config):
        assert fne_config.ncc == "9606123E"
        assert fne_config.active is True
        assert fne_config.environnement == "sandbox"

    async def test_get_config_active(self, db_session, tenant, admin_user, fne_config):
        svc = FneService(db_session, tenant.id, admin_user.id)
        config = await svc.get_configuration_active()
        assert config.id == fne_config.id

    async def test_get_config_absente_leve_404(self, db_session, tenant, admin_user):
        from fastapi import HTTPException
        svc = FneService(db_session, tenant.id, admin_user.id)
        with pytest.raises(HTTPException) as exc:
            await svc.get_configuration_active()
        assert exc.value.status_code == 404


# ═════════════════════════════════════════════════════════════════════════════
# TESTS CERTIFICATION (avec mock HTTP)
# ═════════════════════════════════════════════════════════════════════════════
class TestCertification:
    async def test_certification_succes(
        self, db_session, tenant, admin_user, fne_config,
        invoice_validee, plan_comptable_ci,
    ):
        """Mock une réponse FNE réussie."""
        # Injecter des stickers
        from app.models.fne import FneStickerBalance
        balance = await db_session.scalar(
            select(FneStickerBalance).where(FneStickerBalance.tenant_id == tenant.id)
        )
        if balance is None:
            balance = FneStickerBalance(tenant_id=tenant.id)
            db_session.add(balance)
        balance.balance_fne = 100
        balance.balance_total = 100
        await db_session.flush()

        # Réponse mockée
        mock_response = {
            "ncc": "9606123E",
            "reference": "9606123E25000000019",
            "token": "http://54.247.95.108/fr/verification/019465c1-3f61",
            "warning": False,
            "balance_sticker": 99,
            "invoice": {
                "id": "e2b2d8da-a532-4c08-9182-f5b428ca468d",
                "reference": "9606123E25000000019",
                "type": "invoice",
                "status": "paid",
            },
        }

        with patch("app.services.fne_service.get_fne_client") as mock_factory:
            mock_client = AsyncMock()
            mock_client.certifier_facture = AsyncMock(return_value=mock_response)
            mock_factory.return_value = mock_client

            svc = FneService(db_session, tenant.id, admin_user.id)
            result = await svc.certifier_facture(
                FneCertificationRequest(customer_invoice_id=invoice_validee.id)
            )

        assert result.success is True
        assert result.fne_invoice.fne_reference == "9606123E25000000019"
        assert result.fne_invoice.statut == "certifiee"
        assert result.qr_code_url is not None

    async def test_certification_solde_insuffisant(
        self, db_session, tenant, admin_user, fne_config,
        invoice_validee, plan_comptable_ci,
    ):
        """Solde de stickers à 0 → 402."""
        from app.models.fne import FneStickerBalance
        balance = await db_session.scalar(
            select(FneStickerBalance).where(FneStickerBalance.tenant_id == tenant.id)
        )
        if balance is None:
            balance = FneStickerBalance(tenant_id=tenant.id)
            db_session.add(balance)
        balance.balance_fne = 0
        balance.balance_total = 0
        await db_session.flush()

        from fastapi import HTTPException
        svc = FneService(db_session, tenant.id, admin_user.id)
        with pytest.raises(HTTPException) as exc:
            await svc.certifier_facture(
                FneCertificationRequest(customer_invoice_id=invoice_validee.id)
            )
        assert exc.value.status_code == 402
        assert "sticker" in str(exc.value.detail).lower()

    async def test_certification_idempotente(
        self, db_session, tenant, admin_user, fne_config,
        invoice_validee, plan_comptable_ci,
    ):
        """Certifier 2 fois la même facture → retourne l'existante."""
        from app.models.fne import FneInvoice, FneStickerBalance
        balance = await db_session.scalar(
            select(FneStickerBalance).where(FneStickerBalance.tenant_id == tenant.id)
        )
        if balance is None:
            balance = FneStickerBalance(tenant_id=tenant.id)
            db_session.add(balance)
        balance.balance_fne = 100
        balance.balance_total = 100
        await db_session.flush()

        # Insérer une facture déjà certifiée
        fne = FneInvoice(
            tenant_id=tenant.id,
            customer_invoice_id=invoice_validee.id,
            configuration_id=fne_config.id,
            fne_reference="9606123E25000000001",
            fne_id="existing-id",
            document_type="invoice",
            template="B2F",
            annee_edition=2025,
            statut="certifiee",
            qr_code_url="http://example.com/qr",
            numero_normalise="9606123E25000000001",
        )
        db_session.add(fne)
        await db_session.flush()

        svc = FneService(db_session, tenant.id, admin_user.id)
        result = await svc.certifier_facture(
            FneCertificationRequest(customer_invoice_id=invoice_validee.id)
        )
        assert result.success is True
        assert "déjà certifiée" in result.message.lower()
