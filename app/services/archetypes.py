"""Canonical archetype vocabulary — the single server-side source of truth.

The 14 fixed Jungian archetypes, mirroring ``oneiros/data/ontology.ts``. Every
part of the pipeline that names an archetype (extraction, grounding lexicon,
symbol amplification) must speak THIS vocabulary, so an archetype id always
resolves to a real node in the ontology and links into the constellation.

If you change the set here, change ``oneiros/data/ontology.ts`` to match.
"""

# id → one-line description (descriptions mirror the ontology's `description`).
ARCHETYPES: dict[str, str] = {
    "self": "The totality of the psyche — the goal of individuation.",
    "ego": "The conscious sense of self and center of awareness.",
    "persona": "The social mask we present to the world.",
    "shadow": "The repressed, hidden, and disowned aspects of the self.",
    "anima": "The inner feminine principle in the male psyche.",
    "animus": "The inner masculine principle in the female psyche.",
    "hero": "The courageous aspect that overcomes obstacles and achieves goals.",
    "sage": "The wise counselor, teacher, or knowing/visionary figure.",
    "trickster": "The chaotic, boundary-breaking force that disrupts patterns.",
    "lover": "The capacity for intimacy, passion, and deep connection.",
    "caregiver": "The nurturing, compassionate, protective, mother-like aspect.",
    "child": "The innocent, vulnerable, emerging potential within; renewal.",
    "wanderer": "The seeker, the restless soul on a journey of discovery.",
    "destroyer": "The force of dissolution, clearing the old for the new.",
}

# Ordered list of the 14 ids, for prompts and validation.
ARCHETYPE_IDS: list[str] = list(ARCHETYPES)

# Fast membership set.
ARCHETYPE_ID_SET: frozenset[str] = frozenset(ARCHETYPE_IDS)


def is_valid_archetype(archetype_id: str) -> bool:
    """True if the id is one of the canonical 14."""
    return archetype_id in ARCHETYPE_ID_SET


def archetype_catalog_lines() -> str:
    """Render the 14 as ``id — description`` lines for prompt injection."""
    return "\n".join(f"- {aid}: {desc}" for aid, desc in ARCHETYPES.items())
