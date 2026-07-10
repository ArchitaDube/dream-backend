"""Image generation via fal.ai (or Replicate fallback)."""

import logging
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)


async def generate_dream_image(dream_body: str, analysis: dict[str, Any]) -> str:
    """
    Generate an image from dream body + analysis.
    Returns a URL to the generated image.
    """
    prompt = _build_image_prompt(dream_body, analysis)

    if not settings.fal_key:
        logger.warning("FAL_KEY not set; returning placeholder URL")
        return "https://placehold.co/1024x576/1a1a2e/eaeaea?text=Dream+Image"

    try:
        import fal_client

        result = await fal_client.run(
            "fal-ai/flux/dev",
            arguments={
                "prompt": prompt,
                "image_size": "landscape_16_9",
                "num_inference_steps": 28,
            },
        )
        image_url = result["images"][0]["url"]
        return image_url
    except Exception as e:
        logger.error("Image generation failed: %s", str(e))
        return "https://placehold.co/1024x576/1a1a2e/eaeaea?text=Generation+Failed"


def _build_image_prompt(dream_body: str, analysis: dict[str, Any]) -> str:
    symbols = ", ".join(
        s["name"] for s in (analysis.get("symbols") or [])[:4]
    )
    mood = analysis.get("emotionalTone") or "dreamlike"
    return (
        f"A dreamlike scene: {dream_body[:200]}. "
        f"Symbolic elements: {symbols}. "
        f"Mood: {mood}. "
        "Aesthetic: ethereal, desaturated, soft pastels, cinematic, no text."
    )
