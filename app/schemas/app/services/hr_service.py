"""
Service RH — Départements, Contrats, Congés, Évaluations, Formations.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.hr_syscohada import (
    CONGE_ANNUEL_JOURS_AN,
    CONGE_ANNUEL_JOURS_PAR_MOIS,
    CONGE_DECES_CONJOINT_JOURS,
    CONGE_DECES_PARENT_JOURS,
    CONGE_MARIAGE_JOURS,
    CONGE_MATERNITE_SEMAINES,
    CONGE_NAISSANCE_JOURS,
    CONGE_PATERNITE_JOURS,
    DEPARTEMENTS_DEFAUT,
    MAJORATION_ANCIENNETE_5ANS,
    MAJORATION_ANCIENNETE_10ANS,
    MAJORATION_ANCIENNETE_15ANS,
    MAJORATION_ANCIENNETE_20ANS,
    NiveauPerformance,
    StatutDemandeConge,
    StatutEmploye,
    TypeConge,
    TypeContrat,
    niveau_performance_pour,
)
from app.models.hr import (
    Department,
    DisciplinaryAction,
    EmployeeAbsence,
    EmployeeDocument,
    EmployeeOffboarding,
    EmploymentContract,
    LeaveBalance,
    LeaveRequest,
    PerformanceReview,
    TimeEntry,
    Training,
    TrainingParticipant,
)
from app.models.payroll import Employee
from app.schemas.hr import (
    AbsenceCreate,
    AbsenceOut,
    ContractCreate,
    ContractRuptureIn,
    ContractUpdate,
    DepartmentCreate,
    DepartmentUpdate,
    EmployeeDocumentCreate,
    HRDashboardOut,
    LeaveApprovalIn,
    LeaveBalanceOut,
    LeaveCancelIn,
    LeaveRefuseIn,
    LeaveRequestCreate,
    LeaveSummaryOut,
    OffboardingCreate,
    ReviewCreate,
    ReviewFinalizeIn,
    ReviewUpdate,
    SanctionCreate,
    TimeEntryCreate,
    TrainingCreate,
    TrainingParticipantCreate,
    TrainingParticipantUpdate,
    TurnoverAnalysisOut,
)
from app.services.audit_service import AuditService

logger = logging.getLogger(__name__)


class HRService:
    def __init__(self, db: AsyncSession, tenant_id: UUID, user_id: UUID) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.audit = AuditService(db)

    # ═════════════════════════════════════════════════════════════════════
    # DÉPARTEMENTS
    # ═════════════════════════════════════════════════════════════════════
    async def creer_departement(self, data: DepartmentCreate) -> Department:
        existing = await self.db.scalar(
            select(Department.id).where(
                Department.tenant_id == self.tenant_id,
                Department.code == data.code,
            )
        )
        if existing:
            raise HTTPException(409, f"Département {data.code} déjà existant")

        dept = Department(tenant_id=self.tenant_id, **data.model_dump())
        self.db.add(dept)
        await self.db.flush()
        return dept

    async def seed_departements_defaut(self) -> int:
        """Initialise les départements par défaut."""
        existing_codes = set(
            (await self.db.execute(
                select(Department.code).where(Department.tenant_id == self.tenant_id)
            )).scalars().all()
        )
        created = 0
        for code, libelle in DEPARTEMENTS_DEFAUT:
            if code in existing_codes:
                continue
            self.db.add(Department(
                tenant_id=self.tenant_id, code=code, libelle=libelle,
            ))
            created += 1
        await self.db.flush()
        return created

    async def lister_departements(self, actif_only: bool = True) -> list[Department]:
        stmt = select(Department).where(Department.tenant_id == self.tenant_id)
        if actif_only:
            stmt = stmt.where(Department.actif.is_(True))
        return list((await self.db.execute(stmt.order_by(Department.code))).scalars().all())

    # ═════════════════════════════════════════════════════════════════════
    # CONTRATS
    # ═════════════════════════════════════════════════════════════════════
    async def creer_contrat(self, data: ContractCreate) -> EmploymentContract:
        emp = await self._get_employee(data.employee_id)

        # Vérifier qu'il n'y a pas de contrat actif
        existing_actif = await self.db.scalar(
            select(EmploymentContract.id).where(
                EmploymentContract.employee_id == emp.id,
                EmploymentContract.statut == "actif",
            )
        )
        if existing_actif:
            raise HTTPException(
                409,
                "Un contrat actif existe déjà. Clôturez-le avant d'en créer un nouveau.",
            )

        count = int(await self.db.scalar(
            select(func.count(EmploymentContract.id)).where(
                EmploymentContract.tenant_id == self.tenant_id
            )
        ) or 0)
        numero = f"CTR-{date.today().year}-{count + 1:05d}"

        # Calcul fin période d'essai
        date_fin_pe = None
        if data.periode_essai_mois:
            date_fin_pe = data.date_debut + timedelta(days=30 * data.periode_essai_mois)

        contract = EmploymentContract(
            tenant_id=self.tenant_id,
            employee_id=emp.id,
            numero=numero,
            type_contrat=data.type_contrat,
            date_debut=data.date_debut,
            date_fin=data.date_fin,
            date_signature=data.date_signature,
            periode_essai_mois=data.periode_essai_mois,
            date_fin_periode_essai=date_fin_pe,
            poste=data.poste,
            categorie_professionnelle=data.categorie_professionnelle,
            coefficient=data.coefficient,
            departement_id=data.departement_id,
            manager_employee_id=data.manager_employee_id,
            salaire_base_mensuel=data.salaire_base_mensuel,
            sursalaire=data.sursalaire,
            primes_contractuelles=data.primes_contractuelles,
            avantages=data.avantages,
            lieu_travail=data.lieu_travail,
            convention_collective=data.convention_collective,
            document_contrat_url=data.document_contrat_url,
            statut="actif",
            created_by=self.user_id,
        )
        self.db.add(contract)
        await self.db.flush()

        # Mettre à jour l'employé
        emp.salaire_base_mensuel = data.salaire_base_mensuel
        emp.sursalaire = data.sursalaire
        emp.poste = data.poste
        emp.type_contrat = data.type_contrat
        emp.date_embauche = data.date_debut if emp.date_embauche is None else emp.date_embauche

        # Créer le solde de congés pour l'année en cours
        await self._initialiser_solde_conges(emp.id, data.date_debut.year)

        await self.audit.log(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            action="HR_CONTRACT_CREATE",
            ressource="employment_contract",
            ressource_id=contract.id,
            payload={
                "numero": numero,
                "type": contract.type_contrat,
                "salaire": contract.salaire_base_mensuel,
            },
        )
        return contract

    async def modifier_contrat(
        self, contract_id: UUID, data: ContractUpdate
    ) -> EmploymentContract:
        contract = await self._get_contract(contract_id)
        for k, v in data.model_dump(exclude_unset=True).items():
            setattr(contract, k, v)
        await self.db.flush()
        return contract

    async def rompre_contrat(
        self, contract_id: UUID, data: ContractRuptureIn
    ) -> EmployeeOffboarding:
        """
        Rompt un contrat et déclenche l'offboarding avec calcul du solde de tout compte.
        """
        contract = await self._get_contract(contract_id)
        if contract.statut != "actif":
            raise HTTPException(400, f"Contrat {contract.statut} — non rompu")

        # Calculer l'ancienneté et le solde de tout compte
        emp = await self._get_employee(contract.employee_id)
        anciennete_annees = (data.date_effective - contract.date_debut).days / 365.25

        # Indemnité de préavis
        preavis_jours = self._calculer_preavis(emp, anciennete_annees)
        indemnite_preavis = 0
        if data.dispense_preavis:
            indemnite_preavis = int(
                contract.salaire_base_mensuel * preavis_jours / 30
            )

        # Indemnité de licenciement (si applicable)
        indemnite_licenciement = 0
        if data.motif in ("licenciement_faute", "licenciement_economique"):
            indemnite_licenciement = self._calculer_indemnite_licenciement(
                contract.salaire_base_mensuel, anciennete_annees
            )

        # Solde de congés
        balance = await self.db.scalar(
            select(LeaveBalance).where(
                LeaveBalance.employee_id == emp.id,
                LeaveBalance.annee == data.date_effective.year,
            )
        )
        solde_conges = float(balance.conges_annuels_solde) if balance else 0.0
        indemnite_conges = int(
            contract.salaire_base_mensuel * solde_conges / 26
        ) if solde_conges > 0 else 0

        total_solde = indemnite_conges + indemnite_preavis + indemnite_licenciement

        # Créer l'offboarding
        offboarding = EmployeeOffboarding(
            tenant_id=self.tenant_id,
            employee_id=emp.id,
            motif_depart=data.motif,
            date_annonce=date.today(),
            date_effective=data.date_effective,
            preavis_jours=preavis_jours,
            dispense_preavis=data.dispense_preavis,
            solde_conges_jours=Decimal(str(solde_conges)),
            indemnite_conges=indemnite_conges,
            indemnite_preavis=indemnite_preavis,
            indemnite_licenciement=indemnite_licenciement,
            total_solde=total_solde,
            statut="en_cours",
            created_by=self.user_id,
            metadata_={"commentaire": data.commentaire} if data.commentaire else {},
        )
        self.db.add(offboarding)

        # Mettre à jour le contrat et l'employé
        contract.statut = "rompu"
        contract.motif_rupture = data.motif
        contract.date_rupture = data.date_effective
        contract.preavis_jours = preavis_jours

        emp.actif = False
        emp.date_depart = data.date_effective
        emp.statut = "licencie" if "licenciement" in data.motif else "demissionnaire"

        await self.db.flush()

        await self.audit.log(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            action="HR_CONTRACT_TERMINATE",
            ressource="employment_contract",
            ressource_id=contract.id,
            payload={
                "motif": data.motif,
                "date_effective": str(data.date_effective),
                "total_solde": total_solde,
            },
        )
        return offboarding

    # ═════════════════════════════════════════════════════════════════════
    # CONGÉS
    # ═════════════════════════════════════════════════════════════════════
    async def _initialiser_solde_conges(
        self, employee_id: UUID, annee: int
    ) -> LeaveBalance:
        """
        Initialise le solde de congés pour une année.
        Formule : 2,2 jours par mois travaillé dans l'année.
        """
        emp = await self._get_employee(employee_id)

        existing = await self.db.scalar(
            select(LeaveBalance).where(
                LeaveBalance.employee_id == employee_id,
                LeaveBalance.annee == annee,
            )
        )
        if existing:
            return existing

        # Mois travaillés dans l'année
        debut_annee = date(annee, 1, 1)
        fin_annee = date(annee, 12, 31)

        date_debut = max(emp.date_embauche, debut_annee)
        date_fin = min(emp.date_depart or fin_annee, fin_annee)

        mois_travailles = max(0, (date_fin - date_debut).days / 30.5)
        conges_acquis = round(mois_travailles * CONGE_ANNUEL_JOURS_PAR_MOIS, 2)
        conges_acquis = min(conges_acquis, CONGE_ANNUEL_JOURS_AN)

        # Majoration ancienneté
        anciennete = (date_fin - emp.date_embauche).days / 365.25
        jours_anc = self._calculer_majoration_anciennete(anciennete)

        # Reprise du solde N-1 (max 15 jours selon CCI)
        solde_precedent = await self.db.scalar(
            select(LeaveBalance).where(
                LeaveBalance.employee_id == employee_id,
                LeaveBalance.annee == annee - 1,
            )
        )
        reportes = 0.0
        if solde_precedent:
            reportes = min(15.0, float(solde_precedent.conges_annuels_solde))

        solde_total = conges_acquis + jours_anc + reportes

        balance = LeaveBalance(
            tenant_id=self.tenant_id,
            employee_id=employee_id,
            annee=annee,
            conges_annuels_acquis=Decimal(str(conges_acquis)),
            conges_annuels_reportes=Decimal(str(reportes)),
            conges_annuels_pris=Decimal("0"),
            conges_annuels_solde=Decimal(str(solde_total)),
            jours_anciennete=Decimal(str(jours_anc)),
        )
        self.db.add(balance)
        await self.db.flush()
        return balance

    @staticmethod
    def _calculer_majoration_anciennete(annees: float) -> float:
        if annees >= 20:
            return MAJORATION_ANCIENNETE_20ANS
        if annees >= 15:
            return MAJORATION_ANCIENNETE_15ANS
        if annees >= 10:
            return MAJORATION_ANCIENNETE_10ANS
        if annees >= 5:
            return MAJORATION_ANCIENNETE_5ANS
        return 0.0

    async def get_solde_conges(
        self, employee_id: UUID, annee: int | None = None
    ) -> LeaveBalanceOut:
        annee = annee or date.today().year
        balance = await self.db.scalar(
            select(LeaveBalance).where(
                LeaveBalance.employee_id == employee_id,
                LeaveBalance.annee == annee,
            )
        )
        if balance is None:
            balance = await self._initialiser_solde_conges(employee_id, annee)
        return LeaveBalanceOut.model_validate(balance)

    async def creer_demande_conge(
        self, data: LeaveRequestCreate
    ) -> LeaveRequest:
        emp = await self._get_employee(data.employee_id)

        # Calculer les jours
        nb_jours_cal = (data.date_fin - data.date_debut).days + 1
        nb_jours_ouv = self._calculer_jours_ouvrables(data.date_debut, data.date_fin)

        # Vérifier le solde pour les congés annuels
        if data.type_conge == TypeConge.ANNUEL:
            balance = await self.db.scalar(
                select(LeaveBalance).where(
                    LeaveBalance.employee_id == emp.id,
                    LeaveBalance.annee == data.date_debut.year,
                )
            )
            if balance is None:
                balance = await self._initialiser_solde_conges(emp.id, data.date_debut.year)
            if float(balance.conges_annuels_solde) < nb_jours_ouv:
                raise HTTPException(
                    400,
                    f"Solde de congés insuffisant : "
                    f"{float(balance.conges_annuels_solde)} jours disponibles, "
                    f"{nb_jours_ouv} demandés",
                )

        # Générer la référence
        count = int(await self.db.scalar(
            select(func.count(LeaveRequest.id)).where(
                LeaveRequest.tenant_id == self.tenant_id
            )
        ) or 0)
        reference = f"CG-{data.date_debut.year}-{count + 1:05d}"

        req = LeaveRequest(
            tenant_id=self.tenant_id,
            employee_id=emp.id,
            reference=reference,
            type_conge=data.type_conge,
            date_debut=data.date_debut,
            date_fin=data.date_fin,
            nb_jours_ouvrables=Decimal(str(nb_jours_ouv)),
            nb_jours_calendaires=nb_jours_cal,
            motif=data.motif,
            justificatif_url=data.justificatif_url,
            statut=StatutDemandeConge.SOUMISE,
            manager_validateur_id=data.manager_validateur_id,
            created_by=self.user_id,
        )
        self.db.add(req)
        await self.db.flush()

        await self.audit.log(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            action="HR_LEAVE_REQUEST_CREATE",
            ressource="leave_request",
            ressource_id=req.id,
            payload={
                "reference": reference,
                "type": data.type_conge,
                "nb_jours": nb_jours_ouv,
            },
        )
        return req

    async def valider_conge_manager(
        self, leave_id: UUID, data: LeaveApprovalIn
    ) -> LeaveRequest:
        req = await self._get_leave(leave_id)
        if req.statut != StatutDemandeConge.SOUMISE:
            raise HTTPException(400, f"Demande {req.statut} — non validable")

        if data.approuve:
            req.statut = StatutDemandeConge.VALIDEE_MANAGER
            req.validee_manager_at = datetime.now(timezone.utc)
            req.validee_manager_par = self.user_id
            req.commentaire_manager = data.commentaire
        else:
            req.statut = StatutDemandeConge.REFUSEE
            req.refusee_at = datetime.now(timezone.utc)
            req.motif_refus = data.commentaire or "Refusé par le manager"

        await self.db.flush()
        return req

    async def valider_conge_rh(
        self, leave_id: UUID, data: LeaveApprovalIn
    ) -> LeaveRequest:
        req = await self._get_leave(leave_id)
        if req.statut != StatutDemandeConge.VALIDEE_MANAGER:
            raise HTTPException(400, "Validation manager requise avant RH")

        if data.approuve:
            req.statut = StatutDemandeConge.VALIDEE
            req.validee_rh_at = datetime.now(timezone.utc)
            req.rh_validateur_id = self.user_id
            req.commentaire_rh = data.commentaire
            req.validee_at = datetime.now(timezone.utc)

            # Décrémenter le solde
            if req.type_conge == TypeConge.ANNUEL:
                balance = await self.db.scalar(
                    select(LeaveBalance).where(
                        LeaveBalance.employee_id == req.employee_id,
                        LeaveBalance.annee == req.date_debut.year,
                    )
                )
                if balance:
                    balance.conges_annuels_pris = Decimal(
                        str(float(balance.conges_annuels_pris) + float(req.nb_jours_ouvrables))
                    )
                    balance.conges_annuels_solde = Decimal(
                        str(float(balance.conges_annuels_solde) - float(req.nb_jours_ouvrables))
                    )
        else:
            req.statut = StatutDemandeConge.REFUSEE
            req.refusee_at = datetime.now(timezone.utc)
            req.motif_refus = data.commentaire or "Refusé par les RH"

        await self.db.flush()
        return req

    async def annuler_conge(
        self, leave_id: UUID, data: LeaveCancelIn
    ) -> LeaveRequest:
        req = await self._get_leave(leave_id)
        if req.statut in (StatutDemandeConge.TERMINEE, StatutDemandeConge.REFUSEE):
            raise HTTPException(400, "Demande déjà clôturée")

        # Si déjà validée, remettre le solde
        if req.statut == StatutDemandeConge.VALIDEE and req.type_conge == TypeConge.ANNUEL:
            balance = await self.db.scalar(
                select(LeaveBalance).where(
                    LeaveBalance.employee_id == req.employee_id,
                    LeaveBalance.annee == req.date_debut.year,
                )
            )
            if balance:
                balance.conges_annuels_pris = Decimal(
                    str(max(0, float(balance.conges_annuels_pris) - float(req.nb_jours_ouvrables)))
                )
                balance.conges_annuels_solde = Decimal(
                    str(float(balance.conges_annuels_solde) + float(req.nb_jours_ouvrables))
                )

        req.statut = StatutDemandeConge.ANNULEE
        req.annulee_at = datetime.now(timezone.utc)
        req.motif_annulation = data.motif_annulation
        await self.db.flush()
        return req

    async def lister_conges(
        self,
        employee_id: UUID | None = None,
        statut: str | None = None,
        limit: int = 200,
    ) -> list[LeaveRequest]:
        stmt = select(LeaveRequest).where(LeaveRequest.tenant_id == self.tenant_id)
        if employee_id:
            stmt = stmt.where(LeaveRequest.employee_id == employee_id)
        if statut:
            stmt = stmt.where(LeaveRequest.statut == statut)
        stmt = stmt.order_by(LeaveRequest.date_debut.desc()).limit(limit)
        return list((await self.db.execute(stmt)).scalars().all())

    # ═════════════════════════════════════════════════════════════════════
    # ABSENCES
    # ═════════════════════════════════════════════════════════════════════
    async def creer_absence(self, data: AbsenceCreate) -> EmployeeAbsence:
        emp = await self._get_employee(data.employee_id)
        nb_jours = (data.date_fin - data.date_debut).days + 1

        # Retenue salaire si impact
        retenue = 0
        if data.impact_salaire:
            salaire_journalier = emp.salaire_base_mensuel / 26
            retenue = int(salaire_journalier * nb_jours)

        absence = EmployeeAbsence(
            tenant_id=self.tenant_id,
            employee_id=emp.id,
            date_debut=data.date_debut,
            date_fin=data.date_fin,
            nb_jours=Decimal(str(nb_jours)),
            type_absence=data.type_absence,
            motif=data.motif,
            justificatif_url=data.justificatif_url,
            impact_salaire=data.impact_salaire,
            montant_retenue=retenue,
            created_by=self.user_id,
        )
        self.db.add(absence)
        await self.db.flush()
        return absence

    # ═════════════════════════════════════════════════════════════════════
    # ÉVALUATIONS
    # ═════════════════════════════════════════════════════════════════════
    async def creer_evaluation(self, data: ReviewCreate) -> PerformanceReview:
        await self._get_employee(data.employee_id)

        count = int(await self.db.scalar(
            select(func.count(PerformanceReview.id)).where(
                PerformanceReview.tenant_id == self.tenant_id
            )
        ) or 0)
        reference = f"EVL-{date.today().year}-{count + 1:05d}"

        review = PerformanceReview(
            tenant_id=self.tenant_id,
            employee_id=data.employee_id,
            evaluateur_id=data.evaluateur_id,
            reference=reference,
            type_evaluation=data.type_evaluation,
            periode_debut=data.periode_debut,
            periode_fin=data.periode_fin,
            date_entretien=data.date_entretien,
            competences=data.competences,
            objectifs=data.objectifs,
            points_forts=data.points_forts,
            axes_amelioration=data.axes_amelioration,
            commentaires_employe=data.commentaires_employe,
            objectifs_prochaine_periode=data.objectifs_prochaine_periode,
            augmentation_proposee_pct=Decimal(str(data.augmentation_proposee_pct)) if data.augmentation_proposee_pct else None,
            promotion_proposee=data.promotion_proposee,
            nouveau_poste_propose=data.nouveau_poste_propose,
            statut="brouillon",
        )
        self.db.add(review)
        await self.db.flush()
        return review

    async def finaliser_evaluation(
        self, review_id: UUID, data: ReviewFinalizeIn
    ) -> PerformanceReview:
        review = await self.db.scalar(
            select(PerformanceReview).where(
                PerformanceReview.id == review_id,
                PerformanceReview.tenant_id == self.tenant_id,
            )
        )
        if review is None:
            raise HTTPException(404, "Évaluation introuvable")

        review.score_global = Decimal(str(data.score_global))
        review.niveau_performance = niveau_performance_pour(data.score_global)
        review.date_finalisation = date.today()
        review.statut = "finalisee"
        if data.commentaire:
            review.metadata_ = {**(review.metadata_ or {}), "commentaire_final": data.commentaire}

        await self.db.flush()
        return review

    # ═════════════════════════════════════════════════════════════════════
    # FORMATIONS
    # ═════════════════════════════════════════════════════════════════════
    async def creer_formation(self, data: TrainingCreate) -> Training:
        existing = await self.db.scalar(
            select(Training.id).where(
                Training.tenant_id == self.tenant_id,
                Training.code == data.code,
            )
        )
        if existing:
            raise HTTPException(409, f"Formation {data.code} déjà existante")

        training = Training(
            tenant_id=self.tenant_id,
            **data.model_dump(),
            statut="planifiee",
            created_by=self.user_id,
        )
        self.db.add(training)
        await self.db.flush()
        return training

    async def inscrire_participant(
        self, training_id: UUID, data: TrainingParticipantCreate
    ) -> TrainingParticipant:
        await self._get_employee(data.employee_id)

        training = await self.db.scalar(
            select(Training).where(
                Training.id == training_id,
                Training.tenant_id == self.tenant_id,
            )
        )
        if training is None:
            raise HTTPException(404, "Formation introuvable")

        existing = await self.db.scalar(
            select(TrainingParticipant.id).where(
                TrainingParticipant.training_id == training_id,
                TrainingParticipant.employee_id == data.employee_id,
            )
        )
        if existing:
            raise HTTPException(409, "Employé déjà inscrit")

        participant = TrainingParticipant(
            tenant_id=self.tenant_id,
            training_id=training_id,
            employee_id=data.employee_id,
            statut_participation="inscrit",
        )
        self.db.add(participant)
        await self.db.flush()
        return participant

    async def update_participant(
        self, participant_id: UUID, data: TrainingParticipantUpdate
    ) -> TrainingParticipant:
        p = await self.db.scalar(
            select(TrainingParticipant).where(
                TrainingParticipant.id == participant_id,
                TrainingParticipant.tenant_id == self.tenant_id,
            )
        )
        if p is None:
            raise HTTPException(404, "Participant introuvable")
        for k, v in data.model_dump(exclude_unset=True).items():
            setattr(p, k, v)
        await self.db.flush()
        return p

    # ═════════════════════════════════════════════════════════════════════
    # DOCUMENTS RH
    # ═════════════════════════════════════════════════════════════════════
    async def ajouter_document(
        self, data: EmployeeDocumentCreate
    ) -> EmployeeDocument:
        await self._get_employee(data.employee_id)
        doc = EmployeeDocument(
            tenant_id=self.tenant_id,
            **data.model_dump(),
            uploaded_by=self.user_id,
        )
        self.db.add(doc)
        await self.db.flush()
        return doc

    async def lister_documents(
        self, employee_id: UUID, type_document: str | None = None
    ) -> list[EmployeeDocument]:
        stmt = select(EmployeeDocument).where(
            EmployeeDocument.tenant_id == self.tenant_id,
            EmployeeDocument.employee_id == employee_id,
        )
        if type_document:
            stmt = stmt.where(EmployeeDocument.type_document == type_document)
        stmt = stmt.order_by(EmployeeDocument.created_at.desc())
        return list((await self.db.execute(stmt)).scalars().all())

    # ═════════════════════════════════════════════════════════════════════
    # SANCTIONS
    # ═════════════════════════════════════════════════════════════════════
    async def creer_sanction(self, data: SanctionCreate) -> DisciplinaryAction:
        await self._get_employee(data.employee_id)

        count = int(await self.db.scalar(
            select(func.count(DisciplinaryAction.id)).where(
                DisciplinaryAction.tenant_id == self.tenant_id
            )
        ) or 0)
        reference = f"SAN-{date.today().year}-{count + 1:05d}"

        sanction = DisciplinaryAction(
            tenant_id=self.tenant_id,
            reference=reference,
            **data.model_dump(),
            created_by=self.user_id,
        )
        self.db.add(sanction)
        await self.db.flush()
        return sanction

    # ═════════════════════════════════════════════════════════════════════
    # POINTAGE
    # ═════════════════════════════════════════════════════════════════════
    async def saisir_temps(self, data: TimeEntryCreate) -> TimeEntry:
        await self._get_employee(data.employee_id)

        existing = await self.db.scalar(
            select(TimeEntry.id).where(
                TimeEntry.employee_id == data.employee_id,
                TimeEntry.date_travail == data.date_travail,
            )
        )
        if existing:
            raise HTTPException(409, "Une saisie existe déjà pour cette date")

        entry = TimeEntry(
            tenant_id=self.tenant_id,
            **data.model_dump(),
        )
        self.db.add(entry)
        await self.db.flush()
        return entry

    # ═════════════════════════════════════════════════════════════════════
    # ANALYTICS RH
    # ═════════════════════════════════════════════════════════════════════
    async def dashboard(self) -> HRDashboardOut:
        today = date.today()
        annee = today.year

        # Effectif actif
        nb_actifs = int(await self.db.scalar(
            select(func.count(Employee.id)).where(
                Employee.tenant_id == self.tenant_id,
                Employee.actif.is_(True),
            )
        ) or 0)

        # Sorties 12 derniers mois
        il_y_a_12m = today - timedelta(days=365)
        nb_sortis = int(await self.db.scalar(
            select(func.count(Employee.id)).where(
                Employee.tenant_id == self.tenant_id,
                Employee.date_depart.isnot(None),
                Employee.date_depart >= il_y_a_12m,
            )
        ) or 0)

        # Employés en congé actuellement
        nb_en_conge = int(await self.db.scalar(
            select(func.count(LeaveRequest.id)).where(
                LeaveRequest.tenant_id == self.tenant_id,
                LeaveRequest.statut == StatutDemandeConge.VALIDEE,
                LeaveRequest.date_debut <= today,
                LeaveRequest.date_fin >= today,
            )
        ) or 0)

        # Période d'essai
        nb_pe = int(await self.db.scalar(
            select(func.count(EmploymentContract.id)).where(
                EmploymentContract.tenant_id == self.tenant_id,
                EmploymentContract.date_fin_periode_essai.isnot(None),
                EmploymentContract.date_fin_periode_essai >= today,
            )
        ) or 0)

        # Masse salariale mensuelle
        masse = int(await self.db.scalar(
            select(func.coalesce(func.sum(EmploymentContract.salaire_base_mensuel), 0)).where(
                EmploymentContract.tenant_id == self.tenant_id,
                EmploymentContract.statut == "actif",
            )
        ) or 0)

        # Congés en attente
        nb_conges_attente = int(await self.db.scalar(
            select(func.count(LeaveRequest.id)).where(
                LeaveRequest.tenant_id == self.tenant_id,
                LeaveRequest.statut.in_([StatutDemandeConge.SOUMISE, StatutDemandeConge.VALIDEE_MANAGER]),
            )
        ) or 0)

        # Évaluations à venir
        dans_30j = today + timedelta(days=30)
        nb_eval = int(await self.db.scalar(
            select(func.count(PerformanceReview.id)).where(
                PerformanceReview.tenant_id == self.tenant_id,
                PerformanceReview.date_entretien.isnot(None),
                PerformanceReview.date_entretien.between(today, dans_30j),
            )
        ) or 0)

        # Formations
        nb_form = int(await self.db.scalar(
            select(func.count(Training.id)).where(
                Training.tenant_id == self.tenant_id,
                Training.date_debut.between(today, dans_30j),
                Training.statut == "planifiee",
            )
        ) or 0)

        # Répartition par département
        rows = (
            await self.db.execute(
                select(Department.code, func.count(Employee.id))
                .outerjoin(EmploymentContract, EmploymentContract.departement_id == Department.id)
                .outerjoin(Employee, Employee.id == EmploymentContract.employee_id)
                .where(Department.tenant_id == self.tenant_id, Department.actif.is_(True))
                .group_by(Department.code)
            )
        ).all()
        repartition_dept = {r[0]: int(r[1]) for r in rows}

        # Répartition par type contrat
        rows2 = (
            await self.db.execute(
                select(EmploymentContract.type_contrat, func.count(EmploymentContract.id))
                .where(
                    EmploymentContract.tenant_id == self.tenant_id,
                    EmploymentContract.statut == "actif",
                )
                .group_by(EmploymentContract.type_contrat)
            )
        ).all()
        repartition_contrat = {r[0]: int(r[1]) for r in rows2}

        # Turnover
        effectif_moyen = max(1, nb_actifs + (nb_sortis // 2))
        turnover = round(nb_sortis / effectif_moyen * 100, 2)

        return HRDashboardOut(
            tenant_id=self.tenant_id,
            date_arret=today,
            nb_employes_actifs=nb_actifs,
            nb_employes_sortis_12m=nb_sortis,
            nb_employes_en_conge_actuellement=nb_en_conge,
            nb_candidats_periode_essai=nb_pe,
            taux_turnover_12m_pct=turnover,
            anciennete_moyenne_annees=0.0,
            masse_salariale_mensuelle_ht=masse,
            conges_en_attente_validation=nb_conges_attente,
            evaluations_a_venir_30j=nb_eval,
            formations_planifiees_30j=nb_form,
            repartition_par_departement=repartition_dept,
            repartition_par_contrat=repartition_contrat,
        )

    async def resume_conges(self, annee: int | None = None) -> LeaveSummaryOut:
        annee = annee or date.today().year
        stmt = select(LeaveRequest).where(
            LeaveRequest.tenant_id == self.tenant_id,
            func.extract("year", LeaveRequest.date_debut) == annee,
        )
        reqs = list((await self.db.execute(stmt)).scalars().all())

        validees = [r for r in reqs if r.statut in (StatutDemandeConge.VALIDEE, StatutDemandeConge.TERMINEE)]
        refusees = [r for r in reqs if r.statut == StatutDemandeConge.REFUSEE]
        attente = [r for r in reqs if r.statut in (StatutDemandeConge.SOUMISE, StatutDemandeConge.VALIDEE_MANAGER)]

        jours_total = sum(float(r.nb_jours_ouvrables) for r in validees)
        nb_actifs = int(await self.db.scalar(
            select(func.count(Employee.id)).where(
                Employee.tenant_id == self.tenant_id,
                Employee.actif.is_(True),
            )
        ) or 0)
        capacite = nb_actifs * CONGE_ANNUEL_JOURS_AN
        taux = (jours_total / capacite * 100) if capacite > 0 else 0.0

        return LeaveSummaryOut(
            tenant_id=self.tenant_id,
            annee=annee,
            nb_demandes_total=len(reqs),
            nb_validees=len(validees),
            nb_refusees=len(refusees),
            nb_en_attente=len(attente),
            jours_pris_total=jours_total,
            taux_utilisation_conges_pct=round(taux, 2),
            top_employes_conges=[],
        )

    # ═════════════════════════════════════════════════════════════════════
    # HELPERS
    # ═════════════════════════════════════════════════════════════════════
    async def _get_employee(self, employee_id: UUID) -> Employee:
        emp = await self.db.scalar(
            select(Employee).where(
                Employee.id == employee_id,
                Employee.tenant_id == self.tenant_id,
            )
        )
        if emp is None:
            raise HTTPException(404, "Employé introuvable")
        return emp

    async def _get_contract(self, contract_id: UUID) -> EmploymentContract:
        c = await self.db.scalar(
            select(EmploymentContract).where(
                EmploymentContract.id == contract_id,
                EmploymentContract.tenant_id == self.tenant_id,
            )
        )
        if c is None:
            raise HTTPException(404, "Contrat introuvable")
        return c

    async def _get_leave(self, leave_id: UUID) -> LeaveRequest:
        r = await self.db.scalar(
            select(LeaveRequest).where(
                LeaveRequest.id == leave_id,
                LeaveRequest.tenant_id == self.tenant_id,
            )
        )
        if r is None:
            raise HTTPException(404, "Demande de congé introuvable")
        return r

    @staticmethod
    def _calculer_jours_ouvrables(debut: date, fin: date) -> float:
        """Compte les jours ouvrables (lundi-samedi) entre 2 dates."""
        jours = 0
        d = debut
        while d <= fin:
            if d.weekday() != 6:  # Dimanche = 6
                jours += 1
            d += timedelta(days=1)
        return float(jours)

    @staticmethod
    def _calculer_preavis(emp: Employee, anciennete_annees: float) -> int:
        """Préavis selon Code du travail CI."""
        if anciennete_annees < 1:
            return 15
        if anciennete_annees < 5:
            return 30
        return 60

    @staticmethod
    def _calculer_indemnite_licenciement(salaire_mensuel: int, anciennete_annees: float) -> int:
        """
        Barème CCI CI :
        - 0-5 ans  : 30% du salaire mensuel par année
        - 5-10 ans : 35%
        - >10 ans  : 40%
        """
        total = 0.0
        annees = anciennete_annees

        if annees <= 5:
            total = salaire_mensuel * annees * 0.30
        elif annees <= 10:
            total = salaire_mensuel * 5 * 0.30 + salaire_mensuel * (annees - 5) * 0.35
        else:
            total = (
                salaire_mensuel * 5 * 0.30
                + salaire_mensuel * 5 * 0.35
                + salaire_mensuel * (annees - 10) * 0.40
            )
        return int(total)
