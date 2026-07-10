"""Image generation endpoint."""

import logging

from fastapi import APIRouter, Depends, HTTPException

from app.db import get_dream, update_dream_image
from app.middleware.client import require_tier, resolve_client
from app.services.image_gen import generate_dream_image

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/dreams/{dream_id}/image")
async def generate_image(
    dream_id: str,
    client: dict = Depends(require_tier("pro")),
) -> dict:
    """Generate an image for a dream. Pro tier only."""
    dream = await get_dream(dream_id, client["client_id"])
    if not dream:
        raise HTTPException(status_code=404, detail="Dream not found")

    if not dream.get("analysis"):
        raise HTTPException(
            status_code=400,
            detail="Dream must be analyzed before generating an image.",
        )

    image_url = await generate_dream_image(dream["body"], dream["analysis"])
    await update_dream_image(dream_id, image_url)

    return {"imageUrl": image_url}
