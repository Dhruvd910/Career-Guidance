from sqlalchemy import Float, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.mixins import ProvenanceMixin, TimestampMixin


class Fee(Base, ProvenanceMixin, TimestampMixin):
    __tablename__ = "fees"

    id: Mapped[int] = mapped_column(primary_key=True)
    college_course_id: Mapped[int] = mapped_column(ForeignKey("college_courses.id"), index=True)

    tuition_fee: Mapped[float | None] = mapped_column(Float, nullable=True)
    admission_fee: Mapped[float | None] = mapped_column(Float, nullable=True)
    exam_fee: Mapped[float | None] = mapped_column(Float, nullable=True)
    hostel_fee: Mapped[float | None] = mapped_column(Float, nullable=True)
    mess_fee: Mapped[float | None] = mapped_column(Float, nullable=True)
    security_deposit: Mapped[float | None] = mapped_column(Float, nullable=True)
    other_charges: Mapped[float | None] = mapped_column(Float, nullable=True)

    college_course: Mapped["CollegeCourse"] = relationship()  # noqa: F821

    @property
    def approximate_annual_cost(self) -> float:
        parts = [
            self.tuition_fee, self.admission_fee, self.exam_fee,
            self.hostel_fee, self.mess_fee, self.other_charges,
        ]
        return sum(p for p in parts if p is not None)
