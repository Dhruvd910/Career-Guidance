"""The fallback for spoken answers the Pi couldn't match itself (docs/design/12-phase3-plan.md P3-8):
one quick LLM call that maps what the student said onto one of the item's answers — or says
it can't. Most answers never get here: the Pi matches keywords, letters and numbers in English,
Hindi and Hinglish first, at no cost in time.

It only ever picks an existing option, never writes an answer of its own, and says "none" rather
than guess. Measured answers never go through it: a model reading "sattasi" as 37, or leaning
towards the right answer to a problem, would quietly change a score — so marks and problems are
matched on the Pi or tapped (`MEASURED`).
"""

from __future__ import annotations

import json
import logging

from app.models.assessment import AssessmentItem
from app.providers.llm import LLMProvider

logger = logging.getLogger(__name__)

MEASURED = ("problem", "marks")

INSTRUCTIONS = """A student answered one question of a career assessment out loud, in English, Hindi or \
Hinglish; you get the question, its possible answers and what speech recognition heard. Return JSON: \
{"option": the key of the answer they gave, or null}, and "skip": true only if they clearly asked to skip \
or move on. Choose an answer only if what they said clearly means it; if it's unclear, unrelated, or could \
mean two answers, return null (and skip false). Never guess."""


def _question(item: AssessmentItem) -> str:
    content = item.content
    lines = [f"Question: {content['prompt']['en']} / {content['prompt']['hi']}"]
    for n, option in enumerate(content.get("options", [])):
        lines.append(f'- key "{option["key"]}" (option {n + 1}, letter {"ABCDEFGH"[n]}): '
                     f'{option["label"]["en"]} / {option["label"]["hi"]}')
    return "\n".join(lines)


async def interpret(item: AssessmentItem, transcript: str, llm: LLMProvider) -> dict:
    """{"answer": {"option": key} | None, "skip": bool}."""
    if item.item_type in MEASURED:
        return {"answer": None, "skip": False}
    reply = await llm.chat([
        {"role": "system", "content": INSTRUCTIONS},
        {"role": "user", "content": f"{_question(item)}\n\nThey said: {transcript[:500]}"},
    ], json_mode=True)
    try:
        data = json.loads(reply.get("content") or "")
    except ValueError:
        logger.info("item %s: unreadable interpretation", item.key)
        return {"answer": None, "skip": False}
    if not isinstance(data, dict):
        return {"answer": None, "skip": False}
    if data.get("skip") is True:
        return {"answer": None, "skip": True}
    keys = {o["key"] for o in item.content.get("options", [])}
    option = data.get("option")
    return {"answer": {"option": option} if option in keys else None, "skip": False}
