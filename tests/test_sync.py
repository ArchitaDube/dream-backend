"""Tests for sync (backup/restore) endpoints."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_sync_init(client: AsyncClient, auth_headers: dict, test_client_id: str):
    """POST /sync/init should create a backup and return a mnemonic phrase."""
    await client.post("/clients", json={"client_id": test_client_id})

    # Create a dream first
    await client.post(
        "/dreams", json={"body": "Backup this dream."}, headers=auth_headers
    )

    response = await client.post("/sync/init", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert "phrase" in data
    assert len(data["phrase"]) == 12  # 12-word BIP-39
    assert "encryptedPayload" in data


@pytest.mark.asyncio
async def test_sync_restore(client: AsyncClient, auth_headers: dict, test_client_id: str):
    """POST /sync/restore should restore dreams from a phrase."""
    await client.post("/clients", json={"client_id": test_client_id})

    # Create a dream and backup
    await client.post(
        "/dreams", json={"body": "Dream to restore."}, headers=auth_headers
    )
    init_resp = await client.post("/sync/init", headers=auth_headers)
    phrase = init_resp.json()["phrase"]

    # Restore
    response = await client.post(
        "/sync/restore",
        json={"phrase": phrase},
    )
    assert response.status_code == 200
    data = response.json()
    assert "client_id" in data
    assert "dreams" in data
    assert len(data["dreams"]) >= 1


@pytest.mark.asyncio
async def test_sync_restore_invalid_phrase(client: AsyncClient):
    """POST /sync/restore with invalid phrase should return 404."""
    response = await client.post(
        "/sync/restore",
        json={"phrase": ["invalid", "phrase", "words"]},
    )
    assert response.status_code == 404
    assert "No backup found" in response.text
