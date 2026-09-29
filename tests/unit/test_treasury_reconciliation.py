"""
Tests du module Trésorerie & Rapprochement bancaire.

Couvre :
- Import CSV/OFX
- Matching automatique (montant exact, score, tolérance)
- Détection frais bancaires
- État de rapprochement formel
- Position consolidée multi-comptes
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO

import pytest
from fastapi import UploadFile

from app.schemas.treasury import (
    RapprochementAutoRequest,
    TreasuryAccountCreate,
)
from app.services.treasury_service import TreasuryService

pytestmark = pytest.mark.integration


# ─── Fixtures locales ───────────────────────────────────────────────────────
@pytest.fixture
async def treasury_account(db_session, tenant, admin_user):
    svc = TreasuryService(db_session, tenant.id, admin_user.id)
    return await svc.creer_compte(TreasuryAccountCreate(
        code="BNQ-SGCI",
        libelle="SGCI Compte courant",
        type_compte="banque",
        compte_comptable="521000",
        compte_principal=True,
    ))


# ═════════════════════════════════════════════════════════════════════════════
# TESTS COMPTE
# ═════════════════════════════════════════════════════════════════════════════
class TestTreasuryAccount:
    async def test_creation_compte(self, db_session, treasury_account):
        assert treasury_account.code == "BNQ-SGCI"
        assert treasury_account.compte_comptable == "521000"
        assert treasury_account.solde_comptable == 0
        assert treasury_account.compte_principal is True


# ═════════════════════════════════════════════════════════════════════════════
# TESTS IMPORT CSV
# ═════════════════════════════════════════════════════════════════════════════
class TestImportCSV:
    async def test_import_csv_simple(
        self, db_session, tenant, admin_user, treasury_account
    ):
        """Import d'un CSV basique avec 3 lignes."""
        csv_content = """date;libelle;debit;credit;reference
15/03/2025;Virement client KONE;;500000;VIR-001
16/03/2025;Frais bancaires;2500;;FRAIS-001
17/03/2025;Achat fournisseur;120000;;ACH-001
""".encode("utf-8")

        file = UploadFile(
            filename="releve.csv",
            file=BytesIO(csv_content),
        )

        svc = TreasuryService(db_session, tenant.id, admin_user.id)
        stmt = await svc.importer_releve(
            treasury_account_id=treasury_account.id,
            file=file,
            format_source="csv",
        )
        await db_session.flush()

        assert stmt.nb_lignes == 3
        assert stmt.solde_cloture == 500_000 - 2_500 - 120_000  # 377 500

    async def test_import_doublon_rejete(
        self, db_session, tenant, admin_user, treasury_account
    ):
        """Le même fichier ne peut pas être importé 2 fois."""
        from fastapi import HTTPException

        csv_content = b"date;libelle;debit;credit\n15/03/2025;Test;;1000\n"

        svc = TreasuryService(db_session, tenant.id, admin_user.id)

        file1 = UploadFile(filename="r.csv", file=BytesIO(csv_content))
        await svc.importer_releve(treasury_account.id, file1, "csv")
        await db_session.flush()

        file2 = UploadFile(filename="r.csv", file=BytesIO(csv_content))
        with pytest.raises(HTTPException) as exc:
            await svc.importer_releve(treasury_account.id, file2, "csv")
        assert exc.value.status_code == 409


# ═════════════════════════════════════════════════════════════════════════════
# TESTS RAPPROCHEMENT AUTO
# ═════════════════════════════════════════════════════════════════════════════
class TestRapprochementAuto:
    async def _setup_ecriture_client(
        self, db_session, tenant, admin_user, plan_comptable_ci, amount: int, d: date
    ):
        """Crée une écriture comptable d'encaissement client."""
        from app.schemas.ecriture import EcritureCreate, LigneIn
        from app.services.syscohada_service import SyscohadaService

        # Créer un journal BQ
        from app.models.enums import JournalType
        from app.models.journal import Journal
        from sqlalchemy import select
        existing = await db_session.scalar(
            select(Journal).where(Journal.tenant_id == tenant.id, Journal.code == "BQ")
        )
        if not existing:
            db_session.add(Journal(
                tenant_id=tenant.id,
                code="BQ",
                libelle="Journal banque",
                type_journal=JournalType.BANQUE,
            ))
            await db_session.flush()

        svc = SyscohadaService(db_session, tenant.id, admin_user.id)
        return await svc.create(EcritureCreate(
            date_ecriture=d,
            code_journal="BQ",
            libelle=f"Encaissement client {amount}",
            lignes=[
                LigneIn(compte="521000", debit=amount),
                LigneIn(compte="411100", credit=amount),
            ],
        ))

    async def test_rapprochement_montant_exact(
        self, db_session, tenant, admin_user,
        treasury_account, plan_comptable_ci,
    ):
        """Une ligne bancaire crédit 500 000 matche une écriture compta débit 500 000."""
        today = date.today()

        # 1. Créer l'écriture comptable
        await self._setup_ecriture_client(
            db_session, tenant, admin_user, plan_comptable_ci, 500_000, today
        )
        await db_session.flush()

        # 2. Importer un relevé correspondant
        csv_content = f"""date;libelle;debit;credit;reference
{today.strftime('%d/%m/%Y')};VIR CLIENT KONE;;500000;VIR-001
""".encode("utf-8")

        svc = TreasuryService(db_session, tenant.id, admin_user.id)
        file = UploadFile(filename="r.csv", file=BytesIO(csv_content))
        stmt = await svc.importer_releve(treasury_account.id, file, "csv")
        await db_session.flush()

        # 3. Rapprochement auto
        result = await svc.rapprocher_automatique(
            RapprochementAutoRequest(statement_id=stmt.id)
        )

        assert result.nb_rapprochees_auto == 1
        assert result.nb_ecarts == 0

    async def test_ecart_non_rapproche(
        self, db_session, tenant, admin_user,
        treasury_account, plan_comptable_ci,
    ):
        """Une ligne bancaire sans correspondance → ECART."""
        today = date.today()
        csv_content = f"""date;libelle;debit;credit
{today.strftime('%d/%m/%Y')};VIR INCONNU;;999999
""".encode("utf-8")

        svc = TreasuryService(db_session, tenant.id, admin_user.id)
        file = UploadFile(filename="r.csv", file=BytesIO(csv_content))
        stmt = await svc.importer_releve(treasury_account.id, file, "csv")
        await db_session.flush()

        result = await svc.rapprocher_automatique(
            RapprochementAutoRequest(statement_id=stmt.id)
        )
        assert result.nb_rapprochees_auto == 0
        assert result.nb_ecarts == 1

    async def test_detection_frais_bancaires(
        self, db_session, tenant, admin_user,
        treasury_account, plan_comptable_ci,
    ):
        """Une ligne 'FRAIS BANCAIRES' génère une écriture 631800."""
        today = date.today()
        csv_content = f"""date;libelle;debit;credit
{today.strftime('%d/%m/%Y')};Frais bancaires trimestriels;2500;
""".encode("utf-8")

        svc = TreasuryService(db_session, tenant.id, admin_user.id)
        file = UploadFile(filename="r.csv", file=BytesIO(csv_content))
        stmt = await svc.importer_releve(treasury_account.id, file, "csv")
        await db_session.flush()

        result = await svc.rapprocher_automatique(
            RapprochementAutoRequest(
                statement_id=stmt.id,
                comptabiliser_frais=True,
            )
        )

        assert result.nb_frais_bancaires == 1
        assert result.nb_ecarts == 0

        # Vérifier que l'écriture a été créée
        from sqlalchemy import select
        from app.models.treasury import BankStatementLine
        line = (await db_session.execute(
            select(BankStatementLine).where(BankStatementLine.statement_id == stmt.id)
        )).scalar_one()
        assert line.ecriture_id is not None
        assert line.statut_rapprochement == "frais_bancaire"


# ═════════════════════════════════════════════════════════════════════════════
# TESTS ÉTAT DE RAPPROCHEMENT
# ═════════════════════════════════════════════════════════════════════════════
class TestEtatRapprochement:
    async def test_etat_equilibre(
        self, db_session, tenant, admin_user,
        treasury_account, plan_comptable_ci,
    ):
        """État équilibré quand solde compta = solde bancaire."""
        today = date.today()

        # Créer écriture 100 000 débit banque
        from app.schemas.ecriture import EcritureCreate, LigneIn
        from app.services.syscohada_service import SyscohadaService
        from app.models.enums import JournalType
        from app.models.journal import Journal
        from sqlalchemy import select

        existing = await db_session.scalar(
            select(Journal).where(Journal.tenant_id == tenant.id, Journal.code == "BQ")
        )
        if not existing:
            db_session.add(Journal(
                tenant_id=tenant.id, code="BQ", libelle="BQ",
                type_journal=JournalType.BANQUE,
            ))
            await db_session.flush()

        sys_svc = SyscohadaService(db_session, tenant.id, admin_user.id)
        await sys_svc.create(EcritureCreate(
            date_ecriture=today, code_journal="BQ", libelle="Alim banque",
            lignes=[
                LigneIn(compte="521000", debit=100_000),
                LigneIn(compte="411100", credit=100_000),
            ],
        ))
        await db_session.flush()

        # Relevé avec solde final 100 000
        csv_content = f"""date;libelle;debit;credit
{today.strftime('%d/%m/%Y')};VIR CLIENT;;100000
""".encode("utf-8")

        svc = TreasuryService(db_session, tenant.id, admin_user.id)
        file = UploadFile(filename="r.csv", file=BytesIO(csv_content))
        stmt = await svc.importer_releve(treasury_account.id, file, "csv")
        await db_session.flush()

        etat = await svc.generer_etat_rapprochement(stmt.id)
        assert etat.solde_comptable == 100_000
        assert etat.solde_bancaire == 100_000
        assert etat.equilibre is True
        assert etat.ecart == 0


# ═════════════════════════════════════════════════════════════════════════════
# TESTS POSITION CONSOLIDÉE
# ═════════════════════════════════════════════════════════════════════════════
class TestPositionConsolidee:
    async def test_position_multi_comptes(
        self, db_session, tenant, admin_user, plan_comptable_ci
    ):
        """Position consolidée avec 3 comptes (banque, caisse, MM)."""
        from app.schemas.treasury import TreasuryAccountCreate

        svc = TreasuryService(db_session, tenant.id, admin_user.id)

        # 3 comptes
        await svc.creer_compte(TreasuryAccountCreate(
            code="BNQ", libelle="Banque", type_compte="banque",
            compte_comptable="521000",
        ))
        await svc.creer_compte(TreasuryAccountCreate(
            code="CAI", libelle="Caisse", type_compte="caisse",
            compte_comptable="571000",
        ))
        await svc.creer_compte(TreasuryAccountCreate(
            code="WAV", libelle="Wave", type_compte="mobile_money",
            compte_comptable="521700",
        ))
        await db_session.flush()

        position = await svc.calculer_position_actuelle()
        assert len(position.detail_comptes) == 3
        assert position.solde_total == 0  # Aucune écriture
        assert position.solde_banques == 0
        assert position.solde_caisses == 0
        assert position.solde_mobile_money == 0
