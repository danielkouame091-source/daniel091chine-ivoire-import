"""
app.py — BaobabVault ERP
Orchestrateur principal : licence machine-locked, authentification avec
verrouillage après 3 échecs + alerte, déblocage d'urgence fondateur,
changement de mot de passe forcé à la première connexion, déconnexion
automatique après inactivité, kill-switch d'urgence, et intégration
sécurité / comptabilité / traçabilité.
"""

import hashlib
import hmac
import sqlite3
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import streamlit as st

import licences
import securite_bancaire as sec
import tracabilite as tracker
import comptabilite_syscohada as compta
import alertes

st.set_page_config(page_title="BaobabVault ERP", page_icon="🛡️", layout="wide")

# ======================================================================
# CONSTANTES — DOIVENT être définies avant tout ce qui les utilise
# ======================================================================
DB_NAME = "baobabvault_core.db"
LICENCES_DB = "baobabvault_licences.db"
TIMEOUT_INACTIVITE_MINUTES = 15

licences.init_licences_tables(LICENCES_DB)


def _param_url(nom: str) -> str:
    """Lit un paramètre d'URL en gérant les deux API Streamlit (ancienne et récente)."""
    try:
        return st.query_params.get(nom, "")
    except AttributeError:
        valeurs = st.experimental_get_query_params().get(nom, [""])
        return valeurs[0] if valeurs else ""


# ======================================================================
# 0) ASSISTANT DE PREMIÈRE LICENCE — ?bootstrap=1. Se désactive tout
#    seul dès qu'une licence existe déjà en base.
# ======================================================================
if _param_url("bootstrap") == "1":
    conn = sqlite3.connect(LICENCES_DB)
    nb_licences_existantes = conn.execute("SELECT COUNT(*) FROM licences").fetchone()[0]
    conn.close()

    if nb_licences_existantes > 0:
        st.markdown(
            """<div style="max-width:600px;margin:100px auto;padding:30px;background:#1E293B;
            border:1px solid #334155;border-radius:16px;text-align:center;color:#F8FAFC;">
            <h3>ℹ️ Assistant de première licence désactivé</h3>
            <p>Une licence existe déjà en base. Utilise le panneau fondateur
            (<code>?fondateur=1</code>) pour gérer les licences existantes.</p>
            </div>""",
            unsafe_allow_html=True,
        )
        st.stop()

    st.markdown("## 🔧 Assistant de première licence")
    st.caption("Cet assistant ne s'affiche que tant qu'aucune licence n'existe en base — une fois ta première licence créée, cette page se désactive d'elle-même.")
    with st.form("form_bootstrap_licence"):
        client = st.text_input("Nom du titulaire", value="Kouassi Kouame Daniel")
        type_ab = st.selectbox("Type d'abonnement", ["annuel", "mensuel", "essai"])
        submit = st.form_submit_button("Générer la licence", use_container_width=True)
    if submit:
        cle = licences.creer_licence(LICENCES_DB, client, type_ab)
        st.success("Licence créée avec succès !")
        st.code(cle, language=None)
        st.warning(
            "Copie cette clé maintenant : va dans Manage app → Settings → Secrets "
            "et colle-la sous `LICENCE_KEY = \"...\"`. Une fois fait, recharge l'app "
            "sans le paramètre `?bootstrap=1`."
        )
    st.stop()

# ======================================================================
# 0bis) DÉBLOCAGE D'URGENCE D'UN COMPTE — ?debloquer=1. Protégé par le
#       même FOUNDER_PASSWORD que le panneau fondateur. Nécessaire car
#       un compte verrouillé après 3 échecs n'a sinon AUCUN moyen de se
#       débloquer lui-même — il faut un accès administrateur externe.
# ======================================================================
if _param_url("debloquer") == "1":
    st.markdown("## 🔓 Déblocage d'urgence d'un compte utilisateur")
    mdp_attendu = st.secrets.get("FOUNDER_PASSWORD", "") if hasattr(st, "secrets") else ""
    if not mdp_attendu:
        st.error("FOUNDER_PASSWORD n'est pas configuré dans les secrets — déblocage impossible.")
        st.stop()

    saisi = st.text_input("Mot de passe fondateur", type="password", key="debloquer_pwd")
    if not saisi:
        st.stop()
    if not hmac.compare_digest(saisi, mdp_attendu):
        st.error("Mot de passe incorrect.")
        st.stop()

    conn = sqlite3.connect(DB_NAME)
    df_users = pd.read_sql_query("SELECT username, role, statut, echecs_consecutifs FROM users", conn)
    conn.close()

    if df_users.empty:
        st.info("Aucun utilisateur en base pour l'instant.")
        st.stop()

    st.dataframe(df_users, use_container_width=True)
    compte_sel = st.selectbox("Compte à débloquer", df_users["username"].tolist())
    if st.button("🔓 Débloquer ce compte", use_container_width=True):
        conn = sqlite3.connect(DB_NAME)
        conn.execute("UPDATE users SET statut='Actif', echecs_consecutifs=0 WHERE username=?", (compte_sel,))
        conn.commit(); conn.close()
        sec.init_audit_chain(DB_NAME)
        sec.log_action_immuable(DB_NAME, "FONDATEUR", "Déblocage d'urgence", f"Compte {compte_sel} débloqué manuellement")
        st.success(f"Compte {compte_sel} débloqué. Reconnecte-toi via l'URL normale (sans paramètre).")
    st.stop()

# ======================================================================
# 1) PANNEAU FONDATEUR (route cachée ?fondateur=1) — avant tout le reste
# ======================================================================
licences.panneau_fondateur_secret(LICENCES_DB)

# ======================================================================
# 2) LICENCE MACHINE-LOCKED — bloque l'app si invalide/expirée
# ======================================================================
licences.bloc_verification_licence(LICENCES_DB)


def hash_password(pwd: str) -> str:
    return hashlib.sha256(pwd.encode()).hexdigest()


def init_db():
    conn = sqlite3.connect(DB_NAME)
    conn.execute("""CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password_hash TEXT,
        role TEXT, statut TEXT DEFAULT 'Actif', echecs_consecutifs INTEGER DEFAULT 0,
        doit_changer_mdp INTEGER DEFAULT 0
    )""")
    cols = [c[1] for c in conn.execute("PRAGMA table_info(users)").fetchall()]
    if "doit_changer_mdp" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN doit_changer_mdp INTEGER DEFAULT 0")

    conn.execute(
        "INSERT OR IGNORE INTO users (username, password_hash, role, statut, doit_changer_mdp) VALUES (?,?,?,?,1)",
        ("admin", hash_password("ChangeMoi2026!"), "Administrateur", "Actif"),
    )
    conn.commit(); conn.close()


init_db()
sec.init_audit_chain(DB_NAME)
sec.init_transactions_table(DB_NAME)
tracker.init_tracabilite_tables(DB_NAME)
compta.init_compta_tables(DB_NAME)


def envoyer_alerte_urgence(destinataire: str, message: str):
    resultat = alertes.alerte_urgence_founder(f"[{destinataire}] {message}")
    sec.log_action_immuable(
        DB_NAME, "système",
        "Alerte SMS envoyée" if resultat["succes"] else "Alerte (journalisée, SMS non envoyé)",
        f"À {destinataire} : {message} — {resultat['details']}",
    )
    return resultat["succes"]


def kill_switch_global():
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


def _regles_mot_de_passe_respectees(pwd: str) -> list[str]:
    problemes = []
    if len(pwd) < 10:
        problemes.append("au moins 10 caractères")
    if not any(c.isupper() for c in pwd):
        problemes.append("au moins une majuscule")
    if not any(c.isdigit() for c in pwd):
        problemes.append("au moins un chiffre")
    if not any(not c.isalnum() for c in pwd):
        problemes.append("au moins un caractère spécial")
    return problemes


# ======================================================================
# 3) AUTHENTIFICATION avec verrouillage après 3 échecs + alerte
# ======================================================================
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
    st.session_state.username = ""
    st.session_state.user_role = ""
    st.session_state.doit_changer_mdp = False

if not st.session_state.authenticated:
    st.markdown("## 🛡️ BaobabVault ERP — Connexion Sécurisée")
    username_input = st.text_input("Identifiant")
    password_input = st.text_input("Mot de passe", type="password")

    if st.button("Se connecter"):
        conn = sqlite3.connect(DB_NAME)
        row = conn.execute(
            "SELECT username, password_hash, role, statut, echecs_consecutifs, doit_changer_mdp FROM users WHERE username=?",
            (username_input,),
        ).fetchone()

        if not row:
            st.error("Identifiant inconnu.")
        else:
            u_name, u_hash, u_role, u_statut, echecs, doit_changer = row
            if u_statut == "Bloqué":
                st.error("🔒 Compte bloqué (trop d'échecs ou kill-switch actif). Contactez l'administrateur.")
                st.caption("Déblocage : ouvrez l'URL de l'app avec `?debloquer=1` à la fin.")
            elif hash_password(password_input) == u_hash:
                conn.execute("UPDATE users SET echecs_consecutifs=0 WHERE username=?", (u_name,))
                conn.commit()
                st.session_state.authenticated = True
                st.session_state.username = u_name
                st.session_state.user_role = u_role
                st.session_state.doit_changer_mdp = bool(doit_changer)
                st.session_state.derniere_activite = datetime.now()
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
# 3bis) CHANGEMENT DE MOT DE PASSE OBLIGATOIRE
# ======================================================================
if st.session_state.doit_changer_mdp:
    st.markdown("## 🔑 Changement de mot de passe obligatoire")
    st.warning("Ce compte utilise un mot de passe temporaire. Choisissez un mot de passe définitif avant de continuer.")
    nouveau = st.text_input("Nouveau mot de passe", type="password", key="nouveau_mdp")
    confirmation = st.text_input("Confirmer le nouveau mot de passe", type="password", key="confirmation_mdp")

    if st.button("Valider le nouveau mot de passe"):
        if nouveau != confirmation:
            st.error("Les deux mots de passe ne correspondent pas.")
        else:
            problemes = _regles_mot_de_passe_respectees(nouveau)
            if problemes:
                st.error("Le mot de passe doit contenir : " + ", ".join(problemes) + ".")
            else:
                conn = sqlite3.connect(DB_NAME)
                conn.execute(
                    "UPDATE users SET password_hash=?, doit_changer_mdp=0 WHERE username=?",
                    (hash_password(nouveau), st.session_state.username),
                )
                conn.commit(); conn.close()
                sec.log_action_immuable(DB_NAME, st.session_state.username, "Changement mot de passe", "Mot de passe temporaire remplacé")
                st.session_state.doit_changer_mdp = False
                st.success("Mot de passe mis à jour.")
                st.rerun()
    st.stop()

# ======================================================================
# 3ter) DÉCONNEXION AUTOMATIQUE APRÈS INACTIVITÉ
# ======================================================================
derniere_activite = st.session_state.get("derniere_activite")
maintenant = datetime.now()
if derniere_activite and (maintenant - derniere_activite) > timedelta(minutes=TIMEOUT_INACTIVITE_MINUTES):
    sec.log_action_immuable(DB_NAME, st.session_state.username, "Déconnexion auto", f"Inactivité > {TIMEOUT_INACTIVITE_MINUTES} min")
    st.session_state.authenticated = False
    st.warning(f"Session expirée après {TIMEOUT_INACTIVITE_MINUTES} minutes d'inactivité. Reconnectez-vous.")
    st.stop()
st.session_state.derniere_activite = maintenant

# ======================================================================
# 4) NAVIGATION
# ======================================================================
st.sidebar.markdown(f"**Utilisateur :** `{st.session_state.username}`")
st.sidebar.markdown(f"**Rôle :** `{st.session_state.user_role}`")
st.sidebar.caption(f"Déconnexion automatique après {TIMEOUT_INACTIVITE_MINUTES} min d'inactivité")

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
