"""
Référentiel SYSCOHADA révisé — module Trésorerie & Rapprochement bancaire.

Sources :
- SYSCOHADA révisé (Acte uniforme OHADA, 2017) — chapitre 5
- Norme bancaire UEMOA sur les relevés
- Format OFX (Open Financial Exchange) — standard international
- Format MT940 (SWIFT) — utilisé par les banques CI (SGCI, NSIA, BOA, Ecobank)
"""
from __future__ import annotations

from typing import NamedTuple


# ─────────────────────────────────────────────────────────────────────────────
# Comptes de trésorerie (classe 5)
# ─────────────────────────────────────────────────────────────────────────────
class CompteTresorerie(NamedTuple):
    compte: str
    libelle: str
    type_compte: str          # banque | caisse | mobile_money | placement


COMPTES_TRESORERIE: dict[str, CompteTresorerie] = {
    # ─── Banques locales ────────────────────────────────────────────────
    "banque_sgci":          CompteTresorerie("521000", "SGCI",                     "banque"),
    "banque_nsia":          CompteTresorerie("521100", "NSIA Banque",              "banque"),
    "banque_boa":           CompteTresorerie("521200", "Bank of Africa",           "banque"),
    "banque_ecobank":       CompteTresorerie("521300", "Ecobank CI",               "banque"),
    "banque_orabank":       CompteTresorerie("521400", "Orabank CI",               "banque"),
    "banque_correspondant": CompteTresorerie("521500", "Banque correspondante",    "banque"),
    "banque_secondaire":    CompteTresorerie("521600", "Banque secondaire",        "banque"),
    # ─── Mobile Money ──────────────────────────────────────────────────
    "wave":                 CompteTresorerie("521700", "Wave CI",                  "mobile_money"),
    "orange_money":         CompteTresorerie("521800", "Orange Money CI",          "mobile_money"),
    "mtn_momo":             CompteTresorerie("521900", "MTN MoMo CI",              "mobile_money"),
    "moov_money":           CompteTresorerie("521910", "Moov Money CI",            "mobile_money"),
    # ─── Caisses ───────────────────────────────────────────────────────
    "caisse_principale":    CompteTresorerie("571000", "Caisse principale",        "caisse"),
    "caisse_secondaire":    CompteTresorerie("571100", "Caisse secondaire",        "caisse"),
    "caisse_devises":       CompteTresorerie("571200", "Caisse devises",           "caisse"),
    # ─── Placements / valeurs à encaisser ──────────────────────────────
    "titres_placement":     CompteTresorerie("503000", "Titres de placement",      "placement"),
    "valeurs_a_encaisser":  CompteTresorerie("511000", "Effets à encaisser",       "placement"),
    "valeurs_a_payer":      CompteTresorerie("512000", "Effets à payer",           "placement"),
    "cheques_a_encaisser":  CompteTresorerie("511100", "Chèques à encaisser",      "placement"),
    "cheques_a_payer":      CompteTresorerie("512100", "Chèques à payer",          "placement"),
    "virements_internes":   CompteTresorerie("585000", "Virements de fonds internes", "placement"),
}


# ─── Comptes d'attente pour écarts de rapprochement ────────────────────────
COMPTE_ATTENTE_RAPPROCHEMENT = "471800"          # Écarts de rapprochement bancaire
COMPTE_FRAIS_BANCAIRES = "631800"                # Frais et commissions bancaires
COMPTE_INTERETS_BANCAIRES = "671000"             # Intérêts débiteurs
COMPTE_PRODUITS_BANCAIRES = "771000"             # Intérêts créditeurs


# ─────────────────────────────────────────────────────────────────────────────
# Modes de rapprochement
# ─────────────────────────────────────────────────────────────────────────────
class StatutLigneReleve:
    NON_RAPPROCHEE = "non_rapprochee"
    RAPPROCHEE_AUTO = "rapprochee_auto"
    RAPPROCHEE_MANUELLE = "rapprochee_manuelle"
    ECART = "ecart"
    FRAIS_BANCAIRE = "frais_bancaire"
    INTERET = "interet"


class TypeLigneReleve:
    DEBIT = "debit"
    CREDIT = "credit"


class StatutRapprochement:
    EN_COURS = "en_cours"
    EQUILIBRE = "equilibre"
    ECART = "ecart"
    VALIDE = "valide"


# ─────────────────────────────────────────────────────────────────────────────
# Tolérance pour le matching automatique
# ─────────────────────────────────────────────────────────────────────────────
MATCHING_DATE_TOLERANCE_JOURS = 3                # fenêtre de ± 3 jours
MATCHING_MONTANT_TOLERANCE_PCT = 0.005           # 0,5% de tolérance sur le montant
MATCHING_LIBELLE_SEUIL = 0.65                    # 65% de similarité textuelle
MATCHING_MONTANT_EXACT_PRIORITE = True           # match exact montant prioritaire


# ─────────────────────────────────────────────────────────────────────────────
# Journaux
# ─────────────────────────────────────────────────────────────────────────────
JOURNAL_BANQUE = "BQ"
JOURNAL_CAISSE = "CA"
JOURNAL_OD = "OD"


# ─────────────────────────────────────────────────────────────────────────────
# États de rapprochement (terminologie bancaire UEMOA)
# ─────────────────────────────────────────────────────────────────────────────
class EtatRapprochement:
    OK = "ok"                                       # solde comptable = solde bancaire
    ECART_POSITIF = "ecart_positif"                 # banque > compta (enregistrement manquant côté compta)
    ECART_NEGATIF = "ecart_negatif"                 # compta > banque (opération non passée en banque)
    NON_RAPPROCHE = "non_rapproche"                 # lignes non rapprochées


# ─────────────────────────────────────────────────────────────────────────────
# Mapping codes OFX/SWIFT vers libellés
# ─────────────────────────────────────────────────────────────────────────────
CODES_BANCAIRES_CI: dict[str, str] = {
    "FRAIS": "Frais bancaires",
    "COM": "Commission bancaire",
    "TENUE": "Tenue de compte",
    "VIRE": "Virement",
    "VIR": "Virement",
    "CHEQ": "Chèque",
    "CHQ": "Chèque",
    "PRELEV": "Prélèvement automatique",
    "PRLV": "Prélèvement automatique",
    "RETRAIT": "Retrait DAB",
    "DEPOT": "Dépôt espèces",
    "REMISE": "Remise chèque",
    "INTERETS": "Intérêts créditeurs",
    "AGIOS": "Agios / intérêts débiteurs",
    "SWIFT": "Virement international SWIFT",
    "SEPA": "Virement SEPA",
    "MOBILE": "Transaction Mobile Money",
    "WAVE": "Wave",
    "OM": "Orange Money",
    "MTN": "MTN MoMo",
    "MOOV": "Moov Money",
}
