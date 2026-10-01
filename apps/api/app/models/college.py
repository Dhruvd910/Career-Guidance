from sqlalchemy import Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.core.types import Json
from app.models.mixins import ProvenanceMixin, TimestampMixin


class College(Base, TimestampMixin):
    """Canonical college record (§26 normalization) — the prediction engine and all
    college-facing features operate on this id, never on a raw name string."""

    __tablename__ = "colleges"

    id: Mapped[int] = mapped_column(primary_key=True)
    canonical_name: Mapped[str] = mapped_column(String(255), index=True)
    aliases: Mapped[list] = mapped_column(Json, default=list)

    college_type: Mapped[str] = mapped_column(String(50))  # IIT|NIT|IIIT|GFTI|State|Private|Deemed|Medical-Govt|...
    ownership: Mapped[str] = mapped_column(String(20))  # government | private | deemed
    state: Mapped[str] = mapped_column(String(100))
    city: Mapped[str] = mapped_column(String(100))
    established_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    affiliated_university: Mapped[str | None] = mapped_column(String(255), nullable=True)
    accreditation: Mapped[str | None] = mapped_column(String(500), nullable=True)
    official_website: Mapped[str | None] = mapped_column(String(500), nullable=True)
    logo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    is_demo_data: Mapped[bool] = mapped_column(default=True)
    # Where it is — kept in step with its current location.coordinates fact (Phase 6), for distance filters.
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))  # B.Tech | MBBS | BDS | B.Arch | ...
    level: Mapped[str] = mapped_column(String(20))  # UG | PG
    duration_years: Mapped[float] = mapped_column(default=4.0)


class Branch(Base):
    __tablename__ = "branches"

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"))
    name: Mapped[str] = mapped_column(String(255))  # Computer Science and Engineering | ...
    code: Mapped[str] = mapped_column(String(50))


class CollegeCourse(Base, ProvenanceMixin, TimestampMixin):
    """Which colleges offer which course(+branch), accepting which exam — the join the
    predictor and cutoffs table key off (§10 college+branch+category+quota+year+round)."""

    __tablename__ = "college_courses"

    id: Mapped[int] = mapped_column(primary_key=True)
    college_id: Mapped[int] = mapped_column(ForeignKey("colleges.id"))
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"))
    branch_id: Mapped[int | None] = mapped_column(ForeignKey("branches.id"), nullable=True)
    exam_id: Mapped[int] = mapped_column(ForeignKey("exams.id"))
    total_seats: Mapped[int | None] = mapped_column(Integer, nullable=True)

    college: Mapped["College"] = relationship()
    course: Mapped["Course"] = relationship()
    branch: Mapped["Branch | None"] = relationship()
    exam: Mapped["Exam"] = relationship()  # noqa: F821
