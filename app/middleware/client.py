"""Client identity middleware — resolves client_id from X-Client-Id header."""

import logging
from uuid import UUID

from fastapi import Depends, Header, HTTPException

from app.db import upsert_client

logger = logging.getLogger(__name__)


async def resolve_client(
    x_client_id: UUID = Header(..., alias="X-Client-Id"),
) -> dict:
    """
    Resolve a client from the X-Client-Id header.

    Performs a single idempotent upsert: it auto-creates the client row if it
    doesn't exist yet and refreshes last_seen_at in the same query. The client_id
    is a random UUID minted on the device, so trusting it and lazily materializing
    the row carries the same privacy/durability properties as a separate
    registration step — but without the extra round-trip or the "Unknown client"
    lockout failure mode.
    """
    return dict(await upsert_client(x_client_id))


def require_tier(min_tier: str):
    """Dependency factory: require a minimum tier to access an endpoint."""
    async def check(client: dict = Depends(resolve_client)):
        if min_tier == "pro" and client.get("tier") != "pro":
            raise HTTPException(
                status_code=402,
                detail=f"{min_tier.capitalize()} subscription required",
            )
        return client
    return check
