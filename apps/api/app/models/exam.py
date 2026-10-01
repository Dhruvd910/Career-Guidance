from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.mixins import TimestampMixin


class Exam(Base):
    """Extensible exam catalog (§48) — JEE Main/Advanced/NEET UG today, CUET/CLAT/NATA/etc. later
    without any schema change."""

    __tablename__ = "exams"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True)  # e.g. JEE_MAIN
    name: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(50))  # engineering | medical | other
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class ExamProfile(Base, TimestampMixin):
    __tablename__ = "exam_profiles"
    __table_args__ = (UniqueConstraint("student_profile_id", "exam_id", name="uq_student_exam"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    student_profile_id: Mapped[int] = mapped_column(ForeignKey("student_profiles.id"))
    exam_id: Mapped[int] = mapped_column(ForeignKey("exams.id"))

    status: Mapped[str] = mapped_column(String(30), default="planning")  # planning|preparing|appeared|qualified
    attempt_year: Mapped[int | None] = mapped_column(Integer, nullable=True)

    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    percentile: Mapped[float | None] = mapped_column(Float, nullable=True)
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    category_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # exam-specific extras, e.g. JEE Advanced score/rank, subject-wise split
    extra: Mapped[dict] = mapped_column(JSON, default=dict)

    preferred_branches: Mapped[list] = mapped_column(JSON, default=list)
    preferred_states: Mapped[list] = mapped_column(JSON, default=list)
    preferred_cities: Mapped[list] = mapped_column(JSON, default=list)
    college_type_preference: Mapped[str | None] = mapped_column(String(20), nullable=True)  # government|private|any
    budget_max: Mapped[float | None] = mapped_column(Float, nullable=True)

    exam: Mapped["Exam"] = relationship()
