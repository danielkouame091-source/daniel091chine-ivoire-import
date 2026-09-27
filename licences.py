"""
licences.py — BaobabVault ERP
Licence liée à l'empreinte matérielle (machine-locked) + panneau
administrateur "fondateur" caché pour révoquer/bloquer à distance.

Mise à jour sécurité :
- Comparaison du mot de passe fondateur à temps constant (hmac.compare_digest)
  au lieu de `==`/`!=`, pour éviter les attaques par mesure de timing.
- Verrouillage du panneau fondateur après 3 échecs consécutifs, pendant
  15 minutes (persisté en base, donc résistant à un simple rechargement
  de page ou une nouvelle session de navigateur).

⚠️ Limite honnête : comme pour tout schéma SQLite embarqué dans le même
process que l'app cliente, un client avec accès shell au conteneur
pourrait théoriquement altérer sa propre ligne. Pour une vraie séparation
fournisseur/client en production, la table `licences` doit vivre sur un
serveur central à toi (API HTTPS séparée), pas dans le déploiement du
client. Le code ci-dessous est une base fonctionnelle, pas une preuve
d'inviolabilité absolue.
"""

import hashlib
import hmac
import platform
import sqlite3
import uuid
from datetime import datetime, timedelta

import streamlit as st

DUREE_JOURS = {"mensuel": 30, "annuel": 365, "essai": 14}
SEUIL_TENTATIVES_FONDATEUR = 3
DUREE_VERROUILLAGE_MINUTES = 15


def empreinte_machine() -> str:
    """
    Empreinte stable de la machine hôte (nœud réseau + adresse MAC + OS).
    Ne collecte rien d'autre — sert uniquement à lier une licence payante
    à un poste précis, pratique standard des logiciels commerciaux.
    """
    brut = f"{platform.node()}|{uuid.getnode()}|{platform.system()}|{platform.machine()}"
    return hashlib.sha256(brut.encode("utf-8")).hexdigest()[:32]


def init_licences_tables(db_name: str):
    conn = sqlite3.connect(db_name)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS licences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client TEXT,
            licence_key TEXT UNIQUE,
            type_abonnement TEXT,
            empreinte_machine TEXT,
            date_debut TEXT,
            date_fin TEXT,
            statut TEXT DEFAULT 'Actif'
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS licence_evenements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT, licence_key TEXT, evenement TEXT, details TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fondateur_securite (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            tentatives INTEGER DEFAULT 0,
            verrouille_jusqua TEXT
        )
    """)
    conn.execute("INSERT OR IGNORE INTO fondateur_securite (id, tentatives, verrouille_jusqua) VALUES (1, 0, NULL)")
    conn.commit()
    conn.close()


def _log(db_name, licence_key, evenement, details):
    conn = sqlite3.connect(db_name)
    conn.execute(
        "INSERT INTO licence_evenements (timestamp, licence_key, evenement, details) VALUES (?,?,?,?)",
        (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), licence_key, evenement, details),
    )
    conn.commit(); conn.close()


def creer_licence(db_name: str, client: str, type_abonnement: str) -> str:
    init_licences_tables(db_name)
    cle = hashlib.sha256(f"{client}{datetime.now()}".encode()).hexdigest()[:20].upper()
    debut = datetime.now(); fin = debut + timedelta(days=DUREE_JOURS.get(type_abonnement, 30))
    conn = sqlite3.connect(db_name)
    conn.execute(
        "INSERT INTO licences (client, licence_key, type_abonnement, date_debut, date_fin, statut) VALUES (?,?,?,?,?,'Actif')",
        (client, cle, type_abonnement, debut.strftime("%Y-%m-%d"), fin.strftime("%Y-%m-%d")),
    )
    conn.commit(); conn.close()
    _log(db_name, cle, "Création", f"Licence créée pour {client}")
    return cle


def verifier_licence_machine(db_name: str, licence_key: str) -> dict:
    """
    Vérifie la licence ET verrouille/vérifie l'empreinte machine.
    Première utilisation → lie automatiquement la licence à cette machine.
    Machine différente ensuite → refus (transfert doit passer par le
    panneau fondateur, pas être auto-géré par le client).
    """
    init_licences_tables(db_name)
    if not licence_key:
        return {"valide": False, "message": "Aucune clé de licence configurée."}

    empreinte_actuelle = empreinte_machine()
    conn = sqlite3.connect(db_name)
    row = conn.execute(
        "SELECT client, date_fin, statut, empreinte_machine FROM licences WHERE licence_key=?", (licence_key,)
    ).fetchone()

    if not row:
        conn.close()
        _log(db_name, licence_key, "⚠️ Clé introuvable", f"Tentative depuis machine {empreinte_actuelle}")
        return {"valide": False, "message": "Clé de licence introuvable."}

    client, date_fin_str, statut, empreinte_liee = row

    if statut == "Révoqué":
        conn.close()
        return {"valide": False, "message": f"Licence révoquée pour {client}. Contactez le fournisseur."}
    if statut == "Bloqué":
        conn.close()
        return {"valide": False, "message": f"Licence bloquée (impayé/fraude signalée) pour {client}."}

    if empreinte_liee is None:
        conn.execute("UPDATE licences SET empreinte_machine=? WHERE licence_key=?", (empreinte_actuelle, licence_key))
        conn.commit()
        _log(db_name, licence_key, "Activation machine", f"Liée à l'empreinte {empreinte_actuelle}")
    elif empreinte_liee != empreinte_actuelle:
        conn.close()
        _log(db_name, licence_key, "🚨 Machine non autorisée", f"Empreinte reçue {empreinte_actuelle} ≠ empreinte liée {empreinte_liee}")
        return {"valide": False, "message": "Cette licence est déjà activée sur une autre machine. Contactez le fournisseur pour un transfert."}

    date_fin = datetime.strptime(date_fin_str, "%Y-%m-%d")
    jours_restants = (date_fin - datetime.now()).days
    conn.close()

    if jours_restants < 0:
        return {"valide": False, "message": f"Licence expirée depuis {abs(jours_restants)} jour(s)."}

    return {"valide": True, "message": f"Licence active — {client}", "jours_restants": jours_restants}


def bloc_verification_licence(db_name: str) -> bool:
    licence_key = st.secrets.get("LICENCE_KEY", "") if hasattr(st, "secrets") else ""
    resultat = verifier_licence_machine(db_name, licence_key)
    if not resultat["valide"]:
        st.markdown(
            f"""<div style="max-width:600px;margin:100px auto;padding:30px;background:#1E293B;
            border:1px solid #7F1D1D;border-radius:16px;text-align:center;color:#F8FAFC;">
            <h2 style="color:#F87171;">🔒 Accès Verrouillé</h2><p>{resultat['message']}</p></div>""",
            unsafe_allow_html=True,
        )
        st.stop()
    elif resultat.get("jours_restants", 999) <= 7:
        st.sidebar.warning(f"⏳ Licence expire dans {resultat['jours_restants']} jour(s).")
    return True


# ------------------------------------------------------------------
# SÉCURITÉ DU PANNEAU FONDATEUR — verrouillage après 3 échecs
# ------------------------------------------------------------------
def _etat_securite_fondateur(db_name: str):
    init_licences_tables(db_name)
    conn = sqlite3.connect(db_name)
    row = conn.execute("SELECT tentatives, verrouille_jusqua FROM fondateur_securite WHERE id=1").fetchone()
    conn.close()
    return row  # (tentatives, verrouille_jusqua_str_ou_None)


def _reinitialiser_securite_fondateur(db_name: str):
    conn = sqlite3.connect(db_name)
    conn.execute("UPDATE fondateur_securite SET tentatives=0, verrouille_jusqua=NULL WHERE id=1")
    conn.commit(); conn.close()


def _enregistrer_echec_fondateur(db_name: str) -> tuple[int, str | None]:
    tentatives, _ = _etat_securite_fondateur(db_name)
    tentatives += 1
    verrou = None
    if tentatives >= SEUIL_TENTATIVES_FONDATEUR:
        verrou = (datetime.now() + timedelta(minutes=DUREE_VERROUILLAGE_MINUTES)).strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(db_name)
    conn.execute("UPDATE fondateur_securite SET tentatives=?, verrouille_jusqua=? WHERE id=1", (tentatives, verrou))
    conn.commit(); conn.close()
    return tentatives, verrou


# ------------------------------------------------------------------
# PANNEAU FONDATEUR — caché, jamais dans le menu principal.
# Accès : ajouter ?fondateur=1 à l'URL, puis saisir le mot de passe
# stocké dans st.secrets["FOUNDER_PASSWORD"] (jamais en dur dans le code).
# ------------------------------------------------------------------
def panneau_fondateur_secret(db_name: str):
    try:
        params = st.query_params
        actif = params.get("fondateur") == "1"
    except AttributeError:
        actif = st.experimental_get_query_params().get("fondateur", [""])[0] == "1"
    if not actif:
        return  # route cachée : ne s'affiche que si le paramètre est présent

    st.markdown("## 🕵️ Panneau Fondateur — Contrôle Total des Licences")
    mdp_attendu = st.secrets.get("FOUNDER_PASSWORD", "") if hasattr(st, "secrets") else ""
    if not mdp_attendu:
        st.error("FOUNDER_PASSWORD n'est pas configuré dans les secrets — panneau désactivé.")
        st.stop()

    tentatives, verrouille_jusqua = _etat_securite_fondateur(db_name)
    if verrouille_jusqua:
        fin_verrou = datetime.strptime(verrouille_jusqua, "%Y-%m-%d %H:%M:%S")
        if datetime.now() < fin_verrou:
            minutes_restantes = int((fin_verrou - datetime.now()).total_seconds() / 60) + 1
            st.error(f"🔒 Panneau verrouillé après {SEUIL_TENTATIVES_FONDATEUR} échecs. Réessayez dans {minutes_restantes} minute(s).")
            _log(db_name, "FONDATEUR", "🚨 Tentative pendant verrouillage", f"Accès refusé — verrouillé jusqu'à {verrouille_jusqua}")
            st.stop()
        else:
            _reinitialiser_securite_fondateur(db_name)

    saisi = st.text_input("Mot de passe fondateur", type="password", key="fondateur_pwd")
    if saisi:
        # Comparaison à temps constant : évite qu'un attaquant déduise le
        # mot de passe en mesurant le temps de réponse caractère par caractère.
        if hmac.compare_digest(saisi, mdp_attendu):
            _reinitialiser_securite_fondateur(db_name)
        else:
            nouvelles_tentatives, verrou = _enregistrer_echec_fondateur(db_name)
            _log(db_name, "FONDATEUR", "⚠️ Échec mot de passe", f"Tentative {nouvelles_tentatives}/{SEUIL_TENTATIVES_FONDATEUR}")
            if verrou:
                st.error(f"🔒 {SEUIL_TENTATIVES_FONDATEUR} échecs atteints — panneau verrouillé {DUREE_VERROUILLAGE_MINUTES} minutes.")
            else:
                st.error(f"Mot de passe incorrect ({nouvelles_tentatives}/{SEUIL_TENTATIVES_FONDATEUR} avant verrouillage).")
            st.stop()
    else:
        st.stop()

    init_licences_tables(db_name)
    import pandas as pd
    conn = sqlite3.connect(db_name)
    df = pd.read_sql_query("SELECT * FROM licences ORDER BY id DESC", conn)
    conn.close()
    st.dataframe(df, use_container_width=True)

    st.markdown("---")
    st.markdown("##### ➕ Créer une nouvelle licence")
    with st.form("form_nouvelle_licence_fondateur"):
        client_nom = st.text_input("Nom du client")
        type_ab = st.selectbox("Type d'abonnement", ["annuel", "mensuel", "essai"])
        if st.form_submit_button("Générer"):
            cle = creer_licence(db_name, client_nom, type_ab)
            st.success(f"Licence créée pour {client_nom}")
            st.code(cle, language=None)

    if not df.empty:
        st.markdown("---")
        st.markdown("##### ⚙️ Administrer une licence existante")
        cle_sel = st.selectbox("Licence à administrer", df["licence_key"].tolist())
        c1, c2, c3 = st.columns(3)
        with c1:
            if st.button("⛔ Bloquer (impayé/fraude)", use_container_width=True):
                conn = sqlite3.connect(db_name)
                conn.execute("UPDATE licences SET statut='Bloqué' WHERE licence_key=?", (cle_sel,))
                conn.commit(); conn.close()
                _log(db_name, cle_sel, "Blocage fondateur", "Bloqué manuellement par le fondateur")
                st.success("Licence bloquée. Le client sera coupé à sa prochaine ouverture d'app.")
        with c2:
            if st.button("🔓 Débloquer / Réactiver", use_container_width=True):
                conn = sqlite3.connect(db_name)
                conn.execute("UPDATE licences SET statut='Actif' WHERE licence_key=?", (cle_sel,))
                conn.commit(); conn.close()
                _log(db_name, cle_sel, "Réactivation fondateur", "Réactivé manuellement")
                st.success("Licence réactivée.")
        with c3:
            if st.button("🗑️ Révoquer définitivement", use_container_width=True):
                conn = sqlite3.connect(db_name)
                conn.execute("UPDATE licences SET statut='Révoqué' WHERE licence_key=?", (cle_sel,))
                conn.commit(); conn.close()
                _log(db_name, cle_sel, "Révocation fondateur", "Révoqué définitivement")
                st.error("Licence révoquée définitivement.")

        if st.button("🔁 Autoriser un transfert vers une nouvelle machine"):
            conn = sqlite3.connect(db_name)
            conn.execute("UPDATE licences SET empreinte_machine=NULL WHERE licence_key=?", (cle_sel,))
            conn.commit(); conn.close()
            _log(db_name, cle_sel, "Déverrouillage machine", "Empreinte machine réinitialisée pour transfert")
            st.info("La licence se liera à la prochaine machine qui l'utilisera.")

    st.markdown("---")
    st.markdown("##### 🕵️ Journal des événements de licence")
    conn = sqlite3.connect(db_name)
    df_ev = pd.read_sql_query("SELECT * FROM licence_evenements ORDER BY id DESC LIMIT 100", conn)
    conn.close()
    st.dataframe(df_ev, use_container_width=True)

    st.stop()  # le panneau fondateur ne doit jamais fusionner avec le reste de l'UI cliente
