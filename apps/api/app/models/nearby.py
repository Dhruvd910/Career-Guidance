from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.mixins import TimestampMixin


class NearbyPlace(Base, TimestampMixin):
    """§19 surroundings. No live maps provider is wired up yet (needs its own API-key
    decision) — rows here are seeded sample data until that integration lands."""

    __tablename__ = "nearby_places"

    id: Mapped[int] = mapped_column(primary_key=True)
    college_id: Mapped[int] = mapped_column(ForeignKey("colleges.id"), index=True)

    place_type: Mapped[str] = mapped_column(String(50))  # pg|hospital|pharmacy|atm|metro|bus_stop|...
    name: Mapped[str] = mapped_column(String(255))
    distance_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    approx_monthly_rent: Mapped[float | None] = mapped_column(Float, nullable=True)

    source: Mapped[str] = mapped_column(String(255), default="demo_seed")
    last_updated: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    college: Mapped["College"] = relationship()  # noqa: F821
