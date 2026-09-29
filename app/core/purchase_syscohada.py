"""
Référentiel SYSCOHADA révisé — module Achats & Fournisseurs.

Sources :
- SYSCOHADA révisé (Acte uniforme OHADA, 2017)
- Code Général des Impôts CI — TVA récupérable, retenue à la source
- Convention DGI sur les factures fournisseurs (mentions obligatoires)
"""
from __future__ import annotations

from typing import NamedTuple


# ─────────────────────────────────────────────────────────────────────────────
# Comptes fournisseurs & annexes
# ─────────────────────────────────────────────────────────────────────────────
class CompteFournisseur(NamedTuple):
    compte: str
    libelle: str


COMPTES_FOURNISSEURS: dict[str, CompteFournisseur] = {
    "fournisseur_local":     CompteFournisseur("401100", "Fournisseurs locaux"),
    "fournisseur_import":    CompteFournisseur("401200", "Fournisseurs étrangers"),
    "fournisseur_groupe":    CompteFournisseur("401300", "Fournisseurs — sociétés du groupe"),
    "factures_non_parvenues": CompteFournisseur("408100", "Fournisseurs — factures non parvenues"),
    "avances_fournisseurs":  CompteFournisseur("409100", "Fournisseurs débiteurs — avances versées"),
    "rra_fournisseurs":      CompteFournisseur("409800", "Fournisseurs — RRR à obtenir"),
}

# ─── Comptes d'achats (classe 6) ────────────────────────────────────────────
COMPTES_ACHATS: dict[str, CompteFournisseur] = {
    "marchandises":           CompteFournisseur("601000", "Achats de marchandises"),
    "matieres_premieres":     CompteFournisseur("602100", "Achats de matières premières"),
    "autres_appro":           CompteFournisseur("604100", "Achats d'autres approvisionnements"),
    "fournitures_entretien":  CompteFournisseur("605100", "Achats de fournitures d'entretien"),
    "fournitures_bureau":     CompteFournisseur("605200", "Achats de fournitures de bureau"),
    "eau":                    CompteFournisseur("605300", "Achats d'eau"),
    "electricite":            CompteFournisseur("605400", "Achats d'électricité"),
    "carburants":             CompteFournisseur("605500", "Achats de carburants"),
    "autres_energies":        CompteFournisseur("605600", "Achats d'autres énergies"),
    "emballages":             CompteFournisseur("608100", "Achats d'emballages"),
    "transport_sur_achat":    CompteFournisseur("608200", "Frais de transport sur achats"),
    "services_exterieurs":    CompteFournisseur("628100", "Frais de services externes"),
}

# ─── TVA ────────────────────────────────────────────────────────────────────
COMPTE_TVA_RECUPERABLE = "445200"            # TVA récupérable sur achats
COMPTE_TVA_RECUPERABLE_IMMO = "445100"       # TVA récupérable sur immobilisations
COMPTE_TVA_RECUPERABLE_SERVICES = "445400"   # TVA récupérable sur services extérieurs

TVA_TAUX_NORMAL = 0.18
TVA_TAUX_REDUIT = 0.09

# ─── Retenue à la source (RAS) ──────────────────────────────────────────────
# En Côte d'Ivoire, la RAS s'applique aux prestataires non-résidents (BIC)
# et à certains services locaux (prestataires individuels > 100 000 FCFA)
COMPTE_RAS_A_PAYER = "447400"                # État — Retenue à la source à payer
RAS_TAUX_SERVICES_LOCAUX = 0.05              # 5% (honoraires versés à personnes physiques)
RAS_TAUX_NON_RESIDENTS = 0.15                # 15% (BIC non-résidents)
RAS_SEUIL_LOCAL = 100_000                    # seuil RAS prestataires locaux individuels


# ─────────────────────────────────────────────────────────────────────────────
# Statuts
# ─────────────────────────────────────────────────────────────────────────────
class StatutCommande:
    BROUILLON = "brouillon"
    VALIDEE = "validee"
    PARTIELLEMENT_RECUE = "partiellement_recue"
    RECUE = "recue"
    FACTUREE = "facturee"
    ANNULEE = "annulee"
    CLOTUREE = "cloturee"


class StatutReception:
    BROUILLON = "brouillon"
    VALIDEE = "validee"
    FACTUREE = "facturee"
    ANNULEE = "annulee"


class StatutFactureFournisseur:
    BROUILLON = "brouillon"
    VALIDEE = "validee"
    PARTIELLEMENT_PAYEE = "partiellement_payee"
    PAYEE = "payee"
    EN_LITIGE = "en_litige"
    ANNULEE = "annulee"


class StatutPaiement:
    BROUILLON = "brouillon"
    VALIDE = "valide"
    ANNULE = "annule"


class ResultatRapprochement:
    OK = "ok"                          # Les 3 documents concordent
    ECART_PRIX = "ecart_prix"          # Facture ≠ Commande (prix)
    ECART_QUANTITE = "ecart_quantite"  # Facture ≠ Réception (quantité)
    SANS_COMMANDE = "sans_commande"    # Facture sans PO (achat direct)
    SANS_RECEPTION = "sans_reception"  # Facture sans BL (prestation)
    LITIGE = "litige"


# ─────────────────────────────────────────────────────────────────────────────
# Journaux SYSCOHADA
# ─────────────────────────────────────────────────────────────────────────────
JOURNAL_ACHAT = "AC"
JOURNAL_BANQUE = "BQ"
JOURNAL_CAISSE = "CA"
JOURNAL_OD = "OD"


# ─────────────────────────────────────────────────────────────────────────────
# Modes de paiement
# ─────────────────────────────────────────────────────────────────────────────
class ModePaiement:
    VIREMENT = "virement"
    CHEQUE = "cheque"
    ESPECES = "especes"
    WAVE = "wave"
    ORANGE_MONEY = "orange_money"
    MTN_MOMO = "mtn_momo"
    MOOV_MONEY = "moov_money"
    TRAITE = "traite"
    COMPENSATION = "compensation"


MODES_PAIEMENT_ADMIS = {
    ModePaiement.VIREMENT, ModePaiement.CHEQUE, ModePaiement.ESPECES,
    ModePaiement.WAVE, ModePaiement.ORANGE_MONEY, ModePaiement.MTN_MOMO,
    ModePaiement.MOOV_MONEY, ModePaiement.TRAITE, ModePaiement.COMPENSATION,
}


# Mapping mode de paiement → compte de trésorerie SYSCOHADA
COMPTES_TRESORERIE_PAR_MODE: dict[str, str] = {
    ModePaiement.VIREMENT:     "521000",
    ModePaiement.CHEQUE:       "521000",
    ModePaiement.ESPECES:      "571000",
    ModePaiement.WAVE:         "521100",
    ModePaiement.ORANGE_MONEY: "521100",
    ModePaiement.MTN_MOMO:     "521100",
    ModePaiement.MOOV_MONEY:   "521100",
    ModePaiement.TRAITE:       "521000",
    ModePaiement.COMPENSATION: "411000",   # compensation fournisseur ↔ client
}
