"""Primitives cryptographiques : HMAC-SHA256, AES-256-GCM."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings


def verify_hmac(payload: bytes | str, signature: str, secret: str) -> bool:
    """Vérifie la signature HMAC-SHA256 d'un webhook (comparaison constant-time)."""
    if not signature or not secret:
        return False
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    expected = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def _aes_key() -> bytes:
    key = base64.b64decode(settings.ENCRYPTION_KEY)
    if len(key) != 32:
        raise ValueError("ENCRYPTION_KEY doit faire 32 octets après décodage base64")
    return key


def encrypt(plaintext: str) -> bytes:
    """AES-256-GCM : retour = nonce(12) || ciphertext+tag."""
    aes = AESGCM(_aes_key())
    nonce = os.urandom(12)
    ct = aes.encrypt(nonce, plaintext.encode("utf-8"), None)
    return nonce + ct


def decrypt(ciphertext: bytes) -> str:
    aes = AESGCM(_aes_key())
    nonce, ct = ciphertext[:12], ciphertext[12:]
    return aes.decrypt(nonce, ct, None).decode("utf-8")
