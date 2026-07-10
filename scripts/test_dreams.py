#!/usr/bin/env python3
"""Integration test: Dream CRUD.

Usage:
    python scripts/test_dreams.py

Requires:
    - Server running on http://localhost:8000
    - Neon DB configured and migrated
"""

import sys
import uuid

import httpx

BASE = "http://localhost:8000"


def _register_client() -> str:
    client_id = str(uuid.uuid4())
    resp = httpx.post(f"{BASE}/clients", json={"client_id": client_id})
    assert resp.status_code == 201
    return client_id


def _auth_headers(client_id: str) -> dict:
    return {"X-Client-Id": client_id}


def test_create_dream():
    """POST /dreams — create a dream, expect 201."""
    client_id = _register_client()
    resp = httpx.post(
        f"{BASE}/dreams",
        json={"body": "I was flying over a city at night.", "title": "Flight"},
        headers=_auth_headers(client_id),
    )
    assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"
    data = resp.json()
    dream = data["dream"]
    assert dream["body"] == "I was flying over a city at night."
    assert dream["title"] == "Flight"
    assert dream["id"].startswith("drm_")
    print(f"  ✅ Create dream: {dream['id']} — {dream['title']}")
    return client_id, dream["id"]


def test_create_dream_without_title():
    """POST /dreams — create dream without title, expect 201."""
    client_id = _register_client()
    resp = httpx.post(
        f"{BASE}/dreams",
        json={"body": "I was in a dark forest."},
        headers=_auth_headers(client_id),
    )
    assert resp.status_code == 201
    dream = resp.json()["dream"]
    assert dream["title"] is None
    print(f"  ✅ Create dream (no title): {dream['id']}")


def test_list_dreams():
    """GET /dreams — list dreams, expect 200."""
    client_id = _register_client()
    # Create 2 dreams
    for i in range(2):
        httpx.post(
            f"{BASE}/dreams",
            json={"body": f"Dream number {i}", "title": f"Dream {i}"},
            headers=_auth_headers(client_id),
        )
    resp = httpx.get(f"{BASE}/dreams", headers=_auth_headers(client_id))
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["dreams"]) == 2
    print(f"  ✅ List dreams: {len(data['dreams'])} dreams found")


def test_get_dream():
    """GET /dreams/:id — get a single dream, expect 200."""
    client_id, dream_id = test_create_dream()
    resp = httpx.get(f"{BASE}/dreams/{dream_id}", headers=_auth_headers(client_id))
    assert resp.status_code == 200
    dream = resp.json()["dream"]
    assert dream["id"] == dream_id
    print(f"  ✅ Get dream: {dream_id}")


def test_get_dream_not_found():
    """GET /dreams/:id — non-existent dream, expect 404."""
    client_id = _register_client()
    resp = httpx.get(f"{BASE}/dreams/drm_nonexistent", headers=_auth_headers(client_id))
    assert resp.status_code == 404
    print(f"  ✅ Get non-existent dream returns 404")


def test_delete_dream():
    """DELETE /dreams/:id — delete a dream, expect 204."""
    client_id, dream_id = test_create_dream()
    resp = httpx.delete(f"{BASE}/dreams/{dream_id}", headers=_auth_headers(client_id))
    assert resp.status_code == 204, f"Expected 204, got {resp.status_code}"
    # Verify it's gone
    resp = httpx.get(f"{BASE}/dreams/{dream_id}", headers=_auth_headers(client_id))
    assert resp.status_code == 404
    print(f"  ✅ Delete dream: {dream_id}")


def test_delete_dream_not_found():
    """DELETE /dreams/:id — non-existent dream, expect 404."""
    client_id = _register_client()
    resp = httpx.delete(f"{BASE}/dreams/drm_nonexistent", headers=_auth_headers(client_id))
    assert resp.status_code == 404
    print(f"  ✅ Delete non-existent dream returns 404")


def test_dream_limit_free_tier():
    """POST /dreams — free tier limit (10 max), expect 403 on 11th."""
    client_id = _register_client()
    for i in range(10):
        resp = httpx.post(
            f"{BASE}/dreams",
            json={"body": f"Dream {i}"},
            headers=_auth_headers(client_id),
        )
        assert resp.status_code == 201, f"Failed on dream {i}: {resp.text}"
    # 11th should fail
    resp = httpx.post(
        f"{BASE}/dreams",
        json={"body": "One too many"},
        headers=_auth_headers(client_id),
    )
    assert resp.status_code == 403, f"Expected 403, got {resp.status_code}"
    print(f"  ✅ Free tier limit enforced (403 on 11th dream)")


def test_dreams_scoped_to_client():
    """GET /dreams — dreams are scoped per client."""
    client_a = _register_client()
    client_b = _register_client()
    httpx.post(
        f"{BASE}/dreams",
        json={"body": "Client A's dream"},
        headers=_auth_headers(client_a),
    )
    httpx.post(
        f"{BASE}/dreams",
        json={"body": "Client B's dream"},
        headers=_auth_headers(client_b),
    )
    resp_a = httpx.get(f"{BASE}/dreams", headers=_auth_headers(client_a))
    resp_b = httpx.get(f"{BASE}/dreams", headers=_auth_headers(client_b))
    assert len(resp_a.json()["dreams"]) == 1
    assert len(resp_b.json()["dreams"]) == 1
    print(f"  ✅ Dreams scoped per client")


def main():
    print("\n=== Dream CRUD Tests ===\n")
    test_create_dream()
    test_create_dream_without_title()
    test_list_dreams()
    test_get_dream()
    test_get_dream_not_found()
    test_delete_dream()
    test_delete_dream_not_found()
    test_dream_limit_free_tier()
    test_dreams_scoped_to_client()
    print("\n✅ All dream tests passed!\n")


if __name__ == "__main__":
    main()
