"""
Référentiel Conformité RGPD / Protection des Données.

Cadre juridique applicable :
- Loi ivoirienne 2013-450 du 19/06/2013 relative à la protection des données à caractère personnel
- Convention de Malabo (Union Africaine, 2014) sur la cybersécurité et la protection des données
- RGPD (UE 2016/679) — pour les clients européens de MTech
- ARTCI — Autorité de Régulation des Télécommunications/TIC de Côte d'Ivoire
- Directives CEDEAO sur la protection des données

Principes clés :
- Licéité, loyauté, transparence
- Limitation des finalités
- Minimisation des données
- Exactitude
- Limitation de conservation
- Intégrité et confidentialité
- Responsabilité (accountability)
"""
from __future__ import annotations

from typing import NamedTuple


# ─────────────────────────────────────────────────────────────────────────────
# Bases légales du traitement (Art. 6 RGPD / Art. 25 Loi 2013-450)
# ─────────────────────────────────────────────────────────────────────────────
class BaseLegale:
    CONSENTEMENT = "consentement"
    CONTRAT = "contrat"
    OBLIGATION_LEGALE = "obligation_legale"
    INTERET_VITAL = "interet_vital"
    MISSION_PUBLIQUE = "mission_publique"
    INTERET_LEGITIME = "interet_legitime"


BASES_LEGALES = {
    BaseLegale.CONSENTEMENT, BaseLegale.CONTRAT, BaseLegale.OBLIGATION_LEGALE,
    BaseLegale.INTERET_VITAL, BaseLegale.MISSION_PUBLIQUE, BaseLegale.INTERET_LEGITIME,
}


# ─────────────────────────────────────────────────────────────────────────────
# Catégories de données personnelles
# ─────────────────────────────────────────────────────────────────────────────
class CategorieDonnee:
    IDENTITE = "identite"                 # Nom, prénom, date naissance
    CONTACT = "contact"                   # Email, téléphone, adresse
    FISCAL = "fiscal"                     # NCC, RCCM
    FINANCIER = "financier"               # IBAN, transactions
    PROFESSIONNEL = "professionnel"       # Poste, employeur
    SENSIBLE_SANTE = "sensible_sante"     # Certificats médicaux
    SENSIBLE_BIOMETRIQUE = "sensible_biometrique"
    SENSIBLE_OPINION = "sensible_opinion" # Politique, religieuse
    CONNEXION = "connexion"               # IP, user agent, logs
    LOCALISATION = "localisation"


CATEGORIES_SENSIBLES = {
    CategorieDonnee.SENSIBLE_SANTE,
    CategorieDonnee.SENSIBLE_BIOMETRIQUE,
    CategorieDonnee.SENSIBLE_OPINION,
}


# ─────────────────────────────────────────────────────────────────────────────
# Finalités du traitement (registre)
# ─────────────────────────────────────────────────────────────────────────────
class FinaliteTraitement:
    GESTION_CLIENTS = "gestion_clients"
    GESTION_FOURNISSEURS = "gestion_fournisseurs"
    GESTION_PAIE = "gestion_paie"
    GESTION_COMPTABLE = "gestion_comptable"
    GESTION_FISCALE = "gestion_fiscale"
    GESTION_SOCIALE = "gestion_sociale"
    GESTION_TRESORERIE = "gestion_tresorerie"
    GESTION_STOCKS = "gestion_stocks"
    GESTION_PROJETS = "gestion_projets"
    MARKETING = "marketing"
    NEWSLETTER = "newsletter"
    SUPPORT_CLIENT = "support_client"
    SECURITE = "securite"
    ANALYSE_STATISTIQUE = "analyse_statistique"
    RECHERCHE_DEV = "recherche_dev"
    CONFORMITE_LEGALE = "conformite_legale"
    LUTTE_FRAUDE = "lutte_fraude"
    RECRUTEMENT = "recrutement"


# ─────────────────────────────────────────────────────────────────────────────
# Statuts de consentement
# ─────────────────────────────────────────────────────────────────────────────
class StatutConsentement:
    ACCORDE = "accorde"
    REFUSE = "refuse"
    RETIRE = "retire"
    EXPIRE = "expire"


# ─────────────────────────────────────────────────────────────────────────────
# Types de droits (demandes des personnes)
# ─────────────────────────────────────────────────────────────────────────────
class TypeDroit:
    ACCES = "acces"                            # Art. 15 RGPD
    RECTIFICATION = "rectification"            # Art. 16
    EFFACEMENT = "effacement"                  # Art. 17 (droit à l'oubli)
    LIMITATION = "limitation"                  # Art. 18
    PORTABILITE = "portabilite"                # Art. 20
    OPPOSITION = "opposition"                  # Art. 21
    RETRAIT_CONSENTEMENT = "retrait_consentement"
    RECLAMATION = "reclamation"                # Réclamation ARTCI
    DECISION_AUTOMATISEE = "decision_automatisee"  # Art. 22


# ─────────────────────────────────────────────────────────────────────────────
# Statuts d'une demande de droit
# ─────────────────────────────────────────────────────────────────────────────
class StatutDemandeDroit:
    RECUE = "recue"
    EN_COURS = "en_cours"
    EN_ATTENTE_VERIFICATION = "en_attente_verification"
    ACCEPTEE = "acceptee"
    REFUSEE = "refusee"
    PARTIELLEMENT_SATISFAITE = "partiellement_satisfaite"
    CLOTUREE = "cloturee"
    ANNULEE = "annulee"


# Délai légal de réponse (RGPD : 30 jours)
DELAI_REPONSE_DROIT_JOURS = 30
DELAI_REPONSE_DROIT_PROLONGATION_JOURS = 60  # Si complexe


# ─────────────────────────────────────────────────────────────────────────────
# Types d'incidents / violations de données
# ─────────────────────────────────────────────────────────────────────────────
class TypeIncident:
    ACCES_NON_AUTORISE = "acces_non_autorise"
    DIVULGATION = "divulgation"
    PERTE = "perte"
    ALTERATION = "alteration"
    DESTRUCTION = "destruction"
    VOL = "vol"
    RANSOMWARE = "ransomware"
    PHISHING = "phishing"
    ERREUR_HUMAINE = "erreur_humaine"


# ─────────────────────────────────────────────────────────────────────────────
# Niveaux de gravité
# ─────────────────────────────────────────────────────────────────────────────
class GraviteIncident:
    FAIBLE = "faible"
    MOYEN = "moyen"
    ELEVE = "eleve"
    CRITIQUE = "critique"


# Délais de notification
DELAI_NOTIFICATION_AUTORITE_HEURES = 72   # ARTCI / CNIL : 72h
DELAI_NOTIFICATION_PERSONNES_HEURES = 72  # Si risque élevé


# ─────────────────────────────────────────────────────────────────────────────
# Statuts d'incident
# ─────────────────────────────────────────────────────────────────────────────
class StatutIncident:
    DETECTE = "detecte"
    EN_INVESTIGATION = "en_investigation"
    CONFIRME = "confirme"
    NOTIFIE_AUTORITE = "notifie_autorite"
    NOTIFIE_PERSONNES = "notifie_personnes"
    CLOTURE = "cloture"
    FAUX_POSITIF = "faux_positif"


# ─────────────────────────────────────────────────────────────────────────────
# Autorités de contrôle
# ─────────────────────────────────────────────────────────────────────────────
class AutoriteControle:
    ARTCI = "artci"                # Côte d'Ivoire
    CNIL = "cnil"                  # France
    AUTRE = "autre"


AUTORITES_CI = {
    "artci": {
        "nom": "ARTCI — Autorité de Régulation des Télécommunications/TIC de Côte d'Ivoire",
        "adresse": "Abidjan, Côte d'Ivoire",
        "email": "contact@artci.ci",
        "site": "https://www.artci.ci",
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Mesures de sécurité (art. 32 RGPD)
# ─────────────────────────────────────────────────────────────────────────────
class MesureSecurite:
    CHIFFREMENT_REPOS = "chiffrement_repos"
    CHIFFREMENT_TRANSIT = "chiffrement_transit"
    RLS_MULTI_TENANT = "rls_multi_tenant"
    MFA_OBLIGATOIRE = "mfa_obligatoire"
    HASH_MOT_DE_PASSE = "hash_mot_de_passe"
    AUDIT_TRAIL = "audit_trail"
    SAUVEGARDES_CHIFFREES = "sauvegardes_chiffrees"
    PSEUDONYMISATION = "pseudonymisation"
    MINIMISATION = "minimisation"
    CONTROLE_ACCES = "controle_acces"
    JOURNALISATION = "journalisation"
    TESTS_INTRUSION = "tests_intrusion"
    FORMATION_PERSONNEL = "formation_personnel"
    PLAN_CONTINUITE = "plan_continuite"


# ─────────────────────────────────────────────────────────────────────────────
# Types de traitement automatisé (pour AIPD)
# ─────────────────────────────────────────────────────────────────────────────
class NiveauRisque:
    FAIBLE = "faible"
    MOYEN = "moyen"
    ELEVE = "eleve"
    TRES_ELEVE = "tres_eleve"


# AIPD (Analyse d'Impact relative à la Protection des Données) requise si :
AIPD_REQUISE_SI = [
    "profilage",
    "decision_automatisee",
    "donnees_sensibles",
    "surveillance_systematique",
    "grande_echelle",
    "personnes_vulnerables",
]


# ─────────────────────────────────────────────────────────────────────────────
# Délais de conservation par catégorie (Loi 2013-450 + CGi CI)
# ─────────────────────────────────────────────────────────────────────────────
class ConservationDonnees:
    COMPTE_UTILISATEUR = 3                    # ans après dernière connexion
    FACTURATION = 10                          # ans (obligation fiscale)
    PAIE = 30                                 # ans (obligation CNPS)
    LOGS_CONNEXION = 1                        # an
    LOGS_AUDIT = 10                           # ans (obligation OHADA)
    MARKETING = 3                             # ans après dernière interaction
    COOKIES = 13                              # mois (recommandation CNIL)
    RECRUTEMENT_NON_RETENU = 2                # ans
    CANDIDAT_RECRUTE = 5                      # ans après embauche
    RECLAMATION = 5                           # ans après clôture
    DONNEES_SENSIBLES = 5                     # ans (minimisation)


# ─────────────────────────────────────────────────────────────────────────────
# Droits des personnes (rappel pédagogique)
# ─────────────────────────────────────────────────────────────────────────────
DROITS_PERSONNES: dict[str, dict[str, str]] = {
    TypeDroit.ACCES: {
        "titre": "Droit d'accès",
        "description": "Obtenir une copie des données personnelles traitées",
        "delai": "30 jours",
        "reference": "Art. 15 RGPD / Art. 40 Loi 2013-450",
    },
    TypeDroit.RECTIFICATION: {
        "titre": "Droit de rectification",
        "description": "Corriger des données inexactes ou incomplètes",
        "delai": "30 jours",
        "reference": "Art. 16 RGPD / Art. 41 Loi 2013-450",
    },
    TypeDroit.EFFACEMENT: {
        "titre": "Droit à l'effacement (droit à l'oubli)",
        "description": "Demander la suppression de ses données",
        "delai": "30 jours",
        "reference": "Art. 17 RGPD / Art. 42 Loi 2013-450",
    },
    TypeDroit.LIMITATION: {
        "titre": "Droit à la limitation du traitement",
        "description": "Geler temporairement le traitement des données",
        "delai": "30 jours",
        "reference": "Art. 18 RGPD",
    },
    TypeDroit.PORTABILITE: {
        "titre": "Droit à la portabilité",
        "description": "Recevoir ses données dans un format structuré (JSON/CSV)",
        "delai": "30 jours",
        "reference": "Art. 20 RGPD",
    },
    TypeDroit.OPPOSITION: {
        "titre": "Droit d'opposition",
        "description": "S'opposer au traitement pour motif légitime",
        "delai": "30 jours",
        "reference": "Art. 21 RGPD",
    },
    TypeDroit.RETRAIT_CONSENTEMENT: {
        "titre": "Retrait du consentement",
        "description": "Retirer son consentement à tout moment",
        "delai": "Immédiat",
        "reference": "Art. 7.3 RGPD",
    },
    TypeDroit.RECLAMATION: {
        "titre": "Droit de réclamation",
        "description": "Saisir l'autorité de contrôle (ARTCI)",
        "delai": "N/A",
        "reference": "Art. 77 RGPD",
    },
    TypeDroit.DECISION_AUTOMATISEE: {
        "titre": "Droit relatif aux décisions automatisées",
        "description": "Ne pas faire l'objet d'une décision entièrement automatisée",
        "delai": "30 jours",
        "reference": "Art. 22 RGPD",
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Templates de documents légaux
# ─────────────────────────────────────────────────────────────────────────────
TYPES_DOCUMENT_LEGAL = {
    "politique_confidentialite": "Politique de confidentialité",
    "mentions_legales": "Mentions légales",
    "cgu": "Conditions Générales d'Utilisation",
    "cgv": "Conditions Générales de Vente",
    "politique_cookies": "Politique de cookies",
    "charte_donnees": "Charte de protection des données",
    "dpa": "Accord de traitement des données (DPA)",
    "registre_traitements": "Registre des traitements",
    "charte_informatique": "Charte informatique",
    "procedure_violation": "Procédure de gestion des violations",
}
