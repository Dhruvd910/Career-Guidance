"""What MAYA brings to mind before each reply (spec §9): never the whole history — the few things
that matter for this student and this question.

Always: the counselling state (open topics, where each stands, the next step), the last session's
summary, the student's interests, goals and constraints. By meaning: the memories closest to what
was just said, found with the on-device embedding model — no extra LLM call, so no extra wait.
Private things (family pressure, money) come in only when the question is clearly about them.
Within a fixed budget, each item tagged with its id.
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.memory import consent
from app.memory.store import search_memories
from app.models.memory import (
    CounsellingThread, MemoryItem, SessionSummary, StudentConstraint, StudentEvent, StudentGoal, StudentInterest,
)
from app.models.student import StudentProfile
from app.providers.embedding import EmbeddingProvider

BUDGET_CHARS = 2400  # ~600 tokens
MEMORIES = 5
THREADS = 3
EVENTS = 5
# A private memory joins only when the question is this close to it. Measured on the real model
# (2026-10-01): questions about a private item (father's expectations, fees — in English, Hindi and
# Hinglish) scored 0.820-0.885 against it; unrelated questions at most 0.806. A narrow gap from a
# small sample: revisit with real students' questions.
SENSITIVE_MIN_SIMILARITY = 0.815

HEADER = ("What you remember about this student from earlier sessions. Use it naturally — don't recite it, "
          "don't claim more than it says, and if something may have changed, check with them.")


def _ago(when: datetime | None, now: datetime) -> str:
    if when is None:
        return ""
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    days = (now - when).days
    return "today" if days < 1 else "yesterday" if days == 1 else f"{days} days ago"


def build_memory_context(db: Session, profile: StudentProfile, query: str,
                         embedder: EmbeddingProvider | None, now: datetime | None = None) -> str | None:
    """The memory section for the prompt, or None when there's nothing to remember or no
    permission to."""
    if not consent.allowed(db, profile, consent.LONG_TERM_MEMORY):
        return None
    now = now or datetime.now(timezone.utc)
    sections: list[str] = []

    details = [f"{label}: {value}" for label, value in (
        ("Stage", profile.education_stage), ("Stream", profile.stream), ("City", profile.city),
        ("Study time", f"{profile.study_hours_per_week} h/week" if profile.study_hours_per_week else None),
    ) if value]
    if details:
        sections.append("Profile: " + "; ".join(details))

    threads = db.execute(select(CounsellingThread).where(
        CounsellingThread.student_profile_id == profile.id, CounsellingThread.status.in_(("open", "parked", "reopened")))
        .order_by(CounsellingThread.last_touched_at.desc()).limit(THREADS)).scalars().all()
    if threads:
        lines = ["Open topics (most recent first):"]
        for t in threads:
            line = f"- [thread {t.id}] {t.title} — {t.decision_status}; {t.current_position}".rstrip("; ")
            if t.open_questions:
                line += f" Open: {'; '.join(t.open_questions[:3])}."
            if t.next_step:
                line += f" Next step: {t.next_step}."
            lines.append(line + f" (last discussed {_ago(t.last_touched_at, now)})")
        sections.append("\n".join(lines))

    last = db.execute(select(SessionSummary).where(SessionSummary.student_profile_id == profile.id)
                      .order_by(SessionSummary.created_at.desc()).limit(1)).scalar_one_or_none()
    if last:
        text = f"Last session ({_ago(last.created_at, now)}): {last.summary}"
        if last.next_steps:
            text += " Agreed next steps: " + "; ".join(last.next_steps[:3]) + "."
        sections.append(text)

    interests = db.execute(select(StudentInterest.label).where(
        StudentInterest.student_profile_id == profile.id, StudentInterest.status == "active")).scalars().all()
    goals = db.execute(select(StudentGoal.title).where(
        StudentGoal.student_profile_id == profile.id, StudentGoal.status == "active")).scalars().all()
    if interests:
        sections.append("Interests: " + ", ".join(interests))
    if goals:
        sections.append("Goals: " + "; ".join(goals))

    query_vector = embedder.embed([query], "query")[0] if embedder and query.strip() else None
    constraints = db.execute(select(StudentConstraint).where(
        StudentConstraint.student_profile_id == profile.id, StudentConstraint.status == "active")).scalars().all()
    shown = [c for c in constraints if c.sensitivity == "normal"]
    private = [c for c in constraints if c.sensitivity != "normal"]
    if private and query_vector is not None:
        vectors = np.array(embedder.embed([c.detail for c in private], "passage"))
        shown += [c for c, sim in zip(private, vectors @ np.array(query_vector)) if sim >= SENSITIVE_MIN_SIMILARITY]
    if shown:
        sections.append("Constraints: " + "; ".join(f"{c.detail} ({c.kind})" for c in shown))

    used: list[MemoryItem] = []
    if query_vector is not None:
        found = search_memories(db, profile.id, query_vector, k=MEMORIES, include_sensitive=True)
        used = [m for m, sim in found if m.sensitivity == "normal" or sim >= SENSITIVE_MIN_SIMILARITY]
    else:  # no embeddings: the most important recent ones instead
        used = db.execute(select(MemoryItem).where(
            MemoryItem.student_profile_id == profile.id, MemoryItem.status == "active",
            MemoryItem.sensitivity == "normal")
            .order_by(MemoryItem.salience.desc(), MemoryItem.created_at.desc()).limit(MEMORIES)).scalars().all()
    if used:
        sections.append("Things they've told you:\n" + "\n".join(f"- [mem {m.id}] {m.text}" for m in used))
        for m in used:
            m.last_used_at = now

    events = db.execute(select(StudentEvent).where(
        StudentEvent.student_profile_id == profile.id, StudentEvent.event_type != "COUNSELLING_SESSION")
        .order_by(StudentEvent.occurred_at.desc()).limit(EVENTS)).scalars().all()
    if events:
        sections.append("Recent milestones: " + "; ".join(
            f"{e.event_type.replace('_', ' ').lower()}"
            f"{' (' + str(e.payload.get('label') or e.payload.get('title')) + ')' if e.payload.get('label') or e.payload.get('title') else ''}"
            f" {_ago(e.occurred_at, now)}" for e in events))

    if not sections:
        return None
    text = HEADER + "\n\n" + "\n\n".join(sections)
    return text if len(text) <= BUDGET_CHARS else text[:BUDGET_CHARS].rsplit("\n", 1)[0]
