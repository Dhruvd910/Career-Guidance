from sqlalchemy import Float, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.core.types import Json
from app.models.mixins import ProvenanceMixin, TimestampMixin


class Placement(Base, ProvenanceMixin, TimestampMixin):
    """§18: engineering uses placement %/packages; medical must NOT be forced into
    "placement" language — its metrics (internship stipend, PG pathways, research) live
    in `extra` and the API/UI pick the right fields by the college's course category."""

    __tablename__ = "placements"

    id: Mapped[int] = mapped_column(primary_key=True)
    college_id: Mapped[int] = mapped_column(ForeignKey("colleges.id"), index=True)
    course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.id"), nullable=True)

    # Engineering-style metrics
    placement_percentage: Mapped[float | None] = mapped_column(Float, nullable=True)
    average_package: Mapped[float | None] = mapped_column(Float, nullable=True)
    median_package: Mapped[float | None] = mapped_column(Float, nullable=True)
    highest_package: Mapped[float | None] = mapped_column(Float, nullable=True)
    major_recruiters: Mapped[list] = mapped_column(Json, default=list)

    # Medical/other-category metrics: internship_stipend, clinical_exposure,
    # pg_pathways, research_opportunities, residency_opportunities, etc.
    extra: Mapped[dict] = mapped_column(Json, default=dict)

    college: Mapped["College"] = relationship()  # noqa: F821
