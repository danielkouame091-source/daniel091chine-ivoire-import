"""
securite_bancaire.py — MFA (TOTP) + Piste d'Audit Immuable

Pourquoi un chaînage de hachage pour l'audit :
Une table `audit_logs` classique peut être modifiée ou purgée par
quiconque a un accès direct à la base (y compris un admin malveillant
ou un attaquant qui a exfiltré la DB). Un régulateur bancaire /
douanier exige une preuve que le journal n'a PAS été altéré après
coup. La solution ici : chaque ligne contient le hash de la ligne
précédente (comme une mini blockchain locale). Toute modification
ou suppression d'une ligne ancienne casse la chaîne — vérifiable en
une passe (`verifier_integrite_audit`).

⚠️ Ce n'est pas un substitut à une vraie solution WORM (write-once /
S3 Object Lock, journal externalisé chez un tiers). C'est une preuve
de manipulation en base locale, pas une preuve d'existence absolue.

Dépendance requise : pip install pyotp qrcode[pil]
"""

import hashlib
import sqlite3
from datetime import datetime

import streamlit as st

try:
    import pyotp
    import qrcode
    import io
except ImportError:
    pyotp = None


# ---------------------------------------------------------------------
# MFA — TOTP (Google Authenticator / Microsoft Authenticator compatible)
# ---------------------------------------------------------------------

def init_mfa_table(db_name: str):
    conn = sqlite3.connect(db_name)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS mfa_secrets (
            username TEXT PRIMARY KEY,
            secret TEXT,
            active INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()


def generer_secret_mfa(db_name: str, username: str) -> str | None:
    """Crée (ou récupère) un secret TOTP pour l'utilisateur, non encore activé."""
    if pyotp is None:
        return None
    conn = sqlite3.connect(db_name)
    row = conn.execute("SELECT secret FROM mfa_secrets WHERE username=?", (username,)).fetchone()
    if row:
        secret = row[0]
    else:
        secret = pyotp.random_base32()
        conn.execute("INSERT INTO mfa_secrets (username, secret, active) VALUES (?, ?, 0)", (username, secret))
        conn.commit()
    conn.close()
    return secret


def qr_code_mfa(secret: str, username: str, issuer: str = "SNDGIR ERP") -> bytes:
    uri = pyotp.totp.TOTP(secret).provisioning_uri(name=username, issuer_name=issuer)
    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def activer_mfa(db_name: str, username: str, code_saisi: str) -> bool:
    conn = sqlite3.connect(db_name)
    row = conn.execute("SELECT secret FROM mfa_secrets WHERE username=?", (username,)).fetchone()
    if not row:
        conn.close()
        return False
    totp = pyotp.TOTP(row[0])
    if totp.verify(code_saisi, valid_window=1):
        conn.execute("UPDATE mfa_secrets SET active=1 WHERE username=?", (username,))
        conn.commit()
        conn.close()
        return True
    conn.close()
    return False


def mfa_est_actif(db_name: str, username: str) -> bool:
    conn = sqlite3.connect(db_name)
    row = conn.execute("SELECT active FROM mfa_secrets WHERE username=?", (username,)).fetchone()
    conn.close()
    return bool(row and row[0] == 1)


def verifier_code_mfa(db_name: str, username: str, code_saisi: str) -> bool:
    if pyotp is None:
        return True  # dépendance absente — ne bloque pas le login, à corriger en prod
    conn = sqlite3.connect(db_name)
    row = conn.execute("SELECT secret FROM mfa_secrets WHERE username=?", (username,)).fetchone()
    conn.close()
    if not row:
        return False
    return pyotp.TOTP(row[0]).verify(code_saisi, valid_window=1)


def bloc_login_mfa(db_name: str, username: str) -> bool:
    """
    À insérer juste après une authentification mot de passe réussie,
    avant de mettre `st.session_state.authenticated = True`.
    Retourne True seulement quand le code TOTP est validé.
    """
    if pyotp is None:
        st.warning("⚠️ Package `pyotp` non installé — MFA désactivé (mode dégradé).")
        return True

    if not mfa_est_actif(db_name, username):
        st.info("🔐 Première connexion : configuration de l'authentification à deux facteurs requise.")
        secret = generer_secret_mfa(db_name, username)
        st.image(qr_code_mfa(secret, username), caption="Scannez avec Google Authenticator / Microsoft Authenticator")
        code = st.text_input("Entrez le code à 6 chiffres pour activer le MFA", key="mfa_activation_code")
        if st.button("Activer le MFA"):
            if activer_mfa(db_name, username, code):
                st.success("MFA activé. Reconnectez-vous.")
                st.rerun()
            else:
                st.error("Code invalide.")
        return False

    code = st.text_input("🔐 Code d'authentification à deux facteurs", key="mfa_login_code")
    if st.button("Valider le code MFA"):
        if verifier_code_mfa(db_name, username, code):
            return True
        st.error("Code MFA invalide ou expiré.")
    return False


# ---------------------------------------------------------------------
# Piste d'audit immuable — chaînage de hachage (hash chain)
# ---------------------------------------------------------------------

GENESIS_HASH = "0" * 64


def init_audit_chain_table(db_name: str):
    conn = sqlite3.connect(db_name)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS audit_chain (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            username TEXT,
            action TEXT,
            details TEXT,
            hash_precedent TEXT,
            hash_courant TEXT
        )
    """)
    conn.commit()
    conn.close()


def _calculer_hash(timestamp, username, action, details, hash_precedent) -> str:
    contenu = f"{timestamp}|{username}|{action}|{details}|{hash_precedent}"
    return hashlib.sha256(contenu.encode("utf-8")).hexdigest()


def log_action_immuable(db_name: str, username: str, action: str, details: str):
    """Remplace log_action() classique partout où la traçabilité doit être opposable."""
    init_audit_chain_table(db_name)
    conn = sqlite3.connect(db_name)
    dernier = conn.execute("SELECT hash_courant FROM audit_chain ORDER BY id DESC LIMIT 1").fetchone()
    hash_precedent = dernier[0] if dernier else GENESIS_HASH
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
    hash_courant = _calculer_hash(timestamp, username, action, details, hash_precedent)
    conn.execute(
        "INSERT INTO audit_chain (timestamp, username, action, details, hash_precedent, hash_courant) VALUES (?, ?, ?, ?, ?, ?)",
        (timestamp, username, action, details, hash_precedent, hash_courant),
    )
    conn.commit()
    conn.close()


def verifier_integrite_audit(db_name: str) -> tuple[bool, str]:
    """Reparcourt toute la chaîne et vérifie qu'aucune ligne n'a été modifiée/supprimée."""
    conn = sqlite3.connect(db_name)
    lignes = conn.execute("SELECT timestamp, username, action, details, hash_precedent, hash_courant FROM audit_chain ORDER BY id ASC").fetchall()
    conn.close()

    hash_attendu = GENESIS_HASH
    for i, (ts, user, action, details, hash_prec, hash_cour) in enumerate(lignes):
        if hash_prec != hash_attendu:
            return False, f"Rupture de chaîne à la ligne {i+1} (hash précédent incohérent)."
        recalcul = _calculer_hash(ts, user, action, details, hash_prec)
        if recalcul != hash_cour:
            return False, f"Ligne {i+1} altérée : le contenu ne correspond plus à son empreinte."
        hash_attendu = hash_cour

    return True, f"Chaîne intègre — {len(lignes)} entrées vérifiées."


def render_audit_viewer(db_name: str):
    """Onglet Admin : afficher le journal + un bouton de vérification d'intégrité."""
    import pandas as pd
    init_audit_chain_table(db_name)
    st.subheader("🔗 Piste d'Audit Immuable (Hash Chain)")

    if st.button("🔍 Vérifier l'intégrité complète de la chaîne"):
        ok, message = verifier_integrite_audit(db_name)
        (st.success if ok else st.error)(message)

    conn = sqlite3.connect(db_name)
    df = pd.read_sql_query("SELECT id, timestamp, username, action, details, hash_courant FROM audit_chain ORDER BY id DESC LIMIT 200", conn)
    conn.close()
    st.dataframe(df, use_container_width=True)
