"""
Référentiel OHADA — Consolidation & Comptes combinés.

Sources :
- Acte uniforme relatif au droit comptable et à l'information financière (AUDCIF)
- Système comptable OHADA révisé — chapitre 9 « Comptes consolidés et combinés »
- Règlement CRC 99-02 (inspiration française, applicable par analogie)

Méthodes de consolidation :
- Intégration globale (IG)      : contrôle exclusif (> 50% des droits de vote)
- Intégration proportionnelle (IP) : contrôle conjoint (co-entreprises)
- Mise en équivalence (MEE)     : influence notable (20-50%)

Le pourcentage de contrôle détermine la méthode.
Le pourcentage d'intérêt détermine la part revenant au groupe.
"""
from __future__ import annotations

from typing import NamedTuple


# ─────────────────────────────────────────────────────────────────────────────
# Méthodes de consolidation
# ─────────────────────────────────────────────────────────────────────────────
class MethodeConsolidation:
    INTEGRATION_GLOBALE = "integration_globale"
    INTEGRATION_PROPORTIONNELLE = "integration_proportionnelle"
    MISE_EN_EQUIVALENCE = "mise_en_equivalence"
    EXCLUE = "exclue"                              # hors périmètre


METHODES_ADMISES = {
    MethodeConsolidation.INTEGRATION_GLOBALE,
    MethodeConsolidation.INTEGRATION_PROPORTIONNELLE,
    MethodeConsolidation.MISE_EN_EQUIVALENCE,
    MethodeConsolidation.EXCLUE,
}


# ─────────────────────────────────────────────────────────────────────────────
# Nature du contrôle
# ─────────────────────────────────────────────────────────────────────────────
class NatureControle:
    CONTROLE_EXCLUSIF = "controle_exclusif"
    CONTROLE_CONJOINT = "controle_conjoint"
    INFLUENCE_NOTABLE = "influence_notable"
    AUCUN = "aucun"


# Seuils (règle OHADA)
SEUIL_CONTROLE_EXCLUSIF = 0.50            # > 50%
SEUIL_CONTROLE_CONJOINT = 0.50            # = 50%
SEUIL_INFLUENCE_NOTABLE = 0.20            # 20-50%


def determiner_methode(pct_controle: float) -> str:
    """
    Détermine la méthode de consolidation selon le pourcentage de contrôle.
    """
    if pct_controle > SEUIL_CONTROLE_EXCLUSIF:
        return MethodeConsolidation.INTEGRATION_GLOBALE
    if pct_controle == SEUIL_CONTROLE_CONJOINT:
        return MethodeConsolidation.INTEGRATION_PROPORTIONNELLE
    if pct_controle >= SEUIL_INFLUENCE_NOTABLE:
        return MethodeConsolidation.MISE_EN_EQUIVALENCE
    return MethodeConsolidation.EXCLUE


# ─────────────────────────────────────────────────────────────────────────────
# Types d'éliminations intragroupe
# ─────────────────────────────────────────────────────────────────────────────
class TypeElimination:
    TITRES_CAPITAUX_PROPRES = "titres_capitaux_propres"      # Titres de participation ↔ CP
    CREANCES_DETTES = "creances_dettes"                      # Comptes 4xx réciproques
    PRODUITS_CHARGES = "produits_charges"                    # Comptes 6xx/7xx réciproques
    DIVIDENDES = "dividendes"                                # Distributions intragroupe
    PLUS_VALUES_STOCKS = "plus_values_stocks"                # Marge sur stocks internes
    PLUS_VALUES_IMMOS = "plus_values_immos"                  # Cession interne d'immo
    PRETS_AVANCES = "prets_avances"                          # Prêts/avances intragroupe


TYPES_ELIMINATION = {
    TypeElimination.TITRES_CAPITAUX_PROPRES,
    TypeElimination.CREANCES_DETTES,
    TypeElimination.PRODUITS_CHARGES,
    TypeElimination.DIVIDENDES,
    TypeElimination.PLUS_VALUES_STOCKS,
    TypeElimination.PLUS_VALUES_IMMOS,
    TypeElimination.PRETS_AVANCES,
}


# ─────────────────────────────────────────────────────────────────────────────
# Retraitements d'homogénéisation
# ─────────────────────────────────────────────────────────────────────────────
class TypeRetraitement:
    HOMOGENEISATION_METHODES = "homogeneisation_methodes"
    RETRAITEMENT_LOCATION = "retraitement_location"           # Location-acquisition
    REPRISE_PROVISIONS_REGLEMENTEES = "reprise_provisions_reg"
    FRAIS_ETABLISSEMENT = "frais_etablissement"               # Retraitement selon OHADA
    ECART_CONVERSION = "ecart_conversion"
    IMPOTS_DIFFERES = "impots_differes"                       # Non obligatoire OHADA


TYPES_RETRAITEMENT = {
    TypeRetraitement.HOMOGENEISATION_METHODES,
    TypeRetraitement.RETRAITEMENT_LOCATION,
    TypeRetraitement.REPRISE_PROVISIONS_REGLEMENTEES,
    TypeRetraitement.FRAIS_ETABLISSEMENT,
    TypeRetraitement.ECART_CONVERSION,
    TypeRetraitement.IMPOTS_DIFFERES,
}


# ─────────────────────────────────────────────────────────────────────────────
# Comptes consolidés OHADA (plan spécifique consolidation)
# ─────────────────────────────────────────────────────────────────────────────
class CompteConsolide(NamedTuple):
    compte: str
    libelle: str
    categorie: str


COMPTES_CONSOLIDES: dict[str, CompteConsolide] = {
    # ─── Capitaux propres consolidés ─────────────────────────────────
    "capital_consolide":                CompteConsolide("101000", "Capital social consolidé",                    "cp"),
    "primes_consolidees":               CompteConsolide("105000", "Primes liées au capital",                     "cp"),
    "ecarts_reevaluation_groupes":      CompteConsolide("106100", "Écarts de réévaluation du groupe",             "cp"),
    "reserves_consolidees":             CompteConsolide("111000", "Réserves consolidées",                        "cp"),
    "report_nouveau_consolide":         CompteConsolide("118000", "Report à nouveau consolidé",                 "cp"),
    "resultat_groupe":                  CompteConsolide("121000", "Résultat net — part du groupe",              "cp"),
    "interets_minoritaires":            CompteConsolide("128000", "Intérêts minoritaires",                       "cp"),
    "ecart_acquisition":                CompteConsolide("131000", "Écart d'acquisition (goodwill)",              "cp"),
    "ecart_evaluation":                 CompteConsolide("132000", "Écart d'évaluation",                          "cp"),
    "ecart_conversion":                 CompteConsolide("133000", "Écart de conversion",                         "cp"),
}


# ─────────────────────────────────────────────────────────────────────────────
# Statuts de consolidation
# ─────────────────────────────────────────────────────────────────────────────
class StatutConsolidation:
    BROUILLON = "brouillon"
    EN_COURS = "en_cours"
    CALCULE = "calcule"
    VALIDE = "valide"
    PUBLIE = "publie"
    ANNULE = "annule"


class StatutPerimetre:
    ACTIF = "actif"
    CEDE = "cede"
    ACQUIS = "acquis"
    ENTRANT = "entrant"
    SORTANT = "sortant"


# ─────────────────────────────────────────────────────────────────────────────
# Devises UEMOA
# ─────────────────────────────────────────────────────────────────────────────
class DeviseUEMOA:
    XOF = "XOF"          # Franc CFA BCEAO
    XAF = "XAF"          # Franc CFA BEAC (zones voisines)
    EUR = "EUR"          # Euro
    USD = "USD"
    GHS = "GHS"          # Cedi ghanéen (zone CEDEAO hors UEMOA)


DEVISES_ADMISES = {DeviseUEMOA.XOF, DeviseUEMOA.XAF, DeviseUEMOA.EUR, DeviseUEMOA.USD, DeviseUEMOA.GHS}


# Parité fixe XOF ↔ EUR (irrévocable)
XOF_EUR_PARITE = 655.957


# ─────────────────────────────────────────────────────────────────────────────
# Seuils de signification (pour exclusion du périmètre)
# ─────────────────────────────────────────────────────────────────────────────
SEUIL_SIGNIFICATION_PCT = 0.05            # < 5% du total → peut être exclu si justifié
SEUIL_ACTIF_TOTAL = 0.05
SEUIL_CA_TOTAL = 0.05
SEUIL_EFFECTIF = 0.05
