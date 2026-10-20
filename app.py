"""
app.py — Kelanewin Transit SYDAM Pro Ultra (iOS SpringBoard 3D Edition)
Système Intégré d'Import-Export Chine → Côte d'Ivoire
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

# ─── CONFIGURATION & CHEMINS ───────────────────────────────────────────────────
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

# ─── UTILITAIRES & SÉCURITÉ ────────────────────────────────────────────────────

def setting(name: str, default: str = "") -> str:
    try:
        val = st.secrets.get(name, None)
        if val not in (None, ""):
            return str(val)
    except Exception:
        pass
    return os.getenv(name, default)


def hash_password(password: str) -> str:
    salt = setting("APP_SALT", "KelanewinTransit2026SecureSalt")
    return hashlib.sha256((password + salt).encode("utf-8")).hexdigest()


def safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._") or "document"
    return cleaned[:120]

# ─── BASE DE DONNÉES & MIGRATIONS ──────────────────────────────────────────────

def db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=10.0)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with db_connection() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS articles (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            nom         TEXT UNIQUE NOT NULL,
            sh          TEXT NOT NULL,
            dd          REAL NOT NULL,
            categorie   TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS dossiers (
            id                      INTEGER PRIMARY KEY AUTOINCREMENT,
            date                    TEXT NOT NULL,
            client                  TEXT NOT NULL,
            article                 TEXT NOT NULL,
            regime                  TEXT NOT NULL DEFAULT 'C100 - Mise à la consommation',
            fob_xof                 REAL NOT NULL DEFAULT 0,
            total_facture           REAL NOT NULL DEFAULT 0,
            solde_du                REAL NOT NULL DEFAULT 0,
            statut                  TEXT NOT NULL DEFAULT 'En cours',
            bl_number               TEXT,
            container_number        TEXT,
            date_arrivee            TEXT,
            jours_franchise         INTEGER DEFAULT 14,
            frais_surestarie_jour   REAL    DEFAULT 25000,
            document_path           TEXT,
            email                   TEXT,
            telephone               TEXT,
            devise                  TEXT    DEFAULT 'CNY',
            observation             TEXT
        );

        CREATE TABLE IF NOT EXISTS fournisseurs_chine (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            nom_usine   TEXT NOT NULL,
            ville       TEXT NOT NULL,
            contact     TEXT,
            produits    TEXT
        );

        CREATE TABLE IF NOT EXISTS users (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            username        TEXT UNIQUE NOT NULL,
            password_hash   TEXT NOT NULL,
            role            TEXT NOT NULL,
            statut          TEXT NOT NULL DEFAULT 'Actif'
        );

        CREATE TABLE IF NOT EXISTS audit_logs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at  TEXT NOT NULL,
            utilisateur TEXT NOT NULL,
            action      TEXT NOT NULL,
            details     TEXT
        );
        """)

        default_articles = [
            ("Station Totale Topographique & GNSS/GPS", "9015.80.00", 5.0,  "Topographie"),
            ("Smartphones, iPhones & Téléphones portables","8517.13.00",20.0,"High-Tech"),
            ("Ordinateurs Portables, MacBooks & Tablettes","8471.30.00", 5.0,"Informatique"),
            ("Panneaux Photovoltaïques / Solaires",        "8541.43.00", 5.0, "Énergie"),
            ("Groupes Électrogènes (Générateurs)",         "8502.11.00", 5.0, "Machines"),
            ("Vélos et Bicyclettes sans moteur",           "8712.00.00", 20.0,"Transport (Deux-roues)"),
            ("Motos & Motocycles (125cc - 250cc)",         "8711.20.00", 20.0,"Transport (Deux-roues)"),
            ("Voitures de Tourisme (Berlines / SUV)",      "8703.22.00", 20.0,"Transport (Véhicules)"),
            ("Vêtements Homme (Pantalons, Chemises)",      "6203.00.00", 20.0,"Textile"),
            ("Sacs à main pour Dames",                     "4202.22.00", 20.0,"Maroquinerie"),
        ]
        conn.executemany(
            "INSERT OR IGNORE INTO articles (nom, sh, dd, categorie) VALUES (?,?,?,?)",
            default_articles,
        )

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
    return read_df("SELECT * FROM audit_logs ORDER BY id DESC LIMIT ?", (limit,))


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


def add_article(nom, sh, dd, categorie) -> None:
    with db_connection() as conn:
        conn.execute(
            "INSERT INTO articles (nom, sh, dd, categorie) VALUES (?,?,?,?)",
            (nom.strip(), sh.strip(), dd, categorie.strip() or "Autre"),
        )


def create_user(username, password, role) -> None:
    with db_connection() as conn:
        conn.execute(
            "INSERT INTO users (username, password_hash, role, statut) VALUES (?,?,?,'Actif')",
            (username, hash_password(password), role),
        )

# ─── TAUX DE CHANGE ────────────────────────────────────────────────────────────

@st.cache_data(ttl=3600)
def fetch_rates() -> tuple[dict, str]:
    defaults = {"CNY": 85.0, "USD": 610.0, "EUR": 655.957, "AED": 166.0}
    try:
        r = requests.get("https://open.er-api.com/v6/latest/USD", timeout=4)
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

# ─── MOTEUR DE CALCUL DOUANIER UEMOA ───────────────────────────────────────────

def calculer_droits_douane(caf_xof: float, dd_pct: float, regime_code: str) -> tuple[float, str]:
    if "C100" in regime_code:
        tdd = dd_pct / 100.0
        redev = 0.010 + 0.008 + 0.002
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
    else:
        tdd = dd_pct / 100.0
        droits = caf_xof * (tdd + 0.02)
        tva = (caf_xof + droits) * 0.18
        total = droits + tva
        details = f"Régime standard — Total: {total:,.0f} FCFA"
    return total, details

# ─── GÉNÉRATEUR DE DEVIS PDF ───────────────────────────────────────────────────

def build_pdf(
    client, article_nom, item_info, regime_code, quantite,
    fob_xof, fret_xof, assurance_xof, caf_xof,
    total_douane, total_transit, post_ach,
    total_facture, acompte, solde_du,
    bl_num="", container_num=""
) -> Path:
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
            "Agrément Douane N° 2026/CI-ABJ | Port Autonome d'Abidjan &amp; San-Pédro<br/>"
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

# ─── ASSISTANT IA GROQ ─────────────────────────────────────────────────────────

def ask_ai(api_key: str, question: str, context: str) -> tuple[str | None, list[str]]:
    if not Groq or not api_key:
        return None, ["Bibliothèque groq absente ou clé API manquante."]
    client = Groq(api_key=api_key)
    system_prompt = (
        "Tu es l'assistant expert en douane, transit et logistique portuaire de Kelanewin Transit en Côte d'Ivoire. "
        "Maîtrise parfaite du SYDAM, du Tarif Douanier UEMOA et des procédures portuaires d'Abidjan."
    )
    errors: list[str] = []
    for model in ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]:
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
        df.to_excel(writer, index=False, sheet_name="Dossiers_Transit")
    return buf.getvalue()

# ─── DESIGN iOS SPRINGBOARD 3D & CONFIGURATION PAGE ──────────────────────────────

st.set_page_config(
    page_title="Kelanewin Transit — Chine/Côte d'Ivoire",
    page_icon="🇨🇮",
    layout="wide",
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');

html, body, [class*="css"] {
    font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif;
    color: #F8FAFC;
}

.stApp {
    background: linear-gradient(135deg, #0A0F1D 0%, #030712 100%);
    background-attachment: fixed;
}

.header-banner {
    background: linear-gradient(135deg, rgba(6, 95, 70, 0.9) 0%, rgba(5, 150, 105, 0.9) 50%, rgba(2, 132, 199, 0.9) 100%);
    padding: 35px 40px;
    border-radius: 28px;
    color: white;
    margin-bottom: 30px;
    box-shadow: 0 30px 60px -15px rgba(0, 0, 0, 0.8), inset 0 1px 2px rgba(255, 255, 255, 0.4);
    border: 1px solid rgba(255, 255, 255, 0.2);
    backdrop-filter: blur(25px);
}

.springboard-container {
    background: rgba(15, 23, 42, 0.65);
    border-radius: 24px;
    padding: 24px;
    border: 1px solid rgba(255, 255, 255, 0.1);
    backdrop-filter: blur(20px);
    box-shadow: 0 20px 40px -15px rgba(0,0,0,0.7);
    margin-bottom: 25px;
}

.custom-card {
    background: rgba(17, 24, 39, 0.8);
    border-radius: 24px;
    padding: 32px;
    border: 1px solid rgba(255, 255, 255, 0.08);
    margin-bottom: 30px;
    box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.9);
    backdrop-filter: blur(20px);
}

.kpi-card {
    background: linear-gradient(145deg, rgba(31, 41, 55, 0.9), rgba(17, 24, 39, 0.95));
    border-radius: 20px;
    padding: 24px;
    border: 1px solid rgba(255, 255, 255, 0.12);
    box-shadow: inset 0 1px 2px rgba(255,255,255,0.1), 0 15px 35px -10px rgba(0,0,0,0.6);
    text-align: center;
}

.kpi-title { font-size: 0.85rem; color: #94A3B8; text-transform: uppercase; font-weight: 700; margin-bottom: 8px; }
.kpi-value { font-size: 1.7rem; font-weight: 800; color: #38BDF8; }

.alert-green { background: rgba(6, 78, 59, 0.85); border-left: 6px solid #10B981; padding: 16px; border-radius: 14px; margin-bottom: 15px; }
.alert-red { background: rgba(127, 29, 29, 0.85); border-left: 6px solid #EF4444; padding: 16px; border-radius: 14px; margin-bottom: 15px; }

div[data-testid="stButton"] > button {
    border-radius: 16px !important;
    font-weight: 700 !important;
    padding: 0.65rem 1.4rem;
    transition: all 0.3s ease !important;
    box-shadow: 0 6px 15px rgba(0, 0, 0, 0.4);
}

#MainMenu, footer { visibility: hidden; }
</style>
""", unsafe_allow_html=True)

# ─── GESTION SESSION & AUTH ────────────────────────────────────────────────────

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
    st.session_state.username = ""
    st.session_state.user_role = ""

if "groq_api_key" not in st.session_state:
    st.session_state.groq_api_key = setting("GROQ_API_KEY", "")

if not st.session_state.authenticated:
    st.markdown("<br><br>", unsafe_allow_html=True)
    col_l, col_m, col_r = st.columns([1, 2, 1])
    with col_m:
        st.markdown('<div class="custom-card">', unsafe_allow_html=True)
        st.subheader("🔐 Connexion — Kelanewin Transit")
        st.caption("Sécurité Cryptographique · Contrôle d'Accès RBAC")
        u_input = st.text_input("Identifiant")
        p_input = st.text_input("Mot de passe", type="password")
        if st.button("Se connecter", use_container_width=True, type="primary"):
            user = get_user(u_input)
            if user is None:
                st.error("Utilisateur introuvable.")
            elif user["statut"] != "Actif":
                st.error("Ce compte a été désactivé.")
            elif hash_password(p_input) == user["password_hash"]:
                st.session_state.authenticated = True
                st.session_state.username = user["username"]
                st.session_state.user_role = user["role"]
                add_audit(user["username"], "login", "Connexion réussie")
                st.rerun()
            else:
                st.error("Mot de passe incorrect.")
        st.caption("Accès par défaut : admin / transit2026")
        st.markdown("</div>", unsafe_allow_html=True)
    st.stop()

taux_devises, status_api = fetch_rates()

# ─── SIDEBAR ───────────────────────────────────────────────────────────────────

st.sidebar.title("🇨🇮 KELANEWIN TRANSIT")
st.sidebar.markdown(f"**Utilisateur :** `{st.session_state.username}`")
st.sidebar.markdown(f"**Rôle :** `{st.session_state.user_role}`")
st.sidebar.markdown("---")

groq_key_input = st.sidebar.text_input("🔑 Clé API Groq", value=st.session_state.groq_api_key, type="password")
if groq_key_input != st.session_state.groq_api_key:
    st.session_state.groq_api_key = groq_key_input

st.sidebar.subheader("💱 Taux de change (FCFA)")
st.sidebar.caption(status_api)
taux_cny = st.sidebar.number_input("1 CNY →", value=taux_devises["CNY"], step=0.1, format="%.2f")
taux_usd = st.sidebar.number_input("1 USD →", value=taux_devises["USD"], step=1.0, format="%.2f")
TAUX_MAP = {"CNY": taux_cny, "USD": taux_usd, "EUR": 655.957, "AED": 166.0}

st.sidebar.markdown("---")
if st.sidebar.button("🚪 Se déconnecter", use_container_width=True):
    add_audit(st.session_state.username, "logout", "Déconnexion")
    st.session_state.authenticated = False
    st.rerun()

# ─── EN-TÊTE & MENU SPRINGBOARD ───────────────────────────────────────────────

st.markdown("""
<div class="header-banner">
  <h1>📦 KELANEWIN TRANSIT · CHINE ➔ CÔTE D'IVOIRE</h1>
  <p>Plateforme Intégrée d'Import-Export & Gestion Douanière (SYDAM Pro Ultra)</p>
</div>
""", unsafe_allow_html=True)

st.markdown('<div class="springboard-container">', unsafe_allow_html=True)
st.markdown("### 📱 Menu d'Application Principal (iOS Style Grid)")

menu_options = [
    "📈 Dashboard",
    "📄 Cotation & Douane",
    "🚨 Surestaries",
    "🗺️ Tracking Chine-Abidjan",
    "📂 CRM & Dossiers",
    "🇨🇳 Fournisseurs Chine",
    "🤖 Assistant IA",
    "📚 Base SH",
]
is_admin = st.session_state.user_role == "Administrateur"
if is_admin:
    menu_options.append("🔐 Admin & Audit")

cols = st.columns(3)
if "selected_app" not in st.session_state:
    st.session_state.selected_app = "📈 Dashboard"

for idx, option in enumerate(menu_options):
    col_target = cols[idx % 3]
    with col_target:
        if st.button(option, use_container_width=True):
            st.session_state.selected_app = option

st.markdown(f"**Module actif :** `{st.session_state.selected_app}`")
st.markdown('</div>', unsafe_allow_html=True)

selected_tab = st.session_state.selected_app

# ═══════════════════════════════════════════════════════════════════════════════
# ROUTAGE DES MODULES
# ═══════════════════════════════════════════════════════════════════════════════

if selected_tab == "📈 Dashboard":
    st.markdown('<div class="custom-card">', unsafe_allow_html=True)
    st.subheader("📈 Performance Financière & Opérationnelle")
    df_d = get_dossiers()
    if df_d.empty:
        st.info("Aucun dossier enregistré. Créez votre premier dossier dans Cotation & Douane.")
    else:
        tot_ca    = df_d["total_facture"].sum()
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
                fig = px.pie(df_d, names="statut", title="Répartition par Statut Opérationnel", hole=0.4)
                fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", font_color="white")
                st.plotly_chart(fig, use_container_width=True)
            with g2:
                fig2 = px.bar(df_d, x="article", y="total_facture", color="regime", title="Facturation par Article & Régime")
                fig2.update_layout(paper_bgcolor="rgba(0,0,0,0)", font_color="white")
                st.plotly_chart(fig2, use_container_width=True)
        else:
            st.dataframe(df_d[["date", "client", "article", "total_facture", "statut"]], use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)

elif selected_tab == "📄 Cotation & Douane":
    df_articles = get_articles()
    st.markdown('<div class="custom-card">', unsafe_allow_html=True)
    st.subheader("📄 Simulateur de Cotation & Facturation Pro (Chine ➔ Abidjan)")
    
    col_s1, col_s2 = st.columns(2)
    with col_s1:
        client_nom = st.text_input("Nom du Client / Entreprise", "SARL Global Trade CI")
        email_cl = st.text_input("Email Client", "client@globaltrade.ci")
        article_choisi = st.selectbox("Article / Marchandise", df_articles["nom"].tolist())
        item_row = df_articles[df_articles["nom"] == article_choisi].iloc[0]
        regime_choisi = st.selectbox("Régime Douanier", REGIMES)
        
    with col_s2:
        devise_achat = st.selectbox("Devise d'achat fournisseur", ["CNY", "USD", "EUR"], index=0)
        montant_devise = st.number_input("Facture Fournisseur (Devise)", value=50000.0, step=1000.0)
        quantite_art = st.number_input("Quantité d'unités", value=100, step=1)
        fret_devise = st.number_input("Fret international (Devise)", value=3000.0, step=100.0)
        assurance_devise = st.number_input("Assurance maritime (Devise)", value=500.0, step=100.0)

    taux_actuel = TAUX_MAP.get(devise_achat, 85.0)
    fob_xof = montant_devise * taux_actuel
    fret_xof = fret_devise * taux_actuel
    assurance_xof = assurance_devise * taux_actuel
    caf_xof = fob_xof + fret_xof + assurance_xof

    dd_taux = float(item_row["dd"])
    total_douane, details_douane = calculer_droits_douane(caf_xof, dd_taux, regime_choisi)

    frais_port = 150000.0
    frais_guce = 45000.0
    honoraires = max(100000.0, fob_xof * 0.03)
    total_transit = frais_port + frais_guce + honoraires

    post_acheminement = 120000.0
    total_facture = caf_xof + total_douane + total_transit + post_acheminement

    st.markdown("---")
    rc1, rc2, rc3, rc4 = st.columns(4)
    rc1.metric("Valeur FOB (FCFA)", f"{fob_xof:,.0f}")
    rc2.metric("Valeur CAF (FCFA)", f"{caf_xof:,.0f}")
    rc3.metric("Droits & Taxes", f"{total_douane:,.0f} FCFA")
    rc4.metric("TOTAL GÉNÉRAL", f"{total_facture:,.0f} FCFA")

    acompte_verse = st.number_input("Acompte versé par le client (FCFA)", value=total_facture * 0.5, step=50000.0)
    solde_restant = total_facture - acompte_verse

    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        if st.button("📄 Générer le Devis PDF Pro", use_container_width=True, type="primary"):
            pdf_path = build_pdf(
                client=client_nom, article_nom=article_choisi, item_info=item_row,
                regime_code=regime_choisi, quantite=quantite_art, fob_xof=fob_xof,
                fret_xof=fret_xof, assurance_xof=assurance_xof, caf_xof=caf_xof,
                total_douane=total_douane, total_transit=total_transit, post_ach=post_acheminement,
                total_facture=total_facture, acompte=acompte_verse, solde_du=solde_restant
            )
            with open(pdf_path, "rb") as f:
                st.download_button("📥 Télécharger Devis PDF", f.read(), file_name=pdf_path.name, mime="application/pdf", use_container_width=True)

    with col_btn2:
        if st.button("💾 Enregistrer dans le CRM", use_container_width=True):
            add_dossier(
                client=client_nom, article=article_choisi, regime=regime_choisi,
                fob=fob_xof, total=total_facture, solde=solde_restant, statut="En cours",
                bl="", container="", date_arrivee=(datetime.now() + timedelta(days=25)).strftime("%Y-%m-%d"),
                franchise=14, frais_surest=25000.0, email=email_cl, telephone="+225 07000000",
                devise=devise_achat, observation=f"Import Chine - {quantite_art} unités"
            )
            st.success("Dossier enregistré avec succès !")
    st.markdown("</div>", unsafe_allow_html=True)

elif selected_tab == "🚨 Surestaries":
    st.markdown('<div class="custom-card">', unsafe_allow_html=True)
    st.subheader("🚨 Suivi des Surestaries Conteneurs (Port d'Abidjan)")
    df_d = get_dossiers()
    if df_d.empty:
        st.info("Aucun dossier actif.")
    else:
        for idx, row in df_d.iterrows():
            if row["date_arrivee"]:
                try:
                    d_arr = datetime.strptime(row["date_arrivee"], "%Y-%m-%d")
                    jours_ecoules = (datetime.now() - d_arr).days
                    franchise = int(row["jours_franchise"] or 14)
                    coût_jour = float(row["frais_surestarie_jour"] or 25000)
                    jours_retard = max(0, jours_ecoules - franchise)
                    montant = jours_retard * coût_jour
                    with st.expander(f"📦 Dossier #{row['id']} — Client : {row['client']}"):
                        if jours_retard > 0:
                            st.markdown(f'<div class="alert-red"><b>Pénalité active :</b> {montant:,.0f} FCFA ({jours_retard} jours de retard).</div>', unsafe_allow_html=True)
                        else:
                            st.markdown(f'<div class="alert-green"><b>Dans les délais :</b> Reste {franchise - jours_ecoules} jours de franchise.</div>', unsafe_allow_html=True)
                except Exception:
                    pass
    st.markdown("</div>", unsafe_allow_html=True)

elif selected_tab == "🗺️ Tracking Chine-Abidjan":
    st.markdown('<div class="custom-card">', unsafe_allow_html=True)
    st.subheader("🗺️ Tracking Maritime en Temps Réel (Ningbo / Shanghai ➔ Abidjan)")
    st.markdown("> * **Ligne :** Asie - Afrique de l'Ouest (MSC / CMA CGM)\n> * **ETA Port d'Abidjan :** Dans 14 jours")
    map_data = pd.DataFrame({
        "lat": [31.2304, 1.2921, 12.8628, 5.3600],
        "lon": [121.4737, 103.8198, 45.0340, -4.0083],
        "lieu": ["Shanghai (Chine)", "Singapour (Hub)", "Golfe d'Aden", "Port d'Abidjan (CI)"]
    })
    st.map(map_data, zoom=2)
    st.markdown("</div>", unsafe_allow_html=True)

elif selected_tab == "📂 CRM & Dossiers":
    st.markdown('<div class="custom-card">', unsafe_allow_html=True)
    st.subheader("📂 Gestion CRM & Suivi des Dossiers")
    df_d = get_dossiers()
    if not df_d.empty:
        st.dataframe(df_d[["id", "date", "client", "article", "total_facture", "solde_du", "statut"]], use_container_width=True)
        excel_bytes = export_excel(df_d)
        st.download_button("📊 Exporter les dossiers (Excel)", excel_bytes, "Kelanewin_Dossiers.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    else:
        st.info("Aucun dossier.")
    st.markdown("</div>", unsafe_allow_html=True)

elif selected_tab == "🇨🇳 Fournisseurs Chine":
    st.markdown('<div class="custom-card">', unsafe_allow_html=True)
    st.subheader("🇨🇳 Annuaire & Suivi des Fournisseurs en Chine (Yiwu / Shenzhen)")
    with st.form("form_fournisseur"):
        f_nom = st.text_input("Nom de l'usine / Fournisseur")
        f_ville = st.text_input("Ville en Chine (ex: Yiwu, Guangzhou)")
        f_prod = st.text_input("Produits principaux")
        if st.form_submit_button("Enregistrer le fournisseur", type="primary"):
            if f_nom:
                with db_connection() as conn:
                    conn.execute("INSERT INTO fournisseurs_chine (nom_usine, ville, produits) VALUES (?, ?, ?)", (f_nom, f_ville, f_prod))
                st.success("Fournisseur enregistré avec succès !")
                st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)

elif selected_tab == "🤖 Assistant IA":
    st.markdown('<div class="custom-card">', unsafe_allow_html=True)
    st.subheader("🤖 Assistant IA SYDAM & Douanes")
    user_q = st.text_area("Posez votre question sur les procédures d'importation :")
    if st.button("Interroger l'IA", type="primary"):
        if st.session_state.groq_api_key and user_q:
            with st.spinner("Analyse..."):
                ans, errs = ask_ai(st.session_state.groq_api_key, user_q, "Importation Chine ➔ Côte d'Ivoire")
                if ans:
                    st.markdown(ans)
                else:
                    st.error(f"Erreur : {errs}")
        else:
            st.warning("Veuillez renseigner votre clé API Groq dans la barre latérale et saisir une question.")
    st.markdown("</div>", unsafe_allow_html=True)

elif selected_tab == "📚 Base SH":
    st.markdown('<div class="custom-card">', unsafe_allow_html=True)
    st.subheader("📚 Base de Données des Codes SH & Tarifs Douaniers")
    st.dataframe(get_articles(), use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)

elif selected_tab == "🔐 Admin & Audit" and is_admin:
    st.markdown('<div class="custom-card">', unsafe_allow_html=True)
    st.subheader("🔐 Administration & Journaux d'Audit")
    st.dataframe(get_users(), use_container_width=True)
    st.markdown("### Journaux d'Audit")
    st.dataframe(get_audit_logs(50), use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)
