"""
licences.py — Gestion des licences & abonnements (type "Microsoft 365")

Modèle retenu, adapté à un déploiement Streamlit Cloud par client :
- Chaque déploiement (chaque instance de l'app, donc chaque client final)
  a UNE clé de licence, stockée dans `st.secrets["LICENCE_KEY"]` —
  jamais en dur dans le code, jamais committée sur GitHub.
- La base `licences.db` (centrale, chez TOI, le fournisseur — pas chez
  le client) contient la table de vérité : qui a payé, jusqu'à quand.
- L'app du client interroge cette vérité à chaque démarrage de session.

⚠️ Limite honnête à connaître : si `licences.db` tourne dans le MÊME
process Streamlit Cloud que l'app cliente (comme ici, pour rester simple
avec SQLite), un client qui a un accès shell au conteneur pourrait en
théorie modifier sa propre ligne. Pour une vraie séparation fournisseur/
client, la table de licences doit vivre sur UN SERVEUR CENTRAL À TOI
(API séparée, ou base Postgres hébergée par toi) que l'app du client
appelle par HTTPS — pas une DB locale au déploiement du client. Le code
ci-dessous fonctionne tel quel en mode "DB partagée le temps de valider
le concept", et est écrit pour être facile à brancher sur une vraie API
plus tard (une seule fonction à remplacer : `verifier_licence`).

⚠️ Bootstrap premier lancement : tant qu'AUCUNE licence n'existe encore
dans `licences.db`, `bloc_verification_licence` laisse passer (avec un
avertissement) au lieu de tout bloquer — sinon personne ne pourrait
jamais atteindre l'écran Admin pour créer la toute première licence.
Dès qu'une licence existe en base, ce mode de secours se désactive
automatiquement et la vérification stricte reprend.
"""

import secrets
import sqlite3
from datetime import datetime, timedelta

import streamlit as st

DUREE_JOURS = {"mensuel": 30, "annuel": 365, "essai": 14}


def init_licences_tables(db_name: str):
    conn = sqlite3.connect(db_name)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS licences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entreprise TEXT,
            licence_key TEXT UNIQUE,
            type_abonnement TEXT,
            contact_email TEXT,
            montant REAL,
            date_debut TEXT,
            date_fin TEXT,
            statut TEXT DEFAULT 'Actif',
            derniere_verification_ok TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS licence_evenements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            licence_key TEXT,
            evenement TEXT,
            details TEXT
        )
    """)
    conn.commit()
    conn.close()


def _log_evenement(db_name: str, licence_key: str, evenement: str, details: str):
    conn = sqlite3.connect(db_name)
    conn.execute(
        "INSERT INTO licence_evenements (timestamp, licence_key, evenement, details) VALUES (?, ?, ?, ?)",
        (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), licence_key, evenement, details),
    )
    conn.commit()
    conn.close()


def _aucune_licence_existante(db_name: str) -> bool:
    conn = sqlite3.connect(db_name)
    nb = conn.execute("SELECT COUNT(*) FROM licences").fetchone()[0]
    conn.close()
    return nb == 0


def generer_cle_licence() -> str:
    """Format XXXX-XXXX-XXXX-XXXX, lisible et facile à communiquer par email/téléphone."""
    bloc = lambda: secrets.token_hex(2).upper()
    return f"{bloc()}-{bloc()}-{bloc()}-{bloc()}"


def creer_licence(db_name: str, entreprise: str, type_abonnement: str, contact_email: str, montant: float) -> str:
    init_licences_tables(db_name)
    cle = generer_cle_licence()
    date_debut = datetime.now()
    date_fin = date_debut + timedelta(days=DUREE_JOURS.get(type_abonnement, 30))
    conn = sqlite3.connect(db_name)
    conn.execute(
        """INSERT INTO licences (entreprise, licence_key, type_abonnement, contact_email, montant, date_debut, date_fin, statut)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'Actif')""",
        (entreprise, cle, type_abonnement, contact_email, montant, date_debut.strftime("%Y-%m-%d"), date_fin.strftime("%Y-%m-%d")),
    )
    conn.commit()
    conn.close()
    _log_evenement(db_name, cle, "Création", f"Licence créée pour {entreprise} ({type_abonnement})")
    return cle


def renouveler_licence(db_name: str, licence_key: str, type_abonnement: str | None = None) -> bool:
    conn = sqlite3.connect(db_name)
    row = conn.execute("SELECT date_fin, type_abonnement FROM licences WHERE licence_key=?", (licence_key,)).fetchone()
    if not row:
        conn.close()
        return False
    date_fin_actuelle, type_actuel = row
    type_final = type_abonnement or type_actuel
    base = max(datetime.strptime(date_fin_actuelle, "%Y-%m-%d"), datetime.now())
    nouvelle_date_fin = base + timedelta(days=DUREE_JOURS.get(type_final, 30))
    conn.execute(
        "UPDATE licences SET date_fin=?, statut='Actif', type_abonnement=? WHERE licence_key=?",
        (nouvelle_date_fin.strftime("%Y-%m-%d"), type_final, licence_key),
    )
    conn.commit()
    conn.close()
    _log_evenement(db_name, licence_key, "Renouvellement", f"Nouvelle échéance : {nouvelle_date_fin.strftime('%Y-%m-%d')}")
    return True


def suspendre_licence(db_name: str, licence_key: str, raison: str):
    conn = sqlite3.connect(db_name)
    conn.execute("UPDATE licences SET statut='Suspendu' WHERE licence_key=?", (licence_key,))
    conn.commit()
    conn.close()
    _log_evenement(db_name, licence_key, "Suspension", raison)


def verifier_licence(db_name: str, licence_key: str) -> dict:
    """
    Retourne {valide, message, jours_restants, entreprise, alerte_anomalie}.
    Détecte : clé inexistante, licence suspendue, licence expirée,
    et un indice de retour arrière d'horloge (le serveur Streamlit Cloud
    a une horloge fiable, donc surtout utile en déploiement on-premise).
    """
    init_licences_tables(db_name)

    if not licence_key:
        return {"valide": False, "message": "Aucune clé de licence configurée (LICENCE_KEY manquante dans les secrets).", "jours_restants": 0, "entreprise": None, "alerte_anomalie": False}

    conn = sqlite3.connect(db_name)
    row = conn.execute(
        "SELECT entreprise, date_fin, statut, derniere_verification_ok FROM licences WHERE licence_key=?", (licence_key,)
    ).fetchone()

    if not row:
        conn.close()
        _log_evenement(db_name, licence_key, "⚠️ Clé invalide", "Tentative de vérification avec une clé introuvable en base")
        return {"valide": False, "message": "Clé de licence introuvable.", "jours_restants": 0, "entreprise": None, "alerte_anomalie": True}

    entreprise, date_fin_str, statut, derniere_ok = row
    maintenant = datetime.now()
    date_fin = datetime.strptime(date_fin_str, "%Y-%m-%d")
    jours_restants = (date_fin - maintenant).days

    alerte_anomalie = False
    if derniere_ok:
        derniere_ok_dt = datetime.strptime(derniere_ok, "%Y-%m-%d %H:%M:%S")
        if maintenant < derniere_ok_dt - timedelta(hours=1):
            alerte_anomalie = True
            _log_evenement(db_name, licence_key, "🚨 Anomalie horloge", f"Heure système ({maintenant}) antérieure à la dernière vérification réussie ({derniere_ok_dt}) — possible contournement.")

    if statut == "Suspendu":
        conn.close()
        _log_evenement(db_name, licence_key, "Accès refusé", "Licence suspendue")
        return {"valide": False, "message": f"Licence suspendue pour {entreprise}. Contactez le fournisseur.", "jours_restants": jours_restants, "entreprise": entreprise, "alerte_anomalie": alerte_anomalie}

    if jours_restants < 0:
        conn.execute("UPDATE licences SET statut='Expiré' WHERE licence_key=?", (licence_key,))
        conn.commit()
        conn.close()
        _log_evenement(db_name, licence_key, "Accès refusé", f"Licence expirée depuis {abs(jours_restants)} jour(s)")
        return {"valide": False, "message": f"Licence expirée depuis {abs(jours_restants)} jour(s). Renouvellement requis.", "jours_restants": jours_restants, "entreprise": entreprise, "alerte_anomalie": alerte_anomalie}

    conn.execute("UPDATE licences SET derniere_verification_ok=? WHERE licence_key=?", (maintenant.strftime("%Y-%m-%d %H:%M:%S"), licence_key))
    conn.commit()
    conn.close()

    message = f"Licence active pour {entreprise}."
    if jours_restants <= 7:
        message += f" ⚠️ Expire dans {jours_restants} jour(s) — pensez au renouvellement."
    return {"valide": True, "message": message, "jours_restants": jours_restants, "entreprise": entreprise, "alerte_anomalie": alerte_anomalie}


def bloc_verification_licence(db_name: str) -> bool:
    """
    À appeler tout en haut de app.py, avant même l'écran de connexion.
    Bloque complètement l'app (st.stop()) si la licence n'est pas valide.

    Exception (bootstrap) : si la table `licences` est encore totalement
    vide (aucune licence créée nulle part), on laisse passer avec un
    simple avertissement — sinon il serait impossible d'atteindre
    l'écran Admin pour créer la toute première licence.
    """
    init_licences_tables(db_name)

    if _aucune_licence_existante(db_name):
        st.sidebar.warning(
            "🔧 Aucune licence créée pour l'instant — accès libre temporaire. "
            "Connectez-vous en Administrateur puis allez dans **Admin & Audit → Licences** "
            "pour créer la première licence, puis ajoutez sa clé dans `LICENCE_KEY` (secrets)."
        )
        return True

    licence_key = st.secrets.get("LICENCE_KEY", "") if hasattr(st, "secrets") else ""
    resultat = verifier_licence(db_name, licence_key)

    if resultat["alerte_anomalie"]:
        st.warning("⚠️ Anomalie détectée sur la vérification de licence (voir journal fournisseur).")

    if not resultat["valide"]:
        st.markdown(
            f"""
            <div style="max-width:600px;margin:100px auto;padding:30px;background:#1E293B;
                        border:1px solid #7F1D1D;border-radius:16px;text-align:center;color:#F8FAFC;">
                <h2 style="color:#F87171;">🔒 Accès Verrouillé</h2>
                <p style="font-size:1.05rem;">{resultat['message']}</p>
                <p style="color:#9CA3AF;font-size:0.85rem;">Contactez votre fournisseur pour renouveler votre abonnement.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.stop()
        return False

    if resultat["jours_restants"] <= 7:
        st.sidebar.warning(f"⏳ {resultat['message']}")

    return True


def render_admin_licences(db_name: str):
    """Écran d'administration fournisseur — création, renouvellement, suspension, journal."""
    import pandas as pd
    init_licences_tables(db_name)

    st.subheader("🔑 Gestion des Licences & Abonnements")
    sous_tabs = st.tabs(["➕ Nouvelle Licence", "🔄 Renouveler / Suspendre", "📋 Registre", "🕵️ Journal d'Anomalies"])
    tab_nouvelle, tab_action, tab_registre, tab_journal = sous_tabs

    with tab_nouvelle:
        with st.form("form_nouvelle_licence"):
            entreprise = st.text_input("Nom de l'entreprise cliente")
            type_ab = st.selectbox("Type d'abonnement", ["mensuel", "annuel", "essai"])
            email = st.text_input("Email de contact")
            montant = st.number_input("Montant facturé (FCFA)", min_value=0.0, step=10000.0)
            submit = st.form_submit_button("Générer la licence")
        if submit and entreprise:
            cle = creer_licence(db_name, entreprise, type_ab, email, montant)
            st.success(f"Licence créée pour **{entreprise}**")
            st.code(cle, language=None)
            st.caption("Copie cette clé dans le fichier `secrets.toml` du déploiement du client, sous `LICENCE_KEY = \"...\"`.")

    with tab_action:
        conn = sqlite3.connect(db_name)
        df_l = pd.read_sql_query("SELECT licence_key, entreprise FROM licences", conn)
        conn.close()
        if df_l.empty:
            st.info("Aucune licence enregistrée.")
        else:
            cle_sel = st.selectbox("Licence", df_l["licence_key"].tolist(), format_func=lambda k: f"{k} — {df_l[df_l['licence_key']==k]['entreprise'].values[0]}")
            c1, c2 = st.columns(2)
            with c1:
                if st.button("🔄 Renouveler (+ durée du plan actuel)", use_container_width=True):
                    renouveler_licence(db_name, cle_sel)
                    st.success("Licence renouvelée.")
            with c2:
                raison = st.text_input("Motif de suspension", value="Non-paiement")
                if st.button("⛔ Suspendre", use_container_width=True):
                    suspendre_licence(db_name, cle_sel, raison)
                    st.warning("Licence suspendue.")

    with tab_registre:
        conn = sqlite3.connect(db_name)
        df_reg = pd.read_sql_query("SELECT entreprise, licence_key, type_abonnement, date_debut, date_fin, statut FROM licences ORDER BY id DESC", conn)
        conn.close()
        st.dataframe(df_reg, use_container_width=True)

    with tab_journal:
        conn = sqlite3.connect(db_name)
        df_ev = pd.read_sql_query("SELECT * FROM licence_evenements ORDER BY id DESC LIMIT 200", conn)
        conn.close()
        anomalies = df_ev[df_ev["evenement"].str.contains("⚠️|🚨", na=False)]
        if not anomalies.empty:
            st.error(f"{len(anomalies)} anomalie(s) détectée(s) récemment.")
        st.dataframe(df_ev, use_container_width=True)
