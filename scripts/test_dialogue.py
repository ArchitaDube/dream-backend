#!/usr/bin/env python3
"""Integration test: Dialogue SSE streaming.

Usage:
    python scripts/test_dialogue.py

Requires:
    - Server running on http://localhost:8000
    - Neon DB configured and migrated
    - DeepSeek API key set in .env (or MockLLMProvider will be used)
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


def _create_dream(client_id: str) -> str:
    resp = httpx.post(
        f"{BASE}/dreams",
        json={"body": "I was flying over a city at night. The buildings were glowing blue.", "title": "Flight"},
        headers={"X-Client-Id": client_id},
    )
    assert resp.status_code == 201
    return resp.json()["dream"]["id"]


def _auth_headers(client_id: str) -> dict:
    return {"X-Client-Id": client_id}


def test_dialogue_turn():
    """POST /dreams/:id/dialogue — SSE stream, expect tokens + done event."""
    client_id = _register_client()
    dream_id = _create_dream(client_id)

    with httpx.Client() as client:
        resp = client.post(
            f"{BASE}/dreams/{dream_id}/dialogue",
            json={"message": "I felt both scared and exhilarated."},
            headers=_auth_headers(client_id),
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        # Parse SSE events
        events = []
        for line in resp.text.strip().split("\n"):
            if line.startswith("data: "):
                import json
                events.append(json.loads(line[6:]))

        # Debug: print the raw response and parsed events
        if len(events) < 2:
            print(f"\n  ⚠️  Only got {len(events)} event(s). Raw response:")
            print(f"  {repr(resp.text[:500])}")
            for i, ev in enumerate(events):
                print(f"  Event {i}: {ev}")

        assert len(events) >= 2, f"Expected at least 2 events, got {len(events)}"
        # First event should be a token
        assert events[0]["type"] == "token", f"Expected token, got {events[0]}"
        # Last event should be done
        assert events[-1]["type"] == "done", f"Expected done, got {events[-1]}"
        print(f"  ✅ Dialogue turn: {len(events)} events ({events[-1]['turnsUsed']} turn used)")


def test_dialogue_turn_limit():
    """POST /dreams/:id/dialogue — 10 turn limit, expect 400 on 11th."""
    client_id = _register_client()
    dream_id = _create_dream(client_id)

    for i in range(10):
        with httpx.Client() as client:
            resp = client.post(
                f"{BASE}/dreams/{dream_id}/dialogue",
                json={"message": f"Turn {i + 1}"},
                headers=_auth_headers(client_id),
            )
            assert resp.status_code == 200, f"Failed on turn {i + 1}: {resp.status_code}"

    # 11th turn should fail
    resp = httpx.post(
        f"{BASE}/dreams/{dream_id}/dialogue",
        json={"message": "One too many"},
        headers=_auth_headers(client_id),
    )
    assert resp.status_code == 400, f"Expected 400, got {resp.status_code}"
    print(f"  ✅ Turn limit enforced (400 on 11th turn)")


def test_dialogue_complete():
    """POST /dreams/:id/dialogue/complete — mark dialogue complete."""
    client_id = _register_client()
    dream_id = _create_dream(client_id)

    # Do one turn first
    httpx.post(
        f"{BASE}/dreams/{dream_id}/dialogue",
        json={"message": "I felt both scared and exhilarated."},
        headers=_auth_headers(client_id),
    )

    resp = httpx.post(
        f"{BASE}/dreams/{dream_id}/dialogue/complete",
        headers=_auth_headers(client_id),
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert "groundedAt" in data
    print(f"  ✅ Dialogue completed: groundedAt={data['groundedAt']}")


def test_dialogue_complete_already_done():
    """POST /dreams/:id/dialogue/complete — already complete, expect 400."""
    client_id = _register_client()
    dream_id = _create_dream(client_id)

    httpx.post(
        f"{BASE}/dreams/{dream_id}/dialogue",
        json={"message": "Hello"},
        headers=_auth_headers(client_id),
    )
    httpx.post(
        f"{BASE}/dreams/{dream_id}/dialogue/complete",
        headers=_auth_headers(client_id),
    )
    # Second complete should fail
    resp = httpx.post(
        f"{BASE}/dreams/{dream_id}/dialogue/complete",
        headers=_auth_headers(client_id),
    )
    assert resp.status_code == 400, f"Expected 400, got {resp.status_code}"
    print(f"  ✅ Double complete rejected (400)")


def test_dialogue_after_complete_blocked():
    """POST /dreams/:id/dialogue — after complete, expect 400."""
    client_id = _register_client()
    dream_id = _create_dream(client_id)

    httpx.post(
        f"{BASE}/dreams/{dream_id}/dialogue",
        json={"message": "Hello"},
        headers=_auth_headers(client_id),
    )
    httpx.post(
        f"{BASE}/dreams/{dream_id}/dialogue/complete",
        headers=_auth_headers(client_id),
    )
    resp = httpx.post(
        f"{BASE}/dreams/{dream_id}/dialogue",
        json={"message": "Can I still talk?"},
        headers=_auth_headers(client_id),
    )
    assert resp.status_code == 400, f"Expected 400, got {resp.status_code}"
    print(f"  ✅ Dialogue after complete blocked (400)")


def main():
    print("\n=== Dialogue Tests ===\n")
    test_dialogue_turn()
    test_dialogue_turn_limit()
    test_dialogue_complete()
    test_dialogue_complete_already_done()
    test_dialogue_after_complete_blocked()
    print("\n✅ All dialogue tests passed!\n")


if __name__ == "__main__":
    main()
