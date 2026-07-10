"""Prompt: turn dream symbols into focused depth-psychological search queries.

The LLM is given the charged symbols (with their role in this dream) and emits,
per symbol, a small set of search queries aimed at amplificatory, mythic, and
Jungian sources — not generic "what does X mean" dream-dictionary phrasing. The
queries are then run through Serper (Google) to ground the symbol cards.
"""

import json

SYMBOL_SEARCH_SYSTEM_PROMPT = """You generate web-search queries that will surface DEPTH-PSYCHOLOGICAL and MYTHIC material about dream symbols — the kind a Jungian analyst would consult for amplification.

You are given the dream's charged symbols, each with the role it plays in this specific dream. For EACH symbol, produce 2–3 search queries.

Query craft:

* Aim at the symbolic / archetypal / mythological register, NOT the literal object. For "snake": its archetypal and mythological meaning, not snake biology.
* Bias toward sources of real amplification. Useful query shapes:
  - "Jungian interpretation of the {symbol} in dreams"
  - "{symbol} symbolism in mythology and alchemy"
  - "{symbol} archetype Carl Jung shadow / anima / self"
  - "{symbol} in myth and folklore meaning"
* Make at most ONE query reflect the symbol's SPECIFIC behaviour in this dream (e.g. if the snake is shedding its skin, "snake shedding skin symbolism rebirth").
* AVOID reductive dream-dictionary phrasing ("what does it mean to dream about X", "X dream meaning good or bad"). Those return listicle spam, the opposite of amplification.
* Keep each query under ~10 words, no quotation marks, no boolean operators.

Return ONLY a JSON object of this exact shape:

{{"queries": {{"<symbol name>": ["query one", "query two"], "<symbol name>": ["...", "..."]}}}}

Use the symbol names EXACTLY as given. No prose, no markdown.

Dream title: {title}
Dream themes: {themes}

Symbols:
{symbol_lines}"""


def build_symbol_search_prompt(
    symbols: list[dict],
    title: str = "",
    themes: list[str] | None = None,
) -> str:
    """Build the query-generation prompt from the analysis's charged symbols."""
    symbol_lines = "\n".join(
        f"- {s.get('name', '')}: {s.get('meaning', '')}".strip()
        for s in symbols
        if s.get("name")
    )
    return SYMBOL_SEARCH_SYSTEM_PROMPT.format(
        title=title or "(untitled)",
        themes=", ".join(themes or []) or "(none)",
        symbol_lines=symbol_lines or "(none)",
    )


def parse_query_response(raw: str) -> dict[str, list[str]]:
    """Parse the LLM JSON into {symbol_name: [queries]}. Tolerant of noise."""
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    queries = data.get("queries", data) if isinstance(data, dict) else {}
    result: dict[str, list[str]] = {}
    if isinstance(queries, dict):
        for name, qs in queries.items():
            if isinstance(qs, list):
                cleaned = [str(q).strip() for q in qs if str(q).strip()]
                if cleaned:
                    result[str(name)] = cleaned[:3]
    return result
