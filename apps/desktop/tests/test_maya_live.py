"""MAYA's page on the live conversation: streamed replies, interruptions, and the fallback."""

import json
import time

import pytest
from PySide6.QtCore import QObject, Signal

from app import audio_io
from app.pages import maya as maya_page
from app.voice import IDLE, SPEAKING, THINKING, Voice
from tests.test_stream_player import FakeOutput

RATE = 1000


class FakeSocket(QObject):
    """Stands in for QWebSocket: records what MAYA sends; the test plays the server."""

    textMessageReceived = Signal(str)
    binaryMessageReceived = Signal(bytes)
    disconnected = Signal()

    def __init__(self):
        super().__init__()
        self.sent: list = []
        self.opened = 0

    def open(self, request):
        self.opened += 1

    def close(self):
        pass

    def sendTextMessage(self, text):
        self.sent.append(json.loads(text))

    def sendBinaryMessage(self, data):
        self.sent.append(bytes(data))

    # the server's side
    def server(self, message: dict, payload: bytes | None = None):
        self.textMessageReceived.emit(json.dumps(message))
        if payload is not None:
            self.binaryMessageReceived.emit(payload)


class FakeKeyboard(QObject):
    visibility_changed = Signal(bool)

    def isVisible(self):
        return False

    def hide_keyboard(self):
        pass


INSTRUMENTS = [{"key": "interests", "title": {"en": "What you enjoy", "hi": "आपको क्या पसंद है"}, "est_minutes": 6,
                "last_completed": {"attempt_id": 1, "completed_at": "2026-10-01T10:00:00+00:00"}}]


class FakeWindow:
    def __init__(self):
        self.voice = Voice()
        self.keyboard = FakeKeyboard()

    def navigate(self, name, **kwargs):
        pass


@pytest.fixture()
def page(qapp, monkeypatch):
    socket = FakeSocket()
    real_client = maya_page.ConversationClient
    monkeypatch.setattr(maya_page, "ConversationClient", lambda token: real_client(lambda: "tok", socket=socket))
    monkeypatch.setattr(audio_io.sd, "OutputStream", FakeOutput)
    monkeypatch.setattr(audio_io.StreamPlayer, "LEAD_IN_SECONDS", 0.0)
    monkeypatch.setattr(maya_page.api_client, "get_consent",
                        lambda: {"long_term_memory": {"granted": False, "decided_at": None}})
    monkeypatch.setattr(maya_page.api_client, "assessment_instruments", lambda: INSTRUMENTS)
    p = maya_page.MayaPage(FakeWindow())
    p.isVisible = lambda: True
    p.socket = socket
    p.listens = []
    monkeypatch.setattr(p.voice.recorder, "listen", lambda **kw: p.listens.append(kw))
    p.on_show()
    socket.server({"type": "session.ready", "session_id": 7, "opening": None})
    return p


def sent(page, kind):
    return [m for m in page.socket.sent if isinstance(m, dict) and m["type"] == kind]


def bubbles(page):
    layout = page.messages_layout
    texts = []
    for i in range(layout.count()):
        row = layout.itemAt(i).widget()
        texts += [w.text() for w in row.findChildren(maya_page.ChatBubble)]
    return texts[1:]  # after the welcome


def pcm(ms):
    return b"\x01\x00" * (ms * RATE // 1000)


def answer(page, turn, *sentences, language="en", audio_ms=100):
    s = page.socket
    for seq, text in enumerate(sentences):
        s.server({"type": "reply.delta", "turn_id": turn, "seq": seq, "text": text})
        s.server({"type": "reply.audio", "turn_id": turn, "seq": seq, "sample_rate": RATE, "encoding": "pcm_s16le"},
                 pcm(audio_ms))
    s.server({"type": "reply.done", "turn_id": turn, "text": " ".join(sentences), "language": language,
              "tool_calls_used": []})


def type_question(page, text):
    page.text_input.setText(text)
    page._send_text()
    return sent(page, "turn.text")[-1]["turn_id"]


def test_a_typed_question_is_answered_and_spoken_as_it_streams(qapp, page):
    turn = type_question(page, "Should I take PCM?")
    assert page.voice.state == THINKING
    page.socket.server({"type": "turn.transcript", "turn_id": turn, "text": "Should I take PCM?", "language": "en"})
    answer(page, turn, "It depends on what you enjoy.", "Do you like maths?")
    assert page.voice.state == SPEAKING
    assert bubbles(page) == ["Should I take PCM?", "It depends on what you enjoy. Do you like maths?"]

    FakeOutput.last.play(5)  # both sentences out
    qapp.processEvents()
    assert [m["seq"] for m in sent(page, "playback.ack")] == [0, 1]
    assert page.voice.state == IDLE
    assert page.listens == [], "a typed question doesn't open the mic afterwards"
    assert sent(page, "turn.interrupt") == []


def test_a_spoken_question_answered_with_a_question_listens_for_the_answer(qapp, page):
    page._send_voice(b"RIFF....WAVE")
    header, wav = page.socket.sent[-2], page.socket.sent[-1]
    assert header["type"] == "turn.audio" and wav == b"RIFF....WAVE"
    turn = header["turn_id"]
    page.socket.server({"type": "turn.transcript", "turn_id": turn, "text": "Mujhe kya karna chahiye?",
                        "language": "hinglish"})
    answer(page, turn, "Tumhe kaunsa subject pasand hai?", language="hinglish")
    FakeOutput.last.play(3)
    qapp.processEvents()
    time.sleep(0.3)  # the pause before listening, so she doesn't hear her own last word
    qapp.processEvents()
    assert bubbles(page) == ["Mujhe kya karna chahiye?", "Tumhe kaunsa subject pasand hai?"]
    assert page.language == "hinglish"
    assert len(page.listens) == 1, "she asked, so she listens"


def test_stop_maya_mid_sentence_tells_the_server_what_was_heard(qapp, page):
    turn = type_question(page, "Tell me about IIT")
    answer(page, turn, "IITs are hard to get into.", "But worth it.", audio_ms=200)
    FakeOutput.last.play(6)  # 300 ms: all of sentence 0, 100 ms into sentence 1
    page.voice.interrupt()  # what "Stop Maya" does
    interrupt = sent(page, "turn.interrupt")[-1]
    assert interrupt == {"type": "turn.interrupt", "turn_id": turn, "seq": 1, "played_ms": pytest.approx(100.0)}
    assert page.voice.state == IDLE


def test_a_new_question_cuts_off_the_old_answer_first(qapp, page):
    first = type_question(page, "Options?")
    answer(page, first, "Engineering is one.", audio_ms=500)
    FakeOutput.last.play(1)
    second = type_question(page, "Actually, what about law?")
    kinds = [(m["type"], m["turn_id"]) for m in page.socket.sent if isinstance(m, dict) and m["type"] != "playback.ack"]
    assert kinds[-2:] == [("turn.interrupt", first), ("turn.text", second)], "interrupt first, then the new turn"


def test_messages_for_an_old_turn_are_ignored(qapp, page):
    first = type_question(page, "Options?")
    second = type_question(page, "Never mind, colleges?")
    answer(page, first, "Late answer to the first question.")
    assert bubbles(page) == ["Options?", "Never mind, colleges?"]
    answer(page, second, "Here are some colleges.")
    assert bubbles(page)[-1] == "Here are some colleges."


def test_without_a_voice_the_answer_still_shows(qapp, page):
    turn = type_question(page, "Options?")
    page.socket.server({"type": "error", "turn_id": turn, "code": "tts_unavailable",
                        "message": "My voice isn't working right now, so I'll answer on screen.", "retryable": True})
    page.socket.server({"type": "reply.delta", "turn_id": turn, "seq": 0, "text": "Engineering is one."})
    page.socket.server({"type": "reply.done", "turn_id": turn, "text": "Engineering is one.", "language": "en"})
    assert bubbles(page)[-1] == "Engineering is one."
    assert "voice isn't working" in page.not_configured_label.text()
    assert page.voice.state == IDLE


def test_a_failed_turn_says_so(qapp, page):
    turn = type_question(page, "Options?")
    page.socket.server({"type": "error", "turn_id": turn, "code": "llm_unavailable",
                        "message": "I'm having trouble reaching one of my services right now.", "retryable": True})
    assert bubbles(page)[-1].startswith("⚠ I'm having trouble")
    assert page.voice.state == IDLE


def test_before_the_live_line_is_up_questions_go_the_older_way(qapp, page, monkeypatch):
    page.socket.disconnected.emit()
    calls = []
    monkeypatch.setattr(maya_page, "run_async", lambda fn, *args, **kw: calls.append((fn.__name__, args)))
    page.text_input.setText("Hello?")
    page._send_text()
    assert calls and calls[0][0] == "chat" and calls[0][1][0] == "Hello?"
    assert sent(page, "turn.text") == []


def test_a_returning_student_hears_where_they_left_off(qapp, page, monkeypatch):
    said = []
    monkeypatch.setattr(page.voice, "say", lambda text, on_done=None, language=None: said.append((text, language)))
    page.socket.server({"type": "session.opening", "session_id": 7, "language": "hinglish",
                        "text": "Pichli baar hum PCM vs PCB pe the. Kuch badla?"})
    assert said == [("Pichli baar hum PCM vs PCB pe the. Kuch badla?", "hinglish")]
    assert bubbles(page)[-1] == "Pichli baar hum PCM vs PCB pe the. Kuch badla?"
    assert page.language == "hinglish"


def test_an_opening_that_arrives_while_she_is_busy_waits_for_her_next_wake(qapp, page, monkeypatch):
    said = []
    monkeypatch.setattr(page.voice, "say", lambda text, on_done=None, language=None: said.append(text))
    turn = type_question(page, "Options?")  # she's busy with this
    page.socket.server({"type": "session.opening", "session_id": 7, "language": "en", "text": "Welcome back!"})
    assert said == []
    answer(page, turn, "Engineering.")
    page.wake(greet=True)
    assert said == ["Welcome back!"], 'instead of "Yes? How can I help?"'
    page.wake(greet=True)
    assert said[-1] == "Yes? How can I help?", "only once"


def test_maya_offering_an_assessment_shows_a_start_button(qapp, page):
    went = []
    page.ctx.navigate = lambda name, **kw: went.append((name, kw))
    turn = type_question(page, "Mujhe nahi pata main kis cheez mein accha hoon")
    page.socket.server({"type": "ui.suggest", "turn_id": turn, "action": "open_assessment", "instrument_key": "aptitude",
                        "title": {"en": "Thinking skills", "hi": "सोचने की क्षमता"}, "est_minutes": 10, "reason": ""})
    answer(page, turn, "Chalo ek chhota sa check karte hain.", language="hinglish")
    assert page.suggestion_btn.isVisibleTo(page) and page.suggestion_btn.text() == "शुरू करें: सोचने की क्षमता · लगभग 10 मिनट"
    page.suggestion_btn.click()
    assert went == [("assessment_run", {"key": "aptitude", "language": "hi"})]
    assert not page.suggestion_btn.isVisibleTo(page)


def test_before_any_assessment_what_you_enjoy_waits_as_a_start_button(qapp, page, monkeypatch):
    fresh = [{**INSTRUMENTS[0], "last_completed": None}]
    monkeypatch.setattr(maya_page.api_client, "assessment_instruments", lambda: fresh)
    monkeypatch.setattr(maya_page, "run_async",
                        lambda fn, *a, on_success=None, on_error=None: on_success and on_success(fn(*a)))
    page.on_show()
    assert page.suggestion_btn.isVisibleTo(page) and page.suggestion_btn.text() == "Start: What you enjoy · about 6 min"
