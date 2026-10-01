"""The Silero speech gate on real voices — and on the noises a loudness check mistakes for one."""

import wave
from pathlib import Path

import numpy as np
import pytest

from app import audio_io, vad
from app.vad import EnergyGate, SileroGate
from tests.test_audio_vad import RATE, FakeStream

FIXTURES = Path(__file__).parent / "fixtures"

pytestmark = pytest.mark.skipif(not vad.silero_available(), reason="Silero model or onnxruntime not installed")


def voice(name: str, rate: int = RATE) -> np.ndarray:
    with wave.open(str(FIXTURES / name)) as w:
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
        return vad.resample_int16(pcm, w.getframerate(), rate)


def blocks(signal: np.ndarray, rate: int = RATE):
    size = int(rate * audio_io.BLOCK_SECONDS)
    for i in range(0, len(signal) - size + 1, size):
        yield signal[i:i + size]


def decisions(gate, signal):
    return [gate.is_speech(b, RATE) for b in blocks(signal)]


def hiss(seconds, rms=450):
    rng = np.random.default_rng(7)
    return rng.normal(0, rms, int(RATE * seconds)).astype(np.int16)


@pytest.fixture()
def gate():
    return vad.make_gate()


def test_the_best_available_gate_is_silero(gate):
    assert isinstance(gate, SileroGate)


@pytest.mark.parametrize("name", ["maya_hello_16k.wav", "speech_without_wake_word.wav"])
def test_a_real_voice_is_speech(gate, name):
    said = decisions(gate, np.concatenate([np.zeros(RATE // 2, np.int16), voice(name)]))
    assert sum(said) / len(said) > 0.5, "most of a spoken sentence counts as speech"
    assert not any(said[:10]), "the silence before it doesn't"


def test_silence_and_steady_hiss_are_not_speech(gate):
    assert not any(decisions(gate, np.zeros(RATE * 2, np.int16)))
    assert not any(decisions(gate, hiss(2)))


def test_a_fan_switching_on_fools_the_loudness_gate_but_not_silero(gate):
    fan = np.concatenate([hiss(0.5, rms=200), hiss(1.5, rms=4000)])
    assert any(decisions(EnergyGate(), fan)), "loud enough to pass for speech by volume alone"
    assert not any(decisions(gate, fan))


@pytest.fixture()
def silero_mic(monkeypatch):
    monkeypatch.setattr(audio_io.sd, "InputStream", FakeStream)
    monkeypatch.setattr(audio_io.sd, "query_devices",
                        lambda device=None, kind=None: [] if device is None and kind is None else {"default_samplerate": RATE})


def record(qapp, signal):
    """Runs a real VoiceRecorder over `signal`; returns ("speech", wav) or ("no_speech", None)."""
    from PySide6.QtCore import QEventLoop, QTimer

    FakeStream.signal = signal
    recorder = audio_io.VoiceRecorder()
    result = []
    loop = QEventLoop()
    recorder.finished.connect(lambda wav: (result.append(("speech", wav)), loop.quit()))
    recorder.no_speech.connect(lambda: (result.append(("no_speech", None)), loop.quit()))
    recorder.failed.connect(lambda message: (result.append(("failed", message)), loop.quit()))
    recorder.listen(no_speech_timeout=2.0)
    QTimer.singleShot(10_000, loop.quit)
    loop.exec()
    return result[0] if result else ("timeout", None)


def test_the_recorder_ends_an_utterance_on_silero_silence(qapp, silero_mic):
    spoken = voice("speech_without_wake_word.wav")
    outcome, wav = record(qapp, np.concatenate([np.zeros(RATE // 2, np.int16), spoken, np.zeros(RATE * 2, np.int16)]))
    assert outcome == "speech"
    seconds = (len(wav) - 44) / 2 / audio_io.WHISPER_RATE
    assert len(spoken) / RATE - 0.5 < seconds < len(spoken) / RATE + 1.5, "the sentence, not the silence after it"


def test_the_recorder_ignores_a_fan(qapp, silero_mic):
    outcome, _ = record(qapp, np.concatenate([hiss(0.5, rms=200), hiss(3, rms=4000)]))
    assert outcome == "no_speech"
