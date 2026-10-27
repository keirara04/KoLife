"""AES-256-GCM for data at rest (redacted documents). Key = MASTER_KEY (base64, 32 bytes).

Generate one:  python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"
"""

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import settings


def _key() -> AESGCM:
    # fail closed: never store documents unencrypted because the key is missing
    if not settings.master_key:
        raise RuntimeError("MASTER_KEY is not set")
    return AESGCM(base64.b64decode(settings.master_key))


def key_configured() -> bool:
    try:
        return len(base64.b64decode(settings.master_key, validate=True)) == 32
    except ValueError:
        return False


def encrypt(data: bytes, aad: str) -> bytes:
    """nonce (12 bytes) + ciphertext. `aad` (e.g. the row id) binds the blob to its row."""
    # ponytail: one master key for everything; per-user envelope keys once users exist (docs/03 §5)
    nonce = os.urandom(12)
    return nonce + _key().encrypt(nonce, data, aad.encode())


def decrypt(blob: bytes, aad: str) -> bytes:
    return _key().decrypt(blob[:12], blob[12:], aad.encode())
