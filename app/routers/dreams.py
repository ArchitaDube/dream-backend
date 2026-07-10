"""Dream CRUD endpoints."""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.db import (
    create_dream,
    delete_dream,
    get_dialogue_for_dream,
    get_dialogues_for_dreams,
    get_dream,
    get_dream_count,
    list_dreams,
)
from app.middleware.client import resolve_client

logger = logging.getLogger(__name__)

router = APIRouter()


class CreateDreamRequest(BaseModel):
    body: str
    title: str | None = None


def _serialize_dream(row: dict, dialogue: dict | None) -> dict:
    """Serialize a dream DB row to the API response format, including dialogue state.

    The caller supplies the (already-loaded) dialogue so that listing many dreams
    doesn't fan out into one query per dream.
    """
    turns_used = 0
    grounded_at = None
    if dialogue:
        history = dialogue.get("history") or []
        turns_used = len(history) // 2
        grounded_at = dialogue.get("grounded_at")
    return {
        "id": row["id"],
        "title": row.get("title"),
        "body": row["body"],
        "createdAt": row["created_at"].isoformat(),
        "analyzedAt": row["analyzed_at"].isoformat() if row.get("analyzed_at") else None,
        "analysis": row.get("analysis"),
        "extraction": row.get("extraction"),
        "imageUrl": row.get("image_url"),
        "tags": row.get("tags") or [],
        "mood": row.get("mood"),
        "dialogueState": {
            "turnsUsed": turns_used,
            "turnsRemaining": max(0, 6 - turns_used),
            "groundedAt": grounded_at.isoformat() if grounded_at else None,
        },
    }


@router.post("/dreams", status_code=201)
async def create_dream_endpoint(
    body: CreateDreamRequest,
    client: dict = Depends(resolve_client),
) -> dict:
    """Create a new dream entry."""
    client_id = client["client_id"]
    logger.info("create_dream_endpoint: client_id=%s body_len=%d", client_id, len(body.body))

    # Check free tier limit (10 dreams max)
    count = await get_dream_count(client_id)
    logger.info("create_dream_endpoint: dream_count=%d tier=%s", count, client.get("tier"))
    if client.get("tier") == "free" and count >= 10:
        raise HTTPException(
            status_code=403,
            detail="Dream limit reached. Upgrade to Pro for unlimited dreams.",
        )

    import nanoid
    dream_id = "drm_" + nanoid.generate(size=10)
    row = await create_dream(dream_id, client_id, body.body, body.title)
    logger.info("create_dream_endpoint: created dream_id=%s", dream_id)
    # A freshly created dream has no dialogue yet.
    return {"dream": _serialize_dream(dict(row), None)}


@router.get("/dreams")
async def list_dreams_endpoint(
    client: dict = Depends(resolve_client),
) -> dict:
    """List all dreams for the authenticated client."""
    rows = await list_dreams(client["client_id"])
    # Batch-load all dialogues in one query instead of one-per-dream (N+1).
    dialogues = await get_dialogues_for_dreams([r["id"] for r in rows])
    serialized = [_serialize_dream(dict(r), dialogues.get(r["id"])) for r in rows]
    return {"dreams": serialized}


@router.get("/dreams/{dream_id}")
async def get_dream_endpoint(
    dream_id: str,
    client: dict = Depends(resolve_client),
) -> dict:
    """Get a single dream by ID."""
    row = await get_dream(dream_id, client["client_id"])
    if not row:
        raise HTTPException(status_code=404, detail="Dream not found")
    dialogue = await get_dialogue_for_dream(dream_id)
    return {"dream": _serialize_dream(dict(row), dialogue)}


@router.delete("/dreams/{dream_id}", status_code=204)
async def delete_dream_endpoint(
    dream_id: str,
    client: dict = Depends(resolve_client),
) -> None:
    """Delete a dream by ID."""
    deleted = await delete_dream(dream_id, client["client_id"])
    if not deleted:
        raise HTTPException(status_code=404, detail="Dream not found")
