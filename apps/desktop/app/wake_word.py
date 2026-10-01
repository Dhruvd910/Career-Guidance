"""Offline wake word: listens for "Maya" on the Pi itself, with a small Vosk speech model,
so no room audio leaves the device until someone actually says her name.

It's a background mic user. The USB mic accepts only one stream, so foreground recording
(VoiceRecorder) pauses this synchronously before opening its own; the main window resumes
it once MAYA has been idle for a moment. It never runs while MAYA is speaking — she'd wake
herself up every time she said her own name.
"""

from __future__ import annotations

import json
import queue
import threading
from pathlib import Path

import numpy as np
import sounddevice as sd
from PySide6.QtCore import QObject, Signal

from app import audio_io
from app.config import VOSK_MODEL_DIR

MODEL_RATE = 16000
BLOCK_SECONDS = 0.1
# A greeting is required: "Maya" on its own is a word that turns up in ordinary conversation
# (and in MAYA's own name on screen), so she'd wake at the wrong moments.
WAKE_GREETINGS = ["hey", "hi", "hello", "ok", "okay"]
# "Stop Maya" / "Maya stop" interrupt her while she's talking, the same way "Hey Maya" does.
STOP_WORDS = ["stop", "wait"]
WAKE_PHRASES = (
    [f"{greeting} maya" for greeting in WAKE_GREETINGS + STOP_WORDS]
    + [f"maya {word}" for word in STOP_WORDS]
)
# What the full-vocabulary recognizer may write for a real "Maya" (it's a name, so spelling varies).
VERIFIED_WAKE_WORDS = {"maya", "mia", "maia", "mayer", "myra"}
BUFFER_SECONDS = 5
VERIFY_BEFORE_SECONDS = 0.5
VERIFY_AFTER_SECONDS = 0.4


def _vosk_recognizer(model, grammar: str | None):
    import vosk

    if grammar is None:
        return vosk.KaldiRecognizer(model, MODEL_RATE)
    return vosk.KaldiRecognizer(model, MODEL_RATE, grammar)


def is_wake_phrase(words: list[str]) -> bool:
    """"hey/hi/hello/ok/stop/wait maya", or "maya stop/wait" — the name alone never counts."""
    for i, word in enumerate(words):
        if word not in VERIFIED_WAKE_WORDS:
            continue
        if i > 0 and words[i - 1] in WAKE_GREETINGS + STOP_WORDS:
            return True
        if i + 1 < len(words) and words[i + 1] in STOP_WORDS:
            return True
    return False


class WakeDetector:
    """Decides whether audio contained "Maya", in two stages.

    1. A recognizer restricted to ["hey maya", "hi maya", "hello maya", …, unknown] runs on every chunk.
       It's cheap (~8% of a core while someone talks) but, forced to choose, it hears "maya" in
       ordinary speech: in testing it said "maya" with confidence 0.87 for "nice to meet you".
    2. So each candidate is re-read by an unrestricted recognizer over just ~1s of audio around
       it (~0.2s on a Pi). That one transcribed the same clip correctly, and MAYA only wakes if
       it hears a greeting immediately before the name. Running it continuously would cost ~54%
       of a core instead.
    """

    def __init__(self, model, recognizer_factory=None):
        self._model = model
        self._make = recognizer_factory or _vosk_recognizer
        self._grammar = self._new_grammar_recognizer()
        self._verifier = self._make(model, None)
        self._verifier.AcceptWaveform(bytes(MODEL_RATE))  # warm-up: the first decode is ~3x slower
        self._verifier.FinalResult()
        self._buffer = np.zeros(0, dtype=np.int16)
        self._fed = 0  # samples fed to the current grammar recognizer (word timestamps count from here)

    def _new_grammar_recognizer(self):
        recognizer = self._make(self._model, json.dumps(WAKE_PHRASES + ["[unk]"]))
        recognizer.SetWords(True)
        return recognizer

    def feed(self, pcm16: np.ndarray) -> bool:
        """Feed 16kHz mono int16 audio. Returns True when "Hey Maya" (or hi/hello Maya) was heard."""
        self._buffer = np.concatenate([self._buffer, pcm16])[-BUFFER_SECONDS * MODEL_RATE:]
        self._fed += len(pcm16)
        if not self._grammar.AcceptWaveform(pcm16.tobytes()):
            return False
        result = json.loads(self._grammar.Result())
        for word in result.get("result", []):
            if word.get("word") == "maya" and self._verified(word["start"], word["end"]):
                self._grammar = self._new_grammar_recognizer()
                self._buffer = np.zeros(0, dtype=np.int16)
                self._fed = 0
                return True
        return False

    def _verified(self, start: float, end: float) -> bool:
        buffer_origin = self._fed - len(self._buffer)
        first = max(0, int((start - VERIFY_BEFORE_SECONDS) * MODEL_RATE) - buffer_origin)
        last = min(len(self._buffer), int((end + VERIFY_AFTER_SECONDS) * MODEL_RATE) - buffer_origin)
        if last - first < MODEL_RATE // 5:
            return False
        self._verifier.Reset()
        self._verifier.AcceptWaveform(self._buffer[first:last].tobytes())
        heard = json.loads(self._verifier.FinalResult()).get("text", "").split()
        return is_wake_phrase(heard)


class WakeWordListener(QObject):
    detected = Signal()
    available_changed = Signal(bool)
    _heard = Signal()
    _loaded = Signal(bool)

    def __init__(self, model_dir: Path = VOSK_MODEL_DIR):
        super().__init__()
        self.available = False
        self._model = None
        self._stream: sd.InputStream | None = None
        self._stop_event = threading.Event()
        self._want_running = False
        self._heard.connect(self._on_heard)
        self._loaded.connect(self._on_loaded)
        audio_io.set_background_mic_user(self)
        # ~4s and ~100MB on a Pi — never on the UI thread.
        threading.Thread(target=self._load, args=(model_dir,), name="vosk-load", daemon=True).start()

    @property
    def is_running(self) -> bool:
        return self._stream is not None

    def _load(self, model_dir: Path) -> None:
        try:
            import vosk

            vosk.SetLogLevel(-1)
            if not Path(model_dir).is_dir():
                raise FileNotFoundError(model_dir)
            self._model = vosk.Model(str(model_dir))
            ok = True
        except Exception:  # noqa: BLE001 — no model means tap-to-wake only, never a crash
            ok = False
        self._loaded.emit(ok)

    def _on_loaded(self, ok: bool) -> None:
        self.available = ok
        self.available_changed.emit(ok)
        if ok and self._want_running:
            self.resume()

    def resume(self) -> None:
        self._want_running = True
        if not self.available or self._stream is not None:
            return
        try:
            device = audio_io.input_device()
            rate = audio_io.input_rate(device)
        except Exception:  # noqa: BLE001
            return

        stop_event = threading.Event()
        chunks: queue.Queue = queue.Queue(maxsize=50)

        def callback(indata, frames, time_info, status):
            try:
                chunks.put_nowait(indata[:, 0].copy())
            except queue.Full:
                pass  # recognizer fell behind; dropping audio beats stalling the stream

        try:
            stream = sd.InputStream(
                device=device, samplerate=rate, channels=1, dtype="int16", blocksize=int(rate * BLOCK_SECONDS), callback=callback,
            )
            stream.start()
        except Exception:  # noqa: BLE001 — mic busy or missing; the next resume will retry
            return
        self._stop_event = stop_event
        self._stream = stream
        threading.Thread(
            target=self._recognize, args=(chunks, rate, stop_event), name="wake-word", daemon=True,
        ).start()

    def pause(self) -> None:
        self._want_running = False
        self._stop_event.set()
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.abort()
                stream.close()
            except Exception:  # noqa: BLE001
                pass

    def _recognize(self, chunks: queue.Queue, rate: int, stop_event: threading.Event) -> None:
        detector = WakeDetector(self._model)
        while not stop_event.is_set():
            try:
                chunk = chunks.get(timeout=0.2)
            except queue.Empty:
                continue
            if detector.feed(audio_io.resample_int16(chunk, rate, MODEL_RATE)) and not stop_event.is_set():
                self._heard.emit()

    def _on_heard(self) -> None:
        if self._stream is not None:  # ignore a detection that raced with pause()
            self.detected.emit()


def _diagnose() -> None:  # pragma: no cover - a hands-on check, run from the terminal
    """`python -m app.wake_word` — say "Hey Maya" a few times and watch what she hears.

    Prints every candidate the cheap first-stage recognizer flags, what the second stage
    actually heard in that moment, and whether that counts as a wake. If your "Maya" keeps
    getting written as something not in VERIFIED_WAKE_WORDS, add that spelling there.
    """
    import sys
    import time

    print("Loading the speech model…")
    import vosk

    vosk.SetLogLevel(-1)
    if not Path(VOSK_MODEL_DIR).is_dir():
        sys.exit(f"No model at {VOSK_MODEL_DIR} — see the README.")
    detector = WakeDetector(vosk.Model(str(VOSK_MODEL_DIR)))
    verified = detector._verified

    def traced(start, end):
        heard = verified(start, end)
        print(f"  heard something like 'maya' at {start:.1f}s… second listen says: "
              f"{'WAKE' if heard else 'not Maya, ignoring'}")
        return heard

    detector._verified = traced
    device = audio_io.input_device()
    rate = audio_io.input_rate(device)
    print(f'Listening on the mic at {rate}Hz. Say "Maya" a few times. Ctrl-C to stop.')
    wakes = 0
    with sd.InputStream(device=device, samplerate=rate, channels=1, dtype="int16", blocksize=int(rate * BLOCK_SECONDS)) as stream:
        started = time.time()
        while True:
            block, _overflowed = stream.read(int(rate * BLOCK_SECONDS))
            if detector.feed(audio_io.resample_int16(block[:, 0], rate, MODEL_RATE)):
                wakes += 1
                print(f"MAYA WOKE UP ({wakes} so far, {time.time() - started:.0f}s in)")


if __name__ == "__main__":  # pragma: no cover
    try:
        _diagnose()
    except KeyboardInterrupt:
        print("\nStopped.")
