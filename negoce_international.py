"""
negoce_international.py — BaobabVault ERP
Trésorerie multi-devises (FX) + calcul du prix de revient des importations
(valeur en douane, droits, frais annexes) — cœur du besoin "négoce
international" pour une PME ivoirienne qui importe.
"""

import sqlite3
from datetime import datetime

import pandas as pd
import streamlit as st

import theme

DEVISES_USUELLES = ["XOF", "EUR", "USD", "CNY", "GBP", "MAD"]


def init_negoce_tables(db_name: str):
    conn = sqlite3.connect(db_name)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS taux_change (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            devise TEXT, taux_vers_xof REAL, date_maj TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS dossiers_import (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reference TEXT UNIQUE,
            fournisseur TEXT,
            devise_achat TEXT,
            valeur_fob REAL,
            fret REAL,
            assurance REAL,
            taux_change_utilise REAL,
            valeur_caf_xof REAL,
            droits_douane_pct REAL,
            autres_frais_xof REAL,
            quantite REAL,
            prix_revient_unitaire REAL,
            prix_revient_total REAL,
            created_at TEXT,
            created_by TEXT
        )
    """)
    conn.commit()
    conn.close()


def enregistrer_taux(db_name: str, devise: str, taux_vers_xof: float):
    init_negoce_tables(db_name)
    conn = sqlite3.connect(db_name)
    conn.execute(
        "INSERT INTO taux_change (devise, taux_vers_xof, date_maj) VALUES (?,?,?)",
        (devise, taux_vers_xof, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    )
    conn.commit()
    conn.close()


def dernier_taux(db_name: str, devise: str) -> float | None:
    if devise == "XOF":
        return 1.0
    conn = sqlite3.connect(db_name)
    row = conn.execute(
        "SELECT taux_vers_xof FROM taux_change WHERE devise=? ORDER BY id DESC LIMIT 1", (devise,)
    ).fetchone()
    conn.close()
    return row[0] if row else None


def calculer_prix_revient(valeur_fob: float, fret: float, assurance: float, taux_change: float,
                           droits_douane_pct: float, autres_frais_xof: float, quantite: float) -> dict:
    """
    Valeur CAF (Coût-Assurance-Fret) = FOB + Fret + Assurance, convertie en XOF.
    Prix de revient = Valeur CAF + Droits de douane (% de la CAF) + Autres frais
    (transit, manutention, stockage...) — méthode standard de calcul douanier OHADA/UEMOA.
    """
    valeur_caf_devise = valeur_fob + fret + assurance
    valeur_caf_xof = valeur_caf_devise * taux_change
    droits_douane_xof = valeur_caf_xof * (droits_douane_pct / 100)
    prix_revient_total = valeur_caf_xof + droits_douane_xof + autres_frais_xof
    prix_revient_unitaire = prix_revient_total / quantite if quantite > 0 else 0

    return {
        "valeur_caf_xof": round(valeur_caf_xof, 2),
        "droits_douane_xof": round(droits_douane_xof, 2),
        "prix_revient_total": round(prix_revient_total, 2),
        "prix_revient_unitaire": round(prix_revient_unitaire, 2),
    }


def render_negoce_international(db_name: str, utilisateur_courant: str):
    init_negoce_tables(db_name)
    theme.inject_apple_theme()
    st.subheader("🌐 Trésorerie FX & Négoce International")

    onglet_fx, onglet_import = st.tabs(["💱 Taux de change", "🚢 Prix de revient import"])

    with onglet_fx:
        st.markdown("##### Mettre à jour un taux de change (vers XOF)")
        with st.form("form_taux"):
            c1, c2 = st.columns(2)
            with c1:
                devise = st.selectbox("Devise", [d for d in DEVISES_USUELLES if d != "XOF"])
            with c2:
                taux = st.number_input("1 unité = ? XOF", min_value=0.0, step=0.01, format="%.4f")
            if st.form_submit_button("Enregistrer le taux", use_container_width=True):
                enregistrer_taux(db_name, devise, taux)
                st.success(f"Taux {devise}/XOF mis à jour : {taux}")

        st.markdown("##### Derniers taux connus")
        lignes = []
        for d in DEVISES_USUELLES:
            t = dernier_taux(db_name, d)
            if t:
                lignes.append({"Devise": d, "Taux vers XOF": t})
        if lignes:
            st.dataframe(pd.DataFrame(lignes), use_container_width=True)
        else:
            st.info("Aucun taux enregistré pour l'instant.")

    with onglet_import:
        st.markdown("##### Calculer le prix de revient d'un dossier d'importation")
        with st.form("form_import"):
            c1, c2, c3 = st.columns(3)
            with c1:
                reference = st.text_input("Référence dossier (ex: IMP-2026-014)")
                fournisseur = st.text_input("Fournisseur")
                devise_achat = st.selectbox("Devise d'achat", DEVISES_USUELLES)
            with c2:
                valeur_fob = st.number_input("Valeur FOB (devise)", min_value=0.0, step=1000.0)
                fret = st.number_input("Fret (devise)", min_value=0.0, step=1000.0)
                assurance = st.number_input("Assurance (devise)", min_value=0.0, step=100.0)
            with c3:
                droits_douane_pct = st.number_input("Droits de douane (%)", min_value=0.0, max_value=100.0, step=0.5)
                autres_frais_xof = st.number_input("Autres frais (XOF) — transit, manutention...", min_value=0.0, step=10000.0)
                quantite = st.number_input("Quantité importée", min_value=0.0, step=1.0, value=1.0)

            taux_actuel = dernier_taux(db_name, devise_achat) or 0.0
            st.caption(f"Taux de change utilisé : 1 {devise_achat} = {taux_actuel} XOF (dernier taux enregistré)")

            if st.form_submit_button("Calculer et enregistrer", use_container_width=True):
                if not reference:
                    st.error("La référence du dossier est obligatoire.")
                elif taux_actuel == 0:
                    st.error(f"Aucun taux de change enregistré pour {devise_achat}. Renseigne-le dans l'onglet 'Taux de change'.")
                else:
                    resultat = calculer_prix_revient(valeur_fob, fret, assurance, taux_actuel,
                                                       droits_douane_pct, autres_frais_xof, quantite)
                    conn = sqlite3.connect(db_name)
                    try:
                        conn.execute("""
                            INSERT INTO dossiers_import (reference, fournisseur, devise_achat, valeur_fob, fret,
                                assurance, taux_change_utilise, valeur_caf_xof, droits_douane_pct, autres_frais_xof,
                                quantite, prix_revient_unitaire, prix_revient_total, created_at, created_by)
                            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        """, (reference, fournisseur, devise_achat, valeur_fob, fret, assurance, taux_actuel,
                              resultat["valeur_caf_xof"], droits_douane_pct, autres_frais_xof, quantite,
                              resultat["prix_revient_unitaire"], resultat["prix_revient_total"],
                              datetime.now().strftime("%Y-%m-%d %H:%M:%S"), utilisateur_courant))
                        conn.commit()
                        st.success("Dossier enregistré.")
                        c1, c2, c3 = st.columns(3)
                        c1.markdown(theme.carte_kpi_html("Valeur CAF", f"{resultat['valeur_caf_xof']:,.0f} XOF"), unsafe_allow_html=True)
                        c2.markdown(theme.carte_kpi_html("Prix de revient total", f"{resultat['prix_revient_total']:,.0f} XOF"), unsafe_allow_html=True)
                        c3.markdown(theme.carte_kpi_html("Prix de revient unitaire", f"{resultat['prix_revient_unitaire']:,.0f} XOF"), unsafe_allow_html=True)
                    except sqlite3.IntegrityError:
                        st.error("Cette référence de dossier existe déjà.")
                    conn.close()

        st.markdown("##### Dossiers d'importation enregistrés")
        conn = sqlite3.connect(db_name)
        df = pd.read_sql_query("SELECT reference, fournisseur, devise_achat, valeur_caf_xof, prix_revient_total, prix_revient_unitaire, created_at FROM dossiers_import ORDER BY id DESC", conn)
        conn.close()
        st.dataframe(df, use_container_width=True)
