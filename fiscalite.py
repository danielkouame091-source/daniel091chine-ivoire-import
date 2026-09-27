"""
fiscalite.py — Module Fiscalité & Trésor (Côte d'Ivoire / UEMOA)

⚠️ Les taux ci-dessous (TVA 18%, IS 25%, minimum de perception) sont ceux
en vigueur au moment de la rédaction de ce module, à titre de valeurs par
défaut modifiables. Ils doivent être vérifiés à chaque exercice fiscal
auprès de la Direction Générale des Impôts (DGI) de Côte d'Ivoire — ce
module ne remplace pas un conseil fiscal professionnel.

Fournit :
- Calcul TVA collectée / déductible / à décaisser
- Calcul de l'Impôt sur les Bénéfices Industriels et Commerciaux (BIC/IS)
  avec minimum forfaitaire
- Génération PDF d'un état de déclaration mensuel

À appeler depuis app.py :

    import fiscalite as fiscal
    with tab_fiscal:
        fiscal.render(DB_NAME)
"""

import sqlite3
from datetime import datetime

import pandas as pd
import streamlit as st

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

TAUX_TVA_UEMOA = 0.18
TAUX_IS_CI = 0.25          # Impôt sur les sociétés / BIC, régime réel normal
MINIMUM_PERCEPTION_IS = 3_000_000  # minimum forfaitaire de perception (FCFA), indicatif


def calculer_tva(chiffre_affaires_ht: float, achats_deductibles_ht: float) -> dict:
    tva_collectee = chiffre_affaires_ht * TAUX_TVA_UEMOA
    tva_deductible = achats_deductibles_ht * TAUX_TVA_UEMOA
    tva_nette = tva_collectee - tva_deductible
    return {
        "tva_collectee": tva_collectee,
        "tva_deductible": tva_deductible,
        "tva_a_decaisser": max(tva_nette, 0),
        "credit_de_tva": max(-tva_nette, 0),
    }


def calculer_bic(resultat_fiscal: float) -> dict:
    is_calcule = max(resultat_fiscal, 0) * TAUX_IS_CI
    is_du = max(is_calcule, MINIMUM_PERCEPTION_IS) if resultat_fiscal > 0 else 0
    return {
        "resultat_fiscal": resultat_fiscal,
        "is_theorique": is_calcule,
        "minimum_perception": MINIMUM_PERCEPTION_IS,
        "is_du": is_du,
    }


def generer_declaration_pdf(periode: str, contribuable: str, tva: dict, bic: dict | None = None) -> str:
    pdf_filename = f"Declaration_Fiscale_{periode.replace(' ', '_')}.pdf"
    doc = SimpleDocTemplate(pdf_filename, pagesize=letter, rightMargin=35, leftMargin=35, topMargin=35, bottomMargin=35)
    styles = getSampleStyleSheet()
    elements = []
    title_style = ParagraphStyle("Title", parent=styles["Heading1"], fontSize=15, textColor=colors.HexColor("#064E3B"), alignment=1)

    elements += [
        Paragraph("<b>RÉPUBLIQUE DE CÔTE D'IVOIRE</b>", title_style),
        Paragraph("<font size=10>Direction Générale des Impôts — Déclaration Fiscale Périodique</font>", title_style),
        Spacer(1, 15),
        Paragraph(f"<b>Contribuable :</b> {contribuable}<br/><b>Période :</b> {periode}", styles["Normal"]),
        Spacer(1, 10),
    ]

    data_tva = [
        ["TVA", "Montant (FCFA)"],
        ["TVA Collectée", f"{tva['tva_collectee']:,.0f}"],
        ["TVA Déductible", f"{tva['tva_deductible']:,.0f}"],
        ["TVA à Décaisser", f"{tva['tva_a_decaisser']:,.0f}"],
        ["Crédit de TVA reporté", f"{tva['credit_de_tva']:,.0f}"],
    ]
    t_tva = Table(data_tva, colWidths=[300, 200])
    t_tva.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F172A")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("FONTNAME", (0, -2), (-1, -1), "Helvetica-Bold"),
    ]))
    elements.append(t_tva)

    if bic:
        elements.append(Spacer(1, 15))
        data_bic = [
            ["Impôt sur les Bénéfices (BIC/IS)", "Montant (FCFA)"],
            ["Résultat Fiscal", f"{bic['resultat_fiscal']:,.0f}"],
            ["IS Théorique (25%)", f"{bic['is_theorique']:,.0f}"],
            ["Minimum de Perception", f"{bic['minimum_perception']:,.0f}"],
            ["IS Dû (retenu)", f"{bic['is_du']:,.0f}"],
        ]
        t_bic = Table(data_bic, colWidths=[300, 200])
        t_bic.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F172A")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ]))
        elements.append(t_bic)

    doc.build(elements)
    return pdf_filename


def render(db_name: str):
    st.subheader("🧾 Fiscalité & Trésor — TVA / BIC (Côte d'Ivoire, UEMOA)")
    st.caption("Taux par défaut : TVA 18% (UEMOA), IS/BIC 25%, minimum de perception 3 000 000 FCFA — à vérifier chaque exercice auprès de la DGI.")

    sous_tabs = st.tabs(["💶 TVA", "🏢 BIC / IS", "📄 Édition Déclaration"])
    tab_tva, tab_bic, tab_edition = sous_tabs

    with tab_tva:
        c1, c2 = st.columns(2)
        with c1:
            ca_ht = st.number_input("Chiffre d'affaires HT du mois (FCFA)", min_value=0.0, value=0.0, step=100000.0, key="fisc_ca")
        with c2:
            achats_ht = st.number_input("Achats déductibles HT du mois (FCFA)", min_value=0.0, value=0.0, step=100000.0, key="fisc_achats")
        res_tva = calculer_tva(ca_ht, achats_ht)
        st.session_state["_derniere_tva"] = res_tva
        k1, k2, k3 = st.columns(3)
        k1.metric("TVA Collectée", f"{res_tva['tva_collectee']:,.0f} FCFA")
        k2.metric("TVA Déductible", f"{res_tva['tva_deductible']:,.0f} FCFA")
        k3.metric("TVA à Décaisser", f"{res_tva['tva_a_decaisser']:,.0f} FCFA")
        if res_tva["credit_de_tva"] > 0:
            st.info(f"Crédit de TVA à reporter : {res_tva['credit_de_tva']:,.0f} FCFA")

    with tab_bic:
        resultat_fiscal = st.number_input("Résultat fiscal de l'exercice (FCFA)", value=0.0, step=500000.0, key="fisc_resultat")
        res_bic = calculer_bic(resultat_fiscal)
        st.session_state["_dernier_bic"] = res_bic
        k1, k2 = st.columns(2)
        k1.metric("IS Théorique (25%)", f"{res_bic['is_theorique']:,.0f} FCFA")
        k2.metric("IS Dû (après minimum de perception)", f"{res_bic['is_du']:,.0f} FCFA")
        if 0 < res_bic["is_theorique"] < res_bic["minimum_perception"]:
            st.warning("Le minimum de perception s'applique (résultat imposable faible).")

    with tab_edition:
        contribuable = st.text_input("Raison sociale du contribuable", value="")
        periode = st.text_input("Période (ex: Septembre 2026)", value=datetime.now().strftime("%B %Y"))
        if st.button("📄 Générer la Déclaration Fiscale (PDF)", use_container_width=True):
            tva = st.session_state.get("_derniere_tva", calculer_tva(0, 0))
            bic = st.session_state.get("_dernier_bic")
            pdf_path = generer_declaration_pdf(periode, contribuable or "Non renseigné", tva, bic)
            with open(pdf_path, "rb") as f:
                st.download_button(
                    "📥 Télécharger la Déclaration (PDF)",
                    data=f.read(),
                    file_name=pdf_path,
                    mime="application/pdf",
                    use_container_width=True,
                )
