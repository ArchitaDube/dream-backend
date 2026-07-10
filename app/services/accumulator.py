"""SSE token accumulator — scans streaming tokens for XML-tagged events."""

import re
from typing import Any


class AnalysisAccumulator:
    """
    Scans streaming tokens for XML-tagged events.
    Emits typed SSE payloads as tags complete.
    """

    def __init__(self):
        self.buffer = ""
        self.seen_events: set[str] = set()

    def ingest(self, token: str) -> list[dict[str, Any]]:
        """Feed a token into the accumulator. Returns any completed events."""
        self.buffer += token
        emitted: list[dict[str, Any]] = []

        patterns: dict[str, str] = {
            "mood": r"<mood>(.*?)</mood>",
            "theme": r"<theme>(.*?)</theme>",
            "title": r"<title>(.*?)</title>",
            "symbol": r'<symbol name="([^"]+)">(.*?)</symbol>',
            "fragment": r'<fragment label="([^"]+)">(.*?)</fragment>',
        }

        for event_type, pattern in patterns.items():
            for match in re.finditer(pattern, self.buffer, re.DOTALL):
                full_match = match.group(0)
                if full_match not in self.seen_events:
                    self.seen_events.add(full_match)
                    if event_type == "mood":
                        emitted.append({"type": "mood", "value": match.group(1).strip()})
                    elif event_type == "theme":
                        emitted.append({"type": "theme", "value": match.group(1).strip()})
                    elif event_type == "title":
                        emitted.append({"type": "title", "value": match.group(1).strip()})
                    elif event_type == "symbol":
                        emitted.append({
                            "type": "symbol",
                            "name": match.group(1),
                            "meaning": match.group(2).strip(),
                        })
                    elif event_type == "fragment":
                        emitted.append({
                            "type": "fragment",
                            "label": match.group(1),
                            "content": match.group(2).strip(),
                        })

        return emitted

    def build_analysis(self) -> dict[str, Any]:
        """Build the final DreamAnalysis object from accumulated events."""
        symbols: list[dict[str, str]] = []
        themes: list[str] = []
        fragments: list[dict[str, str]] = []
        mood = ""
        title = ""

        for event_str in self.seen_events:
            for event_type, pattern in {
                "mood": r"<mood>(.*?)</mood>",
                "theme": r"<theme>(.*?)</theme>",
                "title": r"<title>(.*?)</title>",
                "symbol": r'<symbol name="([^"]+)">(.*?)</symbol>',
                "fragment": r'<fragment label="([^"]+)">(.*?)</fragment>',
            }.items():
                match = re.match(pattern, event_str, re.DOTALL)
                if match:
                    if event_type == "mood":
                        mood = match.group(1).strip()
                    elif event_type == "theme":
                        themes.append(match.group(1).strip())
                    elif event_type == "title":
                        title = match.group(1).strip()
                    elif event_type == "symbol":
                        symbols.append({
                            "name": match.group(1),
                            "meaning": match.group(2).strip(),
                        })
                    elif event_type == "fragment":
                        fragments.append({
                            "label": match.group(1),
                            "content": match.group(2).strip(),
                        })
                    break

        return {
            "summary": self._extract_summary(),
            "symbols": symbols,
            "symbolArchetypes": [],
            "themes": themes,
            "emotionalTone": mood,
            "archetype": self._infer_archetype(themes, symbols),
            "fragments": fragments,
        }

    def _extract_summary(self) -> str:
        """Extract a summary from the buffer (all non-tag prose)."""
        cleaned = re.sub(r"<[^>]+>", "", self.buffer).strip()
        return cleaned if cleaned else ""

    def _infer_archetype(self, themes: list[str], symbols: list[dict]) -> str:
        """Simple archetype inference based on themes and symbols."""
        theme_text = " ".join(themes).lower()
        symbol_text = " ".join(s.get("name", "") for s in symbols).lower()
        combined = theme_text + " " + symbol_text

        archetypes = {
            "The Wanderer": ["journey", "path", "road", "travel", "wander", "threshold"],
            "The Shadow": ["shadow", "dark", "fear", "monster", "pursuit"],
            "The Anima/Animus": ["lover", "beloved", "feminine", "masculine", "partner"],
            "The Wise Old Man/Woman": ["teacher", "guide", "elder", "wise", "sage"],
            "The Child": ["child", "innocent", "beginning", "new", "birth"],
            "The Trickster": ["trick", "joke", "mirror", "reverse", "paradox"],
            "The Hero": ["battle", "quest", "victory", "courage", "strength"],
            "The Mother": ["mother", "nurture", "home", "shelter", "earth"],
        }

        for archetype, keywords in archetypes.items():
            if any(kw in combined for kw in keywords):
                return archetype

        return ""
