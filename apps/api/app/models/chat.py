from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.mixins import TimestampMixin


class Conversation(Base, TimestampMixin):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_profile_id: Mapped[int] = mapped_column(ForeignKey("student_profiles.id"))
    title: Mapped[str] = mapped_column(String(255), default="New conversation")

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", order_by="Message.id"
    )


class Message(Base, TimestampMixin):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"))

    role: Mapped[str] = mapped_column(String(20))  # user | assistant | tool
    content: Mapped[str] = mapped_column(String(8000), default="")
    tool_calls: Mapped[list] = mapped_column(JSON, default=list)
    audio_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")
