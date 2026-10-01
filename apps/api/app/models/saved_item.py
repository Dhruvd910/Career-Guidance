from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.mixins import TimestampMixin


class SavedItem(Base, TimestampMixin):
    """§38 "My Shortlist" — students bucket colleges/branches/careers/courses into
    dream/target/safe."""

    __tablename__ = "saved_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_profile_id: Mapped[int] = mapped_column(ForeignKey("student_profiles.id"))

    item_type: Mapped[str] = mapped_column(String(20))  # college | branch | career | course
    item_id: Mapped[int] = mapped_column(Integer)
    bucket: Mapped[str | None] = mapped_column(String(20), nullable=True)  # dream | target | safe
    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)
