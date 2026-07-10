"""Tests for image generation endpoint."""

import pytest
from httpx import AsyncClient

from tests.test_db import get_mock_db


@pytest.mark.asyncio
async def test_generate_image_free_tier_blocked(client: AsyncClient, auth_headers: dict, test_client_id: str):
    """Image generation should be blocked for free tier."""
    await client.post("/clients", json={"client_id": test_client_id})

    create_resp = await client.post(
        "/dreams", json={"body": "A dream image."}, headers=auth_headers
    )
    dream_id = create_resp.json()["dream"]["id"]

    response = await client.post(
        f"/dreams/{dream_id}/image",
        headers=auth_headers,
    )
    assert response.status_code == 402
    assert "subscription required" in response.text


@pytest.mark.asyncio
async def test_generate_image_no_analysis(client: AsyncClient, test_client_id: str):
    """Image generation should require analysis to exist."""
    # Register as pro
    await client.post("/clients", json={"client_id": test_client_id})

    # Manually upgrade to pro in mock DB
    mock_db = get_mock_db()
    mock_db.clients[test_client_id]["tier"] = "pro"

    create_resp = await client.post(
        "/dreams", json={"body": "Image without analysis."},
        headers={"X-Client-Id": test_client_id},
    )
    dream_id = create_resp.json()["dream"]["id"]

    response = await client.post(
        f"/dreams/{dream_id}/image",
        headers={"X-Client-Id": test_client_id},
    )
    assert response.status_code == 400
    assert "must be analyzed" in response.text
