"""
Service Immobilisations & Amortissements SYSCOHADA.

Fonctionnalités :
- Création d'une immobilisation + génération du plan d'amortissement complet
- Calcul des dotations annuelles (linéaire / dégressif / variable / accéléré)
- Prorata temporis 1re année
- Génération des écritures de dotation (681x / 28x)
- Cession / rebut avec calcul de plus/moins-value
- Réévaluation
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.asset_syscohada import (
    COMPTE_PRODUIT_CESSION,
    COMPTE_TVA_COLLECTEE,
    COMPTE_VNC_CESSION,
    COMPTES_IMMOBILISATIONS,
    JOURNAL_CESSION,
    JOURNAL_IMMO,
    JOURNAL_OD,
    StatutImmobilisation,
    coefficient_degressif,
)
from app.models.asset import (
    AssetDisposal,
    AssetRevaluation,
    DepreciationEntry,
    FixedAsset,
)
from app.models.enums import EcritureSource
from app.schemas.asset import (
    DisposalCreate,
    FixedAssetCreate,
    RevaluationCreate,
)
from app.schemas.ecriture import EcritureCreate, LigneIn
from app.services.audit_service import AuditService
from app.services.journal_service import JournalService
from app.services.syscohada_service import SyscohadaService

logger = logging.getLogger(__name__)


class AssetService:
    def __init__(self, db: AsyncSession, tenant_id: UUID, user_id: UUID) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.audit = AuditService(db)

    # ═════════════════════════════════════════════════════════════════════
    # CRÉATION
    # ═════════════════════════════════════════════════════════════════════
    async def creer_immobilisation(
        self, data: FixedAssetCreate, comptabiliser_acquisition: bool = False
    ) -> FixedAsset:
        """
        Crée une immobilisation + génère le plan d'amortissement complet.
        Optionnellement, génère l'écriture d'acquisition (si facture d'achat directe).
        """
        info = COMPTES_IMMOBILISATIONS.get(data.famille)
        if info is None:
            raise HTTPException(400, f"Famille inconnue : {data.famille}")

        # Vérifier unicité code
        existing = await self.db.scalar(
            select(FixedAsset.id).where(
                FixedAsset.tenant_id == self.tenant_id,
                FixedAsset.code == data.code,
            )
        )
        if existing:
            raise HTTPException(409, f"Code immobilisation {data.code} déjà existant")

        base_amortissable = data.valeur_origine - data.valeur_residuelle
        taux = round(100.0 / data.duree_amortissement_ans, 4)
        coef = 1.0
        if data.methode_amortissement == "degressif":
            coef = coefficient_degressif(int(round(data.duree_amortissement_ans)))

        asset = FixedAsset(
            tenant_id=self.tenant_id,
            code=data.code,
            designation=data.designation,
            description=data.description,
            famille=data.famille,
            compte=info.compte,
            compte_amortissement=info.compte_amortissement,
            localisation=data.localisation,
            numero_serie=data.numero_serie,
            fournisseur=data.fournisseur,
            date_acquisition=data.date_acquisition,
            date_mise_en_service=data.date_mise_en_service,
            valeur_origine=data.valeur_origine,
            valeur_residuelle=data.valeur_residuelle,
            methode_amortissement=data.methode_amortissement,
            duree_amortissement_ans=data.duree_amortissement_ans,
            taux_amortissement=taux,
            coefficient_degressif=coef,
            base_amortissable=base_amortissable,
            amortissement_cumule=0,
            vnc=data.valeur_origine,
            statut="actif",
            totalement_amorti=False,
        )
        self.db.add(asset)
        await self.db.flush()

        # Génération du plan d'amortissement
        await self._generer_plan_amortissement(asset)

        # Écriture d'acquisition (facultatif)
        if comptabiliser_acquisition:
            ecriture_id = await self._generer_ecriture_acquisition(asset)
            asset.ecriture_acquisition_id = ecriture_id

        await self.db.flush()
        await self.audit.log(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            action="ASSET_CREATE",
            ressource="fixed_asset",
            ressource_id=asset.id,
            payload={
                "code": asset.code,
                "valeur": asset.valeur_origine,
                "methode": asset.methode_amortissement,
                "duree": asset.duree_amortissement_ans,
            },
        )
        return asset

    # ═════════════════════════════════════════════════════════════════════
    # PLAN D'AMORTISSEMENT
    # ═════════════════════════════════════════════════════════════════════
    async def _generer_plan_amortissement(self, asset: FixedAsset) -> None:
        """
        Génère l'intégralité du plan d'amortissement :
        - Linéaire : dotation constante
        - Dégressif : dotation = VNC début × taux dégressif, avec bascule linéaire
        - Variable / Accéléré : traité comme linéaire (MVP)
        """
        duree = float(asset.duree_amortissement_ans)
        annees_completes = int(duree)
        mois_supplementaires = round((duree - annees_completes) * 12)

        date_mise_service = asset.date_mise_en_service
        base = asset.base_amortissable
        vnc_courante = asset.valeur_origine
        cumul = 0
        dotation_constante = base / duree  # pour linéaire

        # Si dégressif : taux dégressif annuel
        taux_lineaire = 1.0 / duree
        taux_degressif = taux_lineaire * asset.coefficient_degressif if asset.methode_amortissement == "degressif" else 0

        # Boucle sur chaque exercice
        for i in range(annees_completes + (1 if mois_supplementaires > 0 else 0)):
            exercice = date_mise_service.year + i

            # ── Prorata temporis 1re année ───────────────────────────────
            if i == 0:
                # Nombre de jours restants de l'année de mise en service
                fin_annee = date(exercice, 12, 31)
                jours_restants = (fin_annee - date_mise_service).days + 1
                jours_annee = 365
                prorata = jours_restants / jours_annee
                periode_debut = date_mise_service
                periode_fin = fin_annee
            else:
                prorata = 1.0
                periode_debut = date(exercice, 1, 1)
                periode_fin = date(exercice, 12, 31)

            # Ajustement dernière année si durée avec décimales
            est_derniere_annee = (i == annees_completes) or (cumul + int(vnc_courante) == asset.valeur_origine)

            # ── Calcul de la dotation ────────────────────────────────────
            if asset.methode_amortissement == "lineaire" or asset.methode_amortissement in ("variable", "accelere"):
                dotation_theorique = int(dotation_constante * prorata)
            elif asset.methode_amortissement == "degressif":
                # Dégressif basé sur VNC début × taux dégressif
                # Mais bascule en linéaire si le taux linéaire sur la durée restante > taux dégressif
                annees_restantes = duree - i
                if annees_restantes <= 0:
                    dotation_theorique = 0
                else:
                    dotation_degressive = int(vnc_courante * taux_degressif)
                    dotation_lineaire_residuelle = int(vnc_courante / annees_restantes)
                    if i == 0:
                        # 1re année : prorata
                        dotation_theorique = int(vnc_courante * taux_degressif * prorata)
                    else:
                        dotation_theorique = max(dotation_degressive, dotation_lineaire_residuelle)
            else:
                dotation_theorique = 0

            # Ne jamais dépasser la base amortissable
            if cumul + dotation_theorique > base:
                dotation_theorique = base - cumul

            if dotation_theorique <= 0 and i > 0:
                break

            cumul_avant = cumul
            cumul = cumul + dotation_theorique
            vnc_debut = asset.valeur_origine - cumul_avant
            vnc_fin = asset.valeur_origine - cumul

            entry = DepreciationEntry(
                tenant_id=self.tenant_id,
                asset_id=asset.id,
                exercice=exercice,
                periode_debut=periode_debut,
                periode_fin=periode_fin,
                base_amortissement=base,
                taux_applique=taux_degressif * 100 if asset.methode_amortissement == "degressif" else asset.taux_amortissement,
                dotation=dotation_theorique,
                amortissement_cumule=cumul,
                vnc_debut=vnc_debut,
                vnc_fin=vnc_fin,
                jours_periode=(periode_fin - periode_debut).days + 1,
                prorata=prorata,
                comptabilise=False,
            )
            self.db.add(entry)

            if cumul >= base:
                asset.totalement_amorti = True
                break

        await self.db.flush()

    async def get_plan(self, asset_id: UUID) -> list[DepreciationEntry]:
        rows = (
            await self.db.execute(
                select(DepreciationEntry)
                .where(
                    DepreciationEntry.tenant_id == self.tenant_id,
                    DepreciationEntry.asset_id == asset_id,
                )
                .order_by(DepreciationEntry.exercice)
            )
        ).scalars().all()
        return list(rows)

    # ═════════════════════════════════════════════════════════════════════
    # COMPTABILISATION DES DOTATIONS
    # ═════════════════════════════════════════════════════════════════════
    async def comptabiliser_dotations(
        self, exercice: int, asset_id: UUID | None = None
    ) -> dict[str, Any]:
        """
        Comptabilise toutes les dotations d'un exercice (ou d'une seule immobilisation).

        Écriture par immobilisation :
          Débit 681x (Dotations aux amortissements)  dotation
          Crédit 28x (Amortissement de l'immo)        dotation
        """
        stmt = (
            select(DepreciationEntry)
            .where(
                DepreciationEntry.tenant_id == self.tenant_id,
                DepreciationEntry.exercice == exercice,
                DepreciationEntry.comptabilise.is_(False),
            )
        )
        if asset_id:
            stmt = stmt.where(DepreciationEntry.asset_id == asset_id)

        entries = (await self.db.execute(stmt)).scalars().all()
        if not entries:
            raise HTTPException(400, f"Aucune dotation à comptabiliser pour {exercice}")

        total_dotation = 0
        ecritures_creees: list[UUID] = []

        for entry in entries:
            asset = await self.db.scalar(
                select(FixedAsset).where(FixedAsset.id == entry.asset_id)
            )
            if asset is None:
                continue

            # Compte de dotation : 681x (par convention SYSCOHADA)
            compte_dotation = self._compte_dotation_depuis_immo(asset.compte)

            ecriture_id = await self._generer_ecriture_dotation(
                asset, entry, compte_dotation
            )
            entry.ecriture_id = ecriture_id
            entry.comptabilise = True
            entry.comptabilise_at = datetime.now(timezone.utc)
            total_dotation += entry.dotation
            ecritures_creees.append(ecriture_id)

        # Mettre à jour les totaux cumulés sur les immobilisations
        asset_ids = list({e.asset_id for e in entries})
        for aid in asset_ids:
            await self._recalculer_cumuls_asset(aid)

        await self.db.flush()
        await self.audit.log(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            action="ASSET_DOTATIONS_COMPTABILISEES",
            ressource="depreciation_entry",
            payload={
                "exercice": exercice,
                "nb_ecritures": len(ecritures_creees),
                "dotation_totale": total_dotation,
            },
        )
        return {
            "exercice": exercice,
            "nb_immobilisations": len(entries),
            "dotation_totale": total_dotation,
            "ecritures_ids": [str(e) for e in ecritures_creees],
        }

    async def _recalculer_cumuls_asset(self, asset_id: UUID) -> None:
        """Met à jour amortissement_cumule + vnc + statut sur l'immobilisation."""
        asset = await self.db.scalar(
            select(FixedAsset).where(FixedAsset.id == asset_id)
        )
        if asset is None:
            return

        cumul = await self.db.scalar(
            select(func.coalesce(func.sum(DepreciationEntry.dotation), 0))
            .where(
                DepreciationEntry.asset_id == asset_id,
                DepreciationEntry.comptabilise.is_(True),
            )
        )
        asset.amortissement_cumule = int(cumul or 0)
        asset.vnc = asset.valeur_origine - asset.amortissement_cumule

        if asset.amortissement_cumule >= asset.base_amortissable:
            asset.totalement_amorti = True
            if asset.statut == StatutImmobilisation.ACTIF:
                asset.statut = StatutImmobilisation.TOTALEMENT_AMORTI

    # ═════════════════════════════════════════════════════════════════════
    # CESSION / REBUT
    # ═════════════════════════════════════════════════════════════════════
    async def ceder_immobilisation(self, data: DisposalCreate) -> AssetDisposal:
        """
        Cession ou mise au rebut.

        Écritures SYSCOHADA :
        1. Sortie de l'immobilisation :
           Débit 28x (Amortissements cumulés)       cumul
           Débit 81x (VNC cédée)                    VNC
           Crédit 2xx (Immobilisation)               VO

        2. Prix de cession (si > 0) :
           Débit 5xx (Banque)                        TTC
           Crédit 82x (Produits des cessions)        HT
           Crédit 443x (TVA collectée)               TVA
        """
        asset = await self.db.scalar(
            select(FixedAsset).where(
                FixedAsset.id == data.asset_id,
                FixedAsset.tenant_id == self.tenant_id,
            )
        )
        if asset is None:
            raise HTTPException(404, "Immobilisation introuvable")
        if asset.statut in (StatutImmobilisation.CEDE, StatutImmobilisation.REBUTE):
            raise HTTPException(400, f"Immobilisation déjà {asset.statut}")

        # Vérifier qu'on n'est pas avant la mise en service
        if data.date_cession < asset.date_mise_en_service:
            raise HTTPException(400, "Date de cession antérieure à la mise en service")

        # ── Recalculer les cumuls jusqu'à la date de cession ──────────────
        cumul_a_date = await self._cumul_amortissement_a_date(asset, data.date_cession)

        vnc = asset.valeur_origine - cumul_a_date
        tva = int(data.prix_cession_ht * data.taux_tva) if data.prix_cession_ht > 0 else 0
        prix_ttc = data.prix_cession_ht + tva

        plus_value = max(0, data.prix_cession_ht - vnc)
        moins_value = max(0, vnc - data.prix_cession_ht)

        disposal = AssetDisposal(
            tenant_id=self.tenant_id,
            asset_id=asset.id,
            type_cession=data.type_cession,
            date_cession=data.date_cession,
            motif=data.motif,
            valeur_origine=asset.valeur_origine,
            amortissement_cumule=cumul_a_date,
            vnc=vnc,
            prix_cession_ht=data.prix_cession_ht,
            tva_collectee=tva,
            prix_cession_ttc=prix_ttc,
            plus_value=plus_value,
            moins_value=moins_value,
            acquereur=data.acquereur,
            reference_piece=data.reference_piece,
            created_by=self.user_id,
        )
        self.db.add(disposal)
        await self.db.flush()

        # ── Générer l'écriture de cession ─────────────────────────────────
        ecriture_id = await self._generer_ecriture_cession(asset, disposal)
        disposal.ecriture_id = ecriture_id

        # ── Mettre à jour l'immobilisation ────────────────────────────────
        asset.statut = (
            StatutImmobilisation.REBUTE if data.type_cession == "rebut"
            else StatutImmobilisation.CEDE
        )
        asset.amortissement_cumule = cumul_a_date
        asset.vnc = vnc
        asset.totalement_amorti = cumul_a_date >= asset.base_amortissable

        await self.db.flush()
        await self.audit.log(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            action="ASSET_DISPOSAL",
            ressource="asset_disposal",
            ressource_id=disposal.id,
            payload={
                "code": asset.code,
                "type": data.type_cession,
                "vnc": vnc,
                "prix": data.prix_cession_ht,
                "plus_value": plus_value,
                "moins_value": moins_value,
            },
        )
        return disposal

    async def _cumul_amortissement_a_date(self, asset: FixedAsset, date_sortie: date) -> int:
        """Calcule l'amortissement cumulé jusqu'à la date de cession (inclut le prorata)."""
        entries = (
            await self.db.execute(
                select(DepreciationEntry)
                .where(
                    DepreciationEntry.asset_id == asset.id,
                    DepreciationEntry.exercice <= date_sortie.year,
                )
                .order_by(DepreciationEntry.exercice)
            )
        ).scalars().all()

        cumul = 0
        for e in entries:
            if e.exercice < date_sortie.year:
                cumul += e.dotation
            elif e.exercice == date_sortie.year:
                # Prorata temporis sur l'exercice de cession
                jours_dans_exercice = (date_sortie - e.periode_debut).days + 1
                jours_totaux = (e.periode_fin - e.periode_debut).days + 1
                prorata = jours_dans_exercice / jours_totaux if jours_totaux > 0 else 1
                cumul += int(e.dotation * prorata)
        return cumul

    # ═════════════════════════════════════════════════════════════════════
    # RÉÉVALUATION
    # ═════════════════════════════════════════════════════════════════════
    async def reevaluer(self, data: RevaluationCreate) -> AssetRevaluation:
        """
        Réévaluation d'une immobilisation.
        L'écart entre VNC et valeur réévaluée est constaté en capitaux propres
        (compte 106x Écarts de réévaluation) ou en résultat (781x Reprises).
        """
        asset = await self.db.scalar(
            select(FixedAsset).where(
                FixedAsset.id == data.asset_id,
                FixedAsset.tenant_id == self.tenant_id,
            )
        )
        if asset is None:
            raise HTTPException(404, "Immobilisation introuvable")
        if asset.statut == StatutImmobilisation.CEDE:
            raise HTTPException(400, "Impossible de réévaluer une immobilisation cédée")

        vnc_avant = asset.vnc
        ecart = data.valeur_reevaluee - vnc_avant
        if ecart == 0:
            raise HTTPException(400, "Aucun écart de réévaluation")

        # Créer l'entrée de réévaluation
        reval = AssetRevaluation(
            tenant_id=self.tenant_id,
            asset_id=asset.id,
            date_reevaluation=data.date_reevaluation,
            vnc_avant=vnc_avant,
            valeur_reevaluee=data.valeur_reevaluee,
            ecart=ecart,
            nouvelle_duree_restante_ans=data.nouvelle_duree_restante_ans,
            created_by=self.user_id,
        )
        self.db.add(reval)
        await self.db.flush()

        # Écriture
        ecriture_id = await self._generer_ecriture_reevaluation(asset, reval)
        reval.ecriture_id = ecriture_id

        # Mettre à jour l'immobilisation : nouvelle VO, nouveau plan
        asset.valeur_origine = data.valeur_reevaluee + asset.amortissement_cumule
        asset.vnc = data.valeur_reevaluee
        asset.base_amortissable = asset.valeur_origine - asset.valeur_residuelle
        asset.statut = StatutImmobilisation.EN_REEVALUATION

        # Régénérer le plan d'amortissement sur la durée restante
        if data.nouvelle_duree_restante_ans:
            # Supprimer les entrées non comptabilisées futures
            await self.db.execute(
                DepreciationEntry.__table__.delete().where(
                    DepreciationEntry.asset_id == asset.id,
                    DepreciationEntry.comptabilise.is_(False),
                )
            )
            asset.duree_amortissement_ans = data.nouvelle_duree_restante_ans
            asset.methode_amortissement = "lineaire"  # après réévaluation, on repasse en linéaire
            await self._generer_plan_depuis_date(
                asset, data.date_reevaluation, data.valeur_reevaluee
            )

        await self.db.flush()
        await self.audit.log(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            action="ASSET_REVALUATION",
            ressource="asset_revaluation",
            ressource_id=reval.id,
            payload={
                "code": asset.code,
                "vnc_avant": vnc_avant,
                "valeur_reevaluee": data.valeur_reevaluee,
                "ecart": ecart,
            },
        )
        return reval

    async def _generer_plan_depuis_date(
        self, asset: FixedAsset, date_debut: date, nouvelle_valeur: int
    ) -> None:
        """Régénère un plan d'amortissement linéaire à partir d'une date donnée."""
        duree = float(asset.duree_amortissement_ans)
        base = nouvelle_valeur - asset.valeur_residuelle
        dotation = base / duree if duree > 0 else base

        vnc = nouvelle_valeur
        cumul = asset.amortissement_cumule
        exercice_courant = date_debut.year
        nb_annees = int(duree) + (1 if (duree - int(duree)) > 0 else 0)

        for i in range(nb_annees):
            exercice = exercice_courant + i
            if i == 0:
                # Prorata sur l'année en cours (à partir de date_debut)
                fin_annee = date(exercice, 12, 31)
                jours_restants = (fin_annee - date_debut).days + 1
                prorata = jours_restants / 365
                periode_debut = date_debut
                periode_fin = fin_annee
            else:
                prorata = 1.0
                periode_debut = date(exercice, 1, 1)
                periode_fin = date(exercice, 12, 31)

            dot = int(dotation * prorata)
            if cumul + dot > asset.valeur_origine - asset.valeur_residuelle:
                dot = asset.valeur_origine - asset.valeur_residuelle - cumul

            if dot <= 0:
                break

            cumul += dot
            vnc = asset.valeur_origine - cumul

            self.db.add(DepreciationEntry(
                tenant_id=self.tenant_id,
                asset_id=asset.id,
                exercice=exercice,
                periode_debut=periode_debut,
                periode_fin=periode_fin,
                base_amortissement=asset.valeur_origine - asset.valeur_residuelle,
                taux_applique=asset.taux_amortissement,
                dotation=dot,
                amortissement_cumule=cumul,
                vnc_debut=vnc + dot,
                vnc_fin=vnc,
                jours_periode=(periode_fin - periode_debut).days + 1,
                prorata=prorata,
                comptabilise=False,
                metadata_={"reevaluation": True},
            ))

        await self.db.flush()

    # ═════════════════════════════════════════════════════════════════════
    # ÉCRITURES SYSCOHADA
    # ═════════════════════════════════════════════════════════════════════
    async def _generer_ecriture_acquisition(self, asset: FixedAsset) -> UUID:
        """
        Écriture d'acquisition (si l'immobilisation est comptabilisée directement) :
          Débit 2xx (Immobilisation)              VO
          Crédit 481x / 401x (Fournisseur immo)  VO
        """
        lignes = [
            LigneIn(compte=asset.compte, libelle=f"Acquisition {asset.designation}", debit=asset.valeur_origine),
            LigneIn(compte="481000", libelle=f"Fournisseur immobilisation — {asset.fournisseur or 'N/A'}", credit=asset.valeur_origine),
        ]
        journal = await self._resolve_journal(JOURNAL_IMMO)
        syscohada = SyscohadaService(self.db, self.tenant_id, self.user_id)
        e = await syscohada.create(EcritureCreate(
            numero_piece=f"IMMO-{asset.code}",
            date_ecriture=asset.date_acquisition,
            code_journal=journal,
            libelle=f"Acquisition {asset.designation}",
            source=EcritureSource.SYSTEME,
            lignes=lignes,
        ))
        return e.id

    async def _generer_ecriture_dotation(
        self, asset: FixedAsset, entry: DepreciationEntry, compte_dotation: str
    ) -> UUID:
        """
        Écriture de dotation :
          Débit 681x (Dotation aux amortissements)   dotation
          Crédit 28x (Amortissement immobilisation)  dotation
        """
        lignes = [
            LigneIn(
                compte=compte_dotation,
                libelle=f"Dotation {asset.code} exercice {entry.exercice}",
                debit=entry.dotation,
            ),
            LigneIn(
                compte=asset.compte_amortissement,
                libelle=f"Amortissement {asset.code}",
                credit=entry.dotation,
            ),
        ]
        journal = await self._resolve_journal(JOURNAL_IMMO)
        syscohada = SyscohadaService(self.db, self.tenant_id, self.user_id)
        e = await syscohada.create(EcritureCreate(
            numero_piece=f"DOT-{asset.code}-{entry.exercice}",
            date_ecriture=entry.periode_fin,
            code_journal=journal,
            libelle=f"Dotation {asset.code} — {entry.exercice}",
            source=EcritureSource.SYSTEME,
            lignes=lignes,
        ))
        return e.id

    async def _generer_ecriture_cession(
        self, asset: FixedAsset, disposal: AssetDisposal
    ) -> UUID:
        """
        Écriture complète de cession (sortie d'actif + produit).
        """
        lignes: list[LigneIn] = [
            # Sortie des amortissements cumulés
            LigneIn(
                compte=asset.compte_amortissement,
                libelle=f"Reprise amort. {asset.code}",
                debit=disposal.amortissement_cumule,
            ),
            # Constatation de la VNC en charge (81x)
            LigneIn(
                compte=COMPTE_VNC_CESSION,
                libelle=f"VNC cédée {asset.code}",
                debit=disposal.vnc,
            ),
            # Sortie de l'immobilisation
            LigneIn(
                compte=asset.compte,
                libelle=f"Sortie {asset.designation}",
                credit=disposal.valeur_origine,
            ),
        ]

        # Prix de cession
        if disposal.prix_cession_ht > 0:
            lignes.append(LigneIn(
                compte="521000",
                libelle=f"Encaissement cession {asset.code}",
                debit=disposal.prix_cession_ttc,
            ))
            lignes.append(LigneIn(
                compte=COMPTE_PRODUIT_CESSION,
                libelle=f"Produit cession {asset.code}",
                credit=disposal.prix_cession_ht,
            ))
            if disposal.tva_collectee > 0:
                lignes.append(LigneIn(
                    compte=COMPTE_TVA_COLLECTEE,
                    libelle=f"TVA cession {asset.code}",
                    credit=disposal.tva_collectee,
                ))

        journal = await self._resolve_journal(JOURNAL_CESSION)
        syscohada = SyscohadaService(self.db, self.tenant_id, self.user_id)
        e = await syscohada.create(EcritureCreate(
            numero_piece=f"CESS-{asset.code}",
            date_ecriture=disposal.date_cession,
            code_journal=journal,
            libelle=f"{'Cession' if disposal.type_cession == 'cession' else 'Rebut'} {asset.designation}",
            reference_ext=disposal.reference_piece,
            source=EcritureSource.SYSTEME,
            lignes=lignes,
        ))
        return e.id

    async def _generer_ecriture_reevaluation(
        self, asset: FixedAsset, reval: AssetRevaluation
    ) -> UUID:
        """
        Écriture de réévaluation :
        - Écart positif : Débit 2xx (Immo) / Crédit 106x (Écarts de réévaluation)
        - Écart négatif : Débit 681x (Dotation) / Crédit 2xx (Immo)
        """
        if reval.ecart > 0:
            lignes = [
                LigneIn(compte=asset.compte, libelle=f"Réévaluation {asset.code}", debit=reval.ecart),
                LigneIn(compte="106100", libelle=f"Écart de réévaluation {asset.code}", credit=reval.ecart),
            ]
        else:
            ecart_abs = -reval.ecart
            lignes = [
                LigneIn(compte="681000", libelle=f"Dépréciation {asset.code}", debit=ecart_abs),
                LigneIn(compte=asset.compte, libelle=f"Réévaluation {asset.code}", credit=ecart_abs),
            ]

        journal = await self._resolve_journal(JOURNAL_OD)
        syscohada = SyscohadaService(self.db, self.tenant_id, self.user_id)
        e = await syscohada.create(EcritureCreate(
            numero_piece=f"REVAL-{asset.code}",
            date_ecriture=reval.date_reevaluation,
            code_journal=journal,
            libelle=f"Réévaluation {asset.designation}",
            source=EcritureSource.SYSTEME,
            lignes=lignes,
        ))
        return e.id

    # ═════════════════════════════════════════════════════════════════════
    # REPORTING
    # ═════════════════════════════════════════════════════════════════════
    async def tableau_immobilisations(self, date_arret: date) -> dict[str, Any]:
        """Tableau récapitulatif des immobilisations à une date donnée."""
        assets = (
            await self.db.execute(
                select(FixedAsset).where(
                    FixedAsset.tenant_id == self.tenant_id,
                    FixedAsset.statut.notin_([StatutImmobilisation.CEDE, StatutImmobilisation.REBUTE]),
                )
            )
        ).scalars().all()

        par_famille: dict[str, dict[str, int]] = {}
        total_vo = 0
        total_cumul = 0
        total_vnc = 0

        for a in assets:
            cumul = await self._cumul_amortissement_a_date(a, date_arret)
            vnc = a.valeur_origine - cumul
            fam = a.famille
            if fam not in par_famille:
                par_famille[fam] = {"valeur_origine": 0, "amortissement_cumule": 0, "vnc": 0, "nb": 0}
            par_famille[fam]["valeur_origine"] += a.valeur_origine
            par_famille[fam]["amortissement_cumule"] += cumul
            par_famille[fam]["vnc"] += vnc
            par_famille[fam]["nb"] += 1
            total_vo += a.valeur_origine
            total_cumul += cumul
            total_vnc += vnc

        return {
            "date_arret": date_arret,
            "nb_immobilisations": len(assets),
            "valeur_origine_totale": total_vo,
            "amortissement_cumule_total": total_cumul,
            "vnc_totale": total_vnc,
            "par_famille": par_famille,
        }

    # ═════════════════════════════════════════════════════════════════════
    # Helpers
    # ═════════════════════════════════════════════════════════════════════
    @staticmethod
    def _compte_dotation_depuis_immo(compte_immo: str) -> str:
        """
        Mappe le compte d'immobilisation vers le compte de dotation.
        Convention SYSCOHADA :
        - 21x → 6811 (Dotations aux amortissements des immo incorporelles)
        - 22x-24x → 6812 (Dotations aux amortissements des immo corporelles)
        - 26x/27x → 6813 (Dotations aux amortissements des immo financières)
        """
        if compte_immo.startswith("21"):
            return "681100"
        if compte_immo.startswith(("22", "23", "24")):
            return "681200"
        return "681300"

    async def _resolve_journal(self, code_prefere: str) -> str:
        """Retourne le code journal si existant, sinon OD."""
        try:
            await JournalService(self.db, self.tenant_id).get_by_code(code_prefere)
            return code_prefere
        except Exception:
            return "OD"
