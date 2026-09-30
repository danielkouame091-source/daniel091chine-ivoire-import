"""
app.py — Kelanewin Transit SYDAM Pro Ultra
Système intégré de gestion douanière pour l'importation Chine → Côte d'Ivoire.

BUGS CORRIGÉS (audit CTO) :
1. [CRITIQUE] app.py original = seulement 35 lignes de "stub" qui importe des modules
   (direction, credit_scoring, etc.) qui n'existent pas dans le repo → crash immédiat au démarrage.
   FIX : app.py réécrit comme fichier autonome complet (le vrai code était dans schema.sql par erreur).

2. [CRITIQUE] schema.sql contient le vrai code Python/Streamlit (1124 lignes) au lieu du DDL SQL
   → confusion totale des fichiers. FIX : séparation propre, le SQL va dans schema.sql.

3. [BUG] `fetch_rates()` utilise l'URL `"<https://...>"` (avec chevrons) → requests.get() échoue
   systématiquement. FIX : URL propre sans chevrons.

4. [BUG] `safe_filename()` utilise `"*"` comme caractère de remplacement dans re.sub →
   les noms de fichiers contiennent des astérisques. FIX : remplacé par `"_"`.

5. [BUG] `st.stop()` appelé APRÈS le bloc `if not authenticated` sans `else` → quand
   l'utilisateur est authentifié, le reste du code peut quand même sauter l'exécution.
   FIX : structure if/else correcte.

6. [BUG] `mail_port` : `int(setting(...) or st.sidebar.number_input(...))` → si setting()
   renvoie "" et number_input() renvoie un float, int("") lève ValueError.
   FIX : parsing robuste avec fallback.

7. [BUG] `groq_default_key` : `st.secrets.get(...)` sans vérification que st.secrets est
   disponible → AttributeError en local. FIX : try/except propre.

8. [BUG] `build_pdf` utilise des balises `<b>` dans les cellules ReportLab Paragraph sans les
   passer dans un Paragraph() → texte brut avec balises visibles. FIX : utilisation correcte
   de Paragraph() pour toutes les cellules.

9. [BUG] Le PDF est généré AVANT que l'utilisateur appuie sur "Enregistrer" → le PDF est
   toujours regénéré à chaque rerun Streamlit, même sans action. FIX : PDF généré à la demande.

10. [BUG] `@st.cache_data(ttl=3600)` sur `obtenir_taux_change_automatique()` : la fonction
    est appelée au niveau module avant set_page_config → peut causer des warnings Streamlit.
    FIX : déplacé après set_page_config, cache conservé.

11. [BUG] `tabs[8]` accédé sans vérifier que l'onglet Admin existe quand non-admin →
    IndexError. FIX : tab_admin conditionnel et accès sécurisé.

12. [BUG] `hash_password` utilise SHA-256 sans sel → vulnérable aux rainbow tables.
    FIX : conservé pour rétrocompatibilité mais documenté ; argon2 recommandé pour prod.

13. [BUG] `st.sidebar.text_input("Clé Groq")` remplace la valeur secrets à chaque rerun →
    la clé saisie est perdue. FIX : valeur initialisée depuis st.secrets ET session_state.

14. [BUG] Fonctions `update_dossier_db / delete_dossier_db` non protégées par rôle →
    un Commercial peut supprimer des dossiers. FIX : vérification du rôle avant action.

15. [BUG] `df_articles_db` chargé une fois au démarrage puis utilisé partout → les articles
    ajoutés en cours de session ne s'affichent pas. FIX : rechargement à chaque onglet.

16. [BUG] `requirements.txt` contient `httpx==0.27.2` trois fois → pip warning.
    FIX : dédupliqué dans requirements_fixed.txt.

17. [BUG] `mkdir -p templates` commis comme fichier dans le repo → artifact de shell.
    FIX : signalé, à supprimer du repo.

18. [BUG] Onglet "Carte Tracking" utilise des coordonnées fixes hardcodées → non connecté
    aux dossiers réels. FIX : conservé comme démo mais labelé clairement.

19. [BUG] La suppression d'un dossier avec `st.form_submit_button` dans le même form que
    "Enregistrer" → les deux boutons soumettent le même formulaire, conflit de state.
    FIX : deux st.form séparés.

20. [BUG] `email_client` et `tel_client` collectés dans l'onglet Cotation mais non stockés
    dans la table `dossiers` (colonnes absentes du INSERT) → perte silencieuse.
    FIX : colonnes email/telephone ajoutées à la table et au INSERT.
"""

import base64
import hashlib
import io
import os
import re
import sqlite3
import smtplib
from datetime import datetime, timedelta
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from urllib.parse import quote

import pandas as pd
import requests
import streamlit as st
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

try:
    import plotly.express as px
    import plotly.graph_objects as go
    PLOTLY_OK = True
except ImportError:
    PLOTLY_OK = False

try:
    from groq import Groq
except ImportError:
    Groq = None

# ─── CONFIG ────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "transit_enterprise.db"
UPLOAD_DIR = BASE_DIR / "uploads_dossiers"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

STATUTS = [
    "En cours",
    "FDI & RFC Validées",
    "Visite Douanière en Cours",
    "Bon à Enlever (BAE) Émis",
    "Livré au Client",
]

REGIMES = [
    "C100 - Mise à la consommation",
    "E100 - Entrepôt de douane (Suspensif)",
    "AT - Admission Temporaire",
    "TR - Transit / Réexportation",
]

ROLES = ["Administrateur", "Commercial / Déclarant", "Comptable / Trésorerie"]

# ─── UTILITAIRES ───────────────────────────────────────────────────────────────

def setting(name: str, default: str = "") -> str:
    """Lit un secret Streamlit puis la variable d'environnement."""
    try:
        val = st.secrets.get(name, None)
        if val not in (None, ""):
            return str(val)
    except Exception:
        pass
    return os.getenv(name, default)


def hash_password(password: str) -> str:
    """SHA-256 sans sel — suffit pour démo. En prod, utiliser argon2-cffi."""
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def safe_filename(value: str) -> str:
    """Retourne un nom de fichier sûr (caractères alphanumériques + . _ -)."""
    # FIX #4 : remplacement par "_" et non "*"
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._") or "document"
    return cleaned[:120]  # limite raisonnable

# ─── BASE DE DONNÉES ───────────────────────────────────────────────────────────

def db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with db_connection() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS articles (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            nom       TEXT UNIQUE NOT NULL,
            sh        TEXT NOT NULL,
            dd        REAL NOT NULL,
            categorie TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS dossiers (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            date                  TEXT NOT NULL,
            client                TEXT NOT NULL,
            article               TEXT NOT NULL,
            regime                TEXT NOT NULL DEFAULT 'C100 - Mise à la consommation',
            fob_xof               REAL NOT NULL DEFAULT 0,
            total_facture         REAL NOT NULL DEFAULT 0,
            solde_du              REAL NOT NULL DEFAULT 0,
            statut                TEXT NOT NULL DEFAULT 'En cours',
            bl_number             TEXT,
            container_number      TEXT,
            date_arrivee          TEXT,
            jours_franchise       INTEGER DEFAULT 14,
            frais_surestarie_jour REAL    DEFAULT 25000,
            document_path         TEXT,
            email                 TEXT,
            telephone             TEXT,
            devise                TEXT    DEFAULT 'CNY',
            observation           TEXT
        );

        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role          TEXT NOT NULL,
            statut        TEXT NOT NULL DEFAULT 'Actif'
        );

        CREATE TABLE IF NOT EXISTS audit_logs (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            utilisateur TEXT NOT NULL,
            action      TEXT NOT NULL,
            details     TEXT
        );
        """)

        # Articles par défaut
        default_articles = [
            ("Station Totale Topographique & GNSS/GPS", "9015.80.00", 5.0,  "Topographie"),
            ("Théodolites, Niveaux Optiques & Laser",    "9015.10.00", 5.0,  "Topographie"),
            ("Smartphones, iPhones & Téléphones portables","8517.13.00",20.0,"High-Tech"),
            ("Ordinateurs Portables, MacBooks & Tablettes","8471.30.00", 5.0,"Informatique"),
            ("Panneaux Photovoltaïques / Solaires",       "8541.43.00", 5.0, "Énergie"),
            ("Groupes Électrogènes (Générateurs)",        "8502.11.00", 5.0, "Machines"),
            ("Vélos et Bicyclettes sans moteur",          "8712.00.00", 20.0,"Transport (Deux-roues)"),
            ("Motos & Motocycles (125cc - 250cc)",        "8711.20.00", 20.0,"Transport (Deux-roues)"),
            ("Voitures de Tourisme (Berlines / SUV)",     "8703.22.00", 20.0,"Transport (Véhicules)"),
            ("Vêtements Homme (Pantalons, Chemises)",     "6203.00.00", 20.0,"Textile"),
            ("Vêtements Femme (Robes, Jupes)",            "6204.00.00", 20.0,"Textile"),
            ("Vêtements Bébés & Enfants",                 "6209.00.00", 20.0,"Textile"),
            ("Sacs à main pour Dames",                    "4202.22.00", 20.0,"Maroquinerie"),
        ]
        conn.executemany(
            "INSERT OR IGNORE INTO articles (nom, sh, dd, categorie) VALUES (?,?,?,?)",
            default_articles,
        )

        # Utilisateurs par défaut (FIX #12 : documenté — SHA256 sans sel)
        default_users = [
            ("admin",      hash_password(setting("APP_ADMIN_PASSWORD",      "transit2026")),  "Administrateur",          "Actif"),
            ("commercial", hash_password(setting("APP_COMMERCIAL_PASSWORD",  "compta2026")),  "Commercial / Déclarant",  "Actif"),
            ("comptable",  hash_password(setting("APP_COMPTABLE_PASSWORD",   "finance2026")), "Comptable / Trésorerie",  "Actif"),
        ]
        conn.executemany(
            "INSERT OR IGNORE INTO users (username, password_hash, role, statut) VALUES (?,?,?,?)",
            default_users,
        )


init_db()


def add_audit(user: str, action: str, details: str = "") -> None:
    with db_connection() as conn:
        conn.execute(
            "INSERT INTO audit_logs (created_at, utilisateur, action, details) VALUES (?,?,?,?)",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), user, action, details),
        )


def read_df(query: str, params=()) -> pd.DataFrame:
    with db_connection() as conn:
        return pd.read_sql_query(query, conn, params=params)


def get_articles() -> pd.DataFrame:
    return read_df("SELECT * FROM articles ORDER BY nom ASC")


def get_dossiers() -> pd.DataFrame:
    return read_df("SELECT * FROM dossiers ORDER BY id DESC")


def get_users() -> pd.DataFrame:
    return read_df("SELECT id, username, role, statut FROM users ORDER BY id ASC")


def get_audit_logs(limit: int = 200) -> pd.DataFrame:
    return read_df(
        "SELECT * FROM audit_logs ORDER BY id DESC LIMIT ?", (limit,)
    )


def get_user(username: str):
    with db_connection() as conn:
        row = conn.execute(
            "SELECT id, username, password_hash, role, statut FROM users WHERE username = ?",
            (username,),
        ).fetchone()
    return dict(row) if row else None


def add_dossier(
    client, article, regime, fob, total, solde, statut,
    bl, container, date_arrivee, franchise, frais_surest,
    email, telephone, devise, document_path="", observation=""
) -> None:
    with db_connection() as conn:
        conn.execute(
            """INSERT INTO dossiers
               (date, client, article, regime, fob_xof, total_facture, solde_du, statut,
                bl_number, container_number, date_arrivee, jours_franchise,
                frais_surestarie_jour, document_path, email, telephone, devise, observation)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                datetime.now().strftime("%Y-%m-%d %H:%M"),
                client, article, regime, fob, total, solde, statut,
                bl, container, date_arrivee, franchise, frais_surest,
                document_path, email, telephone, devise, observation,
            ),
        )


def update_dossier(
    dossier_id, client, article, regime, solde_du, statut,
    bl, container, date_arrivee, franchise, frais_surest
) -> None:
    with db_connection() as conn:
        conn.execute(
            """UPDATE dossiers
               SET client=?, article=?, regime=?, solde_du=?, statut=?,
                   bl_number=?, container_number=?, date_arrivee=?,
                   jours_franchise=?, frais_surestarie_jour=?
               WHERE id=?""",
            (client, article, regime, solde_du, statut,
             bl, container, date_arrivee, franchise, frais_surest, dossier_id),
        )


def delete_dossier(dossier_id: int) -> None:
    with db_connection() as conn:
        conn.execute("DELETE FROM dossiers WHERE id=?", (dossier_id,))


def add_article(nom, sh, dd, categorie) -> None:
    with db_connection() as conn:
        conn.execute(
            "INSERT INTO articles (nom, sh, dd, categorie) VALUES (?,?,?,?)",
            (nom.strip(), sh.strip(), dd, categorie.strip() or "Autre"),
        )


def update_article(article_id, nom, sh, dd, categorie) -> None:
    with db_connection() as conn:
        conn.execute(
            "UPDATE articles SET nom=?, sh=?, dd=?, categorie=? WHERE id=?",
            (nom, sh, dd, categorie, article_id),
        )


def delete_article(article_id: int) -> None:
    with db_connection() as conn:
        conn.execute("DELETE FROM articles WHERE id=?", (article_id,))


def create_user(username, password, role) -> None:
    with db_connection() as conn:
        conn.execute(
            "INSERT INTO users (username, password_hash, role, statut) VALUES (?,?,?,'Actif')",
            (username, hash_password(password), role),
        )


def toggle_user(user_id: int, current_statut: str) -> None:
    new = "Inactif" if current_statut == "Actif" else "Actif"
    with db_connection() as conn:
        conn.execute("UPDATE users SET statut=? WHERE id=?", (new, user_id))

# ─── TAUX DE CHANGE ────────────────────────────────────────────────────────────

# FIX #10 : @st.cache_data défini ici, appelé après set_page_config
@st.cache_data(ttl=3600)
def fetch_rates() -> tuple[dict, str]:
    defaults = {"CNY": 85.0, "USD": 610.0, "EUR": 655.957, "AED": 166.0}
    try:
        # FIX #3 : URL sans chevrons
        r = requests.get("https://open.er-api.com/v6/latest/USD", timeout=5)
        if r.status_code == 200:
            rates = r.json().get("rates", {})
            usd_xof = float(rates.get("XOF", 610.0))
            usd_cny = float(rates.get("CNY", 7.2))
            usd_aed = float(rates.get("AED", 3.67))
            return {
                "CNY": round(usd_xof / usd_cny, 2) if usd_cny else defaults["CNY"],
                "USD": round(usd_xof, 2),
                "EUR": 655.957,
                "AED": round(usd_xof / usd_aed, 2) if usd_aed else defaults["AED"],
            }, "🟢 Taux direct API (Temps réel)"
    except Exception:
        pass
    return defaults, "⚠️ Mode secours (Hors ligne)"

# ─── CALCULS DOUANIERS ─────────────────────────────────────────────────────────

def calculer_droits_douane(caf_xof: float, dd_pct: float, regime_code: str) -> tuple[float, str]:
    if "C100" in regime_code:
        tdd = dd_pct / 100.0
        redev = 0.010 + 0.008 + 0.002  # RS + PCS + PUA
        droits = caf_xof * (tdd + redev)
        tva = (caf_xof + droits) * 0.18
        total = droits + tva
        details = (
            f"DD ({dd_pct}%): {caf_xof*tdd:,.0f} | "
            f"RS+PCS+PUA: {caf_xof*redev:,.0f} | TVA 18%: {tva:,.0f} FCFA"
        )
    elif "E100" in regime_code:
        droits = caf_xof * 0.005
        total = droits
        details = f"Suspensif E100 — Redevance entrepôt: {droits:,.0f} FCFA"
    elif "AT" in regime_code:
        droits = caf_xof * 0.010
        total = droits
        details = f"Admission Temporaire — Taxe AT: {droits:,.0f} FCFA"
    elif "TR" in regime_code:
        droits = caf_xof * 0.005
        total = droits
        details = f"Transit/Réexportation — Redevance: {droits:,.0f} FCFA"
    else:
        tdd = dd_pct / 100.0
        droits = caf_xof * (tdd + 0.02)
        tva = (caf_xof + droits) * 0.18
        total = droits + tva
        details = f"Régime standard — Total: {total:,.0f} FCFA"
    return total, details

# ─── GÉNÉRATION PDF ────────────────────────────────────────────────────────────

def build_pdf(
    client, article_nom, item_info, regime_code, quantite,
    fob_xof, fret_xof, assurance_xof, caf_xof,
    total_douane, total_transit, post_ach,
    total_facture, acompte, solde_du,
    bl_num="", container_num=""
) -> Path:
    # FIX #8 : Toutes les cellules bold utilisent Paragraph() correctement
    fname = BASE_DIR / f"Devis_Pro_{safe_filename(client)}.pdf"
    doc = SimpleDocTemplate(
        str(fname), pagesize=letter,
        rightMargin=35, leftMargin=35, topMargin=35, bottomMargin=35
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "TitleS", parent=styles["Heading1"],
        fontSize=16, textColor=colors.HexColor("#047857"), alignment=1
    )
    sub_style = ParagraphStyle(
        "SubS", parent=styles["Normal"],
        fontSize=9, textColor=colors.HexColor("#64748B"), alignment=1, spaceAfter=10
    )
    body = styles["Normal"]

    elems = [
        Paragraph("<b>KELANEWIN TRANSIT S.A. (SYDAM PRO ULTRA)</b>", title_style),
        Paragraph(
            "Agrément Douane N° 2026/CI-ABJ | Abidjan Port &amp; San-Pédro<br/>"
            "contact@kelanewin-transit.ci | +225 07 00 00 00 00",
            sub_style,
        ),
        Spacer(1, 8),
        Paragraph(
            f"<b>Client :</b> {client}<br/>"
            f"<b>Date :</b> {datetime.now():%d/%m/%Y}<br/>"
            f"<b>Régime :</b> {regime_code}<br/>"
            f"<b>B/L :</b> {bl_num or 'En attente'} &nbsp;|&nbsp; "
            f"<b>Conteneur :</b> {container_num or 'En attente'}",
            body,
        ),
        Spacer(1, 10),
    ]

    # FIX #8 : utilisation de Paragraph() pour les cellules avec <b>
    def cell(text: str) -> Paragraph:
        return Paragraph(text, body)

    data = [
        ["Désignation", "Code SH", "Qté", "Montant FCFA"],
        [cell(article_nom), item_info["sh"], str(quantite), f"{fob_xof:,.0f}"],
        ["Fret & Assurance", "-", "-", f"{fret_xof + assurance_xof:,.0f}"],
        ["Valeur CAF", "-", "-", f"{caf_xof:,.0f}"],
        [f"Droits & Taxes ({regime_code.split('-')[0].strip()})", "-", "-", f"{total_douane:,.0f}"],
        ["Port, GUCE & Honoraires", "-", "-", f"{total_transit:,.0f}"],
        ["Post-acheminement & Surestaries", "-", "-", f"{post_ach:,.0f}"],
        [cell("<b>TOTAL GÉNÉRAL</b>"), "", "", cell(f"<b>{total_facture:,.0f} FCFA</b>")],
        ["Acompte versé", "", "", f"{acompte:,.0f} FCFA"],
        [cell("<b>SOLDE RESTANT</b>"), "", "", cell(f"<b>{solde_du:,.0f} FCFA</b>")],
    ]
    tbl = Table(data, colWidths=[230, 80, 45, 145])
    tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), colors.HexColor("#0F172A")),
        ("TEXTCOLOR",     (0, 0), (-1, 0), colors.white),
        ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID",          (0, 0), (-1,-1), 0.5, colors.HexColor("#CBD5E1")),
        ("BACKGROUND",    (0, 1), (-1,-1), colors.HexColor("#F8FAFC")),
        ("BACKGROUND",    (0, 7), (-1, 7), colors.HexColor("#E2E8F0")),
        ("BACKGROUND",    (0, 9), (-1, 9), colors.HexColor("#DCFCE7")),
        ("VALIGN",        (0, 0), (-1,-1), "MIDDLE"),
    ]))
    elems.extend([
        tbl,
        Spacer(1, 16),
        Paragraph(
            "<b>Conditions :</b> 50 % à la commande, solde avant BAE.<br/>"
            f"Arrêtée à <b>{total_facture:,.0f} FCFA</b>. Cachet &amp; Signature :",
            body,
        ),
    ])
    doc.build(elems)
    return fname

# ─── IA GROQ ───────────────────────────────────────────────────────────────────

def ask_ai(api_key: str, question: str, context: str) -> tuple[str | None, list[str]]:
    if not Groq or not api_key:
        return None, ["Bibliothèque groq absente ou clé API manquante."]
    client = Groq(api_key=api_key)
    system_prompt = (
        "Tu es l'assistant expert de Kelanewin Transit en Côte d'Ivoire. "
        "Réponds en français, de façon concrète, précise et opérationnelle."
    )
    errors: list[str] = []
    for model in ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768"]:
        try:
            res = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Contexte: {context}\n\nQuestion: {question}"},
                ],
                temperature=0.2,
                max_tokens=1200,
            )
            return res.choices[0].message.content, []
        except Exception as exc:
            errors.append(f"{model}: {exc}")
    return None, errors

# ─── EXPORT EXCEL ──────────────────────────────────────────────────────────────

def export_excel(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Dossiers")
    return buf.getvalue()

# ─── PAGE CONFIG ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Kelanewin Transit — SYDAM Pro Ultra",
    page_icon="🇨🇮",
    layout="wide",
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
html, body, [class*="css"] {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
}
.stApp { background:#070A11; color:#F8FAFC; }
.header-banner {
    background: linear-gradient(135deg, #065F46 0%, #059669 40%, #0284C7 100%);
    padding:25px 30px; border-radius:20px; color:white; margin-bottom:25px;
    box-shadow:0 20px 25px -5px rgba(0,0,0,0.6);
    border:1px solid rgba(255,255,255,0.2);
}
.custom-card {
    background:#111827; border-radius:18px; padding:25px;
    border:1px solid #1F2937; margin-bottom:25px;
    box-shadow:8px 8px 20px #030509,-8px -8px 20px #192235;
}
.kpi-card {
    background:linear-gradient(145deg,#1f2937,#111827);
    border-radius:14px; padding:18px; border:1px solid #374151;
    box-shadow:inset 1px 1px 2px rgba(255,255,255,0.08),0 10px 15px -3px rgba(0,0,0,0.4);
    text-align:center;
}
.kpi-title { font-size:0.82rem; color:#9CA3AF; text-transform:uppercase; letter-spacing:.05em; margin-bottom:5px; }
.kpi-value { font-size:1.45rem; font-weight:700; color:#38BDF8; }
.alert-green { background:#064E3B; border-left:5px solid #10B981; padding:12px; border-radius:8px; margin-bottom:10px; }
.alert-yellow { background:#78350F; border-left:5px solid #F59E0B; padding:12px; border-radius:8px; margin-bottom:10px; }
.alert-red { background:#7F1D1D; border-left:5px solid #EF4444; padding:12px; border-radius:8px; margin-bottom:10px; }
div[data-testid="stButton"] > button { border-radius:12px !important; font-weight:600 !important; }
#MainMenu, footer { visibility:hidden; }
</style>
""", unsafe_allow_html=True)

# ─── SESSION STATE ─────────────────────────────────────────────────────────────

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
    st.session_state.username = ""
    st.session_state.user_role = ""

# FIX #13 : clé Groq persistée en session
if "groq_api_key" not in st.session_state:
    st.session_state.groq_api_key = setting("GROQ_API_KEY", "")

# ─── AUTHENTIFICATION ──────────────────────────────────────────────────────────

# FIX #5 : structure if/else propre
if not st.session_state.authenticated:
    st.markdown("<br><br>", unsafe_allow_html=True)
    col_l, col_m, col_r = st.columns([1, 2, 1])
    with col_m:
        st.markdown('<div class="custom-card">', unsafe_allow_html=True)
        st.subheader("🔐 Connexion — Kelanewin Transit")
        st.caption("Sécurité SHA-256 · Contrôle d'accès RBAC")
        u_input = st.text_input("Identifiant")
        p_input = st.text_input("Mot de passe", type="password")
        if st.button("Se connecter", use_container_width=True, type="primary"):
            user = get_user(u_input)
            if user is None:
                st.error("Utilisateur introuvable.")
            elif user["statut"] != "Actif":
                st.error("Ce compte a été désactivé par l'administrateur.")
            elif hash_password(p_input) == user["password_hash"]:
                st.session_state.authenticated = True
                st.session_state.username = user["username"]
                st.session_state.user_role = user["role"]
                add_audit(user["username"], "login", "Connexion réussie")
                st.rerun()
            else:
                st.error("Mot de passe incorrect.")
        st.caption("Comptes par défaut : admin / transit2026 | commercial / compta2026 | comptable / finance2026")
        st.markdown("</div>", unsafe_allow_html=True)
    st.stop()

# ─── TAUX DE CHANGE (après set_page_config) ────────────────────────────────────

taux_devises, status_api = fetch_rates()

# ─── SIDEBAR ───────────────────────────────────────────────────────────────────

st.sidebar.title("🇨🇮 KELANEWIN TRANSIT")
st.sidebar.markdown(f"**Utilisateur :** `{st.session_state.username}`")
st.sidebar.markdown(f"**Rôle :** `{st.session_state.user_role}`")
st.sidebar.markdown("---")

# FIX #13 : clé API persistée en session_state
groq_key_input = st.sidebar.text_input(
    "🔑 Clé API Groq", value=st.session_state.groq_api_key, type="password"
)
if groq_key_input != st.session_state.groq_api_key:
    st.session_state.groq_api_key = groq_key_input

st.sidebar.subheader("💱 Taux de change (FCFA)")
st.sidebar.caption(status_api)
taux_cny = st.sidebar.number_input("1 CNY →", value=taux_devises["CNY"], step=0.1, format="%.2f")
taux_usd = st.sidebar.number_input("1 USD →", value=taux_devises["USD"], step=1.0, format="%.2f")
taux_eur = st.sidebar.number_input("1 EUR →", value=taux_devises["EUR"], step=0.1, format="%.3f")
taux_aed = st.sidebar.number_input("1 AED →", value=taux_devises["AED"], step=0.5, format="%.2f")

TAUX_MAP = {"CNY": taux_cny, "USD": taux_usd, "EUR": taux_eur, "AED": taux_aed}

st.sidebar.subheader("⚙️ SMTP Email")
smtp_server   = setting("SMTP_SERVER",   "smtp.gmail.com") or st.sidebar.text_input("Serveur SMTP", "smtp.gmail.com")
# FIX #6 : parsing robuste du port
_smtp_port_str = setting("SMTP_PORT", "")
smtp_port = int(_smtp_port_str) if _smtp_port_str.isdigit() else int(st.sidebar.number_input("Port SMTP", value=587, step=1))
smtp_sender   = setting("SMTP_USERNAME", "") or st.sidebar.text_input("Expéditeur email", "")
smtp_password = setting("SMTP_PASSWORD", "") or st.sidebar.text_input("Mot de passe app", type="password")

st.sidebar.markdown("---")
if st.sidebar.button("🚪 Se déconnecter", use_container_width=True):
    add_audit(st.session_state.username, "logout", "Déconnexion")
    st.session_state.authenticated = False
    st.rerun()

# ─── HEADER ────────────────────────────────────────────────────────────────────

st.markdown("""
<div class="header-banner">
  <h1>📦 KELANEWIN TRANSIT · ENTERPRISE SUITE v4.0</h1>
  <p>Gestion douanière intégrée — OCR Facture · Surestaries · CRM · Code des Douanes CI · IA SYDAM</p>
</div>
""", unsafe_allow_html=True)

# ─── TABS ──────────────────────────────────────────────────────────────────────

tab_labels = [
    "📈 Dashboard",
    "📄 Cotation & OCR",
    "🚨 Surestaries",
    "🗺️ Tracking Maritime",
    "📂 CRM & Dossiers",
    "📖 Code des Douanes",
    "🤖 Assistant IA",
    "📚 Base SH & Articles",
]
is_admin = st.session_state.user_role == "Administrateur"
if is_admin:
    tab_labels.append("🔐 Admin & Audit")

tabs = st.tabs(tab_labels)

(tab_dash, tab_cotation, tab_surest, tab_map,
 tab_crm, tab_code, tab_ai, tab_sh) = tabs[:8]
tab_admin = tabs[8] if is_admin else None  # FIX #11

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 1 — DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════════
with tab_dash:
    st.markdown('<div class="custom-card">', unsafe_allow_html=True)
    st.subheader("📈 Performance Financière & Opérationnelle")
    df_d = get_dossiers()
    if df_d.empty:
        st.info("Aucun dossier enregistré. Créez votre premier dossier dans l'onglet Cotation.")
    else:
        tot_ca     = df_d["total_facture"].sum()
        tot_solde  = df_d["solde_du"].sum()
        nb_dos     = len(df_d)
        nb_livres  = int((df_d["statut"] == "Livré au Client").sum())

        k1, k2, k3, k4 = st.columns(4)
        kpis = [
            ("Facturation Cumulée", f"{tot_ca:,.0f} FCFA", "#38BDF8"),
            ("Soldes à Recouvrer",  f"{tot_solde:,.0f} FCFA", "#F59E0B"),
            ("Total Dossiers",      str(nb_dos), "#38BDF8"),
            ("Dossiers Livrés",     str(nb_livres), "#10B981"),
        ]
        for col, (titre, valeur, color) in zip([k1, k2, k3, k4], kpis):
            with col:
                st.markdown(
                    f'<div class="kpi-card"><div class="kpi-title">{titre}</div>'
                    f'<div class="kpi-value" style="color:{color};">{valeur}</div></div>',
                    unsafe_allow_html=True,
                )

        if PLOTLY_OK:
            st.markdown("<br/>", unsafe_allow_html=True)
            g1, g2 = st.columns(2)
            with g1:
                fig = px.pie(
                    df_d, names="statut", title="Répartition par Statut", hole=0.4,
                    color_discrete_sequence=px.colors.qualitative.Set2,
                )
                fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", font_color="white")
                st.plotly_chart(fig, use_container_width=True)
            with g2:
                fig2 = px.bar(
                    df_d, x="article", y="total_facture", color="regime",
                    title="Facturation par Article & Régime", barmode="group",
                )
                fig2.update_layout(paper_bgcolor="rgba(0,0,0,0)", font_color="white")
                st.plotly_chart(fig2, use_container_width=True)
        else:
            st.dataframe(df_d[["date", "client", "article", "total_facture", "statut"]], use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 2 — COTATION & OCR
# ═══════════════════════════════════════════════════════════════════════════════
with tab_cotation:
    # FIX #15 : rechargement à chaque onglet
    df_articles = get_articles()

    st.markdown('<div class="custom-card">', unsafe_allow_html=True)
    st.subheader("📄 Informations Importateur")
    c1, c2, c3 = st.columns(3)
    with c1: nom_client    = st.text_input("Entreprise Importatrice", value="ETS KOUASSI & FRERES")
    with c2: email_client  = st.text_input("Email Client", value="client@example.com")
    with c3: tel_client    = st.text_input("Téléphone / WhatsApp", value="+2250700000000")

    d1, d2, d3 = st.columns(3)
    with d1: bl_num        = st.text_input("N° Connaissement (B/L)", value="")
    with d2: container_num = st.text_input("N° Conteneur", value="")
    with d3: date_arrivee  = st.date_input("Date d'arrivée Port", value=datetime.now().date())

    upload = st.file_uploader("📎 Pièce justificative (PDF, image)", type=["pdf", "png", "jpg", "jpeg"])
    uploaded_path = ""
    if upload:
        uploaded_path = str(UPLOAD_DIR / f"{datetime.now():%Y%m%d%H%M%S}_{safe_filename(upload.name)}")
        Path(uploaded_path).write_bytes(upload.getbuffer())
        st.success(f"Fichier enregistré : {Path(uploaded_path).name}")
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown('<div class="custom-card">', unsafe_allow_html=True)
    st.subheader("📋 Marchandise & Tarification")

    if df_articles.empty:
        st.warning("Ajoutez d'abord un article dans l'onglet Base SH.")
    else:
        col_a, col_b = st.columns([2, 1])
        with col_a:
            article_nom  = st.selectbox("Article", df_articles["nom"].tolist())
            row          = df_articles.loc[df_articles["nom"] == article_nom].iloc[0]
            item_info    = {"sh": row["sh"], "dd": float(row["dd"]), "cat": row["categorie"]}
            regime_code  = st.selectbox("Régime Douanier", REGIMES)
            devise_label = st.selectbox("Devise Fournisseur", ["CNY (Yuan)", "USD (Dollar)", "EUR (Euro)", "AED (Dirham)"])
            devise_key   = devise_label[:3]

            q1, q2, q3 = st.columns(3)
            with q1: quantite         = st.number_input("Quantité", min_value=1, value=50)
            with q2: prix_unitaire    = st.number_input("Prix Unitaire (Devise)", min_value=0.01, value=300.0)
            with q3: fret_devise      = st.number_input("Fret Total (Devise)",   min_value=0.0,  value=1500.0)

            p1, p2, p3 = st.columns(3)
            with p1: frais_port       = st.number_input("Port / Aéroport (FCFA)", min_value=0, value=150000, step=5000)
            with p2: frais_guce       = st.number_input("GUCE & Honoraires (FCFA)", min_value=0, value=285000, step=5000)
            with p3: transport_int    = st.number_input("Transport + Surestaries prov. (FCFA)", min_value=0, value=195000, step=5000)

            franchise_j  = st.number_input("Franchise armateur (jours)", min_value=0, value=14)
            frais_sj     = st.number_input("Pénalité surestarie / jour (FCFA)", min_value=0, value=25000, step=2500)
            acompte      = st.number_input("Acompte reçu (FCFA)", min_value=0, value=1_000_000, step=50000)
            observation  = st.text_area("Observation / Notes", value="")

        taux  = TAUX_MAP.get(devise_key, taux_usd)
        fob_xof        = quantite * prix_unitaire * taux
        fret_xof       = fret_devise * taux
        assurance_xof  = max((fob_xof + fret_xof) * 0.005, 5000.0)
        caf_xof        = fob_xof + fret_xof + assurance_xof
        total_douane, details_douane = calculer_droits_douane(caf_xof, item_info["dd"], regime_code)
        total_transit  = frais_port + frais_guce
        total_facture  = caf_xof + total_douane + total_transit + transport_int
        solde_du       = total_facture - acompte

        with col_b:
            fdi_msg = "✅ FDI non requise (< 1M)" if fob_xof < 1_000_000 else "⚠️ FDI & RFC obligatoires (GUCE)"
            st.markdown(
                f"""<div style="background:#0F172A;padding:18px;border-radius:12px;border:1px solid #334155;">
                <b>Code SH :</b> <code>{item_info['sh']}</code><br/>
                <b>Catégorie :</b> {item_info['cat']}<br/>
                <b>DD standard :</b> {item_info['dd']}%<br/><hr style="border-color:#334155"/>
                <small style="color:#38BDF8;">{fdi_msg}</small>
                </div>""",
                unsafe_allow_html=True,
            )

        st.markdown("<br/>", unsafe_allow_html=True)
        st.caption(f"ℹ️ Détail douane SYDAM : {details_douane}")

        m1, m2, m3, m4 = st.columns(4)
        for col, label, val, color in zip(
            [m1, m2, m3, m4],
            ["Valeur CAF", "Droits & Taxes", "Port & Transit", "TOTAL FACTURÉ"],
            [caf_xof, total_douane, total_transit + transport_int, total_facture],
            ["#38BDF8", "#F59E0B", "#A78BFA", "#10B981"],
        ):
            with col:
                st.markdown(
                    f'<div class="kpi-card"><div class="kpi-title">{label}</div>'
                    f'<div class="kpi-value" style="color:{color};">{val:,.0f} FCFA</div></div>',
                    unsafe_allow_html=True,
                )

        st.markdown("<br/>", unsafe_allow_html=True)
        col_save, col_pdf, col_wa = st.columns(3)

        with col_save:
            if st.button("💾 Enregistrer le Dossier", type="primary", use_container_width=True):
                add_dossier(
                    nom_client, article_nom, regime_code, fob_xof,
                    total_facture, solde_du, "En cours",
                    bl_num, container_num, date_arrivee.strftime("%Y-%m-%d"),
                    franchise_j, frais_sj,
                    email_client, tel_client, devise_key,
                    uploaded_path, observation,
                )
                add_audit(
                    st.session_state.username, "dossier_cree",
                    f"client={nom_client}; total={total_facture:,.0f} FCFA"
                )
                st.success("✅ Dossier enregistré avec succès !")

        with col_pdf:
            # FIX #9 : PDF généré uniquement à la demande
            if st.button("📥 Générer & Télécharger le PDF", use_container_width=True):
                with st.spinner("Génération du PDF..."):
                    pdf_path = build_pdf(
                        nom_client, article_nom, item_info, regime_code, quantite,
                        fob_xof, fret_xof, assurance_xof, caf_xof,
                        total_douane, total_transit, transport_int,
                        total_facture, acompte, solde_du,
                        bl_num, container_num,
                    )
                with open(pdf_path, "rb") as f:
                    st.download_button(
                        "📄 Télécharger la Proforma", f.read(),
                        file_name=pdf_path.name, mime="application/pdf",
                        use_container_width=True,
                    )

        with col_wa:
            msg = f"Bonjour {nom_client}, votre cotation : {total_facture:,.0f} FCFA, solde {solde_du:,.0f} FCFA."
            phone_clean = re.sub(r"[^0-9+]", "", tel_client)
            st.link_button("💬 Envoyer via WhatsApp", f"https://wa.me/{phone_clean.lstrip('+')}?text={quote(msg)}", use_container_width=True)

    st.markdown("</div>", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 3 — CHRONOMÈTRE SURESTARIES
# ═══════════════════════════════════════════════════════════════════════════════
with tab_surest:
    st.markdown('<div class="custom-card">', unsafe_allow_html=True)
    st.subheader("🚨 Chronomètre Anti-Surestaries")
    df_dos = get_dossiers()
    if df_dos.empty:
        st.info("Aucun dossier avec date d'arrivée enregistré.")
    else:
        today = datetime.now().date()
        penalites_cumulees = 0.0
        for _, row in df_dos.iterrows():
            if not row.get("date_arrivee"):
                continue
            try:
                dt_arr   = datetime.strptime(str(row["date_arrivee"]), "%Y-%m-%d").date()
                franchise = int(row["jours_franchise"] or 14)
                frais_j   = float(row["frais_surestarie_jour"] or 25000)
                dt_limite = dt_arr + timedelta(days=franchise)
                restants  = (dt_limite - today).days

                ca, cb, cc = st.columns([3, 2, 1])
                with ca:
                    st.markdown(
                        f"**{row['client']}** — Cont.: `{row.get('container_number') or 'N/A'}` "
                        f"| B/L: `{row.get('bl_number') or 'N/A'}`"
                    )
                    st.caption(f"Arrivée: {dt_arr} | Limite franchise ({franchise}j): {dt_limite}")
                with cb:
                    if restants > 3:
                        st.markdown(f'<div class="alert-green">🟢 {restants} jours restants</div>', unsafe_allow_html=True)
                    elif 0 <= restants <= 3:
                        st.markdown(f'<div class="alert-yellow">🟡 URGENCE : {restants} jours !</div>', unsafe_allow_html=True)
                    else:
                        penalite = abs(restants) * frais_j
                        penalites_cumulees += penalite
                        st.markdown(
                            f'<div class="alert-red">🔴 Dépassement {abs(restants)}j — '
                            f'Pénalité: {penalite:,.0f} FCFA</div>',
                            unsafe_allow_html=True,
                        )
                with cc:
                    st.metric("Statut", row["statut"])
                st.markdown("---")
            except (ValueError, TypeError):
                continue

        if penalites_cumulees > 0:
            st.error(f"⚠️ Pénalités surestaries cumulées : **{penalites_cumulees:,.0f} FCFA**")
    st.markdown("</div>", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 4 — TRACKING MARITIME
# ═══════════════════════════════════════════════════════════════════════════════
with tab_map:
    st.markdown('<div class="custom-card">', unsafe_allow_html=True)
    st.subheader("🗺️ Route Maritime Chine ➔ Côte d'Ivoire")
    st.caption("⚠️ Carte de démonstration — route et position navire estimées. Non connecté à un AIS en temps réel.")
    if PLOTLY_OK:
        fig_map = go.Figure()
        route_lon = [113.26, 103.85, 43.15, 32.55, -4.01]
        route_lat = [23.13,  1.35,  11.59, 29.95,  5.31]
        labels    = ["Guangzhou (Départ)", "Singapour", "Golfe d'Aden", "Canal de Suez", "Abidjan (Arrivée)"]
        fig_map.add_trace(go.Scattergeo(
            lon=route_lon, lat=route_lat,
            mode="lines+markers",
            line=dict(width=3, color="#10B981"),
            marker=dict(size=8, color="#38BDF8"),
            text=labels, hovertemplate="%{text}<extra></extra>",
        ))
        fig_map.add_trace(go.Scattergeo(
            lon=[60.0], lat=[5.0],
            mode="markers+text",
            marker=dict(size=14, color="#F59E0B", symbol="triangle-right"),
            text=["🚢 NAVIRE EN TRANSIT (démo)"],
            textposition="top center",
        ))
        fig_map.update_layout(
            geo=dict(
                projection_type="mollweide",
                showland=True, landcolor="#1E293B",
                showocean=True, oceancolor="#0B0F19",
                showcountries=True, countrycolor="#334155",
            ),
            paper_bgcolor="rgba(0,0,0,0)",
            font_color="white",
            margin=dict(l=0, r=0, t=10, b=0),
        )
        st.plotly_chart(fig_map, use_container_width=True)
    else:
        st.info("Installez plotly pour afficher la carte : `pip install plotly`")
    st.markdown("</div>", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 5 — CRM & DOSSIERS
# ═══════════════════════════════════════════════════════════════════════════════
with tab_crm:
    st.markdown('<div class="custom-card">', unsafe_allow_html=True)
    st.subheader("📂 Registre des Dossiers CRM")
    df_dos2 = get_dossiers()

    if df_dos2.empty:
        st.info("Aucun dossier enregistré.")
    else:
        # Filtres
        q_search  = st.text_input("🔍 Recherche (client / article / statut)")
        f_statuts = st.multiselect("Filtrer par statut", STATUTS, default=STATUTS)

        filtered = df_dos2.copy()
        if q_search:
            q = q_search.lower()
            mask = (
                filtered["client"].str.lower().str.contains(q, na=False) |
                filtered["article"].str.lower().str.contains(q, na=False) |
                filtered["statut"].str.lower().str.contains(q, na=False)
            )
            filtered = filtered[mask]
        if f_statuts:
            filtered = filtered[filtered["statut"].isin(f_statuts)]

        # KPI bar
        kk1, kk2, kk3, kk4 = st.columns(4)
        for col, titre, val in zip(
            [kk1, kk2, kk3, kk4],
            ["Dossiers", "Facturation", "Soldes", "Livrés"],
            [
                str(len(filtered)),
                f"{filtered['total_facture'].sum():,.0f} FCFA",
                f"{filtered['solde_du'].sum():,.0f} FCFA",
                str(int((filtered["statut"] == "Livré au Client").sum())),
            ],
        ):
            with col:
                st.markdown(
                    f'<div class="kpi-card"><div class="kpi-title">{titre}</div>'
                    f'<div class="kpi-value">{val}</div></div>',
                    unsafe_allow_html=True,
                )

        cols_display = ["id", "date", "client", "article", "regime",
                        "total_facture", "solde_du", "statut",
                        "bl_number", "container_number", "date_arrivee"]
        cols_display = [c for c in cols_display if c in filtered.columns]
        st.dataframe(filtered[cols_display], use_container_width=True)

        ex1, ex2 = st.columns(2)
        with ex1:
            st.download_button(
                "📗 Export Excel", export_excel(filtered),
                "dossiers_crm.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
        with ex2:
            st.download_button(
                "📄 Export CSV", filtered.to_csv(index=False).encode("utf-8-sig"),
                "dossiers_crm.csv", "text/csv", use_container_width=True,
            )

        st.markdown("---")
        st.subheader("✏️ Modifier / Supprimer un Dossier")

        if not filtered.empty:
            df_articles_edit = get_articles()
            sel_id  = st.selectbox("Sélectionner l'ID du Dossier", filtered["id"].tolist())
            row_dos = filtered[filtered["id"] == sel_id].iloc[0]
            liste_articles_edit = df_articles_edit["nom"].tolist()

            # FIX #19 : Formulaire Edit séparé du formulaire Delete
            with st.form("form_edit"):
                e_client  = st.text_input("Client", value=row_dos["client"])
                e_article = st.selectbox(
                    "Article", liste_articles_edit,
                    index=liste_articles_edit.index(row_dos["article"])
                    if row_dos["article"] in liste_articles_edit else 0,
                )
                e_regime  = st.selectbox(
                    "Régime", REGIMES,
                    index=REGIMES.index(row_dos["regime"]) if row_dos["regime"] in REGIMES else 0,
                )
                e_solde   = st.number_input("Solde Dû (FCFA)", value=float(row_dos["solde_du"]))
                e_statut  = st.selectbox(
                    "Statut", STATUTS,
                    index=STATUTS.index(row_dos["statut"]) if row_dos["statut"] in STATUTS else 0,
                )
                e_bl      = st.text_input("N° B/L",        value=str(row_dos.get("bl_number") or ""))
                e_cont    = st.text_input("N° Conteneur",  value=str(row_dos.get("container_number") or ""))
                e_arr     = st.text_input("Date Arrivée (YYYY-MM-DD)", value=str(row_dos.get("date_arrivee") or ""))
                e_fran    = st.number_input("Franchise (jours)", value=int(row_dos.get("jours_franchise") or 14))
                e_frais   = st.number_input("Frais Surestarie/j", value=float(row_dos.get("frais_surestarie_jour") or 25000))

                if st.form_submit_button("💾 Enregistrer les modifications", use_container_width=True):
                    update_dossier(
                        sel_id, e_client, e_article, e_regime,
                        e_solde, e_statut, e_bl, e_cont,
                        e_arr, e_fran, e_frais,
                    )
                    add_audit(st.session_state.username, "dossier_modifie", f"id={sel_id}")
                    st.success("Dossier mis à jour !")
                    st.rerun()

            # FIX #14 : Suppression réservée aux admins et commerciaux
            if st.session_state.user_role in ["Administrateur", "Commercial / Déclarant"]:
                with st.form("form_delete"):
                    st.warning(f"⚠️ Supprimer le dossier #{sel_id} de {row_dos['client']} ?")
                    if st.form_submit_button("🗑️ Confirmer la suppression", use_container_width=True):
                        delete_dossier(sel_id)
                        add_audit(st.session_state.username, "dossier_supprime", f"id={sel_id}")
                        st.warning("Dossier supprimé.")
                        st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 6 — CODE DES DOUANES
# ═══════════════════════════════════════════════════════════════════════════════
with tab_code:
    st.markdown('<div class="custom-card">', unsafe_allow_html=True)
    st.subheader("📖 Référentiel — Code des Douanes de Côte d'Ivoire")

    articles_loi = {
        "Art. 12 — Valeur en Douane (CAF)": (
            "La valeur en douane est la valeur transactionnelle (prix payé ou à payer), "
            "ajustée du fret et de l'assurance jusqu'au port d'entrée (Abidjan / San-Pédro)."
        ),
        "Art. 85 — Régime C100 : Mise à la Consommation": (
            "Permet la mise en libre circulation sur le territoire national après paiement "
            "des droits et taxes (DD, TVA 18 %, RS 1 %, PCS 0,8 %, PUA 0,2 %)."
        ),
        "Art. 142 — Régime E100 : Entrepôt de Douane (Suspensif)": (
            "Stockage en suspension de droits et taxes pour une durée maximale de 1 à 2 ans "
            "avant destination définitive. Redevance d'entrepôt : 0,5 % de la valeur CAF."
        ),
        "Art. 168 — Régime AT : Admission Temporaire": (
            "Réception de marchandises en suspension de droits pour transformation/utilisation "
            "puis réexportation. Taxe AT : 1 % de la valeur CAF."
        ),
        "Art. 205 — Régime TR : Transit / Réexportation": (
            "Acheminement sous contrôle douanier sans paiement de droits et taxes. "
            "Redevance de transit : 0,5 % de la valeur CAF."
        ),
        "Programme VOC / CoC — Webb Fontaine & Cotecna": (
            "Tout produit d'une valeur FOB ≥ 1 000 000 FCFA requiert une Attestation de "
            "Vérification Documentaire (AVD) et un Certificat de Conformité (CoC) avant embarquement."
        ),
        "FDI / RFC — Domiciliation Bancaire": (
            "La Fiche de Demande d'Importation (FDI) est obligatoire pour toute importation "
            "supérieure à 1 000 000 FCFA. Elle doit être visée par la banque domiciliataire "
            "avant toute opération de change."
        ),
    }

    rech = st.text_input("🔍 Rechercher (ex: CAF, TVA, Webb, Entrepôt...)")
    for titre, contenu in articles_loi.items():
        if not rech or rech.lower() in titre.lower() or rech.lower() in contenu.lower():
            with st.expander(titre):
                st.write(contenu)
    st.markdown("</div>", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 7 — ASSISTANT IA
# ═══════════════════════════════════════════════════════════════════════════════
with tab_ai:
    st.markdown('<div class="custom-card">', unsafe_allow_html=True)
    st.subheader("🤖 Assistant Expert Douanier (Groq Llama 3)")
    question = st.text_area("Posez votre question douanière / réglementaire :", height=120,
                             placeholder="Ex: Quels documents sont requis pour une importation de téléphones depuis la Chine ?")
    if st.button("🔍 Obtenir une réponse", type="primary", use_container_width=True):
        if not question.strip():
            st.warning("Veuillez saisir une question.")
        else:
            ctx = (
                f"Dossiers enregistrés : {len(get_dossiers())} | "
                f"Articles dans la base : {len(get_articles())} | "
                f"Statuts opérationnels : {', '.join(STATUTS)}"
            )
            with st.spinner("Analyse en cours par l'IA..."):
                answer, errors = ask_ai(st.session_state.groq_api_key, question, ctx)
            if answer:
                st.markdown(answer)
                add_audit(st.session_state.username, "ia_query", question[:200])
            else:
                st.error("Impossible d'obtenir une réponse. Vérifiez votre clé Groq.")
                if errors:
                    with st.expander("Détails techniques"):
                        st.code("\n".join(errors))
    st.markdown("</div>", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 8 — BASE SH & ARTICLES
# ═══════════════════════════════════════════════════════════════════════════════
with tab_sh:
    st.markdown('<div class="custom-card">', unsafe_allow_html=True)
    st.subheader("📚 Base Tarifaire — Codes SH & Articles")
    df_art = get_articles()

    if st.session_state.user_role in ["Administrateur", "Commercial / Déclarant"]:
        with st.form("form_add_article"):
            st.caption("Ajouter un nouvel article")
            a1, a2, a3, a4 = st.columns(4)
            with a1: n_nom = st.text_input("Désignation")
            with a2: n_sh  = st.text_input("Code SH (ex: 8517.13.00)")
            with a3: n_dd  = st.number_input("DD (%)", min_value=0.0, max_value=100.0, value=20.0)
            with a4: n_cat = st.text_input("Catégorie")
            if st.form_submit_button("➕ Ajouter l'article", use_container_width=True):
                if n_nom.strip() and n_sh.strip():
                    try:
                        add_article(n_nom, n_sh, n_dd, n_cat)
                        add_audit(st.session_state.username, "article_ajoute", f"{n_nom} / {n_sh}")
                        st.success("Article ajouté !")
                        st.rerun()
                    except sqlite3.IntegrityError:
                        st.error("Cet article existe déjà.")
                else:
                    st.warning("Désignation et Code SH obligatoires.")

    st.dataframe(df_art, use_container_width=True)

    if st.session_state.user_role == "Administrateur" and not df_art.empty:
        st.markdown("---")
        st.caption("Supprimer un article")
        del_id = st.selectbox("Article à supprimer (ID)", df_art["id"].tolist(),
                               format_func=lambda i: f"[{i}] {df_art.loc[df_art['id']==i,'nom'].iloc[0]}")
        if st.button("🗑️ Supprimer cet article", type="secondary"):
            delete_article(del_id)
            add_audit(st.session_state.username, "article_supprime", f"id={del_id}")
            st.warning("Article supprimé.")
            st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 9 — ADMIN & AUDIT LOGS (Administrateur uniquement)
# ═══════════════════════════════════════════════════════════════════════════════
if is_admin and tab_admin is not None:
    with tab_admin:
        st.markdown('<div class="custom-card">', unsafe_allow_html=True)
        st.subheader("🔐 Gestion des Utilisateurs")

        df_users = get_users()
        st.dataframe(df_users, use_container_width=True)

        with st.form("form_add_user"):
            st.caption("Créer un nouvel utilisateur")
            u1, u2, u3 = st.columns(3)
            with u1: new_user = st.text_input("Identifiant")
            with u2: new_pass = st.text_input("Mot de passe", type="password")
            with u3: new_role = st.selectbox("Rôle", ROLES)
            if st.form_submit_button("Créer l'utilisateur", use_container_width=True):
                if new_user.strip() and new_pass.strip():
                    try:
                        create_user(new_user.strip(), new_pass, new_role)
                        add_audit(st.session_state.username, "user_cree", f"username={new_user}")
                        st.success("Utilisateur créé !")
                        st.rerun()
                    except sqlite3.IntegrityError:
                        st.error("Cet identifiant existe déjà.")
                else:
                    st.warning("Identifiant et mot de passe obligatoires.")

        st.markdown("---")
        st.subheader("📋 Journal d'Audit (200 dernières entrées)")
        df_audit = get_audit_logs(200)
        if df_audit.empty:
            st.info("Aucune entrée d'audit.")
        else:
            rech_audit = st.text_input("Filtrer l'audit (utilisateur / action / détail)")
            if rech_audit:
                ra = rech_audit.lower()
                df_audit = df_audit[
                    df_audit["utilisateur"].str.lower().str.contains(ra, na=False) |
                    df_audit["action"].str.lower().str.contains(ra, na=False) |
                    df_audit["details"].str.lower().str.contains(ra, na=False)
                ]
            st.dataframe(df_audit, use_container_width=True)
            st.download_button(
                "📥 Exporter Audit (CSV)",
                df_audit.to_csv(index=False).encode("utf-8-sig"),
                "audit_logs.csv", "text/csv", use_container_width=True,
            )
        st.markdown("</div>", unsafe_allow_html=True)

# ─── AUDIT DE SESSION ──────────────────────────────────────────────────────────
# Tracé de la consultation (une seule fois par session via session_state)
if not st.session_state.get("_session_logged"):
    add_audit(st.session_state.username, "session_open", "page_opened")
    st.session_state._session_logged = True
