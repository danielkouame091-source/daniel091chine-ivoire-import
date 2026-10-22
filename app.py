"""
app.py — Kelanewin Transit SYDAM Pro Ultra (iOS SpringBoard 3D Ultimate Edition)
Global Import-Export & Customs Management Platform (Enterprise Licensing Edition)
"""

import base64
import hashlib
import io
import os
import re
import sqlite3
from datetime import datetime, timedelta
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

STATUSES = [
    "In Progress",
    "FDI & Customs Cleared",
    "Customs Inspection Underway",
    "Out of Gate / Delivery Order Issued",
    "Delivered to Client",
]

REGIMES = [
    "C100 - Home Consumption (Duty Paid)",
    "E100 - Customs Warehouse (Suspensive)",
    "AT - Temporary Admission",
    "TR - Transit / Re-export",
]

# ─── UTILITAIRES & SÉCURITÉ ────────────────────────────────────────────────────

def setting(name: str, default: str = "") -> str:
    try:
        val = st.secrets.get(name, None)
        if val not in (None, ""):
            return str(val)
    except Exception:
        pass
    return os.getenv(name, default)


def hash_key(key_string: str) -> str:
    salt = setting("APP_SALT", "KelanewinTransit2026SecureSalt")
    return hashlib.sha256((key_string + salt).encode("utf-8")).hexdigest()


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
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            nom        TEXT UNIQUE NOT NULL,
            sh         TEXT NOT NULL,
            dd         REAL NOT NULL,
            categorie  TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS dossiers (
            id                     INTEGER PRIMARY KEY AUTOINCREMENT,
            date                   TEXT NOT NULL,
            client                 TEXT NOT NULL,
            article                TEXT NOT NULL,
            regime                 TEXT NOT NULL DEFAULT 'C100 - Home Consumption (Duty Paid)',
            fob_inr                REAL NOT NULL DEFAULT 0,
            total_facture          REAL NOT NULL DEFAULT 0,
            solde_du               REAL NOT NULL DEFAULT 0,
            statut                 TEXT NOT NULL DEFAULT 'In Progress',
            bl_number              TEXT,
            container_number       TEXT,
            date_arrivee           TEXT,
            jours_franchise        INTEGER DEFAULT 14,
            frais_surestarie_jour  REAL    DEFAULT 2500,
            document_path          TEXT,
            email                  TEXT,
            telephone              TEXT,
            devise                 TEXT    DEFAULT 'USD',
            observation            TEXT
        );

        CREATE TABLE IF NOT EXISTS fournisseurs_chine (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            nom_usine  TEXT NOT NULL,
            ville      TEXT NOT NULL,
            contact    TEXT,
            produits   TEXT
        );

        CREATE TABLE IF NOT EXISTS paiements_fournisseurs (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            date              TEXT NOT NULL,
            fournisseur       TEXT NOT NULL,
            montant_devise    REAL NOT NULL,
            devise            TEXT NOT NULL,
            taux_applique     REAL NOT NULL,
            montant_inr       REAL NOT NULL,
            statut_paiement   TEXT NOT NULL DEFAULT 'Paid'
        );

        CREATE TABLE IF NOT EXISTS licenses (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            license_key    TEXT UNIQUE NOT NULL,
            holder_name    TEXT NOT NULL,
            role           TEXT NOT NULL,
            status         TEXT NOT NULL DEFAULT 'Active',
            created_at     TEXT NOT NULL
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
            ("Topographic Total Station & GNSS/GPS", "9015.80.00", 5.0,  "Surveying"),
            ("Smartphones, iPhones & Mobile Phones", "8517.13.00", 20.0, "High-Tech"),
            ("Laptops, MacBooks & Tablets",          "8471.30.00", 5.0,  "IT Hardware"),
            ("Photovoltaic / Solar Panels",          "8541.43.00", 5.0,  "Energy"),
            ("Diesel Generators",                    "8502.11.00", 5.0,  "Machinery"),
            ("Bicycles & Non-motorized Cycles",      "8712.00.00", 20.0, "Two-Wheelers"),
            ("Motorcycles & Scooters (125cc-250cc)", "8711.20.00", 20.0, "Two-Wheelers"),
            ("Passenger Cars (Sedans / SUVs)",       "8703.22.00", 20.0, "Vehicles"),
            ("Men's Apparel (Trousers, Shirts)",     "6203.00.00", 20.0, "Textile"),
            ("Women's Handbags & Luggage",           "4202.22.00", 20.0, "Leather Goods"),
        ]
        conn.executemany(
            "INSERT OR IGNORE INTO articles (nom, sh, dd, categorie) VALUES (?,?,?,?)",
            default_articles,
        )

        # Clé Administrateur Suprême (Créateur) créée par défaut : MASTER-CREATOR-2026
        master_key = hash_key("MASTER-CREATOR-2026")
        conn.execute(
            "INSERT OR IGNORE INTO licenses (license_key, holder_name, role, status, created_at) VALUES (?,?,?,?,?)",
            (master_key, "Chief Creator (Admin)", "Creator / Master", "Active", datetime.now().strftime("%Y-%m-%d"))
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


def get_fournisseurs() -> pd.DataFrame:
    return read_df("SELECT * FROM fournisseurs_chine ORDER BY id DESC")


def get_paiements() -> pd.DataFrame:
    return read_df("SELECT * FROM paiements_fournisseurs ORDER BY id DESC")


def get_licenses() -> pd.DataFrame:
    return read_df("SELECT id, holder_name, role, status, created_at FROM licenses ORDER BY id ASC")


def get_audit_logs(limit: int = 200) -> pd.DataFrame:
    return read_df("SELECT * FROM audit_logs ORDER BY id DESC LIMIT ?", (limit,))


def verify_license(raw_key: str):
    hashed = hash_key(raw_key.strip())
    with db_connection() as conn:
        row = conn.execute(
            "SELECT * FROM licenses WHERE license_key = ? AND status = 'Active'",
            (hashed,),
        ).fetchone()
    return dict(row) if row else None


def generate_license(holder: str, role: str, raw_key: str) -> None:
    hashed = hash_key(raw_key.strip())
    with db_connection() as conn:
        conn.execute(
            "INSERT INTO licenses (license_key, holder_name, role, status, created_at) VALUES (?,?,?,?,?)",
            (hashed, holder, role, "Active", datetime.now().strftime("%Y-%m-%d"))
        )


def add_dossier(
    client, article, regime, fob, total, solde, statut,
    bl, container, date_arrivee, franchise, frais_surest,
    email, telephone, devise, document_path="", observation=""
) -> None:
    with db_connection() as conn:
        conn.execute(
            """INSERT INTO dossiers
               (date, client, article, regime, fob_inr, total_facture, solde_du, statut,
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


def add_article(nom, sh, dd, categorie) -> None:
    with db_connection() as conn:
        conn.execute(
            "INSERT INTO articles (nom, sh, dd, categorie) VALUES (?,?,?,?)",
            (nom.strip(), sh.strip(), dd, categorie.strip() or "Other"),
        )

# ─── TAUX DE CHANGE (BASE INR / ₹) ─────────────────────────────────────────────

@st.cache_data(ttl=3600)
def fetch_rates() -> tuple[dict, str]:
    defaults = {"USD": 83.5, "CNY": 11.5, "EUR": 90.0, "AED": 22.7}
    try:
        r = requests.get("https://open.er-api.com/v6/latest/USD", timeout=4)
        if r.status_code == 200:
            rates = r.json().get("rates", {})
            usd_inr = float(rates.get("INR", 83.5))
            usd_cny = float(rates.get("CNY", 7.2))
            usd_eur = float(rates.get("EUR", 0.92))
            usd_aed = float(rates.get("AED", 3.67))
            return {
                "USD": round(usd_inr, 2),
                "CNY": round(usd_inr / usd_cny, 2) if usd_cny else defaults["CNY"],
                "EUR": round(usd_inr / usd_eur, 2) if usd_eur else defaults["EUR"],
                "AED": round(usd_inr / usd_aed, 2) if usd_aed else defaults["AED"],
            }, "🟢 Live API Exchange Rates Active"
    except Exception:
        pass
    return defaults, "⚠️ Offline Mode (Fallback Rates)"

# ─── MOTEUR DE CALCUL DOUANIER ─────────────────────────────────────────────────

def calculate_customs_duties(cif_inr: float, dd_pct: float, regime_code: str) -> tuple[float, str]:
    if "C100" in regime_code:
        t_dd = dd_pct / 100.0
        cess_fees = 0.010 + 0.008 + 0.002
        duties = cif_inr * (t_dd + cess_fees)
        gst = (cif_inr + duties) * 0.18
        total = duties + gst
        details = (
            f"Basic Customs Duty ({dd_pct}%): {cif_inr*t_dd:,.2f} | "
            f"Surcharges & Levies: {cif_inr*cess_fees:,.2f} | GST 18%: {gst:,.2f} ₹"
        )
    elif "E100" in regime_code:
        duties = cif_inr * 0.005
        total = duties
        details = f"Suspensive Warehouse E100 — Storage Fee: {duties:,.2f} ₹"
    elif "AT" in regime_code:
        duties = cif_inr * 0.010
        total = duties
        details = f"Temporary Admission — AT Tax: {duties:,.2f} ₹"
    else:
        t_dd = dd_pct / 100.0
        duties = cif_inr * (t_dd + 0.02)
        gst = (cif_inr + duties) * 0.18
        total = duties + gst
        details = f"Standard Regime — Total Duties: {total:,.2f} ₹"
    return total, details

# ─── GÉNÉRATEUR DE DEVIS PDF ───────────────────────────────────────────────────

def build_pdf(
    client, article_nom, item_info, regime_code, quantity,
    fob_inr, freight_inr, insurance_inr, cif_inr,
    total_customs, total_transit, inland_haulage,
    total_invoice, advance_paid, balance_due,
    bl_num="", container_num=""
) -> Path:
    fname = BASE_DIR / f"Proforma_Invoice_{safe_filename(client)}.pdf"
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
            "Customs License No. 2026/IND-MUM | Authorized Port Logistics &amp; Freight Forwarding<br/>"
            "contact@kelanewin-transit.com | +91 22 0000 0000",
            sub_style,
        ),
        Spacer(1, 8),
        Paragraph(
            f"<b>Client:</b> {client}<br/>"
            f"<b>Date:</b> {datetime.now():%d/%m/%Y}<br/>"
            f"<b>Customs Regime:</b> {regime_code}<br/>"
            f"<b>B/L Number:</b> {bl_num or 'Pending'} &nbsp;|&nbsp; "
            f"<b>Container Number:</b> {container_num or 'Pending'}",
            body,
        ),
        Spacer(1, 10),
    ]

    def cell(text: str) -> Paragraph:
        return Paragraph(text, body)

    data = [
        ["Description", "HS Code", "Qty", "Amount (INR)"],
        [cell(article_nom), item_info["sh"], str(quantity), f"{fob_inr:,.2f}"],
        ["Freight & Insurance", "-", "-", f"{freight_inr + insurance_inr:,.2f}"],
        ["CIF Value", "-", "-", f"{cif_inr:,.2f}"],
        [f"Customs Duties & Taxes", "-", "-", f"{total_customs:,.2f}"],
        ["Port Handling, GUCE & Brokerage", "-", "-", f"{total_transit:,.2f}"],
        ["Inland Haulage & Demurrage Buffer", "-", "-", f"{inland_haulage:,.2f}"],
        [cell("<b>TOTAL INVOICE</b>"), "", "", cell(f"<b>{total_invoice:,.2f} ₹</b>")],
        ["Advance Payment", "", "", f"{advance_paid:,.2f} ₹"],
        [cell("<b>BALANCE DUE</b>"), "", "", cell(f"<b>{balance_due:,.2f} ₹</b>")],
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
            "<b>Terms:</b> 50% advance upon order confirmation, balance payable prior to delivery.<br/>"
            f"Certified Amount: <b>{total_invoice:,.2f} INR</b>. Stamp &amp; Signature:",
            body,
        ),
    ])
    doc.build(elems)
    return fname

# ─── ASSISTANT IA GROQ ─────────────────────────────────────────────────────────

def ask_ai(api_key: str, question: str, context: str) -> tuple[str | None, list[str]]:
    if not Groq or not api_key:
        return None, ["Groq library is not installed or API key is missing."]
    client = Groq(api_key=api_key)
    system_prompt = (
        "You are the expert customs, international trade, and port logistics AI assistant for Kelanewin Transit. "
        "You have complete mastery of international tariffs, import compliance, customs regimes, and freight forwarding operations."
    )
    errors: list[str] = []
    for model in ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]:
        try:
            res = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Context: {context}\n\nQuestion: {question}"},
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
        df.to_excel(writer, index=False, sheet_name="Transit_Dossiers")
    return buf.getvalue()

# ─── DESIGN iOS SPRINGBOARD 3D ─────────────────────────────────────────────────

st.set_page_config(
    page_title="Kelanewin Transit — Global Import-Export",
    page_icon="🌐",
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

# ─── ÉCRAN DE VERROUILLAGE / VERIFICATION DE LICENCE ───────────────────────────

if "licensed" not in st.session_state:
    st.session_state.licensed = False
    st.session_state.license_holder = ""
    st.session_state.license_role = ""

if "groq_api_key" not in st.session_state:
    st.session_state.groq_api_key = setting("GROQ_API_KEY", "")

if not st.session_state.licensed:
    st.markdown("<br><br>", unsafe_allow_html=True)
    col_l, col_m, col_r = st.columns([1, 2, 1])
    with col_m:
        st.markdown('<div class="custom-card">', unsafe_allow_html=True)
        st.subheader("🔑 Enterprise License Verification")
        st.caption("Kelanewin Transit SYDAM Pro Ultra — Access Restricted")
        st.markdown("Please enter your official **License Key** provided by the Chief Creator to activate and access the platform.")
        
        entered_key = st.text_input("License Key", type="password", placeholder="Enter key (e.g., MASTER-CREATOR-2026)")
        
        if st.button("Activate License & Enter", use_container_width=True, type="primary"):
            lic = verify_license(entered_key)
            if lic:
                st.session_state.licensed = True
                st.session_state.license_holder = lic["holder_name"]
                st.session_state.license_role = lic["role"]
                add_audit(lic["holder_name"], "license_activation", f"Activated with role: {lic['role']}")
                st.success("License verified successfully! Loading application...")
                st.rerun()
            else:
                st.error("Invalid or expired license key. Please contact the Chief Creator.")
        
        st.markdown("<br>", unsafe_allow_html=True)
        st.info("💡 **Master Creator Key for demonstration:** `MASTER-CREATOR-2026`")
        st.markdown("</div>", unsafe_allow_html=True)
    st.stop()

exchange_rates, api_status = fetch_rates()
is_creator_admin = "Creator" in st.session_state.license_role

# ─── BARRE LATÉRALE ────────────────────────────────────────────────────────────

st.sidebar.title("🌐 KELANEWIN TRANSIT")
st.sidebar.markdown(f"**License Holder:** `{st.session_state.license_holder}`")
st.sidebar.markdown(f"**Access Tier:** `{st.session_state.license_role}`")
st.sidebar.markdown("---")

groq_key_input = st.sidebar.text_input("🔑 Groq API Key", value=st.session_state.groq_api_key, type="password")
if groq_key_input != st.session_state.groq_api_key:
    st.session_state.groq_api_key = groq_key_input

st.sidebar.subheader("💱 Exchange Rates (INR)")
st.sidebar.caption(api_status)
rate_usd = st.sidebar.number_input("1 USD →", value=exchange_rates["USD"], step=1.0, format="%.2f")
rate_cny = st.sidebar.number_input("1 CNY →", value=exchange_rates["CNY"], step=0.5, format="%.2f")
RATE_MAP = {"USD": rate_usd, "CNY": rate_cny, "EUR": 90.0, "AED": 22.7}

st.sidebar.markdown("---")
if st.sidebar.button("🔒 Lock / Revoke Session", use_container_width=True):
    add_audit(st.session_state.license_holder, "session_lock", "User locked session")
    st.session_state.licensed = False
    st.rerun()

# ─── EN-TÊTE & MENU SPRINGBOARD ───────────────────────────────────────────────

st.markdown("""
<div class="header-banner">
  <h1>📦 KELANEWIN TRANSIT · GLOBAL IMPORT-EXPORT</h1>
  <p>Integrated Freight Forwarding, Customs Clearance & Supply Chain Management Platform</p>
</div>
""", unsafe_allow_html=True)

st.markdown('<div class="springboard-container">', unsafe_allow_html=True)
st.markdown("### 📱 Main Application Modules (iOS SpringBoard Grid)")

menu_options = [
    "📈 Dashboard",
    "📄 Quotation & Customs",
    "📦 CBM & Cargo Calculator",
    "💳 Supplier Payments",
    "🚨 Demurrage & Detention",
    "🗺️ Global Tracking",
    "📂 CRM & Dossiers",
    "🇨🇳 Overseas Suppliers",
    "🤖 AI Customs Assistant",
    "📚 HS Code Database",
]

# Seul le créateur obtient le panneau d'administration des licences
if is_creator_admin:
    menu_options.append("👑 Creator License Manager")

cols = st.columns(3)
if "selected_app" not in st.session_state:
    st.session_state.selected_app = "📈 Dashboard"

for idx, option in enumerate(menu_options):
    col_target = cols[idx % 3]
    with col_target:
        if st.button(option, use_container_width=True):
            st.session_state.selected_app = option

st.markdown(f"**Active Module:** `{st.session_state.selected_app}`")
st.markdown('</div>', unsafe_allow_html=True)

selected_tab = st.session_state.selected_app

# ═══════════════════════════════════════════════════════════════════════════════
# ROUTAGE DES MODULES
# ═══════════════════════════════════════════════════════════════════════════════

if selected_tab == "📈 Dashboard":
    st.markdown('<div class="custom-card">', unsafe_allow_html=True)
    st.subheader("📈 Financial & Operational Performance")
    df_d = get_dossiers()
    if df_d.empty:
        st.info("No dossiers recorded yet. Create your first dossier in 'Quotation & Customs'.")
    else:
        tot_ca = df_d["total_facture"].sum()
        tot_solde = df_d["solde_du"].sum()
        nb_dos = len(df_d)
        nb_delivered = int((df_d["statut"] == "Delivered to Client").sum())

        k1, k2, k3, k4 = st.columns(4)
        kpis = [
            ("Total Billings", f"{tot_ca:,.2f} ₹", "#38BDF8"),
            ("Outstanding Receivables", f"{tot_solde:,.2f} ₹", "#F59E0B"),
            ("Total Dossiers", str(nb_dos), "#38BDF8"),
            ("Delivered Shipments", str(nb_delivered), "#10B981"),
        ]
        for col, (title, val, color) in zip([k1, k2, k3, k4], kpis):
            with col:
                st.markdown(
                    f'<div class="kpi-card"><div class="kpi-title">{title}</div>'
                    f'<div class="kpi-value" style="color:{color};">{val}</div></div>',
                    unsafe_allow_html=True,
                )

        if PLOTLY_OK:
            st.markdown("<br/>", unsafe_allow_html=True)
            g1, g2 = st.columns(2)
            with g1:
                fig = px.pie(df_d, names="statut", title="Shipment Status Breakdown", hole=0.4)
                fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", font_color="white")
                st.plotly_chart(fig, use_container_width=True)
            with g2:
                fig2 = px.bar(df_d, x="article", y="total_facture", color="regime", title="Billings by Article & Customs Regime")
                fig2.update_layout(paper_bgcolor="rgba(0,0,0,0)", font_color="white")
                st.plotly_chart(fig2, use_container_width=True)
        else:
            st.dataframe(df_d[["date", "client", "article", "total_facture", "statut"]], use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)

elif selected_tab == "📄 Quotation & Customs":
    df_articles = get_articles()
    st.markdown('<div class="custom-card">', unsafe_allow_html=True)
    st.subheader("📄 Professional Quotation & Customs Calculator")
    
    col_s1, col_s2 = st.columns(2)
    with col_s1:
        client_name = st.text_input("Client / Company Name", "Global Trade Importers Ltd")
        client_email = st.text_input("Client Email", "client@globaltrade.in")
        article_selected = st.selectbox("Article / Commodity", df_articles["nom"].tolist())
        item_row = df_articles[df_articles["nom"] == article_selected].iloc[0]
        regime_selected = st.selectbox("Customs Regime", REGIMES)
        
    with col_s2:
        purchase_currency = st.selectbox("Supplier Invoice Currency", ["USD", "CNY", "EUR", "AED"], index=0)
        invoice_amount = st.number_input("Supplier Invoice Amount (Foreign Currency)", value=50000.0, step=1000.0)
        quantity_items = st.number_input("Quantity of Units", value=100, step=1)
        freight_currency = st.number_input("International Freight (Foreign Currency)", value=3000.0, step=100.0)
        insurance_currency = st.number_input("Marine Insurance (Foreign Currency)", value=500.0, step=50.0)

    current_rate = RATE_MAP.get(purchase_currency, 83.5)
    fob_inr = invoice_amount * current_rate
    freight_inr = freight_currency * current_rate
    insurance_inr = insurance_currency * current_rate
    cif_inr = fob_inr + freight_inr + insurance_inr

    dd_rate = float(item_row["dd"])
    total_customs, customs_details = calculate_customs_duties(cif_inr, dd_rate, regime_selected)

    port_fees = 15000.0
    guce_fees = 4500.0
    brokerage_fees = max(10000.0, fob_inr * 0.03)
    total_transit = port_fees + guce_fees + brokerage_fees

    inland_haulage = 12000.0
    total_invoice = cif_inr + total_customs + total_transit + inland_haulage

    st.markdown("---")
    rc1, rc2, rc3, rc4 = st.columns(4)
    rc1.metric("FOB Value (INR)", f"{fob_inr:,.2f} ₹")
    rc2.metric("CIF Value (INR)", f"{cif_inr:,.2f} ₹")
    rc3.metric("Customs Duties & GST", f"{total_customs:,.2f} ₹")
    rc4.metric("TOTAL INVOICE", f"{total_invoice:,.2f} ₹")

    advance_paid = st.number_input("Advance Payment Received (INR)", value=total_invoice * 0.5, step=10000.0)
    balance_due = total_invoice - advance_paid

    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        if st.button("📄 Generate Proforma PDF", use_container_width=True, type="primary"):
            pdf_path = build_pdf(
                client=client_name, article_nom=article_selected, item_info=item_row,
                regime_code=regime_selected, quantity=quantity_items, fob_inr=fob_inr,
                freight_inr=freight_inr, insurance_inr=insurance_inr, cif_inr=cif_inr,
                total_customs=total_customs, total_transit=total_transit, inland_haulage=inland_haulage,
                total_invoice=total_invoice, advance_paid=advance_paid, balance_due=balance_due
            )
            with open(pdf_path, "rb") as f:
                st.download_button("📥 Download Proforma PDF", f.read(), file_name=pdf_path.name, mime="application/pdf", use_container_width=True)

    with col_btn2:
        if st.button("💾 Save to CRM Dossiers", use_container_width=True):
            add_dossier(
                client=client_name, article=article_selected, regime=regime_selected,
                fob=fob_inr, total=total_invoice, solde=balance_due, statut="In Progress",
                bl="", container="", date_arrivee=(datetime.now() + timedelta(days=25)).strftime("%Y-%m-%d"),
                franchise=14, frais_surest=2500.0, email=client_email, telephone="+91 9800000000",
                devise=purchase_currency, observation=f"Global Import - {quantity_items} units"
            )
            st.success("Dossier successfully saved to CRM!")
    st.markdown("</div>", unsafe_allow_html=True)

elif selected_tab == "📦 CBM & Cargo Calculator":
    st.markdown('<div class="custom-card">', unsafe_allow_html=True)
    st.subheader("📦 CBM Volume & Container Stowage Calculator")
    st.caption("Optimize container loading and LCL/FCL consolidation for global shipments.")
    
    col_c1, col_c2, col_c3 = st.columns(3)
    with col_c1:
        length_cm = st.number_input("Carton Length (cm)", value=50.0, step=1.0)
    with col_c2:
        width_cm = st.number_input("Carton Width (cm)", value=40.0, step=1.0)
    with col_c3:
        height_cm = st.number_input("Carton Height (cm)", value=30.0, step=1.0)
        
    total_cartons = st.number_input("Total Number of Cartons", value=200, step=1)
    
    cbm_unit = (length_cm * width_cm * height_cm) / 1_000_000
    cbm_total = cbm_unit * total_cartons
    
    st.markdown("---")
    m1, m2 = st.columns(2)
    m1.metric("Volume per Carton", f"{cbm_unit:.4f} CBM (m³)")
    m2.metric("Total Cargo Volume", f"{cbm_total:.2f} CBM (m³)")
    
    if cbm_total <= 28:
        st.success("💡 Logistical Recommendation: Your volume fits perfectly into a **20-foot Dry Container (20' Dry)** or LCL Consolidation.")
    elif cbm_total <= 58:
        st.success("💡 Logistical Recommendation: Your volume corresponds to a **40-foot Dry Container (40' Dry)**.")
    else:
        st.warning("⚠️ High Volume Warning: Requires a **40-foot High Cube (40' HC)** container or multiple shipments.")
    st.markdown("</div>", unsafe_allow_html=True)

elif selected_tab == "💳 Supplier Payments":
    st.markdown('<div class="custom-card">', unsafe_allow_html=True)
    st.subheader("💳 Overseas Supplier Payments & Remittances")
    
    df_p = get_paiements()
    with st.form("form_paiement"):
        f_nom = st.text_input("Supplier / Factory Name (e.g., Shenzhen Tech Ltd)")
        montant_dev = st.number_input("Amount in Foreign Currency", value=10000.0, step=500.0)
        dev_choisie = st.selectbox("Currency", ["USD", "CNY", "EUR", "AED"])
        taux_app = st.number_input("Applied Exchange Rate (INR)", value=RATE_MAP.get(dev_choisie, 83.5))
        submit_p = st.form_submit_button("Record Payment")
        
        if submit_p:
            montant_inr = montant_dev * taux_app
            with db_connection() as conn:
                conn.execute(
                    """INSERT INTO paiements_fournisseurs 
                       (date, fournisseur, montant_devise, devise, taux_applique, montant_inr, statut_paiement)
                       VALUES (?,?,?,?,?,?,?)""",
                    (datetime.now().strftime("%Y-%m-%d %H:%M"), f_nom, montant_dev, dev_choisie, taux_app, montant_inr, "Paid")
                )
            st.success(f"Payment of {montant_inr:,.2f} INR recorded successfully!")
            st.rerun()

    st.markdown("### Payment History")
    if not df_p.empty:
        st.dataframe(df_p, use_container_width=True)
    else:
        st.info("No supplier payments recorded yet.")
    st.markdown("</div>", unsafe_allow_html=True)

elif selected_tab == "🚨 Demurrage & Detention":
    st.markdown('<div class="custom-card">', unsafe_allow_html=True)
    st.subheader("🚨 Demurrage & Detention Fee Calculator")
    
    df_d = get_dossiers()
    if df_d.empty:
        st.info("No active dossiers available.")
    else:
        dossier_sel = st.selectbox("Select Dossier / Container", df_d["id"].astype(str) + " - " + df_d["client"] + " (" + df_d["container_number"].fillna("No Container") + ")")
        dos_id = int(dossier_sel.split(" - ")[0])
        row_d = df_d[df_d["id"] == dos_id].iloc[0]
        
        date_arr = st.date_input("Port Arrival Date", value=datetime.strptime(row_d["date_arrivee"], "%Y-%m-%d") if row_d["date_arrivee"] else datetime.now().date())
        franchise = st.number_input("Shipping Line Free Days", value=int(row_d["jours_franchise"] or 14))
        cout_jour = st.number_input("Daily Demurrage Rate (INR)", value=float(row_d["frais_surestarie_jour"] or 2500.0))
        
        days_elapsed = (datetime.now().date() - date_arr).days
        days_overdue = max(0, days_elapsed - franchise)
        demurrage_total = days_overdue * cout_jour
        
        sc1, sc2, sc3 = st.columns(3)
        sc1.metric("Days Elapsed", f"{days_elapsed} days")
        sc2.metric("Overdue Days", f"{days_overdue} days")
        sc3.metric("Estimated Penalties", f"{demurrage_total:,.2f} ₹")
        
        if days_overdue > 0:
            st.markdown(f'<div class="alert-red"><b>Warning:</b> This container has exceeded the free period by {days_overdue} days! Demurrage charges are accumulating.</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="alert-green"><b>Healthy Status:</b> Within shipping line free days. No demurrage fees incurred.</div>', unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

elif selected_tab == "🗺️ Global Tracking":
    st.markdown('<div class="custom-card">', unsafe_allow_html=True)
    st.subheader("🗺️ Maritime Tracking & Port Logistics Pipeline")
    st.caption("Key milestones in international maritime transport and port clearance.")
    
    milestones = [
        ("1. Factory Pickup & Export Origin", "Loading at factory (Ningbo, Shenzhen, Shanghai, Nhava Sheva)", "Completed"),
        ("2. Stuffing & Port Customs", "Export documentation validation & customs sealing", "Completed"),
        ("3. Ocean Freight Transit", "Maritime navigation (Main shipping lanes - approx. 20-30 days)", "In Progress"),
        ("4. Port Arrival & Terminal Discharge", "Vessel unlading and container yard transfer", "Pending"),
        ("5. Customs Inspection & Assessment", "System assessment and duty payment clearance", "Pending"),
        ("6. Delivery Order (DO) & Final Dispatch", "Gate pass issuance and final trucking delivery to client warehouse", "Pending"),
    ]
    
    for title, desc, status in milestones:
        color_badge = "#10B981" if status == "Completed" else ("#38BDF8" if status == "In Progress" else "#64748B")
        st.markdown(f"""
        <div style="background: rgba(30, 41, 59, 0.5); padding: 15px; border-radius: 12px; margin-bottom: 10px; border-left: 4px solid {color_badge};">
            <b>{title}</b> &nbsp;|&nbsp; <span style="color: {color_badge}; font-weight: 700;">{status}</span><br/>
            <small style="color: #94A3B8;">{desc}</small>
        </div>
        """, unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

elif selected_tab == "📂 CRM & Dossiers":
    st.markdown('<div class="custom-card">', unsafe_allow_html=True)
    st.subheader("📂 Transit Dossiers & Client CRM")
    df_d = get_dossiers()
    if not df_d.empty:
        st.dataframe(df_d, use_container_width=True)
        st.markdown("### Export Data")
        st.download_button("📥 Download Excel Report", data=export_excel(df_d), file_name="transit_dossiers.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    else:
        st.info("No dossiers found.")
    st.markdown("</div>", unsafe_allow_html=True)

elif selected_tab == "🇨🇳 Overseas Suppliers":
    st.markdown('<div class="custom-card">', unsafe_allow_html=True)
    st.subheader("🇨🇳 Overseas Suppliers & Factories Directory")
    with st.form("form_fournisseur"):
        nom_us = st.text_input("Factory / Company Name")
        ville_us = st.text_input("City / Province (e.g., Yiwu, Zhejiang)")
        contact_us = st.text_input("WeChat / WhatsApp / Email Contact")
        produits_us = st.text_input("Primary Products")
        if st.form_submit_button("Add Supplier"):
            with db_connection() as conn:
                conn.execute("INSERT INTO fournisseurs_chine (nom_usine, ville, contact, produits) VALUES (?,?,?,?)", 
                             (nom_us, ville_us, contact_us, produits_us))
            st.success("Supplier registered successfully!")
            st.rerun()
    
    df_f = get_fournisseurs()
    if not df_f.empty:
        st.dataframe(df_f, use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)

elif selected_tab == "🤖 AI Customs Assistant":
    st.markdown('<div class="custom-card">', unsafe_allow_html=True)
    st.subheader("🤖 Expert Customs & Logistics AI Assistant (Powered by Groq)")
    user_q = st.text_area("Ask any question regarding customs tariffs, import duties, or logistics procedures:", "What are the applicable customs duties and GST for importing solar panels?")
    if st.button("Query AI Assistant", type="primary"):
        if not st.session_state.groq_api_key:
            st.error("Please enter your Groq API Key in the sidebar.")
        else:
            with st.spinner("Analyzing inquiry..."):
                response, errs = ask_ai(st.session_state.groq_api_key, user_q, "Context: Global import operations, international customs compliance.")
                if response:
                    st.markdown(f"**AI Expert Response:**\n\n{response}")
                else:
                    st.error(f"API Error: {errs}")
    st.markdown("</div>", unsafe_allow_html=True)

elif selected_tab == "📚 HS Code Database":
    st.markdown('<div class="custom-card">', unsafe_allow_html=True)
    st.subheader("📚 Harmonized System (HS) Code & Customs Tariff Reference")
    df_art = get_articles()
    st.dataframe(df_art, use_container_width=True)
    
    with st.expander("➕ Add New Article / HS Code"):
        with st.form("new_art"):
            n_nom = st.text_input("Article Description")
            n_sh = st.text_input("HS Code (e.g., 8517.13.00)")
            n_dd = st.number_input("Customs Duty Rate (%)", value=20.0, step=1.0)
            n_cat = st.text_input("Category")
            if st.form_submit_button("Add to Database"):
                add_article(n_nom, n_sh, n_dd, n_cat)
                st.success("Article added successfully!")
                st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)

elif selected_tab == "👑 Creator License Manager" and is_creator_admin:
    st.markdown('<div class="custom-card">', unsafe_allow_html=True)
    st.subheader("👑 Creator License Manager & System Control")
    st.markdown("En tant que **Créateur**, vous pouvez générer et attribuer des clés de licence uniques pour donner accès à votre application.")
    
    tab_l, tab_a = st.tabs(["Manage Active Licenses", "System Audit Logs"])
    with tab_l:
        st.markdown("### Issued Enterprise Licenses")
        st.dataframe(get_licenses(), use_container_width=True)
        
        with st.form("new_license_form"):
            st.markdown("### Generate New License Key")
            holder_input = st.text_input("Holder / Collaborator Name (e.g., John Doe - Senior Broker)")
            role_input = st.selectbox("Access Role", ["Standard Collaborator", "Senior Customs Broker", "Financial Auditor", "External Partner"])
            raw_key_input = st.text_input("Custom License Passcode / Secret Key (e.g., CLIENT-KEY-999)", type="password")
            
            if st.form_submit_button("Generate & Issue License"):
                if raw_key_input:
                    try:
                        generate_license(holder_input, role_input, raw_key_input)
                        st.success(f"License successfully generated and issued for **{holder_input}**!")
                        add_audit(st.session_state.license_holder, "generate_license", f"Issued license to {holder_input}")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error (Key might already exist): {e}")
                else:
                    st.warning("Please provide a valid license key string.")
                    
    with tab_a:
        st.markdown("### System Activity Audit Logs")
        df_logs = get_audit_logs()
        if not df_logs.empty:
            st.dataframe(df_logs, use_container_width=True)
        else:
            st.info("No audit logs available.")
    st.markdown("</div>", unsafe_allow_html=True)
