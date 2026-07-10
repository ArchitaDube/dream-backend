"""Dialogue endpoints — SSE streaming dialogue turns."""

import json
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.db import (
    complete_dialogue,
    get_dream,
    get_or_create_dialogue,
    update_dialogue_history,
)
from app.middleware.client import resolve_client
from app.middleware.rate_limit import check_rate_limit
from app.prompts.dialogue import build_dialogue_prompt
from app.services.llm import llm

logger = logging.getLogger(__name__)
router = APIRouter()


class DialogueRequest(BaseModel):
    message: str


@router.post("/dreams/{dream_id}/dialogue")
async def dialogue_turn(
    dream_id: str,
    body: DialogueRequest,
    client: dict = Depends(resolve_client),
):
    """Submit a dialogue turn. Returns the facilitator's response as SSE stream."""
    client_id = client["client_id"]

    # Rate limit check
    await check_rate_limit(client_id, "dialogue", client.get("tier") == "pro")

    # Fetch dream
    dream = await get_dream(dream_id, client_id)
    if not dream:
        raise HTTPException(status_code=404, detail="Dream not found")

    # Get or create dialogue
    dialogue = await get_or_create_dialogue(dream_id, client_id)

    # Check if dialogue is already complete
    if dialogue.get("grounded_at"):
        raise HTTPException(
            status_code=400,
            detail="Dialogue already complete. Proceed to analysis.",
        )

    # Check turn limit (max 6 turns)
    history = dialogue.get("history") or []
    turn_count = len(history) // 2
    if turn_count >= 6:
        raise HTTPException(status_code=400, detail="Dialogue limit reached.")

    # Append user message
    new_history = history + [{"role": "user", "content": body.message}]

    async def event_stream():
        full_response = ""

        try:
            async for token in llm.stream_completion(
                messages=new_history,
                system=build_dialogue_prompt(dream["body"], turn_count),
            ):
                full_response += token
                yield f"data: {json.dumps({'type': 'token', 'value': token})}\n\n"

            # Persist completed turn
            final_history = new_history + [{"role": "assistant", "content": full_response}]
            await update_dialogue_history(dialogue["id"], final_history)

            turns_used = turn_count + 1
            yield f"data: {json.dumps({
                'type': 'done',
                'turnsUsed': turns_used,
                'turnsRemaining': 6 - turns_used,
            })}\n\n"

        except Exception as e:
            logger.error("Dialogue stream error: %s", str(e))
            yield f"data: {json.dumps({'type': 'error', 'message': 'An error occurred'})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


class DialogueCompleteResponse(BaseModel):
    groundedAt: str


@router.post("/dreams/{dream_id}/dialogue/complete")
async def dialogue_complete(
    dream_id: str,
    client: dict = Depends(resolve_client),
) -> dict:
    """Mark dialogue as complete. Unlocks the analyze endpoint."""
    grounded_at = await complete_dialogue(dream_id, client["client_id"])
    if not grounded_at:
        raise HTTPException(
            status_code=400,
            detail="Dialogue already marked complete.",
        )
    return {"groundedAt": grounded_at.isoformat()}
