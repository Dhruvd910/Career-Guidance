"""Where we left off: a returning student is met with the unfinished topic, not a blank slate."""

import asyncio
from datetime import datetime, timedelta, timezone

from app.conversation import session as conversation_session
from app.memory import consent
from app.memory.opening import counselling_state, opening_line
from app.models.chat import Conversation
from app.models.memory import CounsellingThread, SessionSummary
from app.models.student import StudentProfile
from tests.fakes import FakeLLM, FakeTTS
from tests.test_conversation_ws import connect, register
from tests.test_memory_writer import student

NOW = datetime(2026, 10, 4, 18, 0, tzinfo=timezone.utc)
GUARDIAN = {"name": "Sunita", "relationship": "mother", "contact": "x"}


def history(db, profile, ended_hours_ago=72):
    conversation = Conversation(student_profile_id=profile.id, status="closed")
    db.add(conversation)
    db.flush()
    db.add_all([
        CounsellingThread(student_profile_id=profile.id, topic_key="stream_choice", title="PCM vs PCB",
                          decision_status="leaning", current_position="Leaning PCM; father prefers PCB",
                          open_questions=["How to tell father"], actions_agreed=["Aptitude assessment"],
                          next_step="Review the assessment together", last_touched_at=NOW - timedelta(days=3)),
        SessionSummary(conversation_id=conversation.id, student_profile_id=profile.id, summary="Discussed PCM vs PCB.",
                       next_steps=["Aptitude assessment"], created_at=NOW - timedelta(hours=ended_hours_ago)),
    ])
    db.commit()
    return conversation


def test_the_counselling_state_has_the_specs_fields(db_session):
    asha = student(db_session)
    last = history(db_session, asha)
    state = counselling_state(db_session, asha)
    assert state["current_counselling_topic"] == "PCM vs PCB"
    assert state["current_problem"] == "Leaning PCM; father prefers PCB"
    assert state["decision_status"] == "leaning" and state["open_questions"] == ["How to tell father"]
    assert state["previous_actions"] == ["Aptitude assessment"] and state["next_step"] == "Review the assessment together"
    assert state["last_session"]["id"] == last.id


def test_a_returning_student_hears_where_they_left_off_in_their_language(db_session):
    asha = student(db_session)
    asha.language_stats = {"hinglish": 0.9, "en": 0.1}
    history(db_session, asha)
    llm = FakeLLM("Asha, pichli baar hum PCM vs PCB pe baat kar rahe the. Kuch badla?")
    text, language = asyncio.run(opening_line(db_session, asha, llm, now=NOW))
    assert language == "hinglish" and text.startswith("Asha, pichli baar")
    prompt = llm.seen[0]
    assert "English letters" in prompt[0]["content"], "asked for Hinglish as she usually writes it"
    assert "PCM vs PCB" in prompt[1]["content"] and "Review the assessment together" in prompt[1]["content"]


def test_no_opening_too_soon_without_an_open_topic_or_without_permission(db_session):
    soon = student(db_session, "soon")
    history(db_session, soon, ended_hours_ago=2)
    assert asyncio.run(opening_line(db_session, soon, FakeLLM("x"), now=NOW)) is None, "back after 2 hours"

    settled = student(db_session, "settled")
    history(db_session, settled)
    db_session.query(CounsellingThread).filter_by(student_profile_id=settled.id).update({"status": "resolved"})
    assert asyncio.run(opening_line(db_session, settled, FakeLLM("x"), now=NOW)) is None

    private = student(db_session, "private", memory=False)
    history(db_session, private)
    llm = FakeLLM("x")
    assert asyncio.run(opening_line(db_session, private, llm, now=NOW)) is None and llm.seen == []


def test_a_new_live_session_sends_the_opening_after_ready(client, db_session, monkeypatch):
    headers_token = register(client)
    profile = db_session.query(StudentProfile).one()
    consent.decide(db_session, profile, consent.LONG_TERM_MEMORY, True, GUARDIAN)
    history(db_session, profile, ended_hours_ago=24 * 30)
    monkeypatch.setattr(conversation_session, "get_llm_provider", lambda: FakeLLM("Welcome back! Still on PCM vs PCB?"))
    monkeypatch.setattr(conversation_session, "get_tts_provider", lambda: FakeTTS())
    with connect(client, headers_token) as ws:
        ready = ws.receive_json()
        opening = ws.receive_json()
    assert ready["type"] == "session.ready"
    assert opening == {"type": "session.opening", "session_id": ready["session_id"],
                       "text": "Welcome back! Still on PCM vs PCB?", "language": "en"}


def test_resuming_the_same_open_session_doesnt_repeat_it(client, db_session, monkeypatch):
    token = register(client)
    profile = db_session.query(StudentProfile).one()
    consent.decide(db_session, profile, consent.LONG_TERM_MEMORY, True, GUARDIAN)
    history(db_session, profile, ended_hours_ago=24 * 30)
    llm = FakeLLM("Welcome back!", "Welcome back again!")
    monkeypatch.setattr(conversation_session, "get_llm_provider", lambda: llm)
    with connect(client, token) as ws:
        session_id = ws.receive_json()["session_id"]
        ws.receive_json()
    with connect(client, token, session_id=session_id) as ws:
        assert ws.receive_json()["session_id"] == session_id
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}, "no second opening on a reconnect"
