from sqlalchemy import Boolean, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.core.types import Json
from app.models.mixins import TimestampMixin


class StudentProfile(Base, TimestampMixin):
    __tablename__ = "student_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)

    name: Mapped[str] = mapped_column(String(255))
    class_level: Mapped[int] = mapped_column(Integer)  # 6-12; 12 for a college student (see education_stage)
    # Beyond class 12 too (spec §18): class_6…class_12 | dropper | ug_y1…ug_y5 | pg | graduate
    education_stage: Mapped[str | None] = mapped_column(String(20), nullable=True)
    stream: Mapped[str | None] = mapped_column(String(20), nullable=True)  # PCM | PCB | PCMB | commerce | humanities
    # Year only: enough to know whether a guardian must consent, without a full date of birth.
    birth_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    study_hours_per_week: Mapped[int | None] = mapped_column(Integer, nullable=True)
    school_board: Mapped[str | None] = mapped_column(String(50), nullable=True)
    state: Mapped[str | None] = mapped_column(String(100), nullable=True)
    domicile_state: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Only used where legally/operationally relevant to admission prediction (§4, §42).
    # Never exposed on public profiles/leaderboards.
    category: Mapped[str | None] = mapped_column(String(20), nullable=True)

    preferred_language: Mapped[str] = mapped_column(String(50), default="English")
    # Running mix of the languages the student actually uses, e.g. {"en": 0.2, "hinglish": 0.8}
    # (app/ai/language.py) — a habit, not a setting: each turn is still answered in its own language.
    language_stats: Mapped[dict | None] = mapped_column(Json, nullable=True)
    preferred_study_locations: Mapped[list] = mapped_column(Json, default=list)

    knows_career_goal: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # What the student is actually aiming at (JEE_MAIN / NEET_UG / "careers" while still
    # exploring). Everything the app suggests keys off this, so a NEET student isn't shown
    # engineering colleges, branches, or mock tests.
    target_exam_code: Mapped[str | None] = mapped_column(String(30), nullable=True)
    onboarding_completed: Mapped[bool] = mapped_column(Boolean, default=False)

    user: Mapped["User"] = relationship(back_populates="student_profile")  # noqa: F821
    academic_records: Mapped[list["AcademicRecord"]] = relationship(
        back_populates="student_profile", cascade="all, delete-orphan"
    )


class AcademicRecord(Base, TimestampMixin):
    __tablename__ = "academic_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_profile_id: Mapped[int] = mapped_column(ForeignKey("student_profiles.id"))

    academic_year: Mapped[str] = mapped_column(String(20))
    class_level: Mapped[int] = mapped_column(Integer)
    board_percentage: Mapped[float | None] = mapped_column(Float, nullable=True)
    # e.g. {"physics": 85, "chemistry": 78, "maths": 90, "biology": 70, "computer_science": 88}
    subject_marks: Mapped[dict] = mapped_column(Json, default=dict)

    student_profile: Mapped["StudentProfile"] = relationship(back_populates="academic_records")
