"""Symbol enrichment service — Jungian amplification of dream symbols.

For each charged symbol the analysis named, this builds a display card by
*amplifying* the symbol the way an analyst would, rather than scraping a search
snippet. The card combines:

* a VERIFIED ANCHOR — the etymological root (Wiktionary) and an attested mythic
  motif (curated lexicon), reusing the grounding already fetched for the
  analysis prompt where possible;
* a structured AMPLIFICATION from one LLM pass: the collective (mythic/religious/
  alchemical) parallels, the personal resonance for this dreamer (read from the
  dialogue), the compensatory function, the felt valence, related Jungian
  archetypes (from the canonical 14), and an active-imagination question.

The anchor is the factual substrate the amplifier is bound to (anti-fabrication).
The symbol → archetype lexicon and the etymology fetcher live in
``app.services.grounding`` so the prompt-injection path and this display path
share one source of truth.
"""

import asyncio
import logging
from typing import Any

import httpx

from app.prompts.amplification import (
    build_amplification_prompt,
    parse_amplification_response,
)
from app.services.archetypes import ARCHETYPE_ID_SET
from app.services.grounding import (
    SYMBOL_ARCHETYPE_MAP,
    SYMBOL_MOTIFS,
    fetch_etymology,
)
from app.services.llm import llm

logger = logging.getLogger(__name__)

TIMEOUT = 10.0
HEADERS = {
    "User-Agent": "Oneiros/1.0 (dream analysis app; https://oneiros.app; contact@oneiros.app)",
    "Accept": "application/json",
}

MAX_SYMBOLS = 4


async def enrich_symbols(
    symbols: list[dict[str, Any]],
    grounding: list[dict[str, Any]] | None = None,
    dream_body: str = "",
    dialogue_summary: str = "",
) -> list[dict[str, Any]]:
    """Build amplified display cards for up to 4 symbols.

    Args:
        symbols: charged symbols from the analysis, each {name, meaning}.
        grounding: optional pre-fetched grounding entries from
            ``gather_grounding`` — reused for etymology + motif + seed archetypes
            so we don't refetch.
        dream_body: the dream text (objective context for amplification).
        dialogue_summary: the dreamer's own associations (subjective material).

    Returns:
        List of SymbolArchetype dicts: name, meaning, etymology, etymologyUrl,
        motif, collectiveAmplification, personalResonance, compensation,
        valence, activeImaginationPrompt, relatedArchetypes.
    """
    if not symbols:
        return []

    top_symbols = [s for s in symbols[:MAX_SYMBOLS] if s.get("name")]
    if not top_symbols:
        return []

    grounding_by_name = {
        (g.get("name") or "").lower(): g for g in (grounding or [])
    }

    # ── 1. Verified anchors (etymology + motif), reused or fetched ──
    anchors = await _gather_anchors(top_symbols, grounding_by_name)

    # ── 2. One structured amplification pass over all symbols ──
    amplifications = await _amplify(top_symbols, dream_body, dialogue_summary, anchors)

    # ── 3. Assemble cards (anchor + amplification), with anchor-only fallback ──
    results: list[dict[str, Any]] = []
    for symbol in top_symbols:
        results.append(
            _assemble_card(symbol, anchors, amplifications, grounding_by_name)
        )
    return results


async def _gather_anchors(
    symbols: list[dict[str, Any]],
    grounding_by_name: dict[str, dict[str, Any]],
) -> dict[str, dict[str, str]]:
    """Collect {name_lower: {etymology, etymologyUrl, motif}} for each symbol.

    Reuses grounding entries; only fetches etymology for symbols not already
    grounded (e.g. an image the analysis named that isn't in the lexicon).
    """
    anchors: dict[str, dict[str, str]] = {}
    to_fetch: list[str] = []

    for symbol in symbols:
        key = (symbol.get("name") or "").lower()
        pre = grounding_by_name.get(key, {})
        motif = pre.get("motif") or SYMBOL_MOTIFS.get(key, "")
        if pre.get("etymology"):
            anchors[key] = {
                "etymology": pre["etymology"],
                "etymologyUrl": pre.get("etymologyUrl") or "",
                "motif": motif,
            }
        else:
            anchors[key] = {"etymology": "", "etymologyUrl": "", "motif": motif}
            to_fetch.append(key)

    if to_fetch:
        async with httpx.AsyncClient(timeout=TIMEOUT, headers=HEADERS) as client:
            fetched = await asyncio.gather(
                *(fetch_etymology(client, key) for key in to_fetch),
                return_exceptions=True,
            )
        for key, result in zip(to_fetch, fetched):
            if isinstance(result, Exception):
                logger.debug("Etymology fetch failed for '%s': %s", key, result)
                continue
            etymology, ety_url = result
            anchors[key]["etymology"] = etymology
            anchors[key]["etymologyUrl"] = ety_url or ""

    return anchors


async def _amplify(
    symbols: list[dict[str, Any]],
    dream_body: str,
    dialogue_summary: str,
    anchors: dict[str, dict[str, str]],
) -> dict[str, dict[str, Any]]:
    """Run the single structured amplification pass. Never raises — returns {}
    on any failure so the caller falls back to anchor-only cards.
    """
    try:
        prompt = build_amplification_prompt(
            symbols, dream_body, dialogue_summary, anchors
        )
        raw = await llm.structured_completion(
            messages=[{"role": "user", "content": "Amplify these dream symbols."}],
            system=prompt,
            temperature=0.5,
        )
        return parse_amplification_response(raw)
    except Exception as e:
        logger.warning("Symbol amplification pass failed: %s", str(e))
        return {}


def _assemble_card(
    symbol: dict[str, Any],
    anchors: dict[str, dict[str, str]],
    amplifications: dict[str, dict[str, Any]],
    grounding_by_name: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Merge the verified anchor with the LLM amplification into one card."""
    name = symbol.get("name", "")
    key = name.lower()
    anchor = anchors.get(key, {})
    pre = grounding_by_name.get(key, {})

    # Match amplification by name (case-insensitive) — models sometimes echo a
    # differently-cased key.
    amp = amplifications.get(name) or _match_ci(amplifications, name) or {}

    seed_archetypes = pre.get("relatedArchetypes") or SYMBOL_ARCHETYPE_MAP.get(key, [])
    related = _coerce_archetypes(amp.get("relatedArchetypes")) or seed_archetypes

    return {
        "name": name,
        "meaning": symbol.get("meaning", ""),
        "etymology": anchor.get("etymology", ""),
        "etymologyUrl": anchor.get("etymologyUrl") or None,
        "motif": anchor.get("motif", ""),
        "collectiveAmplification": _clean_str(amp.get("collectiveAmplification")),
        "personalResonance": _clean_str(amp.get("personalResonance")),
        "compensation": _clean_str(amp.get("compensation")),
        "valence": _clean_str(amp.get("valence")),
        "activeImaginationPrompt": _clean_str(amp.get("activeImaginationPrompt")),
        "relatedArchetypes": related,
    }


def _match_ci(amplifications: dict[str, dict[str, Any]], name: str) -> dict[str, Any] | None:
    lname = name.lower()
    for k, v in amplifications.items():
        if k.lower() == lname:
            return v
    return None


def _coerce_archetypes(value: Any) -> list[str]:
    """Keep only valid canonical archetype ids, deduped, max 3."""
    if not isinstance(value, list):
        return []
    seen: list[str] = []
    for item in value:
        aid = str(item).strip().lower()
        if aid in ARCHETYPE_ID_SET and aid not in seen:
            seen.append(aid)
    return seen[:3]


def _clean_str(value: Any) -> str:
    return str(value).strip() if isinstance(value, (str, int, float)) else ""
