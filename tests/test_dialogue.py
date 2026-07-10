"""Tests for dialogue SSE streaming endpoint."""

import json

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_dialogue_turn(client: AsyncClient, auth_headers: dict, test_client_id: str):
    """POST /dreams/:id/dialogue should stream tokens and a done event."""
    await client.post("/clients", json={"client_id": test_client_id})

    # Create a dream first
    create_resp = await client.post(
        "/dreams", json={"body": "A test dream for dialogue."}, headers=auth_headers
    )
    dream_id = create_resp.json()["dream"]["id"]

    # Send a dialogue turn
    response = await client.post(
        f"/dreams/{dream_id}/dialogue",
        json={"message": "Tell me about this dream."},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]

    # Parse SSE events
    events = []
    for line in response.text.strip().split("\n"):
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))

    # Should have token events and a done event
    token_events = [e for e in events if e["type"] == "token"]
    done_events = [e for e in events if e["type"] == "done"]
    assert len(token_events) > 0
    assert len(done_events) == 1
    assert done_events[0]["turnsUsed"] == 1
    assert done_events[0]["turnsRemaining"] == 9


@pytest.mark.asyncio
async def test_dialogue_turn_limit(client: AsyncClient, auth_headers: dict, test_client_id: str):
    """Dialogue should enforce a 10-turn limit."""
    await client.post("/clients", json={"client_id": test_client_id})

    create_resp = await client.post(
        "/dreams", json={"body": "Dialogue limit test."}, headers=auth_headers
    )
    dream_id = create_resp.json()["dream"]["id"]

    # Use all 10 turns
    for i in range(10):
        resp = await client.post(
            f"/dreams/{dream_id}/dialogue",
            json={"message": f"Turn {i + 1}"},
            headers=auth_headers,
        )
        assert resp.status_code == 200

    # 11th should fail
    response = await client.post(
        f"/dreams/{dream_id}/dialogue",
        json={"message": "One more turn"},
        headers=auth_headers,
    )
    assert response.status_code == 400
    assert "Dialogue limit reached" in response.text


@pytest.mark.asyncio
async def test_dialogue_complete(client: AsyncClient, auth_headers: dict, test_client_id: str):
    """POST /dreams/:id/dialogue/complete should mark dialogue as complete."""
    await client.post("/clients", json={"client_id": test_client_id})

    create_resp = await client.post(
        "/dreams", json={"body": "Complete test."}, headers=auth_headers
    )
    dream_id = create_resp.json()["dream"]["id"]

    # Complete dialogue
    response = await client.post(
        f"/dreams/{dream_id}/dialogue/complete",
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert "groundedAt" in response.json()


@pytest.mark.asyncio
async def test_dialogue_complete_already_done(client: AsyncClient, auth_headers: dict, test_client_id: str):
    """Completing an already-complete dialogue should return 400."""
    await client.post("/clients", json={"client_id": test_client_id})

    create_resp = await client.post(
        "/dreams", json={"body": "Already done."}, headers=auth_headers
    )
    dream_id = create_resp.json()["dream"]["id"]

    await client.post(f"/dreams/{dream_id}/dialogue/complete", headers=auth_headers)
    response = await client.post(
        f"/dreams/{dream_id}/dialogue/complete",
        headers=auth_headers,
    )
    assert response.status_code == 400
    assert "already marked complete" in response.text


@pytest.mark.asyncio
async def test_dialogue_after_complete_blocked(client: AsyncClient, auth_headers: dict, test_client_id: str):
    """Dialogue turns should be blocked after dialogue is complete."""
    await client.post("/clients", json={"client_id": test_client_id})

    create_resp = await client.post(
        "/dreams", json={"body": "Blocked after complete."}, headers=auth_headers
    )
    dream_id = create_resp.json()["dream"]["id"]

    await client.post(f"/dreams/{dream_id}/dialogue/complete", headers=auth_headers)

    response = await client.post(
        f"/dreams/{dream_id}/dialogue",
        json={"message": "Should be blocked"},
        headers=auth_headers,
    )
    assert response.status_code == 400
    assert "already complete" in response.text
