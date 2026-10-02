"""Writing what a counselling session amounted to into the student's memory (spec §6.2, §8, §22).

At the end of a session: the transcript → one LLM call (JSON) → the summary, decisions, open
topics, interests, goals, constraints and memorable facts → checked → reconciled with what MAYA
already remembers → written in one transaction, with the timeline events that record each change.

The check is what keeps memory honest: every item has to cite the messages it came from and
quote them, and an item whose quote isn't in those messages is dropped — so a model that
"remembers" something the student never said can't put it into memory.

Only with the long-term memory permission (app/memory/consent.py).
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.memory import consent
from app.models.chat import Conversation, Message
from app.models.memory import (
    CounsellingThread, MemoryItem, SessionSummary, StudentConstraint, StudentEvent, StudentGoal, StudentInterest,
    TurnAnalysis,
)
from app.models.student import StudentProfile
from app.providers.embedding import EmbeddingProvider
from app.providers.llm import LLMProvider

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 2  # 2: what happened, and roadmap_changes, from the modules (Phase 7)
MAX_TRANSCRIPT_CHARS = 14_000
DUPLICATE_SIMILARITY = 0.92  # a new memory this close to an old one is the same memory
SIGNAL_THRESHOLD = 0.5  # weaker readings of how the student seemed are not kept


# ---------------- what the model is asked for ----------------

class Evidence(BaseModel):
    messages: list[int] = Field(min_length=1)
    quote: str = Field(min_length=3)


class ThreadUpdate(BaseModel):
    thread_id: int | None = None  # an existing thread's id, or None for a new one
    topic_key: str
    title: str
    status: Literal["open", "parked", "resolved", "reopened"] = "open"
    decision_status: Literal["undecided", "leaning", "decided", "reopened"] = "undecided"
    current_position: str = ""
    open_questions: list[str] = []
    actions_agreed: list[str] = []
    next_step: str | None = None
    evidence: Evidence


class InterestUpdate(BaseModel):
    label: str
    change: Literal["added", "confirmed", "removed"] = "added"
    strength: float = Field(default=0.6, ge=0, le=1)
    evidence: Evidence


class GoalUpdate(BaseModel):
    title: str
    kind: Literal["exam", "skill", "decision", "project", "other"] = "other"
    evidence: Evidence


class ConstraintUpdate(BaseModel):
    kind: Literal["budget", "location", "relocation", "time", "family_expectation", "other"] = "other"
    detail: str
    sensitive: bool = False
    evidence: Evidence


class MemoryUpdate(BaseModel):
    kind: Literal["fact", "preference", "concern", "aspiration", "constraint"] = "fact"
    text: str
    sensitive: bool = False
    supersedes: list[int] = []  # ids of memories this one replaces
    evidence: Evidence


class ProfileUpdate(BaseModel):
    city: str | None = None
    stream: Literal["PCM", "PCB", "PCMB", "commerce", "humanities"] | None = None
    study_hours_per_week: int | None = Field(default=None, ge=0, le=100)
    evidence: Evidence


class SessionExtraction(BaseModel):
    summary: str
    important_context: list[str] = []
    decisions: list[str] = []
    unresolved_questions: list[str] = []
    next_steps: list[str] = []
    threads: list[ThreadUpdate] = []
    interests: list[InterestUpdate] = []
    goals: list[GoalUpdate] = []
    constraints: list[ConstraintUpdate] = []
    memories: list[MemoryUpdate] = []
    profile: ProfileUpdate | None = None


INSTRUCTIONS = """You keep the counselling notes for MAYA, an AI career counsellor for Indian students. \
Read one session's transcript and return ONE JSON object recording what matters for future sessions.

Rules:
- Record only what the conversation shows. Never infer facts the student did not express.
- Every thread, interest, goal, constraint, memory and profile change needs "evidence": the ids of the \
messages it comes from (the numbers in [m12]) and a short "quote" copied EXACTLY, word for word, from one \
of those messages — in its original language and script. Interests, constraints, memories and profile \
changes are facts about the student, so they must quote the student's own messages.
- Threads are counselling topics that can continue across sessions (e.g. "PCM vs PCB", "JEE strategy"). \
If the session continued one of the existing threads listed below, update it using its thread_id; otherwise \
use thread_id null. decision_status: undecided / leaning / decided / reopened.
- Interests: change "added" for a new interest, "confirmed" for one already known, "removed" if the student \
said they no longer want it.
- Memories: short third-person facts worth recalling later ("Built a line-follower robot in class 9"). \
If one contradicts an existing memory listed below, put that memory's id in "supersedes".
- Capture every constraint the student states — where they will or won't study (location, relocation), \
money, time, what their family expects — and every worry they voice (as a memory of kind "concern").
- Goals can be steps MAYA suggested that the student agreed to; quote whichever message states the goal.
- Mark anything about family conflict, money, health or other private matters "sensitive": true.
- profile: only if the student explicitly stated their city, stream or weekly study hours; else null.
- Write the summary and notes in English, even if the conversation was in Hindi or Hinglish; quotes stay \
exactly as said.

Return exactly this shape (lists may be empty; every "evidence" is required):
{
  "summary": "two or three sentences",
  "important_context": ["short fact", "..."],
  "decisions": ["what the student decided", "..."],
  "unresolved_questions": ["question still open", "..."],
  "next_steps": ["agreed next step", "..."],
  "threads": [{"thread_id": null, "topic_key": "stream_choice", "title": "PCM vs PCB",
               "status": "open", "decision_status": "leaning", "current_position": "where it stands",
               "open_questions": ["..."], "actions_agreed": ["..."], "next_step": "...",
               "evidence": {"messages": [12], "quote": "exact words"}}],
  "interests": [{"label": "Computers", "change": "added", "strength": 0.8,
                 "evidence": {"messages": [14], "quote": "exact words"}}],
  "goals": [{"title": "Finish the aptitude assessment", "kind": "decision",
             "evidence": {"messages": [18], "quote": "exact words"}}],
  "constraints": [{"kind": "family_expectation", "detail": "Father wants a medical career", "sensitive": true,
                   "evidence": {"messages": [16], "quote": "exact words"}}],
  "memories": [{"kind": "fact", "text": "Made a game in Scratch last year", "sensitive": false, "supersedes": [],
                "evidence": {"messages": [14], "quote": "exact words"}}],
  "profile": null
}
goal kind: exam | skill | decision | project | other. constraint kind: budget | location | relocation | time | \
family_expectation | other. memory kind: fact | preference | concern | aspiration | constraint. profile, when \
stated: {"city": "...", "stream": "PCM|PCB|PCMB|commerce|humanities", "study_hours_per_week": 10, \
"evidence": {...}} with only the stated fields."""


# ---------------- writing ----------------

def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text.lower())).strip()


def _transcript(messages: list[Message]) -> str:
    lines = []
    for m in messages:
        who = "student" if m.role == "user" else "MAYA"
        cut = " [interrupted — the student heard only this]" if m.interrupted else ""
        lines.append(f"[m{m.id}] {who}: {m.content}{cut}")
    text = "\n".join(lines)
    return text[-MAX_TRANSCRIPT_CHARS:]


def _verified(evidence: Evidence, by_id: dict[int, Message], student_only: bool) -> bool:
    quote = _normalise(evidence.quote)
    if len(quote) < 3:
        return False
    for message_id in evidence.messages:
        message = by_id.get(message_id)
        if message is None or (student_only and message.role != "user"):
            continue
        if quote in _normalise(message.content):
            return True
    return False


def _context(db: Session, profile: StudentProfile) -> str:
    threads = db.execute(select(CounsellingThread).where(
        CounsellingThread.student_profile_id == profile.id, CounsellingThread.status != "resolved")).scalars().all()
    memories = db.execute(select(MemoryItem).where(
        MemoryItem.student_profile_id == profile.id, MemoryItem.status == "active")
        .order_by(MemoryItem.created_at.desc()).limit(30)).scalars().all()
    interests = db.execute(select(StudentInterest).where(
        StudentInterest.student_profile_id == profile.id, StudentInterest.status == "active")).scalars().all()
    lines = ["Existing threads:"]
    lines += [f"- thread_id {t.id}: {t.title} ({t.decision_status}) — {t.current_position}" for t in threads] or ["- none"]
    lines += ["Existing memories:"]
    lines += [f"- id {m.id}: {m.text}" for m in memories] or ["- none"]
    lines += ["Known interests: " + (", ".join(i.label for i in interests) or "none")]
    return "\n".join(lines)


async def write_session_memory(db: Session, conversation_id: int, llm: LLMProvider,
                               embedder: EmbeddingProvider | None) -> SessionSummary | None:
    """Writes one finished session into memory. Idempotent: a session already written is left
    alone. Returns the summary, or None if there was nothing to write or no permission."""
    conversation = db.get(Conversation, conversation_id)
    if conversation is None:
        return None
    profile = db.get(StudentProfile, conversation.student_profile_id)
    if db.get(SessionSummary, conversation_id) is not None:
        return db.get(SessionSummary, conversation_id)
    if not consent.allowed(db, profile, consent.LONG_TERM_MEMORY):
        return None
    messages = [m for m in conversation.messages if m.role in ("user", "assistant") and m.content.strip()]
    if not any(m.role == "user" for m in messages):
        return None

    request = [
        {"role": "system", "content": INSTRUCTIONS},
        {"role": "system", "content": _context(db, profile)},
        {"role": "user", "content": _transcript(messages)},
    ]
    extraction = None
    for attempt in (1, 2):
        reply = await llm.chat(request, json_mode=True)
        content = reply.get("content") or ""
        try:
            extraction = SessionExtraction.model_validate(json.loads(_strip_fences(content)))
            break
        except (ValueError, ValidationError) as e:
            logger.warning("session %s: notes didn't fit the schema (attempt %d): %s", conversation_id, attempt,
                           str(e).splitlines()[0])
            # Once: show the model what was wrong. A second miss writes nothing.
            request = request + [{"role": "assistant", "content": content},
                                 {"role": "user", "content": f"That JSON doesn't match the required shape:\n{e}\n"
                                                             "Return the corrected JSON object only."}]
    if extraction is None:
        return None

    by_id = {m.id: m for m in messages}
    now = datetime.now(timezone.utc)
    dropped = 0

    def ok(item, student_only: bool = True) -> bool:
        nonlocal dropped
        if _verified(item.evidence, by_id, student_only):
            return True
        dropped += 1
        logger.info("session %s: dropped %s — its quote isn't in the cited messages: %r",
                    conversation_id, type(item).__name__, item.evidence.quote)
        return False

    def event(event_type: str, entity_type: str | None = None, entity_id=None, reason: str | None = None,
              **payload) -> None:
        db.add(StudentEvent(student_profile_id=profile.id, event_type=event_type, occurred_at=now, actor="ai",
                            entity_type=entity_type, entity_id=str(entity_id) if entity_id is not None else None,
                            payload=payload, reason=reason, session_id=conversation_id))

    touched = []
    own_threads = {t.id: t for t in db.execute(select(CounsellingThread).where(
        CounsellingThread.student_profile_id == profile.id)).scalars()}
    for update in extraction.threads:
        if not ok(update, student_only=False):
            continue
        thread = own_threads.get(update.thread_id) if update.thread_id else None
        before = thread.decision_status if thread else None
        if thread is None:
            thread = CounsellingThread(student_profile_id=profile.id, topic_key=update.topic_key, title=update.title,
                                       opened_session_id=conversation_id)
            db.add(thread)
        for field in ("status", "decision_status", "current_position", "open_questions", "actions_agreed",
                      "next_step"):
            setattr(thread, field, getattr(update, field))
        thread.last_session_id, thread.last_touched_at = conversation_id, now
        thread.resolved_at = now if update.status == "resolved" else None
        db.flush()
        touched.append(thread.id)
        if update.decision_status == "decided" and before != "decided":
            event("DECISION_MADE", "thread", thread.id, update.current_position, title=update.title)
        elif update.decision_status == "reopened" and before == "decided":
            event("DECISION_REOPENED", "thread", thread.id, update.current_position, title=update.title)

    interests = {i.label.lower(): i for i in db.execute(select(StudentInterest).where(
        StudentInterest.student_profile_id == profile.id)).scalars()}
    for update in extraction.interests:
        if not ok(update):
            continue
        known = interests.get(update.label.lower())
        if update.change == "removed":
            if known is not None and known.status == "active":
                known.status = "removed"
                event("CAREER_INTEREST_REMOVED", "interest", known.id, update.evidence.quote, label=known.label)
            continue
        if known is None:
            known = StudentInterest(student_profile_id=profile.id, label=update.label, strength=update.strength,
                                    source_session_id=conversation_id)
            db.add(known)
            db.flush()
            interests[update.label.lower()] = known
            event("CAREER_INTEREST_ADDED", "interest", known.id, update.evidence.quote, label=update.label)
        else:
            known.status, known.strength, known.last_confirmed_at = "active", update.strength, now

    for update in extraction.goals:
        if ok(update, student_only=False):  # a goal is often MAYA's suggestion the student agreed to
            goal = StudentGoal(student_profile_id=profile.id, title=update.title, kind=update.kind,
                               source_session_id=conversation_id)
            db.add(goal)
            db.flush()
            event("GOAL_CREATED", "goal", goal.id, update.evidence.quote, title=update.title)

    for update in extraction.constraints:
        if ok(update):
            db.add(StudentConstraint(student_profile_id=profile.id, kind=update.kind, detail=update.detail,
                                     sensitivity="sensitive" if update.sensitive else "normal",
                                     source_session_id=conversation_id))

    _write_memories(db, profile, conversation_id, [m for m in extraction.memories if ok(m)], embedder)

    if extraction.profile is not None and ok(extraction.profile):
        changed = {f: v for f in ("city", "stream", "study_hours_per_week")
                   if (v := getattr(extraction.profile, f)) is not None and getattr(profile, f) != v}
        for field, value in changed.items():
            setattr(profile, field, value)
        if changed:
            event("PROFILE_UPDATED", "profile", profile.id, extraction.profile.evidence.quote, **changed)

    from app.mentor.session_facts import happened

    record = happened(db, conversation, now)
    summary = SessionSummary(
        happened=record["happened"], roadmap_changes=record["roadmap_changes"],
        conversation_id=conversation_id, student_profile_id=profile.id, schema_version=SCHEMA_VERSION,
        summary=extraction.summary, important_context=extraction.important_context, decisions=extraction.decisions,
        unresolved_questions=extraction.unresolved_questions, new_interests=[
            i.label for i in extraction.interests if i.change == "added"],
        goals=[g.title for g in extraction.goals], next_steps=extraction.next_steps,
        student_state=_student_state(db, profile, conversation_id), threads_touched=touched, model=llm.model_id,
    )
    db.add(summary)
    event("COUNSELLING_SESSION", "conversation", conversation_id, None, summary=extraction.summary,
          threads=touched)
    conversation.status, conversation.ended_at = "closed", conversation.ended_at or now
    db.commit()
    logger.info("session %s written to memory: %d threads, %d memories, %d items dropped as unsupported",
                conversation_id, len(touched), len(extraction.memories), dropped)
    return summary


def _write_memories(db: Session, profile: StudentProfile, conversation_id: int, updates: list[MemoryUpdate],
                    embedder: EmbeddingProvider | None) -> None:
    if not updates:
        return
    from app.memory.store import search_memories

    vectors = embedder.embed([u.text for u in updates], "passage") if embedder else [None] * len(updates)
    own = {m.id: m for m in db.execute(select(MemoryItem).where(
        MemoryItem.student_profile_id == profile.id, MemoryItem.status == "active")).scalars()}
    for update, vector in zip(updates, vectors):
        if vector is not None:
            nearest = search_memories(db, profile.id, vector, k=1, include_sensitive=True)
            if nearest and nearest[0][1] >= DUPLICATE_SIMILARITY and nearest[0][0].id not in update.supersedes:
                same = nearest[0][0]
                same.salience = min(1.0, same.salience + 0.1)  # said again: it matters more
                same.evidence_message_ids = sorted(set(same.evidence_message_ids) | set(update.evidence.messages))
                continue
        item = MemoryItem(student_profile_id=profile.id, kind=update.kind, text=update.text, embedding=vector,
                          embed_model=embedder.model_id if embedder and vector is not None else None,
                          sensitivity="sensitive" if update.sensitive else "normal",
                          source_session_id=conversation_id, evidence_message_ids=update.evidence.messages)
        db.add(item)
        db.flush()
        for old_id in update.supersedes:
            old = own.get(old_id)  # only this student's own memories can be replaced
            if old is not None:
                old.status, old.superseded_by = "superseded", item.id


def _student_state(db: Session, profile: StudentProfile, conversation_id: int) -> list[dict]:
    """How the student seemed across the session, from the per-turn readings: each signal's
    strongest confident reading. Only with that permission, and hedged by its confidences."""
    if not consent.allowed(db, profile, consent.EMOTION_SIGNALS):
        return []
    analyses = db.execute(select(TurnAnalysis).join(Message, Message.id == TurnAnalysis.message_id)
                          .where(Message.conversation_id == conversation_id)).scalars().all()
    strongest: dict[str, float] = {}
    for analysis in analyses:
        for reading in analysis.emotion_signals or []:
            confidence = float(reading.get("confidence", 0))
            if confidence >= SIGNAL_THRESHOLD:
                signal = str(reading.get("signal"))
                strongest[signal] = max(strongest.get(signal, 0.0), confidence)
    return [{"signal": s, "confidence": round(c, 2)} for s, c in sorted(strongest.items(), key=lambda kv: -kv[1])]


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        text = text.rsplit("```", 1)[0]
    return text
