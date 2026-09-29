"""
Référentiel Formation & Support — MTech SaaS SYSCOHADA.

Sources internes :
- Base de connaissances interne (à enrichir)
- Documentation SYSCOHADA révisé
- Procédures internes DGI / CNPS / FNE
- Guides d'utilisation du SaaS
"""
from __future__ import annotations

from typing import NamedTuple


# ─────────────────────────────────────────────────────────────────────────────
# Catégories d'articles
# ─────────────────────────────────────────────────────────────────────────────
class CategorieArticle:
    DEMARRAGE = "demarrage"                          # Premiers pas
    COMPTABILITE = "comptabilite"                    # Écritures SYSCOHADA
    FISCALITE = "fiscalite"                          # TVA, IS, ITS, DGI
    SOCIAL = "social"                                # CNPS, paie
    STOCKS = "stocks"                                # Gestion des stocks
    IMMOBILISATIONS = "immobilisations"              # Amortissements
    VENTES = "ventes"                                # Clients, factures
    ACHATS = "achats"                                # Fournisseurs
    TRESORERIE = "tresorerie"                        # Banque, rapprochement
    ANALYTIQUE = "analytique"                        # Budget, centres de coût
    CONSOLIDATION = "consolidation"                  # Groupes
    FNE = "fne"                                      # Facturation DGI
    AUDIT = "audit"                                  # Contrôle interne
    PROJETS = "projets"                              # Chantiers
    IA = "ia"                                        # NLP, prévisions
    MOBILE_MONEY = "mobile_money"                    # Wave, OM, MTN
    SECURITE = "securite"                            # Comptes, MFA
    ABONNEMENT = "abonnement"                        # Facturation SaaS
    INTEGRATIONS = "integrations"                    # WhatsApp, API
    AVANCE = "avance"                                # Fonctions avancées


CATEGORIES_ARTICLE = {
    CategorieArticle.DEMARRAGE,
    CategorieArticle.COMPTABILITE,
    CategorieArticle.FISCALITE,
    CategorieArticle.SOCIAL,
    CategorieArticle.STOCKS,
    CategorieArticle.IMMOBILISATIONS,
    CategorieArticle.VENTES,
    CategorieArticle.ACHATS,
    CategorieArticle.TRESORERIE,
    CategorieArticle.ANALYTIQUE,
    CategorieArticle.CONSOLIDATION,
    CategorieArticle.FNE,
    CategorieArticle.AUDIT,
    CategorieArticle.PROJETS,
    CategorieArticle.IA,
    CategorieArticle.MOBILE_MONEY,
    CategorieArticle.SECURITE,
    CategorieArticle.ABONNEMENT,
    CategorieArticle.INTEGRATIONS,
    CategorieArticle.AVANCE,
}


# ─────────────────────────────────────────────────────────────────────────────
# Types de contenu
# ─────────────────────────────────────────────────────────────────────────────
class TypeContenu:
    ARTICLE = "article"                              # Article de doc classique
    TUTORIEL = "tutoriel"                            # Tutoriel pas-à-pas
    VIDEO = "video"                                  # Vidéo YouTube/Vimeo
    FAQ = "faq"                                      # Question/réponse
    CHECKLIST = "checklist"                          # Checklist d'actions
    WEBINAR = "webinar"                              # Webinar enregistré
    CHANGELOG = "changelog"                          # Nouveauté produit
    CAS_USAGE = "cas_usage"                          # Cas d'usage client


TYPES_CONTENU = {
    TypeContenu.ARTICLE,
    TypeContenu.TUTORIEL,
    TypeContenu.VIDEO,
    TypeContenu.FAQ,
    TypeContenu.CHECKLIST,
    TypeContenu.WEBINAR,
    TypeContenu.CHANGELOG,
    TypeContenu.CAS_USAGE,
}


# ─────────────────────────────────────────────────────────────────────────────
# Niveaux de difficulté
# ─────────────────────────────────────────────────────────────────────────────
class NiveauDifficulte:
    DEBUTANT = "debutant"
    INTERMEDIAIRE = "intermediaire"
    AVANCE = "avance"
    EXPERT = "expert"


NIVEAUX_DIFFICULTE = {
    NiveauDifficulte.DEBUTANT,
    NiveauDifficulte.INTERMEDIAIRE,
    NiveauDifficulte.AVANCE,
    NiveauDifficulte.EXPERT,
}


# ─────────────────────────────────────────────────────────────────────────────
# Rôles cibles (pour filtrer la doc)
# ─────────────────────────────────────────────────────────────────────────────
class RoleCible:
    TOUS = "tous"
    ADMIN_TENANT = "admin_tenant"
    COMPTABLE = "comptable"
    LECTEUR = "lecteur"
    AUDITEUR = "auditeur"
    FONDATEUR = "fondateur"
    COMPTABLE_EXTERNE = "comptable_externe"          # Expert-comptable


# ─────────────────────────────────────────────────────────────────────────────
# Statuts de publication
# ─────────────────────────────────────────────────────────────────────────────
class StatutPublication:
    BROUILLON = "brouillon"
    EN_REVISION = "en_revision"
    PUBLIE = "publie"
    DEPRECIE = "deprecie"                            # Contenu obsolète mais conservé
    ARCHIVE = "archive"


# ─────────────────────────────────────────────────────────────────────────────
# Types de ticket support
# ─────────────────────────────────────────────────────────────────────────────
class TypeTicket:
    QUESTION = "question"                            # Question simple
    BUG = "bug"                                      # Anomalie technique
    DEMANDE_FONCTIONNALITE = "demande_fonctionnalite" # Feature request
    INCIDENT = "incident"                            # Incident critique
    RECLAMATION = "reclamation"                      # Client mécontent
    AMELIORATION = "amelioration"                    # Suggestion UX


# ─────────────────────────────────────────────────────────────────────────────
# Priorité ticket
# ─────────────────────────────────────────────────────────────────────────────
class PrioriteTicket:
    BASSE = "basse"
    NORMALE = "normale"
    HAUTE = "haute"
    URGENTE = "urgente"
    CRITIQUE = "critique"                            # Bloque la production


# ─────────────────────────────────────────────────────────────────────────────
# Statuts ticket
# ─────────────────────────────────────────────────────────────────────────────
class StatutTicket:
    NOUVEAU = "nouveau"
    EN_COURS = "en_cours"
    EN_ATTENTE_CLIENT = "en_attente_client"
    RESOLU = "resolu"
    FERME = "ferme"
    ANNULE = "annule"
    ESCALADE = "escalade"


# ─────────────────────────────────────────────────────────────────────────────
# Canaux de support
# ─────────────────────────────────────────────────────────────────────────────
class CanalSupport:
    INTERNE = "interne"                              # Depuis l'app
    EMAIL = "email"
    WHATSAPP = "whatsapp"
    TELEPHONE = "telephone"
    CHATBOT = "chatbot"                              # Résolu par le bot
    API = "api"


# ─────────────────────────────────────────────────────────────────────────────
# Types d'onboarding (parcours)
# ─────────────────────────────────────────────────────────────────────────────
class ParcoursOnboarding:
    NOUVEAU_TENANT = "nouveau_tenant"                # Onboarding d'une entreprise
    NOUVEL_UTILISATEUR = "nouvel_utilisateur"        # Onboarding d'un user
    NOUVEAU_COMPTABLE = "nouveau_comptable"          # Onboarding comptable
    MIGRATION_DEPUIS_EXCEL = "migration_excel"       # Migration depuis Excel
    ACTIVATION_FNE = "activation_fne"                # Activation e-invoicing
    CONFIGURATION_MOBILE_MONEY = "config_mm"         # Config Wave/OM/MTN


# ─────────────────────────────────────────────────────────────────────────────
# Scores / seuils
# ─────────────────────────────────────────────────────────────────────────────
SEUIL_ARTICLE_UTILE_PCT = 0.75                       # > 75% d'utilité = bon
SEUIL_ARTICLE_POPULAIRE_VUES = 100                   # > 100 vues = populaire
SEUIL_CHATBOT_CONFIANCE = 0.70                       # Confiance minimale du bot
SEUIL_CHATBOT_AUTO_RESOLUTION = 0.85                 # Auto-résolution si > 85%


# ─────────────────────────────────────────────────────────────────────────────
# Catégories d'articles prioritaires (contenu initial à fournir)
# ─────────────────────────────────────────────────────────────────────────────
CATEGORIES_PRIORITAIRES: list[tuple[str, list[str]]] = [
    ("demarrage", [
        "Créer mon compte entreprise",
        "Importer mon plan comptable SYSCOHADA",
        "Créer mon premier exercice comptable",
        "Saisir ma première écriture (mode manuel)",
        "Saisir une écriture avec l'IA",
        "Inviter mes collaborateurs",
    ]),
    ("comptabilite", [
        "Comprendre la partie double SYSCOHADA",
        "Créer une écriture de vente",
        "Créer une écriture d'achat",
        "Gérer les lettrages clients/fournisseurs",
        "Clôturer un exercice comptable",
        "Générer le bilan et le compte de résultat",
    ]),
    ("fiscalite", [
        "Déclarer la TVA trimestrielle",
        "Calculer et déclarer l'ITS",
        "Déposer la liasse fiscale DGI",
        "Comprendre les barèmes ITS 2024",
    ]),
    ("fne", [
        "Activer l'interfaçage FNE",
        "Certifier une facture de vente",
        "Certifier une facture d'avoir",
        "Gérer mon solde de stickers",
    ]),
    ("mobile_money", [
        "Connecter Wave à mon compte",
        "Connecter Orange Money",
        "Rapprocher mes transactions Mobile Money",
    ]),
    ("ia", [
        "Utiliser la saisie magique",
        "Configurer WhatsApp pour saisir mes factures",
        "Prévoir ma trésorerie à 13 semaines",
    ]),
    ("stocks", [
        "Créer mon catalogue produits",
        "Enregistrer une entrée de stock (CUMP)",
        "Enregistrer une sortie de stock (FIFO)",
        "Réaliser un inventaire physique",
    ]),
    ("social", [
        "Créer mes salariés",
        "Générer les bulletins de paie",
        "Déclarer la CNPS mensuelle",
    ]),
]
