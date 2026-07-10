"""AES-256-GCM encryption with BIP-39 mnemonic key derivation."""

import base64
import hashlib
import json
import os
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from mnemonic import Mnemonic

mnemo = Mnemonic("english")


def generate_mnemonic() -> str:
    """Generate a 12-word BIP-39 mnemonic phrase."""
    return mnemo.generate(strength=128)


def derive_key(phrase: str) -> bytes:
    """Derive a 256-bit AES key from a mnemonic phrase via PBKDF2."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"oneiros-sync-v1",
        iterations=100_000,
    )
    return kdf.derive(phrase.encode())


def encrypt(data: dict[str, Any], key: bytes) -> str:
    """Encrypt a dict to base64-encoded ciphertext (nonce + ciphertext)."""
    nonce = os.urandom(12)
    aesgcm = AESGCM(key)
    ct = aesgcm.encrypt(nonce, json.dumps(data).encode(), None)
    return base64.b64encode(nonce + ct).decode()


def decrypt(payload: str, key: bytes) -> dict[str, Any]:
    """Decrypt a base64-encoded ciphertext back to a dict."""
    raw = base64.b64decode(payload)
    nonce, ct = raw[:12], raw[12:]
    aesgcm = AESGCM(key)
    return json.loads(aesgcm.decrypt(nonce, ct, None))


def phrase_hash(phrase: str) -> str:
    """SHA-256 hash of the mnemonic phrase (used as lookup key)."""
    return hashlib.sha256(phrase.encode()).hexdigest()
