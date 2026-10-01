from datetime import date

from sqlalchemy import Date, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.core.types import Json
from app.models.mixins import TimestampMixin


class MockTest(Base, TimestampMixin):
    __tablename__ = "mock_tests"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_profile_id: Mapped[int] = mapped_column(ForeignKey("student_profiles.id"))
    exam_id: Mapped[int] = mapped_column(ForeignKey("exams.id"))

    test_name: Mapped[str] = mapped_column(String(255))
    test_date: Mapped[date] = mapped_column(Date)

    total_score: Mapped[float] = mapped_column(Float)
    max_score: Mapped[float] = mapped_column(Float)
    percentile: Mapped[float | None] = mapped_column(Float, nullable=True)
    estimated_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # e.g. {"physics": 60, "chemistry": 55, "maths": 70} out of subject max — see note in schema
    subject_scores: Mapped[dict] = mapped_column(Json, default=dict)

    exam: Mapped["Exam"] = relationship()  # noqa: F821
