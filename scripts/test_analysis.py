#!/usr/bin/env python3
"""Integration test: Analysis SSE streaming.

Usage:
    python scripts/test_analysis.py

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


def _create_dream(client_id: str) -> str:
    resp = httpx.post(
        f"{BASE}/dreams",
        json={"body": "I was flying over a city at night. The buildings were glowing blue.", "title": "Flight"},
        headers={"X-Client-Id": client_id},
    )
    assert resp.status_code == 201
    return resp.json()["dream"]["id"]


def _do_dialogue_turn(client_id: str, dream_id: str, message: str):
    resp = httpx.post(
        f"{BASE}/dreams/{dream_id}/dialogue",
        json={"message": message},
        headers={"X-Client-Id": client_id},
    )
    assert resp.status_code == 200


def _complete_dialogue(client_id: str, dream_id: str):
    resp = httpx.post(
        f"{BASE}/dreams/{dream_id}/dialogue/complete",
        headers={"X-Client-Id": client_id},
    )
    assert resp.status_code == 200


def test_analyze_dream():
    """GET /dreams/:id/analyze — SSE stream analysis after dialogue complete."""
    client_id = _register_client()
    dream_id = _create_dream(client_id)

    # Do a dialogue turn and complete
    _do_dialogue_turn(client_id, dream_id, "I felt both scared and exhilarated.")
    _complete_dialogue(client_id, dream_id)

    # Now analyze
    with httpx.Client() as client:
        resp = client.get(
            f"{BASE}/dreams/{dream_id}/analyze",
            headers={"X-Client-Id": client_id},
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

        events = []
        for line in resp.text.strip().split("\n"):
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))

        assert len(events) >= 2, f"Expected at least 2 events, got {len(events)}"
        # Should have tokens
        tokens = [e for e in events if e["type"] == "token"]
        assert len(tokens) > 0, f"No token events found: {events}"
        # Last event should be done with analysis
        assert events[-1]["type"] == "done", f"Expected done, got {events[-1]}"
        assert "analysis" in events[-1]
        print(f"  ✅ Analyze dream: {len(tokens)} tokens, analysis has {len(events[-1]['analysis'])} keys")


def test_analyze_without_dialogue():
    """GET /dreams/:id/analyze — without dialogue complete, expect 400."""
    client_id = _register_client()
    dream_id = _create_dream(client_id)

    resp = httpx.get(
        f"{BASE}/dreams/{dream_id}/analyze",
        headers={"X-Client-Id": client_id},
    )
    assert resp.status_code == 400, f"Expected 400, got {resp.status_code}"
    print(f"  ✅ Analyze without dialogue blocked (400)")


def test_analyze_dream_not_found():
    """GET /dreams/:id/analyze — non-existent dream, expect 404."""
    client_id = _register_client()
    resp = httpx.get(
        f"{BASE}/dreams/drm_nonexistent/analyze",
        headers={"X-Client-Id": client_id},
    )
    assert resp.status_code == 404, f"Expected 404, got {resp.status_code}"
    print(f"  ✅ Analyze non-existent dream returns 404")


def main():
    print("\n=== Analysis Tests ===\n")
    test_analyze_dream()
    test_analyze_without_dialogue()
    test_analyze_dream_not_found()
    print("\n✅ All analysis tests passed!\n")


if __name__ == "__main__":
    main()
