"""Is someone talking? Two answers to that, behind one small interface.

- SileroGate: a small neural voice-activity model (Silero VAD, MIT licence) run with ONNX
  Runtime — ~0.3 ms per 32 ms of audio on the Pi 5. It tells speech from fans, traffic,
  clicks and music far better than loudness can, which matters most when MAYA has to notice
  someone talking over her own voice.
- EnergyGate: the original loudness check (RMS against the room's measured noise floor). No
  model and no ONNX Runtime needed, so it's the fallback when either is missing.

A gate is fed the microphone a block at a time, at the mic's own rate, and says for each block
whether it sounds like speech — or None while it is still measuring the room.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from app.config import APP_DIR

logger = logging.getLogger(__name__)

SILERO_MODEL = APP_DIR / "models" / "silero_vad.onnx"
SILERO_RATE = 16000
SILERO_FRAME = 512  # samples at 16 kHz: 32 ms
SILERO_CONTEXT = 64  # samples of the previous frame the model expects in front of each one


def resample_int16(samples: np.ndarray, from_rate: int, to_rate: int) -> np.ndarray:
    audio = samples.astype(np.float32)
    n_out = max(1, int(len(audio) * to_rate / from_rate))
    resampled = np.interp(np.linspace(0, len(audio) - 1, n_out), np.arange(len(audio)), audio)
    return np.clip(resampled, -32768, 32767).astype(np.int16)


class EnergyGate:
    """Speech is loud: well above the room, measured over the first ~0.3 s."""

    name = "energy"
    end_silence = 1.2  # seconds of quiet that end an utterance: loudness dips mid-sentence

    CALIBRATION_BLOCKS = 10
    MIN_SPEECH_RMS = 350.0  # floor, so a dead-silent room can't set the threshold near zero
    MAX_SPEECH_THRESHOLD = 3000.0  # cap, so a noisy calibration window can't make speech undetectable

    def __init__(self):
        self._calibration: list[float] = []
        self.threshold: float | None = None
        self._talking = False

    def is_speech(self, block: np.ndarray, rate: int) -> bool | None:
        rms = float(np.sqrt(np.mean(block.astype(np.float32) ** 2)))
        if self.threshold is None:
            self._calibration.append(rms)
            if len(self._calibration) < self.CALIBRATION_BLOCKS:
                return None
            ambient = float(np.median(self._calibration))
            self.threshold = min(max(ambient * 2.8, self.MIN_SPEECH_RMS), self.MAX_SPEECH_THRESHOLD)
            return None
        # Hysteresis: once talking, a slightly quieter syllable still counts as talking.
        self._talking = rms > (self.threshold * 0.7 if self._talking else self.threshold)
        return self._talking


class SileroGate:
    name = "silero"
    end_silence = 0.8  # the model hears a pause for breath as speech-adjacent, so this can be shorter
    START, CONTINUE = 0.5, 0.35  # probability to start counting as speech, and to keep counting

    def __init__(self, session):
        self._session = session
        self._pending = np.zeros(0, dtype=np.float32)
        self.reset()

    def reset(self) -> None:
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._context = np.zeros((1, SILERO_CONTEXT), dtype=np.float32)
        self._pending = np.zeros(0, dtype=np.float32)
        self.probability = 0.0
        self._talking = False

    def speech_probability(self, frame: np.ndarray) -> float:
        """One 512-sample float frame at 16 kHz → the chance it holds speech."""
        x = np.concatenate([self._context, frame.reshape(1, -1)], axis=1)
        out, self._state = self._session.run(
            None, {"input": x, "state": self._state, "sr": np.array(SILERO_RATE, dtype=np.int64)})
        self._context = x[:, -SILERO_CONTEXT:]
        return float(out[0][0])

    def is_speech(self, block: np.ndarray, rate: int) -> bool:
        audio = resample_int16(block, rate, SILERO_RATE) if rate != SILERO_RATE else block
        self._pending = np.concatenate([self._pending, audio.astype(np.float32) / 32768.0])
        while len(self._pending) >= SILERO_FRAME:
            frame, self._pending = self._pending[:SILERO_FRAME], self._pending[SILERO_FRAME:]
            self.probability = self.speech_probability(frame)
            self._talking = self.probability >= (self.CONTINUE if self._talking else self.START)
        return self._talking


_silero_session = None


def silero_available(model: Path = SILERO_MODEL) -> bool:
    return _load_silero(model) is not None


def _load_silero(model: Path = SILERO_MODEL):
    global _silero_session
    if _silero_session is None and model.is_file():
        try:
            import onnxruntime as ort

            options = ort.SessionOptions()
            options.intra_op_num_threads = 1  # one 32 ms frame at a time: more threads only add overhead
            options.inter_op_num_threads = 1
            _silero_session = ort.InferenceSession(str(model), options, providers=["CPUExecutionProvider"])
        except Exception as e:  # noqa: BLE001 — no ONNX Runtime, or a bad model: the energy gate still works
            logger.warning("Silero VAD unavailable, using the energy gate: %s", e)
            _silero_session = False
    return _silero_session or None


def make_gate():
    """The best gate this device can run: Silero when its model and ONNX Runtime are present."""
    session = _load_silero()
    return SileroGate(session) if session is not None else EnergyGate()
