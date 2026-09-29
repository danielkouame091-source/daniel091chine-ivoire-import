"""
Moteur de calcul des KPIs — interprète les formules et interroge la DB.
"""
from __future__ import annotations

import hashlib
import logging
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.bi_syscohada import (
    FormatAffichage,
    KPIS_STANDARD,
    LimitesBI,
)
from app.models.bi import KPICache, KPISnapshot
from app.models.ecriture import Ecriture, EcritureLigne
from app.models.plan_comptable import PlanComptable

logger = logging.getLogger(__name__)


class KPIEngine:
    """
    Moteur de calcul des KPIs.
    Chaque KPI est identifié par un code et calculé via une méthode dédiée.
    """

    def __init__(self, db: AsyncSession, tenant_id: UUID) -> None:
        self.db = db
        self.tenant_id = tenant_id

    # ═════════════════════════════════════════════════════════════════════
    # POINT D'ENTRÉE
    # ═════════════════════════════════════════════════════════════════════
    async def calculer_kpi(
        self,
        kpi_code: str,
        filtres: dict[str, Any] | None = None,
        comparer_precedent: bool = True,
        utiliser_cache: bool = True,
    ) -> dict[str, Any]:
        """
        Calcule un KPI et retourne sa valeur + metadata.
        Utilise un cache court-terme (5 min).
        """
        filtres = filtres or {}

        # Cache
        cache_key = self._make_cache_key(kpi_code, filtres)
        if utiliser_cache:
            cached = await self._get_cache(cache_key)
            if cached is not None:
                return cached

        # Calcul
        start = time.monotonic()
        standard = self._get_kpi_standard(kpi_code)

        try:
            if standard is None:
                raise HTTPException(404, f"KPI {kpi_code} inconnu")

            # Dispatch selon le KPI
            calculator = self._get_calculator(kpi_code)
            if calculator is None:
                # Fallback : formule générique
                valeur = await self._calculer_generique(standard, filtres)
            else:
                valeur = await calculator(filtres)

            # Comparaison avec période précédente
            valeur_precedente = None
            variation_pct = None
            if comparer_precedent:
                try:
                    valeur_precedente = await calculator(self._filtres_precedents(filtres))
                    if valeur_precedente and valeur_precedente != 0:
                        variation_pct = (
                            (valeur - valeur_precedente) / abs(valeur_precedente) * 100
                        )
                except Exception:
                    logger.exception(f"[kpi] Échec calcul précédent {kpi_code}")

            # Formater
            valeur_formatee = self._formater(valeur, standard.format_affichage)
            tendance = self._tendance(valeur, valeur_precedente)

            result = {
                "kpi_code": kpi_code,
                "source": standard.source,
                "libelle": standard.libelle,
                "valeur": float(valeur),
                "valeur_formatee": valeur_formatee,
                "format_affichage": standard.format_affichage,
                "unite": standard.unite,
                "valeur_precedente": float(valeur_precedente) if valeur_precedente is not None else None,
                "variation_pct": round(variation_pct, 2) if variation_pct is not None else None,
                "tendance": tendance,
                "calcule_at": datetime.now(timezone.utc).isoformat(),
                "depuis_cache": False,
            }

            # Stocker en cache
            await self._set_cache(cache_key, kpi_code, result)

            duree = int((time.monotonic() - start) * 1000)
            logger.info(f"[kpi] {kpi_code} calculé en {duree}ms")
            return result

        except HTTPException:
            raise
        except Exception as exc:
            logger.exception(f"[kpi] Erreur calcul {kpi_code}")
            raise HTTPException(500, f"Erreur calcul KPI : {exc}")

    # ═════════════════════════════════════════════════════════════════════
    # CALCULATEURS SPÉCIFIQUES
    # ═════════════════════════════════════════════════════════════════════
    async def _ca_mensuel(self, filtres: dict[str, Any]) -> float:
        debut, fin = self._resolve_periode(filtres, defaut="this_month")
        return await self._sum_classe_prefixe("70", debut, fin)

    async def _ca_ytd(self, filtres: dict[str, Any]) -> float:
        debut = date(date.today().year, 1, 1)
        fin = date.today()
        return await self._sum_classe_prefixe("70", debut, fin)

    async def _marge_brute(self, filtres: dict[str, Any]) -> float:
        debut, fin = self._resolve_periode(filtres)
        ca = await self._sum_classe_prefixe("70", debut, fin)
        achats = await self._sum_classe_prefixe("60", debut, fin)
        return ca - achats

    async def _taux_marge(self, filtres: dict[str, Any]) -> float:
        debut, fin = self._resolve_periode(filtres)
        ca = await self._sum_classe_prefixe("70", debut, fin)
        if ca == 0:
            return 0.0
        marge = await self._marge_brute(filtres)
        return (marge / ca) * 100

    async def _ebe(self, filtres: dict[str, Any]) -> float:
        debut, fin = self._resolve_periode(filtres)
        ca = await self._sum_classe_prefixe("70", debut, fin)
        achats = await self._sum_classe_prefixe("60", debut, fin)
        services_ext = await self._sum_classe_prefixe("61", debut, fin) + \
                       await self._sum_classe_prefixe("62", debut, fin)
        impots = await self._sum_classe_prefixe("63", debut, fin) + \
                 await self._sum_classe_prefixe("64", debut, fin)
        personnel = await self._sum_classe_prefixe("66", debut, fin)

        va = ca - achats - services_ext
        return va - personnel - impots

    async def _resultat_net(self, filtres: dict[str, Any]) -> float:
        debut, fin = self._resolve_periode(filtres)
        produits = await self._sum_classe_prefixe("7", debut, fin)
        charges = await self._sum_classe_prefixe("6", debut, fin)
        return produits - charges

    async def _tresorerie(self, filtres: dict[str, Any]) -> float:
        # Solde des comptes 5x à date
        stmt = (
            select(
                func.coalesce(func.sum(EcritureLigne.debit_xof), 0),
                func.coalesce(func.sum(EcritureLigne.credit_xof), 0),
            )
            .join(PlanComptable, PlanComptable.id == EcritureLigne.compte_id)
            .join(Ecriture, Ecriture.id == EcritureLigne.ecriture_id)
            .where(
                EcritureLigne.tenant_id == self.tenant_id,
                PlanComptable.classe == 5,
                Ecriture.statut == "validee",
            )
        )
        result = (await self.db.execute(stmt)).one()
        return float(int(result[0] or 0) - int(result[1] or 0))

    async def _bfr(self, filtres: dict[str, Any]) -> float:
        """BFR = Stocks (3x) + Créances clients (41x) - Dettes fournisseurs (40x)."""
        stocks = await self._solde_classe_prefixe("3")
        creances = await self._solde_classe_prefixe("41")
        dettes = await self._solde_classe_prefixe("40")
        return stocks + creances - dettes

    async def _nb_factures_mois(self, filtres: dict[str, Any]) -> float:
        from app.models.sale import CustomerInvoice
        debut, fin = self._resolve_periode(filtres, defaut="this_month")
        return float(int(await self.db.scalar(
            select(func.count(CustomerInvoice.id)).where(
                CustomerInvoice.tenant_id == self.tenant_id,
                CustomerInvoice.date_facture.between(debut, fin),
                CustomerInvoice.statut.notin_(["annulee", "brouillon"]),
            )
        ) or 0))

    async def _creances_total(self, filtres: dict[str, Any]) -> float:
        from app.models.sale import CustomerInvoice
        return float(int(await self.db.scalar(
            select(func.coalesce(func.sum(CustomerInvoice.solde_du), 0)).where(
                CustomerInvoice.tenant_id == self.tenant_id,
                CustomerInvoice.solde_du > 0,
            )
        ) or 0))

    async def _factures_retard(self, filtres: dict[str, Any]) -> float:
        from app.models.sale import CustomerInvoice
        return float(int(await self.db.scalar(
            select(func.count(CustomerInvoice.id)).where(
                CustomerInvoice.tenant_id == self.tenant_id,
                CustomerInvoice.solde_du > 0,
                CustomerInvoice.date_echeance < date.today(),
                CustomerInvoice.statut.in_(["validee", "partiellement_payee", "en_retard"]),
            )
        ) or 0))

    async def _ticket_moyen(self, filtres: dict[str, Any]) -> float:
        from app.models.sale import CustomerInvoice
        debut, fin = self._resolve_periode(filtres)
        avg = await self.db.scalar(
            select(func.avg(CustomerInvoice.total_ttc)).where(
                CustomerInvoice.tenant_id == self.tenant_id,
                CustomerInvoice.date_facture.between(debut, fin),
                CustomerInvoice.statut.notin_(["annulee", "brouillon"]),
            )
        )
        return float(avg or 0)

    async def _ca_top_client(self, filtres: dict[str, Any]) -> float:
        from app.models.sale import CustomerInvoice
        debut, fin = self._resolve_periode(filtres)
        stmt = (
            select(
                CustomerInvoice.customer_id,
                func.sum(CustomerInvoice.total_ttc).label("total"),
            )
            .where(
                CustomerInvoice.tenant_id == self.tenant_id,
                CustomerInvoice.date_facture.between(debut, fin),
                CustomerInvoice.statut.notin_(["annulee", "brouillon"]),
            )
            .group_by(CustomerInvoice.customer_id)
            .order_by(func.sum(CustomerInvoice.total_ttc).desc())
            .limit(1)
        )
        row = (await self.db.execute(stmt)).one_or_none()
        return float(row[1] if row else 0)

    async def _achats_mois(self, filtres: dict[str, Any]) -> float:
        from app.models.purchase import SupplierInvoice
        debut, fin = self._resolve_periode(filtres, defaut="this_month")
        return float(int(await self.db.scalar(
            select(func.coalesce(func.sum(SupplierInvoice.total_ttc), 0)).where(
                SupplierInvoice.tenant_id == self.tenant_id,
                SupplierInvoice.date_facture.between(debut, fin),
                SupplierInvoice.statut.notin_(["annulee", "brouillon"]),
            )
        ) or 0))

    async def _dettes_total(self, filtres: dict[str, Any]) -> float:
        from app.models.purchase import SupplierInvoice
        return float(int(await self.db.scalar(
            select(func.coalesce(func.sum(SupplierInvoice.solde_du), 0)).where(
                SupplierInvoice.tenant_id == self.tenant_id,
                SupplierInvoice.solde_du > 0,
            )
        ) or 0))

    async def _solde_banque(self, filtres: dict[str, Any]) -> float:
        from app.models.treasury import TreasuryAccount
        return float(int(await self.db.scalar(
            select(func.coalesce(func.sum(TreasuryAccount.solde_comptable), 0)).where(
                TreasuryAccount.tenant_id == self.tenant_id,
                TreasuryAccount.type_compte == "banque",
                TreasuryAccount.actif.is_(True),
            )
        ) or 0))

    async def _solde_mm(self, filtres: dict[str, Any]) -> float:
        from app.models.treasury import TreasuryAccount
        return float(int(await self.db.scalar(
            select(func.coalesce(func.sum(TreasuryAccount.solde_comptable), 0)).where(
                TreasuryAccount.tenant_id == self.tenant_id,
                TreasuryAccount.type_compte == "mobile_money",
                TreasuryAccount.actif.is_(True),
            )
        ) or 0))

    async def _encaissements_mois(self, filtres: dict[str, Any]) -> float:
        from app.models.sale import CustomerPayment
        debut, fin = self._resolve_periode(filtres, defaut="this_month")
        return float(int(await self.db.scalar(
            select(func.coalesce(func.sum(CustomerPayment.montant), 0)).where(
                CustomerPayment.tenant_id == self.tenant_id,
                CustomerPayment.date_encaissement.between(debut, fin),
                CustomerPayment.statut == "valide",
            )
        ) or 0))

    async def _decaissements_mois(self, filtres: dict[str, Any]) -> float:
        from app.models.purchase import SupplierPayment
        debut, fin = self._resolve_periode(filtres, defaut="this_month")
        return float(int(await self.db.scalar(
            select(func.coalesce(func.sum(SupplierPayment.montant), 0)).where(
                SupplierPayment.tenant_id == self.tenant_id,
                SupplierPayment.date_paiement.between(debut, fin),
                SupplierPayment.statut == "valide",
            )
        ) or 0))

    async def _valeur_stock(self, filtres: dict[str, Any]) -> float:
        from app.models.stock import StockLevel
        return float(int(await self.db.scalar(
            select(func.coalesce(func.sum(StockLevel.valeur_stock), 0)).where(
                StockLevel.tenant_id == self.tenant_id,
            )
        ) or 0))

    async def _nb_articles_stock(self, filtres: dict[str, Any]) -> float:
        from app.models.stock import Item
        return float(int(await self.db.scalar(
            select(func.count(Item.id)).where(
                Item.tenant_id == self.tenant_id,
                Item.actif.is_(True),
            )
        ) or 0))

    async def _valeur_immo_brute(self, filtres: dict[str, Any]) -> float:
        from app.models.asset import FixedAsset
        return float(int(await self.db.scalar(
            select(func.coalesce(func.sum(FixedAsset.valeur_origine), 0)).where(
                FixedAsset.tenant_id == self.tenant_id,
                FixedAsset.statut.in_(["actif", "totalement_amorti"]),
            )
        ) or 0))

    async def _vnc_totale(self, filtres: dict[str, Any]) -> float:
        from app.models.asset import FixedAsset
        return float(int(await self.db.scalar(
            select(func.coalesce(func.sum(FixedAsset.vnc), 0)).where(
                FixedAsset.tenant_id == self.tenant_id,
                FixedAsset.statut.in_(["actif", "totalement_amorti"]),
            )
        ) or 0))

    async def _nb_projets_actifs(self, filtres: dict[str, Any]) -> float:
        from app.models.project import Project
        return float(int(await self.db.scalar(
            select(func.count(Project.id)).where(
                Project.tenant_id == self.tenant_id,
                Project.statut == "en_cours",
            )
        ) or 0))

    async def _effectif_actif(self, filtres: dict[str, Any]) -> float:
        from app.models.payroll import Employee
        return float(int(await self.db.scalar(
            select(func.count(Employee.id)).where(
                Employee.tenant_id == self.tenant_id,
                Employee.actif.is_(True),
            )
        ) or 0))

    async def _masse_salariale(self, filtres: dict[str, Any]) -> float:
        from app.models.payroll import Payslip
        debut, fin = self._resolve_periode(filtres, defaut="this_month")
        return float(int(await self.db.scalar(
            select(func.coalesce(func.sum(Payslip.salaire_brut), 0)).where(
                Payslip.tenant_id == self.tenant_id,
                Payslip.date_paie.between(debut, fin),
                Payslip.statut.in_(["valide", "paye"]),
            )
        ) or 0))

    async def _factures_fne_mois(self, filtres: dict[str, Any]) -> float:
        from app.models.fne import FneInvoice
        debut, fin = self._resolve_periode(filtres, defaut="this_month")
        return float(int(await self.db.scalar(
            select(func.count(FneInvoice.id)).where(
                FneInvoice.tenant_id == self.tenant_id,
                FneInvoice.statut == "certifiee",
                func.date(FneInvoice.date_certification).between(debut, fin),
            )
        ) or 0))

    async def _stickers_restants(self, filtres: dict[str, Any]) -> float:
        from app.models.fne import FneStickerBalance
        b = await self.db.scalar(
            select(FneStickerBalance).where(FneStickerBalance.tenant_id == self.tenant_id)
        )
        return float(b.balance_total if b else 0)

    async def _tva_due(self, filtres: dict[str, Any]) -> float:
        debut, fin = self._resolve_periode(filtres)
        collectee = await self._solde_classe_prefixe("443", debut, fin)
        deductible = await self._solde_classe_prefixe("445", debut, fin)
        return collectee - deductible

    async def _dso(self, filtres: dict[str, Any]) -> float:
        from app.models.sale import CustomerInvoice
        debut, fin = self._resolve_periode(filtres)
        rows = (
            await self.db.execute(
                select(CustomerInvoice.date_facture, CustomerInvoice.date_echeance)
                .where(
                    CustomerInvoice.tenant_id == self.tenant_id,
                    CustomerInvoice.date_facture.between(debut, fin),
                    CustomerInvoice.statut == "payee",
                )
            )
        ).all()
        if not rows:
            return 0.0
        delais = [(r[1] - r[0]).days for r in rows if r[0] and r[1]]
        return sum(delais) / len(delais) if delais else 0.0

    async def _dpo(self, filtres: dict[str, Any]) -> float:
        from app.models.purchase import SupplierInvoice
        debut, fin = self._resolve_periode(filtres)
        rows = (
            await self.db.execute(
                select(SupplierInvoice.date_facture, SupplierInvoice.date_echeance)
                .where(
                    SupplierInvoice.tenant_id == self.tenant_id,
                    SupplierInvoice.date_facture.between(debut, fin),
                    SupplierInvoice.statut == "payee",
                )
            )
        ).all()
        if not rows:
            return 0.0
        delais = [(r[1] - r[0]).days for r in rows if r[0] and r[1]]
        return sum(delais) / len(delais) if delais else 0.0

    # ═════════════════════════════════════════════════════════════════════
    # HELPERS
    # ═════════════════════════════════════════════════════════════════════
    def _get_kpi_standard(self, code: str) -> Any:
        for kpi in KPIS_STANDARD:
            if kpi.code == code:
                return kpi
        return None

    def _get_calculator(self, code: str):
        """Mapping code KPI → méthode de calcul."""
        mapping = {
            "CA_MENSUEL": self._ca_mensuel,
            "CA_YTD": self._ca_ytd,
            "MARGE_BRUTE": self._marge_brute,
            "TAUX_MARGE": self._taux_marge,
            "EBE": self._ebe,
            "RESULTAT_NET": self._resultat_net,
            "TRESORERIE": self._tresorerie,
            "BFR": self._bfr,
            "NB_FACTURES_MOIS": self._nb_factures_mois,
            "CREANCES_TOTAL": self._creances_total,
            "FACTURES_RETARD": self._factures_retard,
            "TICKET_MOYEN": self._ticket_moyen,
            "CA_TOP_CLIENT": self._ca_top_client,
            "ACHATS_MOIS": self._achats_mois,
            "DETTES_TOTAL": self._dettes_total,
            "SOLDE_BANQUE": self._solde_banque,
            "SOLDE_MM": self._solde_mm,
            "ENCAISSEMENTS_MOIS": self._encaissements_mois,
            "DECAISSEMENTS_MOIS": self._decaissements_mois,
            "VALEUR_STOCK": self._valeur_stock,
            "NB_ARTICLES_STOCK": self._nb_articles_stock,
            "VALEUR_IMMO_BRUTE": self._valeur_immo_brute,
            "VNC_TOTALE": self._vnc_totale,
            "NB_PROJETS_ACTIFS": self._nb_projets_actifs,
            "EFFECTIF_ACTIF": self._effectif_actif,
            "MASSE_SALARIALE": self._masse_salariale,
            "FACTURES_FNE_MOIS": self._factures_fne_mois,
            "STICKERS_RESTANTS": self._stickers_restants,
            "TVA_DUE": self._tva_due,
            "DSO": self._dso,
            "DPO": self._dpo,
        }
        return mapping.get(code)

    async def _calculer_generique(
        self, standard: Any, filtres: dict[str, Any]
    ) -> float:
        """Fallback : tente un calcul basique."""
        return 0.0

    async def _sum_classe_prefixe(
        self, prefixe: str, debut: date, fin: date
    ) -> float:
        """Somme des crédits (produits) - débits (charges) sur un préfixe de compte."""
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
                Ecriture.date_ecriture.between(debut, fin),
                Ecriture.statut == "validee",
            )
        )
        result = (await self.db.execute(stmt)).one()
        debit, credit = int(result[0] or 0), int(result[1] or 0)
        # Produits (7x) : crédit - débit / Charges (6x) : débit - crédit
        if prefixe.startswith("7"):
            return float(credit - debit)
        return float(debit - credit)

    async def _solde_classe_prefixe(
        self, prefixe: str, debut: date | None = None, fin: date | None = None
    ) -> float:
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
                Ecriture.statut == "validee",
            )
        )
        if debut:
            stmt = stmt.where(Ecriture.date_ecriture >= debut)
        if fin:
            stmt = stmt.where(Ecriture.date_ecriture <= fin)
        result = (await self.db.execute(stmt)).one()
        return float(int(result[0] or 0) - int(result[1] or 0))

    def _resolve_periode(
        self, filtres: dict[str, Any], defaut: str = "this_year"
    ) -> tuple[date, date]:
        """Retourne (debut, fin) selon les filtres."""
        if filtres.get("date_debut") and filtres.get("date_fin"):
            return filtres["date_debut"], filtres["date_fin"]

        periode = filtres.get("periode") or defaut
        today = date.today()

        if periode == "today":
            return today, today
        if periode == "yesterday":
            d = today - timedelta(days=1)
            return d, d
        if periode == "this_week":
            debut = today - timedelta(days=today.weekday())
            return debut, today
        if periode == "last_week":
            debut = today - timedelta(days=today.weekday() + 7)
            fin = debut + timedelta(days=6)
            return debut, fin
        if periode == "this_month":
            return today.replace(day=1), today
        if periode == "last_month":
            premier = today.replace(day=1)
            fin = premier - timedelta(days=1)
            debut = fin.replace(day=1)
            return debut, fin
        if periode == "this_quarter":
            q = (today.month - 1) // 3
            debut = date(today.year, q * 3 + 1, 1)
            return debut, today
        if periode == "last_quarter":
            q = (today.month - 1) // 3
            if q == 0:
                debut = date(today.year - 1, 10, 1)
                fin = date(today.year - 1, 12, 31)
            else:
                debut = date(today.year, (q - 1) * 3 + 1, 1)
                fin = debut + timedelta(days=92)
                fin = fin.replace(day=1) - timedelta(days=1)
            return debut, fin
        if periode == "this_year":
            return date(today.year, 1, 1), today
        if periode == "last_year":
            return date(today.year - 1, 1, 1), date(today.year - 1, 12, 31)
        if periode == "last_12_months":
            return today - timedelta(days=365), today

        return date(today.year, 1, 1), today

    def _filtres_precedents(self, filtres: dict[str, Any]) -> dict[str, Any]:
        """Décale la période pour comparaison."""
        debut, fin = self._resolve_periode(filtres)
        duree = (fin - debut).days
        return {
            **filtres,
            "date_debut": debut - timedelta(days=duree + 1),
            "date_fin": debut - timedelta(days=1),
        }

    def _formater(self, valeur: float, format_affichage: str) -> str:
        if format_affichage == "montant":
            return f"{int(valeur):,} FCFA".replace(",", " ")
        if format_affichage == "montant_compact":
            if abs(valeur) >= 1_000_000_000:
                return f"{valeur / 1_000_000_000:.2f} Md FCFA"
            if abs(valeur) >= 1_000_000:
                return f"{valeur / 1_000_000:.2f} M FCFA"
            if abs(valeur) >= 1_000:
                return f"{valeur / 1_000:.1f} K FCFA"
            return f"{int(valeur):,} FCFA".replace(",", " ")
        if format_affichage == "pourcentage":
            return f"{valeur:.2f}%"
        if format_affichage == "nombre":
            return f"{int(valeur):,}".replace(",", " ")
        if format_affichage == "duree":
            return f"{valeur:.1f}"
        return str(valeur)

    def _tendance(self, valeur: float, precedent: float | None) -> str | None:
        if precedent is None:
            return None
        if valeur > precedent:
            return "up"
        if valeur < precedent:
            return "down"
        return "flat"

    def _make_cache_key(self, kpi_code: str, filtres: dict[str, Any]) -> str:
        contenu = f"{self.tenant_id}|{kpi_code}|{sorted(filtres.items())}"
        return hashlib.sha256(contenu.encode()).hexdigest()

    async def _get_cache(self, key: str) -> dict[str, Any] | None:
        now = datetime.now(timezone.utc)
        cache = await self.db.scalar(
            select(KPICache).where(
                KPICache.tenant_id == self.tenant_id,
                KPICache.cache_key == key,
                KPICache.expire_at > now,
            )
        )
        if cache is None:
            return None
        return cache.valeur_json

    async def _set_cache(self, key: str, kpi_code: str, valeur: dict[str, Any]) -> None:
        now = datetime.now(timezone.utc)
        expire = now + timedelta(minutes=LimitesBI.CACHE_DUREE_MIN)

        existing = await self.db.scalar(
            select(KPICache).where(
                KPICache.tenant_id == self.tenant_id,
                KPICache.cache_key == key,
            )
        )
        if existing:
            existing.valeur_json = valeur
            existing.calcule_at = now
            existing.expire_at = expire
        else:
            self.db.add(KPICache(
                tenant_id=self.tenant_id,
                cache_key=key,
                kpi_code=kpi_code,
                valeur_json=valeur,
                calcule_at=now,
                expire_at=expire,
            ))
        await self.db.flush()

    # ═════════════════════════════════════════════════════════════════════
    # SÉRIES TEMPORELLES
    # ═════════════════════════════════════════════════════════════════════
    async def calculer_serie_temporelle(
        self,
        kpi_code: str,
        debut: date,
        fin: date,
        granularite: str = "month",
        filtres: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Calcule une série temporelle d'un KPI.
        Granularité : day | week | month | quarter | year
        """
        points: list[dict[str, Any]] = []

        if granularite == "day":
            current = debut
            while current <= fin:
                v = await self.calculer_kpi(
                    kpi_code,
                    {"date_debut": current, "date_fin": current, **(filtres or {})},
                    comparer_precedent=False,
                    utiliser_cache=False,
                )
                points.append({"date": current.isoformat(), "valeur": v["valeur"]})
                current += timedelta(days=1)
                if len(points) >= LimitesBI.MAX_POINTS_SERIE_TEMPORELLE:
                    break

        elif granularite == "month":
            current = debut.replace(day=1)
            while current <= fin:
                # Dernier jour du mois
                if current.month == 12:
                    fin_mois = current.replace(year=current.year + 1, month=1, day=1) - timedelta(days=1)
                else:
                    fin_mois = current.replace(month=current.month + 1, day=1) - timedelta(days=1)
                fin_mois = min(fin_mois, fin)

                v = await self.calculer_kpi(
                    kpi_code,
                    {"date_debut": current, "date_fin": fin_mois, **(filtres or {})},
                    comparer_precedent=False,
                    utiliser_cache=False,
                )
                points.append({"date": current.isoformat(), "valeur": v["valeur"]})

                if current.month == 12:
                    current = current.replace(year=current.year + 1, month=1)
                else:
                    current = current.replace(month=current.month + 1)

        elif granularite == "quarter":
            current = debut.replace(month=((debut.month - 1) // 3) * 3 + 1, day=1)
            while current <= fin:
                q = (current.month - 1) // 3
                fin_q = current.replace(month=(q + 1) * 3, day=1) if q < 3 else current.replace(month=12, day=31)
                if q < 3:
                    if (q + 1) * 3 == 12:
                        fin_q = current.replace(month=12, day=31)
                    else:
                        fin_q = current.replace(month=(q + 1) * 3 + 1, day=1) - timedelta(days=1)
                fin_q = min(fin_q, fin)

                v = await self.calculer_kpi(
                    kpi_code,
                    {"date_debut": current, "date_fin": fin_q, **(filtres or {})},
                    comparer_precedent=False,
                    utiliser_cache=False,
                )
                points.append({"date": current.isoformat(), "valeur": v["valeur"]})

                if q == 3:
                    current = current.replace(year=current.year + 1, month=1)
                else:
                    current = current.replace(month=(q + 1) * 3 + 1)

        elif granularite == "year":
            current = debut.replace(month=1, day=1)
            while current <= fin:
                fin_y = current.replace(month=12, day=31)
                fin_y = min(fin_y, fin)
                v = await self.calculer_kpi(
                    kpi_code,
                    {"date_debut": current, "date_fin": fin_y, **(filtres or {})},
                    comparer_precedent=False,
                    utiliser_cache=False,
                )
                points.append({"date": current.isoformat(), "valeur": v["valeur"]})
                current = current.replace(year=current.year + 1)

        return points

    # ═════════════════════════════════════════════════════════════════════
    # SNAPSHOT KPI
    # ═════════════════════════════════════════════════════════════════════
    async def creer_snapshot(self, kpi_code: str) -> KPISnapshot:
        """Crée un snapshot quotidien du KPI."""
        today = date.today()
        result = await self.calculer_kpi(kpi_code, comparer_precedent=True)

        # Vérifier si un snapshot existe déjà
        existing = await self.db.scalar(
            select(KPISnapshot).where(
                KPISnapshot.tenant_id == self.tenant_id,
                KPISnapshot.kpi_code == kpi_code,
                KPISnapshot.date_snapshot == today,
                KPISnapshot.periodicite == "jour",
            )
        )

        if existing:
            existing.valeur = Decimal(str(result["valeur"]))
            existing.valeur_precedente = (
                Decimal(str(result["valeur_precedente"]))
                if result["valeur_precedente"] is not None else None
            )
            existing.variation_pct = (
                Decimal(str(result["variation_pct"]))
                if result["variation_pct"] is not None else None
            )
            await self.db.flush()
            return existing

        snapshot = KPISnapshot(
            tenant_id=self.tenant_id,
            kpi_code=kpi_code,
            source=result["source"],
            date_snapshot=today,
            periodicite="jour",
            valeur=Decimal(str(result["valeur"])),
            valeur_precedente=(
                Decimal(str(result["valeur_precedente"]))
                if result["valeur_precedente"] is not None else None
            ),
            variation_pct=(
                Decimal(str(result["variation_pct"]))
                if result["variation_pct"] is not None else None
            ),
            created_at=datetime.now(timezone.utc),
        )
        self.db.add(snapshot)
        await self.db.flush()
        return snapshot

    async def get_tendance(
        self, kpi_code: str, jours: int = 30
    ) -> dict[str, Any]:
        """Retourne la tendance d'un KPI sur N jours."""
        date_debut = date.today() - timedelta(days=jours)
        snapshots = (
            await self.db.execute(
                select(KPISnapshot)
                .where(
                    KPISnapshot.tenant_id == self.tenant_id,
                    KPISnapshot.kpi_code == kpi_code,
                    KPISnapshot.date_snapshot >= date_debut,
                    KPISnapshot.periodicite == "jour",
                )
                .order_by(KPISnapshot.date_snapshot)
            )
        ).scalars().all()

        if not snapshots:
            return {
                "kpi_code": kpi_code,
                "date_debut": date_debut.isoformat(),
                "date_fin": date.today().isoformat(),
                "periodicite": "jour",
                "points": [],
                "valeur_min": 0.0,
                "valeur_max": 0.0,
                "valeur_moyenne": 0.0,
                "tendance": "stable",
                "variation_pct": 0.0,
            }

        valeurs = [float(s.valeur) for s in snapshots]
        premiere, derniere = valeurs[0], valeurs[-1]
        variation = ((derniere - premiere) / abs(premiere) * 100) if premiere != 0 else 0.0
        tendance = "hausse" if variation > 5 else ("baisse" if variation < -5 else "stable")

        return {
            "kpi_code": kpi_code,
            "date_debut": snapshots[0].date_snapshot.isoformat(),
            "date_fin": snapshots[-1].date_snapshot.isoformat(),
            "periodicite": "jour",
            "points": [
                {"date": s.date_snapshot.isoformat(), "valeur": float(s.valeur)}
                for s in snapshots
            ],
            "valeur_min": min(valeurs),
            "valeur_max": max(valeurs),
            "valeur_moyenne": sum(valeurs) / len(valeurs),
            "tendance": tendance,
            "variation_pct": round(variation, 2),
        }
