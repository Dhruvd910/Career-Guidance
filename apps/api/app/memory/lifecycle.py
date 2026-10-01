"""When does a counselling session end? Students don't say "end session", and MAYA's page can
stay connected all day — so a session ends after SESSION_IDLE_MINUTES without a new turn (or
when explicitly ended). Then its memory is written, in the background, never in a student's way.

One mechanism covers every case: a sweeper that runs at startup and every few minutes, closing
idle conversations and writing their memory. A turn arriving on a closed conversation starts a
new one (app/conversation/session.py).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.memory.writer import write_session_memory
from app.models.chat import Conversation, Message
from app.providers.registry import get_embedding_provider, get_notes_llm_provider

logger = logging.getLogger(__name__)
settings = get_settings()

SWEEP_EVERY_SECONDS = 120
_running: set[asyncio.Task] = set()


async def close_and_remember(conversation_id: int, session_factory=SessionLocal) -> None:
    """Closes a conversation and writes its memory (if the student allowed it). Never raises:
    a failure is logged and the conversation is tried again on a later sweep."""
    db = session_factory()
    try:
        conversation = db.get(Conversation, conversation_id)
        if conversation is None:
            return
        llm = get_notes_llm_provider()
        if llm is not None:
            await write_session_memory(db, conversation_id, llm, get_embedding_provider())
        conversation = db.get(Conversation, conversation_id)
        if conversation.status != "closed":
            conversation.status, conversation.ended_at = "closed", datetime.now(timezone.utc)
            db.commit()
    except Exception:  # noqa: BLE001 — memory is never worth a crash
        logger.exception("couldn't close conversation %s; will retry", conversation_id)
        db.rollback()
    finally:
        db.close()


def remember_soon(conversation_id: int) -> None:
    """Fire and forget, keeping a reference so the task isn't garbage-collected mid-way."""
    task = asyncio.create_task(close_and_remember(conversation_id))
    _running.add(task)
    task.add_done_callback(_running.discard)


def idle_conversations(db, now: datetime | None = None) -> list[int]:
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(minutes=settings.session_idle_minutes)
    last_turn = (select(Message.conversation_id, func.max(Message.created_at).label("last"))
                 .group_by(Message.conversation_id).subquery())
    rows = db.execute(select(Conversation.id).join(last_turn, last_turn.c.conversation_id == Conversation.id)
                      .where(Conversation.status == "open", last_turn.c.last < cutoff)).scalars().all()
    return list(rows)


async def sweep_forever() -> None:
    while True:
        db = SessionLocal()
        try:
            ids = idle_conversations(db)
        except Exception:  # noqa: BLE001
            logger.exception("memory sweep failed")
            ids = []
        finally:
            db.close()
        for conversation_id in ids:
            await close_and_remember(conversation_id)
        await asyncio.sleep(SWEEP_EVERY_SECONDS)
