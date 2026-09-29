"""
Référentiel SYSCOHADA révisé — comptes de stocks et méthodes de valorisation.

Sources :
- SYSCOHADA révisé (Acte uniforme OHADA, 2017)
- Guide d'application SYSCOHADA révisé (chapitre 3 : stocks)

Méthodes admises :
- CUMP (Coût Unitaire Moyen Pondéré) — méthode de référence
- FIFO (First In, First Out) — méthode admise
- PEPS (Premier Entré, Premier Sorti) — synonyme de FIFO en français
- LIFO interdit par le SYSCOHADA révisé
"""
from __future__ import annotations

from typing import NamedTuple


# ─────────────────────────────────────────────────────────────────────────────
# Comptes de stocks (classe 3)
# ─────────────────────────────────────────────────────────────────────────────
class CompteStock(NamedTuple):
    compte: str
    libelle: str
    compte_variation: str
    libelle_variation: str


COMPTES_STOCK: dict[str, CompteStock] = {
    "marchandises":      CompteStock("311000", "Marchandises",                    "603100", "Variation des stocks de marchandises"),
    "matieres_premieres": CompteStock("321000", "Matières premières",             "603200", "Variation des stocks de matières premières"),
    "autres_appro":      CompteStock("331000", "Autres approvisionnements",       "603300", "Variation des stocks d'autres approvisionnements"),
    "produits_en_cours": CompteStock("341000", "Produits en cours",               "603400", "Variation des stocks de produits en cours"),
    "produits_finis":    CompteStock("351000", "Produits finis",                  "603500", "Variation des stocks de produits finis"),
    "produits_residuels": CompteStock("361000", "Produits résiduels",             "603600", "Variation des stocks de produits résiduels"),
    "stocks_en_route":   CompteStock("371000", "Stocks en cours de route",        "603700", "Variation des stocks en cours de route"),
    "stocks_en_depot":   CompteStock("381000", "Stocks en dépôt",                 "603800", "Variation des stocks en dépôt"),
}

# Compte de dépréciation (39x) par famille de stock
COMPTES_DEPRECIATION: dict[str, str] = {
    "marchandises":       "391000",
    "matieres_premieres": "392000",
    "autres_appro":       "393000",
    "produits_en_cours":  "394000",
    "produits_finis":     "395000",
    "produits_residuels": "396000",
}

# Taux de TVA (récupérable sur achats de stocks)
TVA_TAUX_NORMAL = 0.18


# ─────────────────────────────────────────────────────────────────────────────
# Méthodes de valorisation
# ─────────────────────────────────────────────────────────────────────────────
class MethodeValorisation:
    CUMP = "cump"           # Coût Unitaire Moyen Pondéré (par défaut SYSCOHADA)
    FIFO = "fifo"           # Premier Entré, Premier Sorti
    PEPS = "peps"           # Alias de FIFO (usage français)


METHODES_ADMISES = {MethodeValorisation.CUMP, MethodeValorisation.FIFO, MethodeValorisation.PEPS}


# ─────────────────────────────────────────────────────────────────────────────
# Types de mouvements
# ─────────────────────────────────────────────────────────────────────────────
class TypeMouvement:
    ENTREE_ACHAT = "entree_achat"           # Achat fournisseur
    ENTREE_RETOUR_CLIENT = "entree_retour"  # Retour marchandise
    ENTREE_PRODUCTION = "entree_production" # Production interne
    ENTREE_AJUSTEMENT = "entree_ajustement" # Correction d'inventaire (positif)
    SORTIE_VENTE = "sortie_vente"           # Vente client
    SORTIE_CONSOMMATION = "sortie_conso"    # Consommation interne
    SORTIE_PERTE = "sortie_perte"           # Perte / casse
    SORTIE_AJUSTEMENT = "sortie_ajustement" # Correction d'inventaire (négatif)
    TRANSFERT_ENTREE = "transfert_entree"
    TRANSFERT_SORTIE = "transfert_sortie"


SENS_MOUVEMENT: dict[str, str] = {
    TypeMouvement.ENTREE_ACHAT: "entree",
    TypeMouvement.ENTREE_RETOUR_CLIENT: "entree",
    TypeMouvement.ENTREE_PRODUCTION: "entree",
    TypeMouvement.ENTREE_AJUSTEMENT: "entree",
    TypeMouvement.SORTIE_VENTE: "sortie",
    TypeMouvement.SORTIE_CONSOMMATION: "sortie",
    TypeMouvement.SORTIE_PERTE: "sortie",
    TypeMouvement.SORTIE_AJUSTEMENT: "sortie",
    TypeMouvement.TRANSFERT_ENTREE: "entree",
    TypeMouvement.TRANSFERT_SORTIE: "sortie",
}


# ─────────────────────────────────────────────────────────────────────────────
# Journaux SYSCOHADA pour écritures de stock
# ─────────────────────────────────────────────────────────────────────────────
JOURNAL_STOCK = "ST"   # Journal des stocks (à créer si absent)
JOURNAL_ACHAT = "AC"
JOURNAL_VENTE = "VE"
JOURNAL_OD = "OD"
