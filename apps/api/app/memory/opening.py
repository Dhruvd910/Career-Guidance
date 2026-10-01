"""Where we left off (spec §7): a returning student isn't started from zero.

The counselling state is the most recent open topic with where it stands. When the student comes
back after a while and something is still open, MAYA opens with a short recap and a check-in —
written from that state alone, in the student's usual language:

    "Last time we were discussing PCM vs PCB. You were leaning towards PCM, but worried about what
     your father expects. Has anything changed?"
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.language import DEVANAGARI, ENGLISH, HINDI, LATIN, LanguageTag, reply_instruction, usual_language
from app.memory import consent
from app.models.memory import CounsellingThread, SessionSummary
from app.models.student import StudentProfile
from app.providers.llm import LLMProvider

RESUME_AFTER = timedelta(hours=6)

INSTRUCTIONS = """You are MAYA, an AI career counsellor, greeting a student who is coming back. Write your \
opening line: at most two short sentences. First recall where you left off — the topic, where they stood, \
what was still open or agreed — then ask whether anything has changed. Use only the notes below; don't add \
anything. Warm and natural, spoken aloud: no lists, no greeting formulas beyond their name."""


def counselling_state(db: Session, profile: StudentProfile) -> dict | None:
    """The spec's §7 fields, from the most recently touched open topic."""
    thread = db.execute(select(CounsellingThread).where(
        CounsellingThread.student_profile_id == profile.id,
        CounsellingThread.status.in_(("open", "parked", "reopened")))
        .order_by(CounsellingThread.last_touched_at.desc()).limit(1)).scalar_one_or_none()
    last = db.execute(select(SessionSummary).where(SessionSummary.student_profile_id == profile.id)
                      .order_by(SessionSummary.created_at.desc()).limit(1)).scalar_one_or_none()
    if thread is None and last is None:
        return None
    return {
        "current_counselling_topic": thread.title if thread else None,
        "current_problem": thread.current_position if thread else None,
        "decision_status": thread.decision_status if thread else None,
        "open_questions": thread.open_questions if thread else [],
        "previous_actions": thread.actions_agreed if thread else [],
        "next_step": (thread.next_step if thread else None) or (last.next_steps[0] if last and last.next_steps else None),
        "last_session": {"id": last.conversation_id, "ended_at": last.created_at, "summary": last.summary} if last else None,
        "thread_id": thread.id if thread else None,
    }


async def opening_line(db: Session, profile: StudentProfile, llm: LLMProvider,
                       now: datetime | None = None) -> tuple[str, str] | None:
    """(text, language) for a returning student, or None: no permission, nothing open, or too
    soon since the last session to call it a return."""
    if not consent.allowed(db, profile, consent.LONG_TERM_MEMORY):
        return None
    state = counselling_state(db, profile)
    if not state or not state["current_counselling_topic"] or not state["last_session"]:
        return None
    ended = state["last_session"]["ended_at"]
    if ended.tzinfo is None:
        ended = ended.replace(tzinfo=timezone.utc)
    if (now or datetime.now(timezone.utc)) - ended < RESUME_AFTER:
        return None
    lang = usual_language(profile.language_stats) or ENGLISH
    tag = LanguageTag(lang, DEVANAGARI if lang == HINDI else LATIN, 1.0)
    notes = {k: v for k, v in state.items() if k not in ("thread_id", "last_session")}
    notes["last_session_summary"] = state["last_session"]["summary"]
    reply = await llm.chat([
        {"role": "system", "content": INSTRUCTIONS + "\n\n" + reply_instruction(tag)},
        {"role": "user", "content": f"Student's name: {profile.name}\nNotes: {json.dumps(notes, default=str)}"},
    ])
    text = (reply.get("content") or "").strip()
    return (text, lang) if text else None
