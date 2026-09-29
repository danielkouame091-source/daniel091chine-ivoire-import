"""
Tests du module RH.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.core.hr_syscohada import (
    NiveauPerformance,
    StatutDemandeConge,
    niveau_performance_pour,
)
from app.schemas.hr import (
    ContractCreate,
    ContractRuptureIn,
    DepartmentCreate,
    LeaveApprovalIn,
    LeaveCancelIn,
    LeaveRequestCreate,
    ReviewCreate,
    ReviewFinalizeIn,
    TrainingCreate,
    TrainingParticipantCreate,
    TrainingParticipantUpdate,
)
from app.services.hr_service import HRService

pytestmark = pytest.mark.integration


# ═════════════════════════════════════════════════════════════════════════════
# TESTS UNITAIRES (PURS)
# ═════════════════════════════════════════════════════════════════════════════
class TestNiveauPerformance:
    def test_insuffisant(self):
        assert niveau_performance_pour(30) == NiveauPerformance.INSUFFISANT

    def test_partiellement(self):
        assert niveau_performance_pour(60) == NiveauPerformance.PARTIELLEMENT_ATTEINT

    def test_atteint(self):
        assert niveau_performance_pour(80) == NiveauPerformance.ATTEINT

    def test_depasse(self):
        assert niveau_performance_pour(95) == NiveauPerformance.DEPASSE

    def test_exceptionnel(self):
        assert niveau_performance_pour(120) == NiveauPerformance.EXCEPTIONNEL


class TestCalculsRH:
    def test_indemnite_licenciement_5_ans(self):
        """5 ans à 30%/an × 500k = 750k."""
        from app.services.hr_service import HRService
        indemnite = HRService._calculer_indemnite_licenciement(500_000, 5)
        assert indemnite == int(500_000 * 5 * 0.30)   # 750 000

    def test_indemnite_licenciement_8_ans(self):
        """5 ans × 30% + 3 ans × 35% = 750k + 525k = 1 275k."""
        from app.services.hr_service import HRService
        indemnite = HRService._calculer_indemnite_licenciement(500_000, 8)
        attendu = int(500_000 * 5 * 0.30 + 500_000 * 3 * 0.35)
        assert indemnite == attendu

    def test_indemnite_licenciement_15_ans(self):
        """5 ans × 30% + 5 ans × 35% + 5 ans × 40%."""
        from app.services.hr_service import HRService
        indemnite = HRService._calculer_indemnite_licenciement(500_000, 15)
        attendu = int(
            500_000 * 5 * 0.30 + 500_000 * 5 * 0.35 + 500_000 * 5 * 0.40
        )
        assert indemnite == attendu

    def test_majoration_anciennete(self):
        from app.services.hr_service import HRService
        assert HRService._calculer_majoration_anciennete(3) == 0
        assert HRService._calculer_majoration_anciennete(6) == 1
        assert HRService._calculer_majoration_anciennete(12) == 2
        assert HRService._calculer_majoration_anciennete(18) == 3
        assert HRService._calculer_majoration_anciennete(25) == 4

    def test_jours_ouvrables(self):
        from app.services.hr_service import HRService
        # Lundi 2025-01-06 au vendredi 2025-01-10 = 5 jours ouvrables
        assert HRService._calculer_jours_ouvrables(
            date(2025, 1, 6), date(2025, 1, 10)
        ) == 5.0
        # Lundi au dimanche = 6 jours ouvrables (dimanche exclu)
        assert HRService._calculer_jours_ouvrables(
            date(2025, 1, 6), date(2025, 1, 12)
        ) == 6.0


# ─── Fixtures ───────────────────────────────────────────────────────────────
@pytest.fixture
async def department(db_session, tenant, admin_user):
    svc = HRService(db_session, tenant.id, admin_user.id)
    await svc.seed_departements_defaut()
    await db_session.flush()
    from app.models.hr import Department
    d = await db_session.scalar(
        select(Department).where(Department.code == "PROD")
    )
    return d


# ═════════════════════════════════════════════════════════════════════════════
# TESTS DÉPARTEMENTS
# ═════════════════════════════════════════════════════════════════════════════
class TestDepartements:
    async def test_seed_departements(self, db_session, tenant, admin_user):
        svc = HRService(db_session, tenant.id, admin_user.id)
        nb = await svc.seed_departements_defaut()
        assert nb >= 9
        # Idempotent
        nb2 = await svc.seed_departements_defaut()
        assert nb2 == 0

    async def test_creation_custom(self, db_session, tenant, admin_user):
        svc = HRService(db_session, tenant.id, admin_user.id)
        d = await svc.creer_departement(DepartmentCreate(
            code="RND", libelle="Recherche & Développement"
        ))
        assert d.code == "RND"


# ═════════════════════════════════════════════════════════════════════════════
# TESTS CONTRATS
# ═════════════════════════════════════════════════════════════════════════════
class TestContrats:
    async def _create_employee(self, db_session, tenant):
        from app.models.enums import UserRole, UserStatut
        from app.models.payroll import Employee
        emp = Employee(
            tenant_id=tenant.id,
            matricule="EMP-TEST-001",
            nom_prenoms="KOUAME Jean",
            date_embauche=date(2024, 1, 15),
            type_contrat="CDI",
            situation_familiale="celibataire",
            nombre_enfants=0,
            parts_fiscales=1.0,
            salaire_base_mensuel=350_000,
            taux_at_mp=3.0,
        )
        db_session.add(emp)
        await db_session.flush()
        return emp

    async def test_creation_contrat_cdi(
        self, db_session, tenant, admin_user, department
    ):
        emp = await self._create_employee(db_session, tenant)
        svc = HRService(db_session, tenant.id, admin_user.id)

        contract = await svc.creer_contrat(ContractCreate(
            employee_id=emp.id,
            type_contrat="CDI",
            date_debut=date(2024, 1, 15),
            poste="Développeur",
            departement_id=department.id,
            salaire_base_mensuel=500_000,
            periode_essai_mois=3,
        ))
        assert contract.numero.startswith("CTR-")
        assert contract.type_contrat == "CDI"
        assert contract.date_fin is None
        assert contract.date_fin_periode_essai is not None

        # Solde de congés initialisé
        balance = await svc.get_solde_conges(emp.id)
        assert balance.conges_annuels_solde >= 0

    async def test_contrat_cdd_avec_date_fin(
        self, db_session, tenant, admin_user
    ):
        emp = await self._create_employee(db_session, tenant)
        svc = HRService(db_session, tenant.id, admin_user.id)

        contract = await svc.creer_contrat(ContractCreate(
            employee_id=emp.id,
            type_contrat="CDD",
            date_debut=date(2025, 1, 1),
            date_fin=date(2025, 12, 31),
            poste="Assistant",
            salaire_base_mensuel=250_000,
        ))
        assert contract.type_contrat == "CDD"
        assert contract.date_fin == date(2025, 12, 31)

    async def test_double_contrat_actif_rejete(
        self, db_session, tenant, admin_user
    ):
        from fastapi import HTTPException
        emp = await self._create_employee(db_session, tenant)
        svc = HRService(db_session, tenant.id, admin_user.id)
        await svc.creer_contrat(ContractCreate(
            employee_id=emp.id,
            type_contrat="CDI",
            date_debut=date(2024, 1, 15),
            poste="Poste 1",
            salaire_base_mensuel=500_000,
        ))

        with pytest.raises(HTTPException) as exc:
            await svc.creer_contrat(ContractCreate(
                employee_id=emp.id,
                type_contrat="CDI",
                date_debut=date(2025, 1, 1),
                poste="Poste 2",
                salaire_base_mensuel=600_000,
            ))
        assert exc.value.status_code == 409

    async def test_rupture_contrat_avec_solde(
        self, db_session, tenant, admin_user
    ):
        emp = await self._create_employee(db_session, tenant)
        svc = HRService(db_session, tenant.id, admin_user.id)
        contract = await svc.creer_contrat(ContractCreate(
            employee_id=emp.id,
            type_contrat="CDI",
            date_debut=date(2020, 1, 15),
            poste="Chef de projet",
            salaire_base_mensuel=800_000,
        ))
        await db_session.flush()

        # Rompre le contrat
        offboarding = await svc.rompre_contrat(contract.id, ContractRuptureIn(
            motif="licenciement_economique",
            date_effective=date(2025, 6, 30),
            dispense_preavis=False,
        ))
        assert offboarding.motif_depart == "licenciement_economique"
        assert offboarding.indemnite_licenciement > 0
        assert offboarding.total_solde > 0

        # Contrat marqué rompu
        await db_session.refresh(contract)
        assert contract.statut == "rompu"


# ═════════════════════════════════════════════════════════════════════════════
# TESTS CONGÉS
# ═════════════════════════════════════════════════════════════════════════════
class TestConges:
    async def _create_employee_with_contract(
        self, db_session, tenant, admin_user
    ):
        from app.models.payroll import Employee
        emp = Employee(
            tenant_id=tenant.id,
            matricule="EMP-LEAVE",
            nom_prenoms="DIALLO Awa",
            date_embauche=date(2024, 1, 1),
            type_contrat="CDI",
            situation_familiale="celibataire",
            nombre_enfants=0,
            parts_fiscales=1.0,
            salaire_base_mensuel=400_000,
            taux_at_mp=3.0,
        )
        db_session.add(emp)
        await db_session.flush()

        svc = HRService(db_session, tenant.id, admin_user.id)
        await svc.creer_contrat(ContractCreate(
            employee_id=emp.id,
            type_contrat="CDI",
            date_debut=date(2024, 1, 1),
            poste="Comptable",
            salaire_base_mensuel=400_000,
        ))
        return emp

    async def test_solde_conges_apres_1_an(
        self, db_session, tenant, admin_user
    ):
        emp = await self._create_employee_with_contract(
            db_session, tenant, admin_user
        )
        svc = HRService(db_session, tenant.id, admin_user.id)
        balance = await svc.get_solde_conges(emp.id, annee=2024)
        # 12 mois × 2,2 = 26,4 → plafonné à 26
        assert float(balance.conges_annuels_solde) <= 26.0
        assert float(balance.conges_annuels_solde) > 0

    async def test_cycle_complet_conge(
        self, db_session, tenant, admin_user
    ):
        emp = await self._create_employee_with_contract(
            db_session, tenant, admin_user
        )
        svc = HRService(db_session, tenant.id, admin_user.id)

        # Créer une demande
        req = await svc.creer_demande_conge(LeaveRequestCreate(
            employee_id=emp.id,
            type_conge="annuel",
            date_debut=date(2025, 3, 1),
            date_fin=date(2025, 3, 15),
            motif="Congés annuels",
        ))
        assert req.statut == StatutDemandeConge.SOUMISE
        assert req.nb_jours_calendaires == 15

        # Validation manager
        req = await svc.valider_conge_manager(req.id, LeaveApprovalIn(
            approuve=True, commentaire="OK"
        ))
        assert req.statut == StatutDemandeConge.VALIDEE_MANAGER

        # Validation RH
        solde_avant = float((await svc.get_solde_conges(emp.id, annee=2025)).conges_annuels_solde)
        req = await svc.valider_conge_rh(req.id, LeaveApprovalIn(approuve=True))
        assert req.statut == StatutDemandeConge.VALIDEE
        assert req.validee_at is not None

        # Le solde a diminué
        solde_apres = float((await svc.get_solde_conges(emp.id, annee=2025)).conges_annuels_solde)
        assert solde_apres < solde_avant

    async def test_solde_insuffisant_rejete(
        self, db_session, tenant, admin_user
    ):
        from fastapi import HTTPException
        emp = await self._create_employee_with_contract(
            db_session, tenant, admin_user
        )
        svc = HRService(db_session, tenant.id, admin_user.id)

        with pytest.raises(HTTPException) as exc:
            await svc.creer_demande_conge(LeaveRequestCreate(
                employee_id=emp.id,
                type_conge="annuel",
                date_debut=date(2025, 3, 1),
                date_fin=date(2025, 6, 30),   # 4 mois > solde
            ))
        assert "insuffisant" in exc.value.detail.lower()

    async def test_refus_conge(self, db_session, tenant, admin_user):
        emp = await self._create_employee_with_contract(
            db_session, tenant, admin_user
        )
        svc = HRService(db_session, tenant.id, admin_user.id)
        req = await svc.creer_demande_conge(LeaveRequestCreate(
            employee_id=emp.id,
            type_conge="annuel",
            date_debut=date(2025, 3, 1),
            date_fin=date(2025, 3, 5),
        ))
        req = await svc.valider_conge_manager(req.id, LeaveApprovalIn(
            approuve=False, commentaire="Pic d'activité"
        ))
        assert req.statut == StatutDemandeConge.REFUSEE
        assert req.motif_refus == "Pic d'activité"

    async def test_annulation_remet_solde(
        self, db_session, tenant, admin_user
    ):
        emp = await self._create_employee_with_contract(
            db_session, tenant, admin_user
        )
        svc = HRService(db_session, tenant.id, admin_user.id)
        solde_avant = float((await svc.get_solde_conges(emp.id, annee=2025)).conges_annuels_solde)

        req = await svc.creer_demande_conge(LeaveRequestCreate(
            employee_id=emp.id,
            type_conge="annuel",
            date_debut=date(2025, 3, 1),
            date_fin=date(2025, 3, 5),
        ))
        await svc.valider_conge_manager(req.id, LeaveApprovalIn(approuve=True))
        await svc.valider_conge_rh(req.id, LeaveApprovalIn(approuve=True))

        solde_mid = float((await svc.get_solde_conges(emp.id, annee=2025)).conges_annuels_solde)
        assert solde_mid < solde_avant

        # Annuler
        await svc.annuler_conge(req.id, LeaveCancelIn(
            motif_annulation="Annulation personnelle"
        ))
        solde_final = float((await svc.get_solde_conges(emp.id, annee=2025)).conges_annuels_solde)
        assert solde_final == solde_avant   # Solde restitué


# ═════════════════════════════════════════════════════════════════════════════
# TESTS ÉVALUATIONS
# ═════════════════════════════════════════════════════════════════════════════
class TestEvaluations:
    async def test_creation_et_finalisation(
        self, db_session, tenant, admin_user
    ):
        from app.models.payroll import Employee
        emp = Employee(
            tenant_id=tenant.id,
            matricule="EMP-EVAL",
            nom_prenoms="TRAORE Moussa",
            date_embauche=date(2024, 1, 1),
            type_contrat="CDI",
            situation_familiale="celibataire",
            nombre_enfants=0,
            parts_fiscales=1.0,
            salaire_base_mensuel=300_000,
            taux_at_mp=3.0,
        )
        db_session.add(emp)
        await db_session.flush()

        svc = HRService(db_session, tenant.id, admin_user.id)
        review = await svc.creer_evaluation(ReviewCreate(
            employee_id=emp.id,
            type_evaluation="annuelle",
            periode_debut=date(2024, 1, 1),
            periode_fin=date(2024, 12, 31),
            competences=[
                {"libelle": "Communication", "score": 85},
                {"libelle": "Technique", "score": 90},
            ],
        ))
        assert review.reference.startswith("EVL-")
        assert review.statut == "brouillon"

        # Finaliser
        review = await svc.finaliser_evaluation(review.id, ReviewFinalizeIn(
            score_global=95.0,
            commentaire="Excellente performance",
        ))
        assert review.statut == "finalisee"
        assert review.niveau_performance == NiveauPerformance.DEPASSE


# ═════════════════════════════════════════════════════════════════════════════
# TESTS FORMATIONS
# ═════════════════════════════════════════════════════════════════════════════
class TestFormations:
    async def test_creation_et_inscription(
        self, db_session, tenant, admin_user
    ):
        from app.models.payroll import Employee
        emp = Employee(
            tenant_id=tenant.id,
            matricule="EMP-FORM",
            nom_prenoms="KONE Fatou",
            date_embauche=date(2024, 1, 1),
            type_contrat="CDI",
            situation_familiale="celibataire",
            nombre_enfants=0,
            parts_fiscales=1.0,
            salaire_base_mensuel=400_000,
            taux_at_mp=3.0,
        )
        db_session.add(emp)
        await db_session.flush()

        svc = HRService(db_session, tenant.id, admin_user.id)

        training = await svc.creer_formation(TrainingCreate(
            code="FORM-EXCEL-2025",
            titre="Excel Avancé pour comptables",
            type_formation="technique",
            date_debut=date(2025, 4, 1),
            date_fin=date(2025, 4, 3),
            duree_heures=21,
            cout_total=150_000,
            pris_en_charge_employeur=150_000,
        ))
        assert training.code == "FORM-EXCEL-2025"

        # Inscrire
        p = await svc.inscrire_participant(training.id, TrainingParticipantCreate(
            employee_id=emp.id
        ))
        assert p.statut_participation == "inscrit"

        # Mettre à jour après formation
        p = await svc.update_participant(p.id, TrainingParticipantUpdate(
            statut_participation="complete",
            presence_pct=100.0,
            score_evaluation=88.0,
            certification_obtenue=True,
            note_satisfaction=5,
        ))
        assert p.certification_obtenue is True
        assert p.note_satisfaction == 5


# ═════════════════════════════════════════════════════════════════════════════
# TESTS DASHBOARD
# ═════════════════════════════════════════════════════════════════════════════
class TestHRDashboard:
    async def test_dashboard_vide(self, db_session, tenant, admin_user):
        svc = HRService(db_session, tenant.id, admin_user.id)
        dash = await svc.dashboard()
        assert dash.nb_employes_actifs == 0
        assert dash.masse_salariale_mensuelle_ht == 0
