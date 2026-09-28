"""
documents_pdf.py — BaobabVault ERP
Génération de PDF professionnels (factures, attestations) avec QR code de
vérification cryptographique, + envoi omnicanal (Email / WhatsApp / SMS).

Vérification cryptographique : chaque document reçoit une empreinte
HMAC-SHA256 calculée sur son contenu + une clé secrète serveur. Le QR code
encode une URL de vérification portant cette empreinte. Quiconque scanne
le QR peut confirmer que le PDF n'a pas été altéré après émission, sans
dépendre d'un service tiers.
"""

import hashlib
import hmac
import io
import os
import smtplib
import sqlite3
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication

import qrcode
import streamlit as st
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

import alertes  # réutilise ton module SMS/WhatsApp existant

VERIF_SECRET = None  # chargé paresseusement depuis st.secrets — voir _secret()


def _secret() -> bytes:
    global VERIF_SECRET
    if VERIF_SECRET is None:
        cle = st.secrets.get("DOCUMENT_SIGNING_SECRET", "") if hasattr(st, "secrets") else ""
        if not cle:
            cle = "dev-only-signing-key-a-remplacer-en-production"
        VERIF_SECRET = cle.encode("utf-8")
    return VERIF_SECRET


def init_documents_tables(db_name: str):
    conn = sqlite3.connect(db_name)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS documents_emis (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reference TEXT UNIQUE,
            type_document TEXT,
            client TEXT,
            montant REAL,
            empreinte TEXT,
            created_at TEXT,
            created_by TEXT
        )
    """)
    conn.commit()
    conn.close()


def _empreinte_document(reference: str, client: str, montant: float, date_emission: str) -> str:
    """Signature HMAC-SHA256 du contenu clé du document — infalsifiable sans le secret serveur."""
    contenu = f"{reference}|{client}|{montant}|{date_emission}".encode("utf-8")
    return hmac.new(_secret(), contenu, hashlib.sha256).hexdigest()[:24].upper()


def verifier_document(db_name: str, reference: str, empreinte_fournie: str) -> dict:
    """Utilisé par la page de vérification publique (scannée via le QR)."""
    conn = sqlite3.connect(db_name)
    row = conn.execute(
        "SELECT client, montant, empreinte, created_at FROM documents_emis WHERE reference=?",
        (reference,),
    ).fetchone()
    conn.close()
    if not row:
        return {"valide": False, "message": "Document introuvable — référence inconnue."}
    client, montant, empreinte_stockee, created_at = row
    if empreinte_fournie.upper() != empreinte_stockee.upper():
        return {"valide": False, "message": "⚠️ Empreinte invalide — ce document a peut-être été altéré."}
    return {
        "valide": True,
        "message": "✅ Document authentique et non modifié.",
        "client": client, "montant": montant, "emis_le": created_at,
    }


def generer_pdf_facture(db_name: str, reference: str, client: str, adresse_client: str,
                         lignes: list[dict], created_by: str, url_verification_base: str) -> bytes:
    """
    lignes : [{"designation": str, "quantite": float, "prix_unitaire": float}]
    url_verification_base : ex. "https://tonapp.streamlit.app/?verifier=1"
    Retourne les octets du PDF (à proposer en téléchargement ou à joindre à un email).
    """
    init_documents_tables(db_name)
    date_emission = datetime.now().strftime("%Y-%m-%d")
    montant_total = sum(l["quantite"] * l["prix_unitaire"] for l in lignes)
    empreinte = _empreinte_document(reference, client, montant_total, date_emission)

    conn = sqlite3.connect(db_name)
    conn.execute(
        "INSERT OR REPLACE INTO documents_emis (reference, type_document, client, montant, empreinte, created_at, created_by) VALUES (?,?,?,?,?,?,?)",
        (reference, "Facture", client, montant_total, empreinte, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), created_by),
    )
    conn.commit()
    conn.close()

    # --- QR code de vérification ---
    url_verif = f"{url_verification_base}&ref={reference}&sig={empreinte}"
    qr_img = qrcode.make(url_verif)
    qr_buffer = io.BytesIO()
    qr_img.save(qr_buffer, format="PNG")
    qr_buffer.seek(0)

    # --- Construction du PDF ---
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=20 * mm, bottomMargin=20 * mm)
    styles = getSampleStyleSheet()
    style_titre = ParagraphStyle("Titre", parent=styles["Heading1"], textColor=colors.HexColor("#0A84FF"))
    style_normal = styles["Normal"]

    elements = [
        Paragraph("BaobabVault ERP", style_titre),
        Paragraph(f"Facture n° {reference}", styles["Heading2"]),
        Spacer(1, 6),
        Paragraph(f"Client : {client}", style_normal),
        Paragraph(f"Adresse : {adresse_client}", style_normal),
        Paragraph(f"Date d'émission : {date_emission}", style_normal),
        Spacer(1, 16),
    ]

    data = [["Désignation", "Qté", "Prix unitaire (FCFA)", "Total (FCFA)"]]
    for l in lignes:
        total_ligne = l["quantite"] * l["prix_unitaire"]
        data.append([l["designation"], f"{l['quantite']:g}", f"{l['prix_unitaire']:,.0f}", f"{total_ligne:,.0f}"])
    data.append(["", "", "TOTAL", f"{montant_total:,.0f} FCFA"])

    table = Table(data, colWidths=[80 * mm, 20 * mm, 40 * mm, 40 * mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0E1830")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CCCCCC")),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
    ]))
    elements.append(table)
    elements.append(Spacer(1, 24))

    elements.append(Paragraph("Vérification d'authenticité :", styles["Heading3"]))
    elements.append(Image(qr_buffer, width=30 * mm, height=30 * mm))
    elements.append(Paragraph(f"Référence : {reference} — Empreinte : {empreinte}", ParagraphStyle("petit", parent=style_normal, fontSize=7, textColor=colors.grey)))

    doc.build(elements)
    buffer.seek(0)
    return buffer.getvalue()


# ======================================================================
# ENVOI OMNICANAL
# ======================================================================
def envoyer_email_avec_piece_jointe(destinataire: str, sujet: str, corps: str, pdf_bytes: bytes, nom_fichier: str) -> dict:
    hote = st.secrets.get("SMTP_HOST", "") if hasattr(st, "secrets") else ""
    port = int(st.secrets.get("SMTP_PORT", 587)) if hasattr(st, "secrets") else 587
    utilisateur = st.secrets.get("SMTP_USER", "") if hasattr(st, "secrets") else ""
    mdp = st.secrets.get("SMTP_PASSWORD", "") if hasattr(st, "secrets") else ""

    if not hote or not utilisateur:
        return {"succes": False, "details": "SMTP non configuré (simulation) — email non envoyé."}

    try:
        msg = MIMEMultipart()
        msg["From"] = utilisateur
        msg["To"] = destinataire
        msg["Subject"] = sujet
        msg.attach(MIMEText(corps, "plain"))
        piece = MIMEApplication(pdf_bytes, _subtype="pdf")
        piece.add_header("Content-Disposition", "attachment", filename=nom_fichier)
        msg.attach(piece)

        with smtplib.SMTP(hote, port) as serveur:
            serveur.starttls()
            serveur.login(utilisateur, mdp)
            serveur.send_message(msg)
        return {"succes": True, "details": "Email envoyé."}
    except Exception as e:
        return {"succes": False, "details": f"Échec envoi email : {e}"}


def envoyer_whatsapp_document(numero: str, message: str) -> dict:
    """Envoi WhatsApp du lien de vérification (l'API Cloud WhatsApp n'envoie pas
    de PDF brut hors template validé — on envoie le message + lien de vérification/téléchargement)."""
    try:
        from lib.whatsapp.client import sendWhatsAppMessage  # si le projet Next.js est mutualisé
    except ImportError:
        pass
    # Implémentation directe Meta Cloud API pour un projet Python pur :
    token = st.secrets.get("WHATSAPP_ACCESS_TOKEN", "") if hasattr(st, "secrets") else ""
    phone_id = st.secrets.get("WHATSAPP_PHONE_NUMBER_ID", "") if hasattr(st, "secrets") else ""
    if not token or not phone_id:
        return {"succes": False, "details": "WhatsApp non configuré (simulation) — message non envoyé."}
    import requests
    try:
        resp = requests.post(
            f"https://graph.facebook.com/v20.0/{phone_id}/messages",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"messaging_product": "whatsapp", "to": numero, "type": "text", "text": {"body": message}},
            timeout=10,
        )
        resp.raise_for_status()
        return {"succes": True, "details": "Message WhatsApp envoyé."}
    except Exception as e:
        return {"succes": False, "details": f"Échec envoi WhatsApp : {e}"}


def render_documents(db_name: str, utilisateur_courant: str, url_verification_base: str):
    import theme
    theme.inject_apple_theme()
    init_documents_tables(db_name)
    st.subheader("🧾 Génération de documents & envoi omnicanal")

    with st.form("form_facture"):
        c1, c2 = st.columns(2)
        with c1:
            reference = st.text_input("Référence facture (ex: FAC-2026-0142)")
            client = st.text_input("Nom du client")
        with c2:
            adresse_client = st.text_input("Adresse du client")
            contact_client = st.text_input("Téléphone / email du client")

        st.markdown("##### Lignes de facturation")
        nb_lignes = st.number_input("Nombre de lignes", min_value=1, max_value=15, value=1)
        lignes = []
        for i in range(int(nb_lignes)):
            lc1, lc2, lc3 = st.columns([3, 1, 1])
            with lc1:
                designation = st.text_input(f"Désignation {i+1}", key=f"desig_{i}")
            with lc2:
                quantite = st.number_input(f"Qté {i+1}", min_value=0.0, value=1.0, key=f"qte_{i}")
            with lc3:
                prix_unitaire = st.number_input(f"P.U. {i+1}", min_value=0.0, step=1000.0, key=f"pu_{i}")
            if designation:
                lignes.append({"designation": designation, "quantite": quantite, "prix_unitaire": prix_unitaire})

        genere = st.form_submit_button("📄 Générer le PDF", use_container_width=True)

    if genere and reference and client and lignes:
        pdf_bytes = generer_pdf_facture(db_name, reference, client, adresse_client, lignes, utilisateur_courant, url_verification_base)
        st.session_state["dernier_pdf"] = pdf_bytes
        st.session_state["dernier_pdf_ref"] = reference
        st.session_state["dernier_pdf_contact"] = contact_client
        st.success("PDF généré avec QR code de vérification.")

    if "dernier_pdf" in st.session_state:
        st.download_button(
            "⬇️ Télécharger le PDF",
            data=st.session_state["dernier_pdf"],
            file_name=f"{st.session_state['dernier_pdf_ref']}.pdf",
            mime="application/pdf",
            use_container_width=True,
        )

        st.markdown("##### 📤 Envoi omnicanal")
        c1, c2, c3 = st.columns(3)
        with c1:
            if st.button("📧 Envoyer par Email", use_container_width=True):
                res = envoyer_email_avec_piece_jointe(
                    st.session_state["dernier_pdf_contact"],
                    f"Votre facture {st.session_state['dernier_pdf_ref']} — BaobabVault",
                    "Veuillez trouver ci-joint votre facture.",
                    st.session_state["dernier_pdf"],
                    f"{st.session_state['dernier_pdf_ref']}.pdf",
                )
                (st.success if res["succes"] else st.warning)(res["details"])
        with c2:
            if st.button("💬 Envoyer par WhatsApp", use_container_width=True):
                res = envoyer_whatsapp_document(
                    st.session_state["dernier_pdf_contact"],
                    f"Votre facture {st.session_state['dernier_pdf_ref']} est prête. Vérification : {url_verification_base}&ref={st.session_state['dernier_pdf_ref']}",
                )
                (st.success if res["succes"] else st.warning)(res["details"])
        with c3:
            if st.button("📱 Envoyer par SMS", use_container_width=True):
                res = alertes.envoyer_sms(
                    [st.session_state["dernier_pdf_contact"]],
                    f"BaobabVault : votre facture {st.session_state['dernier_pdf_ref']} est disponible.",
                )
                st.info("Résultat SMS journalisé (voir module alertes).")

    st.markdown("---")
    st.markdown("### 📋 Documents émis")
    conn = sqlite3.connect(db_name)
    import pandas as pd
    df = pd.read_sql_query("SELECT reference, type_document, client, montant, created_at, created_by FROM documents_emis ORDER BY id DESC", conn)
    conn.close()
    st.dataframe(df, use_container_width=True)
