"""Tests for analysis SSE streaming endpoint."""

import json

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_analyze_dream(client: AsyncClient, auth_headers: dict, test_client_id: str):
    """GET /dreams/:id/analyze should stream analysis events."""
    await client.post("/clients", json={"client_id": test_client_id})

    # Create dream
    create_resp = await client.post(
        "/dreams", json={"body": "A vast ocean under a blood moon."}, headers=auth_headers
    )
    dream_id = create_resp.json()["dream"]["id"]

    # Complete dialogue first
    await client.post(f"/dreams/{dream_id}/dialogue/complete", headers=auth_headers)

    # Analyze
    response = await client.get(f"/dreams/{dream_id}/analyze", headers=auth_headers)
    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]

    # Parse SSE events
    events = []
    for line in response.text.strip().split("\n"):
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))

    # Should have token events and a done event with analysis
    done_events = [e for e in events if e["type"] == "done"]
    assert len(done_events) == 1
    assert "analysis" in done_events[0]


@pytest.mark.asyncio
async def test_analyze_without_dialogue(client: AsyncClient, auth_headers: dict, test_client_id: str):
    """Analysis should be blocked if dialogue is not complete."""
    await client.post("/clients", json={"client_id": test_client_id})

    create_resp = await client.post(
        "/dreams", json={"body": "No dialogue yet."}, headers=auth_headers
    )
    dream_id = create_resp.json()["dream"]["id"]

    response = await client.get(f"/dreams/{dream_id}/analyze", headers=auth_headers)
    assert response.status_code == 400
    assert "Complete the dialogue" in response.text


@pytest.mark.asyncio
async def test_analyze_dream_not_found(client: AsyncClient, auth_headers: dict, test_client_id: str):
    """Analysis should return 404 for non-existent dream."""
    await client.post("/clients", json={"client_id": test_client_id})

    response = await client.get("/dreams/drm_nonexistent/analyze", headers=auth_headers)
    assert response.status_code == 404
