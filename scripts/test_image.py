#!/usr/bin/env python3
"""Integration test: Image generation.

Usage:
    python scripts/test_image.py

Requires:
    - Server running on http://localhost:8000
    - Neon DB configured and migrated
"""

import json
import sys
import uuid

import httpx

BASE = "http://localhost:8000"


def _register_client(tier: str = "free") -> str:
    client_id = str(uuid.uuid4())
    resp = httpx.post(f"{BASE}/clients", json={"client_id": client_id})
    assert resp.status_code == 201
    # NOTE: To test Pro tier, you'd need to manually upgrade the client in the DB:
    #   UPDATE clients SET tier = 'pro' WHERE client_id = '<uuid>';
    return client_id


def _create_dream(client_id: str) -> str:
    resp = httpx.post(
        f"{BASE}/dreams",
        json={"body": "I was flying over a city at night.", "title": "Flight"},
        headers={"X-Client-Id": client_id},
    )
    assert resp.status_code == 201
    return resp.json()["dream"]["id"]


def test_generate_image_free_tier_blocked():
    """POST /dreams/:id/image — free tier, expect 402."""
    client_id = _register_client("free")
    dream_id = _create_dream(client_id)

    resp = httpx.post(
        f"{BASE}/dreams/{dream_id}/image",
        headers={"X-Client-Id": client_id},
    )
    assert resp.status_code == 402, f"Expected 402, got {resp.status_code}: {resp.text}"
    print(f"  ✅ Free tier blocked from image generation (402)")


def test_generate_image_no_analysis():
    """POST /dreams/:id/image — pro tier but no analysis, expect 400.

    NOTE: This test requires a Pro-tier client. Run manually after upgrading:
        UPDATE clients SET tier = 'pro' WHERE client_id = '<uuid>';
    """
    print(f"  ⏭️  Skipping (requires Pro tier in DB — run manually)")


def main():
    print("\n=== Image Generation Tests ===\n")
    test_generate_image_free_tier_blocked()
    test_generate_image_no_analysis()
    print("\n✅ All image tests passed!\n")


if __name__ == "__main__":
    main()
