"""When a session ends, its memory is written — and a closed session doesn't swallow new turns."""

import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.conversation import session as conversation_session
from app.memory import lifecycle
from app.models.chat import Conversation, Message
from app.models.memory import SessionSummary
from tests.fakes import FakeEmbedding, FakeLLM, FakeTTS
from tests.test_conversation_ws import connect, register, until
from tests.test_memory_writer import TRANSCRIPT, notes, session, student

NOW = datetime(2026, 10, 1, 18, 0, tzinfo=timezone.utc)


def at(db, conversation, minutes_ago):
    for message in conversation.messages:
        message.created_at = NOW - timedelta(minutes=minutes_ago)
    db.commit()


def test_only_conversations_quiet_for_the_idle_time_are_over(db_session, monkeypatch):
    monkeypatch.setattr(lifecycle.settings, "session_idle_minutes", 10)
    asha = student(db_session)
    quiet, _ = session(db_session, asha, *TRANSCRIPT)
    active, _ = session(db_session, asha, *TRANSCRIPT)
    closed, _ = session(db_session, asha, *TRANSCRIPT)
    at(db_session, quiet, 30)
    at(db_session, active, 2)
    at(db_session, closed, 30)
    closed.status = "closed"
    db_session.commit()
    assert lifecycle.idle_conversations(db_session, now=NOW) == [quiet.id]


def test_closing_a_session_writes_its_memory(db_session, monkeypatch):
    asha = student(db_session)
    conversation, ids = session(db_session, asha, *TRANSCRIPT)
    monkeypatch.setattr(lifecycle, "get_notes_llm_provider", lambda: FakeLLM(notes(ids)))
    monkeypatch.setattr(lifecycle, "get_embedding_provider", lambda: FakeEmbedding())
    factory = lambda: Session(bind=db_session.get_bind())  # noqa: E731
    asyncio.run(lifecycle.close_and_remember(conversation.id, session_factory=factory))
    db_session.expire_all()
    assert db_session.get(Conversation, conversation.id).status == "closed"
    assert db_session.get(SessionSummary, conversation.id) is not None


def test_closing_without_memory_permission_still_closes(db_session, monkeypatch):
    ravi = student(db_session, "ravi", memory=False)
    conversation, _ = session(db_session, ravi, *TRANSCRIPT)
    monkeypatch.setattr(lifecycle, "get_notes_llm_provider", lambda: FakeLLM())
    factory = lambda: Session(bind=db_session.get_bind())  # noqa: E731
    asyncio.run(lifecycle.close_and_remember(conversation.id, session_factory=factory))
    db_session.expire_all()
    assert db_session.get(Conversation, conversation.id).status == "closed"
    assert db_session.get(SessionSummary, conversation.id) is None


def test_a_turn_after_the_session_closed_starts_a_new_session(client, db_session, monkeypatch):
    monkeypatch.setattr(conversation_session, "get_llm_provider", lambda: FakeLLM("Hello again.", "Welcome back."))
    monkeypatch.setattr(conversation_session, "get_tts_provider", lambda: FakeTTS())
    with connect(client, register(client)) as ws:
        first = ws.receive_json()["session_id"]
        ws.send_json({"type": "turn.text", "turn_id": "t1", "text": "Hi"})
        until(ws, "reply.done")
        db_session.get(Conversation, first).status = "closed"  # the sweeper closed it while the page sat open
        db_session.commit()
        ws.send_json({"type": "turn.text", "turn_id": "t2", "text": "I'm back"})
        renewed = ws.receive_json()
        assert renewed["type"] == "session.ready" and renewed["session_id"] != first
        until(ws, "reply.done")
    assert db_session.query(Message).filter_by(conversation_id=renewed["session_id"], role="user").one().content == "I'm back"
