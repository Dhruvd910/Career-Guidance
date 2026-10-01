"""One-shot LLM summaries that are grounded entirely in data passed into the prompt —
no tool-calling loop needed since there's nothing further to look up (spec §20 college
comparison explanation). Returns None (never a guess) when the LLM isn't configured."""

import json

from app.providers.registry import get_llm_provider

COMPARISON_SYSTEM_PROMPT = """You write short, balanced comparison summaries for Indian students choosing \
between colleges. You are given ONLY structured comparison data — use nothing else. Do not invent any \
fact not present in the data. If a field is null, say it's not available rather than guessing. Mention \
trade-offs (e.g. fees vs. placement, cutoff difficulty vs. location) in 3-4 sentences, plain language, no \
guarantees about outcomes. If data says "unverified_demo" or similar, do not present it as officially verified."""


async def generate_college_comparison_summary(rows: list[dict]) -> str | None:
    llm = get_llm_provider()
    if llm is None:
        return None
    try:
        response = await llm.chat(
            [
                {"role": "system", "content": COMPARISON_SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(rows, default=str)},
            ]
        )
        return response.get("content")
    except Exception:  # noqa: BLE001 — a missing AI summary should never break the compare page
        return None
