"""Prompt: Jungian *amplification* of a dream's charged symbols.

This replaces the old web-snippet enrichment. Given the dream, the dreamer's own
associations (from the dialogue), each charged symbol's role, and a VERIFIED
anchor (etymology + attested mythic motif), the model amplifies each symbol the
way a Jungian analyst would — gathering mythic/religious/alchemical parallels,
reading the personal (subjective) and collective (objective) levels, and naming
the compensatory function — while staying bound to the verified anchors so it
does not fabricate myth.

Output is strict JSON, one object per symbol, consumed by symbol_enricher.py.
"""

import json
import re
from typing import Any

from app.services.archetypes import archetype_catalog_lines

AMPLIFICATION_SYSTEM_PROMPT = """You are a Jungian analyst performing AMPLIFICATION on the charged symbols of a single dream. Amplification is not a dictionary lookup: you set each image beside its mythic, religious, and alchemical parallels and beside the dreamer's own associations, so its living meaning can emerge.

You are given, for each symbol: its role in THIS dream, the dreamer's own associations from the dialogue, and a VERIFIED ANCHOR (etymological root + attested mythic motif). You must work two levels at once:

* SUBJECTIVE / PERSONAL — what this image means for THIS dreamer, drawn from their associations and the symbol's behaviour in the dream.
* OBJECTIVE / COLLECTIVE — what the image has meant across myth, religion, and alchemy.

Hard rules:

* GROUNDING: factual mythic claims must build on the provided anchor (motif/etymology). If you introduce a parallel that is NOT in the anchor, hedge it ("in many traditions", "often") — never assert it as established fact. Invent nothing.
* ARCHETYPES: choose 1–3 related archetypes ONLY from this fixed set (use the exact id):
{archetype_catalog}
* Be concrete and specific to this dream. No generic dream-dictionary phrasing ("water represents emotions"). No therapy clichés.
* If the dreamer gave no associations for a symbol, infer the personal layer from the symbol's role in the dream and say so softly ("perhaps").

For EACH symbol return an object with these fields:

* "collectiveAmplification": 1–3 sentences of mythic/religious/alchemical parallels, grounded in the anchor.
* "personalResonance": 1–2 sentences on how the image functions for this dreamer (subjective level).
* "compensation": one sentence on the conscious attitude this image may be compensating or balancing.
* "valence": 2–4 words naming the felt charge (e.g. "numinous dread", "consoling warmth", "restless longing").
* "relatedArchetypes": array of 1–3 archetype ids from the fixed set above.
* "activeImaginationPrompt": one question the dreamer can carry into reflection.

Return ONLY a JSON object of this exact shape, using the symbol names EXACTLY as given:

{{"<symbol name>": {{"collectiveAmplification": "...", "personalResonance": "...", "compensation": "...", "valence": "...", "relatedArchetypes": ["..."], "activeImaginationPrompt": "..."}}}}

No prose, no markdown, no commentary outside the JSON.

Dream:
{dream_body}

Dreamer's own associations (from the dialogue):
{dialogue_summary}

Charged symbols and their verified anchors:
{symbol_blocks}"""


def _format_symbol_blocks(
    symbols: list[dict[str, Any]],
    anchors: dict[str, dict[str, str]],
) -> str:
    """Render each symbol with its in-dream role and verified anchor."""
    blocks: list[str] = []
    for s in symbols:
        name = (s.get("name") or "").strip()
        if not name:
            continue
        anchor = anchors.get(name.lower(), {})
        lines = [f"- {name} — role in dream: {s.get('meaning', '') or '(unstated)'}"]
        if anchor.get("etymology"):
            lines.append(f"    verified root (Wiktionary): {anchor['etymology']}")
        if anchor.get("motif"):
            lines.append(f"    attested mythic motif: {anchor['motif']}")
        if not anchor.get("etymology") and not anchor.get("motif"):
            lines.append("    (no external anchor — amplify only from parallels you are confident are real)")
        blocks.append("\n".join(lines))
    return "\n".join(blocks)


def build_amplification_prompt(
    symbols: list[dict[str, Any]],
    dream_body: str,
    dialogue_summary: str = "",
    anchors: dict[str, dict[str, str]] | None = None,
) -> str:
    """Build the amplification prompt.

    Args:
        symbols: charged symbols, each {name, meaning}.
        dream_body: the dream text.
        dialogue_summary: the dreamer's own associations (subjective material).
        anchors: {symbol_name_lower: {etymology, motif}} verified substrate.
    """
    return AMPLIFICATION_SYSTEM_PROMPT.format(
        archetype_catalog=archetype_catalog_lines(),
        dream_body=dream_body.strip() or "(dream text unavailable)",
        dialogue_summary=dialogue_summary.strip()
        or "(the dreamer has not shared associations yet)",
        symbol_blocks=_format_symbol_blocks(symbols, anchors or {}),
    )


_JSON_FENCE = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.DOTALL)
_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


def parse_amplification_response(raw: str) -> dict[str, dict[str, Any]]:
    """Parse the LLM JSON into {symbol_name: amplification}. Tolerant of noise.

    Accepts fenced JSON or a bare object embedded in prose. Returns {} on
    failure so the caller can fall back to anchor-only cards.
    """
    if not raw:
        return {}

    text = raw.strip()
    candidate = text
    fence = _JSON_FENCE.search(text)
    if fence:
        candidate = fence.group(1)
    else:
        obj = _JSON_OBJECT.search(text)
        if obj:
            candidate = obj.group(0)

    try:
        data = json.loads(candidate)
    except (json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}

    # Some models wrap under a top-level key (e.g. {"symbols": {...}}).
    if len(data) == 1:
        only = next(iter(data.values()))
        if isinstance(only, dict) and any(
            isinstance(v, dict) for v in only.values()
        ):
            data = only

    result: dict[str, dict[str, Any]] = {}
    for name, amp in data.items():
        if isinstance(amp, dict):
            result[str(name)] = amp
    return result
