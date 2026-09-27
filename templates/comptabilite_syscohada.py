"""
comptabilite_syscohada.py — BaobabVault ERP
Moteur comptable SYSCOHADA révisé : saisie, Grand Livre, Balance,
rapprochement bancaire. Adapté du module SNDGIR, plan comptable étendu
pour couvrir les cas banque / hôpital / import-export.

À appeler depuis app.py :
    import comptabilite_syscohada as compta
    compta.render(DB_NAME, username=st.session_state.username)
"""

import sqlite3
from datetime import datetime

import pandas as pd
import streamlit as st

PLAN_COMPTABLE_SYSCOHADA = {
    "401000": "Fournisseurs",
    "411000": "Clients",
    "421000": "Personnel, rémunérations dues",
    "445200": "TVA due intracommunautaire",
    "445660": "TVA déductible sur autres biens et services",
    "445710": "TVA collectée",
    "447000": "État, autres impôts et taxes",
    "471000": "Compte d'attente débiteur",
    "521000": "Banque",
    "571000": "Caisse",
    "601000": "Achats de marchandises",
    "602000": "Achats de matières premières",
    "612000": "Transports sur achats",
    "622600": "Honoraires (banque, audit, conseil)",
    "626000": "Frais postaux et de télécommunications",
    "631000": "Impôts et taxes directs",
    "632000": "Impôts et taxes indirects (droits de douane)",
    "641000": "Rémunérations directes versées au personnel",
    "661000": "Charges d'intérêts (prêts bancaires)",
    "706000": "Services vendus (prestations bancaires / soins)",
    "707000": "Ventes de marchandises",
    "758000": "Produits divers de gestion courante",
}


def init_compta_tables(db_name: str):
    conn = sqlite3.connect(db_name)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS compta_ecritures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT, journal TEXT,
            compte_debit TEXT, libelle_debit TEXT,
            compte_credit TEXT, libelle_credit TEXT,
            montant REAL, piece_ref TEXT, lettrage TEXT DEFAULT NULL
        )
    """)
    conn.commit(); conn.close()


def _nom_compte(code: str) -> str:
    return PLAN_COMPTABLE_SYSCOHADA.get(code, "Compte non référencé")


def render(db_name: str, username: str = "système"):
    init_compta_tables(db_name)
    st.subheader("📊 Comptabilité Générale — Norme SYSCOHADA révisée")

    tab_saisie, tab_gl, tab_balance, tab_rappro = st.tabs(
        ["✍️ Saisie", "📒 Grand Livre", "⚖️ Balance", "🏦 Rapprochement Bancaire"]
    )

    with tab_saisie:
        codes = list(PLAN_COMPTABLE_SYSCOHADA.keys())
        with st.form("form_ecriture_manuelle"):
            c1, c2, c3 = st.columns(3)
            with c1:
                journal = st.selectbox("Journal", ["AC (Achats)", "VE (Ventes)", "BQ (Banque)", "CAI (Caisse)", "OD (Opérations Diverses)"])
            with c2:
                compte_debit = st.selectbox("Compte à Débiter", codes, format_func=lambda c: f"{c} — {_nom_compte(c)}")
            with c3:
                compte_credit = st.selectbox("Compte à Créditer", codes, index=1, format_func=lambda c: f"{c} — {_nom_compte(c)}")
            montant = st.number_input("Montant (FCFA)", min_value=0.0, step=1000.0)
            piece_ref = st.text_input("Référence pièce", value=f"PIECE-{datetime.now().strftime('%Y%m%d%H%M')}")
            libelle = st.text_input("Libellé", value="Opération diverse")
            if st.form_submit_button("Enregistrer l'écriture"):
                if compte_debit == compte_credit:
                    st.error("Les comptes débité et crédité doivent être différents.")
                elif montant <= 0:
                    st.error("Le montant doit être positif.")
                else:
                    conn = sqlite3.connect(db_name)
                    conn.execute(
                        """INSERT INTO compta_ecritures (date, journal, compte_debit, libelle_debit, compte_credit, libelle_credit, montant, piece_ref)
                           VALUES (?,?,?,?,?,?,?,?)""",
                        (datetime.now().strftime("%Y-%m-%d"), journal.split(" ")[0], compte_debit, libelle, compte_credit, libelle, montant, piece_ref),
                    )
                    conn.commit(); conn.close()
                    st.success(f"Débit {compte_debit} / Crédit {compte_credit} — {montant:,.0f} FCFA")

        conn = sqlite3.connect(db_name)
        df_ecr = pd.read_sql_query("SELECT * FROM compta_ecritures ORDER BY id DESC LIMIT 50", conn)
        conn.close()
        st.dataframe(df_ecr, use_container_width=True)

    with tab_gl:
        conn = sqlite3.connect(db_name)
        df_all = pd.read_sql_query("SELECT * FROM compta_ecritures", conn)
        conn.close()
        if df_all.empty:
            st.info("Aucune écriture enregistrée.")
        else:
            compte_choisi = st.selectbox(
                "Compte", sorted(set(df_all["compte_debit"]) | set(df_all["compte_credit"])),
                format_func=lambda c: f"{c} — {_nom_compte(c)}",
            )
            mvts = []
            for _, r in df_all.iterrows():
                if r["compte_debit"] == compte_choisi:
                    mvts.append({"date": r["date"], "piece": r["piece_ref"], "libellé": r["libelle_debit"], "débit": r["montant"], "crédit": 0.0})
                if r["compte_credit"] == compte_choisi:
                    mvts.append({"date": r["date"], "piece": r["piece_ref"], "libellé": r["libelle_credit"], "débit": 0.0, "crédit": r["montant"]})
            df_gl = pd.DataFrame(mvts).sort_values("date")
            df_gl["solde cumulé"] = (df_gl["débit"] - df_gl["crédit"]).cumsum()
            st.dataframe(df_gl, use_container_width=True)
            st.metric("Solde", f"{df_gl['solde cumulé'].iloc[-1]:,.0f} FCFA" if not df_gl.empty else "0 FCFA")

    with tab_balance:
        conn = sqlite3.connect(db_name)
        df_all = pd.read_sql_query("SELECT * FROM compta_ecritures", conn)
        conn.close()
        if df_all.empty:
            st.info("Aucune écriture enregistrée.")
        else:
            lignes = []
            for c in sorted(set(df_all["compte_debit"]) | set(df_all["compte_credit"])):
                td = df_all.loc[df_all["compte_debit"] == c, "montant"].sum()
                tc = df_all.loc[df_all["compte_credit"] == c, "montant"].sum()
                solde = td - tc
                lignes.append({"Compte": c, "Libellé": _nom_compte(c), "Total Débit": td, "Total Crédit": tc,
                                "Solde Débiteur": max(solde, 0), "Solde Créditeur": max(-solde, 0)})
            df_bal = pd.DataFrame(lignes)
            st.dataframe(df_bal, use_container_width=True)
            k1, k2 = st.columns(2)
            k1.metric("Total Débit", f"{df_bal['Total Débit'].sum():,.0f} FCFA")
            k2.metric("Total Crédit", f"{df_bal['Total Crédit'].sum():,.0f} FCFA")
            ecart = df_bal["Total Débit"].sum() - df_bal["Total Crédit"].sum()
            (st.success if abs(ecart) < 0.01 else st.error)(
                "✅ Balance équilibrée." if abs(ecart) < 0.01 else f"⚠️ Écart de {ecart:,.0f} FCFA."
            )

    with tab_rappro:
        st.caption("Importez un relevé bancaire (CSV : `date`, `libelle`, `montant`) pour rapprochement du compte 521000.")
        fichier = st.file_uploader("Relevé bancaire (CSV)", type=["csv"])
        conn = sqlite3.connect(db_name)
        df_banque = pd.read_sql_query("SELECT * FROM compta_ecritures WHERE compte_debit='521000' OR compte_credit='521000'", conn)
        conn.close()
        if fichier is not None:
            try:
                df_releve = pd.read_csv(fichier)
                df_releve.columns = [c.strip().lower() for c in df_releve.columns]
                st.dataframe(df_releve, use_container_width=True)
                m_livre = set(df_banque["montant"].round(2))
                m_releve = set(df_releve["montant"].round(2)) if "montant" in df_releve.columns else set()
                c1, c2, c3 = st.columns(3)
                c1.metric("Rapprochés", len(m_livre & m_releve))
                c2.metric("Livre seul", len(m_livre - m_releve))
                c3.metric("Relevé seul", len(m_releve - m_livre))
            except Exception as e:
                st.error(f"Erreur CSV : {e}")
        else:
            st.dataframe(df_banque, use_container_width=True)
