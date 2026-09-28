"""
comptabilite_syscohada.py — BaobabVault ERP
Comptabilité générale au format SYSCOHADA révisé : plan comptable,
saisie d'écritures en partie double, Grand Livre, Balance générale,
rapprochement bancaire simplifié.

Principe de partie double appliqué strictement : une écriture (une
"pièce") n'est enregistrée que si la somme des débits égale la somme
des crédits — sinon Streamlit refuse la validation, comme l'exigerait
n'importe quel logiciel comptable professionnel.
"""

import sqlite3
from datetime import datetime

import pandas as pd
import streamlit as st

import theme
import securite_bancaire as sec

# Plan comptable simplifié — sous-ensemble des classes SYSCOHADA révisé
# les plus courantes pour une PME. Extensible depuis l'écran "Plan comptable".
PLAN_COMPTABLE_DEFAUT = [
    ("101000", "Capital social", "1"),
    ("120000", "Résultat de l'exercice", "1"),
    ("161000", "Emprunts auprès des établissements de crédit", "1"),
    ("211000", "Immobilisations incorporelles", "2"),
    ("241000", "Matériel et outillage industriel", "2"),
    ("245000", "Matériel de transport", "2"),
    ("311000", "Marchandises", "3"),
    ("401000", "Fournisseurs", "4"),
    ("411000", "Clients", "4"),
    ("445200", "TVA due (TVA collectée)", "4"),
    ("445220", "TVA déductible sur achats", "4"),
    ("421000", "Personnel — rémunérations dues", "4"),
    ("447000", "État — Impôts sur les bénéfices (IS/BIC)", "4"),
    ("521000", "Banques locales", "5"),
    ("571000", "Caisse", "5"),
    ("601000", "Achats de marchandises", "6"),
    ("602000", "Achats de matières premières", "6"),
    ("604000", "Achats stockés — fournitures", "6"),
    ("611000", "Transports sur achats", "6"),
    ("622000", "Rémunérations d'intermédiaires", "6"),
    ("628000", "Divers services extérieurs", "6"),
    ("635000", "Impôts et taxes", "6"),
    ("641000", "Rémunérations du personnel", "6"),
    ("661000", "Charges d'intérêts", "6"),
    ("701000", "Ventes de marchandises", "7"),
    ("706000", "Prestations de services", "7"),
    ("707000", "Ventes de marchandises (revente en l'état)", "7"),
    ("771000", "Produits financiers", "7"),
]

CLASSES_LIBELLES = {
    "1": "Classe 1 — Ressources durables",
    "2": "Classe 2 — Actif immobilisé",
    "3": "Classe 3 — Stocks",
    "4": "Classe 4 — Tiers",
    "5": "Classe 5 — Trésorerie",
    "6": "Classe 6 — Charges",
    "7": "Classe 7 — Produits",
}


def init_compta_tables(db_name: str):
    conn = sqlite3.connect(db_name)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS plan_comptable (
            compte TEXT PRIMARY KEY,
            libelle TEXT NOT NULL,
            classe TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ecritures_comptables (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            piece TEXT NOT NULL,
            date_ecriture TEXT NOT NULL,
            journal TEXT NOT NULL,
            compte TEXT NOT NULL,
            libelle TEXT,
            debit REAL DEFAULT 0,
            credit REAL DEFAULT 0,
            lettrage TEXT DEFAULT NULL,
            created_by TEXT,
            created_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rapprochement_bancaire (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            compte_banque TEXT NOT NULL,
            date_releve TEXT NOT NULL,
            libelle TEXT,
            montant REAL NOT NULL,
            pointe INTEGER DEFAULT 0,
            ecriture_id INTEGER,
            created_by TEXT,
            created_at TEXT
        )
    """)
    nb = conn.execute("SELECT COUNT(*) FROM plan_comptable").fetchone()[0]
    if nb == 0:
        conn.executemany(
            "INSERT OR IGNORE INTO plan_comptable (compte, libelle, classe) VALUES (?,?,?)",
            PLAN_COMPTABLE_DEFAUT,
        )
    conn.commit()
    conn.close()


def liste_comptes(db_name: str) -> pd.DataFrame:
    conn = sqlite3.connect(db_name)
    df = pd.read_sql_query("SELECT * FROM plan_comptable ORDER BY compte ASC", conn)
    conn.close()
    return df


def ajouter_compte(db_name: str, compte: str, libelle: str, classe: str):
    conn = sqlite3.connect(db_name)
    conn.execute(
        "INSERT OR REPLACE INTO plan_comptable (compte, libelle, classe) VALUES (?,?,?)",
        (compte, libelle, classe),
    )
    conn.commit()
    conn.close()


def nouvelle_reference_piece(db_name: str, journal: str) -> str:
    conn = sqlite3.connect(db_name)
    annee = datetime.now().year
    count = conn.execute(
        "SELECT COUNT(DISTINCT piece) FROM ecritures_comptables WHERE journal=? AND piece LIKE ?",
        (journal, f"{journal}-{annee}-%"),
    ).fetchone()[0]
    conn.close()
    return f"{journal}-{annee}-{str(count + 1).zfill(4)}"


def enregistrer_ecriture(db_name: str, piece: str, date_ecriture: str, journal: str,
                          lignes: list[dict], created_by: str) -> dict:
    """
    lignes : [{"compte": str, "libelle": str, "debit": float, "credit": float}, ...]
    Refuse l'enregistrement si la partie double n'est pas respectée
    (somme des débits ≠ somme des crédits) — c'est la règle fondamentale
    de toute comptabilité en droit OHADA.
    """
    total_debit = sum(l["debit"] for l in lignes)
    total_credit = sum(l["credit"] for l in lignes)

    if round(total_debit, 2) != round(total_credit, 2):
        return {
            "ok": False,
            "message": f"⚠️ Écriture déséquilibrée : Débit {total_debit:,.0f} ≠ Crédit {total_credit:,.0f}. "
                       f"La partie double impose l'égalité stricte débit = crédit.",
        }
    if total_debit == 0:
        return {"ok": False, "message": "L'écriture ne peut pas être vide."}

    conn = sqlite3.connect(db_name)
    horodatage = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for ligne in lignes:
        if ligne["debit"] == 0 and ligne["credit"] == 0:
            continue
        conn.execute("""
            INSERT INTO ecritures_comptables (piece, date_ecriture, journal, compte, libelle, debit, credit, created_by, created_at)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (piece, date_ecriture, journal, ligne["compte"], ligne.get("libelle", ""),
              ligne["debit"], ligne["credit"], created_by, horodatage))
    conn.commit()
    conn.close()

    sec.log_action_immuable(db_name, created_by, "Écriture comptable",
                             f"Pièce {piece} ({journal}) — {total_debit:,.0f} FCFA")
    return {"ok": True, "message": f"✅ Écriture {piece} enregistrée et équilibrée."}


def grand_livre(db_name: str, compte: str) -> pd.DataFrame:
    """Retourne toutes les lignes d'un compte, triées par date, avec solde cumulé."""
    conn = sqlite3.connect(db_name)
    df = pd.read_sql_query(
        "SELECT date_ecriture, piece, journal, libelle, debit, credit FROM ecritures_comptables "
        "WHERE compte=? ORDER BY date_ecriture ASC, id ASC",
        conn, params=(compte,),
    )
    conn.close()
    if not df.empty:
        df["solde_cumule"] = (df["debit"] - df["credit"]).cumsum()
    return df


def solde_compte(db_name: str, compte_ou_prefixe: str) -> float:
    """Solde net (débit - crédit) d'un compte exact OU de tous les comptes
    commençant par un préfixe (ex: '6' = toute la classe 6 Charges)."""
    conn = sqlite3.connect(db_name)
    row = conn.execute(
        "SELECT COALESCE(SUM(debit),0) - COALESCE(SUM(credit),0) FROM ecritures_comptables WHERE compte LIKE ?",
        (f"{compte_ou_prefixe}%",),
    ).fetchone()
    conn.close()
    return row[0] or 0.0


def balance_generale(db_name: str) -> pd.DataFrame:
    """Balance générale : total débit, total crédit et solde par compte."""
    conn = sqlite3.connect(db_name)
    df = pd.read_sql_query("""
        SELECT e.compte,
               COALESCE(p.libelle, '(compte hors plan)') AS libelle,
               SUM(e.debit) AS total_debit,
               SUM(e.credit) AS total_credit,
               SUM(e.debit) - SUM(e.credit) AS solde
        FROM ecritures_comptables e
        LEFT JOIN plan_comptable p ON p.compte = e.compte
        GROUP BY e.compte
        ORDER BY e.compte ASC
    """, conn)
    conn.close()
    return df


# ======================================================================
# INTERFACE STREAMLIT
# ======================================================================
def render(db_name: str, username: str):
    init_compta_tables(db_name)
    theme.inject_apple_theme()
    st.subheader("📊 Comptabilité SYSCOHADA Révisé")

    onglet_saisie, onglet_gl, onglet_balance, onglet_rapprochement, onglet_plan = st.tabs(
        ["✍️ Saisie d'écritures", "📖 Grand Livre", "⚖️ Balance générale", "🏦 Rapprochement bancaire", "📋 Plan comptable"]
    )

    # ------------------------------------------------------------------
    with onglet_saisie:
        st.caption("Toute écriture doit respecter la partie double : total Débit = total Crédit.")
        comptes_df = liste_comptes(db_name)
        options_comptes = [f"{r.compte} — {r.libelle}" for r in comptes_df.itertuples()]

        journal = st.selectbox("Journal", ["AC (Achats)", "VE (Ventes)", "BQ (Banque)", "CA (Caisse)", "OD (Opérations diverses)"])
        code_journal = journal.split(" ")[0]
        piece_suggeree = nouvelle_reference_piece(db_name, code_journal)
        date_ecriture = st.date_input("Date de l'écriture", value=datetime.now())

        nb_lignes = st.number_input("Nombre de lignes", min_value=2, max_value=12, value=2)
        lignes = []
        total_d, total_c = 0.0, 0.0
        for i in range(int(nb_lignes)):
            c1, c2, c3, c4 = st.columns([3, 3, 1.2, 1.2])
            with c1:
                choix = st.selectbox(f"Compte {i+1}", options_comptes, key=f"cpt_{i}")
                compte = choix.split(" — ")[0]
            with c2:
                libelle_ligne = st.text_input(f"Libellé {i+1}", key=f"lib_{i}")
            with c3:
                debit = st.number_input(f"Débit {i+1}", min_value=0.0, step=1000.0, key=f"deb_{i}")
            with c4:
                credit = st.number_input(f"Crédit {i+1}", min_value=0.0, step=1000.0, key=f"cred_{i}")
            lignes.append({"compte": compte, "libelle": libelle_ligne, "debit": debit, "credit": credit})
            total_d += debit
            total_c += credit

        ecart = round(total_d - total_c, 2)
        c1, c2, c3 = st.columns(3)
        c1.markdown(theme.carte_kpi_html("Total Débit", f"{total_d:,.0f} FCFA"), unsafe_allow_html=True)
        c2.markdown(theme.carte_kpi_html("Total Crédit", f"{total_c:,.0f} FCFA"), unsafe_allow_html=True)
        c3.markdown(theme.carte_kpi_html("Écart", f"{ecart:,.0f} FCFA", "Équilibré" if ecart == 0 else "Déséquilibré", "success" if ecart == 0 else "danger"), unsafe_allow_html=True)

        piece_ref = st.text_input("Référence de la pièce", value=piece_suggeree)
        if st.button("💾 Valider l'écriture", use_container_width=True, type="primary"):
            resultat = enregistrer_ecriture(db_name, piece_ref, date_ecriture.strftime("%Y-%m-%d"), code_journal, lignes, username)
            (st.success if resultat["ok"] else st.error)(resultat["message"])
            if resultat["ok"]:
                st.rerun()

    # ------------------------------------------------------------------
    with onglet_gl:
        comptes_df = liste_comptes(db_name)
        if comptes_df.empty:
            st.info("Aucun compte défini.")
        else:
            options_comptes = [f"{r.compte} — {r.libelle}" for r in comptes_df.itertuples()]
            choix = st.selectbox("Sélectionner un compte", options_comptes, key="gl_compte")
            compte_sel = choix.split(" — ")[0]
            df_gl = grand_livre(db_name, compte_sel)
            if df_gl.empty:
                st.info("Aucun mouvement sur ce compte.")
            else:
                st.dataframe(df_gl, use_container_width=True)
                solde = df_gl["solde_cumule"].iloc[-1]
                nature = "Débiteur" if solde >= 0 else "Créditeur"
                st.markdown(theme.carte_kpi_html("Solde final", f"{abs(solde):,.0f} FCFA", nature, "success" if nature == "Débiteur" else "warning"), unsafe_allow_html=True)

    # ------------------------------------------------------------------
    with onglet_balance:
        df_balance = balance_generale(db_name)
        if df_balance.empty:
            st.info("Aucune écriture enregistrée pour l'instant.")
        else:
            st.dataframe(df_balance, use_container_width=True)
            c1, c2 = st.columns(2)
            c1.markdown(theme.carte_kpi_html("Total Débit", f"{df_balance['total_debit'].sum():,.0f} FCFA"), unsafe_allow_html=True)
            c2.markdown(theme.carte_kpi_html("Total Crédit", f"{df_balance['total_credit'].sum():,.0f} FCFA"), unsafe_allow_html=True)
            ecart_balance = round(df_balance['total_debit'].sum() - df_balance['total_credit'].sum(), 2)
            if ecart_balance != 0:
                st.error(f"⚠️ La balance n'est pas équilibrée globalement (écart {ecart_balance:,.0f} FCFA) — vérifier les écritures.")
            else:
                st.success("✅ Balance équilibrée — cohérence comptable vérifiée.")

    # ------------------------------------------------------------------
    with onglet_rapprochement:
        st.caption("Pointage manuel entre le relevé bancaire et les écritures du compte Banque (classe 5).")
        with st.form("form_releve"):
            c1, c2, c3 = st.columns(3)
            with c1:
                compte_banque = st.text_input("Compte banque", value="521000")
            with c2:
                date_releve = st.date_input("Date du mouvement")
            with c3:
                montant = st.number_input("Montant (FCFA)", step=1000.0)
            libelle_releve = st.text_input("Libellé du relevé")
            if st.form_submit_button("➕ Ajouter une ligne de relevé", use_container_width=True):
                conn = sqlite3.connect(db_name)
                conn.execute(
                    "INSERT INTO rapprochement_bancaire (compte_banque, date_releve, libelle, montant, created_by, created_at) VALUES (?,?,?,?,?,?)",
                    (compte_banque, date_releve.strftime("%Y-%m-%d"), libelle_releve, montant, username, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                )
                conn.commit()
                conn.close()
                st.success("Ligne de relevé ajoutée.")
                st.rerun()

        conn = sqlite3.connect(db_name)
        df_releve = pd.read_sql_query("SELECT * FROM rapprochement_bancaire ORDER BY date_releve DESC", conn)
        conn.close()

        if df_releve.empty:
            st.info("Aucune ligne de relevé importée.")
        else:
            st.markdown("##### Lignes à pointer")
            for _, ligne in df_releve[df_releve["pointe"] == 0].iterrows():
                c1, c2 = st.columns([4, 1])
                with c1:
                    st.write(f"{ligne['date_releve']} — {ligne['libelle']} — {ligne['montant']:,.0f} FCFA")
                with c2:
                    if st.button("✅ Pointer", key=f"pointer_{ligne['id']}"):
                        conn = sqlite3.connect(db_name)
                        conn.execute("UPDATE rapprochement_bancaire SET pointe=1 WHERE id=?", (int(ligne['id']),))
                        conn.commit()
                        conn.close()
                        st.rerun()
            st.markdown("##### Historique complet")
            st.dataframe(df_releve, use_container_width=True)

    # ------------------------------------------------------------------
    with onglet_plan:
        st.caption("Plan comptable SYSCOHADA révisé utilisé par l'entreprise — extensible.")
        with st.form("form_ajout_compte"):
            c1, c2, c3 = st.columns(3)
            with c1:
                nv_compte = st.text_input("Numéro de compte (ex: 606000)")
            with c2:
                nv_libelle = st.text_input("Libellé")
            with c3:
                nv_classe = st.selectbox("Classe", list(CLASSES_LIBELLES.keys()), format_func=lambda c: CLASSES_LIBELLES[c])
            if st.form_submit_button("➕ Ajouter au plan comptable", use_container_width=True) and nv_compte and nv_libelle:
                ajouter_compte(db_name, nv_compte.strip(), nv_libelle.strip(), nv_classe)
                st.success(f"Compte {nv_compte} ajouté.")
                st.rerun()

        st.dataframe(liste_comptes(db_name), use_container_width=True)
