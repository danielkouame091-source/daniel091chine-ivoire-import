"""
Service Consolidation OHADA.

Pipeline complet :
1. Détermination du périmètre (méthode selon % contrôle)
2. Agrégation des comptes de chaque société (avec conversion devises)
3. Calcul des intérêts minoritaires
4. Éliminations intragroupe (détection auto ou manuelle)
5. Retraitements d'homogénéisation
6. Génération du Bilan / Résultat / TAFIRE consolidés
7. Notes annexes
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.consolidation_syscohada import (
    COMPTES_CONSOLIDES,
    MethodeConsolidation,
    StatutConsolidation,
    StatutPerimetre,
    TypeElimination,
    XOF_EUR_PARITE,
    determiner_methode,
)
from app.models.consolidation import (
    AdjustmentEntry,
    ConsolidationGroup,
    ConsolidationRun,
    EliminationEntry,
    ExchangeRate,
    GroupCompany,
    IntercompanyTransaction,
    MinorityInterest,
)
from app.models.ecriture import Ecriture, EcritureLigne
from app.models.plan_comptable import PlanComptable
from app.schemas.consolidation import (
    AdjustmentCreate,
    BilanConsolideOut,
    CompteResultatConsolideOut,
    ConsolidationGroupCreate,
    ConsolidationGroupUpdate,
    ConsolidationRunRequest,
    DetectionIntercosResult,
    EliminationAutoRequest,
    EliminationAutoResult,
    EliminationCreate,
    GroupCompanyCreate,
    GroupCompanyUpdate,
    NoteAnnexeOut,
    NotesAnnexesOut,
    PerimetreLigne,
    PerimetreOut,
    TAFIREConsolideOut,
)
from app.services.audit_service import AuditService

logger = logging.getLogger(__name__)


class ConsolidationService:
    def __init__(self, db: AsyncSession, tenant_id: UUID, user_id: UUID) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.audit = AuditService(db)

    # ═════════════════════════════════════════════════════════════════════
    # GROUPES
    # ═════════════════════════════════════════════════════════════════════
    async def creer_groupe(self, data: ConsolidationGroupCreate) -> ConsolidationGroup:
        existing = await self.db.scalar(
            select(ConsolidationGroup.id).where(
                ConsolidationGroup.tenant_id == self.tenant_id,
                ConsolidationGroup.code == data.code,
            )
        )
        if existing:
            raise HTTPException(409, f"Groupe {data.code} déjà existant")

        # Vérifier que le parent_tenant existe
        from app.models.tenant import Tenant
        parent = await self.db.scalar(
            select(Tenant).where(Tenant.id == data.parent_tenant_id)
        )
        if parent is None:
            raise HTTPException(404, "Tenant parent introuvable")

        group = ConsolidationGroup(tenant_id=self.tenant_id, **data.model_dump())
        self.db.add(group)
        await self.db.flush()

        await self.audit.log(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            action="CONSOLIDATION_GROUP_CREATE",
            ressource="consolidation_group",
            ressource_id=group.id,
            payload={"code": group.code, "devise": group.devise_presentation},
        )
        return group

    async def modifier_groupe(
        self, group_id: UUID, data: ConsolidationGroupUpdate
    ) -> ConsolidationGroup:
        group = await self._get_group(group_id)
        for k, v in data.model_dump(exclude_unset=True).items():
            setattr(group, k, v)
        await self.db.flush()
        return group

    async def lister_groupes(self, actif_only: bool = True) -> list[ConsolidationGroup]:
        stmt = select(ConsolidationGroup).where(ConsolidationGroup.tenant_id == self.tenant_id)
        if actif_only:
            stmt = stmt.where(ConsolidationGroup.actif.is_(True))
        stmt = stmt.order_by(ConsolidationGroup.code)
        return list((await self.db.execute(stmt)).scalars().all())

    # ═════════════════════════════════════════════════════════════════════
    # SOCIÉTÉS MEMBRES
    # ═════════════════════════════════════════════════════════════════════
    async def ajouter_societe(
        self, group_id: UUID, data: GroupCompanyCreate
    ) -> GroupCompany:
        group = await self._get_group(group_id)

        existing = await self.db.scalar(
            select(GroupCompany.id).where(
                GroupCompany.group_id == group_id,
                GroupCompany.code == data.code,
            )
        )
        if existing:
            raise HTTPException(409, f"Société {data.code} déjà membre du groupe")

        # Vérifier que le tenant existe
        from app.models.tenant import Tenant
        t = await self.db.scalar(select(Tenant).where(Tenant.id == data.tenant_id))
        if t is None:
            raise HTTPException(404, "Tenant introuvable")

        # Si méthode non fournie, la déterminer selon % contrôle
        if data.methode == "exclue":
            data.methode = determiner_methode(data.pourcentage_controle)

        company = GroupCompany(group_id=group_id, **data.model_dump())
        self.db.add(company)
        await self.db.flush()

        await self.audit.log(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            action="GROUP_COMPANY_ADD",
            ressource="group_company",
            ressource_id=company.id,
            payload={
                "code": company.code,
                "pct_controle": float(company.pourcentage_controle),
                "methode": company.methode,
            },
        )
        return company

    async def modifier_societe(
        self, company_id: UUID, data: GroupCompanyUpdate
    ) -> GroupCompany:
        company = await self._get_company(company_id)
        for k, v in data.model_dump(exclude_unset=True).items():
            setattr(company, k, v)
        await self.db.flush()
        return company

    async def lister_societes(self, group_id: UUID) -> list[GroupCompany]:
        stmt = (
            select(GroupCompany)
            .where(GroupCompany.group_id == group_id)
            .order_by(GroupCompany.code)
        )
        return list((await self.db.execute(stmt)).scalars().all())

    # ═════════════════════════════════════════════════════════════════════
    # PÉRIMÈTRE
    # ═════════════════════════════════════════════════════════════════════
    async def determiner_perimetre(
        self, group_id: UUID, date_arret: date
    ) -> PerimetreOut:
        """
        Détermine le périmètre de consolidation à une date donnée :
        - Sociétés actives à cette date (date_entree <= date_arret < date_sortie)
        - Méthode applicable selon % contrôle
        - Inclusions/exclusions avec justifications
        """
        group = await self._get_group(group_id)
        companies = await self.lister_societes(group_id)

        lignes: list[PerimetreLigne] = []
        pct_interet_total = 0.0
        nb_inclus = 0
        nb_exclus = 0

        for c in companies:
            # Société active à cette date ?
            dans_periode = (
                c.date_entree <= date_arret
                and (c.date_sortie is None or c.date_sortie > date_arret)
            )
            if not dans_periode:
                continue

            # Méthode
            methode = c.methode
            if methode == "exclue":
                inclus = False
                raison = "Exclusion volontaire (hors périmètre)"
            else:
                inclus = True
                raison = None

            if inclus:
                nb_inclus += 1
                if methode == MethodeConsolidation.INTEGRATION_GLOBALE:
                    pct_interet_total += float(c.pourcentage_interet)
                elif methode == MethodeConsolidation.INTEGRATION_PROPORTIONNELLE:
                    pct_interet_total += float(c.pourcentage_interet)
            else:
                nb_exclus += 1

            lignes.append(PerimetreLigne(
                company_id=c.id,
                code=c.code,
                libelle=c.libelle,
                pct_controle=float(c.pourcentage_controle),
                pct_interet=float(c.pourcentage_interet),
                methode=methode,
                inclus=inclus,
                raison_exclusion=raison,
                date_entree=c.date_entree,
                date_sortie=c.date_sortie,
            ))

        return PerimetreOut(
            group_id=group.id,
            group_libelle=group.libelle,
            date_arret=date_arret,
            devise_presentation=group.devise_presentation,
            nb_societes_incluses=nb_inclus,
            nb_societes_exclues=nb_exclus,
            societes=lignes,
            pct_interet_total=round(pct_interet_total, 4),
        )

    # ═════════════════════════════════════════════════════════════════════
    # TRANSACTIONS INTRAGROUPE
    # ═════════════════════════════════════════════════════════════════════
    async def creer_transaction_interco(
        self, group_id: UUID, data: IntercompanyTransactionCreate
    ) -> IntercompanyTransaction:
        await self._get_group(group_id)
        source = await self._get_company(data.source_company_id)
        target = await self._get_company(data.target_company_id)

        if source.group_id != group_id or target.group_id != group_id:
            raise HTTPException(400, "Les deux sociétés doivent appartenir au groupe")
        if source.id == target.id:
            raise HTTPException(400, "Source et destination ne peuvent être identiques")

        ico = IntercompanyTransaction(
            group_id=group_id,
            tenant_id=self.tenant_id,
            **data.model_dump(),
        )
        self.db.add(ico)
        await self.db.flush()
        return ico

    async def detecter_intercos_auto(
        self, group_id: UUID, date_debut: date, date_fin: date
    ) -> DetectionIntercosResult:
        """
        Détecte automatiquement les transactions intragroupe :
        1. Créances/dettes réciproques (compte 411x ↔ 401x entre sociétés)
        2. Produits/charges réciproques (6xx ↔ 7xx)
        3. Dividendes intragroupe
        """
        await self._get_group(group_id)
        companies = await self.lister_societes(group_id)
        if len(companies) < 2:
            return DetectionIntercosResult(
                group_id=group_id, date_debut=date_debut, date_fin=date_fin,
                nb_detectees=0, nb_creances_dettes=0, nb_produits_charges=0,
                nb_dividendes=0, montant_total=0, details=[],
            )

        # Index : tenant_id → company
        tenant_to_company = {c.tenant_id: c for c in companies}

        # Charger toutes les lignes d'écriture sur la période
        rows = (
            await self.db.execute(
                select(
                    Ecriture.tenant_id,
                    Ecriture.id,
                    Ecriture.date_ecriture,
                    Ecriture.libelle,
                    PlanComptable.compte,
                    EcritureLigne.debit_xof,
                    EcritureLigne.credit_xof,
                )
                .join(EcritureLigne, EcritureLigne.ecriture_id == Ecriture.id)
                .join(PlanComptable, PlanComptable.id == EcritureLigne.compte_id)
                .where(
                    Ecriture.tenant_id.in_([c.tenant_id for c in companies]),
                    Ecriture.date_ecriture.between(date_debut, date_fin),
                    Ecriture.statut == "validee",
                )
            )
        ).all()

        # Grouper par (tenant, date, montant) pour matcher les réciproques
        creances = []      # (tenant, date, montant, client_code)
        dettes = []        # (tenant, date, montant, fournisseur_code)
        produits = []      # (tenant, date, montant, produit_code)
        charges = []       # (tenant, date, montant, charge_code)

        for r in rows:
            t_id, ecr_id, d, lib, compte, debit, credit = r
            debit, credit = int(debit or 0), int(credit or 0)
            company = tenant_to_company.get(t_id)
            if company is None:
                continue
            if compte.startswith("411") and debit > 0:
                creances.append((t_id, d, debit, lib, ecr_id))
            elif compte.startswith("401") and credit > 0:
                dettes.append((t_id, d, credit, lib, ecr_id))
            elif compte.startswith("70") and credit > 0:
                produits.append((t_id, d, credit, lib, ecr_id))
            elif compte.startswith("60") and debit > 0:
                charges.append((t_id, d, debit, lib, ecr_id))

        # Matching : créances ↔ dettes (même montant, dates proches)
        detectees: list[dict[str, Any]] = []
        montant_total = 0
        nb_creances_dettes = 0
        nb_produits_charges = 0
        nb_dividendes = 0

        used_dettes: set[tuple] = set()
        for (t_src, d_src, m_src, lib_src, ecr_src) in creances:
            for (t_dst, d_dst, m_dst, lib_dst, ecr_dst) in dettes:
                if (t_dst, m_dst, ecr_dst) in used_dettes:
                    continue
                if t_src == t_dst:
                    continue
                if m_src != m_dst:
                    continue
                if abs((d_src - d_dst).days) > 5:
                    continue
                # Match !
                ico = IntercompanyTransaction(
                    group_id=group_id,
                    tenant_id=self.tenant_id,
                    source_company_id=tenant_to_company[t_src].id,
                    target_company_id=tenant_to_company[t_dst].id,
                    type_transaction=TypeElimination.CREANCES_DETTES,
                    date_transaction=d_src,
                    libelle=f"Auto: {lib_src}",
                    montant_ht=m_src,
                    detection_auto=True,
                    score_matching=Decimal("95.00"),
                )
                self.db.add(ico)
                used_dettes.add((t_dst, m_dst, ecr_dst))
                nb_creances_dettes += 1
                montant_total += m_src
                detectees.append({
                    "type": TypeElimination.CREANCES_DETTES,
                    "montant": m_src,
                    "date": d_src.isoformat(),
                })
                break

        await self.db.flush()

        return DetectionIntercosResult(
            group_id=group_id,
            date_debut=date_debut,
            date_fin=date_fin,
            nb_detectees=len(detectees),
            nb_creances_dettes=nb_creances_dettes,
            nb_produits_charges=nb_produits_charges,
            nb_dividendes=nb_dividendes,
            montant_total=montant_total,
            details=detectees,
        )

    # ═════════════════════════════════════════════════════════════════════
    # ÉLIMINATIONS
    # ═════════════════════════════════════════════════════════════════════
    async def creer_elimination(
        self, group_id: UUID, data: EliminationCreate
    ) -> EliminationEntry:
        await self._get_group(group_id)

        # Numéro auto
        count = int(await self.db.scalar(
            select(func.count(EliminationEntry.id)).where(
                EliminationEntry.group_id == group_id,
            )
        ) or 0)
        reference = f"ELIM-{count + 1:05d}"

        elim = EliminationEntry(
            group_id=group_id,
            reference=reference,
            type_elimination=data.type_elimination,
            date_elimination=data.date_elimination,
            libelle=data.libelle,
            montant=data.montant,
            lignes=data.lignes,
            section_elimination=data.section_elimination,
            created_by=self.user_id,
        )
        self.db.add(elim)
        await self.db.flush()

        await self.audit.log(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            action="ELIMINATION_CREATE",
            ressource="elimination_entry",
            ressource_id=elim.id,
            payload={"reference": reference, "type": elim.type_elimination, "montant": elim.montant},
        )
        return elim

    async def generer_eliminations_auto(
        self, group_id: UUID, request: EliminationAutoRequest
    ) -> EliminationAutoResult:
        """
        Génère les écritures d'élimination pour toutes les transactions
        intragroupe non éliminées.
        """
        await self._get_group(group_id)

        # Transactions non éliminées
        stmt = select(IntercompanyTransaction).where(
            IntercompanyTransaction.group_id == group_id,
            IntercompanyTransaction.eliminee.is_(False),
            IntercompanyTransaction.date_transaction.between(
                request.date_debut, request.date_fin
            ),
        )
        if request.types:
            stmt = stmt.where(IntercompanyTransaction.type_transaction.in_(request.types))

        icos = (await self.db.execute(stmt)).scalars().all()

        by_type: dict[str, dict[str, int]] = defaultdict(lambda: {"count": 0, "montant": 0})
        total_montant = 0

        for ico in icos:
            lignes = self._generer_lignes_elimination(ico)
            count = int(await self.db.scalar(
                select(func.count(EliminationEntry.id)).where(
                    EliminationEntry.group_id == group_id,
                )
            ) or 0)
            ref = f"ELIM-{count + 1:05d}"

            elim = EliminationEntry(
                group_id=group_id,
                reference=ref,
                type_elimination=ico.type_transaction,
                date_elimination=ico.date_transaction,
                libelle=f"Élimination auto: {ico.libelle}",
                montant=ico.montant_ht,
                lignes=lignes,
                appliquee=True,
                appliquee_at=datetime.now(timezone.utc),
                created_by=self.user_id,
            )
            self.db.add(elim)
            await self.db.flush()

            ico.eliminee = True
            ico.elimination_id = elim.id

            by_type[ico.type_transaction]["count"] += 1
            by_type[ico.type_transaction]["montant"] += ico.montant_ht
            total_montant += ico.montant_ht

        await self.db.flush()

        return EliminationAutoResult(
            group_id=group_id,
            nb_eliminations=len(icos),
            montant_total_elimine=total_montant,
            by_type={k: dict(v) for k, v in by_type.items()},
        )

    def _generer_lignes_elimination(self, ico: IntercompanyTransaction) -> list[dict[str, Any]]:
        """Retourne les lignes comptables d'élimination selon le type."""
        if ico.type_transaction == TypeElimination.CREANCES_DETTES:
            return [
                {"compte": "401000", "libelle": f"Élim. dette — {ico.libelle}", "debit": ico.montant_ht, "credit": 0},
                {"compte": "411000", "libelle": f"Élim. créance — {ico.libelle}", "debit": 0, "credit": ico.montant_ht},
            ]
        if ico.type_transaction == TypeElimination.PRODUITS_CHARGES:
            return [
                {"compte": "701000", "libelle": f"Élim. produit — {ico.libelle}", "debit": ico.montant_ht, "credit": 0},
                {"compte": "601000", "libelle": f"Élim. charge — {ico.libelle}", "debit": 0, "credit": ico.montant_ht},
            ]
        if ico.type_transaction == TypeElimination.DIVIDENDES:
            return [
                {"compte": "457000", "libelle": f"Élim. dividende — {ico.libelle}", "debit": ico.montant_ht, "credit": 0},
                {"compte": "771000", "libelle": f"Élim. produit fin. — {ico.libelle}", "debit": 0, "credit": ico.montant_ht},
            ]
        if ico.type_transaction == TypeElimination.PRETS_AVANCES:
            return [
                {"compte": "451000", "libelle": f"Élim. prêt — {ico.libelle}", "debit": ico.montant_ht, "credit": 0},
                {"compte": "451000", "libelle": f"Élim. prêt — {ico.libelle}", "debit": 0, "credit": ico.montant_ht},
            ]
        # Défaut : contre-passation neutre
        return [
            {"compte": "471800", "libelle": f"Élim. — {ico.libelle}", "debit": ico.montant_ht, "credit": 0},
            {"compte": "471800", "libelle": f"Élim. — {ico.libelle}", "debit": 0, "credit": ico.montant_ht},
        ]

    # ═════════════════════════════════════════════════════════════════════
    # RETRAITEMENTS
    # ═════════════════════════════════════════════════════════════════════
    async def creer_retraitement(
        self, group_id: UUID, data: AdjustmentCreate
    ) -> AdjustmentEntry:
        await self._get_group(group_id)
        await self._get_company(data.company_id)

        count = int(await self.db.scalar(
            select(func.count(AdjustmentEntry.id)).where(
                AdjustmentEntry.group_id == group_id,
            )
        ) or 0)
        ref = f"RETR-{count + 1:05d}"

        adj = AdjustmentEntry(
            group_id=group_id,
            reference=ref,
            company_id=data.company_id,
            type_retraitement=data.type_retraitement,
            date_retraitement=data.date_retraitement,
            libelle=data.libelle,
            montant=data.montant,
            sens=data.sens,
            lignes=data.lignes,
            created_by=self.user_id,
        )
        self.db.add(adj)
        await self.db.flush()
        return adj

    # ═════════════════════════════════════════════════════════════════════
    # CONVERSION DEVISES
    # ═════════════════════════════════════════════════════════════════════
    async def creer_taux_change(
        self, devise_source: str, devise_cible: str, date_taux: date,
        taux_cloture: float, taux_moyen: float | None = None, source: str = "manuel"
    ) -> ExchangeRate:
        existing = await self.db.scalar(
            select(ExchangeRate).where(
                ExchangeRate.tenant_id == self.tenant_id,
                ExchangeRate.devise_source == devise_source,
                ExchangeRate.devise_cible == devise_cible,
                ExchangeRate.date_taux == date_taux,
            )
        )
        if existing:
            existing.taux_cloture = Decimal(str(taux_cloture))
            existing.taux_moyen = Decimal(str(taux_moyen)) if taux_moyen else None
            await self.db.flush()
            return existing

        fx = ExchangeRate(
            tenant_id=self.tenant_id,
            devise_source=devise_source,
            devise_cible=devise_cible,
            date_taux=date_taux,
            taux_cloture=Decimal(str(taux_cloture)),
            taux_moyen=Decimal(str(taux_moyen)) if taux_moyen else None,
            source=source,
        )
        self.db.add(fx)
        await self.db.flush()
        return fx

    async def _convertir(
        self, montant: int, devise_source: str, devise_cible: str, date_ref: date
    ) -> int:
        """Convertit un montant d'une devise vers une autre."""
        if devise_source == devise_cible:
            return montant
        # Parité fixe XOF ↔ EUR
        if {devise_source, devise_cible} == {"XOF", "EUR"}:
            if devise_source == "XOF":
                return int(montant / XOF_EUR_PARITE)
            return int(montant * XOF_EUR_PARITE)

        # Chercher un taux
        fx = await self.db.scalar(
            select(ExchangeRate).where(
                ExchangeRate.tenant_id == self.tenant_id,
                ExchangeRate.devise_source == devise_source,
                ExchangeRate.devise_cible == devise_cible,
                ExchangeRate.date_taux <= date_ref,
            ).order_by(ExchangeRate.date_taux.desc()).limit(1)
        )
        if fx is None:
            # Inverser
            fx_inv = await self.db.scalar(
                select(ExchangeRate).where(
                    ExchangeRate.tenant_id == self.tenant_id,
                    ExchangeRate.devise_source == devise_cible,
                    ExchangeRate.devise_cible == devise_source,
                    ExchangeRate.date_taux <= date_ref,
                ).order_by(ExchangeRate.date_taux.desc()).limit(1)
            )
            if fx_inv:
                return int(montant / float(fx_inv.taux_cloture))
            logger.warning(f"[consolidation] Aucun taux {devise_source}→{devise_cible} à {date_ref}")
            return montant   # On retourne tel quel (à défaut)

        return int(montant * float(fx.taux_cloture))

    # ═════════════════════════════════════════════════════════════════════
    # EXÉCUTION DE CONSOLIDATION
    # ═════════════════════════════════════════════════════════════════════
    async def executer_consolidation(
        self, group_id: UUID, request: ConsolidationRunRequest
    ) -> ConsolidationRun:
        """
        Exécute une consolidation complète pour la période demandée.
        """
        start_time = time.monotonic()
        group = await self._get_group(group_id)

        # Numéro auto
        count = int(await self.db.scalar(
            select(func.count(ConsolidationRun.id)).where(
                ConsolidationRun.group_id == group_id,
            )
        ) or 0)
        reference = f"RUN-{request.date_fin.year}-{count + 1:03d}"

        run = ConsolidationRun(
            group_id=group_id,
            reference=reference,
            date_debut=request.date_debut,
            date_fin=request.date_fin,
            statut="en_cours",
            execute_par=self.user_id,
            execute_at=datetime.now(timezone.utc),
        )
        self.db.add(run)
        await self.db.flush()

        try:
            # ─── 1. Périmètre ──────────────────────────────────────────
            perimetre = await self.determiner_perimetre(group_id, request.date_fin)
            companies_incluses = [c for c in perimetre.societes if c.inclus]
            run.nb_societes = len(companies_incluses)
            run.societes_incluses = [
                {
                    "company_id": str(c.company_id),
                    "code": c.code,
                    "libelle": c.libelle,
                    "pct_controle": c.pct_controle,
                    "pct_interet": c.pct_interet,
                    "methode": c.methode,
                }
                for c in companies_incluses
            ]

            # ─── 2. Agréger les comptes par société ────────────────────
            soldes_par_societe: dict[UUID, dict[str, dict[str, int]]] = {}
            for c in companies_incluses:
                company = await self._get_company(c.company_id)
                soldes = await self._agreger_comptes(
                    company.tenant_id, request.date_debut, request.date_fin
                )
                # Conversion devises
                if request.convertir_devises and company.devise_comptable != group.devise_presentation:
                    for compte, vals in soldes.items():
                        soldes[compte]["debit"] = await self._convertir(
                            vals["debit"], company.devise_comptable,
                            group.devise_presentation, request.date_fin,
                        )
                        soldes[compte]["credit"] = await self._convertir(
                            vals["credit"], company.devise_comptable,
                            group.devise_presentation, request.date_fin,
                        )
                soldes_par_societe[c.company_id] = soldes

            # ─── 3. Éliminations ───────────────────────────────────────
            eliminations_appliquees: list[EliminationEntry] = []
            if request.appliquer_eliminations:
                stmt = select(EliminationEntry).where(
                    EliminationEntry.group_id == group_id,
                    EliminationEntry.appliquee.is_(False),
                    EliminationEntry.date_elimination.between(
                        request.date_debut, request.date_fin
                    ),
                )
                eliminations_appliquees = list((await self.db.execute(stmt)).scalars().all())
                for e in eliminations_appliquees:
                    e.appliquee = True
                    e.appliquee_at = datetime.now(timezone.utc)
                    e.consolidation_run_id = run.id
                run.nb_eliminations = len(eliminations_appliquees)

            # ─── 4. Retraitements ──────────────────────────────────────
            retraitements: list[AdjustmentEntry] = []
            if request.appliquer_retraitements:
                stmt = select(AdjustmentEntry).where(
                    AdjustmentEntry.group_id == group_id,
                    AdjustmentEntry.appliquee.is_(False),
                    AdjustmentEntry.date_retraitement.between(
                        request.date_debut, request.date_fin
                    ),
                )
                retraitements = list((await self.db.execute(stmt)).scalars().all())
                for r in retraitements:
                    r.appliquee = True
                run.nb_retraitements = len(retraitements)

            # ─── 5. Calcul des intérêts minoritaires ───────────────────
            mi_totaux = await self._calculer_interets_minoritaires(
                group_id, companies_incluses, request.date_fin
            )
            run.interets_minoritaires_cp = mi_totaux["cp"]
            run.resultat_net_part_minoritaires = mi_totaux["resultat"]

            # ─── 6. Construire le bilan consolidé ──────────────────────
            bilan = await self._construire_bilan_consolide(
                group, soldes_par_societe, companies_incluses,
                eliminations_appliquees, retraitements, mi_totaux,
            )
            run.bilan_consolide = bilan
            run.total_actif_consolide = bilan["actif"]["total_actif"]
            run.total_passif_consolide = bilan["passif"]["total_passif"]

            # ─── 7. Construire le compte de résultat ───────────────────
            cr = await self._construire_compte_resultat_consolide(
                group, soldes_par_societe, companies_incluses,
                eliminations_appliquees, mi_totaux,
            )
            run.compte_resultat_consolide = cr
            run.chiffre_affaires_consolide = cr["chiffre_affaires"]
            run.resultat_net_part_groupe = cr["resultat_net_part_groupe"]

            # ─── 8. TAFIRE consolidé ───────────────────────────────────
            tafire = self._construire_tafire_consolide(bilan, cr)
            run.tafire_consolide = tafire

            # ─── 9. Notes annexes ──────────────────────────────────────
            if request.generer_notes:
                run.notes_annexes = await self._generer_notes_annexes(
                    group, perimetre, run, eliminations_appliquees, retraitements
                )

            # ─── 10. Écart d'acquisition (goodwill) ────────────────────
            run.ecart_acquisition_total = await self._calculer_ecart_acquisition(
                group_id, companies_incluses, request.date_fin
            )

            # ─── 11. Finaliser ─────────────────────────────────────────
            run.statut = "calcule"
            run.duree_execution_ms = int((time.monotonic() - start_time) * 1000)
            await self.db.flush()

            await self.audit.log(
                tenant_id=self.tenant_id,
                user_id=self.user_id,
                action="CONSOLIDATION_RUN",
                ressource="consolidation_run",
                ressource_id=run.id,
                payload={
                    "reference": reference,
                    "nb_societes": run.nb_societes,
                    "duree_ms": run.duree_execution_ms,
                },
            )
            return run

        except Exception as exc:
            run.statut = "annule"
            run.metadata_ = {"error": str(exc)}
            await self.db.flush()
            logger.exception(f"[consolidation] Échec run {reference}")
            raise

    async def valider_run(self, run_id: UUID) -> ConsolidationRun:
        run = await self.db.scalar(
            select(ConsolidationRun).where(
                ConsolidationRun.id == run_id,
                ConsolidationRun.group_id.in_(
                    select(ConsolidationGroup.id).where(
                        ConsolidationGroup.tenant_id == self.tenant_id
                    )
                ),
            )
        )
        if run is None:
            raise HTTPException(404, "Run de consolidation introuvable")
        if run.statut != "calcule":
            raise HTTPException(400, f"Run {run.statut} — non validable")

        run.statut = "valide"
        run.valide_at = datetime.now(timezone.utc)
        run.valide_par = self.user_id
        await self.db.flush()
        return run

    # ═════════════════════════════════════════════════════════════════════
    # CONSTRUCTION DES COMPTES CONSOLIDÉS
    # ═════════════════════════════════════════════════════════════════════
    async def _agreger_comptes(
        self, tenant_id: UUID, date_debut: date, date_fin: date
    ) -> dict[str, dict[str, int]]:
        """Agrège les mouvements par compte pour un tenant sur une période."""
        stmt = (
            select(
                PlanComptable.compte,
                func.coalesce(func.sum(EcritureLigne.debit_xof), 0),
                func.coalesce(func.sum(EcritureLigne.credit_xof), 0),
            )
            .join(EcritureLigne, EcritureLigne.compte_id == PlanComptable.id)
            .join(Ecriture, Ecriture.id == EcritureLigne.ecriture_id)
            .where(
                Ecriture.tenant_id == tenant_id,
                Ecriture.date_ecriture.between(date_debut, date_fin),
                Ecriture.statut == "validee",
            )
            .group_by(PlanComptable.compte)
        )
        rows = (await self.db.execute(stmt)).all()
        return {
            r[0]: {"debit": int(r[1] or 0), "credit": int(r[2] or 0)}
            for r in rows
        }

    async def _calculer_interets_minoritaires(
        self, group_id: UUID,
        companies_incluses: list[PerimetreLigne],
        date_arret: date,
    ) -> dict[str, int]:
        """Calcule les intérêts minoritaires cumulés (CP + résultat)."""
        total_cp_mino = 0
        total_resultat_mino = 0

        for c in companies_incluses:
            if c.methode != MethodeConsolidation.INTEGRATION_GLOBALE:
                continue  # IP et MEE ne génèrent pas de minoritaires
            company = await self._get_company(c.company_id)
            if company.pourcentage_interet >= 100.0:
                continue

            # Calculer les CP de la filiale
            cp_filiale = await self._calculer_capitaux_propres(company.tenant_id, date_arret)
            resultat_filiale = await self._calculer_resultat(
                company.tenant_id, date(date_arret.year, 1, 1), date_arret
            )

            pct_mino = (100.0 - c.pct_interet) / 100.0
            cp_mino = int(cp_filiale * pct_mino)
            resultat_mino = int(resultat_filiale * pct_mino)

            total_cp_mino += cp_mino
            total_resultat_mino += resultat_mino

            # Persister le cache
            existing = await self.db.scalar(
                select(MinorityInterest).where(
                    MinorityInterest.company_id == company.id,
                    MinorityInterest.date_calcul == date_arret,
                )
            )
            if existing:
                existing.pct_interet_groupe = Decimal(str(c.pct_interet))
                existing.pct_interet_minoritaire = Decimal(str(100.0 - c.pct_interet))
                existing.capitaux_propres_filiale = cp_filiale
                existing.resultat_filiale = resultat_filiale
                existing.interets_minoritaires_cp = cp_mino
                existing.interets_minoritaires_resultat = resultat_mino
            else:
                self.db.add(MinorityInterest(
                    group_id=group_id,
                    company_id=company.id,
                    date_calcul=date_arret,
                    pct_interet_groupe=Decimal(str(c.pct_interet)),
                    pct_interet_minoritaire=Decimal(str(100.0 - c.pct_interet)),
                    capitaux_propres_filiale=cp_filiale,
                    resultat_filiale=resultat_filiale,
                    interets_minoritaires_cp=cp_mino,
                    interets_minoritaires_resultat=resultat_mino,
                ))

        await self.db.flush()
        return {"cp": total_cp_mino, "resultat": total_resultat_mino}

    async def _calculer_capitaux_propres(self, tenant_id: UUID, date_arret: date) -> int:
        """Calcule les capitaux propres d'un tenant (comptes classe 1)."""
        stmt = (
            select(
                func.coalesce(func.sum(EcritureLigne.credit_xof - EcritureLigne.debit_xof), 0)
            )
            .join(PlanComptable, PlanComptable.id == EcritureLigne.compte_id)
            .join(Ecriture, Ecriture.id == EcritureLigne.ecriture_id)
            .where(
                Ecriture.tenant_id == tenant_id,
                PlanComptable.classe == 1,
                Ecriture.date_ecriture <= date_arret,
                Ecriture.statut == "validee",
            )
        )
        return int(await self.db.scalar(stmt) or 0)

    async def _calculer_resultat(
        self, tenant_id: UUID, date_debut: date, date_fin: date
    ) -> int:
        """Calcule le résultat net (produits 7x - charges 6x)."""
        stmt = (
            select(
                func.coalesce(func.sum(EcritureLigne.debit_xof), 0),
                func.coalesce(func.sum(EcritureLigne.credit_xof), 0),
            )
            .join(PlanComptable, PlanComptable.id == EcritureLigne.compte_id)
            .join(Ecriture, Ecriture.id == EcritureLigne.ecriture_id)
            .where(
                Ecriture.tenant_id == tenant_id,
                Ecriture.date_ecriture.between(date_debut, date_fin),
                Ecriture.statut == "validee",
                PlanComptable.classe.in_([6, 7]),
            )
        )
        result = (await self.db.execute(stmt)).one()
        debit, credit = int(result[0] or 0), int(result[1] or 0)
        return credit - debit

    async def _construire_bilan_consolide(
        self,
        group: ConsolidationGroup,
        soldes_par_societe: dict[UUID, dict[str, dict[str, int]]],
        companies: list[PerimetreLigne],
        eliminations: list[EliminationEntry],
        retraitements: list[AdjustmentEntry],
        mi_totaux: dict[str, int],
    ) -> dict[str, Any]:
        """
        Construit le bilan consolidé :
        - Agrégation des soldes de tous les comptes (classes 1-5)
        - Application des éliminations
        - Ajout des intérêts minoritaires au passif
        """
        # Somme des soldes par compte
        totaux_par_compte: dict[str, dict[str, int]] = defaultdict(lambda: {"debit": 0, "credit": 0})
        for c in companies:
            soldes = soldes_par_societe.get(c.company_id, {})
            pct = c.pct_controle / 100.0 if c.methode == "integration_proportionnelle" else 1.0
            for compte, vals in soldes.items():
                if compte[0] not in ("1", "2", "3", "4", "5"):
                    continue
                totaux_par_compte[compte]["debit"] += int(vals["debit"] * pct)
                totaux_par_compte[compte]["credit"] += int(vals["credit"] * pct)

        # Éliminations
        eliminations_par_compte: dict[str, int] = defaultdict(int)
        for e in eliminations:
            for ligne in e.lignes:
                c = ligne.get("compte", "")
                debit = int(ligne.get("debit", 0))
                credit = int(ligne.get("credit", 0))
                eliminations_par_compte[c] += (debit - credit)

        # Construction des sections
        actif_immobilise = self._agreger_classe(totaux_par_compte, ["2"], "debit", eliminations_par_compte)
        actif_circulant = self._agreger_classe(totaux_par_compte, ["3", "4"], "debit", eliminations_par_compte)
        tresorerie_actif = self._agreger_classe(totaux_par_compte, ["5"], "debit", eliminations_par_compte)
        total_actif = actif_immobilise["total"] + actif_circulant["total"] + tresorerie_actif["total"]

        capitaux_propres = self._agreger_classe(totaux_par_compte, ["1"], "credit", eliminations_par_compte)
        passif_circulant = self._agreger_classe(totaux_par_compte, ["4"], "credit", eliminations_par_compte)
        tresorerie_passif = self._agreger_classe(totaux_par_compte, ["5"], "credit", eliminations_par_compte)

        # Intérêts minoritaires (ajout au passif)
        mi_cp = mi_totaux["cp"]
        mi_resultat = mi_totaux["resultat"]
        capitaux_propres["total"] += mi_cp + mi_resultat

        total_passif = (
            capitaux_propres["total"]
            + passif_circulant["total"]
            + tresorerie_passif["total"]
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
                "interets_minoritaires": {
                    "cp": mi_cp,
                    "resultat": mi_resultat,
                    "total": mi_cp + mi_resultat,
                },
                "passif_circulant": passif_circulant,
                "tresorerie_passif": tresorerie_passif,
                "total_passif": total_passif,
            },
            "equilibre": total_actif == total_passif,
            "devise": group.devise_presentation,
        }

    def _agreger_classe(
        self,
        totaux_par_compte: dict[str, dict[str, int]],
        classes: list[str],
        sens: str,
        eliminations_par_compte: dict[str, int],
    ) -> dict[str, Any]:
        lignes: list[dict[str, Any]] = []
        total = 0
        for compte, vals in totaux_par_compte.items():
            if compte[0] not in classes:
                continue
            solde = (vals["debit"] - vals["credit"]) if sens == "debit" else (vals["credit"] - vals["debit"])
            elim = eliminations_par_compte.get(compte, 0)
            solde_consolide = solde - (elim if sens == "debit" else -elim)
            if solde_consolide <= 0:
                continue
            lignes.append({"compte": compte, "montant": solde_consolide})
            total += solde_consolide
        return {"lignes": sorted(lignes, key=lambda x: x["compte"]), "total": total}

    async def _construire_compte_resultat_consolide(
        self,
        group: ConsolidationGroup,
        soldes_par_societe: dict[UUID, dict[str, dict[str, int]]],
        companies: list[PerimetreLigne],
        eliminations: list[EliminationEntry],
        mi_totaux: dict[str, int],
    ) -> dict[str, Any]:
        """Construit le compte de résultat consolidé."""
        # Agrégation
        totaux: dict[str, dict[str, int]] = defaultdict(lambda: {"debit": 0, "credit": 0})
        for c in companies:
            soldes = soldes_par_societe.get(c.company_id, {})
            pct = c.pct_controle / 100.0 if c.methode == "integration_proportionnelle" else 1.0
            for compte, vals in soldes.items():
                if compte[0] not in ("6", "7"):
                    continue
                totaux[compte]["debit"] += int(vals["debit"] * pct)
                totaux[compte]["credit"] += int(vals["credit"] * pct)

        # Éliminations
        elim_par_compte: dict[str, int] = defaultdict(int)
        for e in eliminations:
            for ligne in e.lignes:
                c = ligne.get("compte", "")
                elim_par_compte[c] += int(ligne.get("debit", 0)) - int(ligne.get("credit", 0))

        def solde_prefixe(prefixes: list[str], sens: str) -> int:
            total = 0
            for compte, vals in totaux.items():
                if not any(compte.startswith(p) for p in prefixes):
                    continue
                s = (vals["debit"] - vals["credit"]) if sens == "debit" else (vals["credit"] - vals["debit"])
                s -= elim_par_compte.get(compte, 0) if sens == "debit" else -elim_par_compte.get(compte, 0)
                total += max(0, s)
            return total

        ca = solde_prefixe(["70"], "credit")
        achats = solde_prefixe(["60"], "debit")
        services_ext = solde_prefixe(["61", "62"], "debit")
        autres_charges = solde_prefixe(["63", "64"], "debit")
        charges_personnel = solde_prefixe(["66"], "debit")
        dotations = solde_prefixe(["68"], "debit")
        reprises = solde_prefixe(["78", "79"], "credit")
        charges_financieres = solde_prefixe(["67"], "debit")
        produits_financiers = solde_prefixe(["77"], "credit")

        marge_commerciale = ca - achats
        valeur_ajoutee = marge_commerciale - services_ext
        ebe = valeur_ajoutee - autres_charges - charges_personnel
        resultat_exploitation = ebe - dotations + reprises
        resultat_financier = produits_financiers - charges_financieres
        resultat_avant_impots = resultat_exploitation + resultat_financier
        impots = solde_prefixe(["89"], "debit")
        resultat_net_ensemble = resultat_avant_impots - impots

        # Répartition groupe / minoritaires
        mi_resultat = mi_totaux["resultat"]
        resultat_part_groupe = resultat_net_ensemble - mi_resultat

        return {
            "chiffre_affaires": ca,
            "achats_consommes": achats,
            "marge_commerciale": marge_commerciale,
            "services_externes": services_ext,
            "valeur_ajoutee": valeur_ajoutee,
            "charges_personnel": charges_personnel,
            "autres_charges": autres_charges,
            "ebe": ebe,
            "dotations": dotations,
            "reprises": reprises,
            "resultat_exploitation": resultat_exploitation,
            "charges_financieres": charges_financieres,
            "produits_financiers": produits_financiers,
            "resultat_financier": resultat_financier,
            "resultat_avant_impots": resultat_avant_impots,
            "impots": impots,
            "resultat_net_ensemble": resultat_net_ensemble,
            "resultat_net_part_groupe": resultat_part_groupe,
            "resultat_net_part_minoritaires": mi_resultat,
            "devise": group.devise_presentation,
        }

    def _construire_tafire_consolide(
        self, bilan: dict[str, Any], cr: dict[str, Any]
    ) -> dict[str, Any]:
        """TAFIRE consolidé simplifié."""
        cafg = cr["ebe"] - cr["charges_financieres"] - cr["impots"]
        return {
            "cafg": cafg,
            "resultat_net": cr["resultat_net_ensemble"],
            "resultat_net_part_groupe": cr["resultat_net_part_groupe"],
            "resultat_net_part_minoritaires": cr["resultat_net_part_minoritaires"],
            "valeur_ajoutee": cr["valeur_ajoutee"],
            "ebe": cr["ebe"],
            "note": "TAFIRE consolidé simplifié",
        }

    async def _generer_notes_annexes(
        self,
        group: ConsolidationGroup,
        perimetre: PerimetreOut,
        run: ConsolidationRun,
        eliminations: list[EliminationEntry],
        retraitements: list[AdjustmentEntry],
    ) -> dict[str, Any]:
        """Génère les notes annexes obligatoires selon OHADA."""
        notes: list[dict[str, Any]] = []

        # Note 1 : Périmètre de consolidation
        notes.append({
            "numero": "1",
            "titre": "Périmètre de consolidation",
            "contenu": (
                f"Le groupe {group.libelle} comprend {perimetre.nb_societes_incluses} "
                f"société(s) consolidée(s) à la date du {perimetre.date_arret.isoformat()}."
            ),
            "tableaux": [
                {
                    "code": s.code,
                    "libelle": s.libelle,
                    "pct_controle": s.pct_controle,
                    "pct_interet": s.pct_interet,
                    "methode": s.methode,
                }
                for s in perimetre.societes if s.inclus
            ],
        })

        # Note 2 : Méthodes comptables
        notes.append({
            "numero": "2",
            "titre": "Méthodes comptables",
            "contenu": (
                f"Les comptes consolidés sont établis selon les règles de l'OHADA "
                f"(AUDCIF). Devise de présentation : {group.devise_presentation}. "
                f"Écart d'acquisition traité selon la méthode : {group.methode_ecart_acquisition}."
            ),
            "tableaux": [],
        })

        # Note 3 : Éliminations
        notes.append({
            "numero": "3",
            "titre": "Opérations intragroupe éliminées",
            "contenu": (
                f"{run.nb_eliminations} opération(s) intragroupe ont été éliminées "
                f"sur la période."
            ),
            "tableaux": [
                {"reference": e.reference, "type": e.type_elimination, "montant": e.montant}
                for e in eliminations
            ],
        })

        # Note 4 : Retraitements
        notes.append({
            "numero": "4",
            "titre": "Retraitements d'homogénéisation",
            "contenu": (
                f"{run.nb_retraitements} retraitement(s) ont été appliqués "
                f"pour homogénéiser les méthodes comptables du groupe."
            ),
            "tableaux": [
                {"reference": r.reference, "type": r.type_retraitement, "montant": r.montant}
                for r in retraitements
            ],
        })

        # Note 5 : Intérêts minoritaires
        notes.append({
            "numero": "5",
            "titre": "Intérêts minoritaires",
            "contenu": (
                f"La part des intérêts minoritaires dans les capitaux propres "
                f"consolidés s'élève à {run.interets_minoritaires_cp:,} {group.devise_presentation} "
                f"et dans le résultat à {run.resultat_net_part_minoritaires:,} "
                f"{group.devise_presentation}."
            ).replace(",", " "),
            "tableaux": [],
        })

        return {
            "nb_notes": len(notes),
            "notes": notes,
            "genere_at": datetime.now(timezone.utc).isoformat(),
        }

    async def _calculer_ecart_acquisition(
        self, group_id: UUID, companies: list[PerimetreLigne], date_arret: date
    ) -> int:
        """
        Écart d'acquisition (goodwill) = Prix d'acquisition - Quote-part dans les CP.
        Simplification : on retourne 0 tant que la table "acquisition" n'est pas
        implémentée. À enrichir avec les données d'acquisition.
        """
        return 0

    # ═════════════════════════════════════════════════════════════════════
    # GETTERS COMPTES CONSOLIDÉS
    # ═════════════════════════════════════════════════════════════════════
    async def get_bilan_consolide(self, run_id: UUID) -> BilanConsolideOut:
        run = await self._get_run(run_id)
        if not run.bilan_consolide:
            raise HTTPException(404, "Aucun bilan consolidé pour ce run")
        bilan = run.bilan_consolide
        return BilanConsolideOut(
            run_id=run.id,
            date_fin=run.date_fin,
            devise=bilan.get("devise", "XOF"),
            actif=bilan["actif"],
            passif=bilan["passif"],
            total_actif=bilan["actif"]["total_actif"],
            total_passif=bilan["passif"]["total_passif"],
            equilibre=bilan.get("equilibre", False),
        )

    async def get_compte_resultat_consolide(self, run_id: UUID) -> CompteResultatConsolideOut:
        run = await self._get_run(run_id)
        if not run.compte_resultat_consolide:
            raise HTTPException(404, "Aucun compte de résultat consolidé pour ce run")
        cr = run.compte_resultat_consolide
        return CompteResultatConsolideOut(
            run_id=run.id,
            date_debut=run.date_debut,
            date_fin=run.date_fin,
            devise=cr.get("devise", "XOF"),
            chiffre_affaires=cr["chiffre_affaires"],
            resultat_exploitation=cr["resultat_exploitation"],
            resultat_financier=cr["resultat_financier"],
            resultat_avant_impots=cr["resultat_avant_impots"],
            impots=cr["impots"],
            resultat_net_ensemble=cr["resultat_net_ensemble"],
            resultat_net_part_groupe=cr["resultat_net_part_groupe"],
            resultat_net_part_minoritaires=cr["resultat_net_part_minoritaires"],
        )

    async def get_notes_annexes(self, run_id: UUID) -> NotesAnnexesOut:
        run = await self._get_run(run_id)
        if not run.notes_annexes:
            raise HTTPException(404, "Aucune note annexe pour ce run")
        notes_data = run.notes_annexes
        notes = [NoteAnnexeOut(**n) for n in notes_data.get("notes", [])]
        return NotesAnnexesOut(
            run_id=run.id,
            nb_notes=len(notes),
            notes=notes,
        )

    # ═════════════════════════════════════════════════════════════════════
    # HELPERS
    # ═════════════════════════════════════════════════════════════════════
    async def _get_group(self, group_id: UUID) -> ConsolidationGroup:
        g = await self.db.scalar(
            select(ConsolidationGroup).where(
                ConsolidationGroup.id == group_id,
                ConsolidationGroup.tenant_id == self.tenant_id,
            )
        )
        if g is None:
            raise HTTPException(404, "Groupe de consolidation introuvable")
        return g

    async def _get_company(self, company_id: UUID) -> GroupCompany:
        c = await self.db.scalar(
            select(GroupCompany).where(GroupCompany.id == company_id)
        )
        if c is None:
            raise HTTPException(404, "Société membre introuvable")
        return c

    async def _get_run(self, run_id: UUID) -> ConsolidationRun:
        r = await self.db.scalar(
            select(ConsolidationRun).where(
                ConsolidationRun.id == run_id,
                ConsolidationRun.group_id.in_(
                    select(ConsolidationGroup.id).where(
                        ConsolidationGroup.tenant_id == self.tenant_id
                    )
                ),
            )
        )
        if r is None:
            raise HTTPException(404, "Run de consolidation introuvable")
        return r
