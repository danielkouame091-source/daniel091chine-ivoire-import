"""
Référentiel fiscal Côte d'Ivoire — barèmes et taux officiels.

Sources :
- Ordonnance n° 2023-718 du 13/09/2023 (réforme ITS)
- Code Général des Impôts (CGI) ivoirien
- CNPS — Taux de cotisation 2025
- Annexe Fiscale 2026

⚠️ TOUT CHANGEMENT RÉGLEMENTAIRE DOIT ÊTRE RÉPERCUTÉ ICI
   et une migration Alembic doit historiser les anciens barèmes.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import NamedTuple


# ─────────────────────────────────────────────────────────────────────────────
# ITS — Impôt sur les Traitements et Salaires (post-réforme 2023)
# ─────────────────────────────────────────────────────────────────────────────
class ITSBracket(NamedTuple):
    min_xof: int
    max_xof: int | None   # None = pas de plafond
    taux: float           # ex: 0.16 pour 16%
    variable_xof: int     # constante à soustraire (formule : R × taux - variable)


# Barème mensuel progressif (Ordonnance 2023-718, applicable depuis 01/01/2024)
ITS_BAREME_2024: list[ITSBracket] = [
    ITSBracket(0,            75_000,     0.00, 0),
    ITSBracket(75_000,       240_000,    0.16, 12_000),
    ITSBracket(240_000,      800_000,    0.21, 24_000),
    ITSBracket(800_000,      2_400_000,  0.24, 48_000),
    ITSBracket(2_400_000,    8_000_000,  0.28, 144_000),
    ITSBracket(8_000_000,    None,       0.32, 464_000),
]


# RICF — Réduction d'Impôt pour Charges de Famille
RICF_PAR_PARTS: dict[float, int] = {
    1.0: 0,
    1.5: 5_500,
    2.0: 11_000,
    2.5: 16_500,
    3.0: 22_000,
    3.5: 27_500,
    4.0: 33_000,
    4.5: 38_500,
    5.0: 44_000,
}

# Abattement forfaitaire sur salaire brut imposable
ITS_ABATTEMENT_TAUX = 0.20          # 20%
ITS_ABATTEMENT_MIN = 2_000          # 2 000 FCFA minimum
ITS_ABATTEMENT_MAX = 50_000         # 50 000 FCFA maximum


# ─────────────────────────────────────────────────────────────────────────────
# CNPS — Caisse Nationale de Prévoyance Sociale
# ─────────────────────────────────────────────────────────────────────────────
SMIG_MENSUEL = 75_000                      # depuis 01/01/2023
CNPS_PLAFOND_MENSUEL = 3_375_000           # 45 × SMIG
CNPS_PLAFOND_PF_AT = 70_000                # plafond spécifique PF + AT/MP

CNPS_PENSION_PATRONAL = 0.077              # 7,70%
CNPS_PENSION_SALARIAL = 0.063              # 6,30%
CNPS_PRESTATIONS_FAMILIALES = 0.05         # 5% (100% patronal)
CNPS_MATERNITE = 0.0075                    # 0,75% (100% patronal)
CNPS_AT_MP_MIN = 0.02                      # 2% (selon secteur)
CNPS_AT_MP_MAX = 0.05                      # 5%
CNPS_AT_MP_DEFAUT = 0.03                   # 3% (défaut si inconnu)

CMU_MENSUEL_PAR_PERSONNE = 500             # 500 FCFA / mois / personne


# ─────────────────────────────────────────────────────────────────────────────
# Taxes parafiscales
# ─────────────────────────────────────────────────────────────────────────────
TAXE_SALAIRES_PATRONALE_IVOIRIEN = 0.028   # 2,8% (salariés ivoiriens)
TAXE_SALAIRES_PATRONALE_EXPATRIE = 0.12    # 12% (salariés expatriés)

FDFP_TAUX = 0.012                          # 1,2% (Formation Professionnelle Continue)
CONTRIBUTION_NATIONALE_TAUX = 0.012        # 1,2% (Contribution Nationale)


# ─────────────────────────────────────────────────────────────────────────────
# TVA
# ─────────────────────────────────────────────────────────────────────────────
TVA_TAUX_NORMAL = 0.18                     # 18%
TVA_TAUX_REDUIT = 0.09                     # 9% (depuis 17/01/2026 pour certaines filières)


# ─────────────────────────────────────────────────────────────────────────────
# Impôt sur les Sociétés (IS)
# ─────────────────────────────────────────────────────────────────────────────
IS_TAUX_NORMAL = 0.25                      # 25%
IS_TAUX_REDUIT = 0.20                      # 20% (certaines activités)
IS_MINIMUM_FORFAITAIRE_TAUX = 0.005        # 0,5% du CA TTC
IS_MINIMUM_FORFAITAIRE_PLANCHER = 3_000_000  # 3 000 000 FCFA
IS_MINIMUM_FORFAITAIRE_PLAFOND = 35_000_000  # 35 000 000 FCFA


# ─────────────────────────────────────────────────────────────────────────────
# Échéances fiscales (dates limites légales)
# ─────────────────────────────────────────────────────────────────────────────
def echeance_tva(annee: int, trimestre: int) -> date:
    """TVA : le 10 du mois suivant le trimestre (10 avril, 10 juillet, 10 octobre, 10 janvier)."""
    mois = {1: 4, 2: 7, 3: 10, 4: 1}[trimestre]
    a = annee if trimestre != 4 else annee + 1
    return date(a, mois, 10)


def echeance_its(annee: int, trimestre: int) -> date:
    """ITS : le 10 du mois suivant le trimestre."""
    return echeance_tva(annee, trimestre)


def echeance_cnps(annee: int, mois: int) -> date:
    """CNPS : dans les 15 jours suivant le mois échu."""
    if mois == 12:
        return date(annee + 1, 1, 15)
    return date(annee, mois + 1, 15)


def echeance_liasse_fiscale(annee: int) -> date:
    """Liasse fiscale DGI : au plus tard le 15 mars de l'année suivante."""
    return date(annee + 1, 3, 15)
