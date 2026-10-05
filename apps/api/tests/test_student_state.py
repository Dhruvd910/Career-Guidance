"""How the student seems (uncertain signals, by permission) — and safety, which is always on."""

import asyncio
import json
import time

import pytest
from sqlalchemy.orm import sessionmaker

from app.ai import orchestrator, safety
from app.conversation import session as conversation_session
from app.memory import consent
from app.memory.state import analyze_message, tone_note
from app.models.chat import Message
from app.models.memory import TurnAnalysis
from app.models.student import StudentProfile
from tests.fakes import FakeLLM, FakeTTS
from tests.test_conversation_ws import connect, register, until
from tests.test_memory_writer import session, student

GUARDIAN = {"name": "Sunita", "relationship": "mother", "contact": "x"}


# ---------------- safety ----------------

@pytest.mark.parametrize("text, kind", [
    ("Sometimes I feel like I want to die", "self_harm"),
    ("I don't want to live anymore, nothing is working", "self_harm"),
    ("I've been thinking about suicide", "self_harm"),
    ("main sach mein mar jaana chahta hoon", "self_harm"),
    ("Kabhi kabhi lagta hai zindagi khatam kar doon", "self_harm"),
    ("मैं आत्महत्या के बारे में सोचता हूँ", "self_harm"),
    ("मैं जीना नहीं चाहती", "self_harm"),
    ("My uncle hits me when I get bad marks", "abuse"),
    ("Papa mujhe maarte hain jab marks kam aate hain", "abuse"),
    ("मुझे पीटते हैं घर पर", "abuse"),
])
def test_unsafe_messages_are_noticed_in_every_language(text, kind):
    assert safety.concern(text) == kind


@pytest.mark.parametrize("text", [
    "I want to improve my coding skills",
    "I studied for six hours today",
    "I'm a die-hard cricket fan",
    "I'm dying to know my JEE result",
    "This killer question set took me ages",
    "Mera next step kya hai?",
    "मुझे डॉक्टर बनना है",
])
def test_ordinary_messages_are_left_alone(text):
    assert safety.concern(text) is None


def test_an_unsafe_message_changes_this_very_reply(client, monkeypatch):
    token = client.post("/api/auth/register", json={"email": "s@example.com", "password": "password123",
                                                    "name": "Asha", "class_level": 10}).json()["access_token"]
    llm = FakeLLM("I'm really glad you told me.")
    monkeypatch.setattr(orchestrator, "get_llm_provider", lambda: llm)
    client.post("/api/ai/chat", json={"message": "honestly I want to die, JEE is impossible"},
                headers={"Authorization": f"Bearer {token}"})
    system = [m["content"] for m in llm.seen[0] if m["role"] == "system"]
    assert system[-1] == safety.INSTRUCTION["self_harm"] and "14416" in system[-1]
    assert "Tele-MANAS 14416" in system[0], "and the standing rule is always there"


# ---------------- how the student seems ----------------

READING = json.dumps({"intent": "career_decision", "topic": "JEE vs friends",
                      "emotion_signals": [{"signal": "social_comparison", "confidence": 0.8},
                                          {"signal": "frustration", "confidence": 0.6},
                                          {"signal": "depression", "confidence": 0.9},  # not in the vocabulary
                                          {"signal": "worry", "confidence": 0.3}],
                      "underlying_concerns": [{"concern": "fear of falling behind friends", "confidence": 0.7}]})


def factory(db):
    return sessionmaker(bind=db.get_bind())


def test_a_reading_is_stored_with_permission_and_only_known_signals(db_session):
    asha = student(db_session, signals=True)
    _, ids = session(db_session, asha, ("user", "Mujhse JEE nahi ho raha, sab friends ka ho raha hai"))
    asyncio.run(analyze_message(ids[0], FakeLLM(READING), session_factory=factory(db_session)))
    db_session.expire_all()
    analysis = db_session.get(TurnAnalysis, ids[0])
    assert analysis.intent == "career_decision"
    assert [s["signal"] for s in analysis.emotion_signals] == ["social_comparison", "frustration", "worry"], \
        "no clinical words, whatever the model says"


def test_without_permission_nothing_is_read(db_session):
    asha = student(db_session, signals=False)
    _, ids = session(db_session, asha, ("user", "I feel stuck"))
    llm = FakeLLM(READING)
    assert asyncio.run(analyze_message(ids[0], llm, session_factory=factory(db_session))) is None
    assert llm.seen == [] and db_session.query(TurnAnalysis).count() == 0


def test_the_next_reply_hears_how_they_seemed_but_only_the_confident_part(db_session):
    asha = student(db_session, signals=True)
    conversation, ids = session(db_session, asha, ("user", "Mujhse JEE nahi ho raha"))
    asyncio.run(analyze_message(ids[0], FakeLLM(READING), session_factory=factory(db_session)))
    note = tone_note(db_session, conversation.id)
    assert "social comparison (0.8)" in note and "frustration (0.6)" in note
    assert "worry" not in note, "0.3 is too weak to act on"
    assert "fear of falling behind friends" in note and "never diagnose" in note


def test_weak_readings_make_no_note(db_session):
    asha = student(db_session, signals=True)
    conversation, ids = session(db_session, asha, ("user", "ok"))
    db_session.add(TurnAnalysis(message_id=ids[0], student_profile_id=asha.id,
                                emotion_signals=[{"signal": "confusion", "confidence": 0.2}]))
    db_session.commit()
    assert tone_note(db_session, conversation.id) is None


def test_a_live_turn_is_read_in_the_background_on_the_same_database(client, db_session, monkeypatch):
    token = register(client)
    profile = db_session.query(StudentProfile).one()
    consent.decide(db_session, profile, consent.EMOTION_SIGNALS, True, GUARDIAN)
    class ReplyAndReading(FakeLLM):
        """Streams the reply; answers the (background) reading separately, whichever comes first."""

        async def chat(self, messages, tools=None, json_mode=False):
            return {"role": "assistant", "content": READING}

    model = ReplyAndReading("Koi baat nahi, chalo dekhte hain.")
    monkeypatch.setattr(conversation_session, "get_llm_provider", lambda: model)
    monkeypatch.setattr(conversation_session, "get_notes_llm_provider", lambda: model)  # the reading: background model
    monkeypatch.setattr(conversation_session, "get_tts_provider", lambda: FakeTTS())
    with connect(client, token) as ws:
        ws.receive_json()
        ws.send_json({"type": "turn.text", "turn_id": "t1", "text": "Mujhse JEE nahi ho raha"})
        until(ws, "reply.done")
        for _ in range(50):
            db_session.expire_all()
            if db_session.query(TurnAnalysis).count():
                break
            time.sleep(0.02)
    said = db_session.query(Message).filter_by(role="user").one()
    assert db_session.get(TurnAnalysis, said.id).topic == "JEE vs friends"
