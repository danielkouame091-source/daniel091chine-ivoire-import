"""
Référentiel SYSCOHADA révisé — comptabilité analytique & budget.

Sources :
- SYSCOHADA révisé (Acte uniforme OHADA, 2017) — chapitre 9
- Guide d'application SYSCOHADA : comptabilité des coûts

Structure de la classe 9 :
- 90x : Comptes réfléchis (pour la centralisation)
- 92x : Comptes analytiques (par nature)
- 93x : Coûts par centre d'analyse
- 94x : Coûts par produit
- 95x : Coûts par fonction
- 96x : Écarts
- 97x : Différences de traitement comptable
- 98x : Résultats analytiques
- 99x : Liaison comptabilité générale / analytique

Le module utilise une approche par "axes analytiques" plutôt que par les
comptes 9xx stricto sensu — plus flexible et conforme aux pratiques SaaS.
"""
from __future__ import annotations

from typing import NamedTuple


# ─────────────────────────────────────────────────────────────────────────────
# Types d'axes analytiques
# ─────────────────────────────────────────────────────────────────────────────
class TypeAxeAnalytique:
    CENTRE_COUT = "centre_cout"          # Section qui consomme (production, admin)
    CENTRE_PROFIT = "centre_profit"      # Section qui génère (commercial, boutique)
    PRODUIT = "produit"                  # Par ligne de produit/service
    PROJET = "projet"                    # Par projet/chantier/mission
    REGION = "region"                    # Par zone géographique
    CLIENT = "client"                    # Par client (marge client)
    CANAL = "canal"                      # Par canal de vente (boutique, en ligne, WhatsApp)
    ACTIVITE = "activite"                # Par activité (SYSCOHADA : exploitation, financier)


TYPES_AXES_ADMIS = {
    TypeAxeAnalytique.CENTRE_COUT,
    TypeAxeAnalytique.CENTRE_PROFIT,
    TypeAxeAnalytique.PRODUIT,
    TypeAxeAnalytique.PROJET,
    TypeAxeAnalytique.REGION,
    TypeAxeAnalytique.CLIENT,
    TypeAxeAnalytique.CANAL,
    TypeAxeAnalytique.ACTIVITE,
}


# ─────────────────────────────────────────────────────────────────────────────
# Méthodes de répartition
# ─────────────────────────────────────────────────────────────────────────────
class MethodeRepartition:
    FIXE = "fixe"                        # Pourcentage fixe par axe
    AU_PRORATA_CA = "prorata_ca"         # Selon le CA de chaque axe
    AU_PRORATA_CHARGES = "prorata_charges"  # Selon les charges directes
    AU_PRORATA_EFFECTIF = "prorata_effectif"  # Selon le nombre d'employés
    AU_PRORATA_SURFACE = "prorata_surface"    # Selon la surface (m²)
    MANUELLE = "manuelle"                # Saisie manuelle par le comptable


METHODES_REPARTITION_ADMISES = {
    MethodeRepartition.FIXE,
    MethodeRepartition.AU_PRORATA_CA,
    MethodeRepartition.AU_PRORATA_CHARGES,
    MethodeRepartition.AU_PRORATA_EFFECTIF,
    MethodeRepartition.AU_PRORATA_SURFACE,
    MethodeRepartition.MANUELLE,
}


# ─────────────────────────────────────────────────────────────────────────────
# Statuts de budget
# ─────────────────────────────────────────────────────────────────────────────
class StatutBudget:
    BROUILLON = "brouillon"
    SOUMIS = "soumis"
    VALIDE = "valide"
    ACTIF = "actif"
    CLOTURE = "cloture"
    REVISE = "revise"


# ─────────────────────────────────────────────────────────────────────────────
# Seuils d'alerte budgétaire
# ─────────────────────────────────────────────────────────────────────────────
class NiveauAlerteBudget:
    OK = "ok"                            # < 80% du budget
    VIGILANCE = "vigilance"              # 80-95% du budget
    ALERTE = "alerte"                    # 95-100% du budget
    DEPASSEMENT = "depassement"          # > 100% du budget


# Seuils par défaut (configurables par tenant)
SEUILS_ALERTE_DEFAUT: dict[str, float] = {
    "vigilance": 0.80,
    "alerte": 0.95,
    "depassement": 1.00,
}


def niveau_alerte_pour(consommation_pct: float, seuils: dict[str, float] | None = None) -> str:
    """Retourne le niveau d'alerte budgétaire."""
    seuils = seuils or SEUILS_ALERTE_DEFAUT
    if consommation_pct >= seuils["depassement"]:
        return NiveauAlerteBudget.DEPASSEMENT
    if consommation_pct >= seuils["alerte"]:
        return NiveauAlerteBudget.ALERTE
    if consommation_pct >= seuils["vigilance"]:
        return NiveauAlerteBudget.VIGILANCE
    return NiveauAlerteBudget.OK


# ─────────────────────────────────────────────────────────────────────────────
# Comptes SYSCOHADA 9xx (si utilisation stricte)
# ─────────────────────────────────────────────────────────────────────────────
class CompteAnalytique(NamedTuple):
    compte: str
    libelle: str
    type_axe: str


COMPTES_ANALYTIQUES: dict[str, CompteAnalytique] = {
    # Comptes réfléchis
    "charges_reflechies":    CompteAnalytique("900000", "Charges réfléchies",          TypeAxeAnalytique.CENTRE_COUT),
    "produits_reflechis":    CompteAnalytique("901000", "Produits réfléchis",          TypeAxeAnalytique.CENTRE_PROFIT),
    # Charges par nature
    "charges_par_nature":    CompteAnalytique("920000", "Charges par nature",          TypeAxeAnalytique.ACTIVITE),
    # Coûts par centre
    "couts_centre":          CompteAnalytique("930000", "Coûts par centre d'analyse",  TypeAxeAnalytique.CENTRE_COUT),
    # Coûts par produit
    "couts_produit":         CompteAnalytique("940000", "Coûts par produit",           TypeAxeAnalytique.PRODUIT),
    # Coûts par fonction
    "couts_fonction":        CompteAnalytique("950000", "Coûts par fonction",          TypeAxeAnalytique.ACTIVITE),
    # Écarts
    "ecarts":                CompteAnalytique("960000", "Écarts sur coûts préétablis", TypeAxeAnalytique.ACTIVITE),
    # Résultats analytiques
    "resultat_analytique":   CompteAnalytique("980000", "Résultat analytique",         TypeAxeAnalytique.CENTRE_PROFIT),
    # Liaison CG / CA
    "liaison_cg_ca":         CompteAnalytique("990000", "Liaison comptabilité générale / analytique", TypeAxeAnalytique.ACTIVITE),
}


# ─────────────────────────────────────────────────────────────────────────────
# Indicateurs de gestion par défaut (repris des SIG SYSCOHADA)
# ─────────────────────────────────────────────────────────────────────────────
class IndicateurGestion:
    CHIFFRE_AFFAIRES = "chiffre_affaires"
    MARGE_COMMERCIALE = "marge_commerciale"
    VALEUR_AJOUTEE = "valeur_ajoutee"
    EBE = "ebe"
    RESULTAT_EXPLOITATION = "resultat_exploitation"
    RESULTAT_NET = "resultat_net"
    TAUX_MARGE = "taux_marge"
    RENTABILITE = "rentabilite"


INDICATEURS_GESTION = [
    IndicateurGestion.CHIFFRE_AFFAIRES,
    IndicateurGestion.MARGE_COMMERCIALE,
    IndicateurGestion.VALEUR_AJOUTEE,
    IndicateurGestion.EBE,
    IndicateurGestion.RESULTAT_EXPLOITATION,
    IndicateurGestion.RESULTAT_NET,
    IndicateurGestion.TAUX_MARGE,
    IndicateurGestion.RENTABILITE,
]
