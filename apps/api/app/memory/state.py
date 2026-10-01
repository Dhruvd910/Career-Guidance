"""How the student seems in a message (spec §5) — not a label, a set of uncertain signals:

    {"intent": "career_decision", "topic": "PCM vs PCB",
     "emotion_signals": [{"signal": "confusion", "confidence": 0.72}, {"signal": "pressure", "confidence": 0.6}],
     "underlying_concerns": [{"concern": "fear of disappointing parents", "confidence": 0.55}]}

Read by a quick LLM call that runs alongside the reply (never delaying it) and shapes the tone of
the *next* one. A fixed vocabulary of everyday conversational signals — never clinical terms;
readings under 0.5 are ignored; nothing goes on the profile or to parents. Only with the
emotion-signals permission. (Safety is separate and always on: app/ai/safety.py.)
"""

from __future__ import annotations

import asyncio
import json
import logging

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.db import SessionLocal
from app.memory import consent
from app.models.chat import Message
from app.models.memory import TurnAnalysis
from app.models.student import StudentProfile
from app.providers.llm import LLMProvider

logger = logging.getLogger(__name__)

SIGNALS = ("confusion", "frustration", "pressure", "social_comparison", "low_confidence", "worry", "overwhelm",
           "excitement", "disengagement")
INTENTS = ("career_decision", "stream_choice", "exam_preparation", "college_search", "skill_progress", "next_step",
           "information", "emotional_support", "small_talk", "other")
USE_FROM = 0.5  # weaker readings don't count

INSTRUCTIONS = f"""Read one message from a student talking to MAYA, an AI career counsellor, and return JSON: \
{{"intent": one of {list(INTENTS)}, "topic": "a few words", \
"emotion_signals": [{{"signal": one of {list(SIGNALS)}, "confidence": 0-1}}], \
"underlying_concerns": [{{"concern": "a few words, e.g. fear of disappointing parents", "confidence": 0-1}}]}}.
Only what the message itself suggests; confidences honest (a hint is 0.3, an explicit statement 0.8). No \
diagnoses, no clinical terms. Empty lists when nothing shows."""


class Signal(BaseModel):
    signal: str
    confidence: float = Field(ge=0, le=1)


class Concern(BaseModel):
    concern: str = Field(max_length=120)
    confidence: float = Field(ge=0, le=1)


class Reading(BaseModel):
    intent: str | None = None
    topic: str | None = Field(default=None, max_length=120)
    emotion_signals: list[Signal] = []
    underlying_concerns: list[Concern] = []


async def analyze_message(message_id: int, llm: LLMProvider, session_factory=SessionLocal) -> TurnAnalysis | None:
    """Reads one student message and stores the reading — with the permission only. Runs in the
    background with its own database session; never raises."""
    db = session_factory()
    try:
        message = db.get(Message, message_id)
        if message is None or message.role != "user":
            return None
        profile = db.get(StudentProfile, message.conversation.student_profile_id)
        if not consent.allowed(db, profile, consent.EMOTION_SIGNALS):
            return None
        reply = await llm.chat([{"role": "system", "content": INSTRUCTIONS},
                                {"role": "user", "content": message.content}], json_mode=True)
        try:
            reading = Reading.model_validate(json.loads(reply.get("content") or ""))
        except (ValueError, ValidationError) as e:
            logger.info("message %s: no usable reading: %s", message_id, str(e).splitlines()[0])
            return None
        analysis = TurnAnalysis(
            message_id=message_id, student_profile_id=profile.id,
            intent=reading.intent if reading.intent in INTENTS else "other", topic=reading.topic,
            emotion_signals=[s.model_dump() for s in reading.emotion_signals if s.signal in SIGNALS],
            underlying_concerns=[c.model_dump() for c in reading.underlying_concerns], model=llm.model_id,
        )
        db.add(analysis)
        db.commit()
        return analysis
    except Exception:  # noqa: BLE001 — a missing reading only means a less attuned next reply
        logger.exception("couldn't read message %s", message_id)
        db.rollback()
        return None
    finally:
        db.close()


def tone_note(db: Session, conversation_id: int) -> str | None:
    """How the student seemed in their last message, for the next reply's tone — or None."""
    analysis = db.execute(select(TurnAnalysis).join(Message, Message.id == TurnAnalysis.message_id)
                          .where(Message.conversation_id == conversation_id)
                          .order_by(TurnAnalysis.message_id.desc()).limit(1)).scalar_one_or_none()
    if analysis is None:
        return None
    signals = [s for s in analysis.emotion_signals if s.get("confidence", 0) >= USE_FROM]
    concerns = [c for c in analysis.underlying_concerns if c.get("confidence", 0) >= USE_FROM]
    if not signals and not concerns:
        return None
    parts = []
    if signals:
        parts.append("they seemed to show " + ", ".join(
            f"{s['signal'].replace('_', ' ')} ({s['confidence']:.1f})" for s in signals))
    if concerns:
        parts.append("a possible concern underneath: " + "; ".join(
            f"{c['concern']} ({c['confidence']:.1f})" for c in concerns))
    return ("How the student seemed in their last message — uncertain readings, for your tone only: "
            + "; ".join(parts) + ". Respond with empathy where it fits and ask about it gently if relevant; never "
            "name or label their feelings back to them as a verdict, and never diagnose.")


_running: set[asyncio.Task] = set()


def schedule_analysis(db: Session, profile: StudentProfile, message_id: int, llm: LLMProvider | None) -> None:
    """Starts reading a just-saved student message in the background, if they allowed it — on
    the same database as the request it came from."""
    if llm is None or not consent.allowed(db, profile, consent.EMOTION_SIGNALS):
        return
    same_database = sessionmaker(bind=db.get_bind())
    task = asyncio.create_task(analyze_message(message_id, llm, session_factory=same_database))
    _running.add(task)
    task.add_done_callback(_running.discard)
