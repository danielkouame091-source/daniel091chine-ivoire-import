"""
licences.py — BaobabVault ERP
Système de licences SaaS multi-clients : le fondateur crée des licences à
durée fixe (1 mois / 3 mois / 6 mois / 1 an / essai) depuis un panneau caché
(?fondateur=1). Chaque client se connecte sur le MÊME déploiement en
saisissant SA propre clé de licence, indépendamment des autres clients.

⚠️ Choix d'architecture assumé :
Ce déploiement est un site web PARTAGÉ (une seule URL Streamlit Cloud).
Le "machine-lock" (empreinte matérielle) n'a aucun sens ici : tous les
clients passent par le même serveur, donc une empreinte machine serait
identique pour tout le monde — elle ne distingue pas un client d'un autre,
et verrouillait de fait TOUTES les licences sur le même "poste" (le
serveur). C'est pourquoi ce fichier authentifie PAR SESSION NAVIGATEUR
(st.session_state) : chaque onglet doit saisir sa clé, comme un login
classique, et plusieurs clients peuvent être connectés simultanément avec
des clés différentes.

⚠️ Limite honnête (persistance) :
`licences.db` est un fichier SQLite local au conteneur. Sur Streamlit
Community Cloud, ce fichier peut être réinitialisé lors d'un redéploiement
ou d'un réveil du conteneur après veille prolongée. Pour ne jamais perdre
une licence créée en production, migrer cette table vers une base externe
persistante (Postgres/Supabase, Turso...). Seules les fonctions de connexion
SQLite ci-dessous seraient à remplacer — le reste de l'API ne change pas.

⚠️ Limite honnête (relances planifiées) :
Streamlit ne fait tourner aucune tâche de fond. Les relances J-7/J-3/J-1
se déclenchent quand quelqu'un OUVRE l'app et que le seuil est franchi —
pas exactement au calendrier si personne ne se connecte ce jour-là. Pour
un déclenchement calendaire garanti, ajouter un job planifié externe
(ex: GitHub Actions quotidien) interrogeant la base.
"""

import hashlib
import sqlite3
from datetime import datetime, timedelta

import streamlit as st

import alertes

# Durées proposées au fondateur lors de la création/du renouvellement d'une licence
DUREE_JOURS = {
    "1 mois": 30,
    "3 mois": 90,
    "6 mois": 180,
    "1 an": 365,
    "essai (14 jours)": 14,
}
SEUILS_RELANCE = [7, 3, 1]  # jours avant expiration

SESSION_KEY = "licence_active_key"  # clé de licence saisie pour CETTE session navigateur
SESSION_INFO = "_licence_info"      # dernier résultat de validation, mis en cache pour l'UI


# ======================================================================
# BASE DE DONNÉES
# ======================================================================
def init_licences_tables(db_name: str):
    conn = sqlite3.connect(db_name)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS licences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client TEXT,
            licence_key TEXT UNIQUE,
            type_abonnement TEXT,
            montant REAL DEFAULT 0,
            contact_telephone TEXT DEFAULT '',
            date_debut TEXT,
            date_fin TEXT,
            statut TEXT DEFAULT 'Actif',
            dernier_rappel_envoye INTEGER DEFAULT NULL
        )
    """)
    cols = [c[1] for c in conn.execute("PRAGMA table_info(licences)").fetchall()]
    migrations = [
        ("montant", "ALTER TABLE licences ADD COLUMN montant REAL DEFAULT 0"),
        ("contact_telephone", "ALTER TABLE licences ADD COLUMN contact_telephone TEXT DEFAULT ''"),
        ("dernier_rappel_envoye", "ALTER TABLE licences ADD COLUMN dernier_rappel_envoye INTEGER DEFAULT NULL"),
    ]
    for col, ddl in migrations:
        if col not in cols:
            conn.execute(ddl)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS licence_evenements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT, licence_key TEXT, evenement TEXT, details TEXT
        )
    """)
    conn.commit()
    conn.close()


def _log(db_name: str, licence_key: str, evenement: str, details: str):
    conn = sqlite3.connect(db_name)
    conn.execute(
        "INSERT INTO licence_evenements (timestamp, licence_key, evenement, details) VALUES (?,?,?,?)",
        (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), licence_key, evenement, details),
    )
    conn.commit()
    conn.close()


def creer_licence(db_name: str, client: str, type_abonnement: str, montant: float = 0.0, telephone: str = "") -> str:
    init_licences_tables(db_name)
    cle = hashlib.sha256(f"{client}{datetime.now()}".encode()).hexdigest()[:20].upper()
    debut = datetime.now()
    fin = debut + timedelta(days=DUREE_JOURS.get(type_abonnement, 30))
    conn = sqlite3.connect(db_name)
    conn.execute(
        """INSERT INTO licences (client, licence_key, type_abonnement, montant, contact_telephone, date_debut, date_fin, statut)
           VALUES (?,?,?,?,?,?,?,'Actif')""",
        (client, cle, type_abonnement, montant, telephone, debut.strftime("%Y-%m-%d"), fin.strftime("%Y-%m-%d")),
    )
    conn.commit()
    conn.close()
    _log(db_name, cle, "Création", f"Licence créée pour {client} ({type_abonnement}, {montant:,.0f} FCFA)")
    return cle


def _verifier_et_envoyer_relance(db_name: str, licence_key: str, client: str, telephone: str, jours_restants: int):
    """Envoie une relance (SMS + alerte fondateur) une seule fois par seuil J-7/J-3/J-1."""
    conn = sqlite3.connect(db_name)
    dernier = conn.execute(
        "SELECT dernier_rappel_envoye FROM licences WHERE licence_key=?", (licence_key,)
    ).fetchone()
    conn.close()
    dernier_seuil = dernier[0] if dernier else None

    for seuil in SEUILS_RELANCE:
        deja_envoye = dernier_seuil is not None and dernier_seuil <= seuil
        if jours_restants <= seuil and not deja_envoye:
            message = (
                f"⏳ BaobabVault ERP — l'abonnement de {client} expire dans "
                f"{jours_restants} jour(s). Merci de régulariser pour éviter une coupure d'accès."
            )
            if telephone:
                alertes.envoyer_sms([telephone], message)
            alertes.alerte_urgence_founder(
                f"[Relance J-{seuil}] {client} ({licence_key}) — {jours_restants} j restants."
            )
            conn = sqlite3.connect(db_name)
            conn.execute("UPDATE licences SET dernier_rappel_envoye=? WHERE licence_key=?", (seuil, licence_key))
            conn.commit()
            conn.close()
            _log(db_name, licence_key, f"Relance J-{seuil}", f"SMS envoyé à {telephone or '(aucun numéro client)'}")
            break


def verifier_licence(db_name: str, licence_key: str) -> dict:
    """
    Valide une clé de licence : existence, statut, expiration.
    Ne dépend d'AUCUNE empreinte machine — une clé = un client, quelle
    que soit la session ou l'appareil depuis lequel il se connecte.
    Déclenche aussi le kill-switch automatique si la licence vient
    d'expirer, et les relances J-7/J-3/J-1.
    """
    init_licences_tables(db_name)
    licence_key = (licence_key or "").strip().upper()
    if not licence_key:
        return {"valide": False, "message": "Aucune clé de licence saisie."}

    conn = sqlite3.connect(db_name)
    row = conn.execute(
        "SELECT client, date_fin, statut, contact_telephone FROM licences WHERE licence_key=?",
        (licence_key,),
    ).fetchone()
    conn.close()

    if not row:
        _log(db_name, licence_key, "⚠️ Clé introuvable", "Tentative de connexion avec une clé inconnue")
        return {"valide": False, "message": "Clé de licence invalide. Vérifiez votre saisie."}

    client, date_fin_str, statut, telephone = row

    if statut == "Révoqué":
        return {"valide": False, "message": "Cette licence a été révoquée. Contactez l'administrateur."}
    if statut == "Bloqué":
        return {"valide": False, "message": "Cette licence est bloquée (impayé ou anomalie signalée). Contactez l'administrateur."}

    date_fin = datetime.strptime(date_fin_str, "%Y-%m-%d")
    jours_restants = (date_fin - datetime.now()).days

    if jours_restants < 0:
        conn = sqlite3.connect(db_name)
        conn.execute("UPDATE licences SET statut='Bloqué' WHERE licence_key=? AND statut='Actif'", (licence_key,))
        conn.commit()
        conn.close()
        _log(
            db_name, licence_key, "Kill-switch auto (expiration)",
            f"Expiré depuis {abs(jours_restants)} j — accès bloqué automatiquement",
        )
        return {
            "valide": False,
            "message": f"Licence expirée depuis {abs(jours_restants)} jour(s). Contactez l'administrateur pour renouveler.",
        }

    if jours_restants <= max(SEUILS_RELANCE):
        _verifier_et_envoyer_relance(db_name, licence_key, client, telephone, jours_restants)

    return {
        "valide": True,
        "message": f"Licence active — {client}",
        "client": client,
        "jours_restants": jours_restants,
    }


# ======================================================================
# ÉCRAN DE CONNEXION CLIENT — portail pro, un login par session navigateur
# ======================================================================
def _contact_admin() -> str:
    email = st.secrets.get("ADMIN_CONTACT_EMAIL", "") if hasattr(st, "secrets") else ""
    tel = st.secrets.get("ADMIN_CONTACT_PHONE", "") if hasattr(st, "secrets") else ""
    coord = " · ".join([x for x in [email, tel] if x])
    return coord or "l'administrateur"


def _ecran_connexion_client(db_name: str, message_erreur: str | None = None):
    """Portail de connexion client — sobre, moderne, jamais d'accès admin visible.
    Bloque toujours la suite de l'app via st.stop()."""
    st.markdown(
        """
        <div style="max-width:440px;margin:70px auto 0 auto;text-align:center;">
            <div style="font-size:2.6rem;">🛡️</div>
            <h2 style="margin-bottom:4px;">BaobabVault ERP</h2>
            <p style="color:#94A3B8;margin-top:0;">Portail d'activation client</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        """<div style="max-width:440px;margin:0 auto;padding:32px 32px 8px 32px;
        background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.12);
        border-radius:20px;">""",
        unsafe_allow_html=True,
    )
    cle_saisie = st.text_input(
        "Clé de licence",
        key="cle_licence_saisie",
        placeholder="XXXXXXXXXXXXXXXXXXXX",
        help="Clé fournie par votre fournisseur BaobabVault ERP",
    )
    connecter = st.button("Activer / Se connecter", use_container_width=True, type="primary")
    st.markdown("</div>", unsafe_allow_html=True)

    erreur_a_afficher = message_erreur

    if connecter:
        resultat = verifier_licence(db_name, cle_saisie)
        if resultat["valide"]:
            st.session_state[SESSION_KEY] = cle_saisie.strip().upper()
            st.session_state[SESSION_INFO] = resultat
            _log(db_name, st.session_state[SESSION_KEY], "Connexion client", f"Session ouverte pour {resultat.get('client')}")
            st.rerun()
        else:
            erreur_a_afficher = resultat["message"]

    if erreur_a_afficher:
        st.markdown(
            f"""<div style="max-width:440px;margin:12px auto 0 auto;">""",
            unsafe_allow_html=True,
        )
        st.error(erreur_a_afficher)
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown(
        f"""<div style="max-width:440px;margin:18px auto 0 auto;text-align:center;">
        <p style="font-size:0.82rem;color:#64748B;">
        Besoin d'une licence ou problème d'activation ? Contactez {_contact_admin()}.
        </p></div>""",
        unsafe_allow_html=True,
    )
    st.stop()


def bloc_verification_licence(db_name: str) -> bool:
    """
    Point d'entrée appelé à CHAQUE run de l'app. Exige une clé de licence
    valide pour cette session navigateur. Plusieurs clients peuvent être
    connectés simultanément sur le même déploiement, chacun avec sa
    propre clé — aucune session n'interfère avec une autre.
    Revalide la clé à chaque run : si le fondateur bloque/révoque une
    licence, le client concerné est coupé dès sa prochaine interaction.
    """
    init_licences_tables(db_name)

    cle_session = st.session_state.get(SESSION_KEY, "")
    if not cle_session:
        _ecran_connexion_client(db_name)  # st.stop() interne

    resultat = verifier_licence(db_name, cle_session)
    if not resultat["valide"]:
        st.session_state.pop(SESSION_KEY, None)
        st.session_state.pop(SESSION_INFO, None)
        _ecran_connexion_client(db_name, resultat["message"])  # st.stop() interne

    st.session_state[SESSION_INFO] = resultat
    return True


def afficher_statut_licence_sidebar(db_name: str):
    info = st.session_state.get(SESSION_INFO)
    if not info:
        return
    jours = info.get("jours_restants")
    if jours is not None and jours <= 7:
        st.sidebar.warning(f"⏳ Licence expire dans {jours} jour(s).")
    else:
        suffixe = f" — {jours} j restants" if jours is not None else ""
        st.sidebar.caption(f"🔑 {info['message']}{suffixe}")


def deconnexion_licence_sidebar(db_name: str):
    """Permet de fermer la session de licence en cours (utile pour tester
    plusieurs clients dans le même onglet, ou pour un client qui change
    de clé)."""
    if st.sidebar.button("🔁 Changer de licence", use_container_width=True):
        _log(db_name, st.session_state.get(SESSION_KEY, ""), "Déconnexion client", "Session de licence fermée manuellement")
        st.session_state.pop(SESSION_KEY, None)
        st.session_state.pop(SESSION_INFO, None)
        st.rerun()


# ------------------------------------------------------------------
# PANNEAU FONDATEUR — caché, jamais dans le menu principal.
# Accès : ajouter ?fondateur=1 à l'URL, puis saisir le mot de passe
# stocké dans st.secrets["FOUNDER_PASSWORD"] (jamais en dur dans le code).
# ------------------------------------------------------------------
def panneau_fondateur_secret(db_name: str):
    params = st.query_params
    if params.get("fondateur") != "1":
        return

    st.markdown("## 🕵️ Panneau Fondateur — Supervision Totale")
    mdp_attendu = st.secrets.get("FOUNDER_PASSWORD", "") if hasattr(st, "secrets") else ""
    if not mdp_attendu:
        st.error("FOUNDER_PASSWORD n'est pas configuré dans les secrets — panneau désactivé.")
        st.stop()

    saisi = st.text_input("Mot de passe fondateur", type="password", key="fondateur_pwd")
    if saisi != mdp_attendu:
        if saisi:
            st.error("Mot de passe incorrect.")
        st.stop()

    init_licences_tables(db_name)
    import pandas as pd
    conn = sqlite3.connect(db_name)
    df = pd.read_sql_query("SELECT * FROM licences ORDER BY id DESC", conn)
    df_evt = pd.read_sql_query("SELECT * FROM licence_evenements ORDER BY id DESC LIMIT 300", conn)
    conn.close()

    st.markdown("#### 📊 Indicateurs Clés")
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Licences totales", len(df))
    k2.metric("Actives", int((df["statut"] == "Actif").sum()) if not df.empty else 0)
    k3.metric("Bloquées", int((df["statut"] == "Bloqué").sum()) if not df.empty else 0)
    k4.metric("Révoquées", int((df["statut"] == "Révoqué").sum()) if not df.empty else 0)
    k5.metric("Chiffre d'affaires cumulé", f"{df['montant'].sum():,.0f} FCFA" if not df.empty else "0 FCFA")

    anomalies = df_evt[df_evt["evenement"].str.contains("⚠️|🚨", na=False)] if not df_evt.empty else df_evt
    if not anomalies.empty:
        st.warning(f"🔍 {len(anomalies)} tentative(s) avec une clé invalide/inconnue détectée(s) dans le journal.")

    st.info(
        "ℹ️ Ce déploiement est multi-clients : plusieurs entreprises peuvent être "
        "connectées simultanément, chacune avec sa propre clé de licence. Les "
        "données métier (transactions, dossiers douane...) restent dans la base "
        "applicative de chaque session — ce panneau ne gère QUE le cycle de vie "
        "des licences (création, blocage, relance, journal d'anomalies)."
    )

    st.markdown("---")
    st.markdown("#### ➕ Créer une nouvelle licence")
    with st.form("form_nouvelle_licence_fondateur"):
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            nom_client = st.text_input("Nom du client")
        with c2:
            type_ab = st.selectbox("Durée", list(DUREE_JOURS.keys()))
        with c3:
            montant = st.number_input("Montant (FCFA)", min_value=0.0, step=10000.0)
        with c4:
            tel_client = st.text_input("Téléphone client (+225...)")
        if st.form_submit_button("Générer la licence", use_container_width=True) and nom_client:
            cle = creer_licence(db_name, nom_client, type_ab, montant, tel_client)
            st.success(f"Licence créée pour **{nom_client}** — valable {type_ab}.")
            st.code(cle, language=None)
            st.caption("Transmets cette clé au client : c'est tout ce dont il a besoin pour se connecter.")

    st.markdown("---")
    st.markdown("#### 📋 Licences existantes")
    st.dataframe(df, use_container_width=True)

    if not df.empty:
        cle_sel = st.selectbox("Licence à administrer", df["licence_key"].tolist())
        ligne = df[df["licence_key"] == cle_sel].iloc[0]
        st.caption(f"Client : **{ligne['client']}** — statut actuel : **{ligne['statut']}** — expire le {ligne['date_fin']}")

        c1, c2, c3 = st.columns(3)
        with c1:
            if st.button("⛔ Bloquer (impayé/fraude)", use_container_width=True):
                conn = sqlite3.connect(db_name)
                conn.execute("UPDATE licences SET statut='Bloqué' WHERE licence_key=?", (cle_sel,))
                conn.commit()
                conn.close()
                _log(db_name, cle_sel, "Blocage fondateur", "Bloqué manuellement par le fondateur")
                st.success("Licence bloquée — le client sera coupé dès sa prochaine action dans l'app.")
                st.rerun()
        with c2:
            if st.button("🔓 Débloquer / Réactiver", use_container_width=True):
                conn = sqlite3.connect(db_name)
                conn.execute("UPDATE licences SET statut='Actif', dernier_rappel_envoye=NULL WHERE licence_key=?", (cle_sel,))
                conn.commit()
                conn.close()
                _log(db_name, cle_sel, "Réactivation fondateur", "Réactivé manuellement")
                st.success("Licence réactivée.")
                st.rerun()
        with c3:
            if st.button("🗑️ Révoquer définitivement", use_container_width=True):
                conn = sqlite3.connect(db_name)
                conn.execute("UPDATE licences SET statut='Révoqué' WHERE licence_key=?", (cle_sel,))
                conn.commit()
                conn.close()
                _log(db_name, cle_sel, "Révocation fondateur", "Révoqué définitivement")
                st.error("Licence révoquée définitivement.")
                st.rerun()

        st.markdown("##### 🔄 Renouveler cette licence")
        c4, c5 = st.columns([2, 1])
        with c4:
            nouveau_type = st.selectbox("Nouvelle durée", list(DUREE_JOURS.keys()), key="renouv_type")
        with c5:
            st.write("")
            if st.button("Renouveler à partir d'aujourd'hui", use_container_width=True):
                debut = datetime.now()
                fin = debut + timedelta(days=DUREE_JOURS.get(nouveau_type, 30))
                conn = sqlite3.connect(db_name)
                conn.execute(
                    "UPDATE licences SET date_debut=?, date_fin=?, statut='Actif', dernier_rappel_envoye=NULL, type_abonnement=? WHERE licence_key=?",
                    (debut.strftime("%Y-%m-%d"), fin.strftime("%Y-%m-%d"), nouveau_type, cle_sel),
                )
                conn.commit()
                conn.close()
                _log(db_name, cle_sel, "Renouvellement fondateur", f"Nouvelle échéance {fin.strftime('%Y-%m-%d')} ({nouveau_type})")
                st.success("Licence renouvelée.")
                st.rerun()

    st.markdown("---")
    st.markdown("#### 🕵️ Journal Complet des Événements de Licence")
    st.dataframe(df_evt, use_container_width=True)

    st.stop()
