"""
Service Analytique & Budget SYSCOHADA.

Fonctionnalités :
- CRUD axes, sections, clés de répartition
- Imputation analytique des lignes d'écriture (automatique ou manuelle)
- Génération et validation de budgets
- Contrôle budgétaire temps réel (cache + recalcul)
- Marge par section / produit
- Résultat analytique avec réconciliation CG
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.analytical_syscohada import (
    MethodeRepartition,
    NiveauAlerteBudget,
    SEUILS_ALERTE_DEFAUT,
    TypeAxeAnalytique,
    niveau_alerte_pour,
)
from app.models.analytical import (
    AllocationKey,
    AllocationKeyLine,
    AnalyticalAxis,
    AnalyticalEntry,
    AnalyticalSection,
    Budget,
    BudgetConsumption,
    BudgetLine,
)
from app.models.ecriture import Ecriture, EcritureLigne
from app.models.plan_comptable import PlanComptable
from app.schemas.analytical import (
    AllocationKeyCreate,
    AnalyticalAxisCreate,
    AnalyticalAxisUpdate,
    AnalyticalSectionCreate,
    AnalyticalSectionUpdate,
    BudgetControlLigne,
    BudgetControlOut,
    BudgetCreate,
    ImputationBatchRequest,
    MargeParSectionLigne,
    MargeParSectionOut,
    RentabiliteProduitLigne,
    RentabiliteProduitOut,
    RepartitionChargeOut,
    ResultatAnalytiqueOut,
)
from app.services.audit_service import AuditService

logger = logging.getLogger(__name__)


class AnalyticalService:
    def __init__(self, db: AsyncSession, tenant_id: UUID, user_id: UUID) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.audit = AuditService(db)

    # ═════════════════════════════════════════════════════════════════════
    # AXES ANALYTIQUES
    # ═════════════════════════════════════════════════════════════════════
    async def creer_axe(self, data: AnalyticalAxisCreate) -> AnalyticalAxis:
        existing = await self.db.scalar(
            select(AnalyticalAxis.id).where(
                AnalyticalAxis.tenant_id == self.tenant_id,
                AnalyticalAxis.code == data.code,
            )
        )
        if existing:
            raise HTTPException(409, f"Axe {data.code} déjà existant")

        axis = AnalyticalAxis(tenant_id=self.tenant_id, **data.model_dump())
        self.db.add(axis)
        await self.db.flush()

        await self.audit.log(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            action="ANALYTICAL_AXIS_CREATE",
            ressource="analytical_axis",
            ressource_id=axis.id,
            payload={"code": axis.code, "type": axis.type_axe},
        )
        return axis

    async def modifier_axe(
        self, axis_id: UUID, data: AnalyticalAxisUpdate
    ) -> AnalyticalAxis:
        axis = await self._get_axis(axis_id)
        for k, v in data.model_dump(exclude_unset=True).items():
            setattr(axis, k, v)
        await self.db.flush()
        return axis

    async def lister_axes(
        self, type_axe: str | None = None, actif_only: bool = True
    ) -> list[AnalyticalAxis]:
        stmt = select(AnalyticalAxis).where(AnalyticalAxis.tenant_id == self.tenant_id)
        if type_axe:
            stmt = stmt.where(AnalyticalAxis.type_axe == type_axe)
        if actif_only:
            stmt = stmt.where(AnalyticalAxis.actif.is_(True))
        stmt = stmt.order_by(AnalyticalAxis.ordre_affichage, AnalyticalAxis.code)
        return list((await self.db.execute(stmt)).scalars().all())

    # ═════════════════════════════════════════════════════════════════════
    # SECTIONS ANALYTIQUES
    # ═════════════════════════════════════════════════════════════════════
    async def creer_section(
        self, data: AnalyticalSectionCreate
    ) -> AnalyticalSection:
        await self._get_axis(data.axis_id)

        existing = await self.db.scalar(
            select(AnalyticalSection.id).where(
                AnalyticalSection.axis_id == data.axis_id,
                AnalyticalSection.code == data.code,
            )
        )
        if existing:
            raise HTTPException(409, f"Section {data.code} déjà existante dans cet axe")

        section = AnalyticalSection(tenant_id=self.tenant_id, **data.model_dump())
        self.db.add(section)
        await self.db.flush()
        return section

    async def modifier_section(
        self, section_id: UUID, data: AnalyticalSectionUpdate
    ) -> AnalyticalSection:
        section = await self._get_section(section_id)
        for k, v in data.model_dump(exclude_unset=True).items():
            setattr(section, k, v)
        await self.db.flush()
        return section

    async def lister_sections(
        self, axis_id: UUID | None = None, actif_only: bool = True
    ) -> list[AnalyticalSection]:
        stmt = select(AnalyticalSection).where(AnalyticalSection.tenant_id == self.tenant_id)
        if axis_id:
            stmt = stmt.where(AnalyticalSection.axis_id == axis_id)
        if actif_only:
            stmt = stmt.where(AnalyticalSection.actif.is_(True))
        stmt = stmt.order_by(AnalyticalSection.code)
        return list((await self.db.execute(stmt)).scalars().all())

    # ═════════════════════════════════════════════════════════════════════
    # CLÉS DE RÉPARTITION
    # ═════════════════════════════════════════════════════════════════════
    async def creer_cle_repartition(
        self, data: AllocationKeyCreate
    ) -> AllocationKey:
        await self._get_axis(data.axis_id)

        existing = await self.db.scalar(
            select(AllocationKey.id).where(
                AllocationKey.tenant_id == self.tenant_id,
                AllocationKey.code == data.code,
            )
        )
        if existing:
            raise HTTPException(409, f"Clé {data.code} déjà existante")

        key = AllocationKey(
            tenant_id=self.tenant_id,
            code=data.code,
            libelle=data.libelle,
            methode=data.methode,
            axis_id=data.axis_id,
            description=data.description,
        )
        self.db.add(key)
        await self.db.flush()

        for l in data.lignes:
            await self._get_section(l.section_id)
            self.db.add(AllocationKeyLine(
                tenant_id=self.tenant_id,
                key_id=key.id,
                section_id=l.section_id,
                pourcentage=Decimal(str(l.pourcentage)),
                valeur_base=Decimal(str(l.valeur_base)) if l.valeur_base else None,
            ))
        await self.db.flush()

        await self.audit.log(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            action="ALLOCATION_KEY_CREATE",
            ressource="allocation_key",
            ressource_id=key.id,
            payload={"code": key.code, "methode": key.methode},
        )
        return key

    async def lister_cles(self, actif_only: bool = True) -> list[AllocationKey]:
        stmt = select(AllocationKey).where(AllocationKey.tenant_id == self.tenant_id)
        if actif_only:
            stmt = stmt.where(AllocationKey.actif.is_(True))
        return list((await self.db.execute(stmt.order_by(AllocationKey.code))).scalars().all())

    # ═════════════════════════════════════════════════════════════════════
    # IMPUTATION ANALYTIQUE
    # ═════════════════════════════════════════════════════════════════════
    async def imputer_ligne(
        self, data: ImputationBatchRequest
    ) -> list[AnalyticalEntry]:
        """
        Impute une ligne d'écriture sur une ou plusieurs sections analytiques.
        La somme des montants imputés doit correspondre au montant de la ligne
        (débit ou crédit, valeur absolue).
        """
        # Récupérer la ligne d'écriture
        ligne = await self.db.scalar(
            select(EcritureLigne).where(
                EcritureLigne.id == data.ecriture_ligne_id,
                EcritureLigne.tenant_id == self.tenant_id,
            )
        )
        if ligne is None:
            raise HTTPException(404, "Ligne d'écriture introuvable")

        montant_ligne = int(ligne.debit_xof) if ligne.debit_xof > 0 else int(ligne.credit_xof)

        # Vérifier somme
        total_impute = sum(abs(i.montant) for i in data.imputations)
        if total_impute != montant_ligne:
            raise HTTPException(
                400,
                f"Somme des imputations ({total_impute}) ≠ montant de la ligne ({montant_ligne})",
            )

        # Supprimer anciennes imputations
        await self.db.execute(
            AnalyticalEntry.__table__.delete().where(
                AnalyticalEntry.ecriture_ligne_id == data.ecriture_ligne_id,
                AnalyticalEntry.tenant_id == self.tenant_id,
            )
        )

        entries: list[AnalyticalEntry] = []
        for imp in data.imputations:
            section = await self._get_section(imp.section_id)

            entry = AnalyticalEntry(
                tenant_id=self.tenant_id,
                ecriture_ligne_id=data.ecriture_ligne_id,
                ecriture_id=ligne.ecriture_id,
                section_id=imp.section_id,
                axis_id=section.axis_id,
                montant=imp.montant,
                type_imputation=imp.type_imputation,
                cle_repartition_id=imp.cle_repartition_id,
                pourcentage=Decimal(str(imp.pourcentage)) if imp.pourcentage is not None else None,
                created_by=self.user_id,
            )
            self.db.add(entry)
            entries.append(entry)

        await self.db.flush()
        await self.audit.log(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            action="ANALYTICAL_IMPUTATION",
            ressource="ecriture_ligne",
            ressource_id=data.ecriture_ligne_id,
            payload={"nb_imputations": len(entries), "montant": montant_ligne},
        )
        return entries

    async def imputer_automatiquement(
        self, ecriture_id: UUID, regles: dict[str, UUID] | None = None
    ) -> int:
        """
        Impute automatiquement toutes les lignes d'une écriture selon des règles
        (ex: compte 601 → section "PRODUCTION").
        `regles` : dict { prefixe_compte: section_id }
        """
        regles = regles or {}
        ecriture = await self.db.scalar(
            select(Ecriture).where(
                Ecriture.id == ecriture_id,
                Ecriture.tenant_id == self.tenant_id,
            )
        )
        if ecriture is None:
            raise HTTPException(404, "Écriture introuvable")

        lignes = (
            await self.db.execute(
                select(EcritureLigne, PlanComptable)
                .join(PlanComptable, PlanComptable.id == EcritureLigne.compte_id)
                .where(EcritureLigne.ecriture_id == ecriture.id)
            )
        ).all()

        nb_imputations = 0
        for ligne, plan in lignes:
            # Chercher une règle correspondante
            section_id = None
            for prefixe, sec_id in regles.items():
                if plan.compte.startswith(prefixe):
                    section_id = sec_id
                    break

            if section_id is None:
                continue

            montant = int(ligne.debit_xof) if ligne.debit_xof > 0 else int(ligne.credit_xof)
            if montant == 0:
                continue

            section = await self._get_section(section_id)
            self.db.add(AnalyticalEntry(
                tenant_id=self.tenant_id,
                ecriture_ligne_id=ligne.id,
                ecriture_id=ecriture.id,
                section_id=section.id,
                axis_id=section.axis_id,
                montant=montant,
                type_imputation="directe",
                created_by=self.user_id,
            ))
            nb_imputations += 1

        await self.db.flush()
        return nb_imputations

    async def simuler_repartition(
        self, cle_id: UUID, montant: int
    ) -> RepartitionChargeOut:
        """Simule la répartition d'un montant selon une clé."""
        key = await self._get_key(cle_id)
        lignes = (
            await self.db.execute(
                select(AllocationKeyLine).where(AllocationKeyLine.key_id == key.id)
            )
        ).scalars().all()

        repartitions = []
        total_verif = 0
        for l in lignes:
            section = await self._get_section(l.section_id)
            pct = float(l.pourcentage) / 100.0
            montant_part = int(montant * pct)
            total_verif += montant_part
            repartitions.append({
                "section_id": str(section.id),
                "section_code": section.code,
                "section_libelle": section.libelle,
                "pourcentage": float(l.pourcentage),
                "montant_reparti": montant_part,
            })

        # Ajustement du reliquat sur la première ligne
        if repartitions and total_verif != montant:
            repartitions[0]["montant_reparti"] += montant - total_verif

        return RepartitionChargeOut(
            cle_id=key.id,
            cle_libelle=key.libelle,
            montant_total=montant,
            methode=key.methode,
            repartitions=repartitions,
        )

    # ═════════════════════════════════════════════════════════════════════
    # BUDGETS
    # ═════════════════════════════════════════════════════════════════════
    async def creer_budget(self, data: BudgetCreate) -> Budget:
        # Vérifier unicité (code + version)
        existing = await self.db.scalar(
            select(func.max(Budget.version)).where(
                Budget.tenant_id == self.tenant_id,
                Budget.code == data.code,
            )
        )
        version = (int(existing) + 1) if existing else 1

        if data.section_id:
            await self._get_section(data.section_id)

        # Calcul des totaux
        total_produits = 0
        total_charges = 0
        for l in data.lignes:
            total = sum(l.mois)
            if l.nature == "produit":
                total_produits += total
            else:
                total_charges += total

        budget = Budget(
            tenant_id=self.tenant_id,
            section_id=data.section_id,
            code=data.code,
            libelle=data.libelle,
            description=data.description,
            annee=data.annee,
            date_debut=data.date_debut,
            date_fin=data.date_fin,
            version=version,
            statut="brouillon",
            total_produits=total_produits,
            total_charges=total_charges,
            resultat_prevu=total_produits - total_charges,
            created_by=self.user_id,
        )
        self.db.add(budget)
        await self.db.flush()

        for l in data.lignes:
            total = sum(l.mois)
            self.db.add(BudgetLine(
                tenant_id=self.tenant_id,
                budget_id=budget.id,
                section_id=data.section_id,
                compte=l.compte,
                libelle=l.libelle,
                nature=l.nature,
                m01=l.mois[0], m02=l.mois[1], m03=l.mois[2], m04=l.mois[3],
                m05=l.mois[4], m06=l.mois[5], m07=l.mois[6], m08=l.mois[7],
                m09=l.mois[8], m10=l.mois[9], m11=l.mois[10], m12=l.mois[11],
                total=total,
                hypothese=l.hypothese,
            ))

        await self.db.flush()
        await self.audit.log(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            action="BUDGET_CREATE",
            ressource="budget",
            ressource_id=budget.id,
            payload={"code": budget.code, "annee": budget.annee, "version": version},
        )
        return budget

    async def valider_budget(self, budget_id: UUID) -> Budget:
        budget = await self._get_budget(budget_id)
        if budget.statut not in ("brouillon", "soumis"):
            raise HTTPException(400, f"Budget {budget.statut} — non validable")

        budget.statut = "valide"
        budget.valide_at = datetime.now(timezone.utc)
        budget.valide_par = self.user_id

        # Recalculer le cache de consommation
        await self.recalculer_consommation(budget.id)

        await self.db.flush()
        return budget

    async def activer_budget(self, budget_id: UUID) -> Budget:
        budget = await self._get_budget(budget_id)
        if budget.statut != "valide":
            raise HTTPException(400, "Le budget doit être validé avant activation")

        # Désactiver les autres budgets actifs de même code/section
        await self.db.execute(
            Budget.__table__.update()
            .where(
                Budget.tenant_id == self.tenant_id,
                Budget.code == budget.code,
                Budget.id != budget.id,
                Budget.statut == "actif",
            )
            .values(statut="cloture")
        )
        budget.statut = "actif"
        await self.db.flush()
        return budget

    # ═════════════════════════════════════════════════════════════════════
    # CONTRÔLE BUDGÉTAIRE
    # ═════════════════════════════════════════════════════════════════════
    async def recalculer_consommation(self, budget_id: UUID) -> int:
        """
        Recalcule le cache de consommation budgétaire pour un budget.
        Appelé par le worker nocturne et à la validation du budget.
        """
        budget = await self._get_budget(budget_id)
        lignes = (
            await self.db.execute(
                select(BudgetLine).where(BudgetLine.budget_id == budget.id)
            )
        ).scalars().all()

        # Supprimer l'ancien cache
        await self.db.execute(
            BudgetConsumption.__table__.delete().where(
                BudgetConsumption.budget_id == budget.id
            )
        )

        now = datetime.now(timezone.utc)
        nb_crees = 0

        for bl in lignes:
            # Réalisé annuel cumulé (par compte analytique)
            realise_annuel = await self._calculer_realise_annuel(bl, budget)

            for mois in range(1, 13):
                budget_mois = bl.get_mois(mois)
                budget_cumule = sum(bl.get_mois(m) for m in range(1, mois + 1))

                # Réalisé jusqu'à ce mois
                realise_cumule = 0
                # Note simplifiée : on suppose que le réalisé annuel est réparti
                # proportionnellement au budget. En production, calculer mois par mois
                # en filtrant par date.
                realise_mois = int(realise_annuel / 12) if realise_annuel else 0
                realise_cumule = realise_mois * mois

                ecart_mois = budget_mois - realise_mois
                ecart_cumule = budget_cumule - realise_cumule
                conso_pct = (realise_cumule / budget_cumule * 100) if budget_cumule > 0 else 0.0

                niveau = niveau_alerte_pour(conso_pct / 100.0, SEUILS_ALERTE_DEFAUT)

                # Projection fin d'année (extrapolation linéaire)
                projection = int(realise_cumule * 12 / mois) if mois > 0 else 0

                self.db.add(BudgetConsumption(
                    tenant_id=self.tenant_id,
                    budget_id=budget.id,
                    budget_line_id=bl.id,
                    section_id=bl.section_id,
                    annee=budget.annee,
                    mois=mois,
                    budget_mois=budget_mois,
                    budget_cumule=budget_cumule,
                    realise_mois=realise_mois,
                    realise_cumule=realise_cumule,
                    ecart_mois=ecart_mois,
                    ecart_cumule=ecart_cumule,
                    consommation_pct=Decimal(str(round(conso_pct, 2))),
                    niveau_alerte=niveau,
                    projection_fin_annee=projection,
                    recalcule_at=now,
                ))
                nb_crees += 1

        await self.db.flush()
        return nb_crees

    async def _calculer_realise_annuel(
        self, bl: BudgetLine, budget: Budget
    ) -> int:
        """Calcule le réalisé annuel pour une ligne budgétaire."""
        # Filtrer par compte + section + année
        stmt = (
            select(
                func.coalesce(func.sum(EcritureLigne.debit_xof), 0),
                func.coalesce(func.sum(EcritureLigne.credit_xof), 0),
            )
            .join(PlanComptable, PlanComptable.id == EcritureLigne.compte_id)
            .join(Ecriture, Ecriture.id == EcritureLigne.ecriture_id)
            .where(
                EcritureLigne.tenant_id == self.tenant_id,
                PlanComptable.compte == bl.compte,
                Ecriture.date_ecriture >= budget.date_debut,
                Ecriture.date_ecriture <= budget.date_fin,
                Ecriture.statut == "validee",
            )
        )

        result = (await self.db.execute(stmt)).one()
        debit = int(result[0] or 0)
        credit = int(result[1] or 0)

        # Pour un compte de charge : réalisé = débit - crédit
        # Pour un compte de produit : réalisé = crédit - débit
        if bl.nature == "charge":
            return max(0, debit - credit)
        else:
            return max(0, credit - debit)

    async def controle_budgetaire(
        self, budget_id: UUID, mois_arret: int | None = None
    ) -> BudgetControlOut:
        """Contrôle budgétaire : compare budget vs réalisé à date."""
        budget = await self._get_budget(budget_id)
        mois_arret = mois_arret or date.today().month

        lignes = (
            await self.db.execute(
                select(BudgetLine).where(BudgetLine.budget_id == budget.id)
            )
        ).scalars().all()

        details: list[BudgetControlLigne] = []
        total_produits_budget = 0
        total_produits_realise = 0
        total_charges_budget = 0
        total_charges_realise = 0
        nb_vigilance = 0
        nb_alerte = 0
        nb_depassement = 0

        for bl in lignes:
            budget_annuel = bl.total
            budget_cumule = sum(bl.get_mois(m) for m in range(1, mois_arret + 1))
            realise = await self._calculer_realise_annuel(bl, budget)
            # Approximation : réalisé cumulé proportionnel au mois
            realise_cumule = int(realise * mois_arret / 12) if realise else 0

            ecart = budget_cumule - realise_cumule
            conso_pct = (realise_cumule / budget_cumule * 100) if budget_cumule > 0 else 0.0
            niveau = niveau_alerte_pour(conso_pct / 100.0, SEUILS_ALERTE_DEFAUT)
            projection = int(realise_cumule * 12 / mois_arret) if mois_arret > 0 else 0

            section_libelle = None
            if bl.section_id:
                section = await self.db.scalar(
                    select(AnalyticalSection).where(AnalyticalSection.id == bl.section_id)
                )
                section_libelle = section.libelle if section else None

            details.append(BudgetControlLigne(
                budget_line_id=bl.id,
                compte=bl.compte,
                libelle=bl.libelle,
                nature=bl.nature,
                section_id=bl.section_id,
                section_libelle=section_libelle,
                budget_annuel=budget_annuel,
                budget_cumule_a_date=budget_cumule,
                realise_cumule=realise_cumule,
                ecart=ecart,
                consommation_pct=round(conso_pct, 2),
                niveau_alerte=niveau,
                projection_fin_annee=projection,
            ))

            if bl.nature == "produit":
                total_produits_budget += budget_cumule
                total_produits_realise += realise_cumule
            else:
                total_charges_budget += budget_cumule
                total_charges_realise += realise_cumule

            if niveau == NiveauAlerteBudget.VIGILANCE:
                nb_vigilance += 1
            elif niveau == NiveauAlerteBudget.ALERTE:
                nb_alerte += 1
            elif niveau == NiveauAlerteBudget.DEPASSEMENT:
                nb_depassement += 1

        return BudgetControlOut(
            budget_id=budget.id,
            budget_libelle=budget.libelle,
            annee=budget.annee,
            mois_arret=mois_arret,
            total_produits_budget=total_produits_budget,
            total_produits_realise=total_produits_realise,
            total_charges_budget=total_charges_budget,
            total_charges_realise=total_charges_realise,
            resultat_budget=total_produits_budget - total_charges_budget,
            resultat_realise=total_produits_realise - total_charges_realise,
            nb_lignes_vigilance=nb_vigilance,
            nb_lignes_alerte=nb_alerte,
            nb_lignes_depassement=nb_depassement,
            lignes=details,
        )

    # ═════════════════════════════════════════════════════════════════════
    # TABLEAUX DE BORD ANALYTIQUES
    # ═════════════════════════════════════════════════════════════════════
    async def marge_par_section(
        self, axis_id: UUID, date_debut: date, date_fin: date
    ) -> MargeParSectionOut:
        """
        Calcule la marge par section analytique sur une période.
        Marge = Chiffre d'affaires (7xx) - Coûts directs (6xx imputés).
        """
        axis = await self._get_axis(axis_id)
        sections = await self.lister_sections(axis_id=axis.id)

        lignes: list[MargeParSectionLigne] = []
        total_ca = 0
        total_couts = 0

        for section in sections:
            ca = await self._calculer_produits_section(section.id, date_debut, date_fin)
            couts_directs = await self._calculer_charges_section(
                section.id, date_debut, date_fin, directes=True
            )
            charges_indirectes = await self._calculer_charges_section(
                section.id, date_debut, date_fin, directes=False
            )

            marge_brute = ca - couts_directs
            resultat = marge_brute - charges_indirectes
            taux_marge = (marge_brute / ca * 100) if ca > 0 else 0.0
            taux_rentab = (resultat / ca * 100) if ca > 0 else 0.0

            lignes.append(MargeParSectionLigne(
                section_id=section.id,
                section_code=section.code,
                section_libelle=section.libelle,
                chiffre_affaires=ca,
                couts_directs=couts_directs,
                marge_brute=marge_brute,
                taux_marge_pct=round(taux_marge, 2),
                charges_indirectes_reparties=charges_indirectes,
                resultat_analytique=resultat,
                taux_rentabilite_pct=round(taux_rentab, 2),
            ))

            total_ca += ca
            total_couts += couts_directs

        total_marge = total_ca - total_couts
        taux_global = (total_marge / total_ca * 100) if total_ca > 0 else 0.0

        return MargeParSectionOut(
            tenant_id=self.tenant_id,
            axis_id=axis.id,
            axis_libelle=axis.libelle,
            date_debut=date_debut,
            date_fin=date_fin,
            total_chiffre_affaires=total_ca,
            total_couts=total_couts,
            total_marge=total_marge,
            taux_marge_global_pct=round(taux_global, 2),
            lignes=lignes,
        )

    async def rentabilite_par_produit(
        self, date_debut: date, date_fin: date
    ) -> RentabiliteProduitOut:
        """Rentabilité par produit — basée sur l'axe analytique 'produit'."""
        # Trouver l'axe produit
        axis = await self.db.scalar(
            select(AnalyticalAxis).where(
                AnalyticalAxis.tenant_id == self.tenant_id,
                AnalyticalAxis.type_axe == TypeAxeAnalytique.PRODUIT,
                AnalyticalAxis.actif.is_(True),
            )
        )
        if axis is None:
            raise HTTPException(404, "Aucun axe analytique de type 'produit' configuré")

        sections = await self.lister_sections(axis_id=axis.id)
        lignes: list[RentabiliteProduitLigne] = []
        total_ca = 0
        total_marge = 0

        for section in sections:
            ca = await self._calculer_produits_section(section.id, date_debut, date_fin)
            couts = await self._calculer_charges_section(
                section.id, date_debut, date_fin, directes=True
            )
            marge = ca - couts
            taux = (marge / ca * 100) if ca > 0 else 0.0

            lignes.append(RentabiliteProduitLigne(
                section_id=section.id,
                code_produit=section.code,
                libelle_produit=section.libelle,
                quantite_vendue=0.0,   # À enrichir avec les données de vente
                chiffre_affaires=ca,
                cout_revient=couts,
                marge_unitaire=0,
                marge_totale=marge,
                taux_marge_pct=round(taux, 2),
            ))
            total_ca += ca
            total_marge += marge

        # Top/bottom 5
        triees = sorted(lignes, key=lambda x: x.marge_totale, reverse=True)
        top5 = triees[:5]
        bottom5 = list(reversed(triees[-5:])) if len(triees) > 5 else []

        taux_moyen = (total_marge / total_ca * 100) if total_ca > 0 else 0.0

        return RentabiliteProduitOut(
            tenant_id=self.tenant_id,
            date_debut=date_debut,
            date_fin=date_fin,
            nb_produits=len(lignes),
            chiffre_affaires_total=total_ca,
            marge_totale=total_marge,
            taux_marge_moyen_pct=round(taux_moyen, 2),
            top_5_rentables=top5,
            bottom_5_rentables=bottom5,
            lignes=lignes,
        )

    async def resultat_analytique(
        self, date_debut: date, date_fin: date
    ) -> ResultatAnalytiqueOut:
        """
        Résultat analytique global + réconciliation avec la CG.
        Le résultat analytique doit égaler le résultat net de la CG
        (compte 12x : résultat de l'exercice).
        """
        # CA analytique (produits 7xx imputés)
        ca_stmt = (
            select(func.coalesce(func.sum(AnalyticalEntry.montant), 0))
            .join(EcritureLigne, EcritureLigne.id == AnalyticalEntry.ecriture_ligne_id)
            .join(PlanComptable, PlanComptable.id == EcritureLigne.compte_id)
            .join(Ecriture, Ecriture.id == AnalyticalEntry.ecriture_id)
            .where(
                AnalyticalEntry.tenant_id == self.tenant_id,
                PlanComptable.classe == 7,
                Ecriture.date_ecriture.between(date_debut, date_fin),
            )
        )
        ca = int(await self.db.scalar(ca_stmt) or 0)

        # Charges directes (6xx imputées)
        charges_stmt = (
            select(func.coalesce(func.sum(AnalyticalEntry.montant), 0))
            .join(EcritureLigne, EcritureLigne.id == AnalyticalEntry.ecriture_ligne_id)
            .join(PlanComptable, PlanComptable.id == EcritureLigne.compte_id)
            .join(Ecriture, Ecriture.id == AnalyticalEntry.ecriture_id)
            .where(
                AnalyticalEntry.tenant_id == self.tenant_id,
                PlanComptable.classe == 6,
                Ecriture.date_ecriture.between(date_debut, date_fin),
            )
        )
        charges = int(await self.db.scalar(charges_stmt) or 0)

        resultat_analytique = ca - charges

        # Résultat CG (compte 12x)
        from app.services.financial_statement_service import FinancialStatementService
        # Récupérer via compte de résultat
        cg_stmt = (
            select(
                func.coalesce(func.sum(EcritureLigne.debit_xof), 0),
                func.coalesce(func.sum(EcritureLigne.credit_xof), 0),
            )
            .join(PlanComptable, PlanComptable.id == EcritureLigne.compte_id)
            .join(Ecriture, Ecriture.id == EcritureLigne.ecriture_id)
            .where(
                EcritureLigne.tenant_id == self.tenant_id,
                Ecriture.date_ecriture.between(date_debut, date_fin),
                Ecriture.statut == "validee",
            )
        )
        # Approximation : résultat net = (produits 7x - charges 6x)
        cg_produits = int(await self.db.scalar(
            select(func.coalesce(func.sum(EcritureLigne.credit_xof - EcritureLigne.debit_xof), 0))
            .join(PlanComptable, PlanComptable.id == EcritureLigne.compte_id)
            .join(Ecriture, Ecriture.id == EcritureLigne.ecriture_id)
            .where(
                EcritureLigne.tenant_id == self.tenant_id,
                PlanComptable.classe == 7,
                Ecriture.date_ecriture.between(date_debut, date_fin),
                Ecriture.statut == "validee",
            )
        ) or 0)
        cg_charges = int(await self.db.scalar(
            select(func.coalesce(func.sum(EcritureLigne.debit_xof - EcritureLigne.credit_xof), 0))
            .join(PlanComptable, PlanComptable.id == EcritureLigne.compte_id)
            .join(Ecriture, Ecriture.id == EcritureLigne.ecriture_id)
            .where(
                EcritureLigne.tenant_id == self.tenant_id,
                PlanComptable.classe == 6,
                Ecriture.date_ecriture.between(date_debut, date_fin),
                Ecriture.statut == "validee",
            )
        ) or 0)
        resultat_cg = cg_produits - cg_charges

        ecart = resultat_analytique - resultat_cg

        return ResultatAnalytiqueOut(
            tenant_id=self.tenant_id,
            date_debut=date_debut,
            date_fin=date_fin,
            chiffre_affaires=ca,
            couts_directs=charges,
            marge_brute=resultat_analytique,
            charges_indirectes=0,   # À enrichir avec les charges réparties
            resultat_analytique=resultat_analytique,
            reconciliation_avec_cg=resultat_cg,
            ecart_reconciliation=ecart,
            equilibre=abs(ecart) < 1000,   # Tolérance 1000 FCFA
        )

    # ═════════════════════════════════════════════════════════════════════
    # HELPERS
    # ═════════════════════════════════════════════════════════════════════
    async def _calculer_produits_section(
        self, section_id: UUID, date_debut: date, date_fin: date
    ) -> int:
        """Chiffre d'affaires imputé sur une section (comptes 7xx)."""
        stmt = (
            select(func.coalesce(func.sum(AnalyticalEntry.montant), 0))
            .join(EcritureLigne, EcritureLigne.id == AnalyticalEntry.ecriture_ligne_id)
            .join(PlanComptable, PlanComptable.id == EcritureLigne.compte_id)
            .join(Ecriture, Ecriture.id == AnalyticalEntry.ecriture_id)
            .where(
                AnalyticalEntry.tenant_id == self.tenant_id,
                AnalyticalEntry.section_id == section_id,
                PlanComptable.classe == 7,
                Ecriture.date_ecriture.between(date_debut, date_fin),
                Ecriture.statut == "validee",
            )
        )
        return int(await self.db.scalar(stmt) or 0)

    async def _calculer_charges_section(
        self,
        section_id: UUID,
        date_debut: date,
        date_fin: date,
        directes: bool = True,
    ) -> int:
        """Charges imputées sur une section (comptes 6xx)."""
        type_filter = "directe" if directes else "repartie"
        stmt = (
            select(func.coalesce(func.sum(AnalyticalEntry.montant), 0))
            .join(EcritureLigne, EcritureLigne.id == AnalyticalEntry.ecriture_ligne_id)
            .join(PlanComptable, PlanComptable.id == EcritureLigne.compte_id)
            .join(Ecriture, Ecriture.id == AnalyticalEntry.ecriture_id)
            .where(
                AnalyticalEntry.tenant_id == self.tenant_id,
                AnalyticalEntry.section_id == section_id,
                AnalyticalEntry.type_imputation == type_filter,
                PlanComptable.classe == 6,
                Ecriture.date_ecriture.between(date_debut, date_fin),
                Ecriture.statut == "validee",
            )
        )
        return int(await self.db.scalar(stmt) or 0)

    async def _get_axis(self, axis_id: UUID) -> AnalyticalAxis:
        axis = await self.db.scalar(
            select(AnalyticalAxis).where(
                AnalyticalAxis.id == axis_id,
                AnalyticalAxis.tenant_id == self.tenant_id,
            )
        )
        if axis is None:
            raise HTTPException(404, "Axe analytique introuvable")
        return axis

    async def _get_section(self, section_id: UUID) -> AnalyticalSection:
        s = await self.db.scalar(
            select(AnalyticalSection).where(
                AnalyticalSection.id == section_id,
                AnalyticalSection.tenant_id == self.tenant_id,
            )
        )
        if s is None:
            raise HTTPException(404, "Section analytique introuvable")
        return s

    async def _get_key(self, key_id: UUID) -> AllocationKey:
        k = await self.db.scalar(
            select(AllocationKey).where(
                AllocationKey.id == key_id,
                AllocationKey.tenant_id == self.tenant_id,
            )
        )
        if k is None:
            raise HTTPException(404, "Clé de répartition introuvable")
        return k

    async def _get_budget(self, budget_id: UUID) -> Budget:
        b = await self.db.scalar(
            select(Budget).where(
                Budget.id == budget_id,
                Budget.tenant_id == self.tenant_id,
            )
        )
        if b is None:
            raise HTTPException(404, "Budget introuvable")
        return b
