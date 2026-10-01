"""The live conversation WebSocket, end to end with fake AI services."""

import asyncio
import threading

import pytest
from starlette.websockets import WebSocketDisconnect

from app.ai import orchestrator
from app.conversation import session as conversation_session
from app.models.chat import Message
from app.providers.http import ProviderError
from app.providers.llm import Done, TextDelta
from tests.fakes import FakeLLM, FakeSTT, FakeTTS

REPLY = "Engineering is one good path. Medicine is another. What do you enjoy most?"


def register(client, email="ws@example.com"):
    return client.post("/api/auth/register", json={
        "email": email, "password": "password123", "name": "Asha", "class_level": 10,
    }).json()["access_token"]


@pytest.fixture()
def services(monkeypatch):
    """Fake STT/LLM/TTS behind the session; tests swap in their own where needed."""
    fakes = {"stt": FakeSTT("Should I take PCM or PCB?", "en", confidence=0.9, no_speech_prob=0.01),
             "llm": FakeLLM(REPLY), "tts": FakeTTS()}
    monkeypatch.setattr(conversation_session, "get_stt_provider", lambda: fakes["stt"])
    monkeypatch.setattr(conversation_session, "get_llm_provider", lambda: fakes["llm"])
    monkeypatch.setattr(conversation_session, "get_tts_provider", lambda: fakes["tts"])
    return fakes


def connect(client, token, session_id=None):
    query = f"?session_id={session_id}" if session_id else ""
    ws = client.websocket_connect(f"/api/ws/conversation{query}", headers={"Authorization": f"Bearer {token}"})
    return ws


def receive(ws):
    """One message: a JSON dict, with the binary frame that follows a reply.audio attached."""
    message = ws.receive_json()
    if message["type"] == "reply.audio":
        message["pcm"] = ws.receive_bytes()
    return message


def until(ws, kind):
    """Every message up to and including the first of type `kind`."""
    seen = []
    while True:
        message = receive(ws)
        seen.append(message)
        if message["type"] == kind:
            return seen


def types(messages):
    return [m["type"] for m in messages]


# ---------------- connecting ----------------

def test_no_token_no_conversation(client):
    with pytest.raises(WebSocketDisconnect) as closed:
        with client.websocket_connect("/api/ws/conversation"):
            pass
    assert closed.value.code == 4401


def test_a_session_starts_ready(client, services):
    with connect(client, register(client)) as ws:
        ready = ws.receive_json()
    assert ready["type"] == "session.ready" and ready["session_id"] > 0


def test_another_students_session_is_not_resumed(client, services):
    with connect(client, register(client, "a@example.com")) as ws:
        theirs = ws.receive_json()["session_id"]
    with connect(client, register(client, "b@example.com"), session_id=theirs) as ws:
        mine = ws.receive_json()["session_id"]
    assert mine != theirs


# ---------------- a whole turn ----------------

def test_a_typed_turn_streams_sentences_and_their_audio_in_order(client, services, db_session):
    with connect(client, register(client)) as ws:
        ws.receive_json()
        ws.send_json({"type": "turn.text", "turn_id": "t1", "text": "Should I take PCM or PCB?"})
        messages = until(ws, "reply.done")

    assert types(messages)[:2] == ["turn.transcript", "turn.thinking"]
    deltas = [m for m in messages if m["type"] == "reply.delta"]
    assert [d["text"] for d in deltas] == ["Engineering is one good path.", "Medicine is another.",
                                           "What do you enjoy most?"]
    audio = [m for m in messages if m["type"] == "reply.audio"]
    assert [m["seq"] for m in audio] == sorted(m["seq"] for m in audio)
    for d in deltas:  # every sentence's text arrives before any of its audio
        first_audio = next(i for i, m in enumerate(messages) if m["type"] == "reply.audio" and m["seq"] == d["seq"])
        assert messages.index(d) < first_audio
    assert all(m["encoding"] == "pcm_s16le" and m["sample_rate"] == 16000 and m["pcm"] for m in audio)
    assert services["tts"].spoken == [d["text"] for d in deltas]

    done = messages[-1]
    assert done["text"] == REPLY and done["language"] == "en"
    user, reply = db_session.query(Message).order_by(Message.id).all()
    assert (user.role, user.content, user.turn_id, user.modality) == ("user", "Should I take PCM or PCB?", "t1", "text")
    assert (reply.role, reply.content, reply.interrupted) == ("assistant", REPLY, False)
    assert {"first_token", "first_audio", "total"} <= set(reply.latency)


def test_a_spoken_turn_is_transcribed_first(client, services, db_session):
    with connect(client, register(client)) as ws:
        ws.receive_json()
        ws.send_json({"type": "turn.audio", "turn_id": "v1", "encoding": "wav"})
        ws.send_bytes(b"RIFF....WAVE")
        messages = until(ws, "reply.done")
    transcript = messages[0]
    assert transcript == {"type": "turn.transcript", "turn_id": "v1", "text": "Should I take PCM or PCB?",
                          "language": "en", "script": "latn", "confidence": 0.9}
    user = db_session.query(Message).filter_by(role="user").one()
    assert user.modality == "voice" and user.stt_confidence == 0.9
    assert "stt" in db_session.query(Message).filter_by(role="assistant").one().latency


def test_silence_that_whisper_heard_as_thank_you_is_dropped(client, services, db_session):
    services["stt"] = FakeSTT("Thank you.", "en", no_speech_prob=0.6)
    with connect(client, register(client)) as ws:
        ws.receive_json()
        ws.send_json({"type": "turn.audio", "turn_id": "v1", "encoding": "wav"})
        ws.send_bytes(b"RIFF")
        assert ws.receive_json() == {"type": "turn.no_speech", "turn_id": "v1"}
    assert services["llm"].seen == [] and db_session.query(Message).count() == 0


def test_hinglish_is_spoken_with_the_hindi_voice(client, services):
    services["llm"] = FakeLLM("Koi baat nahi, chalo dekhte hain.")
    with connect(client, register(client)) as ws:
        ws.receive_json()
        ws.send_json({"type": "turn.text", "turn_id": "h1", "text": "Mujhe samajh nahi aa raha kya karun"})
        done = until(ws, "reply.done")[-1]
    assert done["language"] == "hinglish"
    assert services["tts"].languages == ["hi"]


def test_a_tool_lookup_is_announced_then_answered(client, services):
    services["llm"] = FakeLLM([("get_student_profile", "{}")], "You're in class 10, Asha.")
    with connect(client, register(client)) as ws:
        ws.receive_json()
        ws.send_json({"type": "turn.text", "turn_id": "t1", "text": "What class am I in?"})
        messages = until(ws, "reply.done")
    assert {"type": "turn.thinking", "turn_id": "t1", "activity": "get_student_profile"} in messages
    assert messages[-1]["tool_calls_used"] == ["get_student_profile"]
    tool_result = services["llm"].seen[1][-1]
    assert tool_result["role"] == "tool" and "Asha" in tool_result["content"]


# ---------------- interrupting ----------------

class GatedTTS(FakeTTS):
    """Sends the first chunk of any sentence containing "WAIT", then holds the rest until the
    test opens the gate (or the turn is cancelled)."""

    def __init__(self):
        super().__init__()
        self.gate = threading.Event()

    async def stream(self, text, language=None):
        pcm = b"".join([chunk async for chunk in super().stream(text, language)])
        yield pcm
        if "WAIT" in text:
            while not self.gate.is_set():
                await asyncio.sleep(0.005)


def test_an_interruption_keeps_only_what_was_heard(client, services, db_session):
    services["tts"] = GatedTTS()
    services["llm"] = FakeLLM("One two three four five six seven eight WAIT. Never heard at all.")
    with connect(client, register(client)) as ws:
        ws.receive_json()
        ws.send_json({"type": "turn.text", "turn_id": "t1", "text": "Tell me about IIT"})
        first_audio = until(ws, "reply.audio")[-1]
        sentence_ms = len(first_audio["pcm"]) / 2 / 16000 * 1000
        ws.send_json({"type": "turn.interrupt", "turn_id": "t1", "seq": 0, "played_ms": sentence_ms / 2})
        rest = until(ws, "turn.cancelled")
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}, "nothing more arrives for the cancelled turn"
    assert "reply.done" not in types(rest)
    reply = db_session.query(Message).filter_by(role="assistant").one()
    assert reply.interrupted is True
    assert reply.content == "One two three four", "half of the first sentence's nine words"
    assert reply.generated_content.startswith("One two three")


def test_interrupting_after_the_reply_was_sent_still_counts(client, services, db_session):
    services["llm"] = FakeLLM(REPLY, "Sure.")
    with connect(client, register(client)) as ws:
        ws.receive_json()
        ws.send_json({"type": "turn.text", "turn_id": "t1", "text": "Options?"})
        until(ws, "reply.done")
        # Still playing on the device when the student cuts in, at the start of sentence 1.
        ws.send_json({"type": "turn.interrupt", "turn_id": "t1", "seq": 1, "played_ms": 0})
        assert ws.receive_json() == {"type": "turn.cancelled", "turn_id": "t1"}
        ws.send_json({"type": "turn.text", "turn_id": "t2", "text": "Wait, tell me about engineering"})
        until(ws, "reply.done")
    first = db_session.query(Message).filter_by(role="assistant", turn_id="t1").one()
    assert first.content == "Engineering is one good path." and first.interrupted
    history = services["llm"].seen[1]
    assert history[-3] == {"role": "assistant", "content": "Engineering is one good path." + orchestrator.INTERRUPTED_NOTE}


def test_a_new_turn_cuts_off_the_running_one(client, services, db_session):
    services["tts"] = GatedTTS()
    services["llm"] = FakeLLM("First sentence here. Second one WAIT. Third.", "Okay.")
    with connect(client, register(client)) as ws:
        ws.receive_json()
        ws.send_json({"type": "turn.text", "turn_id": "t1", "text": "Hi"})
        until(ws, "reply.audio")
        until(ws, "reply.audio")  # sentence 1's audio is out; its rest is held
        ws.send_json({"type": "playback.ack", "turn_id": "t1", "seq": 0})
        ws.send_json({"type": "turn.text", "turn_id": "t2", "text": "Actually, never mind"})
        assert until(ws, "reply.done")[-1]["turn_id"] == "t2"
    first = db_session.query(Message).filter_by(role="assistant", turn_id="t1").one()
    assert first.interrupted and first.content == "First sentence here."


# ---------------- when services fail ----------------

def test_without_a_voice_the_turn_goes_on_as_text(client, services, db_session):
    services["tts"] = FakeTTS(fail=ProviderError("cartesia", "HTTP 402: no credits", 402))
    with connect(client, register(client)) as ws:
        ws.receive_json()
        ws.send_json({"type": "turn.text", "turn_id": "t1", "text": "Options?"})
        messages = until(ws, "reply.done")
    errors = [m for m in messages if m["type"] == "error"]
    assert [e["code"] for e in errors] == ["tts_unavailable"], "said once, not per sentence"
    assert len([m for m in messages if m["type"] == "reply.delta"]) == 3
    assert "reply.audio" not in types(messages)
    assert db_session.query(Message).filter_by(role="assistant").one().content == REPLY


class BrokenLLM(FakeLLM):
    async def stream(self, messages, tools=None):
        yield TextDelta("Let me")
        raise ProviderError("openrouter", "stream broke off")
        yield Done()  # pragma: no cover


def test_the_model_failing_ends_the_turn_with_an_error(client, services, db_session):
    services["llm"] = BrokenLLM()
    with connect(client, register(client)) as ws:
        ws.receive_json()
        ws.send_json({"type": "turn.text", "turn_id": "t1", "text": "Options?"})
        error = until(ws, "error")[-1]
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}, "the connection survives"
    assert error["code"] == "llm_unavailable" and error["retryable"]
    assert db_session.query(Message).filter_by(role="user").count() == 1


# ---------------- bad input ----------------

def test_bad_messages_are_refused_without_dropping_the_connection(client, services):
    with connect(client, register(client)) as ws:
        ws.receive_json()
        ws.send_text("not json")
        assert ws.receive_json()["code"] == "bad_message"
        ws.send_bytes(b"audio with no header")
        assert ws.receive_json()["code"] == "bad_message"
        ws.send_json({"type": "turn.interrupt", "turn_id": "x", "seq": "not a number"})
        assert ws.receive_json()["code"] == "bad_message"
        ws.send_json({"type": "dance"})
        assert ws.receive_json()["code"] == "bad_message"
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}


# ---------------- REST sessions ----------------

def test_sessions_start_take_messages_and_end(client, services, monkeypatch):
    monkeypatch.setattr(orchestrator, "get_llm_provider", lambda: FakeLLM("Hello Asha."))
    headers = {"Authorization": f"Bearer {register(client)}"}
    session_id = client.post("/api/conversation/start", json={"channel": "text"}, headers=headers).json()["session_id"]
    r = client.post("/api/conversation/message", json={"session_id": session_id, "text": "Hi"}, headers=headers)
    assert r.json()["reply"] == "Hello Asha." and r.json()["conversation_id"] == session_id
    r = client.post("/api/conversation/end", json={"session_id": session_id}, headers=headers)
    assert r.json() == {"session_id": session_id, "status": "closed"}

    other = {"Authorization": f"Bearer {register(client, 'other@example.com')}"}
    assert client.post("/api/conversation/message", json={"session_id": session_id, "text": "Hi"},
                       headers=other).status_code == 404
    assert client.post("/api/conversation/end", json={"session_id": session_id}, headers=other).status_code == 404
