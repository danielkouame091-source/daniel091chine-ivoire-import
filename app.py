"""
app.py — Kelanewin Transit SYDAM Pro Ultra
Système intégré de gestion douanière pour l'importation Chine → Côte d'Ivoire.
Architecture Enterprise Grade — Version 4.3 (Propre, Parfaite & Validée)
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
    """Lit un secret Streamlit puis la variable d'environnement avec repli sécurisé."""
    try:
        val = st.secrets.get(name, None)
        if val not in (None, ""):
            return str(val)
    except Exception:
        pass
    return os.getenv(name, default)


def hash_password(password: str) -> str:
    """Hachage cryptographique (SHA-256 avec sel applicatif pour robustesse)."""
    salt = setting("APP_SALT", "KelanewinTransit2026SecureSalt")
    return hashlib.sha256((password + salt).encode("utf-8")).hexdigest()


def safe_filename(value: str) -> str:
    """Nettoie une chaîne pour en faire un nom de fichier valide et sécurisé."""
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
            ("Théodolites, Niveaux Optiques & Laser",    "9015.10.00", 5.0,  "Topographie"),
            ("Smartphones, iPhones & Téléphones portables","8517.13.00",20.0,"High-Tech"),
            ("Ordinateurs Portables, MacBooks & Tablettes","8471.30.00", 5.0,"Informatique"),
            ("Panneaux Photovoltaïques / Solaires",        "8541.43.00", 5.0, "Énergie"),
            ("Groupes Électrogènes (Générateurs)",         "8502.11.00", 5.0, "Machines"),
            ("Vélos et Bicyclettes sans moteur",           "8712.00.00", 20.0,"Transport (Deux-roues)"),
            ("Motos & Motocycles (125cc - 250cc)",         "8711.20.00", 20.0,"Transport (Deux-roues)"),
            ("Voitures de Tourisme (Berlines / SUV)",      "8703.22.00", 20.0,"Transport (Véhicules)"),
            ("Vêtements Homme (Pantalons, Chemises)",      "6203.00.00", 20.0,"Textile"),
            ("Vêtements Femme (Robes, Jupes)",             "6204.00.00", 20.0,"Textile"),
            ("Vêtements Bébés & Enfants",                  "6209.00.00", 20.0,"Textile"),
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

# ─── TAUX DE CHANGE EN TEMPS RÉEL ──────────────────────────────────────────────

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

# ─── MOTEUR DE CALCUL DOUANIER SYDAM ────────────────────────────────────────────

def calculer_droits_douane(caf_xof: float, dd_pct: float, regime_code: str) -> tuple[float, str]:
    if "C100" in regime_code:
        tdd = dd_pct / 100.0
        redev = 0.010 + 0.008 + 0.002  # RS + PCS + PUA (Côte d'Ivoire)
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

# ─── GÉNÉRATEUR DE DEVIS PDF PROFESSIONNEL ──────────────────────────────────────

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

# ─── INTÉGRATION IA GROQ ───────────────────────────────────────────────────────

def ask_ai(api_key: str, question: str, context: str) -> tuple[str | None, list[str]]:
    if not Groq or not api_key:
        return None, ["Bibliothèque groq absente ou clé API manquante."]
    client = Groq(api_key=api_key)
    system_prompt = (
        "Tu es l'assistant expert en douane, transit et logistique portuaire de Kelanewin Transit en Côte d'Ivoire. "
        "Maîtrise parfaite du SYDAM, du Tarif Douanier UEMOA et des procédures portuaires d'Abidjan. "
        "Réponds en français, de façon précise, technique et opérationnelle."
    )
    errors: list[str] = []
    for model in ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768"]:
        try:
            res = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Contexte opérationnel: {context}\n\nQuestion: {question}"},
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

# ─── CONFIGURATION DE LA PAGE STREAMLIT ────────────────────────────────────────

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

# ─── GESTION DE LA SESSION ─────────────────────────────────────────────────────

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
    st.session_state.username = ""
    st.session_state.user_role = ""

if "groq_api_key" not in st.session_state:
    st.session_state.groq_api_key = setting("GROQ_API_KEY", "")

# ─── ÉCRAN D'AUTHENTIFICATION ──────────────────────────────────────────────────

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
                st.error("Ce compte a été désactivé par l'administrateur.")
            elif hash_password(p_input) == user["password_hash"]:
                st.session_state.authenticated = True
                st.session_state.username = user["username"]
                st.session_state.user_role = user["role"]
                add_audit(user["username"], "login", "Connexion réussie")
                st.rerun()
            else:
                st.error("Mot de passe incorrect.")
        st.caption("Accès par défaut : admin / transit2026 | commercial / compta2026 | comptable / finance2026")
        st.markdown("</div>", unsafe_allow_html=True)
    st.stop()

# ─── RÉCUPÉRATION DES TAUX DE CHANGE ───────────────────────────────────────────

taux_devises, status_api = fetch_rates()

# ─── BARRE LATÉRALE (SIDEBAR) ──────────────────────────────────────────────────

st.sidebar.title("🇨🇮 KELANEWIN TRANSIT")
st.sidebar.markdown(f"**Utilisateur :** `{st.session_state.username}`")
st.sidebar.markdown(f"**Rôle :** `{st.session_state.user_role}`")
st.sidebar.markdown("---")

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
_smtp_port_str = setting("SMTP_PORT", "")
smtp_port = int(_smtp_port_str) if _smtp_port_str.isdigit() else int(st.sidebar.number_input("Port SMTP", value=587, step=1))
smtp_sender   = setting("SMTP_USERNAME", "") or st.sidebar.text_input("Expéditeur email", "")
smtp_password = setting("SMTP_PASSWORD", "") or st.sidebar.text_input("Mot de passe app", type="password")

st.sidebar.markdown("---")
if st.sidebar.button("🚪 Se déconnecter", use_container_width=True):
    add_audit(st.session_state.username, "logout", "Déconnexion")
    st.session_state.authenticated = False
    st.rerun()

# ─── EN-TÊTE PRINCIPAL ─────────────────────────────────────────────────────────

st.markdown("""
<div class="header-banner">
  <h1>📦 KELANEWIN TRANSIT · ENTERPRISE SUITE v4.3</h1>
  <p>Système Intégré de Gestion Douanière — Importation Chine & International → Côte d'Ivoire (SYDAM Pro)</p>
</div>
""", unsafe_allow_html=True)

# ─── NAVIGATION PAR ONGLETS (TABS) ─────────────────────────────────────────────

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
tab_admin = tabs[8] if is_admin else None

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 1 — TABLEAU DE BORD (DASHBOARD)
# ═══════════════════════════════════════════════════════════════════════════════
with tab_dash:
    st.markdown('<div class="custom-card">', unsafe_allow_html=True)
    st.subheader("📈 Performance Financière & Opérationnelle")
    df_d = get_dossiers()
    if df_d.empty:
        st.info("Aucun dossier enregistré. Créez votre premier dossier dans l'onglet Cotation.")
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
                fig = px.pie(
                    df_d, names="statut", title="Répartition par Statut Opérationnel", hole=0.4,
                    color_discrete_sequence=px.colors.qualitative.Set2,
                )
                fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", font_color="white")
                st.plotly_chart(fig, use_container_width=True)
            with g2:
                fig2 = px.bar(
                    df_d, x="article", y="total_facture", color="regime",
                    title="Facturation par Article & Régime Douanier", barmode="group",
                )
                fig2.update_layout(paper_bgcolor="rgba(0,0,0,0)", font_color="white")
                st.plotly_chart(fig2, use_container_width=True)
        else:
            st.dataframe(df_d[["date", "client", "article", "total_facture", "statut"]], use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 2 — COTATION & SIMULATEUR DOUANIER
# ═══════════════════════════════════════════════════════════════════════════════
with tab_cotation:
    df_articles = get_articles()
    st.markdown('<div class="custom-card">', unsafe_allow_html=True)
    st.subheader("📄 Simulateur de Cotation & Facturation Pro")
    st.caption("Calcul instantané des droits de douane UEMOA (SYDAM) & Frais Portuaires Abidjan")

    col_s1, col_s2 = st.columns(2)
    with col_s1:
        client_nom = st.text_input("Nom du Client / Entreprise", "SARL Global Trade CI")
        email_cl = st.text_input("Email Client (pour envoi devis PDF)", "client@globaltrade.ci")
        tel_cl = st.text_input("Téléphone Client", "+225 07 12 34 56 78")
        
        article_choisi = st.selectbox("Article / Marchandise", df_articles["nom"].tolist())
        item_row = df_articles[df_articles["nom"] == article_choisi].iloc[0]
        
        regime_choisi = st.selectbox("Régime Douanier", REGIMES)
        
    with col_s2:
        devise_achat = st.selectbox("Devise d'achat fournisseur", ["CNY", "USD", "EUR", "AED"], index=0)
        montant_devise = st.number_input("Montant de la facture fournisseur (Devise)", value=50000.0, step=1000.0)
        quantite_art = st.number_input("Quantité d'unités", value=100, step=1)
        
        fret_devise = st.number_input("Fret international (Devise)", value=3000.0, step=100.0)
        assurance_devise = st.number_input("Assurance maritime (Devise)", value=500.0, step=50.0)

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
    st.subheader("💰 Synthèse Financière de la Cotation")
    rc1, rc2, rc3, rc4 = st.columns(4)
    rc1.metric("Valeur FOB (FCFA)", f"{fob_xof:,.0f}")
    rc2.metric("Valeur CAF (FCFA)", f"{caf_xof:,.0f}")
    rc3.metric("Droits & Taxes", f"{total_douane:,.0f} FCFA")
    rc4.metric("TOTAL GÉNÉRAL", f"{total_facture:,.0f} FCFA")

    with st.expander("🔍 Voir le détail des calculs douaniers"):
        st.write(f"**Code SH :** `{item_row['sh']}` | **Droit de Douane (DD) :** `{dd_taux}%`")
        st.write(f"**Détails imposition :** {details_douane}")
        st.write(f"**Frais Transit & Port :** {total_transit:,.0f} FCFA (Port: {frais_port:,.0f} | GUCE: {frais_guce:,.0f} | Honoraires: {honoraires:,.0f})")

    acompte_verse = st.number_input("Acompte versé par le client (FCFA)", value=total_facture * 0.5, step=50000.0)
    solde_restant = total_facture - acompte_verse

    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        if st.button("📄 Générer le Devis PDF Pro", use_container_width=True, type="primary"):
            pdf_path = build_pdf(
                client=client_nom,
                article_nom=article_choisi,
                item_info=item_row,
                regime_code=regime_choisi,
                quantite=quantite_art,
                fob_xof=fob_xof,
                fret_xof=fret_xof,
                assurance_xof=assurance_xof,
                caf_xof=caf_xof,
                total_douane=total_douane,
                total_transit=total_transit,
                post_ach=post_acheminement,
                total_facture=total_facture,
                acompte=acompte_verse,
                solde_du=solde_restant,
            )
            with open(pdf_path, "rb") as pdf_file:
                st.download_button(
                    label="📥 Télécharger le Devis PDF",
                    data=pdf_file.read(),
                    file_name=pdf_path.name,
                    mime="application/pdf",
                    use_container_width=True,
                )
            st.success("Devis PDF généré avec succès !")

    with col_btn2:
        if st.button("💾 Enregistrer dans le CRM / Dossiers", use_container_width=True):
            add_dossier(
                client=client_nom,
                article=article_choisi,
                regime=regime_choisi,
                fob=fob_xof,
                total=total_facture,
                solde=solde_restant,
                statut="En cours",
                bl="",
                container="",
                date_arrivee=(datetime.now() + timedelta(days=25)).strftime("%Y-%m-%d"),
                franchise=14,
                frais_surest=25000.0,
                email=email_cl,
                telephone=tel_cl,
                devise=devise_achat,
                observation=f"Cotation auto - {quantite_art} unités",
            )
            add_audit(st.session_state.username, "creation_dossier", f"Dossier créé pour {client_nom}")
            st.success("Dossier enregistré dans la base de données avec succès !")

    st.markdown("</div>", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 3 — SURESTARIES & FRANCHISES CONTENEURS
# ═══════════════════════════════════════════════════════════════════════════════
with tab_surest:
    st.markdown('<div class="custom-card">', unsafe_allow_html=True)
    st.subheader("🚨 Simulateur & Suivi des Surestaries Conteneurs")
    st.caption("Évitez les pénalités d'immobilisation des conteneurs au Port d'Abidjan (PAO)")

    df_d = get_dossiers()
    if df_d.empty:
        st.info("Aucun dossier actif pour calculer les surestaries.")
    else:
        for idx, row in df_d.iterrows():
            if row["date_arrivee"]:
                try:
                    d_arr = datetime.strptime(row["date_arrivee"], "%Y-%m-%d")
                    jours_ecoules = (datetime.now() - d_arr).days
                    franchise = int(row["jours_franchise"] or 14)
                    coût_jour = float(row["frais_surestarie_jour"] or 25000)
                    
                    jours_retard = max(0, jours_ecoules - franchise)
                    montant_surestarie = jours_retard * coût_jour

                    with st.expander(f"📦 Dossier #{row['id']} — Client : {row['client']} | Conteneur : {row['container_number'] or 'Non assigné'}"):
                        c1, c2, c3 = st.columns(3)
                        c1.metric("Date d'arrivée", row["date_arrivee"])
                        c2.metric("Jours de franchise", f"{franchise} jours")
                        c3.metric("Surestaries estimées", f"{montant_surestarie:,.0f} FCFA", delta=f"{jours_retard} jours de retard", delta_color="inverse")
                        
                        if jours_retard > 0:
                            st.markdown(f'<div class="alert-red"><b>ALERTE SURESTARIES :</b> Ce conteneur dépasse la franchise de {jours_retard} jours ! Pénalité active : {montant_surestarie:,.0f} FCFA.</div>', unsafe_allow_html=True)
                        else:
                            st.markdown(f'<div class="alert-green"><b>Dans les délais :</b> Il reste {franchise - jours_ecoules} jours avant application des pénalités.</div>', unsafe_allow_html=True)
                except Exception:
                    pass
    st.markdown("</div>", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 4 — TRACKING MARITIME & GÉOLOCALISATION
# ═══════════════════════════════════════════════════════════════════════════════
with tab_map:
    st.markdown('<div class="custom-card">', unsafe_allow_html=True)
    st.subheader("🗺️ Tracking Maritime en Temps Réel (Route Chine → Abidjan)")
    st.caption("Suivi des navires porte-conteneurs (Ligne Ningbo / Shanghai / Shenzhen → Port Autonome d'Abidjan)")

    st.markdown("""
    > 💡 **Information Navire (Démo interactive) :**  
    > * **Navire :** MSC Jade / CMA CGM ULV (Ligne Asie-Afrique de l'Ouest)  
    > * **Position actuelle :** Golfe d'Aden / Passage au large de Djibouti  
    > * **ETA Port d'Abidjan :** Dans 14 jours  
    """)

    map_data = pd.DataFrame({
        "lat": [31.2304, 1.2921, 12.8628, 5.3600],
        "lon": [121.4737, 103.8198, 45.0340, -4.0083],
        "lieu": ["Port de Shanghai (Chine)", "Singapour (Hub)", "Golfe d'Aden", "Port d'Abidjan (Côte d'Ivoire)"]
    })
    st.map(map_data, zoom=2)
    st.markdown("</div>", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 5 — CRM & GESTION DES DOSSIERS
# ═══════════════════════════════════════════════════════════════════════════════
with tab_crm:
    st.markdown('<div class="custom-card">', unsafe_allow_html=True)
    st.subheader("📂 Gestion CRM & Suivi des Dossiers de Transit")
    
    df_d = get_dossiers()
    if df_d.empty:
        st.info("Aucun dossier enregistré.")
    else:
        search_q = st.text_input("🔍 Rechercher un dossier (Client, Article, B/L, Conteneur)")
        if search_q:
            mask = df_d.apply(lambda row: row.astype(str).str.contains(search_q, case=False).any(), axis=1)
            df_filtered = df_d[mask]
        else:
            df_filtered = df_d

        st.dataframe(df_filtered[["id", "date", "client", "article", "regime", "total_facture", "solde_du", "statut", "bl_number", "container_number"]], use_container_width=True)

        st.markdown("### ✏️ Mettre à jour un dossier")
        dossier_ids = df_d["id"].tolist()
        sel_id = st.selectbox("Sélectionner l'ID du dossier à modifier", dossier_ids)
        
        if sel_id:
            d_row = df_d[df_d["id"] == sel_id].iloc[0]
            with st.form("form_update_dossier"):
                u_client = st.text_input("Client", value=d_row["client"])
                u_article = st.text_input("Article", value=d_row["article"])
                u_regime = st.selectbox("Régime", REGIMES, index=REGIMES.index(d_row["regime"]) if d_row["regime"] in REGIMES else 0)
                u_solde = st.number_input("Solde dû (FCFA)", value=float(d_row["solde_du"]))
                u_statut = st.selectbox("Statut", STATUTS, index=STATUTS.index(d_row["statut"]) if d_row["statut"] in STATUTS else 0)
                u_bl = st.text_input("N° B/L (Connaissement)", value=d_row["bl_number"] or "")
                u_cont = st.text_input("N° Conteneur", value=d_row["container_number"] or "")
                u_arr = st.text_input("Date d'arrivée (AAAA-MM-JJ)", value=d_row["date_arrivee"] or "")
                u_fran = st.number_input("Jours de franchise", value=int(d_row["jours_franchise"] or 14))
                u_sur = st.number_input("Frais surestarie / jour (FCFA)", value=float(d_row["frais_surestarie_jour"] or 25000))
                
                submitted = st.form_submit_button("Mettre à jour le dossier", type="primary")
                if submitted:
                    if st.session_state.user_role == "Commercial / Déclarant" and u_statut == "Bon à Enlever (BAE) Émis":
                        st.error("Action non autorisée : Seul un administrateur ou le service financier peut valider le BAE.")
                    else:
                        update_dossier(sel_id, u_client, u_article, u_regime, u_solde, u_statut, u_bl, u_cont, u_arr, u_fran, u_sur)
                        add_audit(st.session_state.username, "update_dossier", f"Mise à jour dossier #{sel_id}")
                        st.success("Dossier mis à jour avec succès !")
                        st.rerun()

        st.markdown("---")
        excel_bytes = export_excel(df_d)
        st.download_button(
            label="📊 Exporter tous les dossiers (Excel)",
            data=excel_bytes,
            file_name="Kelanewin_Dossiers_Transit.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    st.markdown("</div>", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 6 — CODE DES DOUANES & TARIF EXTÉRIEUR COMMUN (TEC)
# ═══════════════════════════════════════════════════════════════════════════════
with tab_code:
    st.markdown('<div class="custom-card">', unsafe_allow_html=True)
    st.subheader("📖 Code des Douanes de Côte d'Ivoire & TEC UEMOA")
    st.caption("Consultez la réglementation douanière, les régimes suspensifs et les taux applicables")

    search_sh = st.text_input("🔍 Rechercher par Code SH ou Nom de marchandise")
    df_art = get_articles()
    if search_sh:
        df_art = df_art[df_art.apply(lambda r: r.astype(str).str.contains(search_sh, case=False).any(), axis=1)]

    st.dataframe(df_art[["nom", "sh", "dd", "categorie"]], use_container_width=True)

    st.markdown("---")
    st.markdown("### 🏛️ Notes sur les Régimes Douaniers en Côte d'Ivoire")
    st.markdown("""
    * **C100 (Mise à la consommation) :** Dédouanement définitif avec acquittement des Droits de Douane (DD), de la Redevance Statistique (RS), du Prélèvement Communautaire de Solidarité (PCS), du PUA et de la TVA (18%).
    * **E100 (Entrepôt de douane) :** Régime suspensif permettant de stocker les marchandises en franchise de droits et taxes en attendant leur réexportation ou mise à la consommation ultérieure.
    * **AT (Admission Temporaire) :** Pour les matériels professionnels (topographie, BTP, etc.) avec réexportation prévue sous 6 à 12 mois.
    """)
    st.markdown("</div>", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 7 — ASSISTANT IA SYDAM
# ═══════════════════════════════════════════════════════════════════════════════
with tab_ai:
    st.markdown('<div class="custom-card">', unsafe_allow_html=True)
    st.subheader("🤖 Assistant IA SYDAM & Réglementation Douanière")
    st.caption("Posez vos questions sur les procédures douanières portuaires à Abidjan, le calcul des taxes ou les litiges SH.")

    user_q = st.text_area("Votre question à l'expert IA :", placeholder="Ex: Quel est le taux de douane pour l'importation de smartphones en Côte d'Ivoire ?")
    if st.button("Poser la question à l'IA", type="primary"):
        if not st.session_state.groq_api_key:
            st.error("Veuillez renseigner votre clé API Groq dans la barre latérale.")
        elif not user_q:
            st.warning("Veuillez saisir une question.")
        else:
            with st.spinner("Analyse par l'IA SYDAM..."):
                ans, errs = ask_ai(st.session_state.groq_api_key, user_q, "Contexte: Importation Chine → Côte d'Ivoire, Port d'Abidjan.")
                if ans:
                    st.markdown("### 💡 Réponse de l'Expert IA")
                    st.markdown(ans)
                else:
                    st.error(f"Erreur lors de la consultation de l'IA : {errs}")
    st.markdown("</div>", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 8 — BASE SH & ARTICLES
# ═══════════════════════════════════════════════════════════════════════════════
with tab_sh:
    st.markdown('<div class="custom-card">', unsafe_allow_html=True)
    st.subheader("📚 Gestion de la Base de Données SH & Articles")
    
    df_art = get_articles()
    st.dataframe(df_art, use_container_width=True)

    if is_admin:
        st.markdown("### ➕ Ajouter un nouvel article douanier")
        with st.form("form_add_art"):
            n_nom = st.text_input("Nom de l'article")
            n_sh = st.text_input("Code SH (ex: 8517.13.00)")
            n_dd = st.number_input("Taux Droits de Douane (%)", value=20.0, step=1.0)
            n_cat = st.text_input("Catégorie", "High-Tech")
            
            submitted_art = st.form_submit_button("Ajouter l'article", type="primary")
            if submitted_art:
                if n_nom and n_sh:
                    add_article(n_nom, n_sh, n_dd, n_cat)
                    add_audit(st.session_state.username, "add_article", f"Ajout article SH {n_sh}")
                    st.success("Article ajouté avec succès !")
                    st.rerun()
                else:
                    st.error("Veuillez remplir le nom et le code SH.")
    st.markdown("</div>", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 9 — ADMINISTRATION & AUDIT LOGS (ADMIN ONLY)
# ═══════════════════════════════════════════════════════════════════════════════
if is_admin and tab_admin is not None:
    with tab_admin:
        st.markdown('<div class="custom-card">', unsafe_allow_html=True)
        st.subheader("🔐 Administration Système & Journaux d'Audit (RBAC)")
        
        st.markdown("### 👥 Gestion des Utilisateurs")
        df_u = get_users()
        st.dataframe(df_u, use_container_width=True)

        st.markdown("### ➕ Créer un nouvel utilisateur")
        with st.form("form_create_user"):
            new_u = st.text_input("Nom d'utilisateur")
            new_p = st.text_input("Mot de passe", type="password")
            new_r = st.selectbox("Rôle", ROLES)
            sub_u = st.form_submit_button("Créer le compte", type="primary")
            if sub_u:
                if new_u and new_p:
                    try:
                        create_user(new_u, new_p, new_r)
                        add_audit(st.session_state.username, "create_user", f"Création utilisateur {new_u}")
                        st.success(f"Utilisateur {new_u} créé avec succès !")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Erreur : {e}")
                else:
                    st.error("Veuillez remplir tous les champs.")

        st.markdown("---")
        st.markdown("### 📜 Journaux d'Audit & Sécurité (Audit Logs)")
        df_logs = get_audit_logs(100)
        st.dataframe(df_logs, use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)
