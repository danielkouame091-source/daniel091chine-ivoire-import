"""Tests de la règle fondamentale SYSCOHADA : partie double."""
from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from app.schemas.ecriture import EcritureCreate, LigneIn

pytestmark = pytest.mark.unit


class TestPartieDoublePydantic:
    def test_ecriture_equilibree_acceptee(self):
        e = EcritureCreate(
            date_ecriture=date(2025, 3, 15),
            code_journal="VE",
            libelle="Vente de 50 sacs de riz",
            lignes=[
                LigneIn(compte="521100", debit=1_250_000),
                LigneIn(compte="701100", credit=1_250_000),
            ],
        )
        assert len(e.lignes) == 2
        assert sum(l.debit for l in e.lignes) == sum(l.credit for l in e.lignes)

    def test_ecriture_desequilibree_rejetee(self):
        with pytest.raises(ValidationError, match="déséquilibrée"):
            EcritureCreate(
                date_ecriture=date(2025, 3, 15),
                code_journal="VE",
                libelle="Test déséquilibre",
                lignes=[
                    LigneIn(compte="521100", debit=1000),
                    LigneIn(compte="701100", credit=900),
                ],
            )

    def test_ligne_avec_debit_et_credit_rejetee(self):
        with pytest.raises(ValidationError, match="débit ET crédit"):
            LigneIn(compte="521100", debit=100, credit=100)

    def test_ligne_vide_rejetee(self):
        with pytest.raises(ValidationError, match="montant nul"):
            LigneIn(compte="521100", debit=0, credit=0)

    def test_ecriture_avec_une_seule_ligne_rejetee(self):
        with pytest.raises(ValidationError, match="au moins 2 lignes"):
            EcritureCreate(
                date_ecriture=date(2025, 3, 15),
                code_journal="VE",
                libelle="Une seule ligne",
                lignes=[LigneIn(compte="521100", debit=1000)],
            )

    def test_ecriture_avec_3_lignes_equilibree(self):
        """Cas classique : 1 débit, 2 crédits."""
        e = EcritureCreate(
            date_ecriture=date(2025, 3, 15),
            code_journal="VE",
            libelle="Vente avec TVA",
            lignes=[
                LigneIn(compte="411100", debit=1_180_000),
                LigneIn(compte="701100", credit=1_000_000),
                LigneIn(compte="443000", credit=180_000),  # TVA
            ],
        )
        assert e.lignes[0].debit == 1_180_000
        assert sum(l.credit for l in e.lignes) == 1_180_000

    def test_ecriture_zero_rejetee(self):
        with pytest.raises(ValidationError, match="déséquilibrée|vide"):
            EcritureCreate(
                date_ecriture=date(2025, 3, 15),
                code_journal="VE",
                libelle="Vide",
                lignes=[
                    LigneIn(compte="521100", debit=0),
                    LigneIn(compte="701100", credit=0),
                ],
            )

    def test_montant_negatif_rejete(self):
        with pytest.raises(ValidationError):
            LigneIn(compte="521100", debit=-1000)


@pytest.mark.integration
class TestPartieDoubleDB:
    async def test_creation_ecriture_equilibree(
        self,
        db_session,
        tenant,
        admin_user,
        exercice,
        plan_comptable_ci,
        journal_ve,
    ):
        from app.schemas.ecriture import EcritureCreate, LigneIn
        from app.services.syscohada_service import SyscohadaService

        svc = SyscohadaService(db_session, tenant.id, admin_user.id)
        e = await svc.create(
            EcritureCreate(
                date_ecriture=date(2025, 3, 15),
                code_journal="VE",
                libelle="Vente 50 sacs de riz",
                lignes=[
                    LigneIn(compte="521100", debit=1_250_000),
                    LigneIn(compte="701100", credit=1_250_000),
                ],
            )
        )
        assert e.numero_piece.startswith("VE-2025-")
        assert e.statut.value == "validee"
        assert e.hash_chain is not None
        assert e.hash_precedent is None  # 1re écriture du tenant
        assert len(e.lignes) == 2

    async def test_numero_piece_incremente(
        self,
        db_session,
        tenant,
        admin_user,
        exercice,
        plan_comptable_ci,
        journal_ve,
    ):
        from app.schemas.ecriture import EcritureCreate, LigneIn
        from app.services.syscohada_service import SyscohadaService

        svc = SyscohadaService(db_session, tenant.id, admin_user.id)
        e1 = await svc.create(EcritureCreate(
            date_ecriture=date(2025, 3, 15),
            code_journal="VE",
            libelle="Vente 1",
            lignes=[
                LigneIn(compte="521100", debit=100_000),
                LigneIn(compte="701100", credit=100_000),
            ],
        ))
        e2 = await svc.create(EcritureCreate(
            date_ecriture=date(2025, 3, 16),
            code_journal="VE",
            libelle="Vente 2",
            lignes=[
                LigneIn(compte="521100", debit=200_000),
                LigneIn(compte="701100", credit=200_000),
            ],
        ))
        assert e1.numero_piece == "VE-2025-00001"
        assert e2.numero_piece == "VE-2025-00002"
        # Hash-chain : e2 pointe vers e1
        assert e2.hash_precedent == e1.hash_chain

    async def test_compte_inexistant_rejete(
        self,
        db_session,
        tenant,
        admin_user,
        exercice,
        plan_comptable_ci,
        journal_ve,
    ):
        from fastapi import HTTPException
        from app.schemas.ecriture import EcritureCreate, LigneIn
        from app.services.syscohada_service import SyscohadaService

        svc = SyscohadaService(db_session, tenant.id, admin_user.id)
        with pytest.raises(HTTPException) as exc:
            await svc.create(EcritureCreate(
                date_ecriture=date(2025, 3, 15),
                code_journal="VE",
                libelle="Compte inconnu",
                lignes=[
                    LigneIn(compte="999999", debit=1000),
                    LigneIn(compte="701100", credit=1000),
                ],
            ))
        assert exc.value.status_code == 400
        assert "introuvables" in exc.value.detail
