"""
Référentiel Gestion Électronique de Documents (GED).

Objectifs :
- Centraliser toutes les pièces justificatives comptables et fiscales
- Assurer la conformité OHADA (conservation 10 ans) et DGI
- Indexer automatiquement par OCR
- Permettre la signature électronique (interne + externe)
- Tracer toute action (audit trail)

Sources :
- SYSCOHADA révisé (art. 17-20 : tenue des livres et pièces justificatives)
- CGI CI art. 921 (conservation 10 ans des documents)
- Loi ivoirienne 2013-546 sur les transactions électroniques
- eIDAS (signature électronique UE — inspiration)
"""
from __future__ import annotations

from typing import NamedTuple


# ─────────────────────────────────────────────────────────────────────────────
# Types de documents
# ─────────────────────────────────────────────────────────────────────────────
class TypeDocGED:
    # Comptables
    FACTURE_CLIENT = "facture_client"
    FACTURE_FOURNISSEUR = "facture_fournisseur"
    AVOIR_CLIENT = "avoir_client"
    AVOIR_FOURNISSEUR = "avoir_fournisseur"
    BON_COMMANDE = "bon_commande"
    BON_LIVRAISON = "bon_livraison"
    DEVIS = "devis"
    RECU = "recu"
    TICKET_CAISSE = "ticket_caisse"
    RELEVE_BANCAIRE = "releve_bancaire"
    CHEQUE_SCAN = "cheque_scan"

    # Fiscaux
    DECLARATION_TVA = "declaration_tva"
    DECLARATION_IS = "declaration_is"
    DECLARATION_ITS = "declaration_its"
    LIASSE_FISCALE = "liasse_fiscale"
    ATTESTATION_FISCALE = "attestation_fiscale"
    QUITTANCE_DGI = "quittance_dgi"
    ATTESTATION_FNE = "attestation_fne"

    # Sociaux
    BULLETIN_PAIE = "bulletin_paie"
    DECLARATION_CNPS = "declaration_cnps"
    CONTRAT_TRAVAIL = "contrat_travail"
    CERTIFICAT_TRAVAIL = "certificat_travail"
    ATTESTATION_SALAIRE = "attestation_salaire"

    # Juridiques
    CONTRAT_COMMERCIAL = "contrat_commercial"
    STATUTS_SOCIETE = "statuts_societe"
    PV_ASSEMBLEE = "pv_assemblee"
    RCCM = "rccm"
    ATTESTATION_IMPOSITION = "attestation_imposition"

    # Bancaires
    RIB = "rib"
    CONVENTION_BANCAIRE = "convention_bancaire"
    ATTESTATION_BANCAIRE = "attestation_bancaire"

    # RH
    CV = "cv"
    DIPLOME = "diplome"
    PIECE_IDENTITE = "piece_identite"
    CERTIFICAT_MEDICAL = "certificat_medical"

    # Projets
    PLAN_ARCHITECTE = "plan_architecte"
    PERMIS_CONSTRUIRE = "permis_construire"
    SITUATION_TRAVAUX = "situation_travaux"
    PROCES_VERBAL = "proces_verbal"

    # Portail
    FACTURE_PORTAL = "facture_portal"
    JUSTIFICATIF_PAIEMENT = "justificatif_paiement"

    # Autre
    AUTRE = "autre"


# ─────────────────────────────────────────────────────────────────────────────
# Statuts de document
# ─────────────────────────────────────────────────────────────────────────────
class StatutDoc:
    BROUILLON = "brouillon"
    EN_REVISION = "en_revision"
    VALIDE = "valide"
    SIGNE = "signe"
    ARCHIVE = "archive"
    EXPIRE = "expire"        # Si date_expiration dépassée
    SUPPRIME = "supprime"    # Soft delete


# ─────────────────────────────────────────────────────────────────────────────
# Types de fichiers acceptés
# ─────────────────────────────────────────────────────────────────────────────
MIME_TYPES_ACCEPTES = {
    # Documents
    "application/pdf": ".pdf",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.ms-powerpoint": ".ppt",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    # Images
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/tiff": ".tiff",
    "image/heic": ".heic",
    # Texte
    "text/plain": ".txt",
    "text/csv": ".csv",
    "text/markdown": ".md",
    # Archives
    "application/zip": ".zip",
    "application/x-rar-compressed": ".rar",
}

TAILLE_MAX_MO = 50          # 50 Mo par fichier
TAILLE_MAX_TOTAL_MO = 500   # 500 Mo par tenant (soft limit pour MVP)


# ─────────────────────────────────────────────────────────────────────────────
# Types d'OCR
# ─────────────────────────────────────────────────────────────────────────────
class TypeOCR:
    TESSERACT = "tesseract"       # Standard, FR
    PADDLEOCR = "paddleocr"       # Meilleur pour le français moderne
    TEXTRACT = "textract"         # AWS (si activé)
    VISION_API = "vision_api"     # Google Cloud Vision
    NO_OCR = "no_ocr"             # Désactivé


# ─────────────────────────────────────────────────────────────────────────────
# Statuts OCR
# ─────────────────────────────────────────────────────────────────────────────
class StatutOCR:
    EN_ATTENTE = "en_attente"
    EN_COURS = "en_cours"
    TERMINE = "termine"
    ECHEC = "echec"
    NON_APPLICABLE = "non_applicable"    # PDF texte natif → pas besoin


# ─────────────────────────────────────────────────────────────────────────────
# Types de signature électronique
# ─────────────────────────────────────────────────────────────────────────────
class TypeSignature:
    SIMPLE = "simple"                # Coché + acceptation CGU
    AVANCEE = "avancee"              # OTP + log IP
    QUALIFIEE = "qualifiee"          # Certificat ANSSI / eIDAS (pas pour MVP)


# ─────────────────────────────────────────────────────────────────────────────
# Statuts de signature
# ─────────────────────────────────────────────────────────────────────────────
class StatutSignature:
    EN_ATTENTE = "en_attente"
    OTP_ENVOYE = "otp_envoye"
    SIGNEE = "signee"
    REFUSEE = "refusee"
    EXPIREE = "expiree"


# ─────────────────────────────────────────────────────────────────────────────
# Types de dossiers
# ─────────────────────────────────────────────────────────────────────────────
class TypeDossier:
    RACINE = "racine"
    SYSTEME = "systeme"        # Comptabilité, Fiscal, RH, etc.
    CLIENT = "client"          # Un dossier par client
    FOURNISSEUR = "fournisseur" # Un dossier par fournisseur
    EMPLOYE = "employe"        # Un dossier par employé
    PROJET = "projet"          # Un dossier par projet
    ANNE = "annee"             # Sous-dossier par année
    CUSTOM = "custom"          # Créé manuellement


# ─────────────────────────────────────────────────────────────────────────────
# Règles de rétention (conformité OHADA)
# ─────────────────────────────────────────────────────────────────────────────
class Retention:
    DEFAULT_ANNEES = 10                    # 10 ans par défaut (CGI CI art. 921)
    COMPTABLE_ANNEES = 10
    FISCAL_ANNEES = 10
    SOCIAL_ANNEES = 30                      # CNPS : 30 ans
    RH_ANNEES = 30
    CONTRATS_ANNEES = 30
    JURIDIQUE_ANNEES = 10
    FACTURE_ANNEES = 10
    BANCAIRE_ANNEES = 10


# ─────────────────────────────────────────────────────────────────────────────
# Actions d'audit GED
# ─────────────────────────────────────────────────────────────────────────────
class ActionGED:
    UPLOAD = "ged.upload"
    DOWNLOAD = "ged.download"
    VIEW = "ged.view"
    UPDATE_METADATA = "ged.update_metadata"
    DELETE = "ged.delete"
    RESTORE = "ged.restore"
    MOVE = "ged.move"
    COPY = "ged.copy"
    SHARE = "ged.share"
    REVOKE_SHARE = "ged.revoke_share"
    SIGN = "ged.sign"
    VERIFY_SIGNATURE = "ged.verify_signature"
    OCR_DONE = "ged.ocr_done"
    VERSION_CREATE = "ged.version_create"
    FOLDER_CREATE = "ged.folder_create"
    ARCHIVE = "ged.archive"


# ─────────────────────────────────────────────────────────────────────────────
# Sécurité de partage
# ─────────────────────────────────────────────────────────────────────────────
class SecuritePartage:
    TOKEN_TTL_JOURS = 30           # Lien public valable 30 jours max
    TOKEN_TTL_DEFAUT_HEURES = 72   # Par défaut 72 heures
    MAX_DOWNLOADS = 100            # Nombre max de téléchargements


# ─────────────────────────────────────────────────────────────────────────────
# Dossiers système (seed)
# ─────────────────────────────────────────────────────────────────────────────
DOSSIERS_SYSTEME: list[dict] = [
    {"code": "COMPTABILITE", "nom": "Comptabilité", "icone": "calculator", "type": "systeme", "ordre": 1},
    {"code": "FISCAL", "nom": "Fiscal", "icone": "receipt", "type": "systeme", "ordre": 2},
    {"code": "SOCIAL", "nom": "Social / Paie", "icone": "users", "type": "systeme", "ordre": 3},
    {"code": "JURIDIQUE", "nom": "Juridique", "icone": "scale", "type": "systeme", "ordre": 4},
    {"code": "BANCAIRE", "nom": "Bancaire", "icone": "landmark", "type": "systeme", "ordre": 5},
    {"code": "RH", "nom": "Ressources Humaines", "icone": "user-check", "type": "systeme", "ordre": 6},
    {"code": "PROJETS", "nom": "Projets & Chantiers", "icone": "hard-hat", "type": "systeme", "ordre": 7},
    {"code": "CLIENTS", "nom": "Clients", "icone": "shopping-cart", "type": "systeme", "ordre": 8},
    {"code": "FOURNISSEURS", "nom": "Fournisseurs", "icone": "truck", "type": "systeme", "ordre": 9},
    {"code": "AUTRE", "nom": "Autres documents", "icone": "folder", "type": "systeme", "ordre": 99},
]


# ─────────────────────────────────────────────────────────────────────────────
# Formats PDF/A pour archivage légal
# ─────────────────────────────────────────────────────────────────────────────
PDF_A_CONFORMITE = "PDF/A-2b"     # Standard ISO 19005-2 pour l'archivage légal
PDF_A_CONVERTISSEUR = "ghostscript"


# ─────────────────────────────────────────────────────────────────────────────
# Empreinte (hash) obligatoire pour conformité légale
# ─────────────────────────────────────────────────────────────────────────────
HASH_ALGO = "sha256"              # SHA-256 pour conformité
HASH_ALGO_SECONDARY = "blake2b"   # Backup
