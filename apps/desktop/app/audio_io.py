"""Audio for MAYA's voice: microphone capture that stops on its own when you stop talking,
and speech playback — whole clips (SpeechPlayer) or a reply streamed as it is spoken
(StreamPlayer).

Everything goes through PortAudio, so it works with plain ALSA (the original kiosk Pi had no
PulseAudio or PipeWire, which left Qt Multimedia silent) and through PipeWire on the Pi
desktop, where the default output is whatever the desktop's volume control points at.

The USB mic only accepts 44.1/48kHz (it rejects 16kHz outright), so capture runs at the
device's native rate and is resampled to 16kHz — what Whisper uses anyway — before upload.
"""

from __future__ import annotations

import io
import os
import subprocess
import threading
import time
import wave

import numpy as np
import sounddevice as sd
from PySide6.QtCore import QObject, Signal

from app.vad import make_gate, resample_int16

WHISPER_RATE = 16000
PLAYBACK_RATE = 44100

BLOCK_SECONDS = 0.03
SPEECH_ONSET_BLOCKS = 3  # ~90ms that sounds like speech is speech; shorter is a click or a cough
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


# MAYA's own ALSA devices through PipeWire's echo canceller (apps/desktop/audio/): her speech
# goes out through maya_speaker, and maya_mic is the microphone with that speech taken back out
# — which is what lets her hear someone talking over her without hearing herself.
EC_SPEAKER, EC_MIC = "maya_speaker", "maya_mic"
EC_SOURCE_NODE = "maya_ec_source"
_EC_CHECK_SECONDS = 30.0
_ec_checked: tuple[float, bool] = (-_EC_CHECK_SECONDS, False)


def echo_cancelled() -> bool:
    """Are the echo-cancelled devices usable right now? Both ALSA names must exist *and* the
    canceller must be running: without it PipeWire quietly connects maya_mic to the default
    source instead — on this Pi, an empty mic socket."""
    global _ec_checked
    checked_at, ok = _ec_checked
    if time.monotonic() - checked_at < _EC_CHECK_SECONDS:
        return ok
    ok = False
    try:
        names = {d["name"] for d in sd.query_devices()}
        if {EC_SPEAKER, EC_MIC} <= names:
            nodes = subprocess.run(["pw-cli", "ls", "Node"], capture_output=True, text=True, timeout=3).stdout
            ok = f'node.name = "{EC_SOURCE_NODE}"' in nodes
    except Exception:  # noqa: BLE001 — no PipeWire tools, no PortAudio: plain devices then
        ok = False
    _ec_checked = (time.monotonic(), ok)
    return ok


def output_device() -> str | None:
    """Where MAYA speaks: through the echo canceller when it's running, else the default output."""
    return EC_SPEAKER if echo_cancelled() else None


def input_device() -> int | str | None:
    """The microphone to record from.

    The echo-cancelled mic when the canceller is running. Otherwise: PortAudio's default input
    is the first USB sound card, which is the one driving the speaker — and with nothing plugged
    into its mic jack it records near-silence, so MAYA never "hears" anything. A dedicated USB
    microphone shows up as an input-only device, so prefer that. MAYA_MIC (a device index or
    part of its name) overrides the choice.
    """
    override = os.environ.get("MAYA_MIC", "").strip()
    if override:
        return int(override) if override.isdigit() else override
    if echo_cancelled():
        return EC_MIC
    try:
        for index, dev in enumerate(sd.query_devices()):
            if dev["max_input_channels"] > 0 and dev["max_output_channels"] == 0 and "(hw:" in dev["name"]:
                return index
    except Exception:  # noqa: BLE001 — PortAudio raises its own exception types
        pass
    return None  # PortAudio's default


def input_rate(device: int | str | None) -> int:
    return int(sd.query_devices(device, kind="input")["default_samplerate"])


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

    def listen(self, max_seconds: float = 15.0, no_speech_timeout: float | None = 7.0,
               end_silence: float | None = None, onset_blocks: int = SPEECH_ONSET_BLOCKS,
               pause_background: bool = True) -> None:
        """end_silence: how long a pause ends the utterance — by default the speech gate's own
        (shorter for the Silero model, which isn't fooled by a quieter syllable).
        no_speech_timeout None: wait for speech as long as it takes (until cancel()).
        onset_blocks: how many 30 ms blocks of speech in a row start an utterance."""
        self.cancel()
        self._gen += 1
        gen = self._gen
        if pause_background and _background_mic_user is not None:
            _background_mic_user.pause()

        try:
            device = input_device()
            rate = input_rate(device)
        except Exception as e:  # noqa: BLE001 — PortAudio raises its own exception types
            raise MicUnavailableError(f"No microphone available: {e}") from e

        gate = make_gate()
        self._rate = rate
        self._blocks: list[np.ndarray] = []
        self._onset_run = 0
        self._speech_start: int | None = None
        self._last_voice = 0
        self._outcome: str | None = None

        max_blocks = int(max_seconds / BLOCK_SECONDS)
        no_speech_blocks = int(no_speech_timeout / BLOCK_SECONDS) if no_speech_timeout is not None else max_blocks
        end_blocks = int((end_silence if end_silence is not None else gate.end_silence) / BLOCK_SECONDS)

        def callback(indata, frames, time_info, status):
            chunk = indata[:, 0].copy()
            self._blocks.append(chunk)
            i = len(self._blocks) - 1
            speech = gate.is_speech(chunk, rate)
            if speech is None:
                return  # still measuring the room

            if self._speech_start is None:
                self._onset_run = self._onset_run + 1 if speech else 0
                if self._onset_run >= onset_blocks:
                    self._speech_start = i - onset_blocks + 1
                    self._last_voice = i
                    self.speech_started.emit()
                elif i >= no_speech_blocks:
                    self._outcome = "no_speech"
                    raise sd.CallbackStop
            elif speech:
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
            with sd.OutputStream(device=output_device(), samplerate=PLAYBACK_RATE, channels=1, dtype="int16") as stream:
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


class StreamPlayer(QObject):
    """Plays a reply's speech while it is still arriving: 16-bit mono PCM chunks, each tagged
    with the sentence (`seq`) it belongs to, played back to back with no gaps between them.

    It always knows how far it has got — which sentence, and how many ms into it — so when the
    student interrupts, stop() can say exactly what they heard. If the next chunk is late, the
    speaker plays silence until it comes rather than stopping.

    Signals: sentence_played(seq) as each sentence's last sample goes out; drained() once
    end() has been called and everything queued has played.
    """

    sentence_played = Signal(int)
    drained = Signal()
    _finished = Signal(int)  # stream generation, from PortAudio's thread to the UI thread

    LEAD_IN_SECONDS = 0.05  # the DAC takes a moment to wake; without this the first syllable is lost

    def __init__(self):
        super().__init__()
        self._lock = threading.Lock()
        self._stream = None
        self._gen = 0
        self._finished.connect(self._on_finished)
        self._reset()

    def _reset(self) -> None:
        self._chunks: list[list] = []  # [seq, int16 samples, offset into them]
        self._ended = False
        self._seq: int | None = None  # the sentence now playing
        self._seq_samples = 0  # of it, played so far
        self.rate = PLAYBACK_RATE

    @property
    def active(self) -> bool:
        return self._stream is not None

    def start(self, rate: int) -> None:
        self.stop()
        self._gen += 1
        gen = self._gen
        with self._lock:
            self._reset()
            self.rate = rate
            self._chunks.append([None, np.zeros(int(rate * self.LEAD_IN_SECONDS), dtype=np.int16), 0])

        def finished() -> None:
            self._finished.emit(gen)

        try:
            stream = sd.OutputStream(device=output_device(), samplerate=rate, channels=1, dtype="int16",
                                     callback=self._fill, finished_callback=finished)
            stream.start()
        except Exception:  # noqa: BLE001 — no speaker: the words are on screen anyway
            self._stream = None
            self.drained.emit()
            return
        self._stream = stream

    def feed(self, seq: int, pcm: bytes) -> None:
        samples = np.frombuffer(pcm, dtype=np.int16)
        with self._lock:
            self._chunks.append([seq, samples, 0])

    def end(self) -> None:
        """No more chunks are coming: drained() follows once everything queued has played."""
        with self._lock:
            self._ended = True

    def position(self) -> tuple[int, float]:
        """(the sentence playing, ms of it played) — or the next one at 0 ms between sentences."""
        with self._lock:
            if self._seq is None:
                return 0, 0.0
            return self._seq, self._seq_samples / self.rate * 1000

    def stop(self) -> tuple[int, float] | None:
        """Stops at once. Returns where it stopped, or None if nothing was playing."""
        stream, self._stream = self._stream, None
        if stream is None:
            return None
        self._gen += 1  # its finished callback is now stale
        where = self.position()
        try:
            stream.abort()
            stream.close()
        except Exception:  # noqa: BLE001
            pass
        return where

    def _fill(self, outdata, frames, time_info, status) -> None:
        out = outdata[:, 0]
        filled = 0
        finished_seqs = []
        with self._lock:
            while filled < frames and self._chunks:
                chunk = self._chunks[0]
                seq, samples, offset = chunk
                if seq is not None and seq != self._seq:
                    if self._seq is not None:
                        finished_seqs.append(self._seq)
                    self._seq, self._seq_samples = seq, 0
                take = min(frames - filled, len(samples) - offset)
                out[filled:filled + take] = samples[offset:offset + take]
                filled += take
                chunk[2] += take
                if seq is not None:
                    self._seq_samples += take
                if chunk[2] >= len(samples):
                    self._chunks.pop(0)
            out[filled:] = 0  # waiting for the next chunk, or done
            done = self._ended and not self._chunks
            if done and self._seq is not None:
                finished_seqs.append(self._seq)
                self._seq = None
        for seq in finished_seqs:
            self.sentence_played.emit(seq)
        if done:
            raise sd.CallbackStop

    def _on_finished(self, gen: int) -> None:
        if gen != self._gen:
            return
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.close()
            except Exception:  # noqa: BLE001
                pass
        self.drained.emit()
