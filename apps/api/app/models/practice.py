"""Practice papers: a bank of multiple-choice questions, and the attempts students make at
them — either one subject at a time or a full-length paper covering every subject, marked
the way the real exam marks (+4 for a correct answer, -1 for a wrong one).

Questions are written for this app rather than copied from real question papers, so they
carry the same provenance fields as every other factual table (§15/§23/§43) and show up as
practice content, not as past papers.
"""

from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.core.types import Json
from app.models.mixins import TimestampMixin

SUBJECT_MODE, FULL_MODE = "subject", "full"


class Question(Base, TimestampMixin):
    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    subject: Mapped[str] = mapped_column(String(50), index=True)  # Physics/Chemistry/Maths/Biology
    topic: Mapped[str | None] = mapped_column(String(120), nullable=True)
    class_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    difficulty: Mapped[str] = mapped_column(String(20), default="medium")  # easy|medium|hard

    stem: Mapped[str] = mapped_column(Text)
    options: Mapped[list] = mapped_column(Json)  # ["...", "...", "...", "..."]
    correct_index: Mapped[int] = mapped_column(Integer)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)

    source: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    verification_status: Mapped[str] = mapped_column(String(30), default="practice_content")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    exams: Mapped[list["QuestionExam"]] = relationship(back_populates="question", cascade="all, delete-orphan")


class QuestionExam(Base):
    """Which exams a question is relevant to — a mechanics question counts for both JEE and NEET."""

    __tablename__ = "question_exams"
    __table_args__ = (UniqueConstraint("question_id", "exam_id", name="uq_question_exam"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"))
    exam_id: Mapped[int] = mapped_column(ForeignKey("exams.id"), index=True)

    question: Mapped["Question"] = relationship(back_populates="exams")
    exam: Mapped["Exam"] = relationship()  # noqa: F821


class TestAttempt(Base, TimestampMixin):
    __tablename__ = "test_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_profile_id: Mapped[int] = mapped_column(ForeignKey("student_profiles.id"), index=True)
    exam_id: Mapped[int] = mapped_column(ForeignKey("exams.id"))

    mode: Mapped[str] = mapped_column(String(20))  # subject|full
    subject: Mapped[str | None] = mapped_column(String(50), nullable=True)  # None for a full paper
    duration_seconds: Mapped[int] = mapped_column(Integer)  # how long the paper allows

    started_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    seconds_taken: Mapped[int | None] = mapped_column(Integer, nullable=True)

    total_questions: Mapped[int] = mapped_column(Integer)
    correct: Mapped[int] = mapped_column(Integer, default=0)
    wrong: Mapped[int] = mapped_column(Integer, default=0)
    unanswered: Mapped[int] = mapped_column(Integer, default=0)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    max_score: Mapped[float] = mapped_column(Float, default=0.0)
    subject_scores: Mapped[dict] = mapped_column(Json, default=dict)  # {"Physics": {"correct": 7, ...}}

    exam: Mapped["Exam"] = relationship()  # noqa: F821
    answers: Mapped[list["AttemptAnswer"]] = relationship(
        back_populates="attempt", cascade="all, delete-orphan", order_by="AttemptAnswer.position",
    )


class AttemptAnswer(Base):
    __tablename__ = "attempt_answers"

    id: Mapped[int] = mapped_column(primary_key=True)
    attempt_id: Mapped[int] = mapped_column(ForeignKey("test_attempts.id"), index=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"))
    position: Mapped[int] = mapped_column(Integer)  # question order within the paper
    selected_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    attempt: Mapped["TestAttempt"] = relationship(back_populates="answers")
    question: Mapped["Question"] = relationship()
