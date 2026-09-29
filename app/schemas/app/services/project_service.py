"""
Service Projets & Chantiers SYSCOHADA.

Fonctionnalités :
- CRUD projets, phases, tâches, jalons
- Imputation de coûts réels (avec écritures)
- Calcul automatique de l'avancement
- Génération des situations de travaux
- Facturation à l'avancement (méthode SYSCOHADA)
- Suivi budgétaire et marges
- Clôture avec transfert en immobilisation (23x → 2x)
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.project_syscohada import (
    COMPTES_PROJET,
    JOURNAL_PROJET,
    NiveauAlerteProjet,
    RETENUE_GARANTIE_TAUX_DEFAUT,
    SEUILS_ALERTE_PROJET,
    StatutProjet,
    StatutSituation,
    TypeProjet,
)
from app.models.enums import EcritureSource
from app.models.project import (
    ProgressBilling,
    ProgressBillingLine,
    Project,
    ProjectCost,
    ProjectMilestone,
    ProjectPhase,
    ProjectTask,
)
from app.models.sale import Customer
from app.schemas.ecriture import EcritureCreate, LigneIn
from app.schemas.project import (
    AvancementSituationOut,
    ProgressBillingCreate,
    ProjectCostCreate,
    ProjectCreate,
    ProjectDetailOut,
    ProjectMarginOut,
    ProjectMilestoneCreate,
    ProjectOut,
    ProjectPhaseCreate,
    ProjectPhaseUpdate,
    ProjectPortfolioOut,
    ProjectTaskCreate,
    ProjectTaskUpdate,
    ProjectUpdate,
)
from app.services.audit_service import AuditService
from app.services.journal_service import JournalService
from app.services.syscohada_service import SyscohadaService

logger = logging.getLogger(__name__)


class ProjectService:
    def __init__(self, db: AsyncSession, tenant_id: UUID, user_id: UUID) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.audit = AuditService(db)

    # ═════════════════════════════════════════════════════════════════════
    # PROJETS
    # ═════════════════════════════════════════════════════════════════════
    async def creer_projet(self, data: ProjectCreate) -> Project:
        existing = await self.db.scalar(
            select(Project.id).where(
                Project.tenant_id == self.tenant_id,
                Project.code == data.code,
            )
        )
        if existing:
            raise HTTPException(409, f"Code projet {data.code} déjà utilisé")

        if data.customer_id:
            c = await self.db.scalar(
                select(Customer).where(
                    Customer.id == data.customer_id,
                    Customer.tenant_id == self.tenant_id,
                )
            )
            if c is None:
                raise HTTPException(404, "Client introuvable")

        montant_ttc = int(data.montant_marche_ht * (1 + data.taux_tva))
        avance_montant = int(data.montant_marche_ht * data.avance_demarrage_pct / 100)

        project = Project(
            tenant_id=self.tenant_id,
            code=data.code,
            libelle=data.libelle,
            description=data.description,
            type_projet=data.type_projet,
            methode_reconnaissance=data.methode_reconnaissance,
            methode_avancement=data.methode_avancement,
            customer_id=data.customer_id,
            chef_projet_user_id=data.chef_projet_user_id,
            date_debut_prevue=data.date_debut_prevue,
            date_fin_prevue=data.date_fin_prevue,
            montant_marche_ht=data.montant_marche_ht,
            montant_marche_ttc=montant_ttc,
            taux_tva=data.taux_tva,
            budget_previsionnel_ht=data.budget_previsionnel_ht,
            cout_total_estime_ht=data.budget_previsionnel_ht,
            retenue_garantie_taux=data.retenue_garantie_taux,
            avance_demarrage_pct=data.avance_demarrage_pct,
            avance_demarrage_montant=avance_montant,
            compte_projet=data.compte_projet,
            analytical_section_id=data.analytical_section_id,
            statut=StatutProjet.BROUILLON,
            created_by=self.user_id,
        )
        self.db.add(project)
        await self.db.flush()

        await self.audit.log(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            action="PROJECT_CREATE",
            ressource="project",
            ressource_id=project.id,
            payload={
                "code": project.code,
                "type": project.type_projet,
                "montant": project.montant_marche_ht,
            },
        )
        return project

    async def modifier_projet(self, project_id: UUID, data: ProjectUpdate) -> Project:
        project = await self._get_project(project_id)
        for k, v in data.model_dump(exclude_unset=True).items():
            setattr(project, k, v)
        # Recalcul TTC si montant ou TVA modifiés
        if data.montant_marche_ht is not None:
            project.montant_marche_ttc = int(project.montant_marche_ht * (1 + float(project.taux_tva)))
        await self.db.flush()
        return project

    async def lancer_projet(self, project_id: UUID) -> Project:
        """Bascule le projet en 'en_cours'."""
        project = await self._get_project(project_id)
        if project.statut not in (StatutProjet.BROUILLON, StatutProjet.EN_PREPARATION):
            raise HTTPException(400, f"Projet {project.statut} — non démarrable")

        project.statut = StatutProjet.EN_COURS
        if project.date_debut_reelle is None:
            project.date_debut_reelle = date.today()
        await self.db.flush()
        return project

    async def detail_projet(self, project_id: UUID) -> ProjectDetailOut:
        project = await self._get_project(project_id)
        phases = (
            await self.db.execute(
                select(ProjectPhase).where(ProjectPhase.project_id == project.id)
                .order_by(ProjectPhase.ordre)
            )
        ).scalars().all()
        jalons = (
            await self.db.execute(
                select(ProjectMilestone).where(ProjectMilestone.project_id == project.id)
                .order_by(ProjectMilestone.ordre)
            )
        ).scalars().all()

        nb_taches = int(await self.db.scalar(
            select(func.count(ProjectTask.id)).where(ProjectTask.project_id == project.id)
        ) or 0)
        nb_taches_terminees = int(await self.db.scalar(
            select(func.count(ProjectTask.id)).where(
                ProjectTask.project_id == project.id,
                ProjectTask.statut == "terminee",
            )
        ) or 0)
        nb_couts = int(await self.db.scalar(
            select(func.count(ProjectCost.id)).where(ProjectCost.project_id == project.id)
        ) or 0)
        nb_situations = int(await self.db.scalar(
            select(func.count(ProgressBilling.id)).where(ProgressBilling.project_id == project.id)
        ) or 0)

        base = ProjectOut.model_validate(project).model_dump()
        return ProjectDetailOut(
            **base,
            phases=[ProjectPhaseOut.model_validate(p) for p in phases],
            jalons=[ProjectMilestoneOut.model_validate(j) for j in jalons],
            nb_taches=nb_taches,
            nb_taches_terminees=nb_taches_terminees,
            nb_couts_imputes=nb_couts,
            nb_situations=nb_situations,
            marge_previsionnelle=project.marge_previsionnelle,
            marge_previsionnelle_pct=round(project.marge_previsionnelle_pct, 2),
            taux_consommation_budget=round(project.taux_consommation_budget, 2),
        )

    # ═════════════════════════════════════════════════════════════════════
    # PHASES
    # ═════════════════════════════════════════════════════════════════════
    async def creer_phase(
        self, project_id: UUID, data: ProjectPhaseCreate
    ) -> ProjectPhase:
        project = await self._get_project(project_id)

        existing = await self.db.scalar(
            select(ProjectPhase.id).where(
                ProjectPhase.project_id == project.id,
                ProjectPhase.code == data.code,
            )
        )
        if existing:
            raise HTTPException(409, f"Phase {data.code} déjà existante")

        phase = ProjectPhase(
            tenant_id=self.tenant_id,
            project_id=project.id,
            **data.model_dump(),
        )
        self.db.add(phase)
        await self.db.flush()

        # Mettre à jour le budget prévisionnel du projet
        total_phases = int(await self.db.scalar(
            select(func.coalesce(func.sum(ProjectPhase.budget_ht), 0))
            .where(ProjectPhase.project_id == project.id)
        ) or 0)
        if total_phases > 0:
            project.budget_previsionnel_ht = total_phases

        await self.db.flush()
        return phase

    async def modifier_phase(
        self, phase_id: UUID, data: ProjectPhaseUpdate
    ) -> ProjectPhase:
        phase = await self._get_phase(phase_id)
        for k, v in data.model_dump(exclude_unset=True).items():
            setattr(phase, k, v)
        await self.db.flush()
        return phase

    # ═════════════════════════════════════════════════════════════════════
    # TÂCHES
    # ═════════════════════════════════════════════════════════════════════
    async def creer_tache(
        self, project_id: UUID, data: ProjectTaskCreate
    ) -> ProjectTask:
        project = await self._get_project(project_id)

        if data.phase_id:
            await self._get_phase(data.phase_id)

        existing = await self.db.scalar(
            select(ProjectTask.id).where(
                ProjectTask.project_id == project.id,
                ProjectTask.code == data.code,
            )
        )
        if existing:
            raise HTTPException(409, f"Tâche {data.code} déjà existante")

        task = ProjectTask(
            tenant_id=self.tenant_id,
            project_id=project.id,
            **data.model_dump(),
        )
        self.db.add(task)
        await self.db.flush()
        return task

    async def modifier_tache(
        self, task_id: UUID, data: ProjectTaskUpdate
    ) -> ProjectTask:
        task = await self._get_task(task_id)
        for k, v in data.model_dump(exclude_unset=True).items():
            setattr(task, k, v)

        # Si la tâche passe à terminée, mettre à jour les dates
        if data.statut == "terminee" and task.date_fin_reelle is None:
            task.date_fin_reelle = date.today()
            task.pourcentage_avancement = 100

        await self.db.flush()

        # Recalculer l'avancement du projet
        await self._recalculer_avancement_physique(task.project_id)
        return task

    # ═════════════════════════════════════════════════════════════════════
    # JALONS
    # ═════════════════════════════════════════════════════════════════════
    async def creer_jalon(
        self, project_id: UUID, data: ProjectMilestoneCreate
    ) -> ProjectMilestone:
        await self._get_project(project_id)
        existing = await self.db.scalar(
            select(ProjectMilestone.id).where(
                ProjectMilestone.project_id == project_id,
                ProjectMilestone.code == data.code,
            )
        )
        if existing:
            raise HTTPException(409, f"Jalon {data.code} déjà existant")

        m = ProjectMilestone(
            tenant_id=self.tenant_id,
            project_id=project_id,
            **data.model_dump(),
        )
        self.db.add(m)
        await self.db.flush()
        return m

    async def marquer_jalon_atteint(self, milestone_id: UUID) -> ProjectMilestone:
        m = await self.db.scalar(
            select(ProjectMilestone).where(
                ProjectMilestone.id == milestone_id,
                ProjectMilestone.tenant_id == self.tenant_id,
            )
        )
        if m is None:
            raise HTTPException(404, "Jalon introuvable")
        m.atteint = True
        m.date_atteinte = date.today()
        await self.db.flush()
        return m

    # ═════════════════════════════════════════════════════════════════════
    # IMPUTATION DE COÛTS
    # ═════════════════════════════════════════════════════════════════════
    async def imputer_cout(
        self, project_id: UUID, data: ProjectCostCreate, comptabiliser: bool = True
    ) -> ProjectCost:
        project = await self._get_project(project_id)

        if data.phase_id:
            await self._get_phase(data.phase_id)

        cost = ProjectCost(
            tenant_id=self.tenant_id,
            project_id=project.id,
            phase_id=data.phase_id,
            date_cout=data.date_cout,
            libelle=data.libelle,
            type_cout=data.type_cout,
            montant_ht=data.montant_ht,
            montant_tva=data.montant_tva,
            source_type=data.source_type,
            source_id=data.source_id,
            compte_comptable=data.compte_comptable,
            created_by=self.user_id,
        )
        self.db.add(cost)
        await self.db.flush()

        # Mettre à jour le budget réalisé du projet
        project.budget_realise += data.montant_ht
        if data.phase_id:
            phase = await self._get_phase(data.phase_id)
            phase.budget_realise += data.montant_ht
        await self.db.flush()

        if comptabiliser:
            ecriture_id = await self._generer_ecriture_cout(cost, project)
            cost.ecriture_id = ecriture_id
            await self.db.flush()

        # Recalculer l'alerte
        await self._recalculer_alerte(project)

        await self.audit.log(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            action="PROJECT_COST_IMPUTE",
            ressource="project_cost",
            ressource_id=cost.id,
            payload={
                "project_code": project.code,
                "montant": cost.montant_ht,
                "type": cost.type_cout,
            },
        )
        return cost

    # ═════════════════════════════════════════════════════════════════════
    # SITUATION DE TRAVAUX
    # ═════════════════════════════════════════════════════════════════════
    async def creer_situation(
        self, data: ProgressBillingCreate, comptabiliser: bool = True
    ) -> ProgressBilling:
        """
        Crée une situation de travaux (décompte).
        Le montant de la situation = cumul actuel - cumul précédent.
        Retenue de garantie + remboursement avance sont calculés automatiquement.
        """
        project = await self._get_project(data.project_id)
        if project.statut not in (StatutProjet.EN_COURS, StatutProjet.EN_PAUSE):
            raise HTTPException(400, f"Projet {project.statut} — pas de situation possible")

        # N° de situation séquentiel
        last_num = int(await self.db.scalar(
            select(func.coalesce(func.max(ProgressBilling.numero_situation), 0))
            .where(ProgressBilling.project_id == project.id)
        ) or 0)
        new_num = last_num + 1

        numero = await self._generer_numero_situation(project, new_num)

        # Calculs ligne à ligne
        total_cumule_actuel = 0
        total_cumule_precedent = 0
        lignes_db: list[ProgressBillingLine] = []

        for i, l in enumerate(data.lignes, start=1):
            montant_cumul_actuel = int(l.quantite_cumulee_actuelle * l.prix_unitaire_ht)
            montant_cumul_precedent = int(l.quantite_cumulee_precedente * l.prix_unitaire_ht)
            montant_situation = montant_cumul_actuel - montant_cumul_precedent
            quantite_situation = l.quantite_cumulee_actuelle - l.quantite_cumulee_precedente

            total_cumule_actuel += montant_cumul_actuel
            total_cumule_precedent += montant_cumul_precedent

            lignes_db.append(ProgressBillingLine(
                tenant_id=self.tenant_id,
                ordre=l.ordre or i,
                phase_id=l.phase_id,
                designation=l.designation,
                unite=l.unite,
                quantite_marche=Decimal(str(l.quantite_marche)),
                quantite_cumulee_precedente=Decimal(str(l.quantite_cumulee_precedente)),
                quantite_cumulee_actuelle=Decimal(str(l.quantite_cumulee_actuelle)),
                quantite_situation=Decimal(str(quantite_situation)),
                prix_unitaire_ht=l.prix_unitaire_ht,
                montant_cumule_precedent_ht=montant_cumul_precedent,
                montant_cumule_actuel_ht=montant_cumul_actuel,
                montant_situation_ht=montant_situation,
                compte_produit=l.compte_produit,
            ))

        montant_situation_ht = total_cumule_actuel - total_cumule_precedent

        # TVA
        tva = int(montant_situation_ht * data.taux_tva)

        # Retenue de garantie
        retenue_taux = data.retenue_garantie_taux if data.retenue_garantie_taux is not None else float(project.retenue_garantie_taux)
        retenue_montant = int(montant_situation_ht * retenue_taux)

        # Remboursement avance (au prorata de l'avancement)
        avance_rembourse_situation = 0
        if project.avance_demarrage_montant > 0 and project.montant_marche_ht > 0:
            # Avance remboursée au prorata du montant cumulé
            avance_cumul_remboursee = int(
                project.avance_demarrage_montant
                * total_cumule_actuel
                / project.montant_marche_ht
            )
            avance_rembourse_situation = max(
                0, avance_cumul_remboursee - project.avance_remboursee
            )

        # RAS
        ras = int(montant_situation_ht * data.ras_taux)

        # Net à payer
        montant_net = montant_situation_ht + tva - retenue_montant - avance_rembourse_situation - ras

        billing = ProgressBilling(
            tenant_id=self.tenant_id,
            project_id=project.id,
            customer_id=project.customer_id,
            numero=numero,
            numero_situation=new_num,
            date_situation=data.date_situation,
            date_echeance=data.date_echeance,
            libelle=data.libelle,
            pourcentage_avancement_cumule=Decimal(str(data.pourcentage_avancement_cumule)),
            montant_cumule_precedent_ht=total_cumule_precedent,
            montant_cumule_actuel_ht=total_cumule_actuel,
            montant_situation_ht=montant_situation_ht,
            taux_tva=data.taux_tva,
            montant_tva=tva,
            retenue_garantie_taux=retenue_taux,
            retenue_garantie_montant=retenue_montant,
            avance_remboursee_situation=avance_rembourse_situation,
            ras_montant=ras,
            ras_taux=data.ras_taux,
            montant_net_a_payer=montant_net,
            statut=StatutSituation.BROUILLON,
            created_by=self.user_id,
        )
        self.db.add(billing)
        await self.db.flush()

        for l in lignes_db:
            l.billing_id = billing.id
            self.db.add(l)

        # Mettre à jour le projet
        project.pourcentage_avancement_financier = Decimal(str(data.pourcentage_avancement_cumule))
        project.retenue_garantie_montant += retenue_montant
        project.avance_remboursee += avance_rembourse_situation

        await self.db.flush()

        # Écriture comptable
        if comptabiliser:
            ecriture_id = await self._generer_ecriture_situation(billing, project)
            billing.ecriture_id = ecriture_id
            await self.db.flush()

        await self.audit.log(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            action="PROGRESS_BILLING_CREATE",
            ressource="progress_billing",
            ressource_id=billing.id,
            payload={
                "numero": numero,
                "montant_situation_ht": montant_situation_ht,
                "net_a_payer": montant_net,
            },
        )
        return billing

    async def valider_situation(self, billing_id: UUID, par_client: bool = False) -> ProgressBilling:
        billing = await self._get_billing(billing_id)
        if billing.statut != StatutSituation.BROUILLON:
            raise HTTPException(400, f"Situation déjà {billing.statut}")
        billing.statut = StatutSituation.VALIDEE if not par_client else StatutSituation.SOUMISE
        if par_client:
            billing.date_validation_client = date.today()
        await self.db.flush()
        return billing

    async def facturer_situation(
        self, billing_id: UUID
    ) -> tuple[ProgressBilling, UUID]:
        """
        Transforme une situation validée en facture client.
        Retourne (billing, facture_id).
        """
        billing = await self._get_billing(billing_id)
        if billing.statut != StatutSituation.VALIDEE:
            raise HTTPException(400, "Seule une situation validée peut être facturée")

        project = await self._get_project(billing.project_id)
        if project.customer_id is None:
            raise HTTPException(400, "Projet sans client associé")

        # Créer la facture client via SaleService
        from app.schemas.sale import CustomerInvoiceCreate, CustomerInvoiceLineCreate
        from app.services.sale_service import SaleService

        sale_svc = SaleService(self.db, self.tenant_id, self.user_id)

        # Une seule ligne globalisée pour la facture
        invoice_lines = [CustomerInvoiceLineCreate(
            designation=f"Situation n°{billing.numero_situation} — {project.libelle}",
            unite="ENS",
            quantite=1,
            prix_unitaire_ht=billing.montant_situation_ht,
            taux_tva=float(billing.taux_tva),
            compte_produit="705000",
        )]

        invoice = await sale_svc.creer_facture(CustomerInvoiceCreate(
            customer_id=project.customer_id,
            date_facture=billing.date_situation,
            date_echeance=billing.date_echeance,
            numero_client=billing.numero,
            notes=f"Facturation situation de travaux n°{billing.numero_situation}",
            lignes=invoice_lines,
        ))
        await sale_svc.valider_facture(invoice.id)

        billing.customer_invoice_id = invoice.id
        billing.statut = StatutSituation.FACTUREE
        await self.db.flush()

        await self.audit.log(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            action="PROGRESS_BILLING_INVOICED",
            ressource="progress_billing",
            ressource_id=billing.id,
            payload={"invoice_id": str(invoice.id), "numero_facture": invoice.numero},
        )
        return billing, invoice.id

    # ═════════════════════════════════════════════════════════════════════
    # AVANCEMENT & CALCULS
    # ═════════════════════════════════════════════════════════════════════
    async def _recalculer_avancement_physique(self, project_id: UUID) -> None:
        """Recalcule le % d'avancement physique selon la méthode choisie."""
        project = await self._get_project(project_id)

        if project.methode_avancement == "physique":
            # Moyenne pondérée des phases
            phases = (
                await self.db.execute(
                    select(ProjectPhase).where(ProjectPhase.project_id == project_id)
                )
            ).scalars().all()
            if phases:
                total_poids = sum(float(p.poids) for p in phases)
                if total_poids > 0:
                    avct = sum(
                        float(p.pourcentage_avancement) * float(p.poids) / total_poids
                        for p in phases
                    )
                    project.pourcentage_avancement_physique = Decimal(str(round(avct, 2)))
            else:
                # Fallback : moyenne simple des tâches
                tasks = (
                    await self.db.execute(
                        select(ProjectTask).where(ProjectTask.project_id == project_id)
                    )
                ).scalars().all()
                if tasks:
                    avg = sum(float(t.pourcentage_avancement) for t in tasks) / len(tasks)
                    project.pourcentage_avancement_physique = Decimal(str(round(avg, 2)))

        elif project.methode_avancement == "couts_engages":
            # Ratio coûts engagés / coût total estimé
            if project.cout_total_estime_ht > 0:
                ratio = project.budget_realise / project.cout_total_estime_ht * 100
                project.pourcentage_avancement_physique = Decimal(str(min(100, ratio)))

        elif project.methode_avancement == "jalons_atteints":
            total_jalons = int(await self.db.scalar(
                select(func.count(ProjectMilestone.id)).where(
                    ProjectMilestone.project_id == project_id
                )
            ) or 0)
            jalons_atteints = int(await self.db.scalar(
                select(func.count(ProjectMilestone.id)).where(
                    ProjectMilestone.project_id == project_id,
                    ProjectMilestone.atteint.is_(True),
                )
            ) or 0)
            if total_jalons > 0:
                project.pourcentage_avancement_physique = Decimal(
                    str(round(jalons_atteints / total_jalons * 100, 2))
                )

        await self.db.flush()

    async def calculer_avancement_a_facturer(self, project_id: UUID) -> AvancementSituationOut:
        """
        Calcule le montant à facturer selon la méthode à l'avancement SYSCOHADA.
        Montant à facturer = % avancement × montant marché - déjà facturé.
        """
        project = await self._get_project(project_id)

        deja_facture = int(await self.db.scalar(
            select(func.coalesce(func.sum(ProgressBilling.montant_situation_ht), 0))
            .where(
                ProgressBilling.project_id == project.id,
                ProgressBilling.statut.notin_([StatutSituation.BROUILLON, StatutSituation.ANNULEE]),
            )
        ) or 0)

        pct = float(project.pourcentage_avancement_physique)
        montant_a_facturer_cumule = int(project.montant_marche_ht * pct / 100)
        a_facturer_situation = max(0, montant_a_facturer_cumule - deja_facture)

        return AvancementSituationOut(
            project_id=project.id,
            montant_marche_ht=project.montant_marche_ht,
            pourcentage_avancement=pct,
            montant_a_facturer_cumule_ht=montant_a_facturer_cumule,
            montant_deja_facture_ht=deja_facture,
            montant_a_facturer_situation_ht=a_facturer_situation,
            ecart_a_facturer_ht=a_facturer_situation,
            methode=project.methode_reconnaissance,
            note=(
                f"Avancement {pct:.2f}% → {montant_a_facturer_cumule:,} FCFA cumulés. "
                f"Déjà facturé : {deja_facture:,} FCFA. "
                f"À facturer sur la prochaine situation : {a_facturer_situation:,} FCFA."
            ).replace(",", " "),
        )

    async def _recalculer_alerte(self, project: Project) -> None:
        """Recalcule le niveau d'alerte du projet."""
        if project.budget_previsionnel_ht == 0:
            project.niveau_alerte = NiveauAlerteProjet.OK
            return

        conso = project.budget_realise / project.budget_previsionnel_ht
        if conso >= SEUILS_ALERTE_PROJET["critique"]:
            project.niveau_alerte = NiveauAlerteProjet.CRITIQUE
        elif conso >= SEUILS_ALERTE_PROJET["alerte"]:
            project.niveau_alerte = NiveauAlerteProjet.ALERTE
        elif conso >= SEUILS_ALERTE_PROJET["vigilance"]:
            project.niveau_alerte = NiveauAlerteProjet.VIGILANCE
        else:
            project.niveau_alerte = NiveauAlerteProjet.OK

        # Retard planning
        if project.est_en_retard and project.statut == StatutProjet.EN_COURS:
            project.niveau_alerte = NiveauAlerteProjet.RETARD_PLANNING

        project.derniere_alerte_at = datetime.now(timezone.utc)
        await self.db.flush()

    # ═════════════════════════════════════════════════════════════════════
    # RENTABILITÉ & PORTEFEUILLE
    # ═════════════════════════════════════════════════════════════════════
    async def marge_projet(self, project_id: UUID) -> ProjectMarginOut:
        project = await self._get_project(project_id)

        # Marge actuelle = CA facturé - coûts réels
        ca_facture = int(await self.db.scalar(
            select(func.coalesce(func.sum(ProgressBilling.montant_cumule_actuel_ht), 0))
            .where(
                ProgressBilling.project_id == project.id,
                ProgressBilling.statut.notin_([StatutSituation.BROUILLON, StatutSituation.ANNULEE]),
            )
        ) or 0)

        marge_actuelle = ca_facture - project.budget_realise
        marge_actuelle_pct = (marge_actuelle / ca_facture * 100) if ca_facture > 0 else 0.0

        return ProjectMarginOut(
            project_id=project.id,
            code=project.code,
            libelle=project.libelle,
            statut=project.statut,
            montant_marche_ht=project.montant_marche_ht,
            budget_previsionnel_ht=project.budget_previsionnel_ht,
            budget_realise_ht=project.budget_realise,
            marge_previsionnelle=project.marge_previsionnelle,
            marge_previsionnelle_pct=round(project.marge_previsionnelle_pct, 2),
            marge_actuelle=marge_actuelle,
            marge_actuelle_pct=round(marge_actuelle_pct, 2),
            avancement_physique_pct=float(project.pourcentage_avancement_physique),
            avancement_financier_pct=float(project.pourcentage_avancement_financier),
            niveau_alerte=project.niveau_alerte,
            est_en_retard=project.est_en_retard,
        )

    async def portefeuille(self, statut: str | None = None) -> ProjectPortfolioOut:
        stmt = select(Project).where(Project.tenant_id == self.tenant_id)
        if statut:
            stmt = stmt.where(Project.statut == statut)
        projects = (await self.db.execute(stmt.order_by(Project.code))).scalars().all()

        lignes: list[ProjectMarginOut] = []
        total_marche = 0
        total_realise = 0
        for p in projects:
            m = await self.marge_projet(p.id)
            lignes.append(m)
            total_marche += m.montant_marche_ht
            total_realise += m.budget_realise_ht

        en_cours = sum(1 for p in projects if p.statut == "en_cours")
        termines = sum(1 for p in projects if p.statut == "termine")
        en_retard = sum(1 for p in projects if p.est_en_retard)
        depassement = sum(1 for p in projects if p.niveau_alerte == NiveauAlerteProjet.CRITIQUE)

        marge_globale = total_marche - total_realise
        marge_globale_pct = (marge_globale / total_marche * 100) if total_marche > 0 else 0.0

        return ProjectPortfolioOut(
            tenant_id=self.tenant_id,
            date_arret=date.today(),
            nb_projets_total=len(projects),
            nb_projets_en_cours=en_cours,
            nb_projets_termines=termines,
            nb_projets_en_retard=en_retard,
            nb_projets_depassement=depassement,
            montant_marche_total_ht=total_marche,
            budget_realise_total_ht=total_realise,
            marge_globale_ht=marge_globale,
            marge_globale_pct=round(marge_globale_pct, 2),
            projets=lignes,
        )

    # ═════════════════════════════════════════════════════════════════════
    # ÉCRITURES SYSCOHADA
    # ═════════════════════════════════════════════════════════════════════
    async def _generer_ecriture_cout(
        self, cost: ProjectCost, project: Project
    ) -> UUID:
        """
        Écriture d'imputation de coût au projet :
        Débit 6xx (charge) + 445x (TVA) / Crédit 401x (fournisseur)
        """
        lignes = [
            LigneIn(
                compte=cost.compte_comptable,
                libelle=f"{project.code} — {cost.libelle}",
                debit=cost.montant_ht,
            ),
        ]
        if cost.montant_tva > 0:
            lignes.append(LigneIn(
                compte="445200",
                libelle=f"TVA — {cost.libelle}",
                debit=cost.montant_tva,
            ))
        lignes.append(LigneIn(
            compte="401000",
            libelle=f"Fournisseur — {cost.libelle}",
            credit=cost.montant_ht + cost.montant_tva,
        ))

        journal = await self._resolve_journal(JOURNAL_PROJET)
        syscohada = SyscohadaService(self.db, self.tenant_id, self.user_id)
        e = await syscohada.create(EcritureCreate(
            numero_piece=f"COUT-{project.code}-{cost.id.hex[:6]}",
            date_ecriture=cost.date_cout,
            code_journal=journal,
            libelle=f"Coût projet {project.code} — {cost.libelle}",
            source=EcritureSource.SYSTEME,
            lignes=lignes,
        ))
        return e.id

    async def _generer_ecriture_situation(
        self, billing: ProgressBilling, project: Project
    ) -> UUID:
        """
        Écriture de situation de travaux :
        Débit 411x (Client)                     TTC
        Crédit 705x (Travaux facturés)          HT
        Crédit 443x (TVA)                       TVA
        Débit 4194 (Retenue garantie)           RG
        (le net à payer = TTC - RG - avance remboursée)
        """
        # Client (débit pour le TTC complet)
        total_ttc = billing.montant_situation_ht + billing.montant_tva

        lignes = [
            LigneIn(
                compte="411000",
                libelle=f"Situation {billing.numero} — {project.code}",
                debit=total_ttc,
            ),
            LigneIn(
                compte="705000",
                libelle=f"Travaux facturés — Situation {billing.numero}",
                credit=billing.montant_situation_ht,
            ),
        ]
        if billing.montant_tva > 0:
            lignes.append(LigneIn(
                compte="443100",
                libelle=f"TVA — Situation {billing.numero}",
                credit=billing.montant_tva,
            ))

        # Retenue de garantie (le client retient ce montant)
        if billing.retenue_garantie_montant > 0:
            lignes.append(LigneIn(
                compte="419400",
                libelle=f"Retenue de garantie — {project.code}",
                credit=billing.retenue_garantie_montant,
            ))

        # Remboursement avance (le client déduit ce montant)
        if billing.avance_remboursee_situation > 0:
            lignes.append(LigneIn(
                compte="419100",
                libelle=f"Remboursement avance — {project.code}",
                credit=billing.avance_remboursee_situation,
            ))

        # RAS
        if billing.ras_montant > 0:
            lignes.append(LigneIn(
                compte="447400",
                libelle=f"RAS — Situation {billing.numero}",
                credit=billing.ras_montant,
            ))

        # Équilibrage : si débit ≠ crédit, ajuster la ligne client
        td = sum(l.debit for l in lignes)
        tc = sum(l.credit for l in lignes)
        if td != tc:
            diff = td - tc
            # Ajuster le débit client
            for l in lignes:
                if l.compte == "411000":
                    l.debit -= diff
                    break

        journal = await self._resolve_journal(JOURNAL_PROJET)
        syscohada = SyscohadaService(self.db, self.tenant_id, self.user_id)
        e = await syscohada.create(EcritureCreate(
            numero_piece=billing.numero,
            date_ecriture=billing.date_situation,
            code_journal=journal,
            libelle=f"Situation de travaux {billing.numero} — {project.libelle}",
            reference_ext=billing.numero,
            source=EcritureSource.SYSTEME,
            lignes=lignes,
        ))
        return e.id

    # ═════════════════════════════════════════════════════════════════════
    # HELPERS
    # ═════════════════════════════════════════════════════════════════════
    async def _get_project(self, project_id: UUID) -> Project:
        p = await self.db.scalar(
            select(Project).where(
                Project.id == project_id,
                Project.tenant_id == self.tenant_id,
            )
        )
        if p is None:
            raise HTTPException(404, "Projet introuvable")
        return p

    async def _get_phase(self, phase_id: UUID) -> ProjectPhase:
        ph = await self.db.scalar(
            select(ProjectPhase).where(
                ProjectPhase.id == phase_id,
                ProjectPhase.tenant_id == self.tenant_id,
            )
        )
        if ph is None:
            raise HTTPException(404, "Phase introuvable")
        return ph

    async def _get_task(self, task_id: UUID) -> ProjectTask:
        t = await self.db.scalar(
            select(ProjectTask).where(
                ProjectTask.id == task_id,
                ProjectTask.tenant_id == self.tenant_id,
            )
        )
        if t is None:
            raise HTTPException(404, "Tâche introuvable")
        return t

    async def _get_billing(self, billing_id: UUID) -> ProgressBilling:
        b = await self.db.scalar(
            select(ProgressBilling).where(
                ProgressBilling.id == billing_id,
                ProgressBilling.tenant_id == self.tenant_id,
            )
        )
        if b is None:
            raise HTTPException(404, "Situation introuvable")
        return b

    async def _resolve_journal(self, code_prefere: str) -> str:
        try:
            await JournalService(self.db, self.tenant_id).get_by_code(code_prefere)
            return code_prefere
        except Exception:
            return "OD"

    async def _generer_numero_situation(self, project: Project, num: int) -> str:
        return f"SIT-{project.code}-{num:03d}"
