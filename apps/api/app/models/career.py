from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.types import Json
from app.models.mixins import TimestampMixin


class CareerOption(Base, TimestampMixin):
    """A node in the career graph (§49) — deliberately not hard-coded to JEE=Engineering /
    NEET=Medicine so alternatives (§51) and new pathways can be added by inserting rows."""

    __tablename__ = "career_options"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str | None] = mapped_column(String(50), unique=True, nullable=True)  # stable slug, e.g. "cse"
    name: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(100))  # Engineering|Medical|Law|Design|Commerce|...
    description: Mapped[str] = mapped_column(String(2000), default="")

    required_subjects: Mapped[list] = mapped_column(Json, default=list)
    typical_entrance_exam_codes: Mapped[list] = mapped_column(Json, default=list)
    education_path: Mapped[str] = mapped_column(String(2000), default="")
    skills_required: Mapped[list] = mapped_column(Json, default=list)
    timeline: Mapped[str] = mapped_column(String(500), default="")
    related_career_ids: Mapped[list] = mapped_column(Json, default=list)
    possible_challenges: Mapped[list] = mapped_column(Json, default=list)
    explore_next: Mapped[list] = mapped_column(Json, default=list)
    # How much the career draws on each assessment dimension (0-3), and the dimensions it
    # can't do without — see app/seed/careers.json and services/assessment_engine.py.
    profile: Mapped[dict] = mapped_column(Json, default=dict)
    must: Mapped[list] = mapped_column(Json, default=list)
    # The long-form guide: how to prepare, where to start, resources, roles, earnings + sources.
    details: Mapped[dict] = mapped_column(Json, default=dict)


class CareerAssessment(Base, TimestampMixin):
    __tablename__ = "career_assessments"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_profile_id: Mapped[int] = mapped_column(ForeignKey("student_profiles.id"))

    # class8_9_exploration | class10_stream | class11_12_career
    assessment_type: Mapped[str] = mapped_column(String(50))
    responses: Mapped[dict] = mapped_column(Json, default=dict)
    # list of {career_option_id, fit_score, rationale, challenges, next_steps}
    results: Mapped[list] = mapped_column(Json, default=list)
