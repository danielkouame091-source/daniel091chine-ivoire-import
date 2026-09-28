"""
credit_scoring.py — BaobabVault ERP
Notation de risque crédit des tiers (clients, fournisseurs, partenaires).
Modèle pondéré TRANSPARENT (pas de boîte noire) — chaque composante du
score est visible et justifiable, condition nécessaire pour qu'une banque
partenaire accepte de s'appuyer dessus en due diligence.
"""

import sqlite3
from datetime import datetime

import pandas as pd
import streamlit as st

import theme

# Pondérations du modèle — somme = 100. Ajustables si un partenaire bancaire
# impose sa propre grille (ex: méthode BCEAO/OHADA de cotation des entreprises).
PONDERATIONS = {
    "solvabilite": 30,     # capitaux propres / dettes totales
    "rentabilite": 20,     # résultat net / chiffre d'affaires
    "liquidite": 20,       # actif circulant / passif circulant (approximé si dispo)
    "anciennete": 15,      # ancienneté de la relation commerciale
    "historique_paiement": 15,  # incidents de paiement sur 24 mois
}

CLASSES_RISQUE = [
    (85, 100, "A", "Risque très faible"),
    (70, 84, "B", "Risque faible"),
    (55, 69, "C", "Risque modéré"),
    (40, 54, "D", "Risque élevé"),
    (0, 39, "E", "Risque très élevé"),
]


def init_scoring_tables(db_name: str):
    conn = sqlite3.connect(db_name)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tiers_notation (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            raison_sociale TEXT,
            secteur TEXT,
            capitaux_propres REAL,
            dettes_totales REAL,
            chiffre_affaires REAL,
            resultat_net REAL,
            actif_circulant REAL,
            passif_circulant REAL,
            anciennete_mois INTEGER,
            incidents_paiement_24m INTEGER,
            score REAL,
            classe TEXT,
            libelle_classe TEXT,
            evalue_le TEXT,
            evalue_par TEXT
        )
    """)
    conn.commit()
    conn.close()


def _score_composante(ratio: float, seuils: list[tuple[float, float]]) -> float:
    """seuils: liste de (borne_ratio, score) triée croissant — interpolation simple par palier."""
    for borne, score in seuils:
        if ratio <= borne:
            return score
    return seuils[-1][1]


def calculer_score(capitaux_propres: float, dettes_totales: float, chiffre_affaires: float,
                    resultat_net: float, actif_circulant: float, passif_circulant: float,
                    anciennete_mois: int, incidents_paiement_24m: int) -> dict:
    """Retourne le détail complet du calcul — chaque sous-score est explicité,
    aucune 'magie' : reproductible à la main par un analyste crédit bancaire."""

    # 1) Solvabilité : capitaux propres / dettes totales
    ratio_solvabilite = capitaux_propres / dettes_totales if dettes_totales > 0 else 2.0
    score_solvabilite = _score_composante(ratio_solvabilite, [
        (0.2, 20), (0.5, 50), (1.0, 75), (1.5, 90), (99, 100)
    ])

    # 2) Rentabilité : résultat net / chiffre d'affaires
    marge_nette = (resultat_net / chiffre_affaires) if chiffre_affaires > 0 else 0
    score_rentabilite = _score_composante(marge_nette, [
        (-0.05, 10), (0.0, 30), (0.05, 60), (0.10, 85), (0.99, 100)
    ])

    # 3) Liquidité : actif circulant / passif circulant
    ratio_liquidite = actif_circulant / passif_circulant if passif_circulant > 0 else 2.0
    score_liquidite = _score_composante(ratio_liquidite, [
        (0.5, 15), (0.8, 40), (1.0, 65), (1.3, 85), (99, 100)
    ])

    # 4) Ancienneté relation commerciale
    score_anciennete = _score_composante(anciennete_mois, [
        (6, 20), (12, 45), (24, 70), (48, 90), (9999, 100)
    ])

    # 5) Historique de paiement — chaque incident pèse lourd (logique bancaire)
    score_historique = max(0, 100 - (incidents_paiement_24m * 25))

    score_final = (
        score_solvabilite * PONDERATIONS["solvabilite"]
        + score_rentabilite * PONDERATIONS["rentabilite"]
        + score_liquidite * PONDERATIONS["liquidite"]
        + score_anciennete * PONDERATIONS["anciennete"]
        + score_historique * PONDERATIONS["historique_paiement"]
    ) / 100

    classe, libelle = "E", "Risque très élevé"
    for borne_min, borne_max, code, lib in CLASSES_RISQUE:
        if borne_min <= score_final <= borne_max:
            classe, libelle = code, lib
            break

    return {
        "score_final": round(score_final, 1),
        "classe": classe,
        "libelle_classe": libelle,
        "detail": {
            "Solvabilité": round(score_solvabilite, 1),
            "Rentabilité": round(score_rentabilite, 1),
            "Liquidité": round(score_liquidite, 1),
            "Ancienneté": round(score_anciennete, 1),
            "Historique paiement": round(score_historique, 1),
        },
    }


def enregistrer_notation(db_name: str, raison_sociale: str, secteur: str, evalue_par: str, **kwargs) -> dict:
    init_scoring_tables(db_name)
    resultat = calculer_score(
        kwargs["capitaux_propres"], kwargs["dettes_totales"], kwargs["chiffre_affaires"],
        kwargs["resultat_net"], kwargs["actif_circulant"], kwargs["passif_circulant"],
        kwargs["anciennete_mois"], kwargs["incidents_paiement_24m"],
    )
    conn = sqlite3.connect(db_name)
    conn.execute("""
        INSERT INTO tiers_notation (raison_sociale, secteur, capitaux_propres, dettes_totales,
            chiffre_affaires, resultat_net, actif_circulant, passif_circulant, anciennete_mois,
            incidents_paiement_24m, score, classe, libelle_classe, evalue_le, evalue_par)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        raison_sociale, secteur, kwargs["capitaux_propres"], kwargs["dettes_totales"],
        kwargs["chiffre_affaires"], kwargs["resultat_net"], kwargs["actif_circulant"],
        kwargs["passif_circulant"], kwargs["anciennete_mois"], kwargs["incidents_paiement_24m"],
        resultat["score_final"], resultat["classe"], resultat["libelle_classe"],
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"), evalue_par,
    ))
    conn.commit()
    conn.close()
    return resultat


def render_credit_scoring(db_name: str, utilisateur_courant: str):
    init_scoring_tables(db_name)
    theme.inject_apple_theme()
    st.subheader("📈 Credit Scoring — Notation du Risque Tiers")
    st.caption("Modèle pondéré transparent — chaque composante est auditable, conforme aux attentes de due diligence bancaire.")

    with st.form("form_scoring"):
        c1, c2 = st.columns(2)
        with c1:
            raison_sociale = st.text_input("Raison sociale du tiers")
            secteur = st.selectbox("Secteur d'activité", ["Import/Export", "Commerce général", "Industrie", "Services", "BTP", "Agroalimentaire", "Autre"])
            capitaux_propres = st.number_input("Capitaux propres (FCFA)", step=100000.0)
            dettes_totales = st.number_input("Dettes totales (FCFA)", step=100000.0)
            chiffre_affaires = st.number_input("Chiffre d'affaires annuel (FCFA)", step=100000.0)
        with c2:
            resultat_net = st.number_input("Résultat net (FCFA)", step=100000.0)
            actif_circulant = st.number_input("Actif circulant (FCFA)", step=100000.0)
            passif_circulant = st.number_input("Passif circulant (FCFA)", step=100000.0)
            anciennete_mois = st.number_input("Ancienneté de la relation (mois)", min_value=0, step=1)
            incidents_paiement_24m = st.number_input("Incidents de paiement (24 derniers mois)", min_value=0, step=1)

        if st.form_submit_button("Calculer et enregistrer la notation", use_container_width=True) and raison_sociale:
            resultat = enregistrer_notation(
                db_name, raison_sociale, secteur, utilisateur_courant,
                capitaux_propres=capitaux_propres, dettes_totales=dettes_totales,
                chiffre_affaires=chiffre_affaires, resultat_net=resultat_net,
                actif_circulant=actif_circulant, passif_circulant=passif_circulant,
                anciennete_mois=anciennete_mois, incidents_paiement_24m=incidents_paiement_24m,
            )
            niveau = {"A": "success", "B": "success", "C": "warning", "D": "danger", "E": "danger"}[resultat["classe"]]
            st.markdown(theme.carte_kpi_html(
                f"Score de {raison_sociale}",
                f"{resultat['score_final']} / 100 — Classe {resultat['classe']}",
                resultat["libelle_classe"], niveau,
            ), unsafe_allow_html=True)
            st.markdown("##### Détail par composante")
            st.dataframe(pd.DataFrame([resultat["detail"]]).T.rename(columns={0: "Score /100"}), use_container_width=True)

    st.markdown("---")
    st.markdown("### 📋 Historique des notations")
    conn = sqlite3.connect(db_name)
    df = pd.read_sql_query("SELECT raison_sociale, secteur, score, classe, libelle_classe, evalue_le, evalue_par FROM tiers_notation ORDER BY id DESC", conn)
    conn.close()
    st.dataframe(df, use_container_width=True)
