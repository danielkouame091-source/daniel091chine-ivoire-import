"""
Référentiel RH — Droit du travail ivoirien + bonnes pratiques OHADA.

Sources :
- Code du Travail de Côte d'Ivoire (Loi n° 2015-532 du 20/07/2015)
- Convention Collective Interprofessionnelle (CCI) de Côte d'Ivoire
- Décret n° 96-197 sur les congés payés
- CNPS — régimes de prestations
"""
from __future__ import annotations

from typing import NamedTuple


# ─────────────────────────────────────────────────────────────────────────────
# Types de contrat
# ─────────────────────────────────────────────────────────────────────────────
class TypeContrat:
    CDI = "CDI"                              # Contrat à Durée Indéterminée
    CDD = "CDD"                              # Contrat à Durée Déterminée
    STAGE = "Stage"
    APPRENTISSAGE = "Apprentissage"
    INTERIM = "Interim"
    CONSULTANT = "Consultant"                # Prestataire indépendant
    STAGIAIRE_ECOLE = "Stagiaire école"      # Stage académique


TYPES_CONTRAT = {
    TypeContrat.CDI, TypeContrat.CDD, TypeContrat.STAGE,
    TypeContrat.APPRENTISSAGE, TypeContrat.INTERIM,
    TypeContrat.CONSULTANT, TypeContrat.STAGIAIRE_ECOLE,
}


# ─────────────────────────────────────────────────────────────────────────────
# Statuts employé
# ─────────────────────────────────────────────────────────────────────────────
class StatutEmploye:
    ACTIF = "actif"
    EN_CONGE = "en_conge"
    SUSPENDU = "suspendu"                    # Mise à pied
    EN_MATERNITE = "en_maternite"
    EN_MALADIE = "en_maladie"
    DEMISSIONNAIRE = "demissionnaire"        # Préavis en cours
    LICENCIE = "licencie"                    # Sortie
    RETRAITE = "retraite"
    DECEDE = "decede"


# ─────────────────────────────────────────────────────────────────────────────
# Types de congés (droit ivoirien)
# ─────────────────────────────────────────────────────────────────────────────
class TypeConge:
    ANNUEL = "annuel"                        # 26 jours ouvrables par an
    MALADIE = "maladie"
    MATERNITE = "maternite"                  # 14 semaines
    PATERNITE = "paternite"                  # 10 jours
    EXCEPTIONNEL = "exceptionnel"            # Mariage, décès
    SANS_SOLDE = "sans_solde"
    FORMATION = "formation"
    SABBATIQUE = "sabbatique"
    MARIAGE = "mariage"                      # 4 jours
    DECES_CONJOINT = "deces_conjoint"        # 5 jours
    DECES_PARENT = "deces_parent"            # 3 jours
    NAISSANCE = "naissance"                  # 3 jours


# Droit annuel standard (Code du travail CI)
CONGE_ANNUEL_JOURS_PAR_MOIS = 2.2            # 2,2 jours ouvrables par mois travaillé
CONGE_ANNUEL_JOURS_AN = 26                   # 26 jours ouvrables par an (2,2 × 12)
CONGE_MATERNITE_SEMAINES = 14                # 14 semaines (dont 8 post-natal)
CONGE_PATERNITE_JOURS = 10
CONGE_MARIAGE_JOURS = 4
CONGE_DECES_CONJOINT_JOURS = 5
CONGE_DECES_PARENT_JOURS = 3
CONGE_NAISSANCE_JOURS = 3

# Majorations
MAJORATION_ANCIENNETE_5ANS = 1               # +1 jour après 5 ans
MAJORATION_ANCIENNETE_10ANS = 2              # +2 jours après 10 ans
MAJORATION_ANCIENNETE_15ANS = 3              # +3 jours après 15 ans
MAJORATION_ANCIENNETE_20ANS = 4              # +4 jours après 20 ans


# ─────────────────────────────────────────────────────────────────────────────
# Statuts de demande de congé
# ─────────────────────────────────────────────────────────────────────────────
class StatutDemandeConge:
    BROUILLON = "brouillon"
    SOUMISE = "soumise"
    VALIDEE_MANAGER = "validee_manager"
    VALIDEE_RH = "validee_rh"
    VALIDEE = "validee"                      # Validation finale
    REFUSEE = "refusee"
    ANNULEE = "annulee"
    EN_COURS = "en_cours"                    # Congé effectivement en cours
    TERMINEE = "terminee"


# ─────────────────────────────────────────────────────────────────────────────
# Départements types
# ─────────────────────────────────────────────────────────────────────────────
DEPARTEMENTS_DEFAUT: list[tuple[str, str]] = [
    ("DG", "Direction Générale"),
    ("DAF", "Direction Administrative et Financière"),
    ("RH", "Ressources Humaines"),
    ("COM", "Commercial & Ventes"),
    ("PROD", "Production"),
    ("IT", "Systèmes d'Information"),
    ("LOG", "Logistique & Achats"),
    ("JUR", "Juridique"),
    ("MKT", "Marketing & Communication"),
]


# ─────────────────────────────────────────────────────────────────────────────
# Types d'évaluation
# ─────────────────────────────────────────────────────────────────────────────
class TypeEvaluation:
    ANNUELLE = "annuelle"
    SEMESTRIELLE = "semestrielle"
    PROBATOIRE = "probatoire"                # Fin de période d'essai
    OBJECTIFS = "objectifs"                  # Suivi d'objectifs
    A_CHAUD = "a_chaud"                      # Feedback rapide
    RECONNAISSANCE = "reconnaissance"
    PLAN_DEVELOPPEMENT = "plan_developpement"


# ─────────────────────────────────────────────────────────────────────────────
# Niveaux de performance
# ─────────────────────────────────────────────────────────────────────────────
class NiveauPerformance:
    INSUFFISANT = "insuffisant"              # < 50%
    PARTIELLEMENT_ATTEINT = "partiellement_atteint"   # 50-70%
    ATTEINT = "atteint"                      # 70-90%
    DEPASSE = "depasse"                      # 90-110%
    EXCEPTIONNEL = "exceptionnel"            # > 110%


def niveau_performance_pour(score_pct: float) -> str:
    if score_pct >= 110:
        return NiveauPerformance.EXCEPTIONNEL
    if score_pct >= 90:
        return NiveauPerformance.DEPASSE
    if score_pct >= 70:
        return NiveauPerformance.ATTEINT
    if score_pct >= 50:
        return NiveauPerformance.PARTIELLEMENT_ATTEINT
    return NiveauPerformance.INSUFFISANT


# ─────────────────────────────────────────────────────────────────────────────
# Types de documents RH
# ─────────────────────────────────────────────────────────────────────────────
class TypeDocumentRH:
    CONTRAT = "contrat"
    AVENANT = "avenant"
    CERTIFICAT_TRAVAIL = "certificat_travail"
    ATTESTATION_TRAVAIL = "attestation_travail"
    BULLETIN_PAIE = "bulletin_paie"
    CV = "cv"
    DIPLOME = "diplome"
    ATTESTATION_FORMATION = "attestation_formation"
    FICHE_POSTE = "fiche_poste"
    LETTRE_LICENCIEMENT = "lettre_licenciement"
    LETTRE_DEMISSION = "lettre_demission"
    CERTIFICAT_MEDICAL = "certificat_medical"
    AUTRE = "autre"


# ─────────────────────────────────────────────────────────────────────────────
# Types de formation
# ─────────────────────────────────────────────────────────────────────────────
class TypeFormation:
    INITIALE = "initiale"
    CONTINUE = "continue"
    SECURITE = "securite"
    TECHNIQUE = "technique"
    MANAGERIALE = "manageriale"
    LINGUISTIQUE = "linguistique"
    INFORMATIQUE = "informatique"
    CERTIFIANTE = "certifiante"


class StatutFormation:
    PLANIFIEE = "planifiee"
    EN_COURS = "en_cours"
    TERMINEE = "terminee"
    ANNULEE = "annulee"
    REPORTEE = "reportee"


# ─────────────────────────────────────────────────────────────────────────────
# Types de sanctions disciplinaires
# ─────────────────────────────────────────────────────────────────────────────
class SanctionDisciplinaire:
    AVERTISSEMENT_ECRIT = "avertissement_ecrit"
    BLAME = "blame"
    MISE_A_PIED_1_3J = "mise_a_pied_1_3j"
    MISE_A_PIED_4_8J = "mise_a_pied_4_8j"
    LICENCIEMENT = "licenciement"


# ─────────────────────────────────────────────────────────────────────────────
# Types de sortie / motif de départ
# ─────────────────────────────────────────────────────────────────────────────
class MotifDepart:
    DEMISSION = "demission"
    LICENCIEMENT_FAUTE = "licenciement_faute"
    LICENCIEMENT_ECO = "licenciement_economique"
    RUPTURE_CONVENTIONNELLE = "rupture_conventionnelle"
    FIN_CDD = "fin_cdd"
    RETRAITE = "retraite"
    DECES = "deces"
    ABANDON_POSTE = "abandon_poste"
    PERIODE_ESSAI_NON_CONCLUANTE = "periode_essai_non_concluante"


# ─────────────────────────────────────────────────────────────────────────────
# Préavis (Code du travail CI)
# ─────────────────────────────────────────────────────────────────────────────
class DureePreavis:
    """Durée de préavis selon catégorie professionnelle (CCI CI)."""
    OUVRIER_MOINS_1AN = 8                    # jours
    OUVRIER_1_5ANS = 15
    OUVRIER_PLUS_5ANS = 30
    EMPLOYE_MOINS_1AN = 15
    EMPLOYE_1_5ANS = 30
    EMPLOYE_PLUS_5ANS = 60
    CADRE_MOINS_1AN = 30
    CADRE_1_5ANS = 60
    CADRE_PLUS_5ANS = 90


# ─────────────────────────────────────────────────────────────────────────────
# Indemnité de licenciement (CCI CI)
# ─────────────────────────────────────────────────────────────────────────────
# Barème : 30% du salaire mensuel par année de présence (jusqu'à 5 ans),
# puis 35% (5-10 ans), puis 40% (>10 ans)
INDEMNITE_LICENCIEMENT_TAUX = [
    (0, 5, 0.30),
    (5, 10, 0.35),
    (10, 100, 0.40),
]


# ─────────────────────────────────────────────────────────────────────────────
# Seuils et règles
# ─────────────────────────────────────────────────────────────────────────────
JOURS_ALERTE_SOLDE_CONGES = 5                # Alerte si solde < 5 jours
JOURS_ALERTE_FIN_CDD = 30                    # Alerte 30j avant fin CDD
JOURS_ALERTE_FIN_PERIODE_ESSAI = 7           # Alerte 7j avant fin période d'essai
ANCIENNETE_AUGMENTATION_AUTO_PCT = 0.02      # +2% par an d'ancienneté (indicatif)


# ─────────────────────────────────────────────────────────────────────────────
# Messages types
# ─────────────────────────────────────────────────────────────────────────────
MESSAGE_CONGE_VALIDE = """
Bonjour {prenom},

Votre demande de congé du {date_debut} au {date_fin} ({nb_jours} jours) a été validée.

Bon repos !
L'équipe RH — {tenant_nom}
"""

MESSAGE_CONGE_REFUSE = """
Bonjour {prenom},

Votre demande de congé du {date_debut} au {date_fin} a été refusée.

Motif : {motif}

Pour plus d'informations, contactez votre manager ou le service RH.

L'équipe RH — {tenant_nom}
"""
