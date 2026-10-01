from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ProvenanceMixin:
    """Every factual (non-user-generated) record carries these per spec §15/§23/§40/§43.

    verification_status is one of: "verified", "partially_verified", "unverified_demo".
    Seeded demo data is always "unverified_demo" so the UI can render a DEMO DATA banner
    and the AI layer can refuse to present it as fact.
    """

    source: Mapped[str] = mapped_column(String(255), default="demo_seed")
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    academic_year: Mapped[str | None] = mapped_column(String(20), nullable=True)
    last_verified: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verification_status: Mapped[str] = mapped_column(String(30), default="unverified_demo")
