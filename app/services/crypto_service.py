"""
Service de chiffrement symétrique (AES-256-GCM).
Utilisé pour les secrets (clés API, mots de passe de plugin).
"""
from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings


class CryptoService:
    """Chiffrement/déchiffrement AES-256-GCM."""

    def __init__(self) -> None:
        key = base64.b64decode(settings.ENCRYPTION_KEY)
        if len(key) != 32:
            raise ValueError("ENCRYPTION_KEY doit faire 32 octets (base64)")
        self._aes = AESGCM(key)

    def encrypt(self, plaintext: str) -> str:
        """Chiffre et retourne base64(nonce + ciphertext+tag)."""
        nonce = os.urandom(12)
        ct = self._aes.encrypt(nonce, plaintext.encode("utf-8"), None)
        return base64.b64encode(nonce + ct).decode("ascii")

    def decrypt(self, ciphertext_b64: str) -> str:
        """Déchiffre depuis base64(nonce + ciphertext+tag)."""
        raw = base64.b64decode(ciphertext_b64)
        nonce, ct = raw[:12], raw[12:]
        return self._aes.decrypt(nonce, ct, None).decode("utf-8")
