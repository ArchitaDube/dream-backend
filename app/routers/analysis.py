"""Analysis endpoint — SSE streaming dream analysis."""

import asyncio
import json
import logging
import re
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.db import (
    get_dream,
    get_or_create_dialogue,
    update_dream_analysis,
)
from app.middleware.client import resolve_client
from app.middleware.rate_limit import check_rate_limit
from app.prompts.analysis import build_analysis_prompt
from app.services.accumulator import AnalysisAccumulator
from app.services.extraction import extract_graph_data
from app.services.grounding import format_grounding_block, gather_grounding
from app.services.llm import llm
from app.services.symbol_enricher import enrich_symbols

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/dreams/{dream_id}/analyze")
async def analyze_dream(
    dream_id: str,
    client: dict = Depends(resolve_client),
):
    """Stream dream analysis via SSE. Only available after dialogue is complete."""
    client_id = client["client_id"]

    # Rate limit check
    await check_rate_limit(client_id, "analyze", client.get("tier") == "pro")

    # Fetch dream
    dream = await get_dream(dream_id, client_id)
    if not dream:
        raise HTTPException(status_code=404, detail="Dream not found")

    # Check dialogue is complete
    dialogue = await get_or_create_dialogue(dream_id, client_id)
    if not dialogue.get("grounded_at"):
        raise HTTPException(
            status_code=400,
            detail="Complete the dialogue before analyzing.",
        )

    # Build dialogue summary from history
    history = dialogue.get("history") or []
    dialogue_summary = _summarize_dialogue(history)

    async def event_stream():
        accumulator = AnalysisAccumulator()

        try:
            # Gather verified grounding (etymologies + attested motifs) for the
            # symbols present in the dream, and inject it into the prompt so the
            # analysis amplifies from real sources rather than from memory alone.
            grounding_entries = await gather_grounding(dream["body"], dialogue_summary)
            grounding_block = format_grounding_block(grounding_entries)

            async for token in llm.stream_completion(
                messages=[{"role": "user", "content": "Analyze this dream."}],
                system=build_analysis_prompt(
                    dream["body"], dialogue_summary, grounding_block
                ),
            ):
                # Feed token to accumulator
                events = accumulator.ingest(token)

                # Yield clean (XML-stripped) token for frontend prose display
                clean_token = re.sub(r"<[^>]+>", "", token)
                if clean_token:
                    yield f"data: {json.dumps({'type': 'token', 'value': clean_token})}\n\n"

                # Yield any completed structured events
                for event in events:
                    yield f"data: {json.dumps(event)}\n\n"

            # Build final analysis object
            analysis = accumulator.build_analysis()
            mood = analysis.get("emotionalTone", "")
            tags = analysis.get("themes", [])
            title = analysis.get("title") or dream.get("title")

            # Amplify top symbols for the display cards, reusing the grounding
            # already fetched for the prompt (etymology + motif + seed
            # archetypes) and reading both the collective level (dream body) and
            # the personal level (the dreamer's own associations in the dialogue).
            symbol_archetypes = await enrich_symbols(
                analysis.get("symbols", []),
                grounding_entries,
                dream_body=dream["body"],
                dialogue_summary=dialogue_summary,
            )
            analysis["symbolArchetypes"] = symbol_archetypes

            # Emit individual SSE events for each enriched symbol
            for sa in symbol_archetypes:
                yield f"data: {json.dumps({'type': 'symbol_archetype', **sa})}\n\n"

            # Persist enriched analysis to DB
            await update_dream_analysis(
                dream_id, analysis, mood, tags,
                title=title if not dream.get("title") else None,
            )

            # Trigger graph extraction asynchronously with enriched analysis
            asyncio.create_task(
                extract_graph_data(dream_id, dream["body"], analysis)
            )

            # Yield done event with full enriched analysis
            yield f"data: {json.dumps({'type': 'done', 'analysis': analysis})}\n\n"

        except Exception as e:
            logger.error("Analysis stream error: %s", str(e))
            yield f"data: {json.dumps({'type': 'error', 'message': 'Analysis failed'})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


def _summarize_dialogue(history: list[dict]) -> str:
    """Create a concise summary of the dialogue history."""
    if not history:
        return ""

    parts = []
    for entry in history:
        role = entry.get("role", "unknown")
        content = entry.get("content", "")
        # Truncate long entries
        if len(content) > 200:
            content = content[:200] + "..."
        parts.append(f"[{role}]: {content}")

    return "\n".join(parts[-10:])  # Last 10 exchanges max
