"""
fiscalite_ohada.py — BaobabVault ERP
Module fiscal OHADA : TVA (déclaration et calcul), Impôt sur les Sociétés /
Impôt sur le Bénéfice Industriel et Commercial (IS/BIC), et états financiers
simplifiés (compte de résultat + bilan synthétique) dérivés directement de
la comptabilité SYSCOHADA (module comptabilite_syscohada.py).

⚠️ Limite honnête : les taux ci-dessous (TVA 18%, IS 25%) correspondent au
régime général le plus courant en zone UEMOA/Côte d'Ivoire au moment de
l'écriture, mais varient selon le pays, le secteur et le régime fiscal de
l'entreprise (réel normal / simplifié / synthétique). Ce module les
propose comme valeurs par défaut MODIFIABLES à chaque calcul — il ne
remplace pas la validation d'un expert-comptable ou d'un conseil fiscal
agréé avant toute déclaration officielle auprès de la DGI.
"""

import sqlite3
from datetime import datetime

import pandas as pd
import streamlit as st

import theme
import securite_bancaire as sec
import comptabilite_syscohada as compta

TAUX_TVA_DEFAUT = 18.0   # % — taux normal le plus répandu en zone UEMOA
TAUX_IS_DEFAUT = 25.0    # % — régime du bénéfice réel normal, cas général CI

# Comptes SYSCOHADA utilisés pour flécher la TVA (voir plan comptable par défaut)
COMPTE_TVA_COLLECTEE = "445200"
COMPTE_TVA_DEDUCTIBLE = "445220"


def init_fiscal_tables(db_name: str):
    conn = sqlite3.connect(db_name)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS declarations_tva (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            periode TEXT NOT NULL,
            tva_collectee REAL,
            tva_deductible REAL,
            tva_a_payer REAL,
            taux_utilise REAL,
            statut TEXT DEFAULT 'Brouillon',
            created_by TEXT,
            created_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS declarations_is (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exercice TEXT NOT NULL,
            chiffre_affaires REAL,
            charges_deductibles REAL,
            resultat_fiscal REAL,
            taux_utilise REAL,
            is_du REAL,
            statut TEXT DEFAULT 'Brouillon',
            created_by TEXT,
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()


# ======================================================================
# TVA
# ======================================================================
def calculer_tva_depuis_comptabilite(db_name: str) -> dict:
    """Calcule la TVA collectée/déductible directement à partir des soldes
    des comptes 4452xx du plan comptable — reflète l'activité réelle
    enregistrée en comptabilité plutôt qu'une saisie manuelle séparée."""
    tva_collectee = abs(compta.solde_compte(db_name, COMPTE_TVA_COLLECTEE))
    tva_deductible = abs(compta.solde_compte(db_name, COMPTE_TVA_DEDUCTIBLE))
    tva_a_payer = tva_collectee - tva_deductible
    return {
        "tva_collectee": round(tva_collectee, 2),
        "tva_deductible": round(tva_deductible, 2),
        "tva_a_payer": round(tva_a_payer, 2),
    }


def enregistrer_declaration_tva(db_name: str, periode: str, tva_collectee: float,
                                 tva_deductible: float, taux: float, created_by: str):
    init_fiscal_tables(db_name)
    tva_a_payer = round(tva_collectee - tva_deductible, 2)
    conn = sqlite3.connect(db_name)
    conn.execute("""
        INSERT INTO declarations_tva (periode, tva_collectee, tva_deductible, tva_a_payer, taux_utilise, created_by, created_at)
        VALUES (?,?,?,?,?,?,?)
    """, (periode, tva_collectee, tva_deductible, tva_a_payer, taux, created_by, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()
    sec.log_action_immuable(db_name, created_by, "Déclaration TVA", f"Période {periode} — TVA due {tva_a_payer:,.0f} FCFA")
    return tva_a_payer


# ======================================================================
# IS / BIC
# ======================================================================
def calculer_resultat_fiscal_depuis_comptabilite(db_name: str) -> dict:
    """Résultat fiscal simplifié = Produits (classe 7) - Charges (classe 6).
    Base de calcul avant retraitements fiscaux spécifiques (réintégrations/
    déductions extra-comptables) qu'un expert-comptable devra affiner."""
    produits = abs(compta.solde_compte(db_name, "7"))
    charges = abs(compta.solde_compte(db_name, "6"))
    resultat_fiscal = produits - charges
    return {"chiffre_affaires": round(produits, 2), "charges_deductibles": round(charges, 2), "resultat_fiscal": round(resultat_fiscal, 2)}


def enregistrer_declaration_is(db_name: str, exercice: str, chiffre_affaires: float,
                                charges_deductibles: float, taux: float, created_by: str):
    init_fiscal_tables(db_name)
    resultat_fiscal = round(chiffre_affaires - charges_deductibles, 2)
    is_du = round(max(resultat_fiscal, 0) * (taux / 100), 2)
    conn = sqlite3.connect(db_name)
    conn.execute("""
        INSERT INTO declarations_is (exercice, chiffre_affaires, charges_deductibles, resultat_fiscal, taux_utilise, is_du, created_by, created_at)
        VALUES (?,?,?,?,?,?,?,?)
    """, (exercice, chiffre_affaires, charges_deductibles, resultat_fiscal, taux, is_du, created_by, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()
    sec.log_action_immuable(db_name, created_by, "Déclaration IS/BIC", f"Exercice {exercice} — IS dû {is_du:,.0f} FCFA")
    return is_du, resultat_fiscal


# ======================================================================
# ÉTATS FINANCIERS SIMPLIFIÉS
# ======================================================================
def compte_de_resultat_simplifie(db_name: str) -> pd.DataFrame:
    conn = sqlite3.connect(db_name)
    df = pd.read_sql_query("""
        SELECT e.compte, p.libelle,
               SUM(CASE WHEN e.compte LIKE '7%' THEN e.credit - e.debit ELSE 0 END) AS produit,
               SUM(CASE WHEN e.compte LIKE '6%' THEN e.debit - e.credit ELSE 0 END) AS charge
        FROM ecritures_comptables e
        LEFT JOIN plan_comptable p ON p.compte = e.compte
        WHERE e.compte LIKE '6%' OR e.compte LIKE '7%'
        GROUP BY e.compte
        HAVING produit != 0 OR charge != 0
        ORDER BY e.compte ASC
    """, conn)
    conn.close()
    return df


def bilan_simplifie(db_name: str) -> dict:
    """Synthèse très simplifiée par grande masse du bilan (classes 1 à 5)."""
    return {
        "Ressources durables (classe 1)": compta.solde_compte(db_name, "1"),
        "Actif immobilisé (classe 2)": compta.solde_compte(db_name, "2"),
        "Stocks (classe 3)": compta.solde_compte(db_name, "3"),
        "Tiers — créances/dettes (classe 4)": compta.solde_compte(db_name, "4"),
        "Trésorerie (classe 5)": compta.solde_compte(db_name, "5"),
    }


# ======================================================================
# INTERFACE STREAMLIT
# ======================================================================
def render(db_name: str):
    init_fiscal_tables(db_name)
    theme.inject_apple_theme()
    st.subheader("🧾 Fiscalité OHADA")
    st.caption("⚠️ Base de calcul simplifiée — à valider par un expert-comptable/conseil fiscal agréé avant toute déclaration officielle.")

    username = st.session_state.get("username", "système")
    onglet_tva, onglet_is, onglet_etats = st.tabs(["💶 TVA", "🏢 IS / BIC", "📑 États financiers simplifiés"])

    # ------------------------------------------------------------------
    with onglet_tva:
        auto = calculer_tva_depuis_comptabilite(db_name)
        st.markdown("##### Calcul automatique depuis la comptabilité (comptes 445200 / 445220)")
        c1, c2, c3 = st.columns(3)
        c1.markdown(theme.carte_kpi_html("TVA collectée", f"{auto['tva_collectee']:,.0f} FCFA"), unsafe_allow_html=True)
        c2.markdown(theme.carte_kpi_html("TVA déductible", f"{auto['tva_deductible']:,.0f} FCFA"), unsafe_allow_html=True)
        c3.markdown(theme.carte_kpi_html("TVA à payer", f"{auto['tva_a_payer']:,.0f} FCFA", "" , "warning" if auto['tva_a_payer'] > 0 else "success"), unsafe_allow_html=True)

        st.markdown("---")
        st.markdown("##### Enregistrer une déclaration (période)")
        with st.form("form_tva"):
            c1, c2 = st.columns(2)
            with c1:
                periode = st.text_input("Période (ex: 2026-09)", value=datetime.now().strftime("%Y-%m"))
                taux = st.number_input("Taux de TVA (%)", value=TAUX_TVA_DEFAUT, step=0.5)
            with c2:
                tva_collectee_manuel = st.number_input("TVA collectée (FCFA)", value=auto["tva_collectee"], step=1000.0)
                tva_deductible_manuel = st.number_input("TVA déductible (FCFA)", value=auto["tva_deductible"], step=1000.0)
            if st.form_submit_button("💾 Enregistrer la déclaration TVA", use_container_width=True):
                tva_due = enregistrer_declaration_tva(db_name, periode, tva_collectee_manuel, tva_deductible_manuel, taux, username)
                st.success(f"Déclaration {periode} enregistrée — TVA due : {tva_due:,.0f} FCFA")
                st.rerun()

        conn = sqlite3.connect(db_name)
        df_tva = pd.read_sql_query("SELECT periode, tva_collectee, tva_deductible, tva_a_payer, statut, created_at FROM declarations_tva ORDER BY id DESC", conn)
        conn.close()
        st.markdown("##### Historique des déclarations")
        st.dataframe(df_tva, use_container_width=True)

    # ------------------------------------------------------------------
    with onglet_is:
        auto_is = calculer_resultat_fiscal_depuis_comptabilite(db_name)
        st.markdown("##### Calcul automatique depuis la comptabilité (classes 6 et 7)")
        c1, c2, c3 = st.columns(3)
        c1.markdown(theme.carte_kpi_html("Chiffre d'affaires / Produits", f"{auto_is['chiffre_affaires']:,.0f} FCFA"), unsafe_allow_html=True)
        c2.markdown(theme.carte_kpi_html("Charges déductibles", f"{auto_is['charges_deductibles']:,.0f} FCFA"), unsafe_allow_html=True)
        c3.markdown(theme.carte_kpi_html("Résultat fiscal", f"{auto_is['resultat_fiscal']:,.0f} FCFA", "", "success" if auto_is['resultat_fiscal'] >= 0 else "danger"), unsafe_allow_html=True)

        st.markdown("---")
        st.markdown("##### Enregistrer une déclaration IS/BIC (exercice)")
        with st.form("form_is"):
            c1, c2 = st.columns(2)
            with c1:
                exercice = st.text_input("Exercice (ex: 2026)", value=str(datetime.now().year))
                taux_is = st.number_input("Taux IS/BIC (%)", value=TAUX_IS_DEFAUT, step=0.5)
            with c2:
                ca_manuel = st.number_input("Chiffre d'affaires (FCFA)", value=auto_is["chiffre_affaires"], step=1000.0)
                charges_manuel = st.number_input("Charges déductibles (FCFA)", value=auto_is["charges_deductibles"], step=1000.0)
            if st.form_submit_button("💾 Enregistrer la déclaration IS/BIC", use_container_width=True):
                is_du, resultat = enregistrer_declaration_is(db_name, exercice, ca_manuel, charges_manuel, taux_is, username)
                st.success(f"Exercice {exercice} — Résultat fiscal {resultat:,.0f} FCFA — IS dû : {is_du:,.0f} FCFA")
                st.rerun()

        conn = sqlite3.connect(db_name)
        df_is = pd.read_sql_query("SELECT exercice, chiffre_affaires, charges_deductibles, resultat_fiscal, is_du, statut, created_at FROM declarations_is ORDER BY id DESC", conn)
        conn.close()
        st.markdown("##### Historique des déclarations")
        st.dataframe(df_is, use_container_width=True)

    # ------------------------------------------------------------------
    with onglet_etats:
        st.markdown("##### Compte de résultat simplifié")
        df_resultat = compte_de_resultat_simplifie(db_name)
        if df_resultat.empty:
            st.info("Aucune donnée comptable pour générer le compte de résultat.")
        else:
            st.dataframe(df_resultat, use_container_width=True)
            total_produits = df_resultat["produit"].sum()
            total_charges = df_resultat["charge"].sum()
            resultat_net = total_produits - total_charges
            c1, c2, c3 = st.columns(3)
            c1.markdown(theme.carte_kpi_html("Total Produits", f"{total_produits:,.0f} FCFA"), unsafe_allow_html=True)
            c2.markdown(theme.carte_kpi_html("Total Charges", f"{total_charges:,.0f} FCFA"), unsafe_allow_html=True)
            c3.markdown(theme.carte_kpi_html("Résultat net", f"{resultat_net:,.0f} FCFA", "Bénéfice" if resultat_net >= 0 else "Perte", "success" if resultat_net >= 0 else "danger"), unsafe_allow_html=True)

        st.markdown("---")
        st.markdown("##### Bilan simplifié par grande masse")
        bilan = bilan_simplifie(db_name)
        df_bilan = pd.DataFrame([{"Poste": k, "Solde (FCFA)": v} for k, v in bilan.items()])
        st.dataframe(df_bilan, use_container_width=True)
