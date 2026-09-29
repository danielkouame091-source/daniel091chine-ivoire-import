"""
Référentiel SYSCOHADA révisé — module Ventes & Clients.

Sources :
- SYSCOHADA révisé (Acte uniforme OHADA, 2017) — chapitre 7 (produits)
- Code Général des Impôts CI — TVA collectée, retenue à la source
- Loi ivoirienne sur la facturation (mentions obligatoires)
"""
from __future__ import annotations

from typing import NamedTuple


# ─────────────────────────────────────────────────────────────────────────────
# Comptes clients & annexes
# ─────────────────────────────────────────────────────────────────────────────
class CompteClient(NamedTuple):
    compte: str
    libelle: str


COMPTES_CLIENTS: dict[str, CompteClient] = {
    "client_local":        CompteClient("411100", "Clients locaux"),
    "client_export":       CompteClient("411200", "Clients étrangers"),
    "client_groupe":       CompteClient("411300", "Clients — sociétés du groupe"),
    "clients_douteux":     CompteClient("416100", "Clients douteux ou litigieux"),
    "factures_a_etablir":  CompteClient("418100", "Clients — produits à recevoir"),
    "avances_recues":      CompteClient("419100", "Clients créditeurs — avances reçues"),
    "rrr_a_accorder":      CompteClient("419800", "Clients — RRR à accorder"),
}


# ─── Comptes de produits (classe 7) ─────────────────────────────────────────
COMPTES_PRODUITS: dict[str, CompteClient] = {
    "marchandises":        CompteClient("701100", "Ventes de marchandises"),
    "produits_finis":      CompteClient("702100", "Ventes de produits finis"),
    "produits_intermediaires": CompteClient("703100", "Ventes de produits intermédiaires"),
    "produits_residuels":  CompteClient("704100", "Ventes de produits résiduels"),
    "travaux":             CompteClient("705100", "Travaux facturés"),
    "services":            CompteClient("706100", "Services vendus"),
    "produits_accessoires": CompteClient("707100", "Produits accessoires (port, emballage)"),
    "locations":           CompteClient("707200", "Locations facturées"),
}


# ─── TVA & annexes ──────────────────────────────────────────────────────────
COMPTE_TVA_COLLECTEE = "443100"              # TVA collectée sur ventes
COMPTE_TVA_COLLECTEE_SERVICES = "443200"     # TVA collectée sur services

# Taux TVA CI
TVA_TAUX_NORMAL = 0.18
TVA_TAUX_REDUIT = 0.09

# RRR accordés (réductions commerciales post-facturation)
COMPTE_RRR_ACCORDES = "709000"               # RRR accordés sur ventes

# Créances douteuses
COMPTE_DEPRECIATION_CLIENTS = "491000"       # Dépréciation des comptes clients


# ─────────────────────────────────────────────────────────────────────────────
# Statuts
# ─────────────────────────────────────────────────────────────────────────────
class StatutDevis:
    BROUILLON = "brouillon"
    ENVOYE = "envoye"
    ACCEPTE = "accepte"
    REFUSE = "refuse"
    EXPIRE = "expire"
    CONVERTI = "converti"       # converti en commande


class StatutCommandeClient:
    BROUILLON = "brouillon"
    CONFIRMEE = "confirmee"
    PARTIELLEMENT_LIVREE = "partiellement_livree"
    LIVREE = "livree"
    FACTUREE = "facturee"
    ANNULEE = "annulee"
    CLOTUREE = "cloturee"


class StatutBL:
    BROUILLON = "brouillon"
    VALIDE = "valide"
    FACTURE = "facture"
    ANNULE = "annule"


class StatutFactureClient:
    BROUILLON = "brouillon"
    VALIDEE = "validee"
    PARTIELLEMENT_PAYEE = "partiellement_payee"
    PAYEE = "payee"
    EN_RETARD = "en_retard"              # statut calculé
    EN_LITIGE = "en_litige"
    ANNULEE = "annulee"


class StatutEncaissement:
    BROUILLON = "brouillon"
    VALIDE = "valide"
    ANNULE = "annule"


class StatutAvoir:
    BROUILLON = "brouillon"
    VALIDE = "valide"
    IMPUTE = "impute"                     # imputé sur une facture
    ANNULE = "annule"


class NiveauRelance:
    AUCUNE = "aucune"
    AIMABLE = "aimable"                   # J+3 après échéance
    FERME = "ferme"                       # J+15 après échéance
    MISE_EN_DEMEURE = "mise_en_demeure"   # J+30 après échéance
    CONTENTIEUX = "contentieux"           # J+60 après échéance


# ─────────────────────────────────────────────────────────────────────────────
# Journaux SYSCOHADA
# ─────────────────────────────────────────────────────────────────────────────
JOURNAL_VENTE = "VE"
JOURNAL_BANQUE = "BQ"
JOURNAL_CAISSE = "CA"
JOURNAL_OD = "OD"
JOURNAL_AVOIR = "AV"     # Journal des avoirs (à créer si absent)


# ─────────────────────────────────────────────────────────────────────────────
# Modes d'encaissement
# ─────────────────────────────────────────────────────────────────────────────
class ModeEncaissement:
    VIREMENT = "virement"
    CHEQUE = "cheque"
    ESPECES = "especes"
    WAVE = "wave"
    ORANGE_MONEY = "orange_money"
    MTN_MOMO = "mtn_momo"
    MOOV_MONEY = "moov_money"
    TRAITE = "traite"
    CARTE = "carte"
    COMPENSATION = "compensation"


MODES_ENCAISSEMENT_ADMIS = {
    ModeEncaissement.VIREMENT, ModeEncaissement.CHEQUE, ModeEncaissement.ESPECES,
    ModeEncaissement.WAVE, ModeEncaissement.ORANGE_MONEY, ModeEncaissement.MTN_MOMO,
    ModeEncaissement.MOOV_MONEY, ModeEncaissement.TRAITE, ModeEncaissement.CARTE,
    ModeEncaissement.COMPENSATION,
}


COMPTES_TRESORERIE_PAR_MODE: dict[str, str] = {
    ModeEncaissement.VIREMENT:     "521000",
    ModeEncaissement.CHEQUE:       "521000",
    ModeEncaissement.ESPECES:      "571000",
    ModeEncaissement.WAVE:         "521100",
    ModeEncaissement.ORANGE_MONEY: "521100",
    ModeEncaissement.MTN_MOMO:     "521100",
    ModeEncaissement.MOOV_MONEY:   "521100",
    ModeEncaissement.CARTE:        "521200",
    ModeEncaissement.TRAITE:       "521000",
    ModeEncaissement.COMPENSATION: "401000",
}


# ─────────────────────────────────────────────────────────────────────────────
# Règles de relance automatique
# ─────────────────────────────────────────────────────────────────────────────
# jours après l'échéance → niveau de relance
REGLES_RELANCE: list[tuple[int, str]] = [
    (3,  NiveauRelance.AIMABLE),
    (15, NiveauRelance.FERME),
    (30, NiveauRelance.MISE_EN_DEMEURE),
    (60, NiveauRelance.CONTENTIEUX),
]


def niveau_relance_pour(jours_retard: int) -> str:
    """Retourne le niveau de relance applicable selon les jours de retard."""
    niveau = NiveauRelance.AUCUNE
    for seuil, niv in REGLES_RELANCE:
        if jours_retard >= seuil:
            niveau = niv
    return niveau


# ─────────────────────────────────────────────────────────────────────────────
# Mentions obligatoires sur facture (CGI CI)
# ─────────────────────────────────────────────────────────────────────────────
MENTIONS_OBLIGATOIRES_FACTURE: list[str] = [
    "Nom et adresse du vendeur",
    "Numéro RCCM du vendeur",
    "Numéro de compte contribuable du vendeur",
    "Numéro de facture et date",
    "Nom et adresse du client",
    "Numéro de compte contribuable du client (si assujetti)",
    "Désignation précise des biens/services",
    "Quantité, prix unitaire HT",
    "Taux et montant de TVA",
    "Montant total TTC",
    "Date d'échéance",
    "Mode de règlement",
    "Mention 'Facture acquittée' dès paiement complet",
]
