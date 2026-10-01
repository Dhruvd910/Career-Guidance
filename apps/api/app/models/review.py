from sqlalchemy import JSON, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.mixins import TimestampMixin


class CollegeReview(Base, TimestampMixin):
    """Community-contributed content (§16/§17) — always user-generated, never presented
    as an official/verified fact. Feeds the college card's "student rating" (§36)."""

    __tablename__ = "college_reviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    college_id: Mapped[int] = mapped_column(ForeignKey("colleges.id"), index=True)
    student_profile_id: Mapped[int] = mapped_column(ForeignKey("student_profiles.id"))

    rating: Mapped[int] = mapped_column(Integer)  # 1-5
    text: Mapped[str] = mapped_column(String(2000), default="")
    tags: Mapped[list] = mapped_column(JSON, default=list)  # ["good mess", "strict hostel rules"]

    college: Mapped["College"] = relationship()  # noqa: F821
