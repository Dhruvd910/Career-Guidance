from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.mixins import ProvenanceMixin, TimestampMixin


class Cutoff(Base, ProvenanceMixin, TimestampMixin):
    """The §23 cutoff table — historical admission data keyed at full granularity
    (college_course + year + round + category + quota + seat_type), never just "college"."""

    __tablename__ = "cutoffs"
    __table_args__ = (
        UniqueConstraint(
            "college_course_id", "year", "round", "category", "quota", "seat_type",
            name="uq_cutoff_key",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    college_course_id: Mapped[int] = mapped_column(ForeignKey("college_courses.id"), index=True)

    year: Mapped[int] = mapped_column(Integer)
    round: Mapped[int] = mapped_column(Integer, default=1)
    category: Mapped[str] = mapped_column(String(20))  # General|EWS|OBC|SC|ST|Other
    quota: Mapped[str] = mapped_column(String(50))  # AI|HS (home state)|OS|AIQ|State Quota|...
    seat_type: Mapped[str] = mapped_column(String(30), default="Gender-Neutral")

    opening_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    closing_rank: Mapped[int] = mapped_column(Integer)

    college_course: Mapped["CollegeCourse"] = relationship()  # noqa: F821
