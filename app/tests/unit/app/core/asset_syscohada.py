"""
Référentiel SYSCOHADA révisé — immobilisations et amortissements.

Sources :
- SYSCOHADA révisé (Acte uniforme OHADA, 2017) — chapitre 2
- Annexe Fiscale DGI Côte d'Ivoire 2025 (coefficients dégressifs)

Amortissement selon SYSCOHADA :
- Linéaire (méthode par défaut)
- Dégressif (admis, applicable à certains biens)
- Variable (unités d'œuvre)
- Accéléré (durées réduites pour investissements neufs — contexte CI)

Le dégressif s'applique sur la VNC (Valeur Nette Comptable) et bascule en
linéaire dès que l'annuité linéaire devient supérieure à l'annuité dégressive.
"""
from __future__ import annotations

from typing import NamedTuple


# ─────────────────────────────────────────────────────────────────────────────
# Comptes d'immobilisations (classe 2)
# ─────────────────────────────────────────────────────────────────────────────
class CompteImmobilisation(NamedTuple):
    compte: str
    libelle: str
    compte_amortissement: str  # 28xx correspondant
    libelle_amortissement: str
    duree_indicative_ans: int   # durée d'utilité indicative


COMPTES_IMMOBILISATIONS: dict[str, CompteImmobilisation] = {
    # ── Immatérielles ────────────────────────────────────────────────────
    "frais_etablissement":     CompteImmobilisation("211000", "Frais d'établissement",             "281100", "Amort. frais d'établissement",     5),
    "logiciels":               CompteImmobilisation("212000", "Logiciels",                           "281200", "Amort. logiciels",                 3),
    "brevets_licences":        CompteImmobilisation("213000", "Brevets, licences, concessions",     "281300", "Amort. brevets et licences",        5),
    "fonds_commercial":        CompteImmobilisation("214000", "Fonds commercial",                   "281400", "Amort. fonds commercial",          10),
    "droit_bail":              CompteImmobilisation("215000", "Droit au bail",                       "281500", "Amort. droit au bail",             20),
    # ── Corporelles ──────────────────────────────────────────────────────
    "terrains":                CompteImmobilisation("220000", "Terrains",                            "282000", "Amort. terrains",                   0),
    "terrains_amenages":       CompteImmobilisation("221000", "Terrains aménagés",                   "282100", "Amort. terrains aménagés",          0),
    "batiments_industriels":   CompteImmobilisation("231000", "Bâtiments industriels",               "283100", "Amort. bâtiments industriels",     20),
    "batiments_commerciaux":   CompteImmobilisation("232000", "Bâtiments commerciaux",               "283200", "Amort. bâtiments commerciaux",     20),
    "batiments_administratifs": CompteImmobilisation("233000", "Bâtiments administratifs",           "283300", "Amort. bâtiments administratifs",  20),
    "amenagements_batiments":  CompteImmobilisation("234000", "Aménagements de bâtiments",           "283400", "Amort. aménagements bâtiments",    10),
    "materiel_outillage":      CompteImmobilisation("241000", "Matériel et outillage",                "284100", "Amort. matériel et outillage",      5),
    "materiel_industriel":     CompteImmobilisation("242000", "Matériel industriel",                 "284200", "Amort. matériel industriel",       10),
    "outillage_industriel":    CompteImmobilisation("243000", "Outillage industriel",                "284300", "Amort. outillage industriel",       5),
    "materiel_transport":      CompteImmobilisation("244000", "Matériel de transport",               "284400", "Amort. matériel de transport",      4),
    "materiel_bureau":         CompteImmobilisation("245000", "Matériel de bureau",                  "284500", "Amort. matériel de bureau",         5),
    "mobilier_bureau":         CompteImmobilisation("246000", "Mobilier de bureau",                  "284600", "Amort. mobilier de bureau",        10),
    "amenagements_divers":     CompteImmobilisation("247000", "Aménagements divers",                 "284700", "Amort. aménagements divers",       10),
    "materiel_informatique":   CompteImmobilisation("248000", "Matériel informatique",               "284800", "Amort. matériel informatique",      3),
    # ── Financières ──────────────────────────────────────────────────────
    "titres_participation":    CompteImmobilisation("261000", "Titres de participation",             "286100", "Amort. titres de participation",    0),
    "autres_titres":           CompteImmobilisation("271000", "Autres immobilisations financières",  "287100", "Amort. autres immob. financières",  0),
}

# ── Comptes de sortie d'actif ────────────────────────────────────────────────
COMPTE_VNC_CESSION = "816000"          # Valeurs comptables des cessions
COMPTE_PRODUIT_CESSION = "826000"      # Produits des cessions d'immo
COMPTE_TVA_COLLECTEE = "443000"        # TVA collectée sur cession (18%)


# ─────────────────────────────────────────────────────────────────────────────
# Méthodes d'amortissement
# ─────────────────────────────────────────────────────────────────────────────
class MethodeAmortissement:
    LINEAIRE = "lineaire"
    DEGRESSIF = "degressif"
    VARIABLE = "variable"
    ACCELERE = "accelere"     # durée réduite (fiscal CI)


METHODES_AMORTISSEMENT_ADMISES = {
    MethodeAmortissement.LINEAIRE,
    MethodeAmortissement.DEGRESSIF,
    MethodeAmortissement.VARIABLE,
    MethodeAmortissement.ACCELERE,
}


# Coefficients dégressifs (Code Général des Impôts CI, art. 21)
# Durée 3-4 ans : 1.5 / 5-6 ans : 2.0 / >6 ans : 2.5
COEFFICIENTS_DEGRESSIFS_CI: list[tuple[int, int, float]] = [
    (3, 4, 1.5),
    (5, 6, 2.0),
    (7, 100, 2.5),
]


def coefficient_degressif(duree_ans: int) -> float:
    """Retourne le coefficient dégressif applicable selon la durée."""
    for d_min, d_max, coef in COEFFICIENTS_DEGRESSIFS_CI:
        if d_min <= duree_ans <= d_max:
            return coef
    return 1.0


# ─────────────────────────────────────────────────────────────────────────────
# Journaux
# ─────────────────────────────────────────────────────────────────────────────
JOURNAL_IMMO = "IM"      # Journal des immobilisations (à créer si absent)
JOURNAL_CESSION = "CE"   # Journal des cessions (à créer si absent)
JOURNAL_OD = "OD"


# ─────────────────────────────────────────────────────────────────────────────
# Statuts
# ─────────────────────────────────────────────────────────────────────────────
class StatutImmobilisation:
    ACTIF = "actif"
    TOTALEMENT_AMORTI = "totalement_amorti"
    CEDE = "cede"
    REBUTE = "rebute"
    EN_REEVALUATION = "en_reevaluation"
