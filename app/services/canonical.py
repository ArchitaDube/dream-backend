"""Canonicalization — collapse entity/symbol labels to a stable join key.

A dream's "Kali Ma" and another dream's "kali" must resolve to the same
``canonical`` string so the cross-dream recurrence graph can recognize them as
the same node. This is intentionally lightweight (no NLP models): lowercasing,
article/possessive stripping, naive singularization, and a small alias map for
the synonyms that matter most in dream imagery.
"""

import re

# ──────────────────────────────────────────────
#  Alias map — variants that should collapse together.
#  Keys are already-normalized forms; value is the canonical form.
# ──────────────────────────────────────────────

ALIASES: dict[str, str] = {
    "kali ma": "kali",
    "maa kali": "kali",
    "sea": "water",
    "ocean": "water",
    "lake": "water",
    "river": "water",
    "flame": "fire",
    "flames": "fire",
    "blaze": "fire",
    "snake": "serpent",
    "doorway": "door",
    "gateway": "door",
    "gate": "door",
    "stairs": "staircase",
    "stairway": "staircase",
    "mum": "mother",
    "mom": "mother",
    "mama": "mother",
    "dad": "father",
    "papa": "father",
    "kid": "child",
    "infant": "child",
    "baby": "child",
}

# Leading articles / possessives to strip.
_LEADING = re.compile(r"^(the|a|an|my|your|his|her|their|our|that|this|some)\s+", re.IGNORECASE)

# Non-alphanumeric noise (keep internal spaces).
_NOISE = re.compile(r"[^a-z0-9 ]+")
_WS = re.compile(r"\s+")


def _singularize(word: str) -> str:
    """Naive English singularizer — good enough for symbol joining."""
    if len(word) <= 3:
        return word
    if word.endswith("ies"):
        return word[:-3] + "y"
    if word.endswith("ses") or word.endswith("xes") or word.endswith("zes"):
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def canonicalize(label: str) -> str:
    """Reduce a free-text label to a stable canonical key.

    Empty / unusable input returns "" — callers should treat that as "skip".
    """
    if not label:
        return ""

    text = label.strip().lower()
    text = _NOISE.sub(" ", text)
    text = _WS.sub(" ", text).strip()

    # Strip leading articles repeatedly ("the my old house" is unusual but cheap to handle).
    while True:
        stripped = _LEADING.sub("", text)
        if stripped == text:
            break
        text = stripped

    if not text:
        return ""

    # Whole-phrase alias before singularizing (so "kali ma" resolves intact).
    if text in ALIASES:
        return ALIASES[text]

    # Singularize each word, then re-check the alias map.
    text = " ".join(_singularize(w) for w in text.split(" "))
    text = ALIASES.get(text, text)

    return text
