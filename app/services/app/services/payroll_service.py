"""
Service de paie ivoirien.

Calcule pour chaque salarié :
- Salaire brut imposable (base + sursalaire + primes + avantages - abattements)
- Cotisations CNPS salariales (retraite 6,3% plafonnée)
- ITS selon barème progressif post-réforme 2023
- RICF (Réduction d'Impôt Charges de Famille)
- Cotisations patronales (CNPS patronal, PF, AT/MP, CMU, taxe salaires, FDFP, CN)
- Net à payer
- Coût total employeur

Puis génère l'écriture comptable SYSCOHADA correspondante.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.fiscal_ci import (
    CMU_MENSUEL_PAR_PERSONNE,
    CNPS_AT_MP_DEFAUT,
    CNPS_MATERNITE,
    CNPS_PENSION_PATRONAL,
    CNPS_PENSION_SALARIAL,
    CNPS_PLAFOND_MENSUEL,
    CNPS_PLAFOND_PF_AT,
    CNPS_PRESTATIONS_FAMILIALES,
    CONTRIBUTION_NATIONALE_TAUX,
    FDFP_TAUX,
    ITS_ABATTEMENT_MAX,
    ITS_ABATTEMENT_MIN,
    ITS_ABATTEMENT_TAUX,
    ITS_BAREME_2024,
    RICF_PAR_PARTS,
    TAXE_SALAIRES_PATRONALE_EXPATRIE,
    TAXE_SALAIRES_PATRONALE_IVOIRIEN,
)
from app.models.enums import EcritureSource
from app.models.payroll import CnpsDeclaration, Employee, Payslip
from app.schemas.ecriture import EcritureCreate, LigneIn
from app.services.audit_service import AuditService
from app.services.syscohada_service import SyscohadaService

logger = logging.getLogger(__name__)


class PayrollService:
    def __init__(self, db: AsyncSession, tenant_id: UUID, user_id: UUID) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.audit = AuditService(db)

    # ─────────────────────────────────────────────────────────────────────
    # Calcul d'un bulletin
    # ─────────────────────────────────────────────────────────────────────
    async def calculer_bulletin(
        self, employee_id: UUID, periode: str  # "YYYY-MM"
    ) -> Payslip:
        """
        Calcule et persiste un bulletin de paie.
        Idempotent : réexécuter sur la même période met à jour le brouillon.
        """
        employee = await self._get_employee(employee_id)
        annee, mois = int(periode[:4]), int(periode[5:7])
        date_paie = date(annee, mois, min(28, 28))  # fin de mois simplifiée

        # ─── 1. Salaire brut imposable ─────────────────────────────────
        primes_total = sum(employee.primes_fixes.values()) if employee.primes_fixes else 0
        avantages_total = sum(employee.avantages_nature.values()) if employee.avantages_nature else 0

        salaire_brut = (
            employee.salaire_base_mensuel
            + employee.sursalaire
            + primes_total
            + avantages_total
        )

        # Abattement forfaitaire 20% pour frais professionnels
        abattement = min(
            max(int(salaire_brut * ITS_ABATTEMENT_TAUX), ITS_ABATTEMENT_MIN),
            ITS_ABATTEMENT_MAX,
        )
        # Déduction des cotisations salariales CNPS du revenu imposable
        assiette_cnps_sal = min(salaire_brut, CNPS_PLAFOND_MENSUEL)
        cnps_salarial = int(assiette_cnps_sal * CNPS_PENSION_SALARIAL)

        # Base imposable ITS = brut - abattement - CNPS salarial
        base_imposable = max(0, salaire_brut - abattement - cnps_salarial)

        # ─── 2. ITS brut selon barème progressif ───────────────────────
        its_brut, detail_its = self._calculer_its(base_imposable)

        # ─── 3. RICF (Réduction Impôt Charges de Famille) ──────────────
        ricf = self._calculer_ricf(employee.parts_fiscales)

        # ─── 4. ITS net ────────────────────────────────────────────────
        its_net = max(0, its_brut - ricf)

        # ─── 5. CMU (salarial + patronal) ──────────────────────────────
        # 500 FCFA/mois par personne couverte (salarié + conjoint + enfants)
        personnes_couvertes = 1 + (1 if employee.situation_familiale == "marie" else 0)
        personnes_couvertes += min(employee.nombre_enfants, 6)
        cmu_total = personnes_couvertes * CMU_MENSUEL_PAR_PERSONNE
        cmu_salarial = cmu_total  # 50% employeur, 50% salarié (simplification MVP)
        cmu_patronal = cmu_total

        # ─── 6. Cotisations patronales ─────────────────────────────────
        assiette_pf_at = min(salaire_brut, CNPS_PLAFOND_PF_AT)
        cnps_patronal = int(assiette_cnps_sal * CNPS_PENSION_PATRONAL)
        prestations_familiales = int(assiette_pf_at * CNPS_PRESTATIONS_FAMILIALES)
        maternite = int(assiette_pf_at * CNPS_MATERNITE)
        accidents_travail = int(assiette_pf_at * (employee.taux_at_mp / 100))

        # Taxe sur salaires patronale (2,8% ivoirien / 12% expatrié)
        taux_ts = (
            TAXE_SALAIRES_PATRONALE_EXPATRIE
            if employee.est_expatrie
            else TAXE_SALAIRES_PATRONALE_IVOIRIEN
        )
        taxe_salaires = int(salaire_brut * taux_ts)

        # FDFP (1,2%) — formation professionnelle
        fdfp = int(salaire_brut * FDFP_TAUX)

        # Contribution Nationale (1,2%)
        contribution_nationale = int(salaire_brut * CONTRIBUTION_NATIONALE_TAUX)

        # ─── 7. Net à payer ────────────────────────────────────────────
        total_retenues = cnps_salarial + cmu_salarial + its_net
        net_a_payer = salaire_brut - total_retenues

        # Coût employeur = brut + toutes charges patronales
        cout_employeur = (
            salaire_brut
            + cnps_patronal
            + prestations_familiales
            + maternite
            + accidents_travail
            + cmu_patronal
            + taxe_salaires
            + fdfp
            + contribution_nationale
        )

        # ─── 8. Persistance ────────────────────────────────────────────
        existing = await self.db.scalar(
            select(Payslip).where(
                Payslip.tenant_id == self.tenant_id,
                Payslip.employee_id == employee_id,
                Payslip.periode == periode,
            )
        )

        payslip = existing or Payslip(
            tenant_id=self.tenant_id,
            employee_id=employee_id,
            periode=periode,
            date_paie=date_paie,
        )

        # Remplir tous les champs
        payslip.salaire_base = employee.salaire_base_mensuel
        payslip.sursalaire = employee.sursalaire
        payslip.primes = primes_total
        payslip.avantages_nature = avantages_total
        payslip.salaire_brut = salaire_brut
        payslip.salaire_brut_imposable = base_imposable
        payslip.cnps_salarial = cnps_salarial
        payslip.cmu_salarial = cmu_salarial
        payslip.its_brut = its_brut
        payslip.ricf_reduction = ricf
        payslip.its_net = its_net
        payslip.cnps_patronal = cnps_patronal
        payslip.prestations_familiales = prestations_familiales
        payslip.accidents_travail = accidents_travail + maternite  # regroupé
        payslip.cmu_patronal = cmu_patronal
        payslip.taxe_salaires_patronale = taxe_salaires
        payslip.fdfp = fdfp
        payslip.contribution_nationale = contribution_nationale
        payslip.total_retenues = total_retenues
        payslip.net_a_payer = net_a_payer
        payslip.cout_employeur = cout_employeur
        payslip.detail_its = detail_its
        payslip.statut = "brouillon"

        if existing is None:
            self.db.add(payslip)
        await self.db.flush()

        await self.audit.log(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            action="PAYSLIP_CALCULATE",
            ressource="payslip",
            ressource_id=payslip.id,
            payload={"periode": periode, "net": net_a_payer, "its": its_net},
        )
        return payslip

    # ─────────────────────────────────────────────────────────────────────
    # ITS — Barème progressif
    # ─────────────────────────────────────────────────────────────────────
    @staticmethod
    def _calculer_its(base_imposable: int) -> tuple[int, dict[str, Any]]:
        """
        Calcule l'ITS brut selon le barème progressif mensuel.
        Formule : R × taux - variable (selon tranche).
        Retourne (its_brut, détail).
        """
        detail = {"base": base_imposable, "tranches": []}
        if base_imposable <= 0:
            return 0, detail

        # Trouver la tranche applicable
        for bracket in ITS_BAREME_2024:
            if bracket.max_xof is None or base_imposable <= bracket.max_xof:
                if base_imposable <= bracket.min_xof and bracket.min_xof > 0:
                    continue
                its = int(base_imposable * bracket.taux - bracket.variable_xof)
                its = max(0, its)
                detail["tranches"].append({
                    "min": bracket.min_xof,
                    "max": bracket.max_xof,
                    "taux": bracket.taux,
                    "variable": bracket.variable_xof,
                    "its_calcule": its,
                })
                detail["its_brut"] = its
                return its, detail

        return 0, detail

    @staticmethod
    def _calculer_ricf(parts_fiscales: float) -> int:
        """RICF selon le nombre de parts fiscales."""
        # Arrondir au 0.5 le plus proche
        parts = round(parts_fiscales * 2) / 2
        parts = max(1.0, min(5.0, parts))
        return RICF_PAR_PARTS.get(parts, 0)

    # ─────────────────────────────────────────────────────────────────────
    # Écriture comptable du bulletin
    # ─────────────────────────────────────────────────────────────────────
    async def comptabiliser_bulletin(
        self, payslip_id: UUID, code_journal: str = "PA"
    ) -> UUID:
        """
        Génère l'écriture SYSCOHADA de paie.
        Débit 661xxx (rémunérations) + 664xxx (charges patronales)
        Crédit 422xxx (net à payer) + 431xxx (CNPS) + 447xxx (ITS/CNU) + ...
        """
        payslip = await self.db.scalar(
            select(Payslip).where(
                Payslip.id == payslip_id,
                Payslip.tenant_id == self.tenant_id,
            )
        )
        if payslip is None:
            raise HTTPException(404, "Bulletin introuvable")
        if payslip.ecriture_id is not None:
            return payslip.ecriture_id

        employee = await self._get_employee(payslip.employee_id)

        lignes: list[LigneIn] = [
            # Débit : salaire brut
            LigneIn(
                compte="661000",
                libelle=f"Rémunération {employee.nom_prenoms} — {payslip.periode}",
                debit=payslip.salaire_brut,
            ),
            # Débit : charges patronales
            LigneIn(
                compte="664000",
                libelle=f"Charges patronales {employee.nom_prenoms}",
                debit=(
                    payslip.cnps_patronal
                    + payslip.prestations_familiales
                    + payslip.accidents_travail
                    + payslip.cmu_patronal
                    + payslip.taxe_salaires_patronale
                    + payslip.fdfp
                    + payslip.contribution_nationale
                ),
            ),
            # Crédit : net à payer au salarié
            LigneIn(
                compte="422000",
                libelle=f"Net à payer {employee.nom_prenoms}",
                credit=payslip.net_a_payer,
            ),
            # Crédit : CNPS (parts salariale + patronale + PF + AT)
            LigneIn(
                compte="431000",
                libelle="CNPS — cotisations sociales",
                credit=(
                    payslip.cnps_salarial
                    + payslip.cnps_patronal
                    + payslip.prestations_familiales
                    + payslip.accidents_travail
                ),
            ),
            # Crédit : CMU (salarial + patronal)
            LigneIn(
                compte="431100",
                libelle="CMU — Couverture Maladie Universelle",
                credit=payslip.cmu_salarial + payslip.cmu_patronal,
            ),
            # Crédit : ITS
            LigneIn(
                compte="447000",
                libelle="État — ITS à payer",
                credit=payslip.its_net,
            ),
            # Crédit : Taxe sur salaires patronale
            LigneIn(
                compte="447100",
                libelle="État — Taxe sur salaires patronale",
                credit=payslip.taxe_salaires_patronale,
            ),
            # Crédit : FDFP
            LigneIn(
                compte="447200",
                libelle="FDFP — Formation professionnelle",
                credit=payslip.fdfp,
            ),
            # Crédit : Contribution Nationale
            LigneIn(
                compte="447300",
                libelle="Contribution Nationale",
                credit=payslip.contribution_nationale,
            ),
        ]

        syscohada = SyscohadaService(self.db, self.tenant_id, self.user_id)
        ecriture = await syscohada.create(EcritureCreate(
            numero_piece=f"PA-{payslip.periode}-{employee.matricule}",
            date_ecriture=payslip.date_paie,
            code_journal=code_journal,
            libelle=f"Paie {payslip.periode} — {employee.nom_prenoms}",
            source=EcritureSource.SYSTEME,
            lignes=lignes,
        ))

        payslip.ecriture_id = ecriture.id
        payslip.statut = "valide"
        await self.db.flush()

        await self.audit.log(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            action="PAYSLIP_COMPTABILISE",
            ressource="payslip",
            ressource_id=payslip.id,
            payload={"ecriture_id": str(ecriture.id)},
        )
        return ecriture.id

    # ─────────────────────────────────────────────────────────────────────
    # Déclaration CNPS mensuelle
    # ─────────────────────────────────────────────────────────────────────
    async def generer_declaration_cnps(
        self, annee: int, mois: int, trimestrielle: bool = False
    ) -> CnpsDeclaration:
        """
        Agrège les bulletins de la période et génère la déclaration CNPS.
        """
        if trimestrielle:
            mois_debut = ((mois - 1) // 3) * 3 + 1
            mois_fin = mois_debut + 2
            periodes = [f"{annee}-{m:02d}" for m in range(mois_debut, mois_fin + 1)]
        else:
            periodes = [f"{annee}-{mois:02d}"]

        bulletins = (
            await self.db.execute(
                select(Payslip).where(
                    Payslip.tenant_id == self.tenant_id,
                    Payslip.periode.in_(periodes),
                    Payslip.statut.in_(["brouillon", "valide"]),
                )
            )
        ).scalars().all()

        if not bulletins:
            raise HTTPException(400, "Aucun bulletin trouvé pour la période")

        masse_brute = sum(b.salaire_brut for b in bulletins)
        masse_plafonnee = sum(min(b.salaire_brut, CNPS_PLAFOND_MENSUEL) for b in bulletins)

        detail_salaries = [
            {
                "employee_id": str(b.employee_id),
                "salaire_brut": b.salaire_brut,
                "cnps_salarial": b.cnps_salarial,
                "cnps_patronal": b.cnps_patronal,
                "prestations_familiales": b.prestations_familiales,
                "accidents_travail": b.accidents_travail,
                "cmu": b.cmu_salarial + b.cmu_patronal,
            }
            for b in bulletins
        ]

        decl = CnpsDeclaration(
            tenant_id=self.tenant_id,
            periode_debut=date(annee, int(periodes[0][5:7]), 1),
            periode_fin=date(annee, int(periodes[-1][5:7]), 28),
            type_periode="trimestrielle" if trimestrielle else "mensuelle",
            masse_salariale_brute=masse_brute,
            masse_salariale_plafonnee=masse_plafonnee,
            nb_salaries=len(bulletins),
            cnps_patronal=sum(b.cnps_patronal for b in bulletins),
            cnps_salarial=sum(b.cnps_salarial for b in bulletins),
            prestations_familiales=sum(b.prestations_familiales for b in bulletins),
            accidents_travail=sum(b.accidents_travail for b in bulletins),
            cmu_total=sum(b.cmu_salarial + b.cmu_patronal for b in bulletins),
            total_a_payer=0,
            detail_salaries=detail_salaries,
            date_echeance=date(annee, mois + 1, 15) if mois < 12 else date(annee + 1, 1, 15),
        )
        decl.total_a_payer = (
            decl.cnps_patronal
            + decl.cnps_salarial
            + decl.prestations_familiales
            + decl.accidents_travail
            + decl.cmu_total
        )
        self.db.add(decl)
        await self.db.flush()

        await self.audit.log(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            action="CNPS_DECLARATION_GENERATE",
            ressource="cnps_declaration",
            ressource_id=decl.id,
            payload={"periode": periodes, "total": decl.total_a_payer},
        )
        return decl

    # ─────────────────────────────────────────────────────────────────────
    # Internes
    # ─────────────────────────────────────────────────────────────────────
    async def _get_employee(self, employee_id: UUID) -> Employee:
        emp = await self.db.scalar(
            select(Employee).where(
                Employee.id == employee_id,
                Employee.tenant_id == self.tenant_id,
                Employee.actif.is_(True),
            )
        )
        if emp is None:
            raise HTTPException(404, "Salarié introuvable ou inactif")
        return emp
