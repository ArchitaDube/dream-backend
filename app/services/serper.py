"""Serper client — Google SERP results for symbol context grounding.

Free tier requires an API key (``SERPER_API_KEY``). Supports batch search: a
single POST with a JSON array of query objects returns an array of result sets
in the same order, so all of a dream's symbol queries cost one round trip.

If no key is configured the client is a no-op (returns []), and callers fall
back to the free Wikipedia/DuckDuckGo path.
"""

import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

SERPER_URL = "https://google.serper.dev/search"
TIMEOUT = 30.0


def is_configured() -> bool:
    """True when a usable Serper API key is present."""
    key = settings.serper_api_key
    return bool(key) and not key.startswith("your")


async def search_batch(queries: list[str], num: int = 3) -> list[dict[str, Any]]:
    """Run many queries in one batched Serper request.

    Returns a list of result objects aligned to ``queries`` order. Empty list on
    any failure or when unconfigured — never raises.

    Note: Serper's free tier can be slow on batched requests. If you see
    repeated ConnectTimeout errors, reduce the batch size or switch to
    individual ``search_single`` calls.
    """
    if not queries or not is_configured():
        return []

    payload = [{"q": q, "num": num} for q in queries]
    headers = {
        "X-API-KEY": settings.serper_api_key,
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(SERPER_URL, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as e:
        body = ""
        try:
            body = e.response.text[:500]
        except Exception:
            pass
        logger.warning(
            "Serper batch search failed: HTTP %s — %s",
            e.response.status_code, body or str(e),
        )
        return []
    except Exception as e:
        logger.warning("Serper batch search error: %s", str(e), exc_info=True)
        return []

    if isinstance(data, list):
        return data
    # A single-query request returns a bare object, not an array.
    return [data]


async def search_single(query: str, num: int = 3) -> dict[str, Any]:
    """Run a single Serper search query. Returns the result dict or {} on failure."""
    if not query or not is_configured():
        return {}

    headers = {
        "X-API-KEY": settings.serper_api_key,
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(
                SERPER_URL, headers=headers, json={"q": query, "num": num},
            )
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as e:
        body = ""
        try:
            body = e.response.text[:500]
        except Exception:
            pass
        logger.warning(
            "Serper single search failed: HTTP %s — %s",
            e.response.status_code, body or str(e),
        )
    except Exception as e:
        logger.warning("Serper single search error: %s", str(e), exc_info=True)
    return {}


# Domains that tend to host reductive "dream dictionary" listicle content —
# the opposite of amplification. Deprioritised when picking a snippet.
_LOW_QUALITY_HINTS = (
    "dreammeaning", "dream-meaning", "dreamdictionary", "dreamastromeaning",
    "auntyflo", "dreamingandsleeping", "whatdreamsmean", "dreamglossary",
)


def extract_context(result: dict[str, Any]) -> tuple[str, str | None]:
    """Pull the best context snippet + source link from one Serper result set.

    Prefers a knowledge-graph description, then an answer box, then the highest
    organic result that isn't an obvious dream-dictionary domain.
    """
    if not isinstance(result, dict):
        return "", None

    kg = result.get("knowledgeGraph") or {}
    if kg.get("description"):
        link = kg.get("descriptionLink") or kg.get("website")
        return _clip(kg["description"]), link

    ab = result.get("answerBox") or {}
    ab_text = ab.get("snippet") or ab.get("answer")
    if ab_text:
        return _clip(ab_text), ab.get("link")

    organic = result.get("organic") or []
    # First pass: skip low-quality dream-dictionary domains.
    for o in organic:
        link = (o.get("link") or "").lower()
        if o.get("snippet") and not any(h in link for h in _LOW_QUALITY_HINTS):
            return _clip(o["snippet"]), o.get("link")
    # Fallback: take whatever has a snippet.
    for o in organic:
        if o.get("snippet"):
            return _clip(o["snippet"]), o.get("link")

    return "", None


def _clip(text: str, limit: int = 600) -> str:
    text = " ".join(text.split())
    if len(text) > limit:
        text = text[: limit - 3].rstrip() + "..."
    return text
