"""Grounding service — verified, source-backed material for dream symbols.

Two jobs:

1.  Detect known archetypal symbols in the dream text + dialogue, fetch their
    *etymology* from Wiktionary (a high-signal, non-generic source), and format
    that material so it can be INJECTED INTO the analysis prompt. This anchors
    the LLM's amplification in real, verifiable roots instead of recalled-from-
    memory associations (where generic / hallucinated references creep in).

2.  Expose the symbol → archetype lexicon and the etymology fetcher so the
    post-analysis enricher (symbol_enricher.py) can build the display cards
    without duplicating lookups.

The lexicon doubles as the detection vocabulary: only words we have a known
archetypal reading for are worth grounding.

Context priority for the grounding block: Serper (Google SERP) → Wiktionary
etymology.
"""

import asyncio
import logging
import re
import time
from typing import Any

import httpx

from app.services.archetypes import ARCHETYPE_ID_SET
from app.services.serper import (
    extract_context as serper_extract_context,
    is_configured as serper_is_configured,
    search_single,
)

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
#  Symbol → Archetype lexicon
#  Maps common dream symbols to canonical archetype IDs (the 14 in
#  app.services.archetypes / oneiros/data/ontology.ts). Also serves as the
#  detection vocabulary: the dream text is scanned for these keys.
#
#  NOTE: this map is a coarse SEED/FALLBACK only. The post-analysis amplifier
#  (symbol_enricher.py) chooses related archetypes per-context from the 14, so
#  open-vocabulary symbols (Kali, stage…) resolve correctly even when absent
#  here. Legacy non-canonical ids were collapsed onto the 14 (lossy):
#    great_mother → caregiver · father/ruler/seer/mystic/guardian → sage
#    double/outcast → shadow · rebirth → child
#  These collapses are deliberately blunt; the amplifier refines them.
# ──────────────────────────────────────────────

SYMBOL_ARCHETYPE_MAP: dict[str, list[str]] = {
    "water": ["caregiver", "self"],
    "snake": ["shadow", "trickster"],
    "bridge": ["wanderer", "self"],
    "door": ["sage", "wanderer"],
    "mirror": ["shadow", "ego"],
    "fire": ["destroyer", "hero"],
    "tree": ["self", "caregiver"],
    "mountain": ["sage", "self"],
    "child": ["child"],
    "house": ["caregiver", "self"],
    "journey": ["wanderer", "hero"],
    "death": ["destroyer", "child"],
    "eye": ["sage", "shadow"],
    "sun": ["self", "hero"],
    "moon": ["anima", "caregiver"],
    "star": ["self", "sage"],
    "crown": ["sage", "self"],
    "sword": ["hero", "sage"],
    "heart": ["lover", "caregiver"],
    "mask": ["persona", "trickster"],
    "labyrinth": ["wanderer", "self"],
    "egg": ["child", "self"],
    "wing": ["wanderer", "sage"],
    "chain": ["shadow"],
    "key": ["sage", "wanderer"],
    "shadow": ["shadow"],
    "blood": ["destroyer", "shadow"],
    "rain": ["caregiver", "child"],
    "storm": ["destroyer", "trickster"],
    "light": ["self", "sage"],
    "darkness": ["shadow", "caregiver"],
    "tunnel": ["wanderer", "child"],
    "tower": ["sage", "persona"],
    "garden": ["caregiver", "lover"],
    "desert": ["wanderer", "shadow"],
    "ocean": ["caregiver", "self"],
    "river": ["wanderer", "child"],
    "forest": ["caregiver", "shadow"],
    "maze": ["wanderer", "trickster"],
    "clock": ["sage"],
    "window": ["sage", "wanderer"],
    "rope": ["shadow"],
    "stone": ["sage", "self"],
    "gold": ["self", "hero"],
    "iron": ["sage", "destroyer"],
    "ash": ["destroyer", "child"],
    "bone": ["destroyer", "shadow"],
    "feather": ["wanderer", "sage"],
    "thorn": ["shadow", "destroyer"],
    "flower": ["child", "lover"],
    "fruit": ["caregiver", "child"],
    "bread": ["caregiver"],
    "wine": ["lover", "sage"],
    "horse": ["wanderer", "hero"],
    "wolf": ["shadow", "trickster"],
    "bird": ["wanderer", "sage"],
    "fish": ["self", "caregiver"],
    "spider": ["trickster", "caregiver"],
    "lion": ["hero", "sage"],
    "dragon": ["shadow", "destroyer"],
    "butterfly": ["child", "wanderer"],
    "owl": ["sage"],
    "raven": ["shadow", "sage"],
    "dove": ["caregiver", "sage"],
    "serpent": ["shadow", "trickster"],
}

# Guard: every archetype the lexicon emits MUST be one of the canonical 14, so
# relatedArchetypes always resolves to a real ontology node. Fails fast at
# import if a non-canonical id slips in.
_bad_ids = {
    aid
    for ids in SYMBOL_ARCHETYPE_MAP.values()
    for aid in ids
    if aid not in ARCHETYPE_ID_SET
}
assert not _bad_ids, f"SYMBOL_ARCHETYPE_MAP has non-canonical archetype ids: {_bad_ids}"
del _bad_ids

# A handful of symbols carry a canonical mythic motif so reliably that we name
# it directly — these go into the prompt as suggested "archetypal play" to set
# the dream beside. The LLM is told to use only what genuinely fits, and the
# motifs below are well-attested (no fabrication risk).
SYMBOL_MOTIFS: dict[str, str] = {
    "water": "the primordial waters of Genesis; Inanna's descent through gates of the deep",
    "snake": "the Ouroboros devouring its tail; the serpent in Eden; Asclepius' healing staff",
    "serpent": "the Ouroboros; the Edenic tempter; the kundalini ascent",
    "bridge": "the Bifröst between worlds; the Chinvat Bridge of judgment in Zoroastrian myth",
    "river": "the Styx and the ferryman Charon; Lethe's waters of forgetting",
    "ocean": "the abyss of Tiamat; the night-sea journey of the solar hero",
    "labyrinth": "Theseus, the Minotaur, and Ariadne's thread",
    "maze": "Theseus in the Cretan labyrinth, guided by the thread",
    "death": "the descent of Inanna; Persephone's pomegranate; the alchemical nigredo",
    "tree": "Yggdrasil the world-tree; the Tree of Knowledge; the Bodhi tree",
    "fire": "Prometheus' stolen flame; the phoenix consumed and reborn; the alchemical calcinatio",
    "mirror": "Narcissus at the pool; the speculum of the alchemists",
    "moon": "Selene and Endymion; Hecate at the crossroads; lunar Sophia",
    "sun": "Apollo's chariot; the solar hero's daily death and rebirth",
    "wolf": "Fenrir who will devour the gods; Romulus and the she-wolf",
    "raven": "Odin's Huginn and Muninn; the raven Noah loosed over the flood",
    "owl": "Athena's owl of wisdom; the night-bird of Lilith",
    "egg": "the cosmic egg of Orphic and Vedic creation",
    "dragon": "the dragon guarding the hoard the hero must slay; Tiamat; the Midgard serpent",
    "garden": "Eden before the fall; the hortus conclusus; the Hesperides' golden apples",
    "blood": "the sacrificial blood of covenant; the wounded Fisher King",
    "key": "the keys of Janus and of Peter; the locked chamber of Bluebeard",
    "door": "Janus of the threshold; the narrow gate",
    "horse": "the night-mare; Sleipnir; the pale horse of apocalypse",
    "butterfly": "Psyche, whose name is both soul and butterfly",
    "spider": "Arachne's hubris; the weaving Fates; the Spider Grandmother of creation",
}

WIKTIONARY_API = "https://en.wiktionary.org/w/api.php"
TIMEOUT = 10.0
HEADERS = {
    "User-Agent": "Oneiros/1.0 (dream analysis app; https://oneiros.app; contact@oneiros.app)",
    "Accept": "application/json",
}

# How many distinct symbols to ground per dream.
MAX_GROUNDED_SYMBOLS = 5


def detect_symbols(*texts: str) -> list[str]:
    """Scan one or more texts for known symbol words, ranked by salience.

    Whole-word, case-insensitive. Also matches simple plurals (snakes → snake).
    Returned in descending order of occurrence count, ties broken by first
    appearance, capped at MAX_GROUNDED_SYMBOLS.
    """
    blob = "\n".join(t for t in texts if t).lower()
    if not blob:
        return []

    counts: dict[str, int] = {}
    first_seen: dict[str, int] = {}
    for symbol in SYMBOL_ARCHETYPE_MAP:
        # match the word and its trivial plural, on word boundaries
        pattern = rf"\b{re.escape(symbol)}s?\b"
        matches = list(re.finditer(pattern, blob))
        if matches:
            counts[symbol] = len(matches)
            first_seen[symbol] = matches[0].start()

    ranked = sorted(
        counts,
        key=lambda s: (-counts[s], first_seen[s]),
    )
    return ranked[:MAX_GROUNDED_SYMBOLS]


async def gather_grounding(
    dream_body: str,
    dialogue_summary: str = "",
) -> list[dict[str, Any]]:
    """Detect symbols and fetch verified grounding for each.

    Context priority: Serper (Google SERP) → Wiktionary etymology.

    Returns a list of entries:
        {name, etymology, etymologyUrl, relatedArchetypes, motif, serperContext, serperSourceUrl}
    Best-effort: any field that can't be sourced is left empty/None. Never
    raises — grounding is an enhancement, not a dependency.
    """
    symbols = detect_symbols(dream_body, dialogue_summary)
    if not symbols:
        return []

    # Fetch Serper context for each detected symbol (individual requests
    # are more reliable on Serper's free tier than batched POST).
    serper_contexts: dict[str, tuple[str, str | None]] = {}
    if serper_is_configured():
        for s in symbols:
            try:
                result = await search_single(f"{s} symbolism", num=3)
                if result:
                    ctx, url = serper_extract_context(result)
                    if ctx:
                        serper_contexts[s] = (ctx, url)
            except Exception as e:
                logger.debug("Serper grounding failed for '%s': %s", s, str(e))

    async with httpx.AsyncClient(timeout=TIMEOUT, headers=HEADERS) as client:
        etymologies = await asyncio.gather(
            *(fetch_etymology(client, s) for s in symbols),
            return_exceptions=True,
        )

    entries: list[dict[str, Any]] = []
    for symbol, ety in zip(symbols, etymologies):
        if isinstance(ety, Exception):
            etymology, ety_url = "", None
        else:
            etymology, ety_url = ety

        serper_hit = serper_contexts.get(symbol)
        serper_ctx, serper_url = serper_hit if serper_hit else ("", None)

        entries.append({
            "name": symbol,
            "etymology": etymology,
            "etymologyUrl": ety_url,
            "relatedArchetypes": SYMBOL_ARCHETYPE_MAP.get(symbol, []),
            "motif": SYMBOL_MOTIFS.get(symbol, ""),
            "serperContext": serper_ctx,
            "serperSourceUrl": serper_url,
        })
    return entries


def format_grounding_block(entries: list[dict[str, Any]]) -> str:
    """Render grounding entries as a prompt-injectable reference block.

    Serper context is shown first (when available), then etymology, then motif.
    """
    if not entries:
        return (
            "No external grounding was retrieved for this dream. Amplify only "
            "from myths, motifs, and Jungian readings you are confident are real."
        )

    lines: list[str] = []
    for e in entries:
        parts = [f"• {e['name'].upper()}"]
        if e.get("relatedArchetypes"):
            parts.append(f"archetypes: {', '.join(e['relatedArchetypes'])}")
        lines.append("  ".join(parts))
        # Serper context first (primary source)
        if e.get("serperContext"):
            lines.append(f"    context (Serper/Google): {e['serperContext']}")
        if e.get("etymology"):
            lines.append(f"    root (Wiktionary, verified): {e['etymology']}")
        if e.get("motif"):
            lines.append(f"    attested mythic motif: {e['motif']}")
    return "\n".join(lines)


# Process-wide etymology cache (positive AND negative). Wiktionary results are
# effectively static, and the same symbols recur across dreams, so this collapses
# the bulk of repeat lookups — including mundane words with no etymology section,
# which would otherwise refetch every analysis.
_ETYMOLOGY_CACHE: dict[str, tuple[float, tuple[str, str | None]]] = {}
_ETYMOLOGY_TTL = 60 * 60 * 24  # 24 hours


async def fetch_etymology(
    client: httpx.AsyncClient,
    word: str,
) -> tuple[str, str | None]:
    """Fetch the English etymology of a word from Wiktionary.

    Returns (etymology_text, page_url). Empty string if no etymology section
    is found. Best-effort HTML-section parse — Wiktionary has no clean
    etymology endpoint. Cached (positive + negative) for ``_ETYMOLOGY_TTL``.
    """
    key = word.strip().lower()
    cached = _ETYMOLOGY_CACHE.get(key)
    if cached and (time.monotonic() - cached[0]) < _ETYMOLOGY_TTL:
        return cached[1]

    result = await _fetch_etymology_uncached(client, word)
    _ETYMOLOGY_CACHE[key] = (time.monotonic(), result)
    return result


async def _fetch_etymology_uncached(
    client: httpx.AsyncClient,
    word: str,
) -> tuple[str, str | None]:
    try:
        section_index = await _find_etymology_section(client, word)
        if section_index is None:
            return "", None

        params = {
            "action": "parse",
            "page": word,
            "section": section_index,
            "prop": "text",
            "format": "json",
            "formatversion": "2",
            "disabletoc": "1",
        }
        resp = await client.get(WIKTIONARY_API, params=params)
        resp.raise_for_status()
        html = resp.json().get("parse", {}).get("text", "")
        text = _clean_wiktionary_html(html)
        if not text:
            return "", None

        url = f"https://en.wiktionary.org/wiki/{word.replace(' ', '_')}#Etymology"
        return text, url

    except Exception as e:
        logger.debug("Wiktionary etymology failed for '%s': %s", word, str(e))
        return "", None


async def _find_etymology_section(
    client: httpx.AsyncClient,
    word: str,
) -> str | None:
    """Return the index of the first English 'Etymology' section, or None."""
    params = {
        "action": "parse",
        "page": word,
        "prop": "sections",
        "format": "json",
        "formatversion": "2",
    }
    resp = await client.get(WIKTIONARY_API, params=params)
    resp.raise_for_status()
    sections = resp.json().get("parse", {}).get("sections", [])

    # Walk sections; only consider those under the English language heading.
    in_english = False
    for sec in sections:
        line = (sec.get("line") or "").strip().lower()
        level = sec.get("toclevel", 99)
        if level == 1:
            in_english = line == "english"
        if in_english and line.startswith("etymology"):
            return str(sec.get("index"))
    return None


def _clean_wiktionary_html(html: str) -> str:
    """Strip Wiktionary section HTML down to a single readable paragraph."""
    if not html:
        return ""
    # Drop the leading <h3>Etymology</h3> style heading and edit links.
    text = re.sub(r"<style.*?</style>", "", html, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", "", text)
    # collapse citation/reference brackets and edit markers
    text = re.sub(r"\[edit\]", "", text)
    text = re.sub(r"\[\d+\]", "", text)
    text = re.sub(r"&#?\w+;", " ", text)  # html entities
    # take the first non-empty line that isn't just the heading word
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    paragraphs = [p for p in paragraphs if p.lower() not in ("etymology", "etymology 1", "etymology 2")]
    if not paragraphs:
        return ""
    first = re.sub(r"\s+", " ", paragraphs[0]).strip()
    # Keep only the core derivation — the first sentence — and drop the long
    # "Cognate with… / Doublet of…" tails that make the card noisy.
    sentence = re.split(r"(?<=[.])\s+", first)[0].strip()
    if len(sentence) >= 60:
        first = sentence
    if len(first) > 320:
        first = first[:317].rstrip() + "..."
    return first


