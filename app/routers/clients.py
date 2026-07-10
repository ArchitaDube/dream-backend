"""Client registration endpoint."""

import logging
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel

from app.db import upsert_client

logger = logging.getLogger(__name__)

router = APIRouter()


class RegisterClientRequest(BaseModel):
    client_id: UUID


class RegisterClientResponse(BaseModel):
    client_id: UUID
    tier: str
    created_at: str


@router.post("/clients", status_code=201)
async def register_client(body: RegisterClientRequest) -> dict:
    """Register a new client (upsert — safe to call multiple times)."""
    logger.info("register_client called with client_id=%s", body.client_id)
    row = await upsert_client(body.client_id)
    logger.info("register_client: upserted client_id=%s tier=%s", body.client_id, row.get("tier"))
    return {
        "client_id": str(row["client_id"]),
        "tier": row["tier"],
        "createdAt": row["created_at"].isoformat(),
    }
