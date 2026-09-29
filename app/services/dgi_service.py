"""
Service de déclarations fiscales DGI (TVA, ITS, IS, patente, CN, FDFP).
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.fiscal_ci import (
    IS_MINIMUM_FORFAITAIRE_PLANCHER,
    IS_MINIMUM_FORFAITAIRE_PLAFOND,
    IS_MINIMUM_FORFAITAIRE_TAUX,
    IS_TAUX_NORMAL,
    TVA_TAUX_NORMAL,
    echeance_cnps,
    echeance_its,
    echeance_liasse_fiscale,
    echeance_tva,
)
from app.models.ecriture import Ecriture, EcritureLigne
from app.models.enums import EcritureStatut
from app.models.payroll import DgiDeclaration, Payslip
from app.models.plan_comptable import PlanComptable
from app.services.audit_service import AuditService

logger = logging.getLogger(__name__)


class DgiService:
    def __init__(self, db: AsyncSession, tenant_id: UUID, user_id: UUID) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.audit = AuditService(db)

    # ─────────────────────────────────────────────────────────────────────
    # Déclaration TVA (mensuelle ou trimestrielle)
    # ─────────────────────────────────────────────────────────────────────
    async def generer_declaration_tva(
        self, annee: int, periode_num: int, trimestrielle: bool = False
    ) -> DgiDeclaration:
        """Génère la déclaration TVA depuis les écritures."""
        if trimestrielle:
            mois_debut = ((periode_num - 1) // 3) * 3 + 1
            mois_fin = mois_debut + 2
            date_debut = date(annee, mois_debut, 1)
            date_fin = date(annee, mois_fin, 28)
            periode_str = f"{annee}-T{periode_num}"
            date_echeance = echeance_tva(annee, periode_num)
        else:
            date_debut = date(annee, periode_num, 1)
            date_fin = date(annee, periode_num, 28)
            periode_str = f"{annee}-{periode_num:02d}"
            date_echeance = date(annee, periode_num + 1, 10) if periode_num < 12 else date(annee + 1, 1, 10)

        # TVA collectée (compte 443xxx — crédit)
        tva_collectee = await self._solde_compte_prefixe(date_debut, date_fin, "443", sens="credit")
        # TVA déductible (compte 445xxx — débit)
        tva_deductible = await self._solde_compte_prefixe(date_debut, date_fin, "445", sens="debit")

        tva_nette = tva_collectee - tva_deductible
        credit_report = max(0, -tva_nette)
        montant_du = max(0, tva_nette)

        decl = DgiDeclaration(
            tenant_id=self.tenant_id,
            type_declaration="tva",
            periode=periode_str,
            date_echeance=date_echeance,
            base_imposable=0,
            taux=TVA_TAUX_NORMAL,
            montant_du=montant_du,
            credits=credit_report,
            montant_net=montant_du,
            detail={
                "tva_collectee": tva_collectee,
                "tva_deductible": tva_deductible,
                "tva_nette": tva_nette,
                "credit_report": credit_report,
            },
        )
        self.db.add(decl)
        await self.db.flush()
        return decl

    # ─────────────────────────────────────────────────────────────────────
    # Déclaration ITS (trimestrielle)
    # ─────────────────────────────────────────────────────────────────────
    async def generer_declaration_its(
        self, annee: int, trimestre: int
    ) -> DgiDeclaration:
        """Agrège l'ITS retenu sur les bulletins du trimestre."""
        mois_debut = (trimestre - 1) * 3 + 1
        mois_fin = mois_debut + 2
        periodes = [f"{annee}-{m:02d}" for m in range(mois_debut, mois_fin + 1)]

        bulletins = (
            await self.db.execute(
                select(Payslip).where(
                    Payslip.tenant_id == self.tenant_id,
                    Payslip.periode.in_(periodes),
                    Payslip.statut.in_(["brouillon", "valide"]),
                )
            )
        ).scalars().all()

        total_its = sum(b.its_net for b in bulletins)
        total_brut = sum(b.salaire_brut for b in bulletins)
        nb_salaries = len(bulletins)

        decl = DgiDeclaration(
            tenant_id=self.tenant_id,
            type_declaration="its",
            periode=f"{annee}-T{trimestre}",
            date_echeance=echeance_its(annee, trimestre),
            base_imposable=total_brut,
            montant_du=total_its,
            montant_net=total_its,
            detail={
                "masse_salariale": total_brut,
                "nb_salaries": nb_salaries,
                "par_periode": {
                    p: sum(b.its_net for b in bulletins if b.periode == p)
                    for p in periodes
                },
            },
        )
        self.db.add(decl)
        await self.db.flush()
        return decl

    # ─────────────────────────────────────────────────────────────────────
    # Déclaration IS (Impôt sur les Sociétés)
    # ─────────────────────────────────────────────────────────────────────
    async def generer_declaration_is(
        self, exercice_id: UUID, chiffre_affaires_ttc: int | None = None
    ) -> DgiDeclaration:
        """Calcule l'IS dû : max(IS normal, IS minimum forfaitaire)."""
        from app.models.exercice import Exercice
        exercice = await self.db.scalar(
            select(Exercice).where(
                Exercice.id == exercice_id,
                Exercice.tenant_id == self.tenant_id,
            )
        )
        if exercice is None:
            raise HTTPException(404, "Exercice introuvable")

        # Résultat net depuis le compte de résultat
        from app.services.financial_statement_service import FinancialStatementService
        fs = FinancialStatementService(self.db, self.tenant_id, self.user_id)
        resultat = await fs.generer_compte_resultat(exercice_id)
        resultat_net = resultat["resultat_net"]

        # IS normal
        is_normal = max(0, int(resultat_net * IS_TAUX_NORMAL))

        # IS minimum forfaitaire = 0,5% du CA TTC
        ca_ttc = chiffre_affaires_ttc or resultat["chiffre_affaires"]
        is_minimum = max(
            IS_MINIMUM_FORFAITAIRE_PLANCHER,
            min(int(ca_ttc * IS_MINIMUM_FORFAITAIRE_TAUX), IS_MINIMUM_FORFAITAIRE_PLAFOND),
        )

        is_du = max(is_normal, is_minimum)

        decl = DgiDeclaration(
            tenant_id=self.tenant_id,
            type_declaration="is",
            periode=str(exercice.date_fin.year),
            date_echeance=echeance_liasse_fiscale(exercice.date_fin.year),
            base_imposable=resultat_net,
            taux=IS_TAUX_NORMAL,
            montant_du=is_du,
            montant_net=is_du,
            detail={
                "resultat_net": resultat_net,
                "is_normal": is_normal,
                "is_minimum_forfaitaire": is_minimum,
                "is_retenu": is_du,
                "chiffre_affaires_ttc": ca_ttc,
            },
        )
        self.db.add(decl)
        await self.db.flush()
        return decl

    # ─────────────────────────────────────────────────────────────────────
    # Internes
    # ─────────────────────────────────────────────────────────────────────
    async def _solde_compte_prefixe(
        self, date_debut: date, date_fin: date, prefixe: str, sens: str
    ) -> int:
        stmt = (
            select(
                func.coalesce(func.sum(EcritureLigne.debit_xof), 0),
                func.coalesce(func.sum(EcritureLigne.credit_xof), 0),
            )
            .join(PlanComptable, PlanComptable.id == EcritureLigne.compte_id)
            .join(Ecriture, Ecriture.id == EcritureLigne.ecriture_id)
            .where(
                EcritureLigne.tenant_id == self.tenant_id,
                PlanComptable.compte.like(f"{prefixe}%"),
                Ecriture.date_ecriture.between(date_debut, date_fin),
                Ecriture.statut == EcritureStatut.VALIDEE,
            )
        )
        result = (await self.db.execute(stmt)).one()
        debit, credit = int(result[0] or 0), int(result[1] or 0)
        return (debit - credit) if sens == "debit" else (credit - debit)
