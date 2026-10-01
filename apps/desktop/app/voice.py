"""MAYA's voice: say something, ask something and listen for the answer, or listen for
dictation — one shared mic and speaker, one observable state (drives the mascot), and
cancellation that makes stale callbacks harmless.

Every flow is tagged with a token. cancel(), or starting any new flow, bumps it — so a TTS
request or transcription that comes back after the person already tapped a text box (or
left the page) is dropped instead of hijacking whatever is on screen now.
"""

from __future__ import annotations

import base64
from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer, Signal

from app.api_client import api_client
from app.audio_io import MicUnavailableError, SpeechPlayer, StreamPlayer, VoiceRecorder
from app.voice_parsing import is_meaningful
from app.workers import run_async

IDLE, SPEAKING, LISTENING, THINKING = "idle", "speaking", "listening", "thinking"

# After MAYA stops talking, give the speaker's tail and the room a moment to go quiet
# before opening the mic, so she doesn't transcribe the end of her own sentence.
PAUSE_BEFORE_LISTENING_MS = 250
# If TTS is completely unavailable, still leave a beat before listening so the question
# can be read on screen.
NO_AUDIO_PAUSE_MS = 400


class Voice(QObject):
    state_changed = Signal(str)
    # A streamed reply was cut short: (turn_id, the sentence playing, ms of it played) — what the
    # conversation server needs to keep only what the student heard.
    stream_stopped = Signal(str, int, float)
    # A sentence of the streamed reply finished playing: (turn_id, seq).
    stream_sentence_played = Signal(str, int)

    def __init__(self):
        super().__init__()
        self.state = IDLE
        self.current_text = ""  # what she's saying, or last said
        self._token = 0
        self._after_speech: tuple[int, Callable[[], None] | None] | None = None
        # (token, on_answer, on_no_answer) while an ask() is still at the speaking stage — so
        # an interruption can skip straight to listening for the answer.
        self._asking: tuple[int, Callable[[str], None], Callable[[str], None] | None] | None = None
        # (token, on_result, on_no_answer, transcribe) — on_result gets a transcript, or the raw
        # WAV bytes when transcribe is False.
        self._awaiting_answer: tuple[int, Callable, Callable[[str], None] | None, bool] | None = None

        # The streamed reply in progress: its turn id, and what to do once it has all played.
        self._stream_turn: str | None = None
        self._stream_done: Callable[[], None] | None = None

        self.recorder = VoiceRecorder()
        self.player = SpeechPlayer()
        self.player.finished.connect(self._on_playback_finished)
        self.stream_player = StreamPlayer()
        self.stream_player.drained.connect(self._on_stream_drained)
        self.stream_player.sentence_played.connect(self._on_stream_sentence_played)
        self.recorder.finished.connect(self._on_recording_finished)
        self.recorder.no_speech.connect(lambda: self._on_listen_failed("silence"))
        self.recorder.failed.connect(lambda _message: self._on_listen_failed("error"))

    @property
    def busy(self) -> bool:
        return self.state != IDLE

    def _set_state(self, state: str) -> None:
        if state != self.state:
            self.state = state
            self.state_changed.emit(state)

    def _later(self, ms: int, token: int, fn: Callable[[], None]) -> None:
        QTimer.singleShot(ms, lambda: fn() if token == self._token else None)

    def cancel(self) -> None:
        self._token += 1
        self.recorder.cancel()
        self.player.stop()
        self._after_speech = None
        self._awaiting_answer = None
        self._asking = None
        if self._stream_turn is not None:
            turn_id, self._stream_turn, self._stream_done = self._stream_turn, None, None
            seq, played_ms = self.stream_player.stop() or (0, 0.0)
            self.stream_stopped.emit(turn_id, seq, played_ms)
        self._set_state(IDLE)

    # ---------------- a streamed reply (the live conversation) ----------------

    def begin_stream(self, turn_id: str) -> None:
        """A reply is on its way: think until its speech arrives, then speak it as it comes."""
        self.cancel()
        self._stream_turn = turn_id
        self.current_text = ""
        self._set_state(THINKING)

    def stream_text(self, turn_id: str, text: str) -> None:
        """A sentence of the reply — kept as what she's saying, so the wake word can tell her
        own voice saying "…Maya…" from someone calling her."""
        if turn_id == self._stream_turn:
            self.current_text = f"{self.current_text} {text}".strip()

    def stream_audio(self, turn_id: str, seq: int, sample_rate: int, pcm: bytes) -> None:
        if turn_id != self._stream_turn:
            return
        if not self.stream_player.active:
            self.stream_player.start(sample_rate)
        self.stream_player.feed(seq, pcm)
        self._set_state(SPEAKING)

    def end_stream(self, turn_id: str, on_done: Callable[[], None] | None = None) -> None:
        """The whole reply has arrived. on_done runs once it has finished playing — at once if
        there was no speech (the voice was unavailable)."""
        if turn_id != self._stream_turn:
            return
        if self.stream_player.active:
            self._stream_done = on_done
            self.stream_player.end()
            return
        self._stream_turn = None
        self._set_state(IDLE)
        if on_done:
            self._later(NO_AUDIO_PAUSE_MS, self._token, on_done)

    def _on_stream_sentence_played(self, seq: int) -> None:
        if self._stream_turn is not None:
            self.stream_sentence_played.emit(self._stream_turn, seq)

    def _on_stream_drained(self) -> None:
        if self._stream_turn is None:
            return
        on_done, self._stream_turn, self._stream_done = self._stream_done, None, None
        self._set_state(IDLE)
        if on_done:
            self._later(PAUSE_BEFORE_LISTENING_MS, self._token, on_done)

    # ---------------- speaking ----------------

    def say(self, text: str, on_done: Callable[[], None] | None = None, language: str | None = None) -> None:
        """language: the reply's, when known ("en"/"hi"/"hinglish") — see api_client.speak."""
        self.cancel()
        self.current_text = text
        token = self._token
        self._set_state(THINKING)
        run_async(
            api_client.speak, text, **({"language": language} if language else {}),
            on_success=lambda result: self._on_speech_ready(token, result, on_done),
            on_error=lambda _err: self._on_speech_ready(token, None, on_done),
        )

    def _on_speech_ready(self, token: int, result: dict | None, on_done: Callable[[], None] | None) -> None:
        if token != self._token:
            return
        audio_b64 = (result or {}).get("audio_base64")
        if not audio_b64:
            self._set_state(IDLE)
            if on_done:
                self._later(NO_AUDIO_PAUSE_MS, token, on_done)
            return
        self._after_speech = (token, on_done)
        self._set_state(SPEAKING)
        self.player.play(base64.b64decode(audio_b64))

    def _on_playback_finished(self) -> None:
        pending, self._after_speech = self._after_speech, None
        if pending is None or pending[0] != self._token:
            return
        self._set_state(IDLE)
        token, on_done = pending
        if on_done:
            self._later(PAUSE_BEFORE_LISTENING_MS, token, on_done)

    # ---------------- listening ----------------

    def ask(self, text: str, on_answer: Callable[[str], None], on_no_answer: Callable[[str], None] | None = None) -> None:
        """Speak a question, then listen for the answer. on_no_answer gets a reason:
        'silence', 'unclear', 'no_mic', or 'error'."""
        self.say(text, on_done=lambda: self.listen(on_answer, on_no_answer))
        self._asking = (self._token, on_answer, on_no_answer)

    @property
    def speaking(self) -> bool:
        """Talking, or about to (the audio is on its way)."""
        return (self._after_speech is not None or self._stream_turn is not None
                or (self.state == THINKING and self._awaiting_answer is None))

    def interrupt(self) -> bool:
        """Someone said "Hey Maya" / "Stop Maya" over her. She stops talking at once. If she
        was asking a question, she goes straight to listening for the answer and this returns
        True; otherwise it returns False and the caller decides what listening means there."""
        asking = self._asking
        if asking is not None and asking[0] == self._token:
            _token, on_answer, on_no_answer = asking
            self.listen(on_answer, on_no_answer)  # cancels the speech first
            return True
        self.cancel()
        return False

    def listen(self, on_answer: Callable[[str], None], on_no_answer: Callable[[str], None] | None = None) -> None:
        self._start_listening(on_answer, on_no_answer, transcribe=True)

    def listen_for_audio(self, on_audio: Callable[[bytes], None], on_no_answer: Callable[[str], None] | None = None) -> None:
        """Record one utterance and hand back the WAV untranscribed — for MAYA's chat, whose
        endpoint transcribes server-side as part of the same request."""
        self._start_listening(on_audio, on_no_answer, transcribe=False)

    def play_audio(self, audio_b64: str, on_done: Callable[[], None] | None = None) -> None:
        """Play audio that's already been synthesized (e.g. returned alongside a chat reply)."""
        self.cancel()
        self._on_speech_ready(self._token, {"audio_base64": audio_b64}, on_done)

    def _start_listening(self, on_result: Callable, on_no_answer: Callable[[str], None] | None, transcribe: bool) -> None:
        self.cancel()
        token = self._token
        try:
            self.recorder.listen()
        except MicUnavailableError:
            if on_no_answer:
                on_no_answer("no_mic")
            return
        self._awaiting_answer = (token, on_result, on_no_answer, transcribe)
        self._set_state(LISTENING)

    def _on_recording_finished(self, wav_bytes: bytes) -> None:
        pending = self._awaiting_answer
        if pending is None or pending[0] != self._token:
            return
        token, on_result, _on_no_answer, transcribe = pending
        if not transcribe:
            self._awaiting_answer = None
            self._set_state(IDLE)
            on_result(wav_bytes)
            return
        self._set_state(THINKING)
        run_async(
            api_client.transcribe, wav_bytes,
            on_success=lambda result: self._on_transcribed(token, (result or {}).get("transcript", "")),
            on_error=lambda _err: self._on_transcribed(token, None),
        )

    def _on_transcribed(self, token: int, transcript: str | None) -> None:
        if token != self._token:
            return
        pending, self._awaiting_answer = self._awaiting_answer, None
        self._set_state(IDLE)
        if pending is None:
            return
        _token, on_answer, on_no_answer, _transcribe = pending
        if transcript is None:
            if on_no_answer:
                on_no_answer("error")
        elif is_meaningful(transcript):
            on_answer(transcript)
        elif on_no_answer:
            on_no_answer("unclear")

    def _on_listen_failed(self, reason: str) -> None:
        pending = self._awaiting_answer
        if pending is None or pending[0] != self._token:
            return
        self._awaiting_answer = None
        self._set_state(IDLE)
        if pending[2]:
            pending[2](reason)
