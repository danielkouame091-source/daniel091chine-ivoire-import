# SNDGIR & Transit ERP

Plateforme SaaS **multi-tenant** d'ERP comptable, transit douanier et fiscalité pour
les cabinets d'expertise comptable, directions financières, PME/SARL/SA et
institutions financières de **Côte d'Ivoire** et de la zone **UEMOA**.

Conçue en concurrence directe ou en intégration avec les écosystèmes de type
**Sage** et les solutions bancaires ivoiriennes (SGBCI, Ecobank…).

---

## 🚀 Démarrage rapide

```bash
# 1. Dépendances (Streamlit, pandas, reportlab, groq)
pip install -r requirements.txt

# 2. Lancer l'application (base SQLite auto-créée et peuplée au 1er démarrage)
streamlit run sndgir_erp.py

# 3. Valider le cœur métier (52 contrôles, sans Streamlit)
python3 valider_sndgir.py
```

### Comptes de démonstration (tenant `Cabinet Excellence Comptable CI`)

| Identifiant | Mot de passe | Rôle |
|---|---|---|
| `admin` | `admin123` | Administrateur Système |
| `expert` | `expert123` | Expert-Comptable signataire |
| `collab` | `collab123` | Collaborateur |
| `auditeur` | `audit123` | Auditeur externe |

> ⚠️ **Changez ces mots de passe avant tout déploiement en production.**

---

## 🧩 Périmètre fonctionnel

Le cœur applicatif tient dans un **bloc Python unique et exécutable** :
`sndgir_erp.py`.

### 1. Multi-tenant & sécurité de niveau bancaire (RegTech)
- Isolation stricte des données par entreprise cliente : **chaque requête métier
  est filtrée par `tenant_id`**.
- **5 rôles granulaires** avec permissions `<module>.<action>` :
  Administrateur Système, Expert-Comptable signataire, Collaborateur,
  Auditeur externe, Client final.
- **Piste d'audit immuable** : chaîne de hachage append-only. Chaque entrée
  embarque l'empreinte de la précédente ; toute modification ou suppression
  rétroactive est **détectée** par `verifier_audit()`.
- **Chiffrement authentifié** des données sensibles (nonce + flux HMAC-SHA256 +
  étiquette d'intégrité, encodage base64).
- **Hachage des mots de passe** : Argon2 en priorité, repli PBKDF2-HMAC-SHA256
  (200 000 itérations).
- **Masquage automatique des secrets** (clés API, tokens) avant journalisation.
- **Empreintes SHA-256** pour sceller les documents officiels.

### 2. Moteur comptable SYSCOHADA révisé (standards Sage)
- **Partie double stricte** : une écriture déséquilibrée ou portant un compte
  hors plan comptable est **refusée** (`ErreurComptable`).
- **Journaux auxiliaires et centraux** : Achats `ACQ`, Ventes `VTE`,
  Banque/Trésorerie `BAN`, Opérations Diverses `OD`.
- **Automatisation native des flux** — chaque opération génère ses écritures
  croisées :
  - `ecritures_frais_transit()` → débours douaniers (hors taxes), fret,
    surestaries, honoraires soumis à TVA ;
  - `ecritures_depuis_debours()` → droits et taxes (État 447100 / banque 521000) ;
  - `ecritures_surestaries()` → charge 628000 / banque ;
  - `ecritures_quittance_caisse()` → encaissement caisse 571000 / client 411000 ;
  - `ecritures_achat_import()` → entrée en stock 311000 + droits.
- **États en temps réel** : Balance Générale, Grand Livre, Journaux,
  Compte de résultat et Bilan synthétique (SYSCOHADA).

### 3. Transit, import-export & douanes (contexte ivoirien)
- **Manifestes** maritimes/aériens et **apurement des connaissements (B/L)**,
  unitaire ou automatique à l'échelle du manifeste.
- **Calcul des droits** par régime — `C100` (mise à la consommation),
  `E100` (exportation), `AT` (admission temporaire), `TR` (transit) :
  - droits de douane (DD) ;
  - **Prélèvement Communautaire UEMOA** (0,8 %) ;
  - **Prélèvement Communautaire CEDEAO** (0,5 %) ;
  - **TVA 18 %** assise sur (CAF + DD + PC + PCC).
- **Moteur hybride de sélectivité des risques** (canaux **Vert / Bleu / Jaune /
  Rouge**) par scoring pondéré : écart de taux déclaré, sous-évaluation,
  montant CAF, ancienneté du fournisseur, sensibilité de la marchandise.
- **Surestaries portuaires** : franchise armateur, jours de retard, pénalité
  journalière en **USD convertie en FCFA** au taux en direct
  (`actualiser_taux_api()` avec repli sur le dernier taux connu).
- **Documents officiels PDF** :
  - **Bon à Enlever (BAE)** scellé par empreinte **SHA-256** ;
  - **Facture transitaire** détaillée distinguant les débours douaniers
    (refacturés hors taxes), le fret, le transport et les honoraires soumis à TVA.

### 4. Intelligence artificielle & OCR (IDP)
- **Assistant expert** fiscalité / droit douanier ivoirien connecté à l'API
  **Groq** (modèle par défaut : `llama-3.1-8b-instant`), avec repli explicite
  si la clé ou la librairie sont absentes.
- **Extraction OCR/IDP** de factures fournisseurs (fournisseur, n° de facture,
  date, montants, désignation) — fonctionne hors-ligne, une sortie OCR externe
  peut alimenter la même interface.
- **Cross-checking automatique** : détection des discordances déclaré/extrait et
  de la **sous-évaluation douanière** par comparaison au prix de référence.
- **Générateur de communications** (relances, demandes de pièces, courriers
  administratifs) avec **validation humaine obligatoire** avant toute diffusion.

### 5. Expérience utilisateur & interopérabilité
- **Dark mode** épuré (glassmorphism, palette iOS), KPI financiers dynamiques,
  **graphiques Plotly interactifs** avec **repli automatique** sur `st.bar_chart`
  si Plotly est absent.
- **Robustesse** : dépendances optionnelles (`plotly`, `groq`, `requests`,
  `reportlab`, `passlib`) protégées par `try/except` — aucune ImportError ne
  bloque l'application.
- **Initialisation automatique** de la base au premier lancement avec un jeu de
  données professionnel cohérent (plan comptable, journaux, tenant, utilisateurs,
  articles SH, dossiers).

---

## 🗂️ Architecture

```
sndgir_erp.py        Application complète (bloc unique exécutable, ~2 440 lignes)
valider_sndgir.py    Harnais de validation fonctionnelle (52 contrôles)
requirements.txt     Dépendances Python
sndgir_erp.db        Base SQLite (créée automatiquement, ignorée par Git)
```

Déploiement : `Dockerfile`, `docker-compose*.yml`, `Caddyfile`, `fly.toml`,
`railway.json`. Le point d'entrée FastAPI (`app/main.py`) peut être porté vers
PostgreSQL ; le moteur métier de `sndgir_erp.py` est transposable via SQLAlchemy.

---

## ⚖️ Mentions & limites (honnêteté)

- Les **taux par défaut** (TVA 18 %, IS/BIC 25 %, PC UEMOA 0,8 %, PCC CEDEAO
  0,5 %) reflètent le régime général le plus courant en Côte d'Ivoire mais sont
  **modifiables** à chaque calcul.
- Les **régimes E100 / AT / TR** sont modélisés par exonération des droits ;
  les cas particuliers (contingents, suspensions, destinations privilégiées)
  doivent être affinés selon le tarif douanier en vigueur.
- Cet outil **ne remplace pas** la validation d'un **expert-comptable agréé** ni
  d'un **commissionnaire en douane agréé** avant toute déclaration officielle
  auprès de la DGI ou des Douanes ivoiriennes.
- Le chiffrement embarqué est une construction portable (HMAC-SHA256 + MAC).
  Pour une production bancaire, remplacez-la par **AES-256-GCM**
  (`cryptography`).

---

## ✅ État de validation

```
52 validations · 0 échec
Sécurité ✓  Audit immuable ✓  Partie double ✓  Douanes ✓  Surestaries ✓
OCR/IDP ✓  Transit & B/L ✓  Multi-tenant & RBAC ✓  PDF scellés ✓
```


import io
import os
import re
import sqlite3
from datetime import datetime
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
    from groq import Groq
except ImportError:  # pragma: no cover
    Groq = None

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


def setting(name: str, default: str = "") -> str:
    try:
        value = st.secrets.get(name, default)
        if value not in (None, ""):
            return str(value)
    except Exception:
        pass
    return os.getenv(name, default)


def db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with db_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nom TEXT UNIQUE NOT NULL,
                sh TEXT NOT NULL,
                dd REAL NOT NULL,
                categorie TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dossiers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                client TEXT NOT NULL,
                article TEXT NOT NULL,
                fob_xof REAL NOT NULL,
                total_facture REAL NOT NULL,
                solde_du REAL NOT NULL,
                statut TEXT NOT NULL,
                document_path TEXT,
                email TEXT,
                telephone TEXT,
                devise TEXT,
                observation TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                utilisateur TEXT NOT NULL,
                action TEXT NOT NULL,
                details TEXT
            )
            """
        )
        count = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
        if not count:
            conn.executemany(
                "INSERT OR IGNORE INTO articles (nom, sh, dd, categorie) VALUES (?, ?, ?, ?)",
                [
                    ("Station Totale Topographique & GNSS/GPS", "9015.80.00", 5.0, "Topographie"),
                    ("Théodolites, Niveaux Optiques & Laser", "9015.10.00", 5.0, "Topographie"),
                    ("Smartphones, iPhones & Téléphones portables", "8517.13.00", 20.0, "High-Tech"),
                    ("Ordinateurs Portables, MacBooks & Tablettes", "8471.30.00", 5.0, "Informatique"),
                    ("Panneaux Photovoltaïques / Solaires", "8541.43.00", 5.0, "Énergie"),
                    ("Groupes Électrogènes (Générateurs)", "8502.11.00", 5.0, "Machines"),
                ],
            )


init_db()


def add_audit(user: str, action: str, details: str = ""):
    with db_connection() as conn:
        conn.execute(
            "INSERT INTO audit_logs (created_at, utilisateur, action, details) VALUES (?, ?, ?, ?)",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), user, action, details),
        )


def read_table(query: str, params=()):
    with db_connection() as conn:
        return pd.read_sql_query(query, conn, params=params)


def get_articles():
    return read_table("SELECT * FROM articles ORDER BY nom ASC")


def get_dossiers():
    return read_table("SELECT * FROM dossiers ORDER BY id DESC")


def add_dossier(client, article, fob, total, balance, email, phone, devise, document_path="", observation=""):
    with db_connection() as conn:
        conn.execute(
            "INSERT INTO dossiers (date, client, article, fob_xof, total_facture, solde_du, statut, document_path, email, telephone, devise, observation) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                datetime.now().strftime("%Y-%m-%d %H:%M"),
                client,
                article,
                fob,
                total,
                balance,
                "En cours",
                document_path,
                email,
                phone,
                devise,
                observation,
            ),
        )


def update_status(case_id, new_status):
    with db_connection() as conn:
        conn.execute("UPDATE dossiers SET statut = ? WHERE id = ?", (new_status, case_id))


def safe_filename(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._") or "document"


def fetch_rates() -> tuple[float, float, str]:
    try:
        response = requests.get("https://open.er-api.com/v6/latest/USD", timeout=5)
        if response.status_code == 200:
            data = response.json().get("rates", {})
            usd_xof = float(data.get("XOF", 610.0))
            usd_cny = float(data.get("CNY", 7.2))
            cny_xof = usd_xof / usd_cny if usd_cny else 82.0
            return round(cny_xof, 2), round(usd_xof, 2), "🟢 Taux direct API"
    except Exception:
        pass
    return 82.0, 610.0, "⚠️ Mode secours"


def build_pdf(client, article, info, qty, fob, freight, insurance, caf, customs, transit, inland, total, deposit, balance):
    path = BASE_DIR / f"Devis_Pro_{safe_filename(client)}.pdf"
    doc = SimpleDocTemplate(str(path), pagesize=letter, rightMargin=35, leftMargin=35, topMargin=35, bottomMargin=35)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("title", parent=styles["Heading1"], fontSize=16, textColor=colors.HexColor("#047857"), alignment=1)
    elements = [
        Paragraph("<b>KELANEWIN TRANSIT S.A. (SYDAM PRO CI)</b>", title_style),
        Paragraph("Agrément Douane N° 2026/CI-ABJ | Abidjan Port & San-Pédro\nContact : contact@kelanewin-transit.ci", styles["Normal"]),
        Spacer(1, 12),
        Paragraph(f"<b>Client :</b> {client}<br/><b>Date :</b> {datetime.now():%d/%m/%Y}<br/><b>Objet :</b> Facture Proforma & Cotation Logistique", styles["Normal"]),
    ]
    data = [
        ["Désignation", "Code SH", "Qté", "Montant FCFA"],
        [article, info["sh"], str(qty), f"{fob:,.0f}"],
        ["Fret & assurance", "-", "-", f"{freight + insurance:,.0f}"],
        ["Valeur CAF", "-", "-", f"{caf:,.0f}"],
        ["Droits & taxes", "-", "-", f"{customs:,.0f}"],
        ["Transit", "-", "-", f"{transit:,.0f}"],
        ["Post-acheminement", "-", "-", f"{inland:,.0f}"],
        ["<b>TOTAL</b>", "", "", f"<b>{total:,.0f} FCFA</b>"],
        ["Acompte", "", "", f"{deposit:,.0f} FCFA"],
        ["<b>SOLDE</b>", "", "", f"<b>{balance:,.0f} FCFA</b>"],
    ]
    table = Table(data, colWidths=[230, 80, 45, 145])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F172A")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#F8FAFC")),
                ("BACKGROUND", (0, 7), (-1, 7), colors.HexColor("#E2E8F0")),
                ("BACKGROUND", (0, 9), (-1, 9), colors.HexColor("#DCFCE7")),
            ]
        )
    )
    elements.extend([table, Spacer(1, 18), Paragraph("Conditions : 50% à la commande, solde avant BAE.", styles["Normal"])])
    doc.build(elements)
    return path


def export_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Dossiers")
    return output.getvalue()


def ask_ai(api_key: str, question: str, context: str):
    if not Groq or not api_key:
        return None, ["Bibliothèque Groq absente ou clé API absente."]
    client = Groq(api_key=api_key)
    system_prompt = (
        "Tu es l'assistant expert de Kelanewin Transit en Côte d'Ivoire. Réponds en français, "
        "de façon concrète, précise et opérationnelle. S'il manque des infos, dis-le clairement et propose une vérification."
    )
    errors = []
    for model_name in [setting("GROQ_MODEL", "llama-3.3-70b-versatile"), "llama-3.1-8b-instant", "mixtral-8x7b-32768"]:
        try:
            res = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Contexte métier: {context}\n\nQuestion: {question}"},
                ],
                temperature=0.2,
                max_tokens=1200,
            )
            return res.choices[0].message.content, []
        except Exception as exc:  # pragma: no cover
            errors.append(f"{model_name}: {exc}")
    return None, errors


st.set_page_config(page_title="Kelanewin Transit - Pro", page_icon="🇨🇮", layout="wide")

st.markdown(
    """
    <style>
      .app-shell { background: #0b1220; color: #e2e8f0; }
      .header { background: linear-gradient(135deg, #047857, #0284c7); color: white; padding: 24px 28px; border-radius: 18px; margin-bottom: 20px; }
      .header h1 { margin: 0; font-size: 2.1rem; }
      .kpi { padding: 16px; border: 1px solid #334155; border-radius: 14px; background: #111827; }
      .kpi small { color: #94a3b8; }
      .kpi h3 { margin: 8px 0 0; font-size: 1.5rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
    st.session_state.username = ""
    st.session_state.user_role = ""

users = {
    "admin": (setting("APP_ADMIN_PASSWORD", "transit2026"), "Administrateur"),
    "commercial": (setting("APP_COMMERCIAL_PASSWORD", "compta2026"), "Commercial / Déclarant"),
    "comptable": (setting("APP_COMPTABLE_PASSWORD", "finance2026"), "Comptable / Trésorerie"),
}

if not st.session_state.authenticated:
    st.markdown("<div class='header'><h1>🔐 Accès sécurisé</h1><p>Entreprise - Kelanewin Transit</p></div>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        user = st.text_input("Identifiant")
        password = st.text_input("Mot de passe", type="password")
        if st.button("Se connecter", type="primary", use_container_width=True):
            if user in users and password == users[user][0]:
                st.session_state.authenticated = True
                st.session_state.username = user
                st.session_state.user_role = users[user][1]
                add_audit(user, "login", "connexion réussie")
                st.rerun()
            else:
                st.error("Identifiants invalides.")
    st.stop()

cny_rate, usd_rate, rate_status = fetch_rates()

st.sidebar.title("🇨🇮 KELANEWIN TRANSIT")
st.sidebar.caption(f"{st.session_state.username} · {st.session_state.user_role}")
api_key = setting("GROQ_API_KEY", "") or st.sidebar.text_input("Clé Groq", type="password")

st.sidebar.subheader("💱 Taux de change")
st.sidebar.caption(rate_status)
cny_rate = st.sidebar.number_input("1 CNY → FCFA", value=cny_rate, step=0.1)
usd_rate = st.sidebar.number_input("1 USD → FCFA", value=usd_rate, step=1.0)

st.sidebar.subheader("⚙️ SMTP")
mail_server = setting("SMTP_SERVER", "smtp.gmail.com") or st.sidebar.text_input("Serveur SMTP", value="smtp.gmail.com")
mail_port = int(setting("SMTP_PORT", "587") or st.sidebar.number_input("Port SMTP", value=587))
mail_sender = setting("SMTP_USERNAME", "") or st.sidebar.text_input("Expéditeur", value="")
mail_password = setting("SMTP_PASSWORD", "") or st.sidebar.text_input("Mot de passe app", type="password")

if st.sidebar.button("🚪 Déconnexion"):
    add_audit(st.session_state.username, "logout", "déconnexion")
    st.session_state.authenticated = False
    st.rerun()

articles_df = get_articles()
dossiers_df = get_dossiers()

st.markdown("<div class='header'><h1>📦 KELANEWIN TRANSIT · PRO</h1><p>Gestion douanière, cotation, audit et suivi CRM</p></div>", unsafe_allow_html=True)

tab_quote, tab_crm, tab_ai, tab_tarif = st.tabs(["📊 Cotation pro", "📂 CRM & exports", "🤖 Assistant IA", "📚 SH / Tarif"])

with tab_quote:
    left, right = st.columns([2, 1])
    with left:
        c1, c2, c3 = st.columns(3)
        with c1: client_name = st.text_input("Client", value="ETS KOUASSI & FRERES")
        with c2: client_email = st.text_input("Email", value="client@example.com")
        with c3: client_phone = st.text_input("Téléphone", value="+2250700000000")

        upload = st.file_uploader("Pièce justificative", type=["pdf", "png", "jpg", "jpeg"])
        uploaded_path = ""
        if upload is not None:
            uploaded_path = str(UPLOAD_DIR / f"{datetime.now():%Y%m%d%H%M%S}_{safe_filename(upload.name)}")
            Path(uploaded_path).write_bytes(upload.getbuffer())
            st.success("Pièce enregistrée.")

        if articles_df.empty:
            st.warning("Ajoutez d'abord un article dans l’onglet Tarif SH.")
        else:
            article_name = st.selectbox("Article", articles_df["nom"].tolist())
            row = articles_df.loc[articles_df["nom"] == article_name].iloc[0]
            info = {"sh": row["sh"], "dd": float(row["dd"]), "cat": row["categorie"]}
            currency = st.selectbox("Devise fournisseur", ["CNY", "USD"])
            q1, q2, q3 = st.columns(3)
            with q1: qty = st.number_input("Quantité", min_value=1, value=50)
            with q2: unit_price = st.number_input("Prix unitaire", min_value=0.01, value=300.0)
            with q3: freight_input = st.number_input("Fret total", min_value=0.0, value=1500.0)

            p1, p2, p3 = st.columns(3)
            with p1: port = st.number_input("Port / aéroport", min_value=0, value=150000, step=5000)
            with p2: fees = st.number_input("GUCE + honoraires", min_value=0, value=285000, step=5000)
            with p3: inland = st.number_input("Transport + surestaries", min_value=0, value=195000, step=5000)
            deposit = st.number_input("Acompte reçu", min_value=0, value=1000000, step=50000)
            observation = st.text_area("Observation / notes", value="")

            rate = cny_rate if currency == "CNY" else usd_rate
            fob = qty * unit_price * rate
            freight = freight_input * rate
            insurance = max((fob + freight) * 0.005, 5000.0)
            caf = fob + freight + insurance
            customs = caf * (info["dd"] / 100 + 0.033) * 1.18
            transit = port + fees
            total = fob + freight + insurance + customs + transit + inland
            solde = total - deposit

            m1, m2, m3, m4 = st.columns(4)
            for col, label, value in zip([m1, m2, m3, m4], ["CAF", "Douane", "Total", "Solde"], [caf, customs, total, solde]):
                with col:
                    st.markdown(f"<div class='kpi'><small>{label}</small><h3>{value:,.0f} FCFA</h3></div>", unsafe_allow_html=True)

            if st.button("💾 Enregistrer le dossier", type="primary"):
                add_dossier(client_name, article_name, fob, total, solde, client_email, client_phone, currency, uploaded_path, observation)
                add_audit(st.session_state.username, "dossier_cree", f"client={client_name}; article={article_name}; total={total:,.0f}")
                st.success("Dossier enregistré avec succès.")

            pdf_path = build_pdf(client_name, article_name, info, qty, fob, freight, insurance, caf, customs, transit, inland, total, deposit, solde)
            with open(pdf_path, "rb") as file:
                pdf_bytes = file.read()
            st.download_button("📥 Télécharger le devis PDF", pdf_bytes, file_name=pdf_path.name, mime="application/pdf")

            msg = f"Bonjour {client_name}, votre cotation est estimée à {total:,.0f} FCFA, solde restant {solde:,.0f} FCFA." 
            st.link_button("💬 WhatsApp", f"https://wa.me/{client_phone.replace('+', '')}?text={quote(msg)}")

    with right:
        st.subheader("🧠 Aide décisionnelle")
        st.markdown(
            """
            - Vérifier le code SH et le DD.<br>
            - Contrôler le montant FOB et le taux de conversion.<br>
            - S'assurer de la conformité GUCE / FDI.<br>
            - Valider l'acompte et le solde avant BAE.
            """,
            unsafe_allow_html=True,
        )
        st.info("Le rôle actuel : %s" % st.session_state.user_role)

with tab_crm:
    st.subheader("📂 CRM & exports premium")
    if dossiers_df.empty:
        st.info("Aucun dossier enregistré.")
    else:
        query = st.text_input("Recherche client / article / statut")
        status_filter = st.multiselect("Statuts", STATUTS, default=STATUTS)
        filtered = dossiers_df.copy()
        if query:
            q = query.lower()
            filtered = filtered[filtered.apply(lambda row: q in str(row["client"]).lower() or q in str(row["article"]).lower() or q in str(row["statut"]).lower(), axis=1)]
        if status_filter:
            filtered = filtered[filtered["statut"].isin(status_filter)]

        cards = st.columns(4)
        with cards[0]: st.markdown(f"<div class='kpi'><small>Dossiers</small><h3>{len(filtered)}</h3></div>", unsafe_allow_html=True)
        with cards[1]: st.markdown(f"<div class='kpi'><small>Montant</small><h3>{filtered['total_facture'].sum():,.0f} FCFA</h3></div>", unsafe_allow_html=True)
        with cards[2]: st.markdown(f"<div class='kpi'><small>Soldes</small><h3>{filtered['solde_du'].sum():,.0f} FCFA</h3></div>", unsafe_allow_html=True)
        with cards[3]: st.markdown(f"<div class='kpi'><small>Livrés</small><h3>{(filtered['statut'] == 'Livré au Client').sum()}</h3></div>", unsafe_allow_html=True)

        st.dataframe(filtered[["id", "date", "client", "article", "total_facture", "solde_du", "statut"]], use_container_width=True)

        cexport1, cexport2 = st.columns(2)
        with cexport1:
            st.download_button("📗 Export Excel", export_excel(filtered), "dossiers_export.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        with cexport2:
            st.download_button("📄 Export CSV", filtered.to_csv(index=False).encode("utf-8-sig"), "dossiers_export.csv", "text/csv")

        case_id = st.selectbox("Mise à jour d'un dossier", filtered["id"].tolist())
        new_status = st.selectbox("Nouveau statut", STATUTS)
        if st.button("Mettre à jour le statut"):
            update_status(case_id, new_status)
            add_audit(st.session_state.username, "statut_update", f"dossier={case_id}; statut={new_status}")
            st.success("Statut mis à jour.")
            st.rerun()

with tab_ai:
    st.subheader("🤖 Assistant IA douanier")
    question = st.text_area("Votre question", placeholder="Quel document préparer pour une importation en provenance de Chine ?")
    if st.button("🔍 Répondre", type="primary"):
        if not question.strip():
            st.warning("Saisissez une question.")
        else:
            context = f"Dossiers enregistrés: {len(dossiers_df)}; Articles: {len(articles_df)}; Types de statuts: {', '.join(STATUTS)}"
            with st.spinner("Analyse en cours..."):
                answer, errors = ask_ai(api_key, question, context)
            if answer:
                st.markdown(answer)
            else:
                st.error("Impossible d'obtenir une réponse IA.")
                with st.expander("Détails techniques"):
                    st.code("\n".join(errors) if errors else "Aucune erreur")

with tab_tarif:
    st.subheader("📚 Base tarifaire SH")
    if st.session_state.user_role in ["Administrateur", "Commercial / Déclarant"]:
        with st.form("article_form"):
            n_nom = st.text_input("Désignation")
            n_sh = st.text_input("Code SH")
            n_dd = st.number_input("DD (%)", min_value=0.0, max_value=100.0, value=20.0)
            n_cat = st.text_input("Catégorie")
            submit = st.form_submit_button("Ajouter")
            if submit and n_nom and n_sh:
                with db_connection() as conn:
                    try:
                        conn.execute("INSERT INTO articles (nom, sh, dd, categorie) VALUES (?, ?, ?, ?)", (n_nom.strip(), n_sh.strip(), n_dd, n_cat.strip() or "Autre"))
                        add_audit(st.session_state.username, "article_ajoute", f"article={n_nom}; sh={n_sh}")
                        st.success("Article ajouté.")
                        st.rerun()
                    except sqlite3.IntegrityError:
                        st.error("Cet article existe déjà.")
    else:
        st.info("Votre rôle ne vous permet pas d’ajouter une ligne dans la base tarifaire.")

    st.dataframe(get_articles(), use_container_width=True)

# trace de consultation
add_audit(st.session_state.username, "session_open", f"page_opened")
