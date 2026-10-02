"""What the mentor has raised with a student, so it never nags (docs/design/16-phase7-plan.md, P7-3)."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class AgendaMark(Base):
    __tablename__ = "agenda_marks"
    __table_args__ = (UniqueConstraint("student_profile_id", "key", name="uq_agenda_mark"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    student_profile_id: Mapped[int] = mapped_column(ForeignKey("student_profiles.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(200))  # "thread:12", "reassess:aptitude", "dates:JEE_MAIN:2027-28"…
    first_raised_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_raised_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    times_raised: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | done | dismissed
    snoozed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
