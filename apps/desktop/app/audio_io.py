"""Audio for MAYA's voice: microphone capture that stops on its own when you stop talking,
and speech playback.

Both go through PortAudio straight to ALSA. The kiosk X session has no PulseAudio or
PipeWire (neither is even installed), so Qt Multimedia's audio output had nowhere to go
there and MAYA was silent in kiosk mode. On this Pi, PortAudio's defaults are the USB sound
card's microphone and the 3.5mm jack.

The USB mic only accepts 44.1/48kHz (it rejects 16kHz outright), so capture runs at the
device's native rate and is resampled to 16kHz — what Whisper uses anyway — before upload.
"""

from __future__ import annotations

import io
import os
import subprocess
import threading
import wave

import numpy as np
import sounddevice as sd
from PySide6.QtCore import QObject, Signal

WHISPER_RATE = 16000
PLAYBACK_RATE = 44100

BLOCK_SECONDS = 0.03
CALIBRATION_BLOCKS = 10  # ~0.3s of room noise measured before deciding what counts as speech
MIN_SPEECH_RMS = 350.0  # floor, so a dead-silent room can't set the threshold near zero
MAX_SPEECH_THRESHOLD = 3000.0  # cap, so a noisy calibration window can't make speech undetectable
SPEECH_ONSET_BLOCKS = 3  # ~90ms above threshold is speech; shorter is a click or a cough
PRE_ROLL_SECONDS = 0.4  # keep audio from just before onset so the first syllable isn't clipped
TRAILING_KEEP_SECONDS = 0.3


class MicUnavailableError(Exception):
    pass


# The USB mic accepts only one open stream. Something that listens in the background (the
# "Maya" wake word) registers here, and foreground recording pauses it before opening its own
# stream — otherwise the recording would fail with "device busy".
_background_mic_user = None


def set_background_mic_user(user) -> None:
    global _background_mic_user
    _background_mic_user = user


def input_device() -> int | str | None:
    """The microphone to record from.

    PortAudio's default input is the first USB sound card, which is the one driving the
    speaker — and with nothing plugged into its mic jack it records near-silence, so MAYA
    never "hears" anything. A dedicated USB microphone shows up as an input-only device, so
    prefer that. MAYA_MIC (a device index or part of its name) overrides the choice.
    """
    override = os.environ.get("MAYA_MIC", "").strip()
    if override:
        return int(override) if override.isdigit() else override
    try:
        for index, dev in enumerate(sd.query_devices()):
            if dev["max_input_channels"] > 0 and dev["max_output_channels"] == 0 and "(hw:" in dev["name"]:
                return index
    except Exception:  # noqa: BLE001 — PortAudio raises its own exception types
        pass
    return None  # PortAudio's default


def input_rate(device: int | str | None) -> int:
    return int(sd.query_devices(device, kind="input")["default_samplerate"])


def resample_int16(samples: np.ndarray, from_rate: int, to_rate: int) -> np.ndarray:
    audio = samples.astype(np.float32)
    n_out = max(1, int(len(audio) * to_rate / from_rate))
    resampled = np.interp(np.linspace(0, len(audio) - 1, n_out), np.arange(len(audio)), audio)
    return np.clip(resampled, -32768, 32767).astype(np.int16)


class VoiceRecorder(QObject):
    """Emits exactly one of finished(wav_bytes), no_speech(), or failed(message) per
    listen() — unless cancel() is called first, in which case it emits nothing."""

    speech_started = Signal()
    finished = Signal(bytes)
    no_speech = Signal()
    failed = Signal(str)
    _ended = Signal(int)  # carries the stream generation from the PortAudio thread to the UI thread

    def __init__(self):
        super().__init__()
        self._stream: sd.InputStream | None = None
        self._gen = 0
        self._ended.connect(self._on_ended)

    @property
    def is_listening(self) -> bool:
        return self._stream is not None

    def listen(self, max_seconds: float = 15.0, no_speech_timeout: float = 7.0, end_silence: float = 1.2) -> None:
        self.cancel()
        self._gen += 1
        gen = self._gen
        if _background_mic_user is not None:
            _background_mic_user.pause()

        try:
            device = input_device()
            rate = input_rate(device)
        except Exception as e:  # noqa: BLE001 — PortAudio raises its own exception types
            raise MicUnavailableError(f"No microphone available: {e}") from e

        self._rate = rate
        self._blocks: list[np.ndarray] = []
        self._calibration: list[float] = []
        self._threshold: float | None = None
        self._onset_run = 0
        self._speech_start: int | None = None
        self._last_voice = 0
        self._outcome: str | None = None

        max_blocks = int(max_seconds / BLOCK_SECONDS)
        no_speech_blocks = int(no_speech_timeout / BLOCK_SECONDS)
        end_blocks = int(end_silence / BLOCK_SECONDS)

        def callback(indata, frames, time_info, status):
            chunk = indata[:, 0].copy()
            self._blocks.append(chunk)
            i = len(self._blocks) - 1
            rms = float(np.sqrt(np.mean(chunk.astype(np.float32) ** 2)))

            if i < CALIBRATION_BLOCKS:
                self._calibration.append(rms)
                return
            if self._threshold is None:
                ambient = float(np.median(self._calibration))
                self._threshold = min(max(ambient * 2.8, MIN_SPEECH_RMS), MAX_SPEECH_THRESHOLD)

            if self._speech_start is None:
                self._onset_run = self._onset_run + 1 if rms > self._threshold else 0
                if self._onset_run >= SPEECH_ONSET_BLOCKS:
                    self._speech_start = i - SPEECH_ONSET_BLOCKS + 1
                    self._last_voice = i
                    self.speech_started.emit()
                elif i >= no_speech_blocks:
                    self._outcome = "no_speech"
                    raise sd.CallbackStop
            else:
                # Hysteresis: once talking, a slightly quieter syllable still counts as talking.
                if rms > self._threshold * 0.7:
                    self._last_voice = i
                elif i - self._last_voice >= end_blocks:
                    self._outcome = "speech"
                    raise sd.CallbackStop

            if i >= max_blocks:
                self._outcome = "speech" if self._speech_start is not None else "no_speech"
                raise sd.CallbackStop

        def stream_finished() -> None:
            # Must return None: cffi rejects a lambda here because Signal.emit returns a value.
            self._ended.emit(gen)

        try:
            stream = sd.InputStream(
                device=device, samplerate=rate, channels=1, dtype="int16", blocksize=int(rate * BLOCK_SECONDS),
                callback=callback, finished_callback=stream_finished,
            )
            stream.start()
        except Exception as e:  # noqa: BLE001
            raise MicUnavailableError(f"No microphone available: {e}") from e
        self._stream = stream

    def cancel(self) -> None:
        self._gen += 1  # any end-of-stream event still in flight is now stale
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.abort()
                stream.close()
            except Exception:  # noqa: BLE001
                pass

    def _on_ended(self, gen: int) -> None:
        if gen != self._gen:
            return
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.close()
            except Exception:  # noqa: BLE001
                pass
        if self._outcome == "speech":
            self.finished.emit(self._utterance_wav())
        elif self._outcome == "no_speech":
            self.no_speech.emit()
        else:
            self.failed.emit("Recording stopped unexpectedly.")

    def _utterance_wav(self) -> bytes:
        start = max(0, self._speech_start - int(PRE_ROLL_SECONDS / BLOCK_SECONDS))
        end = min(len(self._blocks), self._last_voice + 1 + int(TRAILING_KEEP_SECONDS / BLOCK_SECONDS))
        pcm = resample_int16(np.concatenate(self._blocks[start:end]), self._rate, WHISPER_RATE)

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(WHISPER_RATE)
            wf.writeframes(pcm.tobytes())
        return buf.getvalue()


def decode_to_pcm(audio_bytes: bytes, rate: int = PLAYBACK_RATE) -> np.ndarray:
    """Any format the TTS engines return (Cartesia MP3, Piper WAV) -> mono int16 PCM."""
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
         "-f", "s16le", "-acodec", "pcm_s16le", "-ac", "1", "-ar", str(rate), "pipe:1"],
        input=audio_bytes, capture_output=True, check=True, timeout=30,
    )
    return np.frombuffer(proc.stdout, dtype=np.int16)


class SpeechPlayer(QObject):
    """Emits finished once playback completes. stop(), or a newer play(), cancels the old
    playback without emitting. A playback that fails outright still emits finished, so a
    conversation never stalls waiting on audio that isn't coming — the words are already
    on screen."""

    finished = Signal()
    _done = Signal(int)

    def __init__(self):
        super().__init__()
        self._gen = 0
        self._stop_event = threading.Event()
        self._done.connect(self._on_done)

    def play(self, audio_bytes: bytes) -> None:
        self.stop()
        self._gen += 1
        stop_event = threading.Event()
        self._stop_event = stop_event
        threading.Thread(target=self._run, args=(audio_bytes, self._gen, stop_event), daemon=True).start()

    def stop(self) -> None:
        self._gen += 1
        self._stop_event.set()

    def _run(self, audio_bytes: bytes, gen: int, stop_event: threading.Event) -> None:
        try:
            pcm = decode_to_pcm(audio_bytes)
            # A short lead-in of silence: the DAC takes a moment to wake, and without it the
            # first syllable gets swallowed.
            pcm = np.concatenate([np.zeros(PLAYBACK_RATE // 20, dtype=np.int16), pcm]).reshape(-1, 1)
            chunk = PLAYBACK_RATE // 10
            with sd.OutputStream(samplerate=PLAYBACK_RATE, channels=1, dtype="int16") as stream:
                for i in range(0, len(pcm), chunk):
                    if stop_event.is_set():
                        stream.abort()
                        return
                    stream.write(pcm[i:i + chunk])
        except Exception:  # noqa: BLE001 — see class docstring
            pass
        if not stop_event.is_set():
            self._done.emit(gen)

    def _on_done(self, gen: int) -> None:
        if gen == self._gen:
            self.finished.emit()
