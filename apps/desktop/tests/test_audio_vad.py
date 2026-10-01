"""Speech detection, exercised without a microphone: a fake PortAudio stream feeds the real
VoiceRecorder callback synthetic blocks — room hiss, then a voice-level signal, then hiss."""

import io
import os
import threading
import time
import wave

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
import sounddevice as sd  # noqa: E402

from app import audio_io  # noqa: E402
from app.vad import EnergyGate  # noqa: E402

RATE = 44100
BLOCK = int(RATE * audio_io.BLOCK_SECONDS)


def _hiss(seconds, rms=450):
    n = int(seconds / audio_io.BLOCK_SECONDS) * BLOCK
    return np.random.default_rng(0).normal(0, rms, n)


def _voice(seconds, rms=4000):
    t = np.arange(int(seconds / audio_io.BLOCK_SECONDS) * BLOCK) / RATE
    return np.sin(2 * np.pi * 220 * t) * rms * np.sqrt(2)


class FakeStream:
    signal = np.zeros(0)

    def __init__(self, samplerate, channels, dtype, blocksize, callback, finished_callback, device=None):
        self.callback, self.finished_callback, self.blocksize = callback, finished_callback, blocksize
        self._stop = threading.Event()

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        data = np.clip(FakeStream.signal, -32768, 32767).astype(np.int16)
        for i in range(0, len(data) - self.blocksize + 1, self.blocksize):
            if self._stop.is_set():
                break
            try:
                self.callback(data[i:i + self.blocksize].reshape(-1, 1), self.blocksize, None, None)
            except sd.CallbackStop:
                break
        self.finished_callback()

    def abort(self):
        self._stop.set()

    def close(self):
        pass


@pytest.fixture()
def fake_mic(monkeypatch):
    monkeypatch.setattr(audio_io.sd, "InputStream", FakeStream)
    def query_devices(device=None, kind=None):
        # No arguments lists every device: none here, so PortAudio's default input is used.
        if device is None and kind is None:
            return []
        return {"default_samplerate": RATE}

    monkeypatch.setattr(audio_io.sd, "query_devices", query_devices)
    # These signals are synthetic tones and hiss, which only the loudness gate takes for speech;
    # the Silero model is tested on a real voice in test_vad.py.
    monkeypatch.setattr(audio_io, "make_gate", EnergyGate)
    return FakeStream


def _run(qapp, recorder, timeout=10.0, **listen_kwargs):
    outcome = []
    recorder.finished.connect(lambda b: outcome.append(("speech", b)))
    recorder.no_speech.connect(lambda: outcome.append(("no_speech", None)))
    recorder.failed.connect(lambda m: outcome.append(("failed", m)))
    recorder.listen(**listen_kwargs)
    end = time.time() + timeout
    while not outcome and time.time() < end:
        qapp.processEvents()
        time.sleep(0.005)
    return outcome


def test_detects_speech_and_stops_after_silence(qapp, fake_mic):
    fake_mic.signal = np.concatenate([_hiss(0.5), _voice(1.0), _hiss(3.0)])
    outcome = _run(qapp, audio_io.VoiceRecorder(), end_silence=1.0)

    assert len(outcome) == 1 and outcome[0][0] == "speech"
    with wave.open(io.BytesIO(outcome[0][1])) as w:
        assert w.getframerate() == 16000  # resampled for Whisper
        duration = w.getnframes() / w.getframerate()
    # ~1.0s of voice + 0.4s pre-roll + 0.3s kept trailing silence; the 3s of hiss is trimmed.
    assert 1.4 <= duration <= 2.0


def test_reports_no_speech_in_a_quiet_room(qapp, fake_mic):
    fake_mic.signal = _hiss(10.0)
    outcome = _run(qapp, audio_io.VoiceRecorder(), no_speech_timeout=2.0)
    assert [kind for kind, _ in outcome] == ["no_speech"]


def test_brief_click_is_not_speech(qapp, fake_mic):
    # 30ms spike — shorter than the onset window — then silence.
    fake_mic.signal = np.concatenate([_hiss(0.5), _voice(0.03, rms=9000), _hiss(5.0)])
    outcome = _run(qapp, audio_io.VoiceRecorder(), no_speech_timeout=2.0)
    assert [kind for kind, _ in outcome] == ["no_speech"]


def test_keeps_listening_through_a_short_pause_mid_sentence(qapp, fake_mic):
    # "My name is ... Dhruv": a 0.5s pause shouldn't end the recording when end_silence is 1.2s.
    fake_mic.signal = np.concatenate([_hiss(0.5), _voice(0.8), _hiss(0.5), _voice(0.6), _hiss(3.0)])
    outcome = _run(qapp, audio_io.VoiceRecorder(), end_silence=1.2)
    assert outcome[0][0] == "speech"
    with wave.open(io.BytesIO(outcome[0][1])) as w:
        duration = w.getnframes() / w.getframerate()
    assert duration >= 2.0  # both halves captured, not just "My name is"


def test_cancel_emits_nothing(qapp, fake_mic):
    fake_mic.signal = np.concatenate([_hiss(0.5), _voice(5.0)])
    recorder = audio_io.VoiceRecorder()
    outcome = []
    recorder.finished.connect(lambda b: outcome.append("speech"))
    recorder.no_speech.connect(lambda: outcome.append("no_speech"))
    recorder.listen()
    recorder.cancel()
    end = time.time() + 1.5
    while time.time() < end:
        qapp.processEvents()
        time.sleep(0.01)
    assert outcome == []
    assert not recorder.is_listening
