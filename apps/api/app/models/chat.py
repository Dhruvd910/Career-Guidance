from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.core.types import EncryptedText, Json
from app.models.mixins import TimestampMixin


class Conversation(Base, TimestampMixin):
    """One counselling session (spec §22): from start (created_at) to end."""

    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_profile_id: Mapped[int] = mapped_column(ForeignKey("student_profiles.id"))
    title: Mapped[str] = mapped_column(String(255), default="New conversation")
    channel: Mapped[str | None] = mapped_column(String(10), nullable=True)  # voice | text
    status: Mapped[str] = mapped_column(String(20), default="open", server_default="open")  # open | closed
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", order_by="Message.id"
    )


class Message(Base, TimestampMixin):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"))

    role: Mapped[str] = mapped_column(String(20))  # user | assistant | tool
    # For MAYA's turns: what the student actually heard (or saw) — after an interruption, only
    # the part played before it. generated_content keeps everything the model wrote.
    content: Mapped[str] = mapped_column(EncryptedText, default="")
    tool_calls: Mapped[list] = mapped_column(Json, default=list)
    audio_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    turn_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    language: Mapped[str | None] = mapped_column(String(10), nullable=True)  # en | hi | hinglish
    modality: Mapped[str | None] = mapped_column(String(10), nullable=True)  # voice | text
    interrupted: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    generated_content: Mapped[str | None] = mapped_column(EncryptedText, nullable=True)
    stt_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Where the time went, in ms: {"stt": …, "first_token": …, "first_audio": …, "total": …}
    latency: Mapped[dict | None] = mapped_column(Json, nullable=True)

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")
