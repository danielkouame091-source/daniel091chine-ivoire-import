"""
app.py — BaobabVault ERP
Orchestrateur principal : licence machine-locked, authentification avec
verrouillage après 3 échecs + alerte simulée, kill-switch d'urgence,
et intégration des modules sécurité / comptabilité / traçabilité.
"""

import hashlib
import sqlite3
from datetime import datetime

import numpy as np
import pandas as pd
import streamlit as st

import licences
licences.panneau_bootstrap_licence_UNE_SEULE_FOIS(LICENCES_DB)
# --- BLOC TEMPORAIRE : à retirer une fois la licence obtenue ---
if st.query_params.get("bootstrap") == "1":
    st.markdown("## 🔧 Génération de la première licence")
    licences.init_licences_tables(LICENCES_DB)
    with st.form("form_bootstrap_temp"):
        client = st.text_input("Nom du titulaire", value="Kouassi Kouame Daniel")
        type_ab = st.selectbox("Type d'abonnement", ["annuel", "mensuel", "essai"])
        if st.form_submit_button("Générer la licence"):
            cle = licences.creer_licence(LICENCES_DB, client, type_ab)
            st.success("Licence créée avec succès !")
            st.code(cle, language=None)
            st.warning("Copie cette clé maintenant, puis supprime ce bloc de app.py.")
    st.stop()
# --- FIN BLOC TEMPORAIRE ---
import securite_bancaire as sec
import tracabilite as tracker
import comptabilite_syscohada as compta
import alertes

st.set_page_config(page_title="BaobabVault ERP", page_icon="🛡️", layout="wide")

DB_NAME = "baobabvault_core.db"
LICENCES_DB = "baobabvault_licences.db"

# ======================================================================
# 0) PANNEAU FONDATEUR (route cachée ?fondateur=1) — avant tout le reste
# ======================================================================
licences.panneau_fondateur_secret(LICENCES_DB)

# ======================================================================
# 1) LICENCE MACHINE-LOCKED
# ======================================================================
licences.bloc_verification_licence(LICENCES_DB)


def hash_password(pwd: str) -> str:
    return hashlib.sha256(pwd.encode()).hexdigest()


def init_db():
    conn = sqlite3.connect(DB_NAME)
    conn.execute("""CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password_hash TEXT,
        role TEXT, statut TEXT DEFAULT 'Actif', echecs_consecutifs INTEGER DEFAULT 0
    )""")
    for u in [("admin", hash_password("ChangeMoi2026!"), "Administrateur", "Actif")]:
        conn.execute("INSERT OR IGNORE INTO users (username, password_hash, role, statut) VALUES (?,?,?,?)", u)
    conn.commit(); conn.close()


init_db()
sec.init_audit_chain(DB_NAME)
sec.init_transactions_table(DB_NAME)
tracker.init_tracabilite_tables(DB_NAME)
compta.init_compta_tables(DB_NAME)


def envoyer_alerte_urgence(destinataire: str, message: str):
    """
    Alerte SMS réelle via Africa's Talking (voir alertes.py). Le numéro
    du titulaire du compte devrait normalement être stocké sur son
    profil utilisateur — ici, à défaut, on alerte le fondateur
    (FOUNDER_PHONE) qui pourra relayer. Ne bloque jamais l'app si
    l'API n'est pas configurée : l'alerte est alors seulement journalisée.
    """
    resultat = alertes.alerte_urgence_founder(f"[{destinataire}] {message}")
    sec.log_action_immuable(
        DB_NAME, "système",
        "Alerte SMS envoyée" if resultat["succes"] else "Alerte (journalisée, SMS non envoyé)",
        f"À {destinataire} : {message} — {resultat['details']}",
    )
    return resultat["succes"]


def kill_switch_global():
    """Gèle TOUS les comptes bancaires suivis, verrouille tous les utilisateurs, et alerte le fondateur par SMS."""
    conn = sqlite3.connect(DB_NAME)
    comptes = [r[0] for r in conn.execute("SELECT DISTINCT compte_source FROM transactions").fetchall()]
    conn.execute("UPDATE users SET statut='Bloqué'")
    conn.commit(); conn.close()
    for c in comptes:
        sec.geler_compte(DB_NAME, c, "KILL-SWITCH D'URGENCE déclenché")
    sec.log_action_immuable(DB_NAME, st.session_state.get("username", "admin"), "🚨 KILL-SWITCH", "Gel total déclenché manuellement")
    envoyer_alerte_urgence(
        st.session_state.get("username", "admin"),
        f"🚨 KILL-SWITCH déclenché sur BaobabVault ERP à {datetime.now().strftime('%Y-%m-%d %H:%M')} — {len(comptes)} compte(s) gelé(s), tous les utilisateurs verrouillés.",
    )


# ======================================================================
# 2) AUTHENTIFICATION avec verrouillage après 3 échecs + alerte
# ======================================================================
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
    st.session_state.username = ""
    st.session_state.user_role = ""

if not st.session_state.authenticated:
    st.markdown("## 🛡️ BaobabVault ERP — Connexion Sécurisée")
    username_input = st.text_input("Identifiant")
    password_input = st.text_input("Mot de passe", type="password")

    if st.button("Se connecter"):
        conn = sqlite3.connect(DB_NAME)
        row = conn.execute(
            "SELECT username, password_hash, role, statut, echecs_consecutifs FROM users WHERE username=?",
            (username_input,),
        ).fetchone()

        if not row:
            st.error("Identifiant inconnu.")
        else:
            u_name, u_hash, u_role, u_statut, echecs = row
            if u_statut == "Bloqué":
                st.error("🔒 Compte bloqué (trop d'échecs ou kill-switch actif). Contactez l'administrateur.")
            elif hash_password(password_input) == u_hash:
                conn.execute("UPDATE users SET echecs_consecutifs=0 WHERE username=?", (u_name,))
                conn.commit()
                st.session_state.authenticated = True
                st.session_state.username = u_name
                st.session_state.user_role = u_role
                sec.log_action_immuable(DB_NAME, u_name, "Connexion", "Accès accordé")
                st.rerun()
            else:
                nouveaux_echecs = echecs + 1
                if nouveaux_echecs >= 3:
                    conn.execute("UPDATE users SET statut='Bloqué', echecs_consecutifs=? WHERE username=?", (nouveaux_echecs, u_name))
                    envoyer_alerte_urgence(u_name, f"⚠️ 3 échecs de connexion consécutifs sur le compte {u_name} — compte verrouillé.")
                    st.error("🔒 3 échecs atteints — compte verrouillé et alerte envoyée au titulaire.")
                else:
                    conn.execute("UPDATE users SET echecs_consecutifs=? WHERE username=?", (nouveaux_echecs, u_name))
                    st.error(f"Mot de passe incorrect ({nouveaux_echecs}/3 avant verrouillage).")
                conn.commit()
                sec.log_action_immuable(DB_NAME, u_name, "Échec connexion", f"Tentative {nouveaux_echecs}/3")
        conn.close()
    st.stop()

# ======================================================================
# 3) NAVIGATION
# ======================================================================
st.sidebar.markdown(f"**Utilisateur :** `{st.session_state.username}`")
st.sidebar.markdown(f"**Rôle :** `{st.session_state.user_role}`")

with st.sidebar.expander("🚨 Zone d'urgence"):
    st.caption("Gèle tous les comptes suivis et verrouille tous les utilisateurs.")
    confirmer = st.checkbox("Je confirme vouloir tout geler immédiatement")
    if st.button("🛑 KILL-SWITCH — TOUT GELER", disabled=not confirmer, use_container_width=True):
        kill_switch_global()
        st.error("Kill-switch déclenché. Tous les comptes et utilisateurs sont gelés.")

if st.sidebar.button("Déconnexion"):
    sec.log_action_immuable(DB_NAME, st.session_state.username, "Déconnexion", "Fin de session")
    st.session_state.authenticated = False
    st.rerun()

page = st.sidebar.radio("Navigation", [
    "📈 Tableau de Bord", "📊 Comptabilité SYSCOHADA", "🕸️ Sécurité & AML",
    "🌍 Traçabilité & Crédit Doc.", "🔗 Audit Immuable",
])

st.title("🛡️ BaobabVault ERP")

if page == "📈 Tableau de Bord":
    st.subheader("Vue d'ensemble")
    conn = sqlite3.connect(DB_NAME)
    df_tx = pd.read_sql_query("SELECT * FROM transactions", conn)
    conn.close()
    if df_tx.empty:
        st.info("Aucune transaction enregistrée pour l'instant.")
    else:
        df_tx["timestamp"] = pd.to_datetime(df_tx["timestamp"])
        df_tx["mois"] = df_tx["timestamp"].dt.to_period("M").astype(str)
        totaux = df_tx.groupby("mois")["montant"].sum().reset_index()
        st.bar_chart(totaux.set_index("mois"))

        st.caption(
            "📊 Projection simple par régression linéaire sur l'historique — "
            "outil d'aide à la lecture, pas un modèle d'IA prédictif validé."
        )
        if len(totaux) >= 2:
            x = np.arange(len(totaux))
            coeffs = np.polyfit(x, totaux["montant"], 1)
            projection = np.polyval(coeffs, len(totaux))
            st.metric("Projection du mois suivant (tendance linéaire)", f"{projection:,.0f} FCFA")

    st.markdown("---")
    st.subheader("➕ Enregistrer une transaction (démo)")
    with st.form("form_tx"):
        c1, c2, c3 = st.columns(3)
        with c1: source = st.text_input("Compte source", value="CI-0001")
        with c2: dest = st.text_input("Compte destination", value="CI-0002")
        with c3: montant = st.number_input("Montant (FCFA)", min_value=0.0, step=10000.0)
        if st.form_submit_button("Enregistrer"):
            if sec.compte_est_gele(DB_NAME, source):
                st.error(f"⛔ Le compte {source} est gelé — transaction refusée.")
            else:
                sec.enregistrer_transaction(DB_NAME, source, dest, montant)
                sec.log_action_immuable(DB_NAME, st.session_state.username, "Transaction", f"{source} → {dest} : {montant:,.0f}")
                st.success("Transaction enregistrée.")

elif page == "📊 Comptabilité SYSCOHADA":
    compta.render(DB_NAME, username=st.session_state.username)

elif page == "🕸️ Sécurité & AML":
    sec.render_module_amls(DB_NAME)
    st.markdown("---")
    conn = sqlite3.connect(DB_NAME)
    df_geles = pd.read_sql_query("SELECT * FROM comptes_geles", conn)
    conn.close()
    st.subheader("🧊 Comptes actuellement gelés")
    st.dataframe(df_geles, use_container_width=True)

elif page == "🌍 Traçabilité & Crédit Doc.":
    tracker.render_module_tracabilite(DB_NAME)

elif page == "🔗 Audit Immuable":
    st.subheader("Piste d'Audit Infalsifiable")
    if st.button("🔍 Vérifier l'intégrité de la chaîne"):
        ok, msg = sec.verifier_integrite_audit(DB_NAME)
        (st.success if ok else st.error)(msg)
    conn = sqlite3.connect(DB_NAME)
    df_audit = pd.read_sql_query("SELECT id, timestamp, username, action, details FROM audit_chain ORDER BY id DESC LIMIT 200", conn)
    conn.close()
    st.dataframe(df_audit, use_container_width=True)
