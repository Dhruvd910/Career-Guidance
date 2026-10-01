import json
import wave
from pathlib import Path

import numpy as np
import pytest

from app import audio_io, wake_word
from app.config import VOSK_MODEL_DIR

FIXTURES = Path(__file__).parent / "fixtures"


class FakeRecognizer:
    """Stands in for vosk.KaldiRecognizer. A grammar recognizer finalizes a result every
    `utterance_chunks` chunks with the scripted words; the free-form verifier returns the
    scripted transcript."""

    def __init__(self, script, grammar):
        self.script = script
        self.grammar = grammar
        self.chunks = 0
        script["created"].append("grammar" if grammar else "verifier")

    def SetWords(self, _):
        pass

    def Reset(self):
        pass

    def AcceptWaveform(self, data):
        if self.grammar is None:
            self.script["verified_audio"].append(len(data) // 2)
            return True
        self.chunks += 1
        return self.chunks % self.script["utterance_chunks"] == 0

    def Result(self):
        return json.dumps({"result": self.script["grammar_words"]})

    def FinalResult(self):
        return json.dumps({"text": self.script["verifier_text"]})


def make_detector(grammar_words, verifier_text):
    script = {
        "grammar_words": grammar_words, "verifier_text": verifier_text,
        "utterance_chunks": 10, "created": [], "verified_audio": [],
    }
    detector = wake_word.WakeDetector(None, recognizer_factory=lambda model, grammar: FakeRecognizer(script, grammar))
    script["verified_audio"].clear()  # ignore the warm-up decode
    return detector, script


def feed_second(detector):
    chunk = np.full(1600, 1000, dtype=np.int16)
    return [detector.feed(chunk) for _ in range(10)]


def test_wakes_when_both_stages_hear_hey_maya():
    detector, script = make_detector([{"word": "maya", "start": 0.4, "end": 0.7, "conf": 0.9}], "hey maya")
    results = feed_second(detector)
    assert results == [False] * 9 + [True]
    # Verified ~0.5s before to ~0.4s after the word: 0.0s (clamped) .. 1.0s (end of what's buffered)
    assert script["verified_audio"] == [16000]
    # A fresh grammar recognizer after waking, so the same "maya" can't fire twice
    assert script["created"].count("grammar") == 2


def test_grammar_false_alarm_is_rejected_by_verifier():
    detector, script = make_detector([{"word": "maya", "start": 0.3, "end": 0.6, "conf": 0.87}], "nice to meet you")
    assert not any(feed_second(detector))
    assert len(script["verified_audio"]) == 1


def test_name_spelling_variants_count_as_maya():
    for heard in ("hi maia", "okay mia", "hello maya"):
        detector, _ = make_detector([{"word": "maya", "start": 0.3, "end": 0.6}], heard)
        assert feed_second(detector)[-1], heard


def test_the_name_alone_is_not_a_wake_word():
    # "Maya" turns up in ordinary conversation — she waits to be greeted.
    for heard in ("maya", "tell maya about it", "maya is thinking"):
        detector, _ = make_detector([{"word": "maya", "start": 0.3, "end": 0.6}], heard)
        assert not any(feed_second(detector)), heard


def test_no_candidate_means_no_verification():
    detector, script = make_detector([{"word": "hi", "start": 0.3, "end": 0.5}], "maya")
    assert not any(feed_second(detector))
    assert script["verified_audio"] == []


def test_too_short_window_is_not_verified():
    detector, script = make_detector([{"word": "maya", "start": 30.0, "end": 30.2}], "maya")
    assert not any(feed_second(detector))  # word timestamps outside the buffered audio
    assert script["verified_audio"] == []


@pytest.mark.skipif(not VOSK_MODEL_DIR.is_dir(), reason="Vosk model not downloaded")
def test_real_model_ignores_speech_without_maya():
    vosk = pytest.importorskip("vosk")
    vosk.SetLogLevel(-1)
    model = vosk.Model(str(VOSK_MODEL_DIR))
    with wave.open(str(FIXTURES / "speech_without_wake_word.wav")) as w:
        rate = w.getframerate()
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    audio = audio_io.resample_int16(pcm, rate, wake_word.MODEL_RATE)
    detector = wake_word.WakeDetector(model)
    silence = np.zeros(1600, dtype=np.int16)
    wakes = 0
    for _ in range(2):
        for i in range(0, len(audio), 1600):
            wakes += detector.feed(audio[i:i + 1600])
        for _ in range(15):
            wakes += detector.feed(silence)
    assert wakes == 0


@pytest.mark.parametrize("heard, wakes", [
    ("hey maya", True), ("hello maya", True), ("okay maya", True),
    ("stop maya", True), ("maya stop", True), ("wait maya", True), ("maya wait", True),
    ("maya", False), ("i asked maya about it", False), ("please stop the video", False),
    ("maya is great", False),
])
def test_what_counts_as_calling_maya(heard, wakes):
    assert wake_word.is_wake_phrase(heard.split()) is wakes
