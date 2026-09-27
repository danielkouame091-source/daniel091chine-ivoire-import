"""
comptabilite_syscohada.py — Module Comptabilité & Finances (SYSCOHADA révisé)

Fournit :
- Plan comptable simplifié SYSCOHADA (classes 1 à 7)
- Saisie manuelle d'écritures (journal général) avec contrôle d'équilibre
- Grand Livre (par compte)
- Balance générale (débit / crédit / solde)
- Rapprochement bancaire simplifié (import CSV du relevé + lettrage)

À appeler depuis app.py :

    import comptabilite_syscohada as compta
    with tab_compta:
        compta.render(DB_NAME)
"""

import sqlite3
from datetime import datetime

import pandas as pd
import streamlit as st

# ---------------------------------------------------------------------
# Plan comptable SYSCOHADA (extrait — les classes utiles à un ERP
# douane/transit/import-export). À étendre selon ton secteur.
# ---------------------------------------------------------------------
PLAN_COMPTABLE_SYSCOHADA = {
    "401000": "Fournisseurs",
    "411000": "Clients",
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
    "626000": "Frais postaux et de télécommunications",
    "631000": "Impôts et taxes directs",
    "632000": "Impôts et taxes indirects (droits de douane)",
    "641000": "Rémunérations directes versées au personnel",
    "706000": "Services vendus (prestations de transit)",
    "707000": "Ventes de marchandises",
}


def init_compta_tables(db_name: str):
    """Idempotent — appelle-le une fois au démarrage, en plus de init_db()."""
    conn = sqlite3.connect(db_name)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS compta_ecritures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            journal TEXT,
            compte_debit TEXT,
            libelle_debit TEXT,
            compte_credit TEXT,
            libelle_credit TEXT,
            montant REAL,
            piece_ref TEXT,
            lettrage TEXT DEFAULT NULL
        )
    """)
    # migration douce si la table existait déjà sans la colonne lettrage
    cols = [c[1] for c in conn.execute("PRAGMA table_info(compta_ecritures)").fetchall()]
    if "lettrage" not in cols:
        conn.execute("ALTER TABLE compta_ecritures ADD COLUMN lettrage TEXT DEFAULT NULL")
    conn.commit()
    conn.close()


def _nom_compte(code: str) -> str:
    return PLAN_COMPTABLE_SYSCOHADA.get(code, "Compte non référencé")


def render(db_name: str, username: str = "système"):
    init_compta_tables(db_name)

    st.subheader("📊 Comptabilité Générale — Norme SYSCOHADA révisée")

    sous_tabs = st.tabs(["✍️ Saisie", "📒 Grand Livre", "⚖️ Balance", "🏦 Rapprochement Bancaire"])
    tab_saisie, tab_gl, tab_balance, tab_rappro = sous_tabs

    # ---------------- SAISIE ----------------
    with tab_saisie:
        st.markdown("##### Nouvelle écriture (journal général)")
        codes = list(PLAN_COMPTABLE_SYSCOHADA.keys())
        with st.form("form_ecriture_manuelle"):
            c1, c2, c3 = st.columns(3)
            with c1:
                journal = st.selectbox("Journal", ["AC (Achats)", "VE (Ventes)", "BQ (Banque)", "CAI (Caisse)", "OD (Opérations Diverses)"])
            with c2:
                compte_debit = st.selectbox("Compte à Débiter", codes, format_func=lambda c: f"{c} — {_nom_compte(c)}")
            with c3:
                compte_credit = st.selectbox("Compte à Créditer", codes, index=min(1, len(codes) - 1), format_func=lambda c: f"{c} — {_nom_compte(c)}")
            montant = st.number_input("Montant (FCFA)", min_value=0.0, step=1000.0)
            piece_ref = st.text_input("Référence pièce justificative", value=f"PIECE-{datetime.now().strftime('%Y%m%d%H%M')}")
            libelle = st.text_input("Libellé de l'opération", value="Opération diverse")
            submit = st.form_submit_button("Enregistrer l'écriture")

        if submit:
            if compte_debit == compte_credit:
                st.error("Le compte débité et le compte crédité doivent être différents.")
            elif montant <= 0:
                st.error("Le montant doit être strictement positif.")
            else:
                conn = sqlite3.connect(db_name)
                conn.execute(
                    """INSERT INTO compta_ecritures
                       (date, journal, compte_debit, libelle_debit, compte_credit, libelle_credit, montant, piece_ref)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (datetime.now().strftime("%Y-%m-%d"), journal.split(" ")[0], compte_debit, libelle, compte_credit, libelle, montant, piece_ref),
                )
                conn.commit()
                conn.close()
                st.success(f"Écriture enregistrée : Débit {compte_debit} / Crédit {compte_credit} — {montant:,.0f} FCFA")

        conn = sqlite3.connect(db_name)
        df_ecr = pd.read_sql_query("SELECT * FROM compta_ecritures ORDER BY id DESC LIMIT 50", conn)
        conn.close()
        st.markdown("##### Dernières écritures")
        st.dataframe(df_ecr, use_container_width=True)

    # ---------------- GRAND LIVRE ----------------
    with tab_gl:
        conn = sqlite3.connect(db_name)
        df_all = pd.read_sql_query("SELECT * FROM compta_ecritures", conn)
        conn.close()

        if df_all.empty:
            st.info("Aucune écriture comptable enregistrée.")
        else:
            compte_choisi = st.selectbox(
                "Sélectionner un compte",
                sorted(set(df_all["compte_debit"]) | set(df_all["compte_credit"])),
                format_func=lambda c: f"{c} — {_nom_compte(c)}",
            )
            mouvements = []
            for _, r in df_all.iterrows():
                if r["compte_debit"] == compte_choisi:
                    mouvements.append({"date": r["date"], "piece": r["piece_ref"], "libellé": r["libelle_debit"], "débit": r["montant"], "crédit": 0.0})
                if r["compte_credit"] == compte_choisi:
                    mouvements.append({"date": r["date"], "piece": r["piece_ref"], "libellé": r["libelle_credit"], "débit": 0.0, "crédit": r["montant"]})

            df_gl = pd.DataFrame(mouvements).sort_values("date")
            df_gl["solde cumulé"] = (df_gl["débit"] - df_gl["crédit"]).cumsum()
            st.markdown(f"##### Grand Livre — {compte_choisi} ({_nom_compte(compte_choisi)})")
            st.dataframe(df_gl, use_container_width=True)
            st.metric("Solde du compte", f"{df_gl['solde cumulé'].iloc[-1]:,.0f} FCFA" if not df_gl.empty else "0 FCFA")

    # ---------------- BALANCE ----------------
    with tab_balance:
        conn = sqlite3.connect(db_name)
        df_all = pd.read_sql_query("SELECT * FROM compta_ecritures", conn)
        conn.close()

        if df_all.empty:
            st.info("Aucune écriture comptable enregistrée.")
        else:
            comptes = sorted(set(df_all["compte_debit"]) | set(df_all["compte_credit"]))
            lignes = []
            for c in comptes:
                total_debit = df_all.loc[df_all["compte_debit"] == c, "montant"].sum()
                total_credit = df_all.loc[df_all["compte_credit"] == c, "montant"].sum()
                solde = total_debit - total_credit
                lignes.append({
                    "Compte": c,
                    "Libellé": _nom_compte(c),
                    "Total Débit": total_debit,
                    "Total Crédit": total_credit,
                    "Solde Débiteur": solde if solde > 0 else 0,
                    "Solde Créditeur": -solde if solde < 0 else 0,
                })
            df_balance = pd.DataFrame(lignes)
            st.markdown("##### Balance Générale")
            st.dataframe(df_balance, use_container_width=True)

            k1, k2 = st.columns(2)
            k1.metric("Total Débit", f"{df_balance['Total Débit'].sum():,.0f} FCFA")
            k2.metric("Total Crédit", f"{df_balance['Total Crédit'].sum():,.0f} FCFA")
            ecart = df_balance["Total Débit"].sum() - df_balance["Total Crédit"].sum()
            if abs(ecart) > 0.01:
                st.error(f"⚠️ Balance déséquilibrée : écart de {ecart:,.0f} FCFA. Vérifier les écritures.")
            else:
                st.success("✅ Balance équilibrée (Débit = Crédit).")

    # ---------------- RAPPROCHEMENT BANCAIRE ----------------
    with tab_rappro:
        st.markdown("##### Rapprochement Bancaire — Compte 521000")
        st.caption("Importez un relevé bancaire (CSV : colonnes `date`, `libelle`, `montant`) pour le confronter aux écritures du compte Banque.")

        fichier_releve = st.file_uploader("Relevé bancaire (CSV)", type=["csv"])
        conn = sqlite3.connect(db_name)
        df_banque = pd.read_sql_query(
            "SELECT * FROM compta_ecritures WHERE compte_debit='521000' OR compte_credit='521000'", conn
        )
        conn.close()

        if fichier_releve is not None:
            try:
                df_releve = pd.read_csv(fichier_releve)
                df_releve.columns = [c.strip().lower() for c in df_releve.columns]
                st.markdown("###### Relevé importé")
                st.dataframe(df_releve, use_container_width=True)

                st.markdown("###### Rapprochement automatique par montant exact")
                montants_livre = set(df_banque["montant"].round(2))
                montants_releve = set(df_releve["montant"].round(2)) if "montant" in df_releve.columns else set()
                matches = montants_livre & montants_releve
                only_livre = montants_livre - montants_releve
                only_releve = montants_releve - montants_livre

                c1, c2, c3 = st.columns(3)
                c1.metric("Montants rapprochés", len(matches))
                c2.metric("En attente (livre uniquement)", len(only_livre))
                c3.metric("En attente (relevé uniquement)", len(only_releve))

                if only_livre:
                    st.warning(f"Écritures comptables sans correspondance bancaire : {sorted(only_livre)}")
                if only_releve:
                    st.warning(f"Mouvements bancaires sans écriture comptable : {sorted(only_releve)}")
            except Exception as e:
                st.error(f"Erreur de lecture du CSV : {e}")
        else:
            st.markdown("###### Écritures du compte Banque (521000)")
            st.dataframe(df_banque, use_container_width=True)
