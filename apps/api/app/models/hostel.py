from sqlalchemy import Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.core.types import Json
from app.models.mixins import ProvenanceMixin, TimestampMixin


class Hostel(Base, ProvenanceMixin, TimestampMixin):
    """verification_status distinguishes officially-verified facts from student-reported
    ones (§16) — the same column ProvenanceMixin already gives every factual table."""

    __tablename__ = "hostels"

    id: Mapped[int] = mapped_column(primary_key=True)
    college_id: Mapped[int] = mapped_column(ForeignKey("colleges.id"), index=True)

    hostel_type: Mapped[str] = mapped_column(String(20))  # boys | girls | co-ed
    capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    room_types: Mapped[list] = mapped_column(Json, default=list)  # ["single", "double", "triple"]
    fee_annual: Mapped[float | None] = mapped_column(Float, nullable=True)
    facilities: Mapped[list] = mapped_column(Json, default=list)  # ["wifi", "laundry", "security"]
    rules: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    distance_from_academic_block_km: Mapped[float | None] = mapped_column(Float, nullable=True)

    college: Mapped["College"] = relationship()  # noqa: F821
