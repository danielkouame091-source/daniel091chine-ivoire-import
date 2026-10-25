"""
sndgir_erp.py — SNDGIR & Transit ERP
====================================
Plateforme SaaS multi-tenant destinée aux cabinets d'expertise comptable,
directions financières, PME/SARL/SA et institutions bancaires de Côte d'Ivoire
et de la zone UEMOA (interopérable avec les écosystèmes de type Sage / SGBCI /
Ecobank).

Périmètre fonctionnel (bloc unique exécutable, Streamlit + SQLite) :
  1. MULTI-TENANT & SÉCURITÉ : isolation stricte par entreprise cliente,
     rôles granulaires, piste d'audit IMMUABLE (chaîne de hachage append-only),
     chiffrement des secrets, empreintes cryptographiques SHA-256.
  2. MOTEUR COMPTABLE SYSCOHADA RÉVISÉ : partie double, journaux auxiliaires
     et centraux (ACQ/VTE/BAN/OD), génération AUTOMATIQUE des écritures à
     partir des flux de caisse, de transit, de surestaries et de débours
     douaniers, Balance Générale, Grand Livre, états financiers (Bilan + CR).
  3. TRANSIT / IMPORT-EXPORT / DOUANES : manifestes maritimes, apurement des
     connaissements (B/L), calcul des droits (régimes C100/E100/AT/TR) avec
     prélèvements communautaires UEMOA/CEDEAO et TVA 18%, sélectivité des
     risques (canaux Vert/Bleu/Jaune/Rouge) par scoring, surestaries portuaires
     (franchise armateur + pénalité journalière USD -> FCFA au taux en direct),
     génération PDF du Bon à Enlever (BAE) scellé SHA-256 + facture transitaire.
  4. IA & OCR/IDP : assistant expert fiscalité/droit douanier ivoirien (Groq),
     extraction automatique de données sur factures avec cross-checking et
     détection de sous-évaluation, générateur de communications (validation
     humaine OBLIGATOIRE avant diffusion).
  5. UX & INTEROPÉRABILITÉ : dark mode épuré, KPI dynamiques, graphiques Plotly
     (dégradation gracieuse si absent), init/seed automatique de la base.

Lancer :  streamlit run sndgir_erp.py

Note d'honnêteté : les taux de taxes et de prélèvements ci-dessous reflètent le
régime général le plus courant en Côte d'Ivoire mais sont MODIFIABLES à chaque
calcul ; ils ne remplacent pas la validation d'un expert-comptable agréé ni les
barèmes officiels en vigueur (DGI / Douanes ivoiriennes) avant toute
déclaration officielle.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import hmac
import io
import json
import os
import re
import smtplib
import sqlite3
from datetime import date, datetime, timedelta
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import pandas as pd
import streamlit as st

# ─── Dépendances optionnelles : dégradation gracieuse ──────────────────────────
try:
    import plotly.express as px
    import plotly.graph_objects as go

    PLOTLY_OK = True
except ImportError:  # pragma: no cover
    PLOTLY_OK = False

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    REPORTLAB_OK = True
except ImportError:  # pragma: no cover
    REPORTLAB_OK = False

try:
    from groq import Groq

    GROQ_OK = True
except ImportError:  # pragma: no cover
    Groq = None
    GROQ_OK = False

try:
    import requests

    REQUESTS_OK = True
except ImportError:  # pragma: no cover
    requests = None
    REQUESTS_OK = False

try:
    from passlib.hash import argon2

    ARGON2_OK = True
except Exception:  # pragma: no cover
    argon2 = None
    ARGON2_OK = False


# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION GLOBALE
# ══════════════════════════════════════════════════════════════════════════════
APP_NAME = "SNDGIR & Transit ERP"
APP_VERSION = "1.0.0"

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "sndgir_erp.db"
UPLOAD_DIR = BASE_DIR / "uploads_sndgir"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# ─── Paramètres fiscaux / douaniers (valeurs par défaut modifiables) ──────────
TAUX_TVA = 18.0                 # TVA Côte d'Ivoire (taux normal)
PC_UEMOA_PCT = 0.8              # Prélèvement Communautaire UEMOA
PCC_CEDEAO_PCT = 0.5           # Prélèvement Communautaire CEDEAO
TAUX_IS_DEFAUT = 25.0          # Impôt sur les Sociétés / BIC (régime réel normal)
TAUX_RS_PCT = 1.0              # Redevance Statistique (≈ 1 % de la valeur CAF)
# Contrôle de conformité des importations (Certificat de Conformité) : seuil FOB.
SEUIL_CDC_FOB_XOF = 1_000_000

REGIMES_DOUANIERS = {
    "C100": "Mise à la consommation (régime général)",
    "E100": "Exportation définitive",
    "AT":   "Admission temporaire",
    "TR":   "Transit / Transbordement",
}

# Régimes où aucun droit ni aucune TVA n'est exigible à l'entrée du dossier.
REGIMES_SUSPENDUS = {
    "E100": "Exportation : droits et TVA non exigibles",
    "AT":   "Admission temporaire : droits et taxes suspendus (garantie à constituer)",
    "TR":   "Transit : droits et taxes suspendus jusqu'à la destination",
}

# Pièces d'un dossier de transit (liste de référence à adapter par le transitaire).
DOCUMENTS_DOSSIER = {
    "FACTURE":     "Facture commerciale",
    "BL":          "Connaissement (B/L) ou LTA",
    "COLISAGE":    "Liste de colisage",
    "FDI":         "FDI (Fiche de Déclaration d'Importation)",
    "BSC":         "BSC (Bordereau de Suivi des Cargaisons, OIC)",
    "CDC":         "Certificat de Conformité (CdC)",
    "DECLARATION": "Déclaration en douane enregistrée",
    "TRANSIT":     "Déclaration de transit (TI / TRIE)",
}
DOCUMENT_STATUTS = ("Reçu", "Exempté")

# Tranches de droits de douane du Tarif Extérieur Commun (information, non bloquant).
TRANCHES_DD = (0.0, 5.0, 10.0, 20.0, 35.0)

MODES_TAXE_SPECIFIQUE = {
    "POURCENT_CAF":      "Pourcentage de la valeur CAF",
    "MONTANT_PAR_UNITE": "Montant fixe par unité (kg, litre…)",
}

# Modèle de fichier pour l'import du tarif (les lignes « EXEMPLE » sont à remplacer).
MODELE_TARIF_CSV = (
    "code_sh;designation;dd;unite\n"
    "8471.30.00.00;EXEMPLE - Ordinateurs portables;5;unité\n"
    "8517.13.00.00;EXEMPLE - Smartphones;20;unité\n"
)

# Canaux de sélectivité douanière (moteur hybride de risque)
CANAUX = {
    "VERT":  "Contrôle documentaire allégé — dédouanement immédiat",
    "BLEU":  "Contrôle a posteriori — mainlevée rapide",
    "JAUNE": "Contrôle documentaire approfondi",
    "ROUGE": "Contrôle documentaire ET physique de la marchandise",
}

STATUTS_DOSSIER = [
    "En cours",
    "FDI & RFC Validées",
    "Visite Douanière en Cours",
    "Bon à Enlever (BAE) Émis",
    "Livré au Client",
]
STATUT_BAE = "Bon à Enlever (BAE) Émis"

# Sécurité des comptes
MOT_DE_PASSE_MIN = 10
CONNEXIONS_ECHECS_MAX = 5       # tentatives échouées tolérées…
CONNEXIONS_FENETRE_MIN = 15     # …sur cette fenêtre (minutes) avant blocage temporaire
MOTS_DE_PASSE_DEMO = {          # comptes créés au premier lancement (à changer)
    "admin": "admin123", "expert": "expert123", "collab": "collab123", "auditeur": "audit123",
}

ROLES = {
    "Administrateur Système":        "Accès total (gestion tenants, utilisateurs, clés)",
    "Expert-Comptable signataire":   "Validation comptable, états financiers, clôture",
    "Collaborateur":                 "Saisie comptable, transit, dossiers",
    "Auditeur externe":              "Lecture seule + piste d'audit",
    "Client final":                  "Portail : suivi de ses propres dossiers",
}

# ─── RBAC granulaire : permissions par rôle (format "<module>.<action>") ──────
PERMISSIONS = {
    "Administrateur Système": {"*"},
    "Expert-Comptable signataire": {
        "dashboard.view", "compta.view", "compta.saisie", "compta.valider",
        "compta.cloture", "etats.view", "fiscal.view", "fiscal.declarer",
        "transit.view", "transit.valider", "audit.view", "portail.view",
    },
    "Collaborateur": {
        "dashboard.view", "compta.view", "compta.saisie",
        "transit.view", "transit.creer", "transit.facturer",
        "douane.view", "douane.calculer", "ocr.view", "ocr.valider",
        "communication.rediger", "portail.view",
    },
    "Auditeur externe": {
        "dashboard.view", "compta.view", "etats.view", "audit.view",
        "transit.view", "fiscal.view", "portail.view",
    },
    "Client final": {
        "portail.view", "portail.dossier_suivi",
    },
}


def a_permission(role: str, permission: str) -> bool:
    perms = PERMISSIONS.get(role, set())
    return "*" in perms or permission in perms


# ══════════════════════════════════════════════════════════════════════════════
# SÉCURITÉ — secrets, chiffrement authentifié, hachage des mots de passe
# ══════════════════════════════════════════════════════════════════════════════
SECRET_PATTERN = re.compile(
    r"(sk-[A-Za-z0-9]{10,}|gsk_[A-Za-z0-9]{10,}|password|secret|api[_-]?key|token)",
    re.IGNORECASE,
)


def get_secret(name: str, default: str = "") -> str:
    """Récupère un secret depuis st.secrets puis les variables d'environnement.

    Ne lève jamais d'exception : retourne `default` si rien n'est trouvé.
    """
    try:
        value = st.secrets.get(name, default)  # type: ignore[union-attr]
        if value not in (None, ""):
            return str(value)
    except Exception:
        pass
    return os.getenv(name, default)


def rediger(texte: str) -> str:
    """Masque les secrets détectés avant écriture dans la piste d'audit."""
    if not texte:
        return ""
    return SECRET_PATTERN.sub("***", str(texte))


def _cle_chiffrement() -> bytes:
    """Dérive une clé 256 bits depuis ENCRYPTION_KEY (ou une clé locale stable)."""
    brut = get_secret("ENCRYPTION_KEY", "") or f"local::{DB_PATH}::{os.getuid()}"
    return hashlib.sha256(brut.encode("utf-8")).digest()


def _flux_chiffrant(cle: bytes, nonce: bytes, taille: int) -> bytes:
    """Génère un flux pseudo-aléatoire via HMAC-SHA256 (construction CTR)."""
    flux = bytearray()
    compteur = 0
    while len(flux) < taille:
        bloc = hmac.new(cle, nonce + compteur.to_bytes(8, "big"), hashlib.sha256).digest()
        flux.extend(bloc)
        compteur += 1
    return bytes(flux[:taille])


def chiffrer(clair: str) -> str:
    """Chiffre une donnée sensible (encrypt-then-MAC) et retourne du base64.

    Construction authentifiée : nonce aléatoire + chiffrement par flux
    HMAC-SHA256 + étiquette d'intégrité. Suffisant pour protéger les secrets
    stockés ; en production bancaire, remplacer par AES-256-GCM via la
    librairie `cryptography` (non requise ici pour rester portable).
    """
    if clair in (None, ""):
        return ""
    cle = _cle_chiffrement()
    nonce = os.urandom(16)
    donnees = str(clair).encode("utf-8")
    flux = _flux_chiffrant(cle, nonce, len(donnees))
    chiffre = bytes(a ^ b for a, b in zip(donnees, flux))
    tag = hmac.new(cle, nonce + chiffre, hashlib.sha256).digest()[:16]
    return base64.b64encode(nonce + tag + chiffre).decode("ascii")


def dechiffrer(charge: str) -> str:
    """Déchiffre une charge produite par `chiffrer`. Retourne "" si altérée."""
    if not charge:
        return ""
    try:
        brut = base64.b64decode(charge)
        nonce, tag, chiffre = brut[:16], brut[16:32], brut[32:]
        cle = _cle_chiffrement()
        if not hmac.compare_digest(tag, hmac.new(cle, nonce + chiffre, hashlib.sha256).digest()[:16]):
            return ""
        flux = _flux_chiffrant(cle, nonce, len(chiffre))
        return bytes(a ^ b for a, b in zip(chiffre, flux)).decode("utf-8")
    except Exception:
        return ""


def hash_mot_de_passe(mot_de_passe: str, sel: str | None = None) -> tuple[str, str]:
    """Hache un mot de passe. Priorité Argon2 ; repli PBKDF2-HMAC-SHA256.

    Retourne (empreinte, sel). Le sel n'est utile qu'en mode PBKDF2 (Argon2
    embarque son propre sel).
    """
    if ARGON2_OK:
        return argon2.hash(mot_de_passe), ""
    sel = sel or base64.b64encode(os.urandom(16)).decode("ascii")
    derive = hashlib.pbkdf2_hmac("sha256", mot_de_passe.encode(), sel.encode(), 200_000)
    return base64.b64encode(derive).decode("ascii"), sel


def verifier_mot_de_passe(mot_de_passe: str, empreinte: str, sel: str = "") -> bool:
    """Vérifie un mot de passe contre son empreinte stockée."""
    if not empreinte:
        return False
    try:
        if empreinte.startswith("$argon2"):
            return bool(argon2.verify(mot_de_passe, empreinte)) if ARGON2_OK else False
        derive = hashlib.pbkdf2_hmac("sha256", mot_de_passe.encode(), sel.encode(), 200_000)
        return hmac.compare_digest(base64.b64encode(derive).decode("ascii"), empreinte)
    except Exception:
        return False


def empreinte_sha256(*parties: object) -> str:
    """Empreinte SHA-256 déterministe (scellement de documents, audit)."""
    h = hashlib.sha256()
    for partie in parties:
        h.update(str(partie).encode("utf-8"))
        h.update(b"|")
    return h.hexdigest()


def maintenant() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def ip_client() -> str:
    """Récupère l'adresse IP de l'utilisateur (contexte Streamlit / proxy)."""
    try:
        entetes = st.context.headers  # type: ignore[attr-defined]
        for cle in ("X-Forwarded-For", "X-Real-Ip", "Remote-Addr"):
            if cle in entetes:
                return str(entetes[cle]).split(",")[0].strip()
    except Exception:
        pass
    return "127.0.0.1"


# ══════════════════════════════════════════════════════════════════════════════
# COUCHE BASE DE DONNÉES (SQLite local ; portage PostgreSQL via SQLAlchemy)
# ══════════════════════════════════════════════════════════════════════════════
def connexion() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def executer(sql: str, params: tuple = ()) -> None:
    with connexion() as conn:
        conn.execute(sql, params)


def lire_df(sql: str, params: tuple = ()) -> pd.DataFrame:
    with connexion() as conn:
        return pd.read_sql_query(sql, conn, params=params)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS tenants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT UNIQUE NOT NULL,
    raison_sociale TEXT NOT NULL,
    pays TEXT DEFAULT 'Côte d''Ivoire',
    regime_fiscal TEXT DEFAULT 'Réel normal',
    actif INTEGER DEFAULT 1,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS utilisateurs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL,
    username TEXT NOT NULL,
    empreinte TEXT NOT NULL,
    sel TEXT,
    role TEXT NOT NULL,
    email TEXT,
    telephone TEXT,
    actif INTEGER DEFAULT 1,
    created_at TEXT,
    UNIQUE(tenant_id, username),
    FOREIGN KEY(tenant_id) REFERENCES tenants(id)
);
CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER,
    ts TEXT NOT NULL,
    username TEXT NOT NULL,
    role TEXT,
    ip TEXT,
    action TEXT NOT NULL,
    entite TEXT,
    entite_id TEXT,
    details TEXT,
    empreinte_precedente TEXT,
    empreinte TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS plan_comptable (
    compte TEXT PRIMARY KEY,
    libelle TEXT NOT NULL,
    classe TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS journaux (code TEXT PRIMARY KEY, libelle TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS ecritures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL,
    piece TEXT NOT NULL,
    date_ecriture TEXT NOT NULL,
    journal TEXT NOT NULL,
    compte TEXT NOT NULL,
    libelle TEXT,
    debit REAL DEFAULT 0,
    credit REAL DEFAULT 0,
    lettrage TEXT,
    created_by TEXT,
    created_at TEXT
);
"""

_SCHEMA += """
CREATE TABLE IF NOT EXISTS articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER,
    nom TEXT NOT NULL,
    sh TEXT NOT NULL,
    dd REAL NOT NULL DEFAULT 0,
    categorie TEXT,
    UNIQUE(tenant_id, nom)
);
CREATE TABLE IF NOT EXISTS manifestes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL,
    numero TEXT NOT NULL,
    navire TEXT,
    armateur TEXT,
    port TEXT DEFAULT 'Abidjan',
    date_arrivee TEXT,
    statut TEXT DEFAULT 'Ouvert',
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS connaissements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL,
    manifeste_id INTEGER,
    bl TEXT NOT NULL,
    client TEXT,
    nb_colis INTEGER DEFAULT 0,
    poids_kg REAL DEFAULT 0,
    valeur_usd REAL DEFAULT 0,
    date_franchise TEXT,
    apure INTEGER DEFAULT 0,
    date_apurement TEXT,
    FOREIGN KEY(manifeste_id) REFERENCES manifestes(id)
);
CREATE TABLE IF NOT EXISTS dossiers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL,
    reference TEXT NOT NULL,
    date TEXT NOT NULL,
    client TEXT NOT NULL,
    bl TEXT,
    article TEXT,
    regime TEXT DEFAULT 'C100',
    fob_xof REAL DEFAULT 0,
    fret_xof REAL DEFAULT 0,
    assurance_xof REAL DEFAULT 0,
    valeur_caf_xof REAL DEFAULT 0,
    droits_douane REAL DEFAULT 0,
    tva REAL DEFAULT 0,
    total_facture REAL DEFAULT 0,
    solde_du REAL DEFAULT 0,
    statut TEXT DEFAULT 'En cours',
    canal_risque TEXT,
    score_risque REAL DEFAULT 0,
    email TEXT,
    telephone TEXT,
    observation TEXT,
    created_at TEXT,
    UNIQUE(tenant_id, reference)
);
CREATE TABLE IF NOT EXISTS surestaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL,
    bl TEXT NOT NULL,
    jours_franchise INTEGER DEFAULT 0,
    jours_retard INTEGER DEFAULT 0,
    penalite_jour_usd REAL DEFAULT 0,
    taux_change REAL DEFAULT 1,
    montant_xof REAL DEFAULT 0,
    date_calcul TEXT,
    created_by TEXT
);
CREATE TABLE IF NOT EXISTS taux_change (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    devise TEXT NOT NULL,
    taux_vers_xof REAL NOT NULL,
    source TEXT,
    date_maj TEXT
);
CREATE TABLE IF NOT EXISTS bae_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL,
    dossier_id INTEGER,
    numero TEXT NOT NULL,
    empreinte_sha256 TEXT NOT NULL,
    emis_par TEXT,
    emis_at TEXT,
    FOREIGN KEY(dossier_id) REFERENCES dossiers(id)
);
CREATE TABLE IF NOT EXISTS declarations_tva (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL,
    periode TEXT NOT NULL,
    tva_collectee REAL DEFAULT 0,
    tva_deductible REAL DEFAULT 0,
    tva_a_payer REAL DEFAULT 0,
    taux REAL DEFAULT 18,
    statut TEXT DEFAULT 'Brouillon',
    created_by TEXT,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS communications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL,
    type TEXT,
    destinataire TEXT,
    email_destinataire TEXT,
    objet TEXT,
    corps TEXT,
    statut_validation TEXT DEFAULT 'En attente',
    valide_par TEXT,
    valide_at TEXT,
    statut_envoi TEXT DEFAULT 'Non envoyée',
    envoyee_at TEXT,
    created_by TEXT,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS ocr_extractions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL,
    fichier TEXT,
    fournisseur TEXT,
    montant_declare REAL DEFAULT 0,
    montant_extrait REAL DEFAULT 0,
    ecart_pct REAL DEFAULT 0,
    discordance INTEGER DEFAULT 0,
    details TEXT,
    created_by TEXT,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS releves_bancaires (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL,
    banque TEXT,
    compte TEXT DEFAULT '521000',
    date_operation TEXT,
    libelle TEXT,
    reference TEXT,
    debit REAL DEFAULT 0,
    credit REAL DEFAULT 0,
    devise TEXT DEFAULT 'XOF',
    rapproche INTEGER DEFAULT 0,
    ecriture_id INTEGER,
    importe_le TEXT
);
CREATE TABLE IF NOT EXISTS dossier_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL,
    dossier_id INTEGER NOT NULL,
    code TEXT NOT NULL,
    reference TEXT,
    statut TEXT NOT NULL DEFAULT 'Reçu',
    created_by TEXT,
    created_at TEXT,
    UNIQUE(tenant_id, dossier_id, code),
    FOREIGN KEY(dossier_id) REFERENCES dossiers(id)
);
CREATE TABLE IF NOT EXISTS tarif_douanier (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL,
    code_sh TEXT NOT NULL,
    designation TEXT,
    dd REAL NOT NULL DEFAULT 0,
    unite TEXT,
    UNIQUE(tenant_id, code_sh)
);
CREATE TABLE IF NOT EXISTS taxes_specifiques (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL,
    prefixe_sh TEXT NOT NULL,
    libelle TEXT NOT NULL,
    mode TEXT NOT NULL,
    valeur REAL NOT NULL,
    unite TEXT,
    UNIQUE(tenant_id, prefixe_sh, libelle)
);
"""


def init_db() -> None:
    """Crée le schéma et insère le jeu de données professionnel (idempotent)."""
    with connexion() as conn:
        conn.executescript(_SCHEMA)
    _migrer_schema()
    _seed_plan_comptable()
    _seed_journaux()
    _seed_tenant_demo()


# Colonnes ajoutées après la première mise en production : la migration est
# idempotente et s'applique sans perte de données aux bases déjà existantes.
_MIGRATIONS_COLONNES = {
    "dossiers": [
        ("code_sh", "TEXT"),
        ("quantite", "REAL DEFAULT 0"),
        ("taxes_specifiques", "REAL DEFAULT 0"),
    ],
    "communications": [
        ("email_destinataire", "TEXT"),
        ("statut_envoi", "TEXT DEFAULT 'Non envoyée'"),
        ("envoyee_at", "TEXT"),
    ],
}


def _migrer_schema() -> None:
    """Ajoute les colonnes manquantes aux bases existantes (sans perte de données)."""
    with connexion() as conn:
        for table, colonnes in _MIGRATIONS_COLONNES.items():
            existantes = {ligne["name"] for ligne in conn.execute(f"PRAGMA table_info({table})")}
            for nom, definition in colonnes:
                if nom not in existantes:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {nom} {definition}")


def _seed_plan_comptable() -> None:
    plan = [
        ("101000", "Capital social", "1"),
        ("120000", "Résultat de l'exercice", "1"),
        ("161000", "Emprunts auprès des établissements de crédit", "1"),
        ("211000", "Immobilisations incorporelles", "2"),
        ("241000", "Matériel et outillage", "2"),
        ("245000", "Matériel de transport", "2"),
        ("311000", "Marchandises", "3"),
        ("401000", "Fournisseurs", "4"),
        ("411000", "Clients", "4"),
        ("421000", "Personnel — rémunérations dues", "4"),
        ("445200", "TVA due (collectée)", "4"),
        ("445220", "TVA déductible sur achats", "4"),
        ("447000", "État — IS/BIC", "4"),
        ("447100", "État — droits de douane à payer", "4"),
        ("521000", "Banques locales", "5"),
        ("571000", "Caisse", "5"),
        ("601000", "Achats de marchandises", "6"),
        ("604000", "Achats stockés — fournitures", "6"),
        ("611000", "Transports sur achats (fret)", "6"),
        ("614000", "Transports sur ventes", "6"),
        ("622000", "Rémunérations d'intermédiaires (transit)", "6"),
        ("626000", "Frais postaux et télécommunications", "6"),
        ("628000", "Divers services extérieurs (surestaries)", "6"),
        ("631000", "Frais bancaires", "6"),
        ("635000", "Impôts et taxes", "6"),
        ("641000", "Rémunérations du personnel", "6"),
        ("701000", "Ventes de marchandises", "7"),
        ("706000", "Prestations de services (honoraires transit)", "7"),
        ("771000", "Produits financiers", "7"),
    ]
    with connexion() as conn:
        conn.executemany(
            "INSERT OR IGNORE INTO plan_comptable (compte, libelle, classe) VALUES (?,?,?)", plan
        )


def _seed_journaux() -> None:
    journaux = [
        ("ACQ", "Journal des Achats"),
        ("VTE", "Journal des Ventes"),
        ("BAN", "Journal de Banque / Trésorerie"),
        ("OD", "Journal des Opérations Diverses"),
    ]
    with connexion() as conn:
        conn.executemany("INSERT OR IGNORE INTO journaux (code, libelle) VALUES (?,?)", journaux)


def _seed_tenant_demo() -> None:
    """Crée un tenant de démonstration complet (utilisateurs, articles, dossiers)."""
    with connexion() as conn:
        if conn.execute("SELECT COUNT(*) FROM tenants").fetchone()[0]:
            return
        ts = maintenant()
        cur = conn.execute(
            "INSERT INTO tenants (slug, raison_sociale, pays, regime_fiscal, created_at)"
            " VALUES (?,?,?,?,?)",
            ("demo-ci", "Cabinet Excellence Comptable CI", "Côte d'Ivoire", "Réel normal", ts),
        )
        tenant_id = cur.lastrowid
        for username, mdp, role, email in [
            ("admin", "admin123", "Administrateur Système", "admin@excellence.ci"),
            ("expert", "expert123", "Expert-Comptable signataire", "expert@excellence.ci"),
            ("collab", "collab123", "Collaborateur", "collab@excellence.ci"),
            ("auditeur", "audit123", "Auditeur externe", "audit@cabinet.ci"),
        ]:
            empreinte, sel = hash_mot_de_passe(mdp)
            conn.execute(
                "INSERT INTO utilisateurs (tenant_id, username, empreinte, sel, role, email, created_at)"
                " VALUES (?,?,?,?,?,?,?)",
                (tenant_id, username, empreinte, sel, role, email, ts),
            )
        conn.executemany(
            "INSERT OR IGNORE INTO articles (tenant_id, nom, sh, dd, categorie) VALUES (?,?,?,?,?)",
            [
                (tenant_id, "Station totale topographique GNSS/GPS", "9015.80.00", 5.0, "Topographie"),
                (tenant_id, "Smartphones & téléphones portables", "8517.13.00", 20.0, "High-Tech"),
                (tenant_id, "Ordinateurs portables & tablettes", "8471.30.00", 5.0, "Informatique"),
                (tenant_id, "Groupes électrogènes diesel", "8502.13.00", 10.0, "Énergie"),
                (tenant_id, "Tissus de coton imprimés", "5208.52.00", 20.0, "Textile"),
            ],
        )
        dossiers = [
            ("IMP-2025-001", "SARL IvoirTech", "MAEU1234567", "Ordinateurs portables & tablettes",
             "C100", 12_500_000, 1_250_000, 250_000, 14_000_000, 700_000, 2_520_000,
             17_220_000, 17_220_000, "En cours", "JAUNE", 42.0),
            ("IMP-2025-002", "Groupe Bâtir SA", "COSCO9988776", "Groupes électrogènes diesel",
             "C100", 28_000_000, 2_800_000, 560_000, 31_360_000, 3_136_000, 5_644_800,
             40_140_800, 15_000_000, "Bon à Enlever (BAE) Émis", "ROUGE", 71.0),
        ]
        for d in dossiers:
            conn.execute(
                "INSERT OR IGNORE INTO dossiers (tenant_id, reference, date, client, bl, article,"
                " regime, fob_xof, fret_xof, assurance_xof, valeur_caf_xof, droits_douane, tva,"
                " total_facture, solde_du, statut, canal_risque, score_risque, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (tenant_id, d[0], date.today().strftime("%Y-%m-%d"), *d[1:], ts),
            )
        conn.executemany(
            "INSERT INTO taux_change (devise, taux_vers_xof, source, date_maj) VALUES (?,?,?,?)",
            [("XOF", 1.0, "fixe", ts), ("USD", 605.0, "défaut", ts),
             ("EUR", 655.957, "fixe UEMOA", ts), ("CNY", 84.0, "défaut", ts)],
        )


# ══════════════════════════════════════════════════════════════════════════════
# PISTE D'AUDIT IMMUABLE (chaîne de hachage append-only)
# ══════════════════════════════════════════════════════════════════════════════
def journaliser(
    action: str,
    entite: str = "",
    entite_id: str = "",
    details: str = "",
    username: str | None = None,
    role: str | None = None,
    tenant_id: int | None = None,
) -> str:
    """Enregistre un événement dans la piste d'audit immuable.

    Chaque ligne embarque l'empreinte de la ligne précédente : toute
    modification ou suppression rétroactive casse la chaîne, ce que
    `verifier_audit()` détecte immédiatement (exigence contrôle fiscal /
    audit bancaire).
    """
    username = username or st.session_state.get("username", "système")
    role = role or st.session_state.get("user_role", "")
    if tenant_id is None:
        tenant_id = st.session_state.get("tenant_id")
    with connexion() as conn:
        precedente = conn.execute(
            "SELECT empreinte FROM audit_logs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        empreinte_precedente = precedente["empreinte"] if precedente else "GENESE"
        ts = maintenant()
        ip = ip_client()
        action = rediger(action)
        details = rediger(details)
        empreinte = empreinte_sha256(
            ts, username, role, ip, action, entite, entite_id, details, empreinte_precedente
        )
        conn.execute(
            "INSERT INTO audit_logs (tenant_id, ts, username, role, ip, action, entite,"
            " entite_id, details, empreinte_precedente, empreinte)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (tenant_id, ts, username, role, ip, action, entite, entite_id, details,
             empreinte_precedente, empreinte),
        )
    return empreinte


def verifier_audit() -> tuple[bool, int, str]:
    """Vérifie l'intégrité de la chaîne d'audit.

    Retourne (valide, nb_lignes, message). Détecte toute altération,
    insertion ou suppression hors application.
    """
    with connexion() as conn:
        lignes = conn.execute(
            "SELECT ts, username, role, ip, action, entite, entite_id, details,"
            " empreinte_precedente, empreinte FROM audit_logs ORDER BY id ASC"
        ).fetchall()
    precedente = "GENESE"
    for index, ligne in enumerate(lignes, start=1):
        attendue = empreinte_sha256(
            ligne["ts"], ligne["username"], ligne["role"], ligne["ip"], ligne["action"],
            ligne["entite"], ligne["entite_id"], ligne["details"], precedente,
        )
        if not hmac.compare_digest(attendue, ligne["empreinte"]):
            return False, len(lignes), f"⚠️ Rupture de chaîne détectée à la ligne {index}."
        if not hmac.compare_digest(ligne["empreinte_precedente"], precedente):
            return False, len(lignes), f"⚠️ Maillon incohérent à la ligne {index}."
        precedente = ligne["empreinte"]
    return True, len(lignes), "✅ Piste d'audit intègre — aucun maillon rompu."


# ══════════════════════════════════════════════════════════════════════════════
# MULTI-TENANT : isolation stricte des données par entreprise cliente
# ══════════════════════════════════════════════════════════════════════════════
def lister_tenants() -> pd.DataFrame:
    return lire_df(
        "SELECT id, slug, raison_sociale, pays, regime_fiscal, actif FROM tenants ORDER BY id"
    )


def creer_tenant(slug: str, raison_sociale: str, pays: str = "Côte d'Ivoire",
                 regime_fiscal: str = "Réel normal") -> int:
    with connexion() as conn:
        cur = conn.execute(
            "INSERT INTO tenants (slug, raison_sociale, pays, regime_fiscal, created_at)"
            " VALUES (?,?,?,?,?)",
            (slug.strip().lower(), raison_sociale.strip(), pays, regime_fiscal, maintenant()),
        )
        tenant_id = cur.lastrowid
    journaliser("tenant_creation", "tenants", str(tenant_id), f"slug={slug}")
    return tenant_id


def creer_utilisateur(tenant_id: int, username: str, mot_de_passe: str, role: str,
                      email: str = "", telephone: str = "") -> int:
    empreinte, sel = hash_mot_de_passe(mot_de_passe)
    with connexion() as conn:
        cur = conn.execute(
            "INSERT INTO utilisateurs (tenant_id, username, empreinte, sel, role, email,"
            " telephone, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (tenant_id, username.strip(), empreinte, sel, role, email, telephone, maintenant()),
        )
        user_id = cur.lastrowid
    journaliser("utilisateur_creation", "utilisateurs", str(user_id),
                f"username={username}; role={role}")
    return user_id


def valider_mot_de_passe(mot_de_passe: str) -> None:
    """Politique minimale : longueur, lettres ET chiffres, pas un mot de passe de démo."""
    if len(mot_de_passe) < MOT_DE_PASSE_MIN:
        raise ValueError(f"Le mot de passe doit contenir au moins {MOT_DE_PASSE_MIN} caractères.")
    if not (re.search(r"[A-Za-z]", mot_de_passe) and re.search(r"\d", mot_de_passe)):
        raise ValueError("Le mot de passe doit contenir des lettres ET des chiffres.")
    if mot_de_passe in MOTS_DE_PASSE_DEMO.values():
        raise ValueError("Ce mot de passe est celui de la démonstration : choisissez-en un autre.")


def definir_mot_de_passe(tenant_id: int, username: str, nouveau: str) -> None:
    """Remplace le mot de passe d'un utilisateur (réinitialisation par l'administrateur)."""
    valider_mot_de_passe(nouveau)
    empreinte, sel = hash_mot_de_passe(nouveau)
    with connexion() as conn:
        cur = conn.execute(
            "UPDATE utilisateurs SET empreinte=?, sel=? WHERE tenant_id=? AND username=?",
            (empreinte, sel, tenant_id, username.strip()),
        )
        if cur.rowcount == 0:
            raise ValueError("Utilisateur introuvable.")
    journaliser("mot_de_passe_modifie", "utilisateurs", username.strip(), "",
                tenant_id=tenant_id)


def changer_mon_mot_de_passe(ancien: str, nouveau: str) -> None:
    """Changement de mot de passe par l'utilisateur connecté (ancien mot de passe exigé)."""
    tenant_id = tenant_courant()
    username = st.session_state.get("username", "")
    with connexion() as conn:
        ligne = conn.execute(
            "SELECT empreinte, sel FROM utilisateurs WHERE tenant_id=? AND username=? AND actif=1",
            (tenant_id, username),
        ).fetchone()
    if not ligne or not verifier_mot_de_passe(ancien, ligne["empreinte"], ligne["sel"] or ""):
        raise ValueError("Mot de passe actuel incorrect.")
    definir_mot_de_passe(tenant_id, username, nouveau)


def comptes_mot_de_passe_demo() -> list[str]:
    """Utilisateurs du tenant courant qui ont encore le mot de passe de la démonstration."""
    comptes = lire_df(
        "SELECT username, empreinte, sel FROM utilisateurs WHERE tenant_id=? AND actif=1",
        (tenant_courant(),),
    )
    return [ligne["username"] for _, ligne in comptes.iterrows()
            if ligne["username"] in MOTS_DE_PASSE_DEMO
            and verifier_mot_de_passe(MOTS_DE_PASSE_DEMO[ligne["username"]],
                                      ligne["empreinte"], ligne["sel"] or "")]


def connexion_bloquee(tenant_id: int, username: str) -> bool:
    """Vrai si trop de connexions ont échoué récemment (depuis la dernière réussite)."""
    limite = (datetime.now() - timedelta(minutes=CONNEXIONS_FENETRE_MIN)).strftime(
        "%Y-%m-%d %H:%M:%S")
    with connexion() as conn:
        echecs = conn.execute(
            "SELECT COUNT(*) FROM audit_logs WHERE action='login_echec' AND username=?"
            " AND tenant_id=? AND ts>=? AND id > COALESCE((SELECT MAX(id) FROM audit_logs"
            " WHERE action='login_reussi' AND username=? AND tenant_id=?), 0)",
            (username.strip(), tenant_id, limite, username.strip(), tenant_id),
        ).fetchone()[0]
    return echecs >= CONNEXIONS_ECHECS_MAX


def authentifier(tenant_id: int, username: str, mot_de_passe: str) -> dict | None:
    """Authentifie un utilisateur dans le tenant donné. Retourne sa fiche ou None."""
    if connexion_bloquee(tenant_id, username):
        journaliser("login_bloque", "utilisateurs", username, "trop de tentatives échouées",
                    username=username, tenant_id=tenant_id)
        return None
    with connexion() as conn:
        ligne = conn.execute(
            "SELECT * FROM utilisateurs WHERE tenant_id=? AND username=? AND actif=1",
            (tenant_id, username.strip()),
        ).fetchone()
    if not ligne:
        journaliser("login_echec", "utilisateurs", username, "utilisateur inconnu",
                    username=username, tenant_id=tenant_id)
        return None
    if not verifier_mot_de_passe(mot_de_passe, ligne["empreinte"], ligne["sel"] or ""):
        journaliser("login_echec", "utilisateurs", str(ligne["id"]), "mot de passe invalide",
                    username=username, tenant_id=tenant_id)
        return None
    journaliser("login_reussi", "utilisateurs", str(ligne["id"]), f"role={ligne['role']}",
                username=username, role=ligne["role"], tenant_id=tenant_id)
    return dict(ligne)


def tenant_courant() -> int:
    """Identifiant du tenant actif — toutes les requêtes métier y sont filtrées."""
    return int(st.session_state.get("tenant_id", 0))


# ══════════════════════════════════════════════════════════════════════════════
# MOTEUR COMPTABLE SYSCOHADA RÉVISÉ (partie double stricte)
# ══════════════════════════════════════════════════════════════════════════════
class ErreurComptable(Exception):
    """Levée lorsqu'une écriture viole les règles de la partie double."""


def ecrire_piece(
    piece: str,
    journal: str,
    lignes: list[tuple[str, str, float, float]],
    date_ecriture: str | None = None,
    created_by: str | None = None,
) -> str:
    """Enregistre une pièce comptable équilibrée (Débit = Crédit).

    `lignes` : liste de tuples (compte, libellé, débit, crédit).
    Lève ErreurComptable si l'écriture n'est pas équilibrée ou si un compte
    est inconnu du plan comptable — garantie d'intégrité exigée par un
    logiciel comptable professionnel.
    """
    total_debit = round(sum(ligne[2] for ligne in lignes), 2)
    total_credit = round(sum(ligne[3] for ligne in lignes), 2)
    if round(total_debit - total_credit, 2) != 0:
        raise ErreurComptable(
            f"Écriture non équilibrée : débit {total_debit:,.2f} ≠ crédit {total_credit:,.2f}"
        )
    if total_debit == 0:
        raise ErreurComptable("Écriture vide : aucun mouvement à enregistrer.")
    comptes_connus = set(lire_df("SELECT compte FROM plan_comptable")["compte"].tolist())
    inconnus = {ligne[0] for ligne in lignes} - comptes_connus
    if inconnus:
        raise ErreurComptable(f"Comptes absents du plan comptable : {', '.join(sorted(inconnus))}")

    tenant = tenant_courant()
    date_ecriture = date_ecriture or date.today().strftime("%Y-%m-%d")
    auteur = created_by or st.session_state.get("username", "système")
    ts = maintenant()
    with connexion() as conn:
        for compte, libelle, debit, credit in lignes:
            conn.execute(
                "INSERT INTO ecritures (tenant_id, piece, date_ecriture, journal, compte, libelle,"
                " debit, credit, created_by, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (tenant, piece, date_ecriture, journal, compte, libelle, round(debit, 2),
                 round(credit, 2), auteur, ts),
            )
    journaliser("ecriture_comptable", "ecritures", piece,
                f"journal={journal}; debit={total_debit:,.2f}")
    return piece


def comptes_par_prefixe(prefixe: str) -> list[str]:
    df = lire_df(
        "SELECT compte FROM plan_comptable WHERE compte LIKE ? ORDER BY compte", (f"{prefixe}%",)
    )
    return df["compte"].tolist()


def solde_compte(compte: str) -> float:
    """Solde débiteur positif / créditeur négatif d'un compte (tenant courant)."""
    df = lire_df(
        "SELECT COALESCE(SUM(debit),0) AS d, COALESCE(SUM(credit),0) AS c FROM ecritures"
        " WHERE tenant_id=? AND compte=?",
        (tenant_courant(), compte),
    )
    return float(df.iloc[0]["d"]) - float(df.iloc[0]["c"])


def solde_prefixe(prefixe: str) -> float:
    df = lire_df(
        "SELECT COALESCE(SUM(debit),0) AS d, COALESCE(SUM(credit),0) AS c FROM ecritures"
        " WHERE tenant_id=? AND compte LIKE ?",
        (tenant_courant(), f"{prefixe}%"),
    )
    return float(df.iloc[0]["d"]) - float(df.iloc[0]["c"])


def balance_generale() -> pd.DataFrame:
    """Balance Générale SYSCOHADA : mouvements et soldes par compte."""
    df = lire_df(
        "SELECT e.compte, p.libelle, p.classe, COALESCE(SUM(e.debit),0) AS debit,"
        " COALESCE(SUM(e.credit),0) AS credit FROM ecritures e"
        " LEFT JOIN plan_comptable p ON p.compte = e.compte"
        " WHERE e.tenant_id=? GROUP BY e.compte ORDER BY e.compte",
        (tenant_courant(),),
    )
    if df.empty:
        return df
    df["solde_debiteur"] = (df["debit"] - df["credit"]).clip(lower=0).round(2)
    df["solde_crediteur"] = (df["credit"] - df["debit"]).clip(lower=0).round(2)
    return df


def grand_livre(compte: str) -> pd.DataFrame:
    return lire_df(
        "SELECT piece, date_ecriture, journal, libelle, debit, credit, created_by FROM ecritures"
        " WHERE tenant_id=? AND compte=? ORDER BY date_ecriture, id",
        (tenant_courant(), compte),
    )


def journal_ecritures(code_journal: str) -> pd.DataFrame:
    return lire_df(
        "SELECT piece, date_ecriture, compte, libelle, debit, credit, created_by FROM ecritures"
        " WHERE tenant_id=? AND journal=? ORDER BY date_ecriture, id",
        (tenant_courant(), code_journal),
    )


def etats_financiers() -> dict:
    """Compte de résultat et bilan synthétique dérivés de la comptabilité.

    Les comptes de charges (classe 6) et de produits (classe 7) alimentent le
    compte de résultat ; les classes 1 à 5 alimentent le bilan.
    """
    charges = lire_df(
        "SELECT COALESCE(SUM(debit-credit),0) AS v FROM ecritures WHERE tenant_id=?"
        " AND compte LIKE '6%'", (tenant_courant(),),
    ).iloc[0]["v"]
    produits = lire_df(
        "SELECT COALESCE(SUM(credit-debit),0) AS v FROM ecritures WHERE tenant_id=?"
        " AND compte LIKE '7%'", (tenant_courant(),),
    ).iloc[0]["v"]
    resultat = round(float(produits) - float(charges), 2)
    actif_immobilise = round(solde_prefixe("2"), 2)
    stocks = round(solde_prefixe("3"), 2)
    creances = round(solde_prefixe("41"), 2)
    tresorerie = round(solde_prefixe("5"), 2)
    dettes = round(-(solde_prefixe("40") + solde_prefixe("44") + solde_prefixe("42")), 2)
    capitaux = round(-solde_prefixe("1"), 2)
    return {
        "charges": round(float(charges), 2),
        "produits": round(float(produits), 2),
        "resultat": resultat,
        "actif": {
            "Immobilisations (classe 2)": actif_immobilise,
            "Stocks (classe 3)": stocks,
            "Créances clients (41)": creances,
            "Trésorerie (classe 5)": tresorerie,
            "TOTAL ACTIF": round(actif_immobilise + stocks + creances + tresorerie, 2),
        },
        "passif": {
            "Capitaux propres (classe 1)": capitaux,
            "Résultat de l'exercice": resultat,
            "Dettes fournisseurs/État/personnel": dettes,
            "TOTAL PASSIF": round(capitaux + resultat + dettes, 2),
        },
    }


# ─── Automatisation des flux : chaque opération génère ses écritures ──────────
def ecritures_depuis_debours(piece: str, libelle: str, montant_xof: float, regime: str = "C100",
                             date_ecriture: str | None = None) -> None:
    """Débours douaniers payés pour le compte du client (débit 447100, crédit banque).

    Les droits et taxes réglés à la douane pour le compte du client transitent
    par le compte d'État 447100 puis sont refacturés au client.
    """
    ecrire_piece(
        piece=f"DOU-{piece}", journal="OD",
        lignes=[
            ("447100", f"{libelle} — droits et taxes ({regime})", montant_xof, 0.0),
            ("521000", f"Paiement débours douaniers {piece}", 0.0, montant_xof),
        ],
        date_ecriture=date_ecriture,
    )


def ecritures_frais_transit(piece: str, honoraires_ht: float, debours_douaniers: float = 0.0,
                           fret: float = 0.0, surestaries: float = 0.0,
                           taux_tva: float = TAUX_TVA, client: str = "CLIENT",
                           date_ecriture: str | None = None) -> str:
    """Facture transitaire : ventile débours, fret, surestaries et honoraires.

    Les débours douaniers sont refacturés en hors taxes (débours = avance de
    fonds), seuls les honoraires supportent la TVA — conformément à la
    pratique des cabinets de transit ivoiriens.
    """
    tva = round(honoraires_ht * taux_tva / 100.0, 2)
    total_ht = round(honoraires_ht + debours_douaniers + fret + surestaries, 2)
    total_ttc = round(total_ht + tva, 2)
    lignes = [
        ("411000", f"Client {client} — facture transit {piece}", total_ttc, 0.0),
        ("447100", f"Débours douaniers refacturés {piece}", 0.0, round(debours_douaniers, 2)),
        ("611000", f"Fret refacturé {piece}", 0.0, round(fret, 2)),
        ("628000", f"Surestaries refacturées {piece}", 0.0, round(surestaries, 2)),
        ("706000", f"Honoraires de transit {piece}", 0.0, round(honoraires_ht, 2)),
        ("445200", f"TVA collectée sur honoraires {piece}", 0.0, tva),
    ]
    lignes = [ligne for ligne in lignes if ligne[2] or ligne[3]]
    ecrire_piece(piece=f"FTR-{piece}", journal="VTE", lignes=lignes, date_ecriture=date_ecriture)
    return f"FTR-{piece}"


def ecritures_surestaries(piece: str, montant_xof: float, armateur: str = "Armateur",
                          date_ecriture: str | None = None) -> str:
    """Surestaries portuaires payées à l'armateur (charge 628000 / banque)."""
    ecrire_piece(
        piece=f"SUR-{piece}", journal="OD",
        lignes=[
            ("628000", f"Surestaries portuaires — {armateur} ({piece})", montant_xof, 0.0),
            ("521000", f"Règlement surestaries {piece}", 0.0, montant_xof),
        ],
        date_ecriture=date_ecriture,
    )
    return f"SUR-{piece}"


def ecritures_quittance_caisse(piece: str, montant_xof: float, compte_tresorerie: str = "571000",
                              date_ecriture: str | None = None) -> str:
    """Encaisse une quittance de caisse (augmente la trésorerie, solde le client)."""
    ecrire_piece(
        piece=f"CAI-{piece}", journal="BAN",
        lignes=[
            (compte_tresorerie, f"Encaissement quittance {piece}", montant_xof, 0.0),
            ("411000", f"Règlement client sur quittance {piece}", 0.0, montant_xof),
        ],
        date_ecriture=date_ecriture,
    )
    return f"CAI-{piece}"


def ecritures_achat_import(piece: str, valeur_caf_xof: float, droits: float,
                           date_ecriture: str | None = None) -> str:
    """Entrée en stock d'une importation (311000) et constatation des droits."""
    ecrire_piece(
        piece=f"IMP-{piece}", journal="ACQ",
        lignes=[
            ("311000", f"Entrée en stock import {piece}", round(valeur_caf_xof, 2), 0.0),
            ("447100", f"Droits de douane import {piece}", round(droits, 2), 0.0),
            ("401000", f"Fournisseur étranger {piece}", 0.0, round(valeur_caf_xof, 2)),
            ("521000", f"Règlement droits douane {piece}", 0.0, round(droits, 2)),
        ],
        date_ecriture=date_ecriture,
    )
    return f"IMP-{piece}"


# ══════════════════════════════════════════════════════════════════════════════
# FISCALITÉ : TVA et IS / BIC
# ══════════════════════════════════════════════════════════════════════════════
def calculer_tva() -> dict:
    """TVA collectée / déductible / à payer, dérivée des comptes 4452xx."""
    collectee = abs(solde_compte("445200"))
    deductible = abs(solde_compte("445220"))
    return {
        "tva_collectee": round(collectee, 2),
        "tva_deductible": round(deductible, 2),
        "tva_a_payer": round(collectee - deductible, 2),
    }


def enregistrer_declaration_tva(periode: str, taux: float = TAUX_TVA) -> dict:
    calcul = calculer_tva()
    executer(
        "INSERT INTO declarations_tva (tenant_id, periode, tva_collectee, tva_deductible,"
        " tva_a_payer, taux, statut, created_by, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (tenant_courant(), periode, calcul["tva_collectee"], calcul["tva_deductible"],
         calcul["tva_a_payer"], taux, "Brouillon", st.session_state.get("username", "système"),
         maintenant()),
    )
    journaliser("declaration_tva", "declarations_tva", periode,
                f"tva_a_payer={calcul['tva_a_payer']:,.2f}")
    return calcul


def calculer_is(taux: float = TAUX_IS_DEFAUT) -> dict:
    """IS/BIC : assiette = produits (7) - charges (6) de l'exercice."""
    etats = etats_financiers()
    resultat_fiscal = etats["resultat"]
    is_du = round(max(resultat_fiscal, 0.0) * taux / 100.0, 2)
    return {
        "chiffre_affaires": etats["produits"],
        "charges_deductibles": etats["charges"],
        "resultat_fiscal": resultat_fiscal,
        "taux": taux,
        "is_du": is_du,
    }


# ══════════════════════════════════════════════════════════════════════════════
# TRANSIT, IMPORT-EXPORT & DOUANES (contexte ivoirien)
# ══════════════════════════════════════════════════════════════════════════════
def calculer_droits(valeur_caf: float, dd_pct: float, regime: str = "C100",
                    taux_tva: float = TAUX_TVA, taux_rs: float = TAUX_RS_PCT,
                    autres_taxes: float = 0.0) -> dict:
    """Calcule les droits et taxes selon le régime douanier.

    Structure du calcul (régime C100, mise à la consommation) :
      1. Droits de douane (DD)       = valeur CAF × taux DD
      2. Redevance statistique (RS)  = valeur CAF × 1 %
      3. PC UEMOA                    = valeur CAF × 0,8 %
      4. PCC CEDEAO                  = valeur CAF × 0,5 %
      5. TVA 18 %                    = (CAF + DD + RS + PC + PCC + autres taxes) × 18 %
    « autres_taxes » : taxes spécifiques / accises propres au produit (voir
    calculer_taxes_specifiques), incluses dans la base de la TVA.
    Les régimes E100 (export), AT (admission temporaire) et TR (transit) ne
    donnent lieu à aucun droit ni aucune TVA à payer (régimes suspensifs ou
    exonérés) : voir REGIMES_SUSPENDUS. Tous les taux restent modifiables et
    doivent être confirmés avec le tarif de la Douane en vigueur.
    """
    valeur_caf = max(float(valeur_caf), 0.0)
    suspendu = regime in REGIMES_SUSPENDUS
    facteur = 0.0 if suspendu else 1.0

    dd = round(valeur_caf * dd_pct / 100.0 * facteur, 2)
    rs = round(valeur_caf * taux_rs / 100.0 * facteur, 2)
    pc_uemoa = round(valeur_caf * PC_UEMOA_PCT / 100.0 * facteur, 2)
    pcc_cedeao = round(valeur_caf * PCC_CEDEAO_PCT / 100.0 * facteur, 2)
    autres = round(max(float(autres_taxes), 0.0) * facteur, 2)
    base_tva = round((valeur_caf + dd + rs + pc_uemoa + pcc_cedeao + autres) * facteur, 2)
    tva = round(base_tva * taux_tva / 100.0, 2)
    total = round(dd + rs + pc_uemoa + pcc_cedeao + autres + tva, 2)
    return {
        "valeur_caf": round(valeur_caf, 2),
        "droits_douane": dd,
        "redevance_statistique": rs,
        "pc_uemoa": pc_uemoa,
        "pcc_cedeao": pcc_cedeao,
        "autres_taxes": autres,
        "base_tva": base_tva,
        "tva": tva,
        "total_droits_taxes": total,
        "regime": regime,
        "suspendu": suspendu,
        "note_regime": REGIMES_SUSPENDUS.get(regime, ""),
    }


def scorer_risque(valeur_caf: float, dd_declare_pct: float, dd_reference_pct: float,
                  ecart_prix_pct: float = 0.0, fournisseur_nouveau: bool = True,
                  marchandise_sensible: bool = False) -> dict:
    """Moteur hybride de sélectivité des risques (canaux VERT/BLEU/JAUNE/ROUGE).

    Score 0-100 pondéré par des indicateurs objectifs de conformité :
    écart de déclaration des droits, sous-évaluation détectée par OCR,
    ancienneté du fournisseur et sensibilité de la marchandise. Le canal est
    dérivé du score, avec les seuils réglementaires usuels.
    """
    score = 0.0
    motifs: list[str] = []

    ecart_dd = abs(dd_declare_pct - dd_reference_pct)
    if ecart_dd > 5:
        score += 30
        motifs.append(f"Écart de taux DD déclaré ({ecart_dd:.1f} pts)")
    elif ecart_dd > 2:
        score += 15
        motifs.append(f"Léger écart de taux DD ({ecart_dd:.1f} pts)")

    if ecart_prix_pct > 20:
        score += 30
        motifs.append(f"Sous-évaluation probable ({ecart_prix_pct:.1f} % sous le prix de référence)")
    elif ecart_prix_pct > 10:
        score += 15
        motifs.append(f"Écart de prix modéré ({ecart_prix_pct:.1f} %)")

    if valeur_caf > 50_000_000:
        score += 15
        motifs.append("Valeur CAF élevée (> 50 M FCFA)")
    if fournisseur_nouveau:
        score += 10
        motifs.append("Fournisseur sans historique")
    if marchandise_sensible:
        score += 15
        motifs.append("Marchandise sensible / à droits élevés")

    score = min(round(score, 1), 100.0)
    if score >= 60:
        canal = "ROUGE"
    elif score >= 40:
        canal = "JAUNE"
    elif score >= 20:
        canal = "BLEU"
    else:
        canal = "VERT"
    return {"score": score, "canal": canal, "libelle_canal": CANAUX[canal], "motifs": motifs}


def calculer_surestaries(date_franchise: str, date_sortie: str, penalite_jour_usd: float,
                         taux_usd_xof: float | None = None) -> dict:
    """Calcule les surestaries portuaires (franchise armateur + pénalités).

    Les pénalités journalières sont exprimées en USD par les armateurs ; elles
    sont converties en FCFA au taux de change en direct.
    """
    taux = taux_usd_xof if taux_usd_xof else dernier_taux("USD") or 605.0
    essai_franchise = pd.to_datetime(date_franchise, errors="coerce")
    essai_sortie = pd.to_datetime(date_sortie, errors="coerce")
    if pd.isna(essai_franchise) or pd.isna(essai_sortie):
        raise ValueError("Dates invalides — format attendu AAAA-MM-JJ.")
    jours_retard = max((essai_sortie.date() - essai_franchise.date()).days, 0)
    montant_usd = round(jours_retard * penalite_jour_usd, 2)
    montant_xof = round(montant_usd * taux, 2)
    return {
        "jours_retard": jours_retard,
        "penalite_jour_usd": round(penalite_jour_usd, 2),
        "montant_usd": montant_usd,
        "taux_usd_xof": round(taux, 2),
        "montant_xof": montant_xof,
    }


# ─── Trésorerie multi-devises (FX) ────────────────────────────────────────────
def enregistrer_taux(devise: str, taux_vers_xof: float, source: str = "manuel") -> None:
    executer(
        "INSERT INTO taux_change (devise, taux_vers_xof, source, date_maj) VALUES (?,?,?,?)",
        (devise.upper(), round(taux_vers_xof, 4), source, maintenant()),
    )


def dernier_taux(devise: str) -> float | None:
    if devise.upper() == "XOF":
        return 1.0
    df = lire_df(
        "SELECT taux_vers_xof FROM taux_change WHERE devise=? ORDER BY id DESC LIMIT 1",
        (devise.upper(),),
    )
    return float(df.iloc[0]["taux_vers_xof"]) if not df.empty else None


def actualiser_taux_api(devise: str = "USD", url: str | None = None) -> float | None:
    """Récupère un taux de change en direct (API publique) et le persiste.

    Retourne None si le réseau est indisponible — l'appelant doit alors
    conserver le dernier taux connu (aucune exception propagée).
    """
    if not REQUESTS_OK:
        return None
    url = url or f"https://open.er-api.com/v6/latest/{devise.upper()}"
    try:
        reponse = requests.get(url, timeout=8)
        reponse.raise_for_status()
        data = reponse.json()
        taux = data.get("rates", {}).get("XOF")
        if taux:
            enregistrer_taux(devise, float(taux), "api")
            journaliser("taux_change_actualise", "taux_change", devise, f"taux={taux}")
            return float(taux)
    except Exception as exc:  # réseau indisponible : on garde le dernier taux
        journaliser("taux_change_echec", "taux_change", devise, f"erreur={type(exc).__name__}")
    return None


# ─── Manifestes maritimes et apurement des connaissements ─────────────────────
def creer_manifeste(numero: str, navire: str, armateur: str, date_arrivee: str,
                    port: str = "Abidjan") -> int:
    with connexion() as conn:
        cur = conn.execute(
            "INSERT INTO manifestes (tenant_id, numero, navire, armateur, port, date_arrivee,"
            " created_at) VALUES (?,?,?,?,?,?,?)",
            (tenant_courant(), numero, navire, armateur, port, date_arrivee, maintenant()),
        )
        manifeste_id = cur.lastrowid
    journaliser("manifeste_creation", "manifestes", str(manifeste_id), f"numero={numero}")
    return manifeste_id


def lister_manifestes() -> pd.DataFrame:
    return lire_df(
        "SELECT * FROM manifestes WHERE tenant_id=? ORDER BY id DESC", (tenant_courant(),)
    )


def enregistrer_connaissement(manifeste_id: int, bl: str, client: str, nb_colis: int,
                              poids_kg: float, valeur_usd: float, date_franchise: str) -> int:
    with connexion() as conn:
        cur = conn.execute(
            "INSERT INTO connaissements (tenant_id, manifeste_id, bl, client, nb_colis, poids_kg,"
            " valeur_usd, date_franchise) VALUES (?,?,?,?,?,?,?,?)",
            (tenant_courant(), manifeste_id, bl, client, nb_colis, poids_kg, valeur_usd,
             date_franchise),
        )
        bl_id = cur.lastrowid
    journaliser("connaissement_creation", "connaissements", str(bl_id), f"bl={bl}")
    return bl_id


def lister_connaissements() -> pd.DataFrame:
    return lire_df(
        "SELECT c.*, m.numero AS manifeste, m.navire FROM connaissements c"
        " LEFT JOIN manifestes m ON m.id = c.manifeste_id"
        " WHERE c.tenant_id=? ORDER BY c.id DESC",
        (tenant_courant(),),
    )


def apurer_connaissement(bl_id: int) -> None:
    """Apure un connaissement (B/L) après mainlevée douanière."""
    executer(
        "UPDATE connaissements SET apure=1, date_apurement=? WHERE id=? AND tenant_id=?",
        (maintenant(), bl_id, tenant_courant()),
    )
    journaliser("connaissement_apure", "connaissements", str(bl_id), "apurement B/L")


def apurer_manifeste(manifeste_id: int) -> None:
    """Apurement automatique : solde tous les B/L non apurés d'un manifeste."""
    executer(
        "UPDATE connaissements SET apure=1, date_apurement=? WHERE manifeste_id=? AND tenant_id=?"
        " AND apure=0",
        (maintenant(), manifeste_id, tenant_courant()),
    )
    executer(
        "UPDATE manifestes SET statut='Apuré' WHERE id=? AND tenant_id=?",
        (manifeste_id, tenant_courant()),
    )
    journaliser("manifeste_apure", "manifestes", str(manifeste_id), "apurement automatique des B/L")


# ─── Dossiers de transit ──────────────────────────────────────────────────────
# ─── Tarif douanier (codes SH) & taxes spécifiques ────────────────────────────
def normaliser_sh(code: str) -> str:
    """Réduit un code SH à ses chiffres (6 à 10). Lève ValueError s'il est invalide."""
    chiffres = re.sub(r"\D", "", str(code or ""))
    if not 6 <= len(chiffres) <= 10:
        raise ValueError("Code SH invalide : 6 à 10 chiffres attendus (ex. 8471.30.00.00).")
    return chiffres


def formater_sh(chiffres: str) -> str:
    """8471300000 → 8471.30.00.00"""
    morceaux = [chiffres[:4], chiffres[4:6], chiffres[6:8], chiffres[8:10]]
    return ".".join(morceau for morceau in morceaux if morceau)


def chercher_tarif(code_sh: str) -> dict | None:
    """Ligne du tarif du tenant pour un code SH.

    Ordre : ligne exacte, sinon la ligne la plus précise qui contient le code
    saisi, sinon l'unique sous-position. None si absente ou ambiguë.
    """
    chiffres = normaliser_sh(code_sh)
    with connexion() as conn:
        lignes = conn.execute(
            "SELECT code_sh, designation, dd, unite FROM tarif_douanier WHERE tenant_id=?"
            " AND (code_sh=? OR ? LIKE code_sh || '%' OR code_sh LIKE ? || '%')",
            (tenant_courant(), chiffres, chiffres, chiffres),
        ).fetchall()
    for ligne in lignes:
        if ligne["code_sh"] == chiffres:
            return dict(ligne)
    parents = [ligne for ligne in lignes if chiffres.startswith(ligne["code_sh"])]
    if parents:
        return dict(max(parents, key=lambda ligne: len(ligne["code_sh"])))
    return dict(lignes[0]) if len(lignes) == 1 else None


def rechercher_tarif(texte: str = "", limite: int = 200) -> pd.DataFrame:
    """Recherche dans le tarif : début de code SH si des chiffres sont saisis, sinon désignation."""
    texte = str(texte or "").strip()
    chiffres = re.sub(r"\D", "", texte)
    if chiffres:
        filtre, motif = "code_sh LIKE ?", chiffres + "%"
    else:
        filtre, motif = "designation LIKE ?", f"%{texte}%"
    tarif = lire_df(
        f"SELECT code_sh, designation, dd, unite FROM tarif_douanier WHERE tenant_id=?"
        f" AND {filtre} ORDER BY code_sh LIMIT ?", (tenant_courant(), motif, limite),
    )
    if not tarif.empty:
        tarif.insert(0, "code", tarif["code_sh"].map(formater_sh))
    return tarif


_ALIAS_COLONNES = {
    "code_sh": ("code_sh", "code", "sh", "hs", "hs_code", "position", "nomenclature"),
    "designation": ("designation", "désignation", "libelle", "libellé", "description", "produit"),
    "dd": ("dd", "droit", "droits", "taux_dd", "droit_de_douane", "taux"),
    "unite": ("unite", "unité", "unit"),
}


def _nombre(valeur) -> float:
    """Convertit « 5 », « 5,5 » ou « 20 % » en nombre."""
    texte = str(valeur or "").replace("%", "").replace(" ", "").replace(" ", "")
    try:
        return float(texte.replace(",", "."))
    except ValueError as exc:
        raise ValueError("taux illisible") from exc


def importer_tarif_csv(contenu) -> dict:
    """Importe un tarif douanier au format CSV (séparateur « ; » ou « , »).

    Colonnes obligatoires : code_sh et dd (en %). Facultatives : designation, unite.
    Les lignes valides sont enregistrées (mise à jour si le code existe déjà) ; les
    lignes invalides sont ignorées et listées. Vérifiez toujours les taux avec le
    tarif officiel avant d'importer.
    """
    texte = (contenu.decode("utf-8-sig", errors="replace")
             if isinstance(contenu, (bytes, bytearray)) else str(contenu))
    lignes_texte = texte.splitlines()
    if not lignes_texte:
        raise ValueError("Fichier vide.")
    separateur = ";" if lignes_texte[0].count(";") >= lignes_texte[0].count(",") else ","
    lecteur = csv.DictReader(io.StringIO(texte), delimiter=separateur)
    entetes = {re.sub(r"\s+", "_", (nom or "").strip().lower()): nom
               for nom in (lecteur.fieldnames or [])}
    colonnes = {cible: next((entetes[alias] for alias in alias_possibles if alias in entetes), None)
                for cible, alias_possibles in _ALIAS_COLONNES.items()}
    if not colonnes["code_sh"] or not colonnes["dd"]:
        raise ValueError("Colonnes obligatoires absentes : code_sh et dd (voir le modèle CSV).")

    valides, erreurs, hors_tranches = [], [], 0
    for numero, ligne in enumerate(lecteur, start=2):
        if not any(str(valeur or "").strip() for valeur in ligne.values()):
            continue
        try:
            code = normaliser_sh(ligne.get(colonnes["code_sh"]))
            dd = _nombre(ligne.get(colonnes["dd"]))
            if not 0 <= dd <= 100:
                raise ValueError("DD hors de 0–100 %")
        except ValueError as exc:
            erreurs.append(f"Ligne {numero} : {exc}")
            continue
        designation = str(ligne.get(colonnes["designation"]) or "").strip() if colonnes["designation"] else ""
        unite = str(ligne.get(colonnes["unite"]) or "").strip() if colonnes["unite"] else ""
        hors_tranches += dd not in TRANCHES_DD
        valides.append((tenant_courant(), code, designation, dd, unite))
    with connexion() as conn:
        conn.executemany(
            "INSERT INTO tarif_douanier (tenant_id, code_sh, designation, dd, unite)"
            " VALUES (?,?,?,?,?) ON CONFLICT(tenant_id, code_sh) DO UPDATE SET"
            " designation=excluded.designation, dd=excluded.dd, unite=excluded.unite", valides,
        )
    journaliser("tarif_import", "tarif_douanier", "",
                f"importees={len(valides)}; ignorees={len(erreurs)}")
    return {"importees": len(valides), "ignorees": len(erreurs),
            "hors_tranches": int(hors_tranches), "erreurs": erreurs[:20]}


def ajouter_taxe_specifique(prefixe_sh: str, libelle: str, mode: str, valeur: float,
                            unite: str = "") -> None:
    """Ajoute (ou met à jour) une taxe spécifique / accise applicable à un préfixe de code SH."""
    prefixe = re.sub(r"\D", "", str(prefixe_sh or ""))
    if not 2 <= len(prefixe) <= 10:
        raise ValueError("Préfixe SH invalide : 2 à 10 chiffres (ex. 22 ou 2203).")
    if not str(libelle or "").strip():
        raise ValueError("Le libellé est obligatoire.")
    if mode not in MODES_TAXE_SPECIFIQUE:
        raise ValueError("Mode de calcul inconnu.")
    if valeur < 0 or (mode == "POURCENT_CAF" and valeur > 1000):
        raise ValueError("Valeur de taxe invalide.")
    if mode == "MONTANT_PAR_UNITE" and not str(unite or "").strip():
        raise ValueError("Précisez l'unité (kg, litre, unité…).")
    with connexion() as conn:
        conn.execute(
            "INSERT INTO taxes_specifiques (tenant_id, prefixe_sh, libelle, mode, valeur, unite)"
            " VALUES (?,?,?,?,?,?) ON CONFLICT(tenant_id, prefixe_sh, libelle) DO UPDATE SET"
            " mode=excluded.mode, valeur=excluded.valeur, unite=excluded.unite",
            (tenant_courant(), prefixe, libelle.strip(), mode, float(valeur), str(unite).strip()),
        )
    journaliser("taxe_specifique_maj", "taxes_specifiques", prefixe,
                f"{libelle.strip()}; {mode}; {valeur}")


def supprimer_taxe_specifique(taxe_id: int) -> None:
    with connexion() as conn:
        cur = conn.execute("DELETE FROM taxes_specifiques WHERE id=? AND tenant_id=?",
                           (taxe_id, tenant_courant()))
        if cur.rowcount == 0:
            raise ValueError("Taxe introuvable.")
    journaliser("taxe_specifique_suppression", "taxes_specifiques", str(taxe_id), "")


def lister_taxes_specifiques() -> pd.DataFrame:
    return lire_df(
        "SELECT id, prefixe_sh, libelle, mode, valeur, unite FROM taxes_specifiques"
        " WHERE tenant_id=? ORDER BY prefixe_sh, libelle", (tenant_courant(),),
    )


def calculer_taxes_specifiques(code_sh: str, valeur_caf: float, quantite: float = 0.0) -> dict:
    """Taxes spécifiques / accises applicables à un code SH (règles du tenant).

    Une règle s'applique si le code SH commence par son préfixe. Une taxe « par unité »
    exige une quantité > 0 (sinon ValueError : mieux vaut refuser que sous-facturer).
    Retourne {"lignes": [{libelle, montant, detail}], "total"}.
    """
    chiffres = re.sub(r"\D", "", str(code_sh or ""))
    lignes: list[dict] = []
    if chiffres:
        for _, regle in lister_taxes_specifiques().iterrows():
            if not chiffres.startswith(str(regle["prefixe_sh"])):
                continue
            valeur = float(regle["valeur"])
            if regle["mode"] == "POURCENT_CAF":
                montant, detail = round(valeur_caf * valeur / 100.0, 2), f"{valeur:g} % de la CAF"
            else:
                if float(quantite or 0) <= 0:
                    raise ValueError(f"Quantité obligatoire ({regle['unite']}) : la taxe "
                                     f"« {regle['libelle']} » s'applique à ce code SH.")
                montant = round(float(quantite) * valeur, 2)
                detail = f"{float(quantite):g} × {valeur:g} FCFA / {regle['unite']}"
            lignes.append({"libelle": regle["libelle"], "montant": montant, "detail": detail})
    return {"lignes": lignes, "total": round(sum(ligne["montant"] for ligne in lignes), 2)}


def _code_sh_article(article: str) -> str:
    """Code SH (chiffres) de l'article de la base tarifaire du tenant, ou chaîne vide."""
    with connexion() as conn:
        ligne = conn.execute("SELECT sh FROM articles WHERE tenant_id=? AND nom=?",
                             (tenant_courant(), article)).fetchone()
    chiffres = re.sub(r"\D", "", str(ligne["sh"]) if ligne and ligne["sh"] else "")
    return chiffres if 6 <= len(chiffres) <= 10 else ""


def taux_dd_reference(article: str) -> float | None:
    """Taux de DD de référence de l'article dans la base tarifaire du tenant (ou None)."""
    with connexion() as conn:
        ligne = conn.execute(
            "SELECT dd FROM articles WHERE tenant_id=? AND nom=?", (tenant_courant(), article)
        ).fetchone()
    return float(ligne["dd"]) if ligne else None


def creer_dossier(reference: str, client: str, bl: str, article: str, regime: str,
                  fob_xof: float, fret_xof: float, assurance_xof: float, dd_pct: float,
                  email: str = "", telephone: str = "",
                  fournisseur_nouveau: bool = True, marchandise_sensible: bool = False,
                  code_sh: str = "", quantite: float = 0.0) -> dict:
    """Crée un dossier de transit : calcule CAF, droits, sélectivité et total.

    Le taux de DD déclaré est comparé au taux de référence (tarif douanier importé
    pour le code SH, sinon base des articles) pour alimenter le moteur de sélectivité
    des risques. Les taxes spécifiques du code SH (code saisi, sinon celui de
    l'article) sont ajoutées ; une taxe « par unité » exige la quantité. Retourne le
    détail du calcul. Lève ValueError si les données sont invalides (référence vide,
    montant négatif, régime inconnu, code SH invalide, quantité manquante, référence
    déjà utilisée).
    """
    if not str(reference).strip() or not str(client).strip():
        raise ValueError("La référence et le client sont obligatoires.")
    if regime not in REGIMES_DOUANIERS:
        raise ValueError(f"Régime douanier inconnu : {regime}.")
    if min(fob_xof, fret_xof, assurance_xof) < 0 or not 0 <= dd_pct <= 100:
        raise ValueError("Montants négatifs ou taux de DD hors de 0–100 % non autorisés.")
    valeur_caf = round(fob_xof + fret_xof + assurance_xof, 2)
    if float(quantite or 0) < 0:
        raise ValueError("La quantité ne peut pas être négative.")
    code_effectif = normaliser_sh(code_sh) if str(code_sh or "").strip() else _code_sh_article(article)
    tarif = chercher_tarif(code_effectif) if code_effectif else None
    # Export, admission temporaire et transit : aucune taxe à l'entrée, donc pas de quantité exigée.
    taxes = ({"lignes": [], "total": 0.0} if regime in REGIMES_SUSPENDUS
             else calculer_taxes_specifiques(code_effectif, valeur_caf, quantite))
    droits = calculer_droits(valeur_caf, dd_pct, regime, autres_taxes=taxes["total"])
    dd_reference = float(tarif["dd"]) if tarif else taux_dd_reference(article)
    risque = scorer_risque(valeur_caf, dd_pct, dd_pct if dd_reference is None else dd_reference,
                           fournisseur_nouveau=fournisseur_nouveau,
                           marchandise_sensible=marchandise_sensible)
    total_facture = round(valeur_caf + droits["total_droits_taxes"], 2)
    try:
        with connexion() as conn:
            cur = conn.execute(
                "INSERT INTO dossiers (tenant_id, reference, date, client, bl, article, regime,"
                " fob_xof, fret_xof, assurance_xof, valeur_caf_xof, droits_douane, tva,"
                " total_facture, solde_du, statut, canal_risque, score_risque, email, telephone,"
                " created_at, code_sh, quantite, taxes_specifiques)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (tenant_courant(), reference.strip(), date.today().strftime("%Y-%m-%d"), client, bl,
                 article, regime, fob_xof, fret_xof, assurance_xof, valeur_caf,
                 droits["total_droits_taxes"], droits["tva"], total_facture, total_facture,
                 "En cours", risque["canal"], risque["score"], email, telephone, maintenant(),
                 code_effectif, float(quantite or 0), droits["autres_taxes"]),
            )
            dossier_id = cur.lastrowid
    except sqlite3.IntegrityError as exc:
        raise ValueError(f"La référence « {reference} » existe déjà.") from exc
    journaliser("dossier_creation", "dossiers", str(dossier_id),
                f"reference={reference}; canal={risque['canal']}; score={risque['score']}")
    return {"dossier_id": dossier_id, "droits": droits, "risque": risque,
            "total_facture": total_facture, "taxes": taxes, "code_sh": code_effectif,
            "tarif": tarif}


def lister_dossiers() -> pd.DataFrame:
    return lire_df(
        "SELECT * FROM dossiers WHERE tenant_id=? ORDER BY id DESC", (tenant_courant(),)
    )


# ─── Conformité documentaire du dossier (FDI, BSC, CdC…) ──────────────────────
def documents_requis(regime: str, fob_xof: float = 0.0) -> list[str]:
    """Codes des pièces obligatoires selon le régime et la valeur FOB du dossier.

    Import (C100) : facture, B/L, colisage, FDI, BSC, déclaration en douane, et
    Certificat de Conformité dès que la FOB atteint SEUIL_CDC_FOB_XOF (le CdC
    peut être déclaré « Exempté » avec motif). Liste de référence à adapter.
    """
    if regime == "C100":
        requis = ["FACTURE", "BL", "COLISAGE", "FDI", "BSC"]
        if float(fob_xof or 0) >= SEUIL_CDC_FOB_XOF:
            requis.append("CDC")
        return requis + ["DECLARATION"]
    if regime == "AT":
        return ["FACTURE", "BL", "COLISAGE", "BSC", "DECLARATION"]
    if regime == "TR":
        return ["FACTURE", "BL", "TRANSIT"]
    if regime == "E100":
        return ["FACTURE", "COLISAGE", "DECLARATION"]
    return ["FACTURE", "BL"]


def enregistrer_document_dossier(dossier_id: int, code: str, reference: str,
                                 statut: str = "Reçu") -> None:
    """Enregistre (ou met à jour) la référence d'une pièce du dossier."""
    if code not in DOCUMENTS_DOSSIER:
        raise ValueError(f"Pièce inconnue : {code}.")
    if statut not in DOCUMENT_STATUTS:
        raise ValueError(f"Statut de pièce inconnu : {statut}.")
    if statut == "Exempté" and code != "CDC":
        raise ValueError("Seul le Certificat de Conformité peut être déclaré exempté.")
    reference = str(reference or "").strip()
    if not reference:
        raise ValueError("Indiquez le motif de l'exemption." if statut == "Exempté"
                         else "Indiquez la référence (numéro) de la pièce.")
    with connexion() as conn:
        existe = conn.execute("SELECT 1 FROM dossiers WHERE id=? AND tenant_id=?",
                              (dossier_id, tenant_courant())).fetchone()
        if not existe:
            raise ValueError("Dossier introuvable.")
        conn.execute(
            "INSERT INTO dossier_documents (tenant_id, dossier_id, code, reference, statut,"
            " created_by, created_at) VALUES (?,?,?,?,?,?,?)"
            " ON CONFLICT(tenant_id, dossier_id, code) DO UPDATE SET reference=excluded.reference,"
            " statut=excluded.statut, created_by=excluded.created_by, created_at=excluded.created_at",
            (tenant_courant(), dossier_id, code, reference, statut,
             st.session_state.get("username", "système"), maintenant()),
        )
    journaliser("document_dossier", "dossier_documents", f"{dossier_id}:{code}",
                f"reference={reference}; statut={statut}")


def lister_documents_dossier(dossier_id: int) -> pd.DataFrame:
    return lire_df(
        "SELECT code, reference, statut, created_by, created_at FROM dossier_documents"
        " WHERE tenant_id=? AND dossier_id=? ORDER BY id", (tenant_courant(), dossier_id),
    )


def _references_documents(dossier_id) -> dict:
    """Pièces enregistrées {code: "référence (statut)"} — vide si dossier inconnu."""
    if dossier_id is None:
        return {}
    docs = lister_documents_dossier(int(dossier_id))
    return {ligne["code"]: f"{ligne['reference']} ({ligne['statut']})"
            for _, ligne in docs.iterrows()}


def controle_conformite(dossier_id: int) -> dict:
    """Compare les pièces obligatoires du dossier à celles déjà enregistrées."""
    with connexion() as conn:
        dossier = conn.execute("SELECT regime, fob_xof FROM dossiers WHERE id=? AND tenant_id=?",
                               (dossier_id, tenant_courant())).fetchone()
    if not dossier:
        raise ValueError("Dossier introuvable.")
    requis = documents_requis(dossier["regime"], float(dossier["fob_xof"] or 0))
    presents = set(_references_documents(dossier_id))
    manquants = [code for code in requis if code not in presents]
    return {
        "requis": requis,
        "presents": [code for code in requis if code in presents],
        "manquants": manquants,
        "libelles_manquants": [DOCUMENTS_DOSSIER[code] for code in manquants],
        "complet": not manquants,
    }


def maj_statut_dossier(dossier_id: int, statut: str) -> None:
    """Change le statut d'un dossier en respectant le cycle de vie du transit.

    - on ne saute pas d'étape (on peut revenir en arrière pour corriger) ;
    - le BAE n'est émis que si toutes les pièces obligatoires sont enregistrées.
    Lève ValueError en cas de refus.
    """
    if statut not in STATUTS_DOSSIER:
        raise ValueError(f"Statut inconnu : {statut}.")
    with connexion() as conn:
        ligne = conn.execute("SELECT statut FROM dossiers WHERE id=? AND tenant_id=?",
                             (dossier_id, tenant_courant())).fetchone()
    if not ligne:
        raise ValueError("Dossier introuvable.")
    actuel = STATUTS_DOSSIER.index(ligne["statut"]) if ligne["statut"] in STATUTS_DOSSIER else 0
    cible = STATUTS_DOSSIER.index(statut)
    if cible > actuel + 1:
        raise ValueError(f"Étape sautée : passez d'abord à « {STATUTS_DOSSIER[actuel + 1]} ».")
    if statut == STATUT_BAE and cible > actuel:
        controle = controle_conformite(dossier_id)
        if not controle["complet"]:
            raise ValueError("BAE impossible, pièces manquantes : "
                             + ", ".join(controle["libelles_manquants"]) + ".")
    executer(
        "UPDATE dossiers SET statut=? WHERE id=? AND tenant_id=?",
        (statut, dossier_id, tenant_courant()),
    )
    journaliser("dossier_statut", "dossiers", str(dossier_id), f"statut={statut}")


# ─── Génération des documents officiels (BAE + facture transitaire) ───────────
def _styles_pdf():
    styles = getSampleStyleSheet()
    return {
        "titre": ParagraphStyle("titre", parent=styles["Title"], fontSize=16, spaceAfter=4),
        "sous": ParagraphStyle("sous", parent=styles["Normal"], fontSize=9,
                               textColor=colors.grey),
        "cellule": ParagraphStyle("cellule", parent=styles["Normal"], fontSize=9),
        "cellule_b": ParagraphStyle("cellule_b", parent=styles["Normal"], fontSize=9,
                                    fontName="Helvetica-Bold"),
    }


def _tableau(donnees: list[list], largeurs: list[float] | None = None):
    tableau = Table(donnees, colWidths=largeurs, hAlign="LEFT")
    tableau.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0E1830")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#B0B8C4")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F3F5F9")]),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return tableau


def generer_bae(dossier: dict, societe: str = "Cabinet Excellence Comptable CI") -> tuple[bytes, str]:
    """Génère le Bon à Enlever (BAE) PDF scellé par empreinte SHA-256.

    Retourne (contenu_pdf, empreinte_sha256). L'empreinte est calculée sur les
    données métier du dossier puis apposée sur le document : toute modification
    ultérieure invalide le sceau (vérifiable en recalculant l'empreinte).
    """
    if not REPORTLAB_OK:
        raise RuntimeError("ReportLab indisponible — installation requise pour le PDF.")
    # Un BAE neuf exige un dossier conforme ; la ré-impression d'un BAE déjà émis reste libre.
    if dossier.get("id") is not None and dossier.get("statut") in STATUTS_DOSSIER[:3]:
        controle = controle_conformite(int(dossier["id"]))
        if not controle["complet"]:
            raise ValueError("BAE refusé, pièces manquantes : "
                             + ", ".join(controle["libelles_manquants"]) + ".")
    pieces = _references_documents(dossier.get("id"))
    numero = f"BAE-{dossier.get('reference', 'SANS-REF')}-{date.today().strftime('%Y%m%d')}"
    empreinte = empreinte_sha256(
        numero, dossier.get("reference"), dossier.get("client"), dossier.get("valeur_caf_xof"),
        dossier.get("droits_douane"), dossier.get("total_facture"),
        json.dumps(pieces, sort_keys=True, ensure_ascii=False),
    )
    style = _styles_pdf()
    flux = io.BytesIO()
    doc = SimpleDocTemplate(flux, pagesize=A4, title=numero)
    elements = [
        Paragraph(f"<b>{societe}</b>", style["titre"]),
        Paragraph("BON À ENLEVER (BAE) — mainlevée douanière", style["sous"]),
        Spacer(1, 8),
        Paragraph(f"<b>N° BAE :</b> {numero}", style["cellule"]),
        Paragraph(f"<b>Date d'émission :</b> {maintenant()}", style["cellule"]),
        Spacer(1, 10),
        _tableau([
            ["Rubrique", "Valeur"],
            ["Référence dossier", str(dossier.get("reference", ""))],
            ["Client / bénéficiaire", str(dossier.get("client", ""))],
            ["Connaissement (B/L)", str(dossier.get("bl", ""))],
            ["Article / désignation", str(dossier.get("article", ""))],
            ["Régime douanier", str(dossier.get("regime", "C100"))],
            ["Valeur en douane (CAF)", f"{float(dossier.get('valeur_caf_xof') or 0):,.0f} FCFA"],
            ["Droits et taxes acquittés", f"{float(dossier.get('droits_douane') or 0):,.0f} FCFA"],
            ["Canal de sélectivité", str(dossier.get("canal_risque", "VERT"))],
            *[[DOCUMENTS_DOSSIER[code].split(" (")[0], pieces[code]]
              for code in ("FDI", "BSC", "CDC") if code in pieces],
            ["Statut", str(dossier.get("statut", ""))],
        ], largeurs=[60 * mm, 105 * mm]),
        Spacer(1, 12),
        Paragraph("<b>Sceau d'intégrité (SHA-256)</b>", style["cellule_b"]),
        Paragraph(f"<font face='Courier' size='8'>{empreinte}</font>", style["cellule"]),
        Spacer(1, 6),
        Paragraph(
            "Document généré électroniquement. Toute modification invalide le sceau "
            "ci-dessus — vérifiable par recalcul de l'empreinte.", style["sous"],
        ),
    ]
    doc.build(elements)
    executer(
        "INSERT INTO bae_documents (tenant_id, dossier_id, numero, empreinte_sha256, emis_par,"
        " emis_at) VALUES (?,?,?,?,?,?)",
        (tenant_courant(), dossier.get("id"), numero, empreinte,
         st.session_state.get("username", "système"), maintenant()),
    )
    journaliser("bae_emis", "bae_documents", numero, f"empreinte={empreinte[:16]}...")
    return flux.getvalue(), empreinte


def generer_facture_transitaire(dossier: dict, honoraires_ht: float, fret: float,
                                surestaries: float,
                                societe: str = "Cabinet Excellence Comptable CI") -> bytes:
    """Facture transitaire détaillée : débours, fret, surestaries et honoraires TVA."""
    if not REPORTLAB_OK:
        raise RuntimeError("ReportLab indisponible — installation requise pour le PDF.")
    debours = float(dossier.get("droits_douane") or 0)
    tva = round(honoraires_ht * TAUX_TVA / 100.0, 2)
    total = round(debours + fret + surestaries + honoraires_ht + tva, 2)
    style = _styles_pdf()
    flux = io.BytesIO()
    doc = SimpleDocTemplate(flux, pagesize=A4, title=f"FACT-{dossier.get('reference')}")
    elements = [
        Paragraph(f"<b>{societe}</b>", style["titre"]),
        Paragraph("FACTURE TRANSITAIRE", style["sous"]),
        Spacer(1, 8),
        Paragraph(f"<b>Dossier :</b> {dossier.get('reference')}", style["cellule"]),
        Paragraph(f"<b>Client :</b> {dossier.get('client')}", style["cellule"]),
        Paragraph(f"<b>Date :</b> {maintenant()}", style["cellule"]),
        Spacer(1, 10),
        _tableau([
            ["Désignation", "Montant (FCFA)"],
            ["Débours douaniers (droits & taxes)", f"{debours:,.0f}"],
            ["Frais de fret / transport", f"{fret:,.0f}"],
            ["Surestaries portuaires", f"{surestaries:,.0f}"],
            ["Honoraires de transit (HT)", f"{honoraires_ht:,.0f}"],
            [f"TVA {TAUX_TVA:.0f} % sur honoraires", f"{tva:,.0f}"],
            ["TOTAL À PAYER", f"{total:,.0f}"],
        ], largeurs=[110 * mm, 55 * mm]),
        Spacer(1, 10),
        Paragraph(
            "Les débours douaniers constituent des avances de fonds refacturées en "
            "hors taxes ; seuls les honoraires supportent la TVA.", style["sous"],
        ),
    ]
    doc.build(elements)
    journaliser("facture_transitaire", "dossiers", str(dossier.get("id")), f"total={total:,.0f}")
    return flux.getvalue()


# ══════════════════════════════════════════════════════════════════════════════
# INTELLIGENCE ARTIFICIELLE & OCR / IDP
# ══════════════════════════════════════════════════════════════════════════════
PROMPT_SYSTEME = (
    "Tu es un assistant expert en fiscalité, comptabilité SYSCOHADA révisé et droit "
    "douanier ivoirien (Code des douanes Côte d'Ivoire, régimes C100/E100/AT/TR, "
    "prélèvements communautaires UEMOA/CEDEAO, TVA 18 %). Tu réponds de façon précise, "
    "structureé et prudente. Tu rappelles systématiquement, lorsque la réponse engage "
    "une décision officielle, que la validation d'un expert-comptable ou d'un "
    "commissionnaire en douane agréé reste nécessaire."
)


def poser_question_ia(question: str, contexte: str = "") -> tuple[str, list[str]]:
    """Interroge l'assistant IA (Groq). Retourne (réponse, erreurs)."""
    if not GROQ_OK:
        return "", ["La librairie `groq` n'est pas installée (pip install groq)."]
    cle = get_secret("GROQ_API_KEY") or st.session_state.get("groq_api_key", "")
    if not cle:
        return "", ["Clé API Groq absente (renseigner GROQ_API_KEY ou la barre latérale)."]
    modele = get_secret("GROQ_MODEL", "llama-3.1-8b-instant")
    try:
        client = Groq(api_key=cle)
        messages = [{"role": "system", "content": PROMPT_SYSTEME}]
        if contexte:
            messages.append({"role": "system", "content": f"Contexte entreprise : {contexte}"})
        messages.append({"role": "user", "content": question})
        reponse = client.chat.completions.create(
            model=modele, messages=messages, temperature=0.2, max_tokens=1200,
        )
        contenu = reponse.choices[0].message.content or ""
        journaliser("ia_question", "assistant", "", f"question={question[:120]}")
        return contenu, []
    except Exception as exc:
        return "", [f"{type(exc).__name__}: {exc}"]


def extraire_facture_heuristique(texte: str) -> dict:
    """Extraction OCR/IDP heuristique des champs clés d'une facture fournisseur.

    Détecte fournisseur, numéro de facture, dates, montants et désignation.
    Fonctionne hors-ligne ; un moteur OCR dédié (Tesseract/Document AI) peut
    fournir le texte en amont sans changer cette interface.
    """
    texte = texte or ""
    montants = [
        float(m.replace(" ", "").replace(",", ""))
        for m in re.findall(r"(?:\d{1,3}(?:[ \u00a0]\d{3})+|\d{4,})(?:[.,]\d{1,2})?", texte)
    ]
    montants = [m for m in montants if m >= 100]
    fournisseur = ""
    correspondance = re.search(r"(?:vendeur|fournisseur|exportateur|seller)\s*[:\-]\s*(.+)", texte, re.I)
    if correspondance:
        fournisseur = correspondance.group(1).strip().splitlines()[0][:80]
    numero = ""
    correspondance_num = re.search(r"(?:facture|invoice|n[°o])\s*[:\-#]?\s*([A-Z0-9\-/]{4,})", texte, re.I)
    if correspondance_num:
        numero = correspondance_num.group(1)
    date_facture = ""
    correspondance_date = re.search(r"(\d{2}[/\-]\d{2}[/\-]\d{4}|\d{4}-\d{2}-\d{2})", texte)
    if correspondance_date:
        date_facture = correspondance_date.group(1)
    designation = ""
    correspondance_des = re.search(r"(?:d[ée]signation|description|article)\s*[:\-]\s*(.+)", texte, re.I)
    if correspondance_des:
        designation = correspondance_des.group(1).strip().splitlines()[0][:120]
    return {
        "fournisseur": fournisseur,
        "numero_facture": numero,
        "date_facture": date_facture,
        "montant_extrait": max(montants) if montants else 0.0,
        "tous_montants": sorted(montants, reverse=True)[:10],
        "designation": designation,
    }


def cross_check_facture(montant_declare: float, montant_extrait: float,
                        prix_reference: float = 0.0, fournisseur: str = "") -> dict:
    """Cross-checking automatique : détecte discordances et sous-évaluation.

    Compare le montant déclaré à la douane au montant extrait du document et
    au prix de référence du marché. Un écart négatif significatif signale une
    sous-évaluation douanière probable.
    """
    ecart_declare = round(montant_declare - montant_extrait, 2)
    ecart_pct = round((ecart_declare / montant_extrait * 100.0), 2) if montant_extrait else 0.0
    ecart_reference_pct = (
        round((montant_declare - prix_reference) / prix_reference * 100.0, 2)
        if prix_reference else 0.0
    )
    anomalies: list[str] = []
    if montant_extrait and abs(ecart_pct) > 5:
        anomalies.append(
            f"Discordance déclaré/extrait : {ecart_declare:,.0f} FCFA ({ecart_pct:+.1f} %)"
        )
    if prix_reference and ecart_reference_pct < -10:
        anomalies.append(
            f"Sous-évaluation probable : {abs(ecart_reference_pct):.1f} % sous le prix de référence"
        )
    if montant_declare > montant_extrait and ecart_pct > 20:
        anomalies.append("Sur-déclaration importante détectée")
    return {
        "ecart_declare": ecart_declare,
        "ecart_pct": ecart_pct,
        "ecart_reference_pct": ecart_reference_pct,
        "discordance": bool(anomalies),
        "anomalies": anomalies,
        "fournisseur": fournisseur,
    }


def enregistrer_extraction_ocr(fichier: str, extraction: dict, cross_check: dict) -> int:
    with connexion() as conn:
        cur = conn.execute(
            "INSERT INTO ocr_extractions (tenant_id, fichier, fournisseur, montant_declare,"
            " montant_extrait, ecart_pct, discordance, details, created_by, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (tenant_courant(), fichier, cross_check.get("fournisseur", ""),
             cross_check.get("montant_declare", 0.0), extraction.get("montant_extrait", 0.0),
             cross_check.get("ecart_pct", 0.0), 1 if cross_check.get("discordance") else 0,
             json.dumps(extraction, ensure_ascii=False, default=str),
             st.session_state.get("username", "système"), maintenant()),
        )
        ocr_id = cur.lastrowid
    journaliser("ocr_extraction", "ocr_extractions", str(ocr_id),
                f"discordance={cross_check.get('discordance')}")
    return ocr_id


# ─── Communications professionnelles (validation humaine obligatoire) ─────────
MODELES_COMMUNICATION = {
    "Relance client (solde impayé)": (
        "Objet : Relance — solde de {montant} FCFA sur le dossier {reference}\n\n"
        "Madame, Monsieur {client},\n\n"
        "Sauf erreur de notre part, un solde de {montant} FCFA reste dû au titre du "
        "dossier {reference} (B/L {bl}). Nous vous serions reconnaissants de bien "
        "vouloir procéder au règlement à votre meilleure convenance.\n\n"
        "Nous restons à votre disposition pour tout justificatif complémentaire.\n\n"
        "Cordialement,\nLe service transit"
    ),
    "Demande de pièces manquantes": (
        "Objet : Pièces manquantes — dossier {reference}\n\n"
        "Madame, Monsieur {client},\n\n"
        "Afin de finaliser le dédouanement du dossier {reference} (B/L {bl}), nous "
        "vous remercions de nous transmettre : facture commerciale, liste de colisage, "
        "connaissement original et certificat d'origine.\n\n"
        "Cordialement,\nLe service transit"
    ),
    "Courrier administratif (DGI / Douanes)": (
        "Objet : Dossier {reference} — demande d'information\n\n"
        "Madame, Monsieur,\n\n"
        "Dans le cadre du traitement du dossier {reference} (B/L {bl}), nous sollicitons "
        "les éléments complémentaires nécessaires à la liquidation des droits et taxes.\n\n"
        "Nous vous prions d'agréer nos salutations distinguées."
    ),
}


def rediger_communication(type_communication: str, variables: dict) -> dict:
    """Prépare un brouillon de communication (statut « En attente »).

    Aucun envoi n'est possible sans validation humaine explicite : la diffusion
    externe passe obligatoirement par `valider_communication()`.
    """
    modele = MODELES_COMMUNICATION.get(type_communication, "")
    corps = modele.format(**variables) if modele else ""
    with connexion() as conn:
        cur = conn.execute(
            "INSERT INTO communications (tenant_id, type, destinataire, email_destinataire,"
            " objet, corps, statut_validation, created_by, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (tenant_courant(), type_communication, variables.get("client", ""),
             variables.get("email", ""), corps.splitlines()[0] if corps else "", corps,
             "En attente", st.session_state.get("username", "système"), maintenant()),
        )
        comm_id = cur.lastrowid
    journaliser("communication_brouillon", "communications", str(comm_id), type_communication)
    return {"id": comm_id, "corps": corps, "statut": "En attente"}


def valider_communication(comm_id: int) -> None:
    """Validation humaine obligatoire avant toute diffusion externe."""
    executer(
        "UPDATE communications SET statut_validation='Validée', valide_par=?, valide_at=?"
        " WHERE id=? AND tenant_id=?",
        (st.session_state.get("username", "système"), maintenant(), comm_id, tenant_courant()),
    )
    journaliser("communication_validee", "communications", str(comm_id), "validation humaine")


def lister_communications() -> pd.DataFrame:
    return lire_df(
        "SELECT * FROM communications WHERE tenant_id=? ORDER BY id DESC", (tenant_courant(),)
    )


# ─── Diffusion externe sécurisée (SMTP / Gmail App Password) ──────────────────
def configuration_smtp() -> dict:
    """Configuration SMTP lue depuis les secrets/env + état de complétude.

    Aucune valeur de mot de passe n'est jamais exposée à l'interface ni à la
    piste d'audit : seules les informations non sensibles sont renvoyées.
    """
    config = {
        "serveur": get_secret("SMTP_SERVER", "smtp.gmail.com") or "smtp.gmail.com",
        "port": int(get_secret("SMTP_PORT", "587") or 587),
        "utilisateur": get_secret("SMTP_USERNAME", ""),
        "mot_de_passe": get_secret("SMTP_PASSWORD", ""),
    }
    config["expediteur"] = get_secret("SMTP_FROM", "") or config["utilisateur"]
    config["configure"] = bool(config["utilisateur"] and config["mot_de_passe"])
    return config


def envoyer_email(destinataire: str, sujet: str, corps: str,
                  pieces_jointes: list[tuple[str, bytes]] | None = None) -> dict:
    """Envoie un e-mail via SMTP (STARTTLS) — mot de passe d'application Gmail.

    Ne lève jamais d'exception : sans configuration, l'envoi est simulé et
    journalisé. Les secrets sont masqués avant écriture dans l'audit.
    """
    config = configuration_smtp()
    if not config["configure"] or not destinataire:
        journaliser("email_simule", "communications", destinataire,
                    f"sujet={sujet[:80]}; smtp_configure={config['configure']}")
        return {"succes": False, "simule": True,
                "details": "SMTP non configuré (ou destinataire vide) — e-mail non transmis."}
    try:
        message = MIMEMultipart()
        message["From"] = config["expediteur"]
        message["To"] = destinataire
        message["Subject"] = sujet
        message.attach(MIMEText(corps, "plain", "utf-8"))
        for nom_fichier, contenu in (pieces_jointes or []):
            piece = MIMEApplication(contenu, _subtype="pdf")
            piece.add_header("Content-Disposition", "attachment", filename=nom_fichier)
            message.attach(piece)
        with smtplib.SMTP(config["serveur"], config["port"], timeout=15) as serveur:
            serveur.starttls()
            serveur.login(config["utilisateur"], config["mot_de_passe"])
            serveur.send_message(message)
        journaliser("email_envoye", "communications", destinataire, f"sujet={sujet[:80]}")
        return {"succes": True, "simule": False, "details": "E-mail transmis."}
    except Exception as exc:  # réseau / authentification : jamais bloquant
        journaliser("email_echec", "communications", destinataire,
                    f"erreur={type(exc).__name__}")
        return {"succes": False, "simule": False,
                "details": f"Échec de l'envoi : {type(exc).__name__}."}


def envoyer_communication(comm_id: int, destinataire: str = "") -> dict:
    """Diffuse une communication DÉJÀ VALIDÉE par un humain.

    Toute tentative de diffusion d'un brouillon non validé est refusée et
    journalisée — exigence de conformité (aucune diffusion externe automatique).
    """
    with connexion() as conn:
        ligne = conn.execute(
            "SELECT * FROM communications WHERE id=? AND tenant_id=?",
            (comm_id, tenant_courant()),
        ).fetchone()
    if not ligne:
        return {"succes": False, "details": "Communication introuvable pour cette entreprise."}
    if ligne["statut_validation"] != "Validée":
        journaliser("email_refuse", "communications", str(comm_id),
                    "diffusion bloquée : validation humaine manquante")
        return {"succes": False,
                "details": "Diffusion refusée : la communication doit d'abord être validée."}
    destinataire = destinataire or (ligne["email_destinataire"] or "")
    resultat = envoyer_email(destinataire, ligne["objet"] or "Communication",
                             ligne["corps"] or "")
    statut = "Envoyée" if resultat["succes"] else ("Simulée" if resultat.get("simule") else "Échec")
    executer(
        "UPDATE communications SET statut_envoi=?, envoyee_at=?, email_destinataire=?"
        " WHERE id=? AND tenant_id=?",
        (statut, maintenant(), destinataire, comm_id, tenant_courant()),
    )
    journaliser("communication_diffusion", "communications", str(comm_id),
                f"statut_envoi={statut}")
    resultat["statut_envoi"] = statut
    return resultat


# ══════════════════════════════════════════════════════════════════════════════
# UX — DARK MODE, KPI & GRAPHIQUES
# ══════════════════════════════════════════════════════════════════════════════
PALETTE = {
    "bg": "#05070D",
    "gradient": "radial-gradient(circle at 15% -10%, #14213D 0%, #05070D 55%)",
    "card": "rgba(255,255,255,0.045)",
    "border": "rgba(255,255,255,0.10)",
    "texte": "#F5F7FA",
    "texte_2": "#8B95A7",
    "accent": "#0A84FF",
    "succes": "#30D158",
    "alerte": "#FF9F0A",
    "danger": "#FF453A",
}


CSS_THEME_3D = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
:root{
  --bg:#04060C; --txt:#F5F7FA; --txt2:#8B95A7; --acc:#0A84FF; --acc2:#5E5CE6;
  --ok:#30D158; --warn:#FF9F0A; --bad:#FF453A;
  --glass:linear-gradient(145deg,rgba(255,255,255,.085),rgba(255,255,255,.025));
  --edge:rgba(255,255,255,.12);
  --lift:0 1px 0 rgba(255,255,255,.14) inset,0 -1px 0 rgba(0,0,0,.4) inset,
         0 18px 40px -12px rgba(0,0,0,.65),0 6px 14px -6px rgba(0,0,0,.5);
}
html,body,[class*="css"]{font-family:'Inter',-apple-system,BlinkMacSystemFont,sans-serif;}
.stApp{
  color:var(--txt);
  background:
    radial-gradient(900px 520px at 8% -8%,rgba(10,132,255,.22),transparent 60%),
    radial-gradient(800px 560px at 100% 0%,rgba(94,92,230,.20),transparent 60%),
    radial-gradient(700px 500px at 50% 115%,rgba(48,209,88,.10),transparent 60%),
    var(--bg);
  background-attachment:fixed;
}
.stApp::before{ /* grille en perspective, très discrète */
  content:"";position:fixed;inset:0;pointer-events:none;z-index:0;opacity:.35;
  background-image:linear-gradient(rgba(255,255,255,.035) 1px,transparent 1px),
                   linear-gradient(90deg,rgba(255,255,255,.035) 1px,transparent 1px);
  background-size:56px 56px;
  -webkit-mask-image:radial-gradient(ellipse at 50% 0%,#000 0%,transparent 70%);
          mask-image:radial-gradient(ellipse at 50% 0%,#000 0%,transparent 70%);
}
.block-container{padding-top:2.2rem;max-width:1280px;position:relative;z-index:1;}
h1,h2,h3{letter-spacing:-.02em;font-weight:800;}
h1{background:linear-gradient(180deg,#fff,#9fb4d6);-webkit-background-clip:text;
   background-clip:text;-webkit-text-fill-color:transparent;}
h5,h4{color:#dfe6f2;font-weight:700;letter-spacing:-.01em;}

/* ---------- Cartes en verre 3D ---------- */
.sndgir-card{
  position:relative;background:var(--glass);
  backdrop-filter:blur(22px) saturate(170%);-webkit-backdrop-filter:blur(22px) saturate(170%);
  border:1px solid var(--edge);border-radius:22px;padding:20px 22px;margin-bottom:16px;
  box-shadow:var(--lift);transform:perspective(900px) rotateX(0) rotateY(0) translateZ(0);
  transition:transform .35s cubic-bezier(.2,.8,.2,1),box-shadow .35s ease,border-color .35s ease;
  overflow:hidden;
}
.sndgir-card::before{ /* reflet de lumière */
  content:"";position:absolute;inset:0 0 auto 0;height:55%;pointer-events:none;
  background:linear-gradient(180deg,rgba(255,255,255,.10),transparent);opacity:.55;
}
.sndgir-card::after{ /* liseré coloré en bas */
  content:"";position:absolute;left:18px;right:18px;bottom:0;height:2px;border-radius:2px;
  background:linear-gradient(90deg,transparent,var(--cardc,var(--acc)),transparent);opacity:.9;
}
.sndgir-card:hover{
  transform:perspective(900px) rotateX(3deg) rotateY(-3deg) translateY(-6px);
  border-color:rgba(255,255,255,.22);
  box-shadow:0 1px 0 rgba(255,255,255,.18) inset,0 30px 60px -14px rgba(0,0,0,.75),
             0 0 40px -10px var(--cardc,var(--acc));
}
.sndgir-card.k-vert{--cardc:var(--ok)}.sndgir-card.k-bleu{--cardc:var(--acc)}
.sndgir-card.k-jaune{--cardc:var(--warn)}.sndgir-card.k-rouge{--cardc:var(--bad)}
.k-titre{color:var(--txt2);font-size:.74rem;font-weight:600;text-transform:uppercase;letter-spacing:.08em;}
.k-valeur{font-size:1.85rem;font-weight:800;margin:6px 0 8px;letter-spacing:-.03em;
  text-shadow:0 2px 14px rgba(10,132,255,.25);}
.sndgir-badge{display:inline-block;padding:3px 12px;border-radius:999px;font-size:.72rem;font-weight:600;
  border:1px solid rgba(255,255,255,.08);}
.b-vert{background:rgba(48,209,88,.15);color:var(--ok)}
.b-bleu{background:rgba(10,132,255,.15);color:var(--acc)}
.b-jaune{background:rgba(255,159,10,.15);color:var(--warn)}
.b-rouge{background:rgba(255,69,58,.15);color:var(--bad)}

/* ---------- Boutons en relief ---------- */
div[data-testid="stButton"]>button,div[data-testid="stFormSubmitButton"]>button,
div[data-testid="stDownloadButton"]>button{
  border-radius:14px!important;color:#fff!important;font-weight:600!important;
  background:linear-gradient(180deg,#2b8cff 0%,#0A63D6 100%)!important;
  border:1px solid rgba(255,255,255,.22)!important;
  box-shadow:0 1px 0 rgba(255,255,255,.35) inset,0 -2px 0 rgba(0,0,0,.25) inset,
             0 10px 20px -8px rgba(10,132,255,.7),0 4px 8px rgba(0,0,0,.4)!important;
  transition:transform .15s ease,box-shadow .15s ease,filter .15s ease!important;
}
div[data-testid="stButton"]>button:hover,div[data-testid="stFormSubmitButton"]>button:hover,
div[data-testid="stDownloadButton"]>button:hover{
  transform:translateY(-2px);filter:brightness(1.1);
  box-shadow:0 1px 0 rgba(255,255,255,.4) inset,0 -2px 0 rgba(0,0,0,.25) inset,
             0 16px 28px -8px rgba(10,132,255,.85),0 6px 12px rgba(0,0,0,.45)!important;
}
div[data-testid="stButton"]>button:active,div[data-testid="stFormSubmitButton"]>button:active{
  transform:translateY(1px);
  box-shadow:0 2px 6px rgba(0,0,0,.5) inset,0 2px 6px rgba(10,132,255,.4)!important;
}

/* ---------- Champs de saisie (creusés) ---------- */
div[data-baseweb="input"],div[data-baseweb="select"]>div,div[data-baseweb="textarea"],
div[data-testid="stNumberInput"] div[data-baseweb="input"]{
  background:rgba(0,0,0,.28)!important;border-radius:12px!important;
  border:1px solid rgba(255,255,255,.09)!important;
  box-shadow:0 2px 6px rgba(0,0,0,.55) inset,0 1px 0 rgba(255,255,255,.06)!important;
  transition:border-color .2s ease,box-shadow .2s ease;
}
div[data-baseweb="input"]:focus-within,div[data-baseweb="select"]>div:focus-within{
  border-color:var(--acc)!important;
  box-shadow:0 2px 6px rgba(0,0,0,.55) inset,0 0 0 3px rgba(10,132,255,.28)!important;
}
label,div[data-testid="stWidgetLabel"] p{color:#c3cbda!important;font-weight:600!important;font-size:.82rem!important;}

/* ---------- Formulaires & expanders ---------- */
div[data-testid="stForm"]{
  background:var(--glass);border:1px solid var(--edge);border-radius:22px;padding:22px;
  box-shadow:var(--lift);backdrop-filter:blur(22px);
}
div[data-testid="stExpander"]{background:var(--glass);border:1px solid var(--edge)!important;
  border-radius:16px;box-shadow:var(--lift);}

/* ---------- Onglets : segments lumineux ---------- */
div[data-baseweb="tab-list"]{
  gap:6px;background:rgba(0,0,0,.30);padding:6px;border-radius:16px;
  border:1px solid rgba(255,255,255,.07);box-shadow:0 3px 10px rgba(0,0,0,.5) inset;
  overflow-x:auto;
}
button[data-baseweb="tab"]{
  border-radius:11px!important;padding:8px 16px!important;color:var(--txt2)!important;font-weight:600!important;
  transition:all .2s ease;background:transparent!important;
}
button[data-baseweb="tab"]:hover{color:#fff!important;background:rgba(255,255,255,.06)!important;}
button[data-baseweb="tab"][aria-selected="true"]{
  color:#fff!important;
  background:linear-gradient(180deg,rgba(255,255,255,.16),rgba(255,255,255,.06))!important;
  box-shadow:0 1px 0 rgba(255,255,255,.25) inset,0 6px 14px -4px rgba(10,132,255,.5),0 2px 4px rgba(0,0,0,.4);
}
div[data-baseweb="tab-highlight"],div[data-baseweb="tab-border"]{display:none!important;}

/* ---------- Métriques, tableaux, alertes ---------- */
div[data-testid="stMetric"]{background:var(--glass);border:1px solid var(--edge);border-radius:18px;
  padding:16px 18px;box-shadow:var(--lift);}
div[data-testid="stMetricValue"]{font-weight:800;letter-spacing:-.02em;}
div[data-testid="stDataFrame"]{border-radius:16px;overflow:hidden;border:1px solid var(--edge);
  box-shadow:var(--lift);}
div[data-testid="stAlert"]{border-radius:14px;border:1px solid var(--edge);
  backdrop-filter:blur(14px);box-shadow:0 8px 20px -10px rgba(0,0,0,.6);}

/* ---------- Barre latérale ---------- */
section[data-testid="stSidebar"]{
  background:linear-gradient(180deg,rgba(14,20,36,.92),rgba(4,6,12,.96));
  border-right:1px solid rgba(255,255,255,.07);
  box-shadow:12px 0 40px -16px rgba(0,0,0,.8);backdrop-filter:blur(24px);
}
section[data-testid="stSidebar"] hr{border-color:rgba(255,255,255,.07);}

/* ---------- Écran de connexion ---------- */
.hero{position:relative;text-align:center;padding:26px 0 8px;}
.hero-logo{
  width:84px;height:84px;margin:0 auto 14px;border-radius:26px;display:flex;align-items:center;justify-content:center;
  font-size:2.3rem;
  background:linear-gradient(145deg,#3b9bff,#5E5CE6 60%,#2a2f8f);
  box-shadow:0 1px 0 rgba(255,255,255,.45) inset,0 -4px 8px rgba(0,0,0,.3) inset,
             0 24px 46px -10px rgba(10,132,255,.7),0 0 0 1px rgba(255,255,255,.12);
  animation:flotte 5s ease-in-out infinite;
}
.hero h1{margin:.1rem 0 .2rem;font-size:2.4rem;}
.hero p{color:var(--txt2);margin:0 0 6px;font-size:.95rem;}
.hero-puces{display:flex;gap:8px;justify-content:center;flex-wrap:wrap;margin-top:10px;}
.hero-puces span{font-size:.72rem;font-weight:600;color:#cfd8e8;padding:4px 12px;border-radius:999px;
  background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.1);}
@keyframes flotte{0%,100%{transform:translateY(0) rotateX(0)}50%{transform:translateY(-8px) rotateX(6deg)}}
@keyframes entree{from{opacity:0;transform:translateY(14px)}to{opacity:1;transform:none}}
.block-container>div{animation:entree .5s ease both;}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
@media (max-width:640px){.k-valeur{font-size:1.4rem}.hero h1{font-size:1.8rem}}
#MainMenu,footer{visibility:hidden;}
::-webkit-scrollbar{width:10px;height:10px}
::-webkit-scrollbar-thumb{background:rgba(255,255,255,.14);border-radius:10px}
</style>
"""


def injecter_theme() -> None:
    st.markdown(CSS_THEME_3D, unsafe_allow_html=True)


def carte_kpi(titre: str, valeur: str, sous_texte: str = "", niveau: str = "bleu") -> None:
    st.markdown(f"""
    <div class="sndgir-card k-{niveau}">
        <div class="k-titre">{titre}</div>
        <div class="k-valeur">{valeur}</div>
        <span class="sndgir-badge b-{niveau}">{sous_texte}</span>
    </div>
    """, unsafe_allow_html=True)


def badge_canal(canal: str) -> str:
    correspondance = {"VERT": "vert", "BLEU": "bleu", "JAUNE": "jaune", "ROUGE": "rouge"}
    return f'<span class="sndgir-badge b-{correspondance.get(canal, "bleu")}">{canal}</span>'


def graphique_barres(df: pd.DataFrame, x: str, y: str, titre: str = ""):
    """Graphique barres Plotly — repli automatique sur st.bar_chart si absent."""
    if df.empty:
        st.info("Aucune donnée à représenter.")
        return
    if PLOTLY_OK:
        figure = px.bar(df, x=x, y=y, title=titre, template="plotly_dark",
                        color_discrete_sequence=["#0A84FF"])
        figure.update_traces(marker_line_width=0, opacity=0.92)
        figure.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                             font_family="Inter", margin=dict(l=10, r=10, t=50, b=10),
                             xaxis=dict(gridcolor="rgba(255,255,255,0.05)"),
                             yaxis=dict(gridcolor="rgba(255,255,255,0.07)"))
        st.plotly_chart(figure, use_container_width=True)
    else:
        st.caption(titre)
        st.bar_chart(df.set_index(x)[y])


def graphique_camembert(df: pd.DataFrame, noms: str, valeurs: str, titre: str = ""):
    if df.empty:
        st.info("Aucune donnée à représenter.")
        return
    if PLOTLY_OK:
        figure = px.pie(df, names=noms, values=valeurs, title=titre, hole=0.55,
                        template="plotly_dark")
        figure.update_traces(marker=dict(line=dict(color="#04060C", width=3)))
        figure.update_layout(paper_bgcolor="rgba(0,0,0,0)", font_family="Inter",
                             margin=dict(l=10, r=10, t=50, b=10))
        st.plotly_chart(figure, use_container_width=True)
    else:
        st.caption(titre)
        st.dataframe(df, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# INTERFACE STREAMLIT
# ══════════════════════════════════════════════════════════════════════════════
def ecran_connexion() -> bool:
    """Écran d'authentification multi-tenant. Retourne True si connecté."""
    st.markdown(f"""
    <div class="hero">
        <div class="hero-logo">🏦</div>
        <h1>{APP_NAME}</h1>
        <p>Comptabilité SYSCOHADA · Transit &amp; Douanes · Fiscalité DGI</p>
        <div class="hero-puces"><span>🔒 Multi-tenant sécurisé</span><span>📜 Audit infalsifiable</span>
        <span>🇨🇮 Côte d'Ivoire · UEMOA</span></div>
    </div>
    """, unsafe_allow_html=True)
    tenants = lister_tenants()
    if tenants.empty:
        st.error("Aucun tenant disponible — la base n'a pas été initialisée.")
        return False

    colonne_gauche, colonne_milieu, colonne_droite = st.columns([1, 1.2, 1])
    with colonne_milieu:
        with st.form("form_connexion"):
            options = {int(ligne["id"]): f"{ligne['raison_sociale']} ({ligne['slug']})"
                       for _, ligne in tenants.iterrows()}
            tenant_id = st.selectbox("Entreprise (tenant)", list(options.keys()),
                                     format_func=lambda cle: options[cle])
            username = st.text_input("Identifiant")
            mot_de_passe = st.text_input("Mot de passe", type="password")
            valide = st.form_submit_button("Se connecter", use_container_width=True)
        if os.getenv("SNDGIR_DEMO", "").lower() in ("1", "true", "oui"):
            st.caption("Démo : " + " · ".join(f"{u}/{m}" for u, m in MOTS_DE_PASSE_DEMO.items()))

        if valide:
            fiche = authentifier(int(tenant_id), username, mot_de_passe)
            if not fiche:
                if connexion_bloquee(int(tenant_id), username):
                    st.error(f"Trop de tentatives échouées. Réessayez dans "
                             f"{CONNEXIONS_FENETRE_MIN} minutes.")
                else:
                    st.error("Identifiants invalides.")
                return False
            st.session_state.update({
                "authentifie": True,
                "tenant_id": fiche["tenant_id"],
                "username": fiche["username"],
                "user_role": fiche["role"],
            })
            st.rerun()
    return bool(st.session_state.get("authentifie"))


def barre_laterale() -> str:
    """Barre latérale : identité, rôle, clés API et déconnexion."""
    tenant = lister_tenants()
    nom_tenant = tenant.loc[tenant["id"] == tenant_courant(), "raison_sociale"]
    with st.sidebar:
        st.markdown(f"### 🏦 {APP_NAME}")
        st.markdown(f"**Entreprise :** {nom_tenant.iloc[0] if not nom_tenant.empty else '—'}")
        st.markdown(f"**Utilisateur :** {st.session_state.get('username', '—')}")
        st.markdown(f"**Rôle :** {st.session_state.get('user_role', '—')}")
        st.divider()
        st.text_input("Clé API Groq (session)", type="password", key="groq_api_key_input",
                      value=st.session_state.get("groq_api_key", ""))
        st.session_state["groq_api_key"] = st.session_state.get("groq_api_key_input", "")
        st.divider()
        if st.session_state.get("user_role") == "Administrateur Système":
            if "comptes_demo" not in st.session_state:
                st.session_state["comptes_demo"] = comptes_mot_de_passe_demo()
            if st.session_state["comptes_demo"]:
                st.warning("⚠️ Mots de passe de démonstration encore actifs : "
                           + ", ".join(st.session_state["comptes_demo"])
                           + ". Changez-les (Administration → Utilisateurs).")
        with st.expander("🔑 Changer mon mot de passe"):
            with st.form("form_mon_mdp"):
                ancien = st.text_input("Mot de passe actuel", type="password")
                nouveau = st.text_input(
                    f"Nouveau mot de passe ({MOT_DE_PASSE_MIN} caractères min., lettres et chiffres)",
                    type="password")
                change = st.form_submit_button("Changer", use_container_width=True)
            if change:
                try:
                    changer_mon_mot_de_passe(ancien, nouveau)
                    st.session_state.pop("comptes_demo", None)
                    st.success("Mot de passe modifié.")
                except ValueError as exc:
                    st.error(str(exc))
        st.divider()
        integre, nb_lignes, message = verifier_audit()
        st.caption(f"Audit : {nb_lignes} entrées")
        st.caption(message if integre else f"⚠️ {message}")
        if st.button("Se déconnecter", use_container_width=True):
            journaliser("deconnexion", "utilisateurs", st.session_state.get("username", ""), "")
            st.session_state.clear()
            st.rerun()
    return str(st.session_state.get("user_role", ""))


def exiger(permission: str) -> bool:
    """Contrôle d'accès : affiche un refus et journalise si non autorisé."""
    role = st.session_state.get("user_role", "")
    if a_permission(role, permission):
        return True
    st.error(f"⛔ Accès refusé : le rôle « {role} » n'a pas la permission `{permission}`.")
    journaliser("acces_refuse", "rbac", permission, f"permission={permission}")
    return False


def onglet_tableau_de_bord() -> None:
    st.subheader("📊 Tableau de bord financier")
    dossiers = lister_dossiers()
    etats = etats_financiers()

    colonnes = st.columns(4)
    with colonnes[0]:
        carte_kpi("Dossiers actifs", f"{len(dossiers)}", "tous statuts", "bleu")
    with colonnes[1]:
        carte_kpi("Chiffre d'affaires", f"{etats['produits']:,.0f}", "FCFA", "vert")
    with colonnes[2]:
        niveau = "vert" if etats["resultat"] >= 0 else "rouge"
        carte_kpi("Résultat net", f"{etats['resultat']:,.0f}", "FCFA", niveau)
    with colonnes[3]:
        solde = dossiers["solde_du"].sum() if not dossiers.empty else 0
        carte_kpi("Soldes à recouvrer", f"{solde:,.0f}", "FCFA", "jaune")

    colonne_gauche, colonne_droite = st.columns(2)
    with colonne_gauche:
        if not dossiers.empty:
            repartition = (dossiers.groupby("statut", as_index=False)["total_facture"]
                           .sum().rename(columns={"statut": "Statut",
                                                  "total_facture": "Montant"}))
            graphique_barres(repartition, "Statut", "Montant", "Montant par statut")
    with colonne_droite:
        if not dossiers.empty:
            canaux = (dossiers.groupby("canal_risque", as_index=False).size()
                      .rename(columns={"canal_risque": "Canal", "size": "Dossiers"}))
            graphique_camembert(canaux, "Canal", "Dossiers", "Canaux de risque")
    st.dataframe(
        dossiers[["reference", "client", "regime", "valeur_caf_xof", "droits_douane",
                  "total_facture", "statut", "canal_risque"]],
        use_container_width=True,
    )


def onglet_comptabilite() -> None:
    if not exiger("compta.view"):
        return
    st.subheader("📒 Comptabilité SYSCOHADA révisé")
    onglet_ecriture, onglet_balance, onglet_livre, onglet_journaux, onglet_etats = st.tabs(
        ["Saisie d'écriture", "Balance générale", "Grand livre", "Journaux", "États financiers"]
    )
    with onglet_ecriture:
        if exiger("compta.saisie"):
            st.caption("Partie double stricte : débits = crédits, sinon l'écriture est refusée.")
            plan = lire_df("SELECT compte, libelle FROM plan_comptable ORDER BY compte")
            libelles = {ligne["compte"]: f"{ligne['compte']} — {ligne['libelle']}"
                        for _, ligne in plan.iterrows()}
            with st.form("form_ecriture"):
                colonnes = st.columns(3)
                with colonnes[0]:
                    piece = st.text_input("N° de pièce", value=f"OD-{datetime.now():%Y%m%d%H%M%S}")
                    journal = st.selectbox("Journal", ["OD", "ACQ", "VTE", "BAN"])
                with colonnes[1]:
                    date_ecriture = st.date_input("Date")
                    compte = st.selectbox("Compte", list(libelles.keys()),
                                          format_func=lambda c: libelles[c])
                with colonnes[2]:
                    debit = st.number_input("Débit", min_value=0.0, step=1000.0)
                    credit = st.number_input("Crédit", min_value=0.0, step=1000.0)
                libelle = st.text_input("Libellé")
                soumis = st.form_submit_button("Enregistrer l'écriture", use_container_width=True)
            if soumis:
                try:
                    ecrire_piece(piece, journal, [(compte, libelle, debit, credit)],
                                 date_ecriture=date_ecriture.strftime("%Y-%m-%d"))
                    st.success(f"Écriture {piece} enregistrée (journal {journal}).")
                except ErreurComptable as exc:
                    st.error(str(exc))
    with onglet_balance:
        balance = balance_generale()
        if balance.empty:
            st.info("Aucune écriture enregistrée.")
        else:
            ecart = round(float(balance["debit"].sum() - balance["credit"].sum()), 2)
            if ecart == 0:
                st.success("✅ Balance équilibrée — cohérence comptable vérifiée.")
            else:
                st.error(f"⚠️ Balance déséquilibrée (écart {ecart:,.0f} FCFA).")
            st.dataframe(balance, use_container_width=True)
    with onglet_livre:
        plan = lire_df("SELECT compte, libelle FROM plan_comptable ORDER BY compte")
        if plan.empty:
            st.info("Plan comptable vide.")
        else:
            libelles_livre = {ligne["compte"]: f"{ligne['compte']} — {ligne['libelle']}"
                              for _, ligne in plan.iterrows()}
            compte_filtre = st.selectbox("Compte", list(libelles_livre.keys()),
                                         format_func=lambda c: libelles_livre[c],
                                         key="livre_compte")
            st.dataframe(grand_livre(compte_filtre), use_container_width=True)
    with onglet_journaux:
        code = st.selectbox("Journal", ["ACQ", "VTE", "BAN", "OD"], key="choix_journal")
        st.dataframe(journal_ecritures(code), use_container_width=True)
    with onglet_etats:
        if exiger("etats.view"):
            etats = etats_financiers()
            colonne_gauche, colonne_droite = st.columns(2)
            with colonne_gauche:
                st.markdown("##### Compte de résultat")
                st.dataframe(pd.DataFrame([
                    {"Rubrique": "Produits (classe 7)", "Montant": etats["produits"]},
                    {"Rubrique": "Charges (classe 6)", "Montant": etats["charges"]},
                    {"Rubrique": "RÉSULTAT NET", "Montant": etats["resultat"]},
                ]), use_container_width=True, hide_index=True)
            with colonne_droite:
                st.markdown("##### Bilan synthétique")
                bilan = ([{"Rubrique": cle, "Montant": valeur}
                          for cle, valeur in etats["actif"].items()] +
                         [{"Rubrique": cle, "Montant": valeur}
                          for cle, valeur in etats["passif"].items()])
                st.dataframe(pd.DataFrame(bilan), use_container_width=True, hide_index=True)
            tva = calculer_tva()
            st.markdown("##### Position TVA")
            st.dataframe(pd.DataFrame([
                {"Rubrique": "TVA collectée (445200)", "Montant": tva["tva_collectee"]},
                {"Rubrique": "TVA déductible (445220)", "Montant": tva["tva_deductible"]},
                {"Rubrique": "TVA à payer", "Montant": tva["tva_a_payer"]},
            ]), use_container_width=True, hide_index=True)


def onglet_transit() -> None:
    if not exiger("transit.view"):
        return
    st.subheader("🚢 Transit, Import-Export & Douanes")
    (onglet_dossiers, onglet_calcul, onglet_manifestes, onglet_surestaries, onglet_documents,
     onglet_tarif) = st.tabs(["Dossiers", "Calculateur douanier", "Manifestes & B/L",
                              "Surestaries", "Documents PDF", "Tarif & taxes"])

    with onglet_dossiers:
        if exiger("transit.creer"):
            with st.expander("➕ Nouveau dossier d'importation", expanded=False):
                articles = lire_df(
                    "SELECT nom, dd FROM articles WHERE tenant_id=? ORDER BY nom",
                    (tenant_courant(),),
                )
                with st.form("form_dossier"):
                    colonnes = st.columns(3)
                    with colonnes[0]:
                        reference = st.text_input("Référence",
                                                  value=f"IMP-{datetime.now():%Y%m%d%H%M}")
                        client = st.text_input("Client")
                        bl = st.text_input("Connaissement (B/L)")
                    with colonnes[1]:
                        article = (st.selectbox("Article", articles["nom"].tolist())
                                   if not articles.empty else st.text_input("Article"))
                        regime = st.selectbox("Régime douanier", list(REGIMES_DOUANIERS.keys()),
                                              format_func=lambda r: f"{r} — {REGIMES_DOUANIERS[r]}")
                        dd_defaut = (float(articles.loc[articles["nom"] == article, "dd"].iloc[0])
                                     if not articles.empty else 20.0)
                        dd_pct = st.number_input("Taux DD (%)", value=dd_defaut, min_value=0.0,
                                                 max_value=100.0)
                        code_sh = st.text_input("Code SH (facultatif)",
                                                placeholder="8471.30.00.00 — vide : code de l'article")
                        quantite = st.number_input("Quantité taxable (kg, litres, unités)",
                                                   min_value=0.0, step=1.0)
                    with colonnes[2]:
                        fob = st.number_input("Valeur FOB (FCFA)", min_value=0.0, step=100_000.0)
                        fret = st.number_input("Fret (FCFA)", min_value=0.0, step=10_000.0)
                        assurance = st.number_input("Assurance (FCFA)", min_value=0.0,
                                                    step=10_000.0)
                        email = st.text_input("E-mail client")
                        telephone = st.text_input("Téléphone client")
                        fournisseur_nouveau = st.checkbox("Fournisseur sans historique",
                                                          value=True)
                        sensible = st.checkbox("Marchandise sensible / droits élevés")
                    soumis = st.form_submit_button("Créer le dossier", use_container_width=True)
                if soumis and client and reference:
                    try:
                        resultat = creer_dossier(reference, client, bl, str(article), regime, fob,
                                                 fret, assurance, dd_pct, email, telephone,
                                                 fournisseur_nouveau, sensible,
                                                 code_sh=code_sh, quantite=quantite)
                    except ValueError as exc:
                        st.error(str(exc))
                    else:
                        st.success(f"Dossier {reference} créé — total facture "
                                   f"{resultat['total_facture']:,.0f} FCFA.")
                        if resultat["droits"]["suspendu"]:
                            st.info(resultat["droits"]["note_regime"])
                        if resultat["tarif"]:
                            st.caption(f"Tarif {formater_sh(resultat['tarif']['code_sh'])} : "
                                       f"DD de référence {float(resultat['tarif']['dd']):g} %")
                        for taxe in resultat["taxes"]["lignes"]:
                            st.caption(f"Taxe spécifique « {taxe['libelle']} » : "
                                       f"{taxe['montant']:,.0f} FCFA ({taxe['detail']})")
                        st.markdown(
                            f"Canal de sélectivité : "
                            f"{badge_canal(resultat['risque']['canal'])} "
                            f"(score {resultat['risque']['score']})", unsafe_allow_html=True,
                        )
                        for motif in resultat["risque"]["motifs"]:
                            st.caption(f"• {motif}")
        dossiers = lister_dossiers()
        if dossiers.empty:
            st.info("Aucun dossier enregistré.")
        else:
            st.dataframe(
                dossiers[["id", "reference", "client", "bl", "regime", "valeur_caf_xof",
                          "droits_douane", "total_facture", "solde_du", "statut",
                          "canal_risque"]],
                use_container_width=True,
            )
            if exiger("transit.valider"):
                colonnes = st.columns(2)
                with colonnes[0]:
                    dossier_id = st.selectbox("Dossier à mettre à jour", dossiers["id"].tolist(),
                                              key="maj_dossier_id")
                with colonnes[1]:
                    statut = st.selectbox("Nouveau statut", STATUTS_DOSSIER, key="maj_statut")
                if st.button("Mettre à jour le statut", use_container_width=True):
                    try:
                        maj_statut_dossier(int(dossier_id), statut)
                    except ValueError as exc:
                        st.error(str(exc))
                    else:
                        st.success("Statut mis à jour.")
                        st.rerun()
            with st.expander("✅ Conformité du dossier (FDI, BSC, Certificat de Conformité…)"):
                dossier_conf = st.selectbox(
                    "Dossier", dossiers["id"].tolist(), key="conf_dossier_id",
                    format_func=lambda cle: str(
                        dossiers.loc[dossiers["id"] == cle, "reference"].iloc[0]))
                controle = controle_conformite(int(dossier_conf))
                recues = lister_documents_dossier(int(dossier_conf)).set_index("code")
                for code in controle["requis"]:
                    if code in recues.index:
                        fiche = recues.loc[code]
                        st.markdown(f"✅ **{DOCUMENTS_DOSSIER[code]}** — {fiche['reference']} "
                                    f"({fiche['statut']})")
                    else:
                        st.markdown(f"⬜ **{DOCUMENTS_DOSSIER[code]}** — manquant")
                if controle["complet"]:
                    st.success("Dossier conforme : le BAE peut être émis.")
                else:
                    st.warning("Pièces manquantes : "
                               + ", ".join(controle["libelles_manquants"]) + ".")
                if exiger("transit.creer"):
                    with st.form("form_document_dossier"):
                        colonnes_doc = st.columns(3)
                        with colonnes_doc[0]:
                            code_doc = st.selectbox(
                                "Pièce", list(DOCUMENTS_DOSSIER.keys()),
                                format_func=lambda cle: DOCUMENTS_DOSSIER[cle])
                        with colonnes_doc[1]:
                            reference_doc = st.text_input("Numéro / référence (ou motif)")
                        with colonnes_doc[2]:
                            statut_doc = st.selectbox("État", list(DOCUMENT_STATUTS))
                        enregistrer_doc = st.form_submit_button("Enregistrer la pièce",
                                                                use_container_width=True)
                    if enregistrer_doc:
                        try:
                            enregistrer_document_dossier(int(dossier_conf), code_doc,
                                                         reference_doc, statut_doc)
                        except ValueError as exc:
                            st.error(str(exc))
                        else:
                            st.success("Pièce enregistrée.")
                            st.rerun()

    with onglet_calcul:
        st.caption("Simulation des droits et taxes par régime douanier (TVA paramétrable).")
        colonnes = st.columns(4)
        with colonnes[0]:
            valeur_caf = st.number_input("Valeur CAF (FCFA)", min_value=0.0, step=100_000.0,
                                         key="calc_caf")
        with colonnes[1]:
            dd_simule = st.number_input("Taux DD (%)", value=20.0, min_value=0.0, max_value=100.0,
                                        key="calc_dd")
        with colonnes[2]:
            regime_simule = st.selectbox("Régime", list(REGIMES_DOUANIERS.keys()),
                                         format_func=lambda r: f"{r} — {REGIMES_DOUANIERS[r]}",
                                         key="calc_regime")
        with colonnes[3]:
            tva_simule = st.number_input("TVA (%)", value=TAUX_TVA, min_value=0.0, max_value=30.0,
                                         key="calc_tva")
        colonnes_taxes = st.columns(2)
        with colonnes_taxes[0]:
            code_simule = st.text_input("Code SH (pour les taxes spécifiques, facultatif)",
                                        key="calc_sh")
        with colonnes_taxes[1]:
            quantite_simulee = st.number_input("Quantité taxable (kg, litres, unités)",
                                               min_value=0.0, key="calc_qte")
        taxes_simulees = {"lignes": [], "total": 0.0}
        if code_simule.strip() and regime_simule not in REGIMES_SUSPENDUS:
            try:
                taxes_simulees = calculer_taxes_specifiques(code_simule, valeur_caf,
                                                            quantite_simulee)
            except ValueError as exc:
                st.error(str(exc))
        calcul = calculer_droits(valeur_caf, dd_simule, regime_simule, tva_simule,
                                 autres_taxes=taxes_simulees["total"])
        if calcul["suspendu"]:
            st.info(calcul["note_regime"])
        st.dataframe(pd.DataFrame([
            {"Rubrique": "Droits de douane (DD)", "Montant": calcul["droits_douane"]},
            {"Rubrique": f"Redevance statistique ({TAUX_RS_PCT:g} %)",
             "Montant": calcul["redevance_statistique"]},
            {"Rubrique": f"Prélèvement UEMOA ({PC_UEMOA_PCT:g} %)",
             "Montant": calcul["pc_uemoa"]},
            {"Rubrique": f"Prélèvement CEDEAO ({PCC_CEDEAO_PCT:g} %)",
             "Montant": calcul["pcc_cedeao"]},
            *[{"Rubrique": f"Taxe spécifique : {taxe['libelle']}", "Montant": taxe["montant"]}
              for taxe in taxes_simulees["lignes"]],
            {"Rubrique": f"TVA ({tva_simule:.0f} %) sur {calcul['base_tva']:,.0f}",
             "Montant": calcul["tva"]},
            {"Rubrique": "TOTAL DROITS & TAXES", "Montant": calcul["total_droits_taxes"]},
        ]), use_container_width=True, hide_index=True)
        st.caption("Taux indicatifs : à confirmer avec le tarif de la Douane en vigueur.")
        analyse = scorer_risque(valeur_caf, dd_simule, dd_simule)
        st.markdown("##### Sélectivité des risques", unsafe_allow_html=True)
        st.markdown(f"Score {analyse['score']} → {badge_canal(analyse['canal'])} "
                    f"{analyse['libelle_canal']}", unsafe_allow_html=True)

    with onglet_manifestes:
        colonne_gauche, colonne_droite = st.columns(2)
        with colonne_gauche:
            st.markdown("##### Nouveau manifeste maritime / aérien")
            with st.form("form_manifeste"):
                numero = st.text_input("Numéro de manifeste")
                navire = st.text_input("Navire / vol")
                armateur = st.text_input("Armateur / compagnie")
                date_arrivee = st.date_input("Date d'arrivée")
                port = st.text_input("Port", value="Abidjan")
                soumis = st.form_submit_button("Créer le manifeste", use_container_width=True)
            if soumis and numero:
                creer_manifeste(numero, navire, armateur,
                                date_arrivee.strftime("%Y-%m-%d"), port)
                st.success(f"Manifeste {numero} créé.")
                st.rerun()
            st.dataframe(lister_manifestes(), use_container_width=True)
        with colonne_droite:
            st.markdown("##### Nouveau connaissement (B/L)")
            manifestes = lister_manifestes()
            if manifestes.empty:
                st.info("Créez d'abord un manifeste.")
            else:
                options = {int(ligne["id"]): ligne["numero"] for _, ligne in manifestes.iterrows()}
                with st.form("form_bl"):
                    manifeste_id = st.selectbox("Manifeste", list(options.keys()),
                                                format_func=lambda cle: options[cle])
                    bl = st.text_input("N° de B/L")
                    client = st.text_input("Client")
                    nb_colis = st.number_input("Nombre de colis", min_value=0, step=1)
                    poids = st.number_input("Poids (kg)", min_value=0.0, step=100.0)
                    valeur_usd = st.number_input("Valeur USD", min_value=0.0, step=1000.0)
                    date_franchise = st.date_input("Date de franchise armateur")
                    soumis_bl = st.form_submit_button("Enregistrer le B/L",
                                                      use_container_width=True)
                if soumis_bl and bl:
                    enregistrer_connaissement(int(manifeste_id), bl, client, int(nb_colis),
                                              poids, valeur_usd,
                                              date_franchise.strftime("%Y-%m-%d"))
                    st.success(f"B/L {bl} enregistré.")
                    st.rerun()
        st.markdown("##### Connaissements et apurement")
        connaissements = lister_connaissements()
        st.dataframe(connaissements, use_container_width=True)
        if not connaissements.empty and exiger("transit.valider"):
            non_apures = connaissements.loc[connaissements["apure"] == 0]
            if not non_apures.empty:
                options_bl = {int(ligne["id"]): f"{ligne['bl']} — {ligne['client']}"
                              for _, ligne in non_apures.iterrows()}
                bl_id = st.selectbox("B/L à apurer", list(options_bl.keys()),
                                     format_func=lambda cle: options_bl[cle], key="bl_apurer")
                if st.button("Apurer le connaissement", use_container_width=True):
                    apurer_connaissement(int(bl_id))
                    st.success("Connaissement apuré.")
                    st.rerun()
            if st.button("Apurement automatique des manifestes", use_container_width=True,
                         key="apurer_manifeste"):
                for identifiant in connaissements["manifeste_id"].dropna().unique():
                    apurer_manifeste(int(identifiant))
                st.success("Manifestes apurés automatiquement.")
                st.rerun()

    with onglet_surestaries:
        st.caption("Surestaries portuaires : pénalités journalières armateur (USD → FCFA).")
        colonnes = st.columns(4)
        with colonnes[0]:
            date_franchise = st.date_input("Fin de franchise armateur")
        with colonnes[1]:
            date_sortie = st.date_input("Date de sortie effective du port")
        with colonnes[2]:
            penalite_usd = st.number_input("Pénalité / jour (USD)", min_value=0.0, step=50.0,
                                           value=250.0)
        with colonnes[3]:
            taux_defaut = dernier_taux("USD") or 605.0
            taux_usd = st.number_input("Taux USD → FCFA", min_value=1.0,
                                       value=float(taux_defaut), step=1.0)
        if st.button("Calculer les surestaries", use_container_width=True):
            try:
                resultat = calculer_surestaries(date_franchise.strftime("%Y-%m-%d"),
                                                date_sortie.strftime("%Y-%m-%d"),
                                                penalite_usd, taux_usd)
                st.dataframe(pd.DataFrame([
                    {"Rubrique": "Jours de retard", "Valeur": resultat["jours_retard"]},
                    {"Rubrique": "Montant USD", "Valeur": f"{resultat['montant_usd']:,.2f} USD"},
                    {"Rubrique": "Taux appliqué", "Valeur": f"{resultat['taux_usd_xof']:,.2f}"},
                    {"Rubrique": "MONTANT SURESTARIES",
                     "Valeur": f"{resultat['montant_xof']:,.0f} FCFA"},
                ]), use_container_width=True, hide_index=True)
                executer(
                    "INSERT INTO surestaries (tenant_id, bl, jours_franchise, jours_retard,"
                    " penalite_jour_usd, taux_change, montant_xof, date_calcul, created_by)"
                    " VALUES (?,?,?,?,?,?,?,?,?)",
                    (tenant_courant(), "N/A", 0, resultat["jours_retard"], penalite_usd,
                     resultat["taux_usd_xof"], resultat["montant_xof"], maintenant(),
                     st.session_state.get("username", "système")),
                )
                st.info("Calcul enregistré — comptabilisez la charge via l'onglet Documents PDF.")
            except ValueError as exc:
                st.error(str(exc))
        st.dataframe(lire_df(
            "SELECT bl, jours_retard, penalite_jour_usd, montant_xof, date_calcul FROM surestaries"
            " WHERE tenant_id=? ORDER BY id DESC", (tenant_courant(),),
        ), use_container_width=True)

    with onglet_documents:
        dossiers = lister_dossiers()
        if dossiers.empty:
            st.info("Aucun dossier : créez-en un pour générer les documents officiels.")
        else:
            options = {int(ligne["id"]): f"{ligne['reference']} — {ligne['client']}"
                       for _, ligne in dossiers.iterrows()}
            dossier_id = st.selectbox("Dossier", list(options.keys()),
                                      format_func=lambda cle: options[cle], key="doc_dossier")
            dossier = dossiers.loc[dossiers["id"] == dossier_id].iloc[0].to_dict()
            ligne_bae, ligne_facture, ligne_ecritures = st.columns(3)
            with ligne_bae:
                if st.button("📄 Générer le BAE (scellé SHA-256)", use_container_width=True):
                    try:
                        contenu, empreinte = generer_bae(dossier)
                        st.session_state["bae_pdf"] = contenu
                        st.session_state["bae_empreinte"] = empreinte
                    except (RuntimeError, ValueError) as exc:
                        st.session_state.pop("bae_pdf", None)
                        st.error(str(exc))
                if st.session_state.get("bae_pdf"):
                    st.download_button("⬇️ Télécharger le BAE", st.session_state["bae_pdf"],
                                       f"BAE_{dossier['reference']}.pdf", "application/pdf",
                                       use_container_width=True)
                    st.caption(f"Sceau : `{st.session_state.get('bae_empreinte', '')[:32]}...`")
            with ligne_facture:
                honoraires = st.number_input("Honoraires HT (FCFA)", min_value=0.0,
                                             step=10_000.0, value=500_000.0, key="fact_honoraires")
                fret_fact = st.number_input("Fret facturé (FCFA)", min_value=0.0,
                                            step=10_000.0, key="fact_fret")
                surestaries_fact = st.number_input("Surestaries refacturées (FCFA)", min_value=0.0,
                                                   step=10_000.0, key="fact_surestaries")
                if st.button("🧾 Générer la facture transitaire", use_container_width=True):
                    try:
                        st.session_state["facture_pdf"] = generer_facture_transitaire(
                            dossier, honoraires, fret_fact, surestaries_fact)
                    except RuntimeError as exc:
                        st.error(str(exc))
                if st.session_state.get("facture_pdf"):
                    st.download_button("⬇️ Télécharger la facture",
                                       st.session_state["facture_pdf"],
                                       f"FACTURE_{dossier['reference']}.pdf", "application/pdf",
                                       use_container_width=True)
            with ligne_ecritures:
                st.markdown("##### Écritures automatiques")
                if exiger("compta.saisie"):
                    if st.button("📒 Comptabiliser les flux du dossier", use_container_width=True):
                        try:
                            ecritures_frais_transit(
                                dossier["reference"], honoraires,
                                debours_douaniers=float(dossier["droits_douane"] or 0),
                                fret=fret_fact, surestaries=surestaries_fact,
                                client=str(dossier["client"]),
                            )
                            ecritures_quittance_caisse(dossier["reference"],
                                                       float(dossier["solde_du"] or 0))
                            st.success("Écritures de vente et d'encaissement générées.")
                            st.rerun()
                        except ErreurComptable as exc:
                            st.error(str(exc))

    with onglet_tarif:
        peut_gerer = a_permission(st.session_state.get("user_role", ""), "tarif.gerer")
        st.caption("Recherche par début de code SH (chiffres) ou par désignation (texte).")
        recherche = st.text_input("Recherche dans le tarif", key="tarif_recherche")
        resultats = rechercher_tarif(recherche)
        if resultats.empty:
            st.info("Aucune ligne dans le tarif."
                    + (" Importez votre tarif ci-dessous." if peut_gerer
                       else " Demandez à l'administrateur de l'importer."))
        else:
            st.dataframe(resultats[["code", "designation", "dd", "unite"]],
                         use_container_width=True, hide_index=True)
            st.caption(f"{len(resultats)} ligne(s) affichée(s) (200 au maximum).")

        st.markdown("##### Taxes spécifiques / accises")
        taxes_liste = lister_taxes_specifiques()
        if taxes_liste.empty:
            st.caption("Aucune taxe spécifique définie : seuls DD, redevance statistique, "
                       "prélèvements et TVA sont calculés.")
        else:
            st.dataframe(taxes_liste.assign(mode=taxes_liste["mode"].map(MODES_TAXE_SPECIFIQUE))
                         [["prefixe_sh", "libelle", "mode", "valeur", "unite"]],
                         use_container_width=True, hide_index=True)

        if peut_gerer:
            st.markdown("##### Importer le tarif douanier (CSV)")
            st.caption("Colonnes : code_sh, designation, dd (en %), unite. Séparateur « ; » ou « , ». "
                       "Exportez le tarif officiel, adaptez les colonnes puis importez. "
                       "Les lignes existantes sont mises à jour.")
            st.download_button("⬇️ Modèle de fichier CSV", MODELE_TARIF_CSV.encode("utf-8-sig"),
                               "modele_tarif_douanier.csv", "text/csv")
            fichier = st.file_uploader("Fichier CSV du tarif", type=["csv"], key="tarif_csv")
            if fichier is not None and st.button("Importer le fichier", key="tarif_importer"):
                try:
                    bilan = importer_tarif_csv(fichier.getvalue())
                except ValueError as exc:
                    st.error(str(exc))
                else:
                    st.success(f"{bilan['importees']} ligne(s) importée(s), "
                               f"{bilan['ignorees']} ignorée(s).")
                    if bilan["hors_tranches"]:
                        st.warning(f"{bilan['hors_tranches']} ligne(s) ont un DD hors des tranches "
                                   f"habituelles {', '.join(f'{t:g}' for t in TRANCHES_DD)} % : "
                                   "à vérifier.")
                    for erreur in bilan["erreurs"]:
                        st.caption(erreur)

            st.markdown("##### Ajouter une taxe spécifique / accise")
            with st.form("form_taxe_specifique", clear_on_submit=True):
                colonnes_taxe = st.columns(5)
                with colonnes_taxe[0]:
                    prefixe = st.text_input("Préfixe SH", placeholder="ex. 2203")
                with colonnes_taxe[1]:
                    libelle_taxe = st.text_input("Libellé")
                with colonnes_taxe[2]:
                    mode_taxe = st.selectbox("Calcul", list(MODES_TAXE_SPECIFIQUE.keys()),
                                             format_func=lambda cle: MODES_TAXE_SPECIFIQUE[cle])
                with colonnes_taxe[3]:
                    valeur_taxe = st.number_input("Valeur (% ou FCFA / unité)", min_value=0.0)
                with colonnes_taxe[4]:
                    unite_taxe = st.text_input("Unité", placeholder="kg, litre…")
                ajout = st.form_submit_button("Enregistrer la taxe", use_container_width=True)
            if ajout:
                try:
                    ajouter_taxe_specifique(prefixe, libelle_taxe, mode_taxe, valeur_taxe,
                                            unite_taxe)
                except ValueError as exc:
                    st.error(str(exc))
                else:
                    st.success("Taxe enregistrée.")
                    st.rerun()
            if not taxes_liste.empty:
                colonnes_sup = st.columns([3, 1])
                with colonnes_sup[0]:
                    a_supprimer = st.selectbox(
                        "Supprimer une taxe", taxes_liste["id"].tolist(),
                        format_func=lambda cle: str(
                            taxes_liste.loc[taxes_liste["id"] == cle, "libelle"].iloc[0]))
                with colonnes_sup[1]:
                    st.write("")
                    if st.button("Supprimer", key="taxe_supprimer"):
                        try:
                            supprimer_taxe_specifique(int(a_supprimer))
                        except ValueError as exc:
                            st.error(str(exc))
                        else:
                            st.rerun()


def onglet_ia() -> None:
    st.subheader("🤖 Assistant IA & OCR / IDP")
    onglet_assistant, onglet_ocr, onglet_communications = st.tabs(
        ["Assistant fiscal & douanier", "Extraction OCR de factures", "Communications"]
    )
    with onglet_assistant:
        st.caption("Assistant expert fiscalité SYSCOHADA et droit douanier ivoirien (Groq).")
        question = st.text_area(
            "Votre question",
            placeholder="Quels documents préparer pour une importation de Chine (régime C100) ?",
        )
        if st.button("🔍 Obtenir une réponse", type="primary", use_container_width=True):
            if not question.strip():
                st.warning("Saisissez une question.")
            else:
                contexte = f"Tenant={tenant_courant()}; dossiers={len(lister_dossiers())}"
                with st.spinner("Analyse en cours…"):
                    reponse, erreurs = poser_question_ia(question, contexte)
                if reponse:
                    st.markdown(reponse)
                else:
                    st.error("Réponse indisponible.")
                    with st.expander("Détails techniques"):
                        st.code("\n".join(erreurs) or "Aucune erreur")
    with onglet_ocr:
        if not exiger("ocr.view"):
            st.stop()
        st.caption("Collez le texte OCR d'une facture fournisseur : extraction + contrôle.")
        texte = st.text_area(
            "Texte de la facture", height=180,
            placeholder="Fournisseur: Shenzhen Ltd\nFacture N°: INV-2025-8891\n"
                        "Date: 12/03/2025\nDésignation: Ordinateurs portables\n"
                        "Total: 12 500 000",
        )
        colonnes = st.columns(2)
        with colonnes[0]:
            montant_declare = st.number_input("Montant déclaré en douane (FCFA)", min_value=0.0,
                                              step=100_000.0, key="ocr_declare")
        with colonnes[1]:
            prix_reference = st.number_input("Prix de référence marché (FCFA)", min_value=0.0,
                                             step=100_000.0, key="ocr_reference")
        if st.button("🔎 Analyser la facture", use_container_width=True):
            extraction = extraire_facture_heuristique(texte)
            controle = cross_check_facture(montant_declare, extraction["montant_extrait"],
                                           prix_reference, extraction["fournisseur"])
            st.markdown("##### Données extraites")
            st.dataframe(pd.DataFrame([
                {"Champ": "Fournisseur", "Valeur": extraction["fournisseur"]},
                {"Champ": "N° facture", "Valeur": extraction["numero_facture"]},
                {"Champ": "Date", "Valeur": extraction["date_facture"]},
                {"Champ": "Montant extrait", "Valeur": f"{extraction['montant_extrait']:,.0f}"},
                {"Champ": "Désignation", "Valeur": extraction["designation"]},
            ]), use_container_width=True, hide_index=True)
            st.markdown("##### Cross-checking")
            if controle["discordance"]:
                for anomalie in controle["anomalies"]:
                    st.error(f"⚠️ {anomalie}")
            else:
                st.success("✅ Aucune discordance significative détectée.")
            enregistrer_extraction_ocr("saisie_manuelle", extraction, controle)
    with onglet_communications:
        if not exiger("communication.rediger"):
            st.stop()
        st.caption("Les brouillons restent « En attente » jusqu'à validation humaine explicite.")
        type_communication = st.selectbox("Type", list(MODELES_COMMUNICATION.keys()))
        colonnes = st.columns(3)
        with colonnes[0]:
            client = st.text_input("Client")
            reference = st.text_input("Référence dossier")
            bl = st.text_input("B/L")
        with colonnes[1]:
            montant = st.number_input("Montant (FCFA)", min_value=0.0, step=10_000.0)
        with colonnes[2]:
            st.write("")
            st.write("")
            if st.button("📝 Rédiger le brouillon", use_container_width=True):
                st.session_state["brouillon"] = rediger_communication(type_communication, {
                    "client": client, "reference": reference, "bl": bl,
                    "montant": f"{montant:,.0f}",
                })
        if st.session_state.get("brouillon"):
            brouillon = st.session_state["brouillon"]
            st.text_area("Aperçu du brouillon", brouillon["corps"], height=200,
                         key="apercu_brouillon")
            if st.button("✅ Valider et autoriser la diffusion", use_container_width=True):
                valider_communication(int(brouillon["id"]))
                st.success("Communication validée — diffusion autorisée.")
                st.rerun()
        st.markdown("##### Historique des communications")
        st.dataframe(lister_communications()[["type", "destinataire", "statut_validation",
                                             "valide_par", "created_at"]],
                     use_container_width=True)


def onglet_portail_client() -> None:
    if not exiger("portail.view"):
        return
    st.subheader("👤 Portail client — suivi des dossiers")
    dossiers = lister_dossiers()
    if dossiers.empty:
        st.info("Aucun dossier à afficher.")
    else:
        st.dataframe(dossiers[["reference", "date", "client", "article", "regime",
                               "total_facture", "solde_du", "statut", "canal_risque"]],
                     use_container_width=True)


def onglet_administration() -> None:
    if not exiger("*"):
        return
    st.subheader("🛡️ Administration, sécurité & piste d'audit")
    onglet_tenants, onglet_utilisateurs, onglet_audit, onglet_taux = st.tabs(
        ["Entreprises (tenants)", "Utilisateurs", "Piste d'audit", "Taux de change"]
    )
    with onglet_tenants:
        with st.form("form_tenant"):
            colonnes = st.columns(3)
            with colonnes[0]:
                slug = st.text_input("Slug")
                raison_sociale = st.text_input("Raison sociale")
            with colonnes[1]:
                pays = st.text_input("Pays", value="Côte d'Ivoire")
                regime = st.selectbox("Régime fiscal",
                                      ["Réel normal", "Réel simplifié", "Synthétique"])
            with colonnes[2]:
                st.write("")
                soumis = st.form_submit_button("Créer l'entreprise", use_container_width=True)
        if soumis and slug and raison_sociale:
            try:
                creer_tenant(slug, raison_sociale, pays, regime)
                st.success(f"Tenant {slug} créé.")
                st.rerun()
            except sqlite3.IntegrityError:
                st.error("Ce slug existe déjà.")
        st.dataframe(lister_tenants(), use_container_width=True)
    with onglet_utilisateurs:
        with st.form("form_utilisateur"):
            colonnes = st.columns(3)
            with colonnes[0]:
                tenants = lister_tenants()
                options_tenant = {int(ligne["id"]): ligne["raison_sociale"]
                                  for _, ligne in tenants.iterrows()}
                tenant_id = st.selectbox("Entreprise", list(options_tenant.keys()),
                                         format_func=lambda cle: options_tenant[cle])
                username = st.text_input("Identifiant")
            with colonnes[1]:
                mot_de_passe = st.text_input("Mot de passe", type="password")
                role = st.selectbox("Rôle", list(ROLES.keys()),
                                    format_func=lambda r: f"{r} — {ROLES[r]}")
            with colonnes[2]:
                email = st.text_input("E-mail")
                telephone = st.text_input("Téléphone")
                soumis = st.form_submit_button("Créer l'utilisateur", use_container_width=True)
        if soumis and username and mot_de_passe:
            try:
                valider_mot_de_passe(mot_de_passe)
                creer_utilisateur(int(tenant_id), username, mot_de_passe, role, email, telephone)
                st.success(f"Utilisateur {username} créé.")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
            except sqlite3.IntegrityError:
                st.error("Cet identifiant existe déjà pour cette entreprise.")
        st.dataframe(lire_df(
            "SELECT u.id, t.raison_sociale, u.username, u.role, u.email, u.actif"
            " FROM utilisateurs u JOIN tenants t ON t.id = u.tenant_id ORDER BY u.id"
        ), use_container_width=True)
        st.markdown("##### Réinitialiser un mot de passe")
        comptes = lire_df(
            "SELECT u.tenant_id, u.username, t.raison_sociale FROM utilisateurs u"
            " JOIN tenants t ON t.id = u.tenant_id ORDER BY t.raison_sociale, u.username"
        )
        if not comptes.empty:
            cles = {f"{ligne['tenant_id']}|{ligne['username']}":
                    f"{ligne['username']} — {ligne['raison_sociale']}"
                    for _, ligne in comptes.iterrows()}
            with st.form("form_reset_mdp"):
                choix = st.selectbox("Utilisateur", list(cles.keys()),
                                     format_func=lambda cle: cles[cle])
                nouveau_mdp = st.text_input("Nouveau mot de passe", type="password")
                reinit = st.form_submit_button("Réinitialiser", use_container_width=True)
            if reinit:
                tid, uname = choix.split("|", 1)
                try:
                    definir_mot_de_passe(int(tid), uname, nouveau_mdp)
                    st.session_state.pop("comptes_demo", None)
                    st.success(f"Mot de passe de {uname} réinitialisé.")
                except ValueError as exc:
                    st.error(str(exc))
    with onglet_audit:
        integre, nb_lignes, message = verifier_audit()
        if integre:
            st.success(f"{message} ({nb_lignes} entrées)")
        else:
            st.error(message)
        st.dataframe(lire_df(
            "SELECT ts, username, role, ip, action, entite, details FROM audit_logs"
            " ORDER BY id DESC LIMIT 500"
        ), use_container_width=True)
    with onglet_taux:
        colonnes = st.columns(3)
        with colonnes[0]:
            devise = st.text_input("Devise", value="USD")
        with colonnes[1]:
            taux = st.number_input("Taux → FCFA", min_value=0.0, step=1.0)
        with colonnes[2]:
            st.write("")
            st.write("")
            if st.button("Enregistrer le taux", use_container_width=True):
                enregistrer_taux(devise, taux, "manuel")
                st.success("Taux enregistré.")
                st.rerun()
        if st.button("🌐 Actualiser via API (USD)", use_container_width=True):
            taux_api = actualiser_taux_api("USD")
            if taux_api:
                st.success(f"Taux USD mis à jour : {taux_api:,.2f} FCFA")
            else:
                st.warning("API indisponible — dernier taux conservé.")
            st.rerun()
        st.dataframe(lire_df(
            "SELECT devise, taux_vers_xof, source, date_maj FROM taux_change ORDER BY id DESC"
        ), use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# POINT D'ENTRÉE STREAMLIT
# ══════════════════════════════════════════════════════════════════════════════
def acces_direct_actif() -> bool:
    """Mode local : ouverture sans mot de passe, activé seulement par SNDGIR_ACCES_DIRECT=1."""
    return os.getenv("SNDGIR_ACCES_DIRECT", "").lower() in ("1", "true", "oui")


def ouvrir_session_directe() -> bool:
    """Ouvre la session du premier administrateur trouvé (usage personnel, en local)."""
    admin = lire_df(
        "SELECT tenant_id, username, role FROM utilisateurs WHERE role = ? AND actif = 1 "
        "ORDER BY tenant_id, id LIMIT 1", ("Administrateur Système",))
    if admin.empty:
        return False
    ligne = admin.iloc[0]
    st.session_state.update({"authentifie": True, "tenant_id": int(ligne["tenant_id"]),
                             "username": str(ligne["username"]), "user_role": str(ligne["role"]),
                             "acces_direct": True})
    return True


def main() -> None:
    st.set_page_config(page_title=APP_NAME, page_icon="🏦", layout="wide",
                       initial_sidebar_state="expanded")
    injecter_theme()
    init_db()

    if not st.session_state.get("authentifie") and acces_direct_actif():
        ouvrir_session_directe()

    if not st.session_state.get("authentifie"):
        ecran_connexion()
        return

    role = barre_laterale()
    if st.session_state.get("acces_direct"):
        st.sidebar.warning("Accès direct sans mot de passe : à utiliser seulement sur votre "
                           "ordinateur, jamais sur internet.")
    st.title(f"🏦 {APP_NAME}")
    st.caption(f"Version {APP_VERSION} · rôle « {role} » · données isolées par entreprise")

    onglets = st.tabs(["📊 Tableau de bord", "📒 Comptabilité", "🚢 Transit & Douanes",
                       "🤖 IA & OCR", "👤 Portail client", "🛡️ Administration"])
    with onglets[0]:
        onglet_tableau_de_bord()
    with onglets[1]:
        onglet_comptabilite()
    with onglets[2]:
        onglet_transit()
    with onglets[3]:
        onglet_ia()
    with onglets[4]:
        onglet_portail_client()
    with onglets[5]:
        onglet_administration()

    journaliser("session_consultation", "ui", role, "chargement de l'interface")


if __name__ == "__main__":
    main()
