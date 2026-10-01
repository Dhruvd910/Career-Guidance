"""Voice controller sequencing: say -> play -> pause -> listen -> transcribe -> answer, and
that cancelling at any point drops late callbacks instead of letting them fire."""

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QObject, QTimer, Signal  # noqa: E402

from app import voice as voice_mod  # noqa: E402
from app.audio_io import MicUnavailableError  # noqa: E402


def pump(qapp, seconds):
    end = time.time() + seconds
    while time.time() < end:
        qapp.processEvents()
        time.sleep(0.005)


class FakePlayer(QObject):
    finished = Signal()

    def __init__(self):
        super().__init__()
        self.played, self.stopped = [], 0

    def play(self, audio_bytes):
        self.played.append(audio_bytes)
        QTimer.singleShot(30, self.finished.emit)

    def stop(self):
        self.stopped += 1


class FakeRecorder(QObject):
    speech_started = Signal()
    finished = Signal(bytes)
    no_speech = Signal()
    failed = Signal(str)

    def __init__(self):
        super().__init__()
        self.mode, self.listens, self.cancels = "speech", 0, 0

    def listen(self, **_kw):
        self.listens += 1
        if self.mode == "no_mic":
            raise MicUnavailableError("none")
        if self.mode == "speech":
            QTimer.singleShot(30, lambda: self.finished.emit(b"WAV"))
        elif self.mode == "silence":
            QTimer.singleShot(30, self.no_speech.emit)

    def cancel(self):
        self.cancels += 1


class FakeApi:
    def __init__(self):
        self.audio = "UklGRg=="  # base64 of b"RIFF"
        self.transcript = "My name is Dhruv."
        self.spoken = []

    def speak(self, text):
        self.spoken.append(text)
        return {"audio_base64": self.audio}

    def transcribe(self, wav):
        return {"transcript": self.transcript}


@pytest.fixture()
def voice(qapp, monkeypatch):
    api = FakeApi()
    monkeypatch.setattr(voice_mod, "api_client", api)
    # Deferred but synchronous stand-in for the thread pool, so ordering is deterministic.
    monkeypatch.setattr(
        voice_mod, "run_async",
        lambda fn, *a, on_success=None, on_error=None: QTimer.singleShot(0, lambda: on_success(fn(*a))),
    )
    monkeypatch.setattr(voice_mod, "VoiceRecorder", FakeRecorder)
    monkeypatch.setattr(voice_mod, "SpeechPlayer", FakePlayer)
    v = voice_mod.Voice()
    v.fake_api = api
    return v


def test_ask_speaks_then_listens_then_answers(qapp, voice):
    states, answers = [], []
    voice.state_changed.connect(states.append)
    voice.ask("What's your name?", on_answer=answers.append)
    pump(qapp, 1.0)

    assert voice.fake_api.spoken == ["What's your name?"]
    assert len(voice.player.played) == 1
    assert voice.recorder.listens == 1
    assert answers == ["My name is Dhruv."]
    assert states == ["thinking", "speaking", "idle", "listening", "thinking", "idle"]


def test_listening_does_not_start_until_playback_finishes(qapp, voice):
    voice.ask("What's your name?", on_answer=lambda t: None)
    pump(qapp, 0.02)  # speech fetched and playing, fake player finishes at 30ms
    assert voice.recorder.listens == 0
    pump(qapp, 0.6)
    assert voice.recorder.listens == 1


def test_cancel_during_speech_prevents_listening_and_answer(qapp, voice):
    answers = []
    voice.ask("What's your name?", on_answer=answers.append)
    pump(qapp, 0.01)
    voice.cancel()
    pump(qapp, 1.0)
    assert voice.recorder.listens == 0
    assert answers == []
    assert voice.state == "idle"


def test_cancel_during_transcription_drops_the_late_answer(qapp, voice):
    answers = []

    def cancel_once_transcribing(state):
        if state == "thinking":
            # Queued before the transcription callback, so it lands while that's in flight —
            # like tapping a text box while MAYA is still working out what you said.
            QTimer.singleShot(0, voice.cancel)

    voice.state_changed.connect(cancel_once_transcribing)
    voice.listen(on_answer=answers.append)
    pump(qapp, 0.5)
    assert answers == []
    assert voice.state == "idle"


def test_still_listens_when_tts_returns_no_audio(qapp, voice):
    voice.fake_api.audio = None
    answers = []
    voice.ask("What's your name?", on_answer=answers.append)
    pump(qapp, 1.5)
    assert voice.player.played == []
    assert answers == ["My name is Dhruv."]


def test_whisper_silence_hallucination_counts_as_unclear(qapp, voice):
    voice.fake_api.transcript = "Thank you."
    answers, misses = [], []
    voice.listen(on_answer=answers.append, on_no_answer=misses.append)
    pump(qapp, 0.5)
    assert answers == [] and misses == ["unclear"]


def test_silence_reported(qapp, voice):
    voice.recorder.mode = "silence"
    misses = []
    voice.listen(on_answer=lambda t: None, on_no_answer=misses.append)
    pump(qapp, 0.5)
    assert misses == ["silence"]
    assert voice.state == "idle"


def test_no_microphone_reported_without_crashing(qapp, voice):
    voice.recorder.mode = "no_mic"
    misses = []
    voice.listen(on_answer=lambda t: None, on_no_answer=misses.append)
    assert misses == ["no_mic"]
    assert voice.state == "idle"


def test_new_question_replaces_the_old_one(qapp, voice):
    first, second = [], []
    voice.ask("What's your name?", on_answer=first.append)
    pump(qapp, 0.01)
    voice.ask("Which class are you in?", on_answer=second.append)
    pump(qapp, 1.0)
    assert first == []
    assert second == ["My name is Dhruv."]


def test_interrupting_a_question_skips_to_listening_for_the_answer(qapp, voice):
    """"Hey Maya" while she's still reading a question out: she stops and listens."""
    answers = []
    voice.player.play = lambda audio: voice.player.played.append(audio)  # a long question: never ends
    voice.ask("Which class are you in? Eight, nine, ten, eleven or twelve?", on_answer=answers.append)
    pump(qapp, 0.05)
    assert voice.speaking and voice.recorder.listens == 0

    assert voice.interrupt() is True
    assert voice.player.stopped >= 1, "she stops talking at once"
    pump(qapp, 0.3)
    assert voice.recorder.listens == 1
    assert answers == ["My name is Dhruv."], "the answer goes to the question she was asking"


def test_interrupting_a_statement_just_stops_her(qapp, voice):
    voice.player.play = lambda audio: voice.player.played.append(audio)
    voice.say("Here is a long explanation about engineering branches...")
    pump(qapp, 0.05)
    assert voice.speaking

    assert voice.interrupt() is False, "nothing to answer — the caller decides what to listen for"
    assert not voice.speaking and voice.state == "idle"
    assert voice.recorder.listens == 0


def test_not_speaking_while_listening_or_transcribing(qapp, voice):
    voice.listen(on_answer=lambda t: None)
    assert voice.state == "listening" and not voice.speaking
    pump(qapp, 0.05)  # recording done, transcribing
    assert not voice.speaking
