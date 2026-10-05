"""What MAYA remembers about a student, in layers (docs/design/03-memory-schema.md):

- consent and requests about it (DPDP: students are mostly minors)
- profile details beyond the basics: interests, goals, constraints
- counselling memory: topics that span sessions (threads) and a summary of each session
- the timeline: events, appended, never edited
- semantic memory: loose but useful facts, searchable by meaning
- per-turn reading of how the student seems (signals with confidences, never diagnoses)

Nothing here is written without the student's — for a minor, a guardian's — consent.
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.types import Embedding, EncryptedJson, EncryptedText, Json
from app.models.mixins import TimestampMixin

EMBEDDING_DIM = 384  # multilingual-e5-small


class Consent(Base, TimestampMixin):
    """One decision about one kind of processing. A new decision is a new row; the latest wins."""

    __tablename__ = "consents"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_profile_id: Mapped[int] = mapped_column(ForeignKey("student_profiles.id"), index=True)
    kind: Mapped[str] = mapped_column(String(30))  # long_term_memory | emotion_signals
    granted: Mapped[bool] = mapped_column(Boolean)
    granted_by: Mapped[str] = mapped_column(String(20))  # student | guardian
    # For a minor: who consented — {name, relationship, contact}. Declared, not verified: DPDP's
    # "verifiable" parental consent needs an identity check this app can't do on its own.
    guardian: Mapped[dict | None] = mapped_column(EncryptedJson, nullable=True)
    verification: Mapped[str] = mapped_column(String(20), default="declared")
    notice_version: Mapped[str] = mapped_column(String(20))  # which wording they agreed to
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DataRequest(Base, TimestampMixin):
    __tablename__ = "data_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_profile_id: Mapped[int] = mapped_column(ForeignKey("student_profiles.id"), index=True)
    kind: Mapped[str] = mapped_column(String(30))  # delete_memory_item | delete_all_memory | export
    status: Mapped[str] = mapped_column(String(20), default="done")
    detail: Mapped[dict] = mapped_column(Json, default=dict)


class StudentInterest(Base, TimestampMixin):
    __tablename__ = "student_interests"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_profile_id: Mapped[int] = mapped_column(ForeignKey("student_profiles.id"), index=True)
    label: Mapped[str] = mapped_column(String(120))  # "AI / machine learning", "biology"
    node_key: Mapped[str | None] = mapped_column(String(120), nullable=True)  # career graph, Phase 4
    strength: Mapped[float] = mapped_column(Float, default=0.5)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | removed
    source_session_id: Mapped[int | None] = mapped_column(ForeignKey("conversations.id"), nullable=True)
    last_confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StudentGoal(Base, TimestampMixin):
    __tablename__ = "student_goals"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_profile_id: Mapped[int] = mapped_column(ForeignKey("student_profiles.id"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    kind: Mapped[str] = mapped_column(String(20), default="other")  # exam | skill | decision | project | other
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | done | dropped
    source_session_id: Mapped[int | None] = mapped_column(ForeignKey("conversations.id"), nullable=True)


class StudentConstraint(Base, TimestampMixin):
    __tablename__ = "student_constraints"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_profile_id: Mapped[int] = mapped_column(ForeignKey("student_profiles.id"), index=True)
    kind: Mapped[str] = mapped_column(String(30))  # budget | location | relocation | time | family_expectation | other
    detail: Mapped[str] = mapped_column(EncryptedText)
    # Family conflict, money, health: kept out of the prompt unless the question needs them.
    sensitivity: Mapped[str] = mapped_column(String(20), default="normal")  # normal | sensitive
    status: Mapped[str] = mapped_column(String(20), default="active")
    source_session_id: Mapped[int | None] = mapped_column(ForeignKey("conversations.id"), nullable=True)


class CounsellingThread(Base, TimestampMixin):
    """One counselling topic that can run over many sessions — the unit of "where we left off"."""

    __tablename__ = "counselling_threads"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_profile_id: Mapped[int] = mapped_column(ForeignKey("student_profiles.id"), index=True)
    topic_key: Mapped[str] = mapped_column(String(80))  # stream_choice, career_direction, exam_strategy…
    title: Mapped[str] = mapped_column(String(200))  # "PCM vs PCB"
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | parked | resolved | reopened
    decision_status: Mapped[str] = mapped_column(String(20), default="undecided")  # undecided | leaning | decided | reopened
    current_position: Mapped[str] = mapped_column(Text, default="")
    open_questions: Mapped[list] = mapped_column(Json, default=list)
    actions_agreed: Mapped[list] = mapped_column(Json, default=list)
    next_step: Mapped[str | None] = mapped_column(Text, nullable=True)
    opened_session_id: Mapped[int | None] = mapped_column(ForeignKey("conversations.id"), nullable=True)
    last_session_id: Mapped[int | None] = mapped_column(ForeignKey("conversations.id"), nullable=True)
    last_touched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SessionSummary(Base, TimestampMixin):
    """What one counselling session amounted to (spec §22), written when it ends."""

    __tablename__ = "session_summaries"

    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), primary_key=True)
    student_profile_id: Mapped[int] = mapped_column(ForeignKey("student_profiles.id"), index=True)
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    summary: Mapped[str] = mapped_column(EncryptedText)
    important_context: Mapped[list] = mapped_column(Json, default=list)
    decisions: Mapped[list] = mapped_column(Json, default=list)
    unresolved_questions: Mapped[list] = mapped_column(Json, default=list)
    new_interests: Mapped[list] = mapped_column(Json, default=list)
    goals: Mapped[list] = mapped_column(Json, default=list)
    next_steps: Mapped[list] = mapped_column(Json, default=list)
    roadmap_changes: Mapped[list] = mapped_column(Json, default=list)
    # Aggregated and hedged — e.g. [{"signal": "confusion", "confidence": 0.7}] — never a diagnosis.
    student_state: Mapped[list] = mapped_column(Json, default=list)
    # Phase 7: what actually happened, from the modules (roadmap versions, steps, assessments, shortlist).
    happened: Mapped[list] = mapped_column(Json, default=list)
    threads_touched: Mapped[list] = mapped_column(Json, default=list)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)


class StudentEvent(Base):
    """The student's journey, one event at a time (spec §8). Appended, never edited."""

    __tablename__ = "student_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_profile_id: Mapped[int] = mapped_column(ForeignKey("student_profiles.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(40))  # CAREER_INTEREST_ADDED, DECISION_MADE, …
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    actor: Mapped[str] = mapped_column(String(20), default="ai")  # student | ai | system | counsellor
    entity_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    payload: Mapped[dict] = mapped_column(Json, default=dict)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    session_id: Mapped[int | None] = mapped_column(ForeignKey("conversations.id"), nullable=True)


class MemoryItem(Base, TimestampMixin):
    """A loose but useful fact — "built a line-follower robot", "parents prefer PCB" — found by
    meaning when a question touches it."""

    __tablename__ = "memory_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_profile_id: Mapped[int] = mapped_column(ForeignKey("student_profiles.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # fact | preference | concern | aspiration | constraint
    text: Mapped[str] = mapped_column(EncryptedText)
    embedding: Mapped[list | None] = mapped_column(Embedding(EMBEDDING_DIM), nullable=True)
    embed_model: Mapped[str | None] = mapped_column(String(60), nullable=True)
    salience: Mapped[float] = mapped_column(Float, default=0.5)
    confidence: Mapped[float] = mapped_column(Float, default=0.8)
    sensitivity: Mapped[str] = mapped_column(String(20), default="normal")  # normal | sensitive
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | superseded | retracted
    superseded_by: Mapped[int | None] = mapped_column(ForeignKey("memory_items.id"), nullable=True)
    source_session_id: Mapped[int | None] = mapped_column(ForeignKey("conversations.id"), nullable=True)
    evidence_message_ids: Mapped[list] = mapped_column(Json, default=list)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TurnAnalysis(Base):
    """How the student seemed in one message (spec §5): conversational signals with confidences,
    used to shape the next reply. Never clinical, never on the profile, never shown to parents."""

    __tablename__ = "turn_analyses"

    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id"), primary_key=True)
    student_profile_id: Mapped[int] = mapped_column(ForeignKey("student_profiles.id"), index=True)
    intent: Mapped[str | None] = mapped_column(String(60), nullable=True)
    topic: Mapped[str | None] = mapped_column(String(120), nullable=True)
    emotion_signals: Mapped[list] = mapped_column(Json, default=list)  # [{"signal": "confusion", "confidence": 0.72}]
    underlying_concerns: Mapped[list] = mapped_column(EncryptedJson, default=list)
    safety: Mapped[str] = mapped_column(String(20), default="none")  # none | self_harm | abuse
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
