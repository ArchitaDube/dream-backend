"""Graph data extraction — structured LLM call after analysis completes.

Produces a dream graph: ``entities`` (figures / symbols / settings) and explicit
``edges`` between them. Each entity carries a ``canonical`` join key and maps to
one of the 14 fixed archetypes, enabling the per-dream constellation and the
cross-dream recurrence graph.
"""

import json
import logging
from typing import Any

from app.db import update_dream_extraction
from app.prompts.extraction import (
    EXTRACTION_SYSTEM_PROMPT,
    VALID_ARCHETYPE_IDS,
    VALID_RELATIONSHIP_TYPES,
)
from app.services.canonical import canonicalize
from app.services.llm import llm

logger = logging.getLogger(__name__)

_ARCHETYPE_SET = set(VALID_ARCHETYPE_IDS)
_RELATIONSHIP_SET = set(VALID_RELATIONSHIP_TYPES)
_VALID_KINDS = {"figure", "symbol", "setting"}

# Shape returned when extraction yields nothing usable / fails.
EMPTY_EXTRACTION: dict[str, Any] = {
    "entities": [],
    "edges": [],
    "dominantArchetypes": [],
    "emotionalTone": "",
    "individuationIndex": 0.5,
}


async def extract_graph_data(
    dream_id: str,
    dream_body: str,
    analysis: dict[str, Any],
) -> dict[str, Any]:
    """Extract a dream graph (entities + edges) and persist it.

    Runs asynchronously after analysis completes.
    """
    prompt = _build_extraction_prompt(dream_body, analysis)

    try:
        raw = await llm.structured_completion(
            messages=[{"role": "user", "content": prompt}],
            system=EXTRACTION_SYSTEM_PROMPT,
        )
        data = json.loads(raw)
        extraction = _validate_extraction(data)
        await update_dream_extraction(dream_id, extraction)
        logger.info(
            "Extraction complete for dream %s: %d entities, %d edges",
            dream_id, len(extraction["entities"]), len(extraction["edges"]),
        )
        return extraction
    except Exception as e:
        logger.error("Extraction failed for dream %s: %s", dream_id, str(e))
        fallback = {**EMPTY_EXTRACTION, "emotionalTone": analysis.get("emotionalTone", "")}
        await update_dream_extraction(dream_id, fallback)
        return fallback


def _build_extraction_prompt(dream_body: str, analysis: dict[str, Any]) -> str:
    symbols_text = ", ".join(
        f"{s['name']}: {s['meaning']}" for s in analysis.get("symbols", [])
    )
    themes = ", ".join(analysis.get("themes", []))
    mood = analysis.get("emotionalTone", "")

    # Include amplified symbol archetypes if available (Jungian amplification —
    # collective + personal reading, with canonical archetype ids).
    symbol_archetypes = analysis.get("symbolArchetypes", [])
    archetype_context = ""
    if symbol_archetypes:
        archetype_lines = []
        for sa in symbol_archetypes:
            arch_ids = ", ".join(sa.get("relatedArchetypes", []))
            ctx = sa.get("collectiveAmplification") or sa.get("personalResonance") or ""
            truncated = ctx[:200] + ("..." if len(ctx) > 200 else "")
            archetype_lines.append(
                f"- {sa['name']}: amplification: {truncated} | Suggested archetypes: {arch_ids}"
            )
        archetype_context = "\n".join(archetype_lines)

    enrichment_block = ""
    if archetype_context:
        enrichment_block = (
            "\nAmplified symbol archetypes (Jungian amplification — guidance only):\n"
            f"{archetype_context}\n"
        )

    return f"""Dream text:
{dream_body}

Analysis context:
- Mood: {mood}
- Themes: {themes}
- Symbols: {symbols_text}
{enrichment_block}
Extract the dream graph (entities + edges) as JSON matching the schema. Map each entity to one of the 14 archetype ids."""


def _clamp(value: Any, lo: float, hi: float, default: float) -> float:
    try:
        return min(max(float(value), lo), hi)
    except (TypeError, ValueError):
        return default


def _coerce_archetype(value: Any) -> str | None:
    """Return a valid archetype id, or None if not recognized."""
    if isinstance(value, str) and value in _ARCHETYPE_SET:
        return value
    return None


def _validate_extraction(data: dict) -> dict:
    """Validate + normalize the LLM graph output.

    - Keeps only entities with a valid kind and a valid primary archetype.
    - Assigns a ``canonical`` key to each entity.
    - Drops edges whose endpoints don't survive validation or whose type is invalid.
    """
    raw_entities = data.get("entities") or []
    entities: list[dict[str, Any]] = []
    valid_ids: set[str] = set()

    for raw in raw_entities:
        if not isinstance(raw, dict):
            continue
        kind = raw.get("kind")
        if kind not in _VALID_KINDS:
            continue
        archetype = _coerce_archetype(raw.get("archetypeId"))
        if archetype is None:
            # An entity with no recognizable archetype can't be placed in the graph.
            continue

        ent_id = str(raw.get("id") or f"e{len(entities) + 1}")
        if ent_id in valid_ids:
            ent_id = f"{ent_id}_{len(entities)}"
        label = str(raw.get("label") or "").strip()

        entities.append({
            "id": ent_id,
            "kind": kind,
            "label": label,
            "canonical": canonicalize(label),
            "figureType": (raw.get("figureType") or None),
            "archetypeId": archetype,
            "archetypeSecondary": _coerce_archetype(raw.get("archetypeSecondary")),
            "intensity": _clamp(raw.get("intensity"), 0.0, 1.0, 0.5),
            "valence": _clamp(raw.get("valence"), -1.0, 1.0, 0.0),
            "confidence": _clamp(raw.get("confidence"), 0.0, 1.0, 0.5),
            "roleInScene": str(raw.get("roleInScene") or "").strip(),
            "evidence": [str(e) for e in (raw.get("evidence") or []) if e],
        })
        valid_ids.add(ent_id)

    edges: list[dict[str, Any]] = []
    for raw in (data.get("edges") or []):
        if not isinstance(raw, dict):
            continue
        source = str(raw.get("source") or "")
        target = str(raw.get("target") or "")
        edge_type = raw.get("type")
        if source not in valid_ids or target not in valid_ids or source == target:
            continue
        if edge_type not in _RELATIONSHIP_SET:
            continue
        edges.append({
            "source": source,
            "target": target,
            "type": edge_type,
            "strength": _clamp(raw.get("strength"), 0.0, 1.0, 0.5),
            "evidence": str(raw.get("evidence") or "").strip(),
        })

    dominant = [
        a for a in (data.get("dominantArchetypes") or [])
        if isinstance(a, str) and a in _ARCHETYPE_SET
    ]
    # Fall back to the strongest entities' archetypes if the model omitted dominants.
    if not dominant and entities:
        ranked = sorted(entities, key=lambda e: e["intensity"], reverse=True)
        seen: list[str] = []
        for e in ranked:
            if e["archetypeId"] not in seen:
                seen.append(e["archetypeId"])
        dominant = seen[:3]

    return {
        "entities": entities,
        "edges": edges,
        "dominantArchetypes": dominant,
        "emotionalTone": str(data.get("emotionalTone") or "").strip(),
        "individuationIndex": _clamp(data.get("individuationIndex"), 0.0, 1.0, 0.5),
    }
