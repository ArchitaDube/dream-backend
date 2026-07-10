"""Tests for encryption service."""

from app.services.encryption import (
    decrypt,
    derive_key,
    encrypt,
    generate_mnemonic,
    phrase_hash,
)


def test_generate_mnemonic():
    """generate_mnemonic() should return a 12-word phrase."""
    phrase = generate_mnemonic()
    words = phrase.split()
    assert len(words) == 12
    # All words should be non-empty strings
    for word in words:
        assert len(word) > 0
        assert word.isalpha()


def test_derive_key_deterministic():
    """derive_key() should return the same key for the same phrase."""
    phrase = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"
    key1 = derive_key(phrase)
    key2 = derive_key(phrase)
    assert key1 == key2
    assert len(key1) == 32  # 256 bits


def test_encrypt_decrypt_roundtrip():
    """Encrypting then decrypting should return the original data."""
    phrase = generate_mnemonic()
    key = derive_key(phrase)
    original = {"client_id": "test-uuid", "dreams": [{"id": "drm_123", "body": "Test"}]}

    encrypted = encrypt(original, key)
    decrypted = decrypt(encrypted, key)

    assert decrypted == original


def test_encrypt_different_ciphertexts():
    """Same data encrypted twice should produce different ciphertexts (nonce)."""
    phrase = generate_mnemonic()
    key = derive_key(phrase)
    data = {"hello": "world"}

    c1 = encrypt(data, key)
    c2 = encrypt(data, key)
    assert c1 != c2


def test_phrase_hash():
    """phrase_hash() should return a consistent hex string."""
    phrase = "test phrase"
    h1 = phrase_hash(phrase)
    h2 = phrase_hash(phrase)
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 hex
