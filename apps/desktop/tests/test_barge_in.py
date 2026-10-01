"""Interrupting MAYA by talking over her."""

import pytest
from PySide6.QtCore import QObject, Signal

from app import audio_io, vad
from app import voice as voice_mod
from app.voice import BARGE_IN_ONSET_BLOCKS, BARGE_IN_SPEECH, BARGE_IN_WAKE_PHRASE, IDLE, LISTENING, SPEAKING
from tests.test_maya_live import FakeOutput, answer, page, sent, type_question  # noqa: F401 — fixture


class FakeBargeRecorder(QObject):
    speech_started = Signal()
    finished = Signal(bytes)

    def __init__(self):
        super().__init__()
        self.listens, self.cancels = [], 0

    def listen(self, **kw):
        self.listens.append(kw)

    def cancel(self):
        self.cancels += 1


@pytest.fixture()
def echo_cancelled(monkeypatch):
    monkeypatch.setattr(audio_io, "echo_cancelled", lambda: True)
    monkeypatch.setattr(vad, "silero_available", lambda model=None: True)


@pytest.fixture()
def barge(page):  # noqa: F811
    recorder = FakeBargeRecorder()
    voice = page.voice
    voice.barge_recorder = recorder
    recorder.speech_started.connect(voice._on_barge_in_started)
    recorder.finished.connect(voice._on_barge_in_finished)
    return recorder


def test_while_she_speaks_she_listens_for_someone_talking_over_her(qapp, page, barge, echo_cancelled):  # noqa: F811
    turn = type_question(page, "Options?")
    answer(page, turn, "Engineering is one path.", "Medicine is another.", audio_ms=500)
    assert page.voice.barge_in_mode == BARGE_IN_SPEECH
    assert len(barge.listens) == 1, "one listener for the whole reply"
    kw = barge.listens[0]
    assert kw["onset_blocks"] == BARGE_IN_ONSET_BLOCKS and kw["no_speech_timeout"] is None
    assert kw["pause_background"] is False


def test_talking_over_her_stops_her_and_becomes_the_next_question(qapp, page, barge, echo_cancelled):  # noqa: F811
    turn = type_question(page, "Options?")
    answer(page, turn, "Engineering is one path.", "Medicine is another.", audio_ms=500)
    FakeOutput.last.play(3)  # 150 ms into the first sentence

    barge.speech_started.emit()
    interrupt = sent(page, "turn.interrupt")[-1]
    assert interrupt["turn_id"] == turn and interrupt["seq"] == 0 and interrupt["played_ms"] == pytest.approx(150.0)
    assert FakeOutput.last.aborted and page.voice.state == LISTENING

    barge.finished.emit(b"RIFF-the-student")
    header, wav = page.socket.sent[-2], page.socket.sent[-1]
    assert header["type"] == "turn.audio" and wav == b"RIFF-the-student"
    assert header["barge_in"] is True
    assert header["over"] == "Engineering is one path. Medicine is another."


def test_the_listener_stops_when_she_finishes(qapp, page, barge, echo_cancelled):  # noqa: F811
    turn = type_question(page, "Options?")
    answer(page, turn, "Short answer.", audio_ms=100)
    FakeOutput.last.play(4)
    qapp.processEvents()
    assert page.voice.state == IDLE and barge.cancels >= 1
    barge.speech_started.emit()  # too late: she'd already finished
    assert sent(page, "turn.interrupt") == []


def test_hearing_herself_three_times_falls_back_to_the_wake_phrase(qapp, page, barge, echo_cancelled):  # noqa: F811
    for _ in range(3):
        turn = type_question(page, "Options?")
        answer(page, turn, "Engineering is one path.", audio_ms=500)
        barge.speech_started.emit()
        barge.finished.emit(b"RIFF")
        echo_turn = page.socket.sent[-2]["turn_id"]
        page.socket.server({"type": "turn.echo", "turn_id": echo_turn})
    assert page.voice.barge_in_mode == BARGE_IN_WAKE_PHRASE
    assert not page.voice.listens_while_speaking
    listens = len(barge.listens)
    turn = type_question(page, "Options?")
    answer(page, turn, "Engineering is one path.", audio_ms=500)
    assert len(barge.listens) == listens, "no more listening over her"


def test_without_the_echo_canceller_only_the_wake_phrase_interrupts(qapp, page, barge):  # noqa: F811
    turn = type_question(page, "Options?")
    answer(page, turn, "Engineering is one path.", audio_ms=500)
    assert page.voice.barge_in_mode == BARGE_IN_WAKE_PHRASE and barge.listens == []


def test_the_wake_phrase_listener_steps_aside_while_she_can_hear_speech(qapp, monkeypatch, echo_cancelled):
    from app.main_window import MainWindow

    class Window:
        _wake_word_wanted = MainWindow._wake_word_wanted
        _keyboard_shown = False

    w = Window()
    w.voice = voice_mod.Voice()
    w._current_page = "maya"
    w.voice._stream_turn, w.voice.state, w.voice.barge_in_mode = "t1", SPEAKING, BARGE_IN_SPEECH
    assert w._wake_word_wanted() is False, "talking over her already interrupts"
    w.voice.barge_in_mode = BARGE_IN_WAKE_PHRASE
    assert w._wake_word_wanted() is True, '"Stop Maya" it is, then'
