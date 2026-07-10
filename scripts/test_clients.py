#!/usr/bin/env python3
"""Integration test: Client registration.

Usage:
    python scripts/test_clients.py

Requires:
    - Server running on http://localhost:8000
    - Neon DB configured and migrated
"""

import sys
import uuid

import httpx

BASE = "http://localhost:8000"


def test_register_client():
    """POST /clients — register a new client, expect 201."""
    client_id = str(uuid.uuid4())
    resp = httpx.post(f"{BASE}/clients", json={"client_id": client_id})
    assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert data["client_id"] == client_id
    assert data["tier"] == "free"
    assert "createdAt" in data
    print(f"  ✅ Register client: {client_id} (tier={data['tier']})")
    return client_id


def test_register_client_upsert():
    """POST /clients — upsert (same client_id again), expect 201."""
    client_id = str(uuid.uuid4())
    resp1 = httpx.post(f"{BASE}/clients", json={"client_id": client_id})
    assert resp1.status_code == 201
    resp2 = httpx.post(f"{BASE}/clients", json={"client_id": client_id})
    assert resp2.status_code == 201, f"Upsert failed: {resp2.status_code}"
    print(f"  ✅ Upsert client: {client_id}")


def test_register_client_invalid_uuid():
    """POST /clients — invalid UUID, expect 422."""
    resp = httpx.post(f"{BASE}/clients", json={"client_id": "not-a-uuid"})
    assert resp.status_code == 422, f"Expected 422, got {resp.status_code}"
    print(f"  ✅ Invalid UUID rejected (422)")


def main():
    print("\n=== Client Registration Tests ===\n")
    test_register_client()
    test_register_client_upsert()
    test_register_client_invalid_uuid()
    print("\n✅ All client tests passed!\n")


if __name__ == "__main__":
    main()
