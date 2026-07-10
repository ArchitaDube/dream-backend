"""Tests for client registration endpoint."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_register_client(client: AsyncClient, test_client_id: str):
    """POST /clients should register a new client and return tier + createdAt."""
    response = await client.post(
        "/clients",
        json={"client_id": test_client_id},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["client_id"] == test_client_id
    assert data["tier"] == "free"
    assert "createdAt" in data


@pytest.mark.asyncio
async def test_register_client_upsert(client: AsyncClient, test_client_id: str):
    """POST /clients should be idempotent (upsert)."""
    # Register twice
    r1 = await client.post("/clients", json={"client_id": test_client_id})
    r2 = await client.post("/clients", json={"client_id": test_client_id})
    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r1.json()["client_id"] == r2.json()["client_id"]


@pytest.mark.asyncio
async def test_register_client_invalid_uuid(client: AsyncClient):
    """POST /clients with invalid UUID should return 422."""
    response = await client.post(
        "/clients",
        json={"client_id": "not-a-uuid"},
    )
    assert response.status_code == 422
