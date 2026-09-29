"""
Tests du module Portail Client / Fournisseur.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.schemas.portal import (
    ClientPortalDashboard,
    OnlinePaymentInitIn,
    PortalInviteIn,
    SupplierInvoiceSubmissionIn,
)
from app.services.portal_auth_service import PortalAuthService
from app.services.portal_client_service import PortalClientService
from app.services.portal_supplier_service import PortalSupplierService

pytestmark = pytest.mark.integration


# ─── Fixtures ───────────────────────────────────────────────────────────────
@pytest.fixture
async def invited_client(db_session, tenant, admin_user, customer):
    """Crée et active un utilisateur portail client."""
    auth = PortalAuthService(db_session, tenant.id, admin_user.id)
    result = await auth.inviter(PortalInviteIn(
        email="client.portal@test.ci",
        prenom="Kouassi",
        nom="Konan",
        type_utilisateur="client",
        customer_id=customer.id,
    ))
    # Récupérer le portal_user
    from app.models.portal import PortalUser
    pu = await db_session.scalar(
        select(PortalUser).where(PortalUser.id == result["portal_user_id"])
    )
    # Activer directement (sans passer par le token)
    pu.statut = "actif"
    pu.password_hash = "fake_hash_for_tests"
    await db_session.flush()
    return pu


# ═════════════════════════════════════════════════════════════════════════════
# TESTS INVITATION & AUTH
# ═════════════════════════════════════════════════════════════════════════════
class TestInvitation:
    async def test_inviter_client(self, db_session, tenant, admin_user, customer):
        auth = PortalAuthService(db_session, tenant.id, admin_user.id)
        result = await auth.inviter(PortalInviteIn(
            email="nouveau.client@test.ci",
            prenom="Awa",
            nom="Diallo",
            type_utilisateur="client",
            customer_id=customer.id,
        ))
        assert "portal_user_id" in result
        assert "invitation_id" in result
        assert result["email"] == "nouveau.client@test.ci"

    async def test_invitation_sans_customer_rejete(self, db_session, tenant, admin_user):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            PortalInviteIn(
                email="x@test.ci",
                prenom="Test",
                nom="User",
                type_utilisateur="client",
                # customer_id manquant
            )

    async def test_double_invitation_rejetee(self, db_session, tenant, admin_user, customer):
        auth = PortalAuthService(db_session, tenant.id, admin_user.id)
        await auth.inviter(PortalInviteIn(
            email="doublon@test.ci",
            prenom="A", nom="B",
            type_utilisateur="client",
            customer_id=customer.id,
        ))
        # Activer le compte
        from app.models.portal import PortalUser
        pu = await db_session.scalar(
            select(PortalUser).where(PortalUser.email == "doublon@test.ci")
        )
        pu.statut = "actif"
        await db_session.flush()

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            await auth.inviter(PortalInviteIn(
                email="doublon@test.ci",
                prenom="A", nom="B",
                type_utilisateur="client",
                customer_id=customer.id,
            ))
        assert exc.value.status_code == 409


# ═════════════════════════════════════════════════════════════════════════════
# TESTS DASHBOARD CLIENT
# ═════════════════════════════════════════════════════════════════════════════
class TestClientDashboard:
    async def test_dashboard_vide(self, db_session, tenant, invited_client):
        svc = PortalClientService(db_session, tenant.id, invited_client)
        dash = await svc.dashboard()
        assert dash.customer_id == invited_client.customer_id
        assert dash.solde_du_xof == 0
        assert dash.nb_factures_impayees == 0

    async def test_dashboard_avec_factures(
        self, db_session, tenant, admin_user, invited_client,
        customer, plan_comptable_ci,
    ):
        # Créer une facture
        from app.schemas.sale import CustomerInvoiceCreate, CustomerInvoiceLineCreate
        from app.services.sale_service import SaleService

        sale_svc = SaleService(db_session, tenant.id, admin_user.id)
        inv = await sale_svc.creer_facture(CustomerInvoiceCreate(
            customer_id=customer.id,
            date_facture=date.today(),
            lignes=[CustomerInvoiceLineCreate(
                designation="Test portal",
                quantite=1,
                prix_unitaire_ht=500_000,
                taux_tva=0.18,
                compte_produit="701100",
            )],
        ))
        await sale_svc.valider_facture(inv.id)
        await db_session.flush()

        svc = PortalClientService(db_session, tenant.id, invited_client)
        dash = await svc.dashboard()
        assert dash.solde_du_xof == 590_000
        assert dash.nb_factures_impayees == 1


# ═════════════════════════════════════════════════════════════════════════════
# TESTS ISOLATION (CRITIQUE)
# ═════════════════════════════════════════════════════════════════════════════
class TestIsolation:
    async def test_client_ne_voit_que_ses_factures(
        self, db_session, tenant, admin_user,
        invited_client, customer, plan_comptable_ci,
    ):
        """
        ⚠️ TEST CRITIQUE : un client A ne doit JAMAIS voir les factures d'un client B.
        """
        # Créer un 2e client
        from app.models.sale import Customer
        from app.schemas.sale import CustomerInvoiceCreate, CustomerInvoiceLineCreate
        from app.services.sale_service import SaleService

        customer_b = Customer(
            tenant_id=tenant.id,
            code="CLI-B",
            raison_sociale="Client B",
            delai_paiement_jours=30,
            mode_encaissement_defaut="virement",
        )
        db_session.add(customer_b)
        await db_session.flush()

        sale_svc = SaleService(db_session, tenant.id, admin_user.id)
        # Facture pour client A
        inv_a = await sale_svc.creer_facture(CustomerInvoiceCreate(
            customer_id=customer.id,
            date_facture=date.today(),
            lignes=[CustomerInvoiceLineCreate(
                designation="Facture A", quantite=1, prix_unitaire_ht=100_000,
                taux_tva=0.18, compte_produit="701100",
            )],
        ))
        # Facture pour client B
        inv_b = await sale_svc.creer_facture(CustomerInvoiceCreate(
            customer_id=customer_b.id,
            date_facture=date.today(),
            lignes=[CustomerInvoiceLineCreate(
                designation="Facture B", quantite=1, prix_unitaire_ht=200_000,
                taux_tva=0.18, compte_produit="701100",
            )],
        ))
        await db_session.flush()

        # Utilisateur portail du client A essaie de voir la facture B
        svc = PortalClientService(db_session, tenant.id, invited_client)
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            await svc.get_facture_detail(inv_b.id)
        assert exc.value.status_code == 404   # Non trouvée → pas de fuite

        # Peut voir sa propre facture
        result = await svc.get_facture_detail(inv_a.id)
        assert result["numero"] == inv_a.numero


# ═════════════════════════════════════════════════════════════════════════════
# TESTS FOURNISSEUR
# ═════════════════════════════════════════════════════════════════════════════
class TestSupplierPortal:
    async def test_soumettre_facture(
        self, db_session, tenant, admin_user, supplier
    ):
        # Créer un utilisateur portail fournisseur
        auth = PortalAuthService(db_session, tenant.id, admin_user.id)
        result = await auth.inviter(PortalInviteIn(
            email="fourn@test.ci",
            prenom="Ali",
            nom="Traoré",
            type_utilisateur="fournisseur",
            supplier_id=supplier.id,
        ))
        from app.models.portal import PortalUser
        pu = await db_session.scalar(
            select(PortalUser).where(PortalUser.id == result["portal_user_id"])
        )
        pu.statut = "actif"
        await db_session.flush()

        # Soumettre une facture
        svc = PortalSupplierService(db_session, tenant.id, pu)
        submission = await svc.soumettre_facture(SupplierInvoiceSubmissionIn(
            numero_fournisseur="FF-2025-001",
            date_facture=date.today(),
            montant_ht=1_000_000,
            montant_tva=180_000,
            fichier_url="https://files.test/ff-001.pdf",
            fichier_nom="facture.pdf",
            lignes=[],
        ))
        assert submission.numero_fournisseur == "FF-2025-001"
        assert submission.montant_ttc == 1_180_000
        assert submission.statut == "soumise"
