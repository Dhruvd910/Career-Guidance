from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.mixins import TimestampMixin


class Facility(Base, TimestampMixin):
    __tablename__ = "facilities"

    id: Mapped[int] = mapped_column(primary_key=True)
    college_id: Mapped[int] = mapped_column(ForeignKey("colleges.id"), index=True)

    facility_type: Mapped[str] = mapped_column(String(50))  # library|labs|sports|clubs|events|...
    description: Mapped[str] = mapped_column(String(1000), default="")
    verification_status: Mapped[str] = mapped_column(String(30), default="unverified_demo")

    college: Mapped["College"] = relationship()  # noqa: F821
