"""
Génère une nouvelle paire de clés RS256 (JWT) + une nouvelle ENCRYPTION_KEY.
⚠️ La rotation invalide TOUS les tokens en cours → à planifier hors heures
   d'activité, ou à utiliser en mode "double-clé" (accepte ancienne + nouvelle
   pendant la fenêtre de transition).

Usage :
    python -m scripts.rotate_secrets --output .env.new
"""
from __future__ import annotations

import argparse
import base64
import os
import secrets
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def generate_rsa_keypair(bits: int = 4096) -> tuple[str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=bits)
    priv_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    pub_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    return priv_pem, pub_pem


def generate_encryption_key() -> str:
    """32 octets aléatoires, encodés base64 (clé AES-256-GCM)."""
    return base64.b64encode(secrets.token_bytes(32)).decode("ascii")


def main() -> None:
    parser = argparse.ArgumentParser(description="Génère une nouvelle paire de clés + AES key.")
    parser.add_argument(
        "--output",
        default=".env.new",
        help="Fichier de sortie (défaut : .env.new)",
    )
    parser.add_argument("--bits", type=int, default=4096)
    args = parser.parse_args()

    priv, pub = generate_rsa_keypair(args.bits)
    aes_key = generate_encryption_key()

    content = (
        "# ⚠️ Ne PAS commiter ce fichier. Fusionner manuellement avec .env.\n"
        f"JWT_PRIVATE_KEY=\"\"\"{priv}\"\"\"\n"
        f"JWT_PUBLIC_KEY=\"\"\"{pub}\"\"\"\n"
        f"ENCRYPTION_KEY={aes_key}\n"
    )

    out = Path(args.output)
    out.write_text(content, encoding="utf-8")
    # Permissions restrictives
    os.chmod(out, 0o600)

    print(f"✅ Nouvelles clés générées dans {out}")
    print("→ Fusionnez avec votre .env, redémarrez l'API, puis")
    print("  révoquez toutes les sessions (DELETE FROM sessions;) si besoin.")


if __name__ == "__main__":
    main()
