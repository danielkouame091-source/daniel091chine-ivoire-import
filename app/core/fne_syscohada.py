"""
Référentiel FNE — Facture Normalisée Électronique (DGI Côte d'Ivoire).

Sources :
- Loi de Finances 2025 (articles 384, 385 CGI)
- Procédure d'interfaçage API FNE (fne.dgi.gouv.ci/documents/FNE-procedureapi.pdf)
- Arrêté sur la numérotation des factures normalisées

Endpoints API FNE (REST/JSON) :
- POST /external/invoices                     → Certifier une facture de vente
- POST /external/invoices/{id}/refund         → Certifier une facture d'avoir
- POST /external/invoices/{id}/cancel         → Annuler une facture
- GET  /external/invoices/{id}                → Récupérer une facture certifiée
- GET  /external/invoices/{reference}         → Récupérer par référence DGI
- GET  /external/invoices/balance-stickers    → Solde de stickers

Authentification : Bearer JWT (obtenu via OAuth 2.0 ou clé API statique)
"""
from __future__ import annotations

from typing import NamedTuple


# ─────────────────────────────────────────────────────────────────────────────
# Environnements FNE
# ─────────────────────────────────────────────────────────────────────────────
class FneEnvironment:
    SANDBOX = "sandbox"          # Environnement de test DGI
    PRODUCTION = "production"    # URL fournie après validation


FNE_URLS = {
    FneEnvironment.SANDBOX: "https://www.services.fne.dgi.gouv.ci",
    FneEnvironment.PRODUCTION: "https://api.fne.dgi.gouv.ci",
}


# ─────────────────────────────────────────────────────────────────────────────
# Types de documents FNE
# ─────────────────────────────────────────────────────────────────────────────
class FneDocumentType:
    INVOICE = "invoice"                # Facture de vente
    REFUND = "refund"                  # Facture d'avoir
    PROFORMA = "proforma"              # Facture proforma
    RNE = "rne"                        # Reçu normalisé électronique
    BAPA = "bapa"                      # Bordereau d'achat produits agricoles
    RAPA = "rapa"                      # Reçu d'achat produits agricoles


FNE_DOCUMENT_TYPES = {
    FneDocumentType.INVOICE,
    FneDocumentType.REFUND,
    FneDocumentType.PROFORMA,
    FneDocumentType.RNE,
    FneDocumentType.BAPA,
    FneDocumentType.RAPA,
}


# ─────────────────────────────────────────────────────────────────────────────
# Statuts de certification FNE
# ─────────────────────────────────────────────────────────────────────────────
class FneStatut:
    BROUILLON = "brouillon"                    # Pas encore soumis
    EN_ATTENTE = "en_attente"                  # Soumis à FNE, en attente
    CERTIFIEE = "certifiee"                    # Certifiée avec succès
    REJETEE = "rejetee"                        # Rejetée par la DGI
    ANNULEE = "annulee"                        # Annulée après certification
    EXPIREE = "expiree"                        # Délai de certification dépassé
    ERROR = "error"                            # Erreur technique


FNE_STATUTS_FINAUX = {FneStatut.CERTIFIEE, FneStatut.REJETEE, FneStatut.ANNULEE}


# ─────────────────────────────────────────────────────────────────────────────
# Modes de paiement FNE (enum imposé par l'API)
# ─────────────────────────────────────────────────────────────────────────────
class FnePaymentMethod:
    CASH = "cash"                              # Espèces
    CHEQUE = "check"                           # Chèque
    CARD = "card"                              # Carte bancaire
    MOBILE_MONEY = "mobile-money"              # Mobile Money (Wave, OM, MTN, Moov)
    TRANSFER = "transfer"                      # Virement
    OTHER = "other"                            # Autre


# Mapping modes internes → modes FNE
MAP_MODE_PAIEMENT_FNE: dict[str, str] = {
    "especes": FnePaymentMethod.CASH,
    "cheque": FnePaymentMethod.CHEQUE,
    "carte": FnePaymentMethod.CARD,
    "wave": FnePaymentMethod.MOBILE_MONEY,
    "orange_money": FnePaymentMethod.MOBILE_MONEY,
    "mtn_momo": FnePaymentMethod.MOBILE_MONEY,
    "moov_money": FnePaymentMethod.MOBILE_MONEY,
    "virement": FnePaymentMethod.TRANSFER,
    "compensation": FnePaymentMethod.OTHER,
    "traite": FnePaymentMethod.OTHER,
}


# ─────────────────────────────────────────────────────────────────────────────
# Codes de TVA FNE
# ─────────────────────────────────────────────────────────────────────────────
class FneVatCode:
    TVA_NORMAL = "TVA"                          # 18%
    TVA_REDUIT = "TVA_REDUIT"                   # 9%
    EXONERE = "EXO"                             # Exonéré
    HORS_TAXE = "HT"                            # Hors taxe


FNE_VAT_RATES: dict[str, float] = {
    FneVatCode.TVA_NORMAL: 0.18,
    FneVatCode.TVA_REDUIT: 0.09,
    FneVatCode.EXONERE: 0.0,
    FneVatCode.HORS_TAXE: 0.0,
}


# ─────────────────────────────────────────────────────────────────────────────
# Stickers (unités de certification)
# ─────────────────────────────────────────────────────────────────────────────
FNE_STICKER_PRIX_FNE = 20      # FCFA par facture
FNE_STICKER_PRIX_RNE = 15      # FCFA par reçu
FNE_STICKER_PRIX_RNE_GROS = 25 # FCFA pour reçu espèces > 100 000 FCFA

FNE_SEUIL_ESPECES_GROS = 100_000  # Seuil de transaction en espèces


# ─────────────────────────────────────────────────────────────────────────────
# Format de numérotation FNE
# ─────────────────────────────────────────────────────────────────────────────
def formater_numero_fne(ncc: str, annee: int, sequence: int, avoir: bool = False) -> str:
    """
    Format imposé par l'arrêté DGI :
    - Facture vente : NCC + AAAA + séquence (13 chiffres)
    - Facture avoir  : A + NCC + AAAA + séquence (14 caractères)

    Exemple : 9606123E25000000019 (facture de vente)
              A9606123E2500000006 (facture d'avoir)
    """
    prefix = "A" if avoir else ""
    return f"{prefix}{ncc}{annee}{sequence:09d}"


# ─────────────────────────────────────────────────────────────────────────────
# Codes d'erreur FNE (extraits de la doc DGI)
# ─────────────────────────────────────────────────────────────────────────────
FNE_ERROR_CODES: dict[int, str] = {
    400: "Erreur dans la requête (données invalides)",
    401: "Clé API invalide ou expirée",
    403: "Accès refusé — certificat non valide",
    404: "Ressource non trouvée",
    409: "Conflit — facture déjà certifiée",
    422: "Données sémantiquement invalides",
    429: "Trop de requêtes — rate limit atteint",
    500: "Erreur interne DGI",
    502: "Passerelle FNE indisponible",
    503: "Service FNE en maintenance",
}


# ─────────────────────────────────────────────────────────────────────────────
# Politique de retry
# ─────────────────────────────────────────────────────────────────────────────
FNE_RETRY_MAX = 5
FNE_RETRY_DELAY_BASE_S = 5              # backoff exponentiel : 5s, 25s, 125s...
FNE_RETRY_ERRORS = {429, 500, 502, 503}  # erreurs pour lesquelles on retente
FNE_TIMEOUT_S = 30


# ─────────────────────────────────────────────────────────────────────────────
# Types d'événements webhook DGI (si activé)
# ─────────────────────────────────────────────────────────────────────────────
class FneWebhookEvent:
    INVOICE_CERTIFIED = "invoice.certified"
    INVOICE_REJECTED = "invoice.rejected"
    INVOICE_CANCELLED = "invoice.cancelled"
    STICKER_LOW = "sticker.low"


# ─────────────────────────────────────────────────────────────────────────────
# Mentions légales obligatoires
# ─────────────────────────────────────────────────────────────────────────────
FNE_MENTIONS_OBLIGATOIRES = [
    "QR Code de certification",
    "Visuel FNE",
    "Numéro de facture (format normatif)",
    "NCC du vendeur",
    "Raison sociale du vendeur",
    "Adresse du vendeur",
    "RCCM du vendeur",
    "Centre de rattachement",
    "Régime d'imposition",
    "Date d'émission",
    "Numéro et date de la facture d'origine (avoir)",
    "Désignation des biens/services",
    "Quantité, prix unitaire HT",
    "Taux et montant TVA",
    "Montant TTC",
    "Mode de règlement",
]
