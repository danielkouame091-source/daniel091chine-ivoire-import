"""
Service de prévision de trésorerie — modèle hybride.

Méthode :
1. Extraction historique (90 jours d'écritures sur comptes 5xx + soldes)
2. Calcul de la tendance (moyenne mobile 7j / 30j)
3. Détection de saisonnalité simple (jour de semaine)
4. Projection linéaire + saisonnalité sur l'horizon demandé
5. Détection de creux (alerte si solde < 0 à venir)
6. Résumé IA (si OpenAI activé)
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.ecriture import Ecriture, EcritureLigne
from app.models.enums import EcritureStatut
from app.models.forecast import CashflowForecast
from app.models.plan_comptable import PlanComptable

logger = logging.getLogger(__name__)


class ForecastService:
    def __init__(self, db: AsyncSession, tenant_id: UUID, user_id: UUID) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self.user_id = user_id

    async def calculer(self, horizon_jours: int = 90) -> CashflowForecast:
        """
        Calcule la prévision et la persiste (snapshot immuable).
        """
        if horizon_jours not in (30, 60, 90, 180):
            raise HTTPException(400, "Horizon invalide (30, 60, 90, 180)")

        today = date.today()

        # ─── 1. Solde initial (tous les comptes 5xx) ─────────────────────
        solde_initial = await self._calculer_solde_tresorerie(today)

        # ─── 2. Extraction historique ────────────────────────────────────
        horizon_histo = 90
        date_debut_histo = today - timedelta(days=horizon_histo)
        flux = await self._extraire_flux_historiques(date_debut_histo, today)

        # ─── 3. Statistiques ─────────────────────────────────────────────
        stats = self._calculer_statistiques(flux, horizon_histo, today)

        # ─── 4. Projection ───────────────────────────────────────────────
        courbe = self._projeter(solde_initial, stats, today, horizon_jours)

        # ─── 5. Détection de creux ───────────────────────────────────────
        soldes = [p["solde"] for p in courbe]
        solde_final = soldes[-1] if soldes else solde_initial
        flux_entrant = sum(p["entrant"] for p in courbe)
        flux_sortant = sum(p["sortant"] for p in courbe)
        alerte = any(s < 0 for s in soldes)
        premiere_neg = next((p["date"] for p in courbe if p["solde"] < 0), None)
        creux_max = min(soldes) if soldes else solde_initial

        # ─── 6. Fiabilité ────────────────────────────────────────────────
        fiabilite = "faible"
        if stats["jours_avec_donnees"] >= 60:
            fiabilite = "elevee"
        elif stats["jours_avec_donnees"] >= 30:
            fiabilite = "moyenne"

        # ─── 7. Résumé IA (facultatif) ───────────────────────────────────
        resume = await self._generer_resume(
            solde_initial, solde_final, flux_entrant, flux_sortant,
            alerte, premiere_neg, fiabilite, horizon_jours,
        )

        # ─── 8. Persistance ──────────────────────────────────────────────
        forecast = CashflowForecast(
            tenant_id=self.tenant_id,
            date_calcul=datetime.now(timezone.utc),
            horizon_jours=horizon_jours,
            date_debut=today,
            date_fin=today + timedelta(days=horizon_jours),
            solde_initial_xof=solde_initial,
            solde_final_prevu_xof=solde_final,
            flux_entrant_prevu_xof=flux_entrant,
            flux_sortant_prevu_xof=flux_sortant,
            jours_historique=stats["jours_avec_donnees"],
            fiabilite=fiabilite,
            methode="hybride",
            courbe_quotidienne=courbe,
            alerte_tresorerie_negative=alerte,
            premiere_date_negative=premiere_neg,
            creux_max_xof=creux_max,
            resume_ia=resume,
        )
        self.db.add(forecast)
        await self.db.flush()
        return forecast

    async def dernier(self) -> CashflowForecast | None:
        return await self.db.scalar(
            select(CashflowForecast)
            .where(CashflowForecast.tenant_id == self.tenant_id)
            .order_by(CashflowForecast.date_calcul.desc())
            .limit(1)
        )

    # ─────────────────────────────────────────────────────────────────────
    # Internes
    # ─────────────────────────────────────────────────────────────────────
    async def _calculer_solde_tresorerie(self, jusqu_a: date) -> int:
        """Solde net des comptes 5xx (trésorerie) à la date donnée."""
        stmt = (
            select(
                func.coalesce(func.sum(EcritureLigne.debit_xof - EcritureLigne.credit_xof), 0)
            )
            .join(PlanComptable, PlanComptable.id == EcritureLigne.compte_id)
            .join(Ecriture, Ecriture.id == EcritureLigne.ecriture_id)
            .where(
                EcritureLigne.tenant_id == self.tenant_id,
                PlanComptable.classe == 5,
                Ecriture.date_ecriture <= jusqu_a,
                Ecriture.statut == EcritureStatut.VALIDEE,
            )
        )
        result = await self.db.scalar(stmt)
        return int(result or 0)

    async def _extraire_flux_historiques(
        self, debut: date, fin: date
    ) -> list[tuple[date, int, int]]:
        """
        Retourne [(date, entrant, sortant), ...] sur les écritures 5xx.
        - entrant = somme débits
        - sortant = somme crédits
        """
        stmt = (
            select(
                Ecriture.date_ecriture,
                func.coalesce(func.sum(EcritureLigne.debit_xof), 0),
                func.coalesce(func.sum(EcritureLigne.credit_xof), 0),
            )
            .join(PlanComptable, PlanComptable.id == EcritureLigne.compte_id)
            .join(Ecriture, Ecriture.id == EcritureLigne.ecriture_id)
            .where(
                EcritureLigne.tenant_id == self.tenant_id,
                PlanComptable.classe == 5,
                Ecriture.date_ecriture.between(debut, fin),
                Ecriture.statut == EcritureStatut.VALIDEE,
            )
            .group_by(Ecriture.date_ecriture)
            .order_by(Ecriture.date_ecriture)
        )
        rows = (await self.db.execute(stmt)).all()
        return [(r[0], int(r[1] or 0), int(r[2] or 0)) for r in rows]

    def _calculer_statistiques(
        self,
        flux: list[tuple[date, int, int]],
        horizon_histo: int,
        today: date,
    ) -> dict[str, Any]:
        """Calcule moyennes globales + par jour de semaine."""
        par_jour_semaine: dict[int, list[tuple[int, int]]] = defaultdict(list)
        jours_avec_donnees = 0

        for d, entrant, sortant in flux:
            if entrant == 0 and sortant == 0:
                continue
            jours_avec_donnees += 1
            weekday = d.weekday()
            par_jour_semaine[weekday].append((entrant, sortant))

        # Moyenne globale
        total_entrant = sum(e for _, e, _ in flux)
        total_sortant = sum(s for _, _, s in flux)
        moyenne_entrant_jour = total_entrant / max(horizon_histo, 1)
        moyenne_sortant_jour = total_sortant / max(horizon_histo, 1)

        # Moyenne par jour de semaine
        moyennes_semaine: dict[int, tuple[float, float]] = {}
        for wd in range(7):
            data = par_jour_semaine.get(wd, [])
            if data:
                moyennes_semaine[wd] = (
                    sum(e for e, _ in data) / len(data),
                    sum(s for _, s in data) / len(data),
                )
            else:
                moyennes_semaine[wd] = (moyenne_entrant_jour, moyenne_sortant_jour)

        return {
            "jours_avec_donnees": jours_avec_donnees,
            "moyenne_entrant_jour": moyenne_entrant_jour,
            "moyenne_sortant_jour": moyenne_sortant_jour,
            "par_jour_semaine": moyennes_semaine,
        }

    def _projeter(
        self,
        solde_initial: int,
        stats: dict[str, Any],
        today: date,
        horizon_jours: int,
    ) -> list[dict[str, Any]]:
        """Projection jour par jour avec saisonnalité hebdomadaire."""
        courbe: list[dict[str, Any]] = []
        solde = solde_initial
        for i in range(horizon_jours):
            d = today + timedelta(days=i)
            wd = d.weekday()
            moy_e, moy_s = stats["par_jour_semaine"][wd]
            # On arrondit et on applique un facteur de prudence (0.9)
            entrant = int(moy_e * 0.9)
            sortant = int(moy_s * 1.05)
            solde += entrant - sortant
            courbe.append({
                "date": d.isoformat(),
                "entrant": entrant,
                "sortant": sortant,
                "solde": solde,
            })
        return courbe

    async def _generer_resume(
        self,
        solde_initial: int,
        solde_final: int,
        entrant: int,
        sortant: int,
        alerte: bool,
        premiere_neg: date | None,
        fiabilite: str,
        horizon: int,
    ) -> str | None:
        """Résumé en langage naturel généré par l'IA."""
        if not settings.nlp_enabled:
            return self._resume_fallback(solde_initial, solde_final, alerte, premiere_neg)

        try:
            from app.integrations.openai_client import get_openai_client
            client = get_openai_client()
            prompt = f"""Voici la prévision de trésorerie d'une entreprise ivoirienne sur {horizon} jours :

- Solde initial : {solde_initial:,} FCFA
- Solde final prévu : {solde_final:,} FCFA
- Flux entrants cumulés : {entrant:,} FCFA
- Flux sortants cumulés : {sortant:,} FCFA
- Fiabilité du modèle : {fiabilite}
- Alerte trésorerie négative : {"OUI, première date " + premiere_neg.isoformat() if alerte and premiere_neg else "non"}

Rédige un résumé de 3 phrases maximum, en français, ton professionnel et direct, à destination du dirigeant. Termine par une recommandation concrète."""
            return await client.chat_text(
                "Tu es un directeur financier africain expérimenté.",
                prompt,
                temperature=0.2,
                max_tokens=200,
            )
        except Exception:
            logger.exception("[forecast] Résumé IA échoué")
            return self._resume_fallback(solde_initial, solde_final, alerte, premiere_neg)

    @staticmethod
    def _resume_fallback(
        solde_initial: int, solde_final: int, alerte: bool, premiere_neg: date | None
    ) -> str:
        tendance = "positive" if solde_final > solde_initial else "négative"
        msg = f"Votre trésorerie devrait évoluer de façon {tendance} sur la période. "
        if alerte and premiere_neg:
            msg += f"⚠️ Attention : un passage en négatif est prévu dès le {premiere_neg.strftime('%d/%m/%Y')}. "
            msg += "Anticipez un encaissement ou réduisez les dépenses non critiques."
        else:
            msg += "Aucun risque immédiat détecté."
        return msg
