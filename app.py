import hashlib
import sqlite3
from datetime import datetime, timedelta

import pandas as pd
import plotly.express as px
import requests
import streamlit as st

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

try:
    from groq import Groq
except ImportError:
    Groq = None

# Modules internes (à placer dans le même dossier que app.py)
from rbac import require_permission
import comptabilite_syscohada as compta
import fiscalite as fiscal
import securite_bancaire as sec

st.set_page_config(page_title="SNDGIR - Transit & Douanes Côte d'Ivoire", page_icon="🇨🇮", layout="wide")

st.markdown("""
<style>
.stApp { background-color: #060911; color: #F8FAFC; font-family: 'Inter', system-ui, -apple-system, sans-serif; }
.header-banner { background: linear-gradient(135deg, #064E3B 0%, #047857 40%, #0284C7 100%); padding: 25px 30px; border-radius: 20px; color: white; margin-bottom: 25px; box-shadow: 0 20px 25px -5px rgba(0,0,0,0.7), 0 8px 10px -6px rgba(0,0,0,0.5); border: 1px solid rgba(255,255,255,0.2); }
.custom-card-3d { background: #0F172A; border-radius: 18px; padding: 22px; border: 1px solid #1E293B; margin-bottom: 22px; box-shadow: 6px 6px 18px #03060D, -6px -6px 18px #1B2437; }
.kpi-card { background: linear-gradient(145deg, #1e293b, #0f172a); border-radius: 14px; padding: 16px; border: 1px solid #334155; box-shadow: inset 1px 1px 2px rgba(255,255,255,0.08), 0 10px 15px -3px rgba(0,0,0,0.4); text-align: center; }
.kpi-title { font-size: 0.8rem; color: #9CA3AF; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 4px; }
.kpi-value { font-size: 1.4rem; font-weight: 700; color: #38BDF8; }
.canal-vert { background-color: #064E3B; color: #34D399; padding: 6px 12px; border-radius: 8px; font-weight: bold; }
.canal-bleu { background-color: #1E3A8A; color: #60A5FA; padding: 6px 12px; border-radius: 8px; font-weight: bold; }
.canal-jaune { background-color: #78350F; color: #FBBF24; padding: 6px 12px; border-radius: 8px; font-weight: bold; }
.canal-rouge { background-color: #7F1D1D; color: #F87171; padding: 6px 12px; border-radius: 8px; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

DB_NAME = "sndgir_national_customs.db"


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password_hash TEXT, role TEXT, statut TEXT DEFAULT 'Actif')""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS manifestes (id INTEGER PRIMARY KEY AUTOINCREMENT, num_manifeste TEXT UNIQUE, moyen_transport TEXT, num_voyage TEXT, provenance TEXT, date_arrivee TEXT, statut TEXT DEFAULT 'Enregistré')""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS fret_lines (id INTEGER PRIMARY KEY AUTOINCREMENT, num_manifeste TEXT, bl_number TEXT UNIQUE, consignee TEXT, poids_brut REAL, nb_colis INTEGER, statut_apurement TEXT DEFAULT 'Non apuré')""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS articles (id INTEGER PRIMARY KEY AUTOINCREMENT, nom TEXT UNIQUE, sh TEXT, dd REAL, categorie TEXT)""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS dossiers (id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, client TEXT, article TEXT, regime TEXT, fob_xof REAL, total_facture REAL, solde_du REAL, statut TEXT, bl_number TEXT, container_number TEXT, date_arrivee TEXT, score_risque REAL, canal_selectivite TEXT, motifs_risque TEXT, quittance_num TEXT, document_path TEXT, honoraires REAL DEFAULT 150000, frais_port REAL DEFAULT 85000, frais_transport REAL DEFAULT 120000, surestaries_xof REAL DEFAULT 0, statut_livraison TEXT DEFAULT 'Sous douane')""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS audit_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, username TEXT, action TEXT, details TEXT)""")
    for u in [
        ("admin", hash_password("transit2026"), "Administrateur Système", "Actif"),
        ("verificateur", hash_password("douane2026"), "Vérificateur Douanier", "Actif"),
        ("caissier", hash_password("caisse2026"), "Agent de Caisse", "Actif"),
        ("declarant", hash_password("compta2026"), "Commissionnaire Agréé", "Actif"),
    ]:
        cursor.execute("INSERT OR IGNORE INTO users (username, password_hash, role, statut) VALUES (?, ?, ?, ?)", u)
    for item in [
        ("Station Totale Topographique & GNSS/GPS", "9015.80.00", 5.0, "Topographie"),
        ("Smartphones & Téléphones portables", "8517.13.00", 20.0, "High-Tech"),
        ("Ordinateurs Portables & MacBooks", "8471.30.00", 5.0, "Informatique"),
        ("Vélos et Bicyclettes sans moteur", "8712.00.00", 20.0, "Transport"),
        ("Motos & Motocycles (125cc - 250cc)", "8711.20.00", 20.0, "Transport"),
        ("Voitures de Tourisme (Berlines / SUV)", "8703.22.00", 20.0, "Véhicules"),
        ("Vêtements Homme / Femme / Enfant", "6203.00.00", 20.0, "Textile"),
        ("Sacs à main pour Dames", "4202.22.00", 20.0, "Maroquinerie"),
    ]:
        cursor.execute("INSERT OR IGNORE INTO articles (nom, sh, dd, categorie) VALUES (?, ?, ?, ?)", item)
    conn.commit()
    conn.close()


init_db()
compta.init_compta_tables(DB_NAME)
sec.init_mfa_table(DB_NAME)
sec.init_audit_chain_table(DB_NAME)


def log_action(username, action, details):
    """Journal classique (lisible, non chaîné) — conservé pour compat."""
    conn = sqlite3.connect(DB_NAME)
    conn.execute("INSERT INTO audit_logs (timestamp, username, action, details) VALUES (?, ?, ?, ?)",
                 (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), username, action, details))
    conn.commit()
    conn.close()


def log_action_complet(username, action, details):
    """À utiliser pour tout événement à valeur probante (paiement, connexion, SAD)."""
    log_action(username, action, details)
    sec.log_action_immuable(DB_NAME, username, action, details)


def calculer_selectivite_risque(fob_xof, item_info, diff_ocr_pct, client_nom):
    score = 10.0
    motifs = []
    if fob_xof > 50000000:
        score += 30; motifs.append("Valeur FOB supérieure à 50M FCFA")
    elif fob_xof > 10000000:
        score += 15; motifs.append("Valeur FOB supérieure à 10M FCFA")
    if diff_ocr_pct > 15.0:
        score += 40; motifs.append(f"Divergence majeure OCR Facture ({diff_ocr_pct:.1f}%)")
    elif diff_ocr_pct > 5.0:
        score += 20; motifs.append(f"Écart mineur OCR Facture ({diff_ocr_pct:.1f}%)")
    if item_info.get("cat") in ["High-Tech", "Véhicules"]:
        score += 15; motifs.append(f"Catégorie sous surveillance ({item_info.get('cat')})")
    canal = "VERT" if score < 25 else ("BLEU" if score < 45 else ("JAUNE" if score < 70 else "ROUGE"))
    return round(score, 1), canal, " | ".join(motifs) if motifs else "Déclaration conforme"


def calculer_surestaries(date_dechargement_str, jours_franchise, frais_jour_usd, taux_usd):
    try:
        date_limite = datetime.strptime(date_dechargement_str, "%Y-%m-%d") + timedelta(days=int(jours_franchise))
        jours_depasses = (datetime.now() - date_limite).days
        if jours_depasses > 0:
            cout_usd = jours_depasses * frais_jour_usd
            return jours_depasses, cout_usd, cout_usd * taux_usd, f"🔴 PÉNALITÉ DE SURESTARIES ({jours_depasses} j. de dépassement)"
        return 0, 0, 0, f"🟢 FRANCHISE ACTIVE (Reste {abs(jours_depasses)} jours)"
    except Exception:
        return 0, 0, 0, "⚪ Non évalué"


@st.cache_data(ttl=3600)
def obtenir_taux_change_automatique():
    default_rates = {"CNY": 85.0, "USD": 610.0, "EUR": 655.957, "AED": 166.0}
    try:
        res = requests.get("https://open.er-api.com/v6/latest/USD", timeout=4)
        if res.status_code == 200:
            rates = res.json().get("rates", {})
            usd_xof = rates.get("XOF", 610.0)
            return {
                "CNY": round(usd_xof / rates.get("CNY", 7.2), 2),
                "USD": round(usd_xof, 2),
                "EUR": 655.957,
                "AED": round(usd_xof / rates.get("AED", 3.67), 2),
            }, "🟢 Taux direct API (Temps réel)"
    except Exception:
        pass
    return default_rates, "⚠️ Mode secours (Hors ligne)"


taux_devises_dict, status_api_devises = obtenir_taux_change_automatique()


def calculer_droits_douane(caf_xof, dd_pct, regime_code):
    if "C100" in regime_code:
        droits_hors_tva = caf_xof * (dd_pct / 100.0 + 0.020)
        return droits_hors_tva + (caf_xof + droits_hors_tva) * 0.18
    if "E100" in regime_code or "TR" in regime_code:
        return caf_xof * 0.005
    if "AT" in regime_code:
        return caf_xof * 0.010
    droits_hors_tva = caf_xof * (dd_pct / 100.0 + 0.02)
    return droits_hors_tva + (caf_xof + droits_hors_tva) * 0.18


def generer_bae_pdf(dossier_id, client, article, bl_num, container_num, quittance_num, total_facture):
    pdf_filename = f"BAE_Officiel_SNDGIR_{dossier_id}.pdf"
    doc = SimpleDocTemplate(pdf_filename, pagesize=letter, rightMargin=35, leftMargin=35, topMargin=35, bottomMargin=35)
    styles = getSampleStyleSheet(); elements = []
    title_style = ParagraphStyle("TitleStyle", parent=styles["Heading1"], fontSize=16, textColor=colors.HexColor("#064E3B"), alignment=1)
    elements += [
        Paragraph("<b>RÉPUBLIQUE DE CÔTE D'IVOIRE</b>", title_style),
        Paragraph("<font size=10>DIRECTION GÉNÉRALE DES DOUANES — SYSTEME SNDGIR</font>", title_style),
        Spacer(1, 15),
    ]
    hash_val = hashlib.sha256(f"{dossier_id}-{quittance_num}-{total_facture}".encode()).hexdigest()[:24].upper()
    elements += [
        Paragraph(
            f"<b>BON À ENLEVER (BAE) OFFICIEL — MAINLEVÉE ACCORDÉE</b><br/><br/>"
            f"<b>N° de Dossier :</b> RCI-DOUANE-2026-{dossier_id}<br/>"
            f"<b>N° de Quittance Caisse :</b> {quittance_num}<br/>"
            f"<b>Importateur / Destinataire :</b> {client}<br/>"
            f"<b>Désignation :</b> {article}<br/>"
            f"<b>N° Connaissement / B/L :</b> {bl_num} | <b>N° Conteneur :</b> {container_num}<br/>"
            f"<b>Montant Droits Acquittés :</b> {total_facture:,.0f} FCFA<br/>"
            f"<b>Empreinte Électronique Sécurisée :</b> <code>{hash_val}</code>",
            styles["Normal"],
        ),
        Spacer(1, 20),
        Paragraph(
            "<b>Le Chef du Bureau de Douane certifie que la marchandise ci-dessus a satisfait à toutes les "
            "obligations douanières et autorise son enlèvement du port.</b>",
            styles["Normal"],
        ),
    ]
    doc.build(elements)
    return pdf_filename


def generer_facture_transit_pdf(dossier_id, client, article, total_douane, honoraires, frais_port, frais_transport, surestaries):
    pdf_filename = f"Facture_Transit_{dossier_id}_{client.replace(' ', '_')}.pdf"
    doc = SimpleDocTemplate(pdf_filename, pagesize=letter, rightMargin=35, leftMargin=35, topMargin=35, bottomMargin=35)
    styles = getSampleStyleSheet(); elements = []
    title_style = ParagraphStyle("TitleStyle", parent=styles["Heading1"], fontSize=16, textColor=colors.HexColor("#0284C7"), alignment=1)
    elements += [
        Paragraph("<b>AGENCE DE TRANSIT & LOGISTIQUE INTERNATIONALE</b>", title_style),
        Paragraph("<font size=10>Facture Définitive de Dédouanement et Prestations</font>", title_style),
        Spacer(1, 15),
    ]
    tva_hon = honoraires * 0.18
    total_general = total_douane + honoraires + tva_hon + frais_port + frais_transport + surestaries
    data = [
        ["Rubrique / Prestation", "Montant (FCFA)"],
        ["Droits & Taxes de Douane (Débours)", f"{total_douane:,.0f} FCFA"],
        ["Frais de Passage Portuaire & Acconage (Débours)", f"{frais_port:,.0f} FCFA"],
        ["Frais de Transport Terrestre / Livraison", f"{frais_transport:,.0f} FCFA"],
        ["Pénalités de Surestaries / Immobilisation", f"{surestaries:,.0f} FCFA"],
        ["Honoraires & Commission de Transit", f"{honoraires:,.0f} FCFA"],
        ["TVA sur Honoraires (18%)", f"{tva_hon:,.0f} FCFA"],
        ["TOTAL GÉNÉRAL À PAYER", f"{total_general:,.0f} FCFA"],
    ]
    t = Table(data, colWidths=[300, 200])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F172A")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("TEXTCOLOR", (0, -1), (-1, -1), colors.HexColor("#0284C7")),
    ]))
    elements += [
        Paragraph(f"<b>Facture N° :</b> FAC-2026-{dossier_id:05d}<br/><b>Client :</b> {client}<br/><b>Marchandise :</b> {article}<br/><br/>", styles["Normal"]),
        t,
    ]
    doc.build(elements)
    return pdf_filename


# ======================================================================
# AUTHENTIFICATION (mot de passe) + MFA (TOTP) — étape 2 obligatoire
# ======================================================================
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
    st.session_state.user_role = ""
    st.session_state.username = ""
    st.session_state.pwd_verified = False

if not st.session_state.authenticated:
    st.markdown("<br><br>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown('<div class="custom-card-3d">', unsafe_allow_html=True)
        st.subheader("🔐 Portail National Douanier & Transit (SNDGIR)")
        st.caption("Système National de Dédouanement et Gestion Intégrée du Transit")

        if not st.session_state.pwd_verified:
            username_input = st.text_input("Identifiant Officiel")
            password_input = st.text_input("Mot de passe", type="password")
            if st.button("Se connecter au Système", use_container_width=True):
                conn = sqlite3.connect(DB_NAME)
                row = conn.execute(
                    "SELECT username, password_hash, role, statut FROM users WHERE username = ?", (username_input,)
                ).fetchone()
                conn.close()
                if row:
                    u_name, u_pwd_hash, u_role, u_statut = row
                    if u_statut != "Actif":
                        st.error("Compte désactivé.")
                    elif hash_password(password_input) == u_pwd_hash:
                        st.session_state.pwd_verified = True
                        st.session_state.username = u_name
                        st.session_state.user_role = u_role
                        st.rerun()
                    else:
                        st.error("Mot de passe incorrect.")
                        log_action_complet(username_input or "inconnu", "Échec connexion", "Mot de passe incorrect")
                else:
                    st.error("Identifiant non reconnu. (Ex: admin / transit2026 ou declarant / compta2026)")
        else:
            st.success(f"Mot de passe validé pour **{st.session_state.username}**. Étape 2/2 requise.")
            if sec.bloc_login_mfa(DB_NAME, st.session_state.username):
                st.session_state.authenticated = True
                log_action_complet(st.session_state.username, "Connexion", "Accès accordé au portail (MFA validé)")
                st.rerun()
            if st.button("⬅️ Annuler / changer d'identifiant"):
                st.session_state.pwd_verified = False
                st.rerun()

        st.markdown("</div>", unsafe_allow_html=True)
    st.stop()

# ======================================================================
# SIDEBAR
# ======================================================================
st.sidebar.title("🇨🇮 SNDGIR & TRANSIT ERP")
st.sidebar.markdown(f"**Utilisateur :** `{st.session_state.username}`")
st.sidebar.markdown(f"**Rôle :** `{st.session_state.user_role}`")
st.sidebar.markdown("---")

groq_default_key = st.secrets.get("GROQ_API_KEY", "") if hasattr(st, "secrets") else ""
groq_api_key = st.sidebar.text_input("🔑 Clé API Groq Llama 3", value=groq_default_key, type="password")

st.sidebar.subheader("💱 Taux de Change Officiels")
st.sidebar.caption(status_api_devises)
taux_cny_xof = st.sidebar.number_input("1 CNY (Chine)", value=taux_devises_dict["CNY"], step=0.1)
taux_usd_xof = st.sidebar.number_input("1 USD (Dollar)", value=taux_devises_dict["USD"], step=1.0)
taux_eur_xof = st.sidebar.number_input("1 EUR (Euro)", value=taux_devises_dict["EUR"], step=0.1)
st.sidebar.markdown("---")

with st.sidebar:
    st.subheader("🤖 Assistant IA Douanier Flottant")
    with st.popover("💬 Ouvrir le Chatbot IA", use_container_width=True):
        st.markdown("##### Assistant Virtuel SNDGIR")
        prompt_ia = st.text_area(
            "Posez votre question réglementaire :",
            value="Quelles sont les conditions d'exonération pour le matériel topographique ?",
            key="ai_prompt_floating",
        )
        if st.button("Interroger l'IA", key="btn_submit_ai_floating", use_container_width=True):
            if not groq_api_key:
                st.error("Veuillez configurer votre clé API Groq.")
            elif Groq is None:
                st.error("Le package `groq` n'est pas installé.")
            else:
                try:
                    client_groq = Groq(api_key=groq_api_key)
                    response = client_groq.chat.completions.create(
                        model="llama3-70b-8192",
                        messages=[
                            {"role": "system", "content": "Vous êtes un expert supérieur des douanes et du commerce international en Côte d'Ivoire."},
                            {"role": "user", "content": prompt_ia},
                        ],
                    )
                    st.markdown("##### 💡 Réponse de l'Expert IA :")
                    st.write(response.choices[0].message.content)
                except Exception as e:
                    st.error(f"Erreur lors de l'appel à l'API Groq : {e}")

st.sidebar.markdown("---")
if st.sidebar.button("🚪 Déconnexion", use_container_width=True):
    log_action_complet(st.session_state.username, "Déconnexion", "Fin de session")
    st.session_state.authenticated = False
    st.session_state.pwd_verified = False
    st.rerun()

st.markdown(
    """<div class="header-banner"><h1>🏛️ CÔTE D'IVOIRE : SYSTÈME DÉDOUANEMENT & TRANSIT ERP (v5.1)</h1>
    <p>Cargo, Sélectivité Douanière, Facturation Client, Surestaries, Comptabilité SYSCOHADA,
    Fiscalité, RBAC, MFA & Audit Immuable</p></div>""",
    unsafe_allow_html=True,
)

tabs_list = [
    "📈 Dashboard & Marges",
    "🚢 1. Manifeste & Fret",
    "📋 2. Déclaration en Détail (SAD)",
    "💼 3. Transit ERP & Facturation",
    "💳 4. Caisse & BAE",
    "📊 5. Comptabilité & SYSCOHADA",
    "🧾 6. Fiscalité & Trésor",
    "🔄 7. Passerelle EDI",
    "📄 8. IDP OCR Cross-Check",
    "🌐 9. Innovations",
    "🔐 Admin & Audit",
]
tabs = st.tabs(tabs_list)
(tab_dash, tab_manifeste, tab_sad, tab_transit_erp, tab_caisse,
 tab_compta, tab_fiscal, tab_edi, tab_ocr, tab_innov, tab_admin) = tabs

# ---------------- DASHBOARD ----------------
with tab_dash:
    if require_permission("dashboard.view", DB_NAME):
        st.markdown('<div class="custom-card-3d">', unsafe_allow_html=True)
        st.subheader("📈 Performance Globale : Douanes & Agence de Transit")
        conn = sqlite3.connect(DB_NAME); df_d = pd.read_sql_query("SELECT * FROM dossiers", conn); conn.close()
        if df_d.empty:
            st.info("Aucun dossier enregistré dans le système.")
        else:
            tot_droits = df_d["total_facture"].sum(); nb_decl = len(df_d)
            nb_rouge = len(df_d[df_d["canal_selectivite"] == "ROUGE"]); nb_vert = len(df_d[df_d["canal_selectivite"] == "VERT"])
            k1, k2, k3, k4 = st.columns(4)
            with k1: st.markdown(f'<div class="kpi-card"><div class="kpi-title">Droits Douane Liquidés</div><div class="kpi-value">{tot_droits:,.0f} FCFA</div></div>', unsafe_allow_html=True)
            with k2: st.markdown(f'<div class="kpi-card"><div class="kpi-title">Dossiers Traités</div><div class="kpi-value">{nb_decl}</div></div>', unsafe_allow_html=True)
            with k3: st.markdown(f'<div class="kpi-card"><div class="kpi-title">Circuits Verts (Mainlevée)</div><div class="kpi-value" style="color:#34D399;">{nb_vert}</div></div>', unsafe_allow_html=True)
            with k4: st.markdown(f'<div class="kpi-card"><div class="kpi-title">Circuits Rouges (Inspections)</div><div class="kpi-value" style="color:#F87171;">{nb_rouge}</div></div>', unsafe_allow_html=True)
            col_g1, col_g2 = st.columns(2)
            with col_g1:
                fig_canal = px.pie(df_d, names="canal_selectivite", title="Répartition par Canal de Sélectivité", hole=0.4,
                                    color_discrete_map={"VERT": "#047857", "BLEU": "#1D4ED8", "JAUNE": "#D97706", "ROUGE": "#B91C1C"})
                fig_canal.update_layout(paper_bgcolor="rgba(0,0,0,0)", font_color="white")
                st.plotly_chart(fig_canal, use_container_width=True)
            with col_g2:
                fig_regime = px.bar(df_d, x="regime", y="total_facture", color="canal_selectivite", title="Recettes Douanières par Régime")
                fig_regime.update_layout(paper_bgcolor="rgba(0,0,0,0)", font_color="white")
                st.plotly_chart(fig_regime, use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)

# ---------------- MANIFESTE & FRET ----------------
with tab_manifeste:
    if require_permission("manifeste.view", DB_NAME):
        st.markdown('<div class="custom-card-3d">', unsafe_allow_html=True)
        st.subheader("🚢 Module Cargo : Manifestes Maritimes & Aériens")
        col_m1, col_m2 = st.columns(2)
        with col_m1:
            st.markdown("##### 1️⃣ Enregistrer un Nouveau Manifeste")
            if require_permission("manifeste.create", DB_NAME):
                with st.form("form_manifeste"):
                    m_num = st.text_input("N° Manifeste (ex: MAN-2026-ABJ-001)")
                    m_transport = st.selectbox("Moyen de Transport", ["Maritime (Navire)", "Aérien (Avion)", "Routier (Camion)"])
                    m_voyage = st.text_input("N° Voyage / Vol", value="MSC-VITA-2026")
                    m_prov = st.text_input("Port de Provenance", value="Guangzhou, Chine")
                    m_date = st.date_input("Date d'Arrivée Prévue", value=datetime.now())
                    btn_m = st.form_submit_button("Enregistrer le Manifeste")
                if btn_m and m_num:
                    conn = sqlite3.connect(DB_NAME); cursor = conn.cursor()
                    try:
                        cursor.execute("INSERT INTO manifestes (num_manifeste,moyen_transport,num_voyage,provenance,date_arrivee) VALUES (?,?,?,?,?)",
                                       (m_num, m_transport, m_voyage, m_prov, m_date.strftime("%Y-%m-%d")))
                        conn.commit()
                        log_action_complet(st.session_state.username, "Ajout Manifeste", f"Manifeste {m_num} créé")
                        st.success(f"Manifeste {m_num} enregistré avec succès !")
                    except Exception as e:
                        st.error(f"Erreur : {e}")
                    conn.close()
        with col_m2:
            st.markdown("##### 2️⃣ Ajouter un Connaissement / B/L")
            conn = sqlite3.connect(DB_NAME); df_man = pd.read_sql_query("SELECT num_manifeste FROM manifestes", conn); conn.close()
            if not df_man.empty and require_permission("manifeste.create", DB_NAME):
                with st.form("form_fret"):
                    f_man = st.selectbox("Manifeste Associé", df_man["num_manifeste"].tolist())
                    f_bl = st.text_input("N° Connaissement / B/L", value="MEDU98765432")
                    f_client = st.text_input("Destinataire (Consignee)", value="ETS KOUASSI & FRERES")
                    f_poids = st.number_input("Poids Brut (kg)", value=1500.0)
                    f_colis = st.number_input("Nombre de Colis", value=45)
                    btn_f = st.form_submit_button("Rattacher le Connaissement")
                if btn_f and f_bl:
                    conn = sqlite3.connect(DB_NAME); cursor = conn.cursor()
                    try:
                        cursor.execute("INSERT INTO fret_lines (num_manifeste,bl_number,consignee,poids_brut,nb_colis) VALUES (?,?,?,?,?)",
                                       (f_man, f_bl, f_client, f_poids, f_colis))
                        conn.commit()
                        st.success(f"B/L {f_bl} rattaché au manifeste {f_man} !")
                    except Exception as e:
                        st.error(f"Erreur B/L existant : {e}")
                    conn.close()
        st.markdown("---")
        st.markdown("### Registre des Connaissements & Apurement Cargo")
        conn = sqlite3.connect(DB_NAME); df_fret_all = pd.read_sql_query("SELECT * FROM fret_lines", conn); conn.close()
        st.dataframe(df_fret_all, use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)

# ---------------- SAD ----------------
with tab_sad:
    if require_permission("sad.view", DB_NAME):
        st.markdown('<div class="custom-card-3d">', unsafe_allow_html=True)
        st.subheader("📋 Module Douane : Saisie du SAD & Sélectivité")
        conn = sqlite3.connect(DB_NAME)
        df_art_db = pd.read_sql_query("SELECT * FROM articles", conn)
        df_bl_unpurged = pd.read_sql_query("SELECT bl_number,consignee FROM fret_lines WHERE statut_apurement = 'Non apuré'", conn)
        conn.close()
        c1, c2, c3 = st.columns(3)
        with c1: client_decl = st.text_input("Nom de l'Importateur / Client", value="ETS KOUASSI & FRERES")
        with c2: bl_select = st.selectbox("N° Connaissement / B/L (Apurement Cargo)", df_bl_unpurged["bl_number"].tolist() if not df_bl_unpurged.empty else ["MEDU98765432"])
        with c3: container_input = st.text_input("N° Conteneur", value="MSCU1234567")
        col_s1, col_s2 = st.columns([2, 1])
        with col_s1:
            article_nom = st.selectbox("Désignation du Produit (Code SH)", df_art_db["nom"].tolist() if not df_art_db.empty else [])
            item_row = df_art_db[df_art_db["nom"] == article_nom].iloc[0] if not df_art_db.empty else {"sh": "8517.13.00", "dd": 20.0, "categorie": "High-Tech"}
            regime_code = st.selectbox("Régime Douanier", ["C100 - Mise à la consommation directe", "E100 - Entrepôt de douane (Suspensif)", "AT - Admission Temporaire", "TR - Transit / Réexportation"])
            devise_facture = st.selectbox("Devise Commerciale", ["USD", "CNY", "EUR", "AED"])
            m1, m2 = st.columns(2)
            with m1: qte = st.number_input("Quantité", min_value=1, value=100)
            with m2: pu_devise = st.number_input(f"Prix Unitaire ({devise_facture})", min_value=0.01, value=250.0)
            fob_devise = qte * pu_devise
            taux_conv = taux_usd_xof if devise_facture == "USD" else (taux_cny_xof if devise_facture == "CNY" else taux_eur_xof)
            fob_xof = fob_devise * taux_conv
            caf_xof = fob_xof * 1.08
            total_douane = calculer_droits_douane(caf_xof, item_row["dd"], regime_code)
        with col_s2:
            st.markdown("##### 🎯 Analyse du Risque & Sélectivité")
            diff_ocr_simulee = st.slider("Divergence OCR Facture vs Déclaration (%)", 0.0, 30.0, 2.0)
            score_risk, canal, motifs_risk = calculer_selectivite_risque(fob_xof, {"cat": item_row["categorie"]}, diff_ocr_simulee, client_decl)
            badge_class = "canal-vert" if canal == "VERT" else ("canal-bleu" if canal == "BLEU" else ("canal-jaune" if canal == "JAUNE" else "canal-rouge"))
            st.markdown(
                f'<div style="background:#020617;padding:20px;border-radius:14px;border:1px solid #1E293B;text-align:center;">'
                f'<h4>Score de Risque : <span style="color:#38BDF8;">{score_risk} / 100</span></h4>'
                f'<span class="{badge_class}">CANAL {canal}</span><br/><br/><small><b>Motifs :</b> {motifs_risk}</small></div>',
                unsafe_allow_html=True,
            )
        if require_permission("sad.create", DB_NAME) and st.button("🚀 Soumettre la Déclaration en Détail (SAD)", use_container_width=True):
            conn = sqlite3.connect(DB_NAME); cursor = conn.cursor()
            date_str = datetime.now().strftime("%Y-%m-%d %H:%M")
            cursor.execute(
                "INSERT INTO dossiers (date,client,article,regime,fob_xof,total_facture,solde_du,statut,bl_number,container_number,date_arrivee,score_risque,canal_selectivite,motifs_risque) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (date_str, client_decl, article_nom, regime_code, fob_xof, total_douane, total_douane,
                 "En cours de contrôle" if canal in ["JAUNE", "ROUGE"] else "Liquidé - En attente de paiement",
                 bl_select, container_input, datetime.now().strftime("%Y-%m-%d"), score_risk, canal, motifs_risk),
            )
            cursor.execute("UPDATE fret_lines SET statut_apurement='Apuré par SAD' WHERE bl_number=?", (bl_select,))
            conn.commit(); conn.close()
            log_action_complet(st.session_state.username, "Soumission SAD", f"SAD enregistrée pour {client_decl} - Canal {canal}")
            st.success(f"Déclaration enregistrée sous le Canal **{canal}** !")
        st.markdown("</div>", unsafe_allow_html=True)

# ---------------- TRANSIT ERP ----------------
with tab_transit_erp:
    if require_permission("transit.view", DB_NAME):
        st.markdown('<div class="custom-card-3d">', unsafe_allow_html=True)
        st.subheader("💼 Module Transitaire : Facturation, Débours & Surestaries")
        conn = sqlite3.connect(DB_NAME); df_dos_t = pd.read_sql_query("SELECT * FROM dossiers ORDER BY id DESC", conn); conn.close()
        if df_dos_t.empty:
            st.info("Aucun dossier disponible pour la facturation transit.")
        else:
            sel_dos_id = st.selectbox("Sélectionner un Dossier de Transit à Facturer", df_dos_t["id"].tolist())
            row_t = df_dos_t[df_dos_t["id"] == sel_dos_id].iloc[0]
            st.markdown(f"### 📑 Dossier N° RCI-DOUANE-2026-{row_t['id']} | Client : **{row_t['client']}**")
            col_tr1, col_tr2 = st.columns(2)
            with col_tr1:
                st.markdown("##### ⏱️ Suivi de la Franchise & Surestaries")
                d_dechargement = st.date_input("Date de Déchargement du Conteneur", value=datetime.now() - timedelta(days=6))
                franchise_j = st.number_input("Jours de Franchise Accordés par l'Armateur", value=7, min_value=1)
                penalite_usd = st.number_input("Pénalité Jour Supplémentaire ($ USD)", value=50.0)
                j_dep, c_usd, c_xof, statut_sure = calculer_surestaries(d_dechargement.strftime("%Y-%m-%d"), franchise_j, penalite_usd, taux_usd_xof)
                st.info(f"**Statut Surestaries :** {statut_sure}")
                if j_dep > 0:
                    st.error(f"Pénalité calculée : **${c_usd:,.2f} USD** ({c_xof:,.0f} FCFA)")
                st.markdown("---")
                st.markdown("##### 📋 Checklist Documentaire Dossier Transit")
                st.checkbox("Facture Commerciale Originale", value=True)
                st.checkbox("Connaissement / B/L Original", value=True)
                st.checkbox("Attestation de Vérification (AVD / Webb Fontaine)", value=True)
                st.checkbox("Bordereau de Suivi de Cargaison (BSC / OIC)", value=False)
            with col_tr2:
                st.markdown("##### 💰 Éléments de Facturation Transitaire")
                d_douane = float(row_t["total_facture"]) if pd.notna(row_t["total_facture"]) else 0.0
                val_f_port = float(row_t["frais_port"]) if pd.notna(row_t["frais_port"]) else 85000.0
                val_f_transport = float(row_t["frais_transport"]) if pd.notna(row_t["frais_transport"]) else 120000.0
                val_f_honoraires = float(row_t["honoraires"]) if pd.notna(row_t["honoraires"]) else 150000.0
                f_port = st.number_input("Frais de Passage Portuaire & Acconage (FCFA)", value=val_f_port)
                f_transport = st.number_input("Frais de Transport Terrestre / Camionnage (FCFA)", value=val_f_transport)
                f_honoraires = st.number_input("Honoraires / Commission de Transit (FCFA)", value=val_f_honoraires)
                tva_honoraires = f_honoraires * 0.18
                total_facture_globale = d_douane + f_port + f_transport + c_xof + f_honoraires + tva_honoraires
                st.markdown(f"#### **TOTAL FACTURE TRANSIT :** `{total_facture_globale:,.0f} FCFA`")
                if require_permission("transit.facturer", DB_NAME) and st.button("📄 Mettre à Jour & Générer la Facture Client (PDF)", use_container_width=True):
                    conn = sqlite3.connect(DB_NAME)
                    conn.execute("UPDATE dossiers SET honoraires=?, frais_port=?, frais_transport=?, surestaries_xof=? WHERE id=?",
                                 (f_honoraires, f_port, f_transport, c_xof, sel_dos_id))
                    conn.commit(); conn.close()
                    pdf_fac = generer_facture_transit_pdf(sel_dos_id, row_t["client"], row_t["article"], d_douane, f_honoraires, f_port, f_transport, c_xof)
                    log_action_complet(st.session_state.username, "Facturation Transit", f"Facture générée pour dossier #{sel_dos_id}")
                    with open(pdf_fac, "rb") as fh:
                        st.download_button("📥 Télécharger la Facture Définitive Transitaire (PDF)", data=fh.read(), file_name=pdf_fac, mime="application/pdf", use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)

# ---------------- CAISSE & BAE ----------------
with tab_caisse:
    if require_permission("caisse.view", DB_NAME):
        st.markdown('<div class="custom-card-3d">', unsafe_allow_html=True)
        st.subheader("💳 Module Caisse & Bon à Enlever (BAE) Sécurisé")
        conn = sqlite3.connect(DB_NAME); df_dossiers_all = pd.read_sql_query("SELECT * FROM dossiers ORDER BY id DESC", conn); conn.close()
        if df_dossiers_all.empty:
            st.info("Aucune déclaration enregistrée.")
        else:
            st.dataframe(df_dossiers_all[["id", "date", "client", "article", "canal_selectivite", "total_facture", "solde_du", "statut"]], use_container_width=True)
            st.markdown("---")
            st.subheader("⚙️ Encaisser la Liquidation & Délivrer le BAE")
            col_pay1, col_pay2 = st.columns(2)
            with col_pay1:
                sel_dossier_id = st.selectbox("Sélectionner l'ID du Dossier à Encaisser", df_dossiers_all["id"].tolist(), key="caisse_sel_id")
                row_pay = df_dossiers_all[df_dossiers_all["id"] == sel_dossier_id].iloc[0]
                st.write(f"**Client :** {row_pay['client']} | **Montant à Régler :** `{row_pay['solde_du']:,.0f} FCFA`")
            with col_pay2:
                moyen_paiement = st.selectbox("Mode de Règlement", ["TrésorPay / RTGS Banque Centrale", "Chèque Certifié Trésor Public", "Virement SWIFT", "Mobile Money"])
                if require_permission("caisse.encaisser", DB_NAME) and st.button("💳 Valider le Paiement & Émettre le BAE", use_container_width=True):
                    quittance = f"QUIT-2026-{sel_dossier_id:05d}"
                    montant_regle = row_pay["solde_du"]
                    conn = sqlite3.connect(DB_NAME)
                    conn.execute("UPDATE dossiers SET solde_du=0, statut='Liquidé & Payé (BAE Émis)', quittance_num=? WHERE id=?", (quittance, sel_dossier_id))
                    date_j = datetime.now().strftime("%Y-%m-%d")
                    conn.execute(
                        """INSERT INTO compta_ecritures (date, journal, compte_debit, libelle_debit, compte_credit, libelle_credit, montant, piece_ref)
                           VALUES (?, 'CAI', '521000', 'Banque / Caisse Recettes', '411000', ?, ?, ?)""",
                        (date_j, f"Client {row_pay['client']}", montant_regle, quittance),
                    )
                    conn.commit(); conn.close()
                    log_action_complet(st.session_state.username, "Paiement Caisse", f"Quittance {quittance} générée pour dossier #{sel_dossier_id} — {moyen_paiement}")

                    pdf_bae = generer_bae_pdf(sel_dossier_id, row_pay["client"], row_pay["article"], row_pay["bl_number"], row_pay["container_number"], quittance, montant_regle)
                    st.success(f"Paiement validé — Quittance **{quittance}** — BAE émis.")
                    with open(pdf_bae, "rb") as fh:
                        st.download_button("📥 Télécharger le Bon à Enlever (BAE)", data=fh.read(), file_name=pdf_bae, mime="application/pdf", use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)

# ---------------- COMPTABILITÉ SYSCOHADA ----------------
with tab_compta:
    st.markdown('<div class="custom-card-3d">', unsafe_allow_html=True)
    if require_permission("compta.view", DB_NAME):
        compta.render(DB_NAME, username=st.session_state.username)
    st.markdown("</div>", unsafe_allow_html=True)

# ---------------- FISCALITÉ ----------------
with tab_fiscal:
    st.markdown('<div class="custom-card-3d">', unsafe_allow_html=True)
    if require_permission("fiscal.view", DB_NAME):
        fiscal.render(DB_NAME)
    st.markdown("</div>", unsafe_allow_html=True)

# ---------------- MODULES NON ENCORE IMPLÉMENTÉS (stubs honnêtes) ----------------
with tab_edi:
    st.markdown('<div class="custom-card-3d">', unsafe_allow_html=True)
    st.subheader("🔄 Passerelle EDI")
    st.warning("🚧 Module non implémenté dans cette version — prévu : échange de messages EDIFACT avec Webb Fontaine / GUCE, à cadrer avec le format d'échange exact attendu par la DGD.")
    st.markdown("</div>", unsafe_allow_html=True)

with tab_ocr:
    st.markdown('<div class="custom-card-3d">', unsafe_allow_html=True)
    st.subheader("📄 IDP OCR Cross-Check")
    st.warning("🚧 Module non implémenté dans cette version — le slider de sélectivité (onglet SAD) simule la divergence OCR, mais l'extraction réelle de facture (OCR) n'est pas branchée.")
    st.markdown("</div>", unsafe_allow_html=True)

with tab_innov:
    st.markdown('<div class="custom-card-3d">', unsafe_allow_html=True)
    st.subheader("🌐 Innovations")
    st.info("Espace réservé pour de futures fonctionnalités (à définir avec toi).")
    st.markdown("</div>", unsafe_allow_html=True)

# ---------------- ADMIN & AUDIT ----------------
with tab_admin:
    st.markdown('<div class="custom-card-3d">', unsafe_allow_html=True)
    if require_permission("admin.audit", DB_NAME):
        st.subheader("👥 Utilisateurs & Rôles")
        conn = sqlite3.connect(DB_NAME); df_users = pd.read_sql_query("SELECT id, username, role, statut FROM users", conn); conn.close()
        st.dataframe(df_users, use_container_width=True)
        st.markdown("---")
        sec.render_audit_viewer(DB_NAME)
    st.markdown("</div>", unsafe_allow_html=True)
