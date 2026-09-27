"""
securite_bancaire.py — BaobabVault ERP
Chiffrement des données sensibles, piste d'audit en chaîne de hachage,
et détection HEURISTIQUE de motifs de transactions en cascade (A→B→C).

⚠️ AVERTISSEMENT DE CONFORMITÉ (à lire avant tout déploiement bancaire) :
`detecter_chaines_suspectes` est un détecteur de MOTIFS, pas un moteur
AML certifié. Une vraie conformité AML/KYC (BCEAO, GAFI/FATF) exige :
listes de sanctions à jour, scoring de risque client, déclarations
d'opérations suspectes (DOS) formalisées, et surtout un AUDIT PAR UN
CABINET DE CONFORMITÉ. Ce module donne une base technique de départ,
pas un certificat de conformité.

Dépendances : pip install cryptography networkx pandas
"""

import hashlib
import sqlite3
from datetime import datetime, timedelta

import streamlit as st
from cryptography.fernet import Fernet

# ------------------------------------------------------------------
# CHIFFREMENT — la clé maîtresse ne doit JAMAIS être en dur dans le code.
# Génère-la une fois avec generer_cle_maitresse(), colle le résultat
# dans st.secrets["MASTER_ENCRYPTION_KEY"], puis ne la régénère plus
# jamais (sinon les données déjà chiffrées deviennent illisibles).
# ------------------------------------------------------------------

def generer_cle_maitresse() -> str:
    return Fernet.generate_key().decode()


def _fernet() -> Fernet:
    cle = st.secrets.get("MASTER_ENCRYPTION_KEY", "") if hasattr(st, "secrets") else ""
    if not cle:
        raise RuntimeError("MASTER_ENCRYPTION_KEY manquante dans les secrets — chiffrement impossible.")
    return Fernet(cle.encode())


def chiffrer(valeur_claire: str) -> str:
    return _fernet().encrypt(valeur_claire.encode()).decode()


def dechiffrer(valeur_chiffree: str) -> str:
    return _fernet().decrypt(valeur_chiffree.encode()).decode()


# ------------------------------------------------------------------
# AUDIT INFALSIFIABLE — chaîne de hachage (chaque ligne contient
# l'empreinte de la précédente ; toute altération casse la chaîne).
# ------------------------------------------------------------------
GENESIS_HASH = "0" * 64


def init_audit_chain(db_name: str):
    conn = sqlite3.connect(db_name)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS audit_chain (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT, username TEXT, action TEXT, details TEXT,
            hash_precedent TEXT, hash_courant TEXT
        )
    """)
    conn.commit(); conn.close()


def _hash_ligne(ts, user, action, details, hash_prec) -> str:
    return hashlib.sha256(f"{ts}|{user}|{action}|{details}|{hash_prec}".encode()).hexdigest()


def log_action_immuable(db_name: str, username: str, action: str, details: str):
    init_audit_chain(db_name)
    conn = sqlite3.connect(db_name)
    dernier = conn.execute("SELECT hash_courant FROM audit_chain ORDER BY id DESC LIMIT 1").fetchone()
    hash_prec = dernier[0] if dernier else GENESIS_HASH
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
    hash_courant = _hash_ligne(ts, username, action, details, hash_prec)
    conn.execute(
        "INSERT INTO audit_chain (timestamp, username, action, details, hash_precedent, hash_courant) VALUES (?,?,?,?,?,?)",
        (ts, username, action, details, hash_prec, hash_courant),
    )
    conn.commit(); conn.close()


def verifier_integrite_audit(db_name: str) -> tuple[bool, str]:
    conn = sqlite3.connect(db_name)
    lignes = conn.execute(
        "SELECT timestamp, username, action, details, hash_precedent, hash_courant FROM audit_chain ORDER BY id ASC"
    ).fetchall()
    conn.close()
    attendu = GENESIS_HASH
    for i, (ts, u, a, d, hp, hc) in enumerate(lignes):
        if hp != attendu:
            return False, f"Rupture de chaîne à la ligne {i+1}."
        if _hash_ligne(ts, u, a, d, hp) != hc:
            return False, f"Ligne {i+1} altérée."
        attendu = hc
    return True, f"Chaîne intègre — {len(lignes)} entrées vérifiées."


# ------------------------------------------------------------------
# DÉTECTION DE MOTIFS EN CASCADE (A → B → C) — heuristique, pas un
# moteur AML certifié (voir avertissement en tête de fichier).
# ------------------------------------------------------------------

def init_transactions_table(db_name: str):
    conn = sqlite3.connect(db_name)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            compte_source TEXT, compte_destination TEXT,
            montant REAL, devise TEXT DEFAULT 'FCFA',
            timestamp TEXT, statut TEXT DEFAULT 'Validée'
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS comptes_geles (
            compte TEXT PRIMARY KEY, raison TEXT, date_gel TEXT
        )
    """)
    conn.commit(); conn.close()


def enregistrer_transaction(db_name: str, source: str, destination: str, montant: float, devise: str = "FCFA"):
    init_transactions_table(db_name)
    conn = sqlite3.connect(db_name)
    conn.execute(
        "INSERT INTO transactions (compte_source, compte_destination, montant, devise, timestamp) VALUES (?,?,?,?,?)",
        (source, destination, montant, devise, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    )
    conn.commit(); conn.close()


def geler_compte(db_name: str, compte: str, raison: str):
    init_transactions_table(db_name)
    conn = sqlite3.connect(db_name)
    conn.execute(
        "INSERT OR REPLACE INTO comptes_geles (compte, raison, date_gel) VALUES (?,?,?)",
        (compte, raison, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    )
    conn.commit(); conn.close()


def compte_est_gele(db_name: str, compte: str) -> bool:
    conn = sqlite3.connect(db_name)
    row = conn.execute("SELECT 1 FROM comptes_geles WHERE compte=?", (compte,)).fetchone()
    conn.close()
    return row is not None


def detecter_chaines_suspectes(db_name: str, fenetre_heures: int = 48, seuil_montant: float = 5_000_000) -> list[dict]:
    """
    Motif recherché ("layering" classique) : A → B → C en moins de
    `fenetre_heures`, chaque montant restant proche du précédent
    (le montant reçu est quasi entièrement retransmis), au-dessus du
    seuil. Retourne la liste des chaînes détectées, SANS geler
    automatiquement les comptes — la décision de gel reste humaine.
    """
    import pandas as pd
    init_transactions_table(db_name)
    conn = sqlite3.connect(db_name)
    df = pd.read_sql_query("SELECT * FROM transactions WHERE montant >= ?", conn, params=(seuil_montant * 0.5,))
    conn.close()
    if df.empty:
        return []

    df["timestamp"] = pd.to_datetime(df["timestamp"])
    alertes = []

    for _, t1 in df.iterrows():
        if t1["montant"] < seuil_montant:
            continue
        suivants = df[
            (df["compte_source"] == t1["compte_destination"]) &
            (df["timestamp"] > t1["timestamp"]) &
            (df["timestamp"] <= t1["timestamp"] + timedelta(hours=fenetre_heures)) &
            (df["montant"] >= t1["montant"] * 0.85)  # quasi-totalité retransmise
        ]
        for _, t2 in suivants.iterrows():
            alertes.append({
                "chaine": f"{t1['compte_source']} → {t1['compte_destination']} → {t2['compte_destination']}",
                "montant_initial": t1["montant"],
                "montant_final": t2["montant"],
                "delai_heures": round((t2["timestamp"] - t1["timestamp"]).total_seconds() / 3600, 1),
                "comptes_impliques": [t1["compte_source"], t1["compte_destination"], t2["compte_destination"]],
            })
    return alertes


def render_module_amls(db_name: str):
    st.subheader("🕸️ Détection de Motifs de Transactions en Cascade")
    st.caption(
        "⚠️ Heuristique de démonstration (motif A→B→C, montants proches, fenêtre courte) — "
        "ne remplace pas un moteur AML certifié ni une revue de conformité professionnelle."
    )
    fenetre = st.slider("Fenêtre de temps (heures)", 1, 168, 48)
    seuil = st.number_input("Seuil de montant (FCFA)", value=5_000_000.0, step=500_000.0)
    if st.button("🔍 Lancer l'analyse"):
        alertes = detecter_chaines_suspectes(db_name, fenetre, seuil)
        if not alertes:
            st.success("Aucun motif en cascade détecté sur ces critères.")
        else:
            st.error(f"{len(alertes)} chaîne(s) suspecte(s) détectée(s).")
            for a in alertes:
                with st.expander(a["chaine"]):
                    st.write(f"Montant initial : {a['montant_initial']:,.0f} — Montant final : {a['montant_final']:,.0f}")
                    st.write(f"Délai : {a['delai_heures']} heures")
                    for compte in a["comptes_impliques"]:
                        if st.button(f"🧊 Geler {compte}", key=f"geler_{compte}_{a['chaine']}"):
                            geler_compte(db_name, compte, f"Motif en cascade : {a['chaine']}")
                            st.warning(f"Compte {compte} gelé.")
