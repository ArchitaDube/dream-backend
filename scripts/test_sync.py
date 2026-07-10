#!/usr/bin/env python3
"""Integration test: Encrypted sync (backup/restore).

Usage:
    python scripts/test_sync.py

Requires:
    - Server running on http://localhost:8000
    - Neon DB configured and migrated
"""

import json
import sys
import uuid

import httpx

BASE = "http://localhost:8000"


def _register_client() -> str:
    client_id = str(uuid.uuid4())
    resp = httpx.post(f"{BASE}/clients", json={"client_id": client_id})
    assert resp.status_code == 201
    return client_id


def _create_dream(client_id: str, body: str, title: str = None):
    payload = {"body": body}
    if title:
        payload["title"] = title
    resp = httpx.post(
        f"{BASE}/dreams",
        json=payload,
        headers={"X-Client-Id": client_id},
    )
    assert resp.status_code == 201


def test_sync_init():
    """POST /sync/init — create encrypted backup, expect phrase + payload."""
    client_id = _register_client()
    _create_dream(client_id, "I was flying over a city.", "Flight")

    resp = httpx.post(
        f"{BASE}/sync/init",
        headers={"X-Client-Id": client_id},
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert "phrase" in data
    assert "encryptedPayload" in data
    assert len(data["phrase"]) == 12, f"Expected 12 words, got {len(data['phrase'])}"
    print(f"  ✅ Sync init: {len(data['phrase'])}-word phrase, payload={len(data['encryptedPayload'])} chars")


def test_sync_restore():
    """POST /sync/restore — restore from phrase, expect dreams back."""
    client_id = _register_client()
    _create_dream(client_id, "I was flying over a city.", "Flight")

    # Backup
    backup_resp = httpx.post(
        f"{BASE}/sync/init",
        headers={"X-Client-Id": client_id},
    )
    assert backup_resp.status_code == 200
    phrase = backup_resp.json()["phrase"]

    # Restore
    resp = httpx.post(
        f"{BASE}/sync/restore",
        json={"phrase": phrase},
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert "dreams" in data
    assert len(data["dreams"]) >= 1
    print(f"  ✅ Sync restore: {len(data['dreams'])} dreams recovered")


def test_sync_restore_invalid_phrase():
    """POST /sync/restore — invalid phrase, expect 404."""
    resp = httpx.post(
        f"{BASE}/sync/restore",
        json={"phrase": ["invalid", "phrase", "words", "here", "x", "y", "z", "a", "b", "c", "d", "e"]},
    )
    assert resp.status_code == 404, f"Expected 404, got {resp.status_code}"
    print(f"  ✅ Invalid phrase returns 404")


def main():
    print("\n=== Sync Tests ===\n")
    test_sync_init()
    test_sync_restore()
    test_sync_restore_invalid_phrase()
    print("\n✅ All sync tests passed!\n")


if __name__ == "__main__":
    main()
