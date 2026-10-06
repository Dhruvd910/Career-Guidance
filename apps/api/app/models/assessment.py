"""Assessments (spec §10, docs/design/12-phase3-plan.md): versioned instruments, each attempt a
student makes at one, what they answered, and what it measured.

Instruments are written as JSON files (app/assessment/instruments/) and synced into these
tables, so every attempt records exactly which version of which questions it answered. Scores
are per dimension — `aptitude:logical`, `skill:programming`, `maths` — honest proportions with
the number of items behind them, never norms or percentiles.

Career directions combine the latest attempt at each instrument; each time one completes, a
snapshot of the directions is kept, so "why did MAYA suggest this in March?" has an answer.
"""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.core.types import Json


class AssessmentInstrument(Base):
    __tablename__ = "assessment_instruments"
    __table_args__ = (UniqueConstraint("key", "version", name="uq_instrument_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(40))  # interests | aptitude | skills | coding_check | academic
    version: Mapped[int] = mapped_column(Integer)
    # interest | aptitude | skill | academic — doc 02 §6
    category: Mapped[str] = mapped_column(String(20))
    title: Mapped[dict] = mapped_column(Json)  # {"en": …, "hi": …}
    # weighted_options | correct_answers | anchored_levels | marks
    scoring_method: Mapped[str] = mapped_column(String(30))
    est_minutes: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | retired
    content_sha: Mapped[str] = mapped_column(String(64))  # the file this version was loaded from
    loaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    items: Mapped[list["AssessmentItem"]] = relationship(
        back_populates="instrument", cascade="all, delete-orphan", order_by="AssessmentItem.sort",
    )


class AssessmentItem(Base):
    __tablename__ = "assessment_items"
    __table_args__ = (UniqueConstraint("instrument_id", "key", name="uq_item_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("assessment_instruments.id"), index=True)
    key: Mapped[str] = mapped_column(String(60))
    sort: Mapped[int] = mapped_column(Integer)
    item_type: Mapped[str] = mapped_column(String(20))  # choice | anchored | problem | marks
    form: Mapped[str | None] = mapped_column(String(5), nullable=True)  # parallel forms: A | B
    difficulty: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1 easy … 3 hard
    # The item as written: section, prompt, speak, options (+ weights/keywords), answer,
    # requires, applies_to — kept whole so a result can always be explained from it.
    content: Mapped[dict] = mapped_column(Json)

    instrument: Mapped["AssessmentInstrument"] = relationship(back_populates="items")


class AssessmentAttempt(Base):
    __tablename__ = "assessment_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_profile_id: Mapped[int] = mapped_column(ForeignKey("student_profiles.id"), index=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("assessment_instruments.id"))
    form: Mapped[str | None] = mapped_column(String(5), nullable=True)
    mode: Mapped[str] = mapped_column(String(10), default="touch")  # touch | voice | mixed
    language: Mapped[str] = mapped_column(String(10), default="en")  # en | hi
    track: Mapped[str | None] = mapped_column(String(20), nullable=True)  # what the student was heading for (tracks.py)
    status: Mapped[str] = mapped_column(String(20), default="in_progress")  # in_progress | completed | abandoned
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_activity_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The item keys in the order they were shown — "back" walks this.
    path: Mapped[list] = mapped_column(Json, default=list)
    # Set for attempts migrated from the old career_assessments table.
    legacy_assessment_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    instrument: Mapped["AssessmentInstrument"] = relationship()
    responses: Mapped[list["AssessmentResponse"]] = relationship(
        back_populates="attempt", cascade="all, delete-orphan",
    )
    scores: Mapped[list["AssessmentScore"]] = relationship(
        back_populates="attempt", cascade="all, delete-orphan",
    )


class AssessmentResponse(Base):
    __tablename__ = "assessment_responses"
    __table_args__ = (UniqueConstraint("attempt_id", "item_id", name="uq_response_item"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    attempt_id: Mapped[int] = mapped_column(ForeignKey("assessment_attempts.id"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("assessment_items.id"))
    answer: Mapped[dict | None] = mapped_column(Json, nullable=True)  # {"option": "love"} | {"value": 87}
    skipped: Mapped[bool] = mapped_column(default=False)
    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)  # what they said, for voice answers
    interpreted_by: Mapped[str] = mapped_column(String(10), default="touch")  # touch | keywords | llm
    response_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    answered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    attempt: Mapped["AssessmentAttempt"] = relationship(back_populates="responses")
    item: Mapped["AssessmentItem"] = relationship()


class AssessmentScore(Base):
    __tablename__ = "assessment_scores"

    attempt_id: Mapped[int] = mapped_column(ForeignKey("assessment_attempts.id"), primary_key=True)
    dimension_key: Mapped[str] = mapped_column(String(60), primary_key=True)
    score: Mapped[float] = mapped_column(Float)  # 0–1
    n_items: Mapped[int] = mapped_column(Integer)  # how many answers it rests on
    detail: Mapped[dict] = mapped_column(Json, default=dict)  # e.g. {"correct": 7, "asked": 10}

    attempt: Mapped["AssessmentAttempt"] = relationship(back_populates="scores")


class CareerAlignmentSnapshot(Base):
    """The career directions as they stood when an attempt completed — with the attempts they
    came from, so every suggestion can be traced back."""

    __tablename__ = "career_alignment_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_profile_id: Mapped[int] = mapped_column(ForeignKey("student_profiles.id"), index=True)
    engine_version: Mapped[str] = mapped_column(String(20))
    inputs: Mapped[dict] = mapped_column(Json)  # {"interests": attempt_id, "aptitude": attempt_id, …}
    results: Mapped[list] = mapped_column(Json)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
