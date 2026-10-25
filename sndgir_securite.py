"""Sécurité de l'ERP : double authentification (TOTP), sauvegardes, mode production.

Tout est écrit avec la bibliothèque standard de Python (aucune installation en plus).
La double authentification suit la norme RFC 6238 : elle marche avec Google Authenticator,
Microsoft Authenticator, Authy, etc.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import sqlite3
import struct
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

# Colonnes ajoutées à la table des utilisateurs (migration automatique).
MIGRATIONS_SECURITE = {
    "utilisateurs": [
        ("totp_secret", "TEXT"),
        ("totp_actif", "INTEGER DEFAULT 0"),
    ],
}


# ── Double authentification (TOTP, RFC 6238) ─────────────────────────────────
def generer_secret() -> str:
    """Secret aléatoire de 160 bits, en base32 (celui qu'on scanne dans l'application)."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _hotp(secret: str, compteur: int, chiffres: int = 6, algo=hashlib.sha1) -> str:
    secret = secret.strip().replace(" ", "").upper()
    secret += "=" * (-len(secret) % 8)
    cle = base64.b32decode(secret)
    mac = hmac.new(cle, struct.pack(">Q", compteur), algo).digest()
    decalage = mac[-1] & 0x0F
    valeur = struct.unpack(">I", mac[decalage:decalage + 4])[0] & 0x7FFFFFFF
    return str(valeur % (10 ** chiffres)).zfill(chiffres)


def code_totp(secret: str, instant: float | None = None, pas: int = 30,
              chiffres: int = 6, algo=hashlib.sha1) -> str:
    instant = time.time() if instant is None else instant
    return _hotp(secret, int(instant // pas), chiffres, algo)


def verifier_totp(secret: str, code: str, instant: float | None = None,
                  fenetre: int = 1, pas: int = 30) -> bool:
    """Vrai si le code est bon (on tolère ±1 période de 30 s pour le décalage d'horloge)."""
    code = (code or "").strip().replace(" ", "")
    if not (code.isdigit() and len(code) == 6) or not secret:
        return False
    instant = time.time() if instant is None else instant
    ok = False
    for decalage in range(-fenetre, fenetre + 1):          # pas de sortie anticipée : temps constant
        attendu = _hotp(secret, int(instant // pas) + decalage)
        ok |= hmac.compare_digest(attendu, code)
    return ok


def uri_otpauth(secret: str, utilisateur: str, emetteur: str = "SNDGIR ERP") -> str:
    """Lien à mettre dans un QR code ou à saisir à la main dans l'application."""
    return (f"otpauth://totp/{quote(emetteur)}:{quote(utilisateur)}"
            f"?secret={secret}&issuer={quote(emetteur)}&algorithm=SHA1&digits=6&period=30")


# ── Sauvegardes de la base ───────────────────────────────────────────────────
def sauvegarder_base(db_path: Path | str, dossier: Path | str, garder: int = 7) -> Path:
    """Copie cohérente de la base (même si l'application l'utilise) dans `dossier`.

    Garde les `garder` copies les plus récentes et supprime les plus anciennes.
    """
    dossier = Path(dossier)
    dossier.mkdir(parents=True, exist_ok=True)
    cible = dossier / f"sndgir_{datetime.now():%Y%m%d_%H%M%S_%f}.db"
    source = sqlite3.connect(str(db_path), timeout=30)
    destination = sqlite3.connect(str(cible))
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()
    copies = sorted(dossier.glob("sndgir_*.db"))
    for ancienne in copies[:-max(1, garder)]:
        ancienne.unlink(missing_ok=True)
    return cible


def sauvegarde_en_octets(db_path: Path | str) -> bytes:
    """Copie complète de la base, en mémoire, pour le bouton « Télécharger »."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        fichier = sauvegarder_base(db_path, tmp, garder=1)
        return fichier.read_bytes()


def base_valide(octets: bytes) -> bool:
    """Contrôle qu'un fichier de sauvegarde est une base SQLite saine (avant de s'y fier)."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        chemin = Path(tmp) / "controle.db"
        chemin.write_bytes(octets)
        try:
            conn = sqlite3.connect(str(chemin))
            try:
                return conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            finally:
                conn.close()
        except sqlite3.DatabaseError:
            return False


# ── Mode production ──────────────────────────────────────────────────────────
def mode_production() -> bool:
    """SNDGIR_PRODUCTION=1 : aucun compte de démonstration, mot de passe admin choisi par vous."""
    return os.getenv("SNDGIR_PRODUCTION", "").lower() in ("1", "true", "oui")


def mot_de_passe_admin_initial(minimum: int = 10) -> str:
    """Lit SNDGIR_ADMIN_MDP (obligatoire en production). Refuse un mot de passe trop faible."""
    mdp = os.getenv("SNDGIR_ADMIN_MDP", "")
    if len(mdp) < minimum:
        raise RuntimeError(
            "Mode production : définissez SNDGIR_ADMIN_MDP (au moins "
            f"{minimum} caractères) avant le premier lancement. "
            "Exemple : export SNDGIR_ADMIN_MDP='MonMotDePasse2026!'")
    return mdp
