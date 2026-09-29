"""
Référentiel Audit & Contrôle interne — SYSCOHADA & DGI CI.

Sources :
- SYSCOHADA révisé — obligations de tenue des livres
- CGI CI — obligations de conservation (10 ans) et piste d'audit fiable
- Normes ISA (International Standards on Auditing) adaptées PME
- Loi ivoirienne 2013-546 sur les transactions électroniques
- RGPD-like (Loi 2013-450 sur la protection des données CI)
"""
from __future__ import annotations

from typing import NamedTuple


# ─────────────────────────────────────────────────────────────────────────────
# Catégories de contrôle
# ─────────────────────────────────────────────────────────────────────────────
class CategorieControle:
    COHERENCE_COMPTABLE = "coherence_comptable"      # Équilibre, partie double
    INTEGRITE_DONNEES = "integrite_donnees"          # Nulls, orphelins, doublons
    CONFORMITE_FISCALE = "conformite_fiscale"        # TVA, RAS, DGI
    CONFORMITE_SOCIALE = "conformite_sociale"        # CNPS, ITS
    SECURITE_ACCES = "securite_acces"                # Rôles, sessions, IP
    FRAUDE_DETECTION = "fraude_detection"            # Benford, patterns suspects
    PERFORMANCE = "performance"                      # Volumes anormaux
    TRAÇABILITE = "tracabilite"                      # Audit trail complet


CATEGORIES_CONTROLE = {
    CategorieControle.COHERENCE_COMPTABLE,
    CategorieControle.INTEGRITE_DONNEES,
    CategorieControle.CONFORMITE_FISCALE,
    CategorieControle.CONFORMITE_SOCIALE,
    CategorieControle.SECURITE_ACCES,
    CategorieControle.FRAUDE_DETECTION,
    CategorieControle.PERFORMANCE,
    CategorieControle.TRACABILITE,
}


# ─────────────────────────────────────────────────────────────────────────────
# Niveaux de sévérité
# ─────────────────────────────────────────────────────────────────────────────
class SeveriteFinding:
    INFO = "info"                    # Information, pas d'action requise
    LOW = "low"                      # À surveiller
    MEDIUM = "medium"                # À corriger
    HIGH = "high"                    # Urgent
    CRITIQUE = "critique"            # Bloquant (fraude suspectée, erreur grave)


SEVERITES_ORDRE = {
    SeveriteFinding.INFO: 0,
    SeveriteFinding.LOW: 1,
    SeveriteFinding.MEDIUM: 2,
    SeveriteFinding.HIGH: 3,
    SeveriteFinding.CRITIQUE: 4,
}


# ─────────────────────────────────────────────────────────────────────────────
# Statuts de finding
# ─────────────────────────────────────────────────────────────────────────────
class StatutFinding:
    NOUVEAU = "nouveau"
    EN_COURS = "en_cours"
    RESOLU = "resolu"
    IGNORE = "ignore"                # Faux positif accepté
    FAUX_POSITIF = "faux_positif"
    ESCALADE = "escalade"            # Escaladé au fondateur


# ─────────────────────────────────────────────────────────────────────────────
# Types de règles d'audit (moteur)
# ─────────────────────────────────────────────────────────────────────────────
class TypeRegleAudit:
    # Cohérence comptable
    ECRITURE_DESEQUILIBREE = "ecriture_desequilibree"
    ECRITURE_SANS_LIGNE = "ecriture_sans_ligne"
    COMPTE_INEXISTANT = "compte_inexistant"
    EXERCICE_CLOTURE_MODIFIE = "exercice_cloture_modifie"
    # Intégrité
    ECRITURE_DOUBLON = "ecriture_doublon"
    TIERS_ORPHELIN = "tiers_orphelin"
    COMPTE_NON_LETTRE_ANCIEN = "compte_non_lettre_ancien"
    # Conformité fiscale
    TVA_MANQUANTE = "tva_manquante"
    RAS_NON_DECLAREE = "ras_non_declaree"
    FACTURE_SANS_FNE = "facture_sans_fne"
    DECLARATION_DGI_RETARD = "declaration_dgi_retard"
    # Sécurité
    CONNEXION_IP_SUSPECTE = "connexion_ip_suspecte"
    ACCES_HORS_HORAIRES = "acces_hors_horaires"
    MODIFICATION_SANS_AUDIT = "modification_sans_audit"
    # Fraude
    LOI_BENFORD = "loi_benford"                       # Distribution non conforme
    MONTANTS_JUSTE_SOUS_SEUIL = "montants_juste_sous_seuil"
    TRANSACTIONS_CIRCULAIRES = "transactions_circulaires"
    FOURNISSEUR_RECENT_GROS_MONTANT = "fournisseur_recent_gros_montant"
    UTILISATEUR_VOLUME_ANORMAL = "utilisateur_volume_anormal"
    # Performance
    ECRITURE_NON_VALIDEE_ANCIENNE = "ecriture_non_validee_ancienne"


TYPES_REGLES_AUDIT = {
    TypeRegleAudit.ECRITURE_DESEQUILIBREE,
    TypeRegleAudit.ECRITURE_SANS_LIGNE,
    TypeRegleAudit.COMPTE_INEXISTANT,
    TypeRegleAudit.EXERCICE_CLOTURE_MODIFIE,
    TypeRegleAudit.ECRITURE_DOUBLON,
    TypeRegleAudit.TIERS_ORPHELIN,
    TypeRegleAudit.COMPTE_NON_LETTRE_ANCIEN,
    TypeRegleAudit.TVA_MANQUANTE,
    TypeRegleAudit.RAS_NON_DECLAREE,
    TypeRegleAudit.FACTURE_SANS_FNE,
    TypeRegleAudit.DECLARATION_DGI_RETARD,
    TypeRegleAudit.CONNEXION_IP_SUSPECTE,
    TypeRegleAudit.ACCES_HORS_HORAIRES,
    TypeRegleAudit.MODIFICATION_SANS_AUDIT,
    TypeRegleAudit.LOI_BENFORD,
    TypeRegleAudit.MONTANTS_JUSTE_SOUS_SEUIL,
    TypeRegleAudit.TRANSACTIONS_CIRCULAIRES,
    TypeRegleAudit.FOURNISSEUR_RECENT_GROS_MONTANT,
    TypeRegleAudit.UTILISATEUR_VOLUME_ANORMAL,
    TypeRegleAudit.ECRITURE_NON_VALIDEE_ANCIENNE,
}


# ─────────────────────────────────────────────────────────────────────────────
# Seuils par défaut (modifiables par tenant)
# ─────────────────────────────────────────────────────────────────────────────
class SeuilsAuditDefaut(NamedTuple):
    # Détection de doublons
    doublon_tolerance_montant_pct: float = 0.0          # Exact par défaut
    doublon_fenetre_jours: int = 3
    # Délais
    ecriture_non_validee_jours: int = 30
    compte_non_lettre_jours: int = 90
    # Seuils fiscaux
    declaration_dgi_retard_jours: int = 5
    # Détection fraude
    montant_sous_seuil_tolerance: int = 1000            # À moins de 1000 FCFA d'un seuil
    montant_gros_suspect: int = 5_000_000               # 5M FCFA
    utilisateur_volume_factor: float = 3.0              # 3× la moyenne = suspect
    # Benford
    benford_seuil_conformite: float = 0.90              # 90% de conformité
    benford_min_echantillons: int = 100                 # Min 100 écritures pour tester


SEUILS_AUDIT_DEFAUT = SeuilsAuditDefaut()


# ─────────────────────────────────────────────────────────────────────────────
# Loi de Benford — distribution théorique attendue (chiffre 1-9)
# ─────────────────────────────────────────────────────────────────────────────
BENFORD_DISTRIBUTION: dict[int, float] = {
    1: 0.30103,
    2: 0.17609,
    3: 0.12494,
    4: 0.09691,
    5: 0.07918,
    6: 0.06695,
    7: 0.05799,
    8: 0.05115,
    9: 0.04576,
}


# ─────────────────────────────────────────────────────────────────────────────
# Types d'actions à tracer (audit trail)
# ─────────────────────────────────────────────────────────────────────────────
class ActionAudit:
    # Authentification
    LOGIN = "login"
    LOGIN_FAILED = "login_failed"
    LOGOUT = "logout"
    MFA_ENABLED = "mfa_enabled"
    PASSWORD_CHANGED = "password_changed"
    # Écritures
    ECRITURE_CREATE = "ecriture_create"
    ECRITURE_UPDATE = "ecriture_update"
    ECRITURE_DELETE = "ecriture_delete"
    ECRITURE_VALIDATE = "ecriture_validate"
    ECRITURE_LETTRAGE = "ecriture_lettrage"
    # Tiers
    CLIENT_CREATE = "client_create"
    CLIENT_UPDATE = "client_update"
    FOURNISSEUR_CREATE = "fournisseur_create"
    FOURNISSEUR_UPDATE = "fournisseur_update"
    # Ventes/Achats
    FACTURE_CREATE = "facture_create"
    FACTURE_UPDATE = "facture_update"
    FACTURE_VALIDATE = "facture_validate"
    ENCAISSEMENT = "encaissement"
    PAIEMENT = "paiement"
    AVOIR_CREATE = "avoir_create"
    # Paramétrage
    PLAN_COMPTABLE_MODIF = "plan_comptable_modif"
    JOURNAL_MODIF = "journal_modif"
    TAUX_MODIF = "taux_modif"
    # Freeze / audit
    FREEZE_APPLIED = "freeze_applied"
    FREEZE_RELEASED = "freeze_released"
    # Admin
    USER_CREATE = "user_create"
    USER_DELETE = "user_delete"
    USER_ROLE_CHANGED = "user_role_changed"
    CONFIG_MODIF = "config_modif"
    EXPORT_DATA = "export_data"
    IMPORT_DATA = "import_data"
    # Système
    BULK_OPERATION = "bulk_operation"
    AUTOMATION_RUN = "automation_run"


# ─────────────────────────────────────────────────────────────────────────────
# Rapport de conformité — checklist OHADA / DGI
# ─────────────────────────────────────────────────────────────────────────────
class CheckConformite(NamedTuple):
    code: str
    libelle: str
    reference_legale: str
    obligatoire: bool


CHECKLIST_CONFORMITE: list[CheckConformite] = [
    CheckConformite(
        "livre_journal",
        "Tenue d'un livre journal chronologique",
        "SYSCOHADA art. 17",
        True,
    ),
    CheckConformite(
        "grand_livre",
        "Tenue d'un grand livre",
        "SYSCOHADA art. 18",
        True,
    ),
    CheckConformite(
        "balance",
        "Édition d'une balance annuelle",
        "SYSCOHADA art. 19",
        True,
    ),
    CheckConformite(
        "etats_financiers",
        "Établissement des états financiers annuels",
        "SYSCOHADA art. 8",
        True,
    ),
    CheckConformite(
        "conservation_10_ans",
        "Conservation des pièces justificatives 10 ans",
        "CGI CI art. 921",
        True,
    ),
    CheckConformite(
        "fne_facturation",
        "Facturation normalisée électronique (FNE)",
        "CGI CI art. 384",
        True,
    ),
    CheckConformite(
        "declaration_tva",
        "Déclaration TVA mensuelle/trimestrielle",
        "CGI CI art. 365",
        True,
    ),
    CheckConformite(
        "declaration_cnps",
        "Déclaration CNPS mensuelle",
        "Code Prévoyance Sociale CI",
        True,
    ),
    CheckConformite(
        "its_trimestriel",
        "Déclaration ITS trimestrielle",
        "CGI CI art. 133",
        True,
    ),
    CheckConformite(
        "liasse_fiscale",
        "Dépôt de la liasse fiscale annuelle",
        "CGI CI art. 916",
        True,
    ),
    CheckConformite(
        "registre_tiers",
        "Registre des tiers (clients/fournisseurs)",
        "SYSCOHADA art. 20",
        True,
    ),
    CheckConformite(
        "inventaire_annuel",
        "Inventaire physique annuel des stocks",
        "SYSCOHADA art. 21",
        True,
    ),
    CheckConformite(
        "piste_audit",
        "Piste d'audit fiable et inaltérable",
        "CGI CI art. 922",
        True,
    ),
    CheckConformite(
        "protection_donnees",
        "Registre de traitement des données personnelles",
        "Loi 2013-450",
        False,
    ),
    CheckConformite(
        "mfa_obligatoire",
        "Authentification multi-facteurs utilisateurs sensibles",
        "Norme interne",
        False,
    ),
]
