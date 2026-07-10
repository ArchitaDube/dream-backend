"""Tests for dream CRUD endpoints."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_dream(client: AsyncClient, auth_headers: dict, test_client_id: str):
    """POST /dreams should create a dream and return it."""
    # First register the client
    await client.post("/clients", json={"client_id": test_client_id})

    response = await client.post(
        "/dreams",
        json={"body": "I was flying over a vast ocean.", "title": "The Flight"},
        headers=auth_headers,
    )
    assert response.status_code == 201
    data = response.json()
    assert "dream" in data
    dream = data["dream"]
    assert dream["body"] == "I was flying over a vast ocean."
    assert dream["title"] == "The Flight"
    assert dream["id"].startswith("drm_")
    assert dream["dialogueState"]["turnsUsed"] == 0
    assert dream["dialogueState"]["turnsRemaining"] == 10


@pytest.mark.asyncio
async def test_create_dream_without_title(client: AsyncClient, auth_headers: dict, test_client_id: str):
    """POST /dreams should work without a title."""
    await client.post("/clients", json={"client_id": test_client_id})

    response = await client.post(
        "/dreams",
        json={"body": "A dark forest with glowing eyes."},
        headers=auth_headers,
    )
    assert response.status_code == 201
    dream = response.json()["dream"]
    assert dream["title"] is None


@pytest.mark.asyncio
async def test_list_dreams(client: AsyncClient, auth_headers: dict, test_client_id: str):
    """GET /dreams should list all dreams for the client."""
    await client.post("/clients", json={"client_id": test_client_id})

    # Create two dreams
    await client.post("/dreams", json={"body": "Dream one"}, headers=auth_headers)
    await client.post("/dreams", json={"body": "Dream two"}, headers=auth_headers)

    response = await client.get("/dreams", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data["dreams"]) == 2


@pytest.mark.asyncio
async def test_get_dream(client: AsyncClient, auth_headers: dict, test_client_id: str):
    """GET /dreams/:id should return a single dream."""
    await client.post("/clients", json={"client_id": test_client_id})

    create_resp = await client.post(
        "/dreams", json={"body": "Test dream"}, headers=auth_headers
    )
    dream_id = create_resp.json()["dream"]["id"]

    response = await client.get(f"/dreams/{dream_id}", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["dream"]["id"] == dream_id


@pytest.mark.asyncio
async def test_get_dream_not_found(client: AsyncClient, auth_headers: dict, test_client_id: str):
    """GET /dreams/:id should return 404 for non-existent dream."""
    await client.post("/clients", json={"client_id": test_client_id})

    response = await client.get("/dreams/drm_nonexistent", headers=auth_headers)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_dream(client: AsyncClient, auth_headers: dict, test_client_id: str):
    """DELETE /dreams/:id should delete a dream."""
    await client.post("/clients", json={"client_id": test_client_id})

    create_resp = await client.post(
        "/dreams", json={"body": "Delete me"}, headers=auth_headers
    )
    dream_id = create_resp.json()["dream"]["id"]

    response = await client.delete(f"/dreams/{dream_id}", headers=auth_headers)
    assert response.status_code == 204

    # Verify it's gone
    get_resp = await client.get(f"/dreams/{dream_id}", headers=auth_headers)
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_dream_not_found(client: AsyncClient, auth_headers: dict, test_client_id: str):
    """DELETE /dreams/:id should return 404 for non-existent dream."""
    await client.post("/clients", json={"client_id": test_client_id})

    response = await client.delete("/dreams/drm_nonexistent", headers=auth_headers)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_dream_limit_free_tier(client: AsyncClient, auth_headers: dict, test_client_id: str):
    """Free tier should be limited to 10 dreams."""
    await client.post("/clients", json={"client_id": test_client_id})

    # Create 10 dreams (the limit)
    for i in range(10):
        resp = await client.post(
            "/dreams", json={"body": f"Dream {i}"}, headers=auth_headers
        )
        assert resp.status_code == 201

    # 11th should fail
    response = await client.post(
        "/dreams", json={"body": "Too many"}, headers=auth_headers
    )
    assert response.status_code == 403
    assert "Dream limit reached" in response.text


@pytest.mark.asyncio
async def test_dreams_scoped_to_client(client: AsyncClient, test_client_id: str):
    """Dreams should be scoped per client — other clients can't see them."""
    other_id = "00000000-0000-0000-0000-000000000002"

    # Register both clients
    await client.post("/clients", json={"client_id": test_client_id})
    await client.post("/clients", json={"client_id": other_id})

    # Create dream for first client
    await client.post(
        "/dreams", json={"body": "Secret dream"},
        headers={"X-Client-Id": test_client_id},
    )

    # Second client should see 0 dreams
    response = await client.get(
        "/dreams", headers={"X-Client-Id": other_id}
    )
    assert len(response.json()["dreams"]) == 0
