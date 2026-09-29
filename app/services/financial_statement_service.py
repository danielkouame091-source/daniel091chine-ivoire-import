"""
Service de génération des états financiers SYSCOHADA révisé.

Produit :
- Bilan (actif + passif)
- Compte de résultat
- TAFIRE (Tableau Financier des Ressources et Emplois)
- Soldes intermédiaires de gestion (SIG)

Méthode : agrégation des écritures par classe SYSCOHADA (1-5 pour bilan, 6-7 pour résultat).
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ecriture import Ecriture, EcritureLigne
from app.models.enums import EcritureStatut
from app.models.exercice import Exercice
from app.models.payroll import FinancialStatement
from app.models.plan_comptable import PlanComptable

logger = logging.getLogger(__name__)


class FinancialStatementService:
    def __init__(self, db: AsyncSession, tenant_id: UUID, user_id: UUID) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self.user_id = user_id

    # ─────────────────────────────────────────────────────────────────────
    # Bilan
    # ─────────────────────────────────────────────────────────────────────
    async def generer_bilan(self, exercice_id: UUID) -> dict[str, Any]:
        """Génère le bilan SYSCOHADA (actif + passif) à la clôture de l'exercice."""
        exercice = await self._get_exercice(exercice_id)
        soldes = await self._soldes_par_compte(exercice.date_debut, exercice.date_fin)

        actif_immobilise = self._agreger(soldes, classes=[2], sens="debit")
        actif_circulant = self._agreger(soldes, classes=[3, 4], sens="debit")
        tresorerie_actif = self._agreger(soldes, classes=[5], sens="debit")
        total_actif = actif_immobilise["total"] + actif_circulant["total"] + tresorerie_actif["total"]

        capitaux_propres = self._agreger(soldes, classes=[1], sens="credit")
        dettes_financieres = self._agreger(soldes, classes=[1, 4], sens="credit", filtre="dettes")
        passif_circulant = self._agreger(soldes, classes=[4], sens="credit")
        tresorerie_passif = self._agreger(soldes, classes=[5], sens="credit")
        total_passif = (
            capitaux_propres["total"] + dettes_financieres["total"]
            + passif_circulant["total"] + tresorerie_passif["total"]
        )

        return {
            "actif": {
                "actif_immobilise": actif_immobilise,
                "actif_circulant": actif_circulant,
                "tresorerie_actif": tresorerie_actif,
                "total_actif": total_actif,
            },
            "passif": {
                "capitaux_propres": capitaux_propres,
                "dettes_financieres": dettes_financieres,
                "passif_circulant": passif_circulant,
                "tresorerie_passif": tresorerie_passif,
                "total_passif": total_passif,
            },
            "equilibre": total_actif == total_passif,
        }

    # ─────────────────────────────────────────────────────────────────────
    # Compte de résultat
    # ─────────────────────────────────────────────────────────────────────
    async def generer_compte_resultat(self, exercice_id: UUID) -> dict[str, Any]:
        """Génère le compte de résultat SYSCOHADA + soldes intermédiaires."""
        exercice = await self._get_exercice(exercice_id)
        soldes = await self._soldes_par_compte(exercice.date_debut, exercice.date_fin)

        # Chiffre d'affaires (701 à 707)
        ca = self._solde_prefixe(soldes, prefixe="70", sens="credit")

        # Achats consommés (601, 602, 603, 604, 605, 608)
        achats = self._solde_prefixe(soldes, prefixe="60", sens="debit")

        # Marge commerciale = CA - achats
        marge_commerciale = ca - achats

        # Autres charges externes (61-62)
        services_ext = self._solde_prefixe(soldes, prefixe="61", sens="debit") + \
                        self._solde_prefixe(soldes, prefixe="62", sens="debit")

        # Valeur ajoutée
        valeur_ajoutee = marge_commerciale - services_ext

        # Charges de personnel (66)
        charges_personnel = self._solde_prefixe(soldes, prefixe="66", sens="debit")

        # Impôts et taxes (63, 64)
        impots_taxes = self._solde_prefixe(soldes, prefixe="63", sens="debit") + \
                       self._solde_prefixe(soldes, prefixe="64", sens="debit")

        # EBE (Excédent Brut d'Exploitation)
        ebe = valeur_ajoutee - charges_personnel - impots_taxes

        # Dotations aux amortissements et provisions (68)
        dotations = self._solde_prefixe(soldes, prefixe="68", sens="debit")

        # Reprises (78, 79)
        reprises = self._solde_prefixe(soldes, prefixe="78", sens="credit") + \
                   self._solde_prefixe(soldes, prefixe="79", sens="credit")

        # Résultat d'exploitation
        resultat_exploitation = ebe - dotations + reprises

        # Charges financières (67)
        charges_financieres = self._solde_prefixe(soldes, prefixe="67", sens="debit")
        # Produits financiers (77)
        produits_financiers = self._solde_prefixe(soldes, prefixe="77", sens="credit")

        # Résultat financier
        resultat_financier = produits_financiers - charges_financieres

        # Résultat des activités ordinaires (RAO)
        rao = resultat_exploitation + resultat_financier

        # Charges HAO (83, 85)
        charges_hao = self._solde_prefixe(soldes, prefixe="83", sens="debit") + \
                      self._solde_prefixe(soldes, prefixe="85", sens="debit")
        # Produits HAO (82, 84, 86, 88)
        produits_hao = sum(
            self._solde_prefixe(soldes, prefixe=p, sens="credit")
            for p in ("82", "84", "86", "88")
        )

        resultat_hao = produits_hao - charges_hao

        # Résultat net
        resultat_net = rao + resultat_hao

        # Participation des travailleurs (87)
        participation = self._solde_prefixe(soldes, prefixe="87", sens="debit")
        resultat_net_final = resultat_net - participation

        return {
            "chiffre_affaires": ca,
            "achats_consommes": achats,
            "marge_commerciale": marge_commerciale,
            "services_externes": services_ext,
            "valeur_ajoutee": valeur_ajoutee,
            "charges_personnel": charges_personnel,
            "impots_taxes": impots_taxes,
            "ebe": ebe,
            "dotations": dotations,
            "reprises": reprises,
            "resultat_exploitation": resultat_exploitation,
            "charges_financieres": charges_financieres,
            "produits_financiers": produits_financiers,
            "resultat_financier": resultat_financier,
            "rao": rao,
            "charges_hao": charges_hao,
            "produits_hao": produits_hao,
            "resultat_hao": resultat_hao,
            "resultat_net": resultat_net_final,
        }

    # ─────────────────────────────────────────────────────────────────────
    # TAFIRE (Tableau Financier des Ressources et Emplois)
    # ─────────────────────────────────────────────────────────────────────
    async def generer_tafire(self, exercice_id: UUID) -> dict[str, Any]:
        """
        Génère le TAFIRE (version simplifiée).
        Le TAFIRE complet nécessite les variations N/N-1.
        """
        exercice = await self._get_exercice(exercice_id)
        resultat = await self.generer_compte_resultat(exercice_id)

        # Capacité d'autofinancement (CAFG) ≈ EBE - charges financières - impôts
        cafg = resultat["ebe"] - resultat["charges_financieres"]

        return {
            "capacite_autofinancement": cafg,
            "resultat_net": resultat["resultat_net"],
            "valeur_ajoutee": resultat["valeur_ajoutee"],
            "ebe": resultat["ebe"],
            "note": "TAFIRE simplifié — la version complète nécessite les variations N/N-1",
        }

    # ─────────────────────────────────────────────────────────────────────
    # Agrégation & helpers
    # ─────────────────────────────────────────────────────────────────────
    async def _soldes_par_compte(
        self, date_debut: date, date_fin: date
    ) -> list[tuple[str, int, int]]:
        """Retourne [(compte, debit, credit), ...] sur la période."""
        stmt = (
            select(
                PlanComptable.compte,
                func.coalesce(func.sum(EcritureLigne.debit_xof), 0),
                func.coalesce(func.sum(EcritureLigne.credit_xof), 0),
            )
            .join(PlanComptable, PlanComptable.id == EcritureLigne.compte_id)
            .join(Ecriture, Ecriture.id == EcritureLigne.ecriture_id)
            .where(
                EcritureLigne.tenant_id == self.tenant_id,
                Ecriture.date_ecriture.between(date_debut, date_fin),
                Ecriture.statut == EcritureStatut.VALIDEE,
            )
            .group_by(PlanComptable.compte)
        )
        rows = (await self.db.execute(stmt)).all()
        return [(r[0], int(r[1] or 0), int(r[2] or 0)) for r in rows]

    @staticmethod
    def _solde_prefixe(soldes: list[tuple[str, int, int]], prefixe: str, sens: str) -> int:
        total = 0
        for compte, debit, credit in soldes:
            if compte.startswith(prefixe):
                if sens == "credit":
                    total += (credit - debit)
                else:
                    total += (debit - credit)
        return max(0, total)

    @staticmethod
    def _agreger(
        soldes: list[tuple[str, int, int]],
        classes: list[int],
        sens: str,
        filtre: str | None = None,
    ) -> dict[str, Any]:
        lignes: list[dict[str, Any]] = []
        total = 0
        for compte, debit, credit in soldes:
            if int(compte[0]) not in classes:
                continue
            solde = (debit - credit) if sens == "debit" else (credit - debit)
            if solde <= 0:
                continue
            lignes.append({"compte": compte, "montant": solde})
            total += solde
        return {"lignes": lignes, "total": total}

    async def _get_exercice(self, exercice_id: UUID) -> Exercice:
        ex = await self.db.scalar(
            select(Exercice).where(
                Exercice.id == exercice_id,
                Exercice.tenant_id == self.tenant_id,
            )
        )
        if ex is None:
            raise HTTPException(404, "Exercice introuvable")
        return ex

    # ─────────────────────────────────────────────────────────────────────
    # Persistance
    # ─────────────────────────────────────────────────────────────────────
    async def generer_et_sauvegarder(self, exercice_id: UUID) -> list[FinancialStatement]:
        """Génère et persiste Bilan + Compte de Résultat + TAFIRE."""
        bilan = await self.generer_bilan(exercice_id)
        resultat = await self.generer_compte_resultat(exercice_id)
        tafire = await self.generer_tafire(exercice_id)

        results: list[FinancialStatement] = []
        for type_etat, donnees, extras in [
            ("bilan", bilan, {
                "total_actif": bilan["actif"]["total_actif"],
                "total_passif": bilan["passif"]["total_passif"],
                "resultat_net": bilan["passif"]["capitaux_propres"]["total"],
                "chiffre_affaires": None, "valeur_ajoutee": None,
            }),
            ("compte_resultat", resultat, {
                "total_actif": None, "total_passif": None,
                "resultat_net": resultat["resultat_net"],
                "chiffre_affaires": resultat["chiffre_affaires"],
                "valeur_ajoutee": resultat["valeur_ajoutee"],
            }),
            ("tafire", tafire, {
                "total_actif": None, "total_passif": None,
                "resultat_net": tafire["resultat_net"],
                "chiffre_affaires": None, "valeur_ajoutee": tafire["valeur_ajoutee"],
            }),
        ]:
            fs = FinancialStatement(
                tenant_id=self.tenant_id,
                exercice_id=exercice_id,
                type_etat=type_etat,
                donnees=donnees,
                statut="brouillon",
                **extras,
            )
            self.db.add(fs)
            results.append(fs)

        await self.db.flush()
        return results
