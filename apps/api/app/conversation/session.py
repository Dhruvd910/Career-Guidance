"""One live conversation over a WebSocket: turns streamed sentence by sentence, and stopped
the moment the student interrupts.

A turn: (speech → transcript) → language → the reply, streamed → sentences → speech per
sentence → the device, which plays each chunk as it arrives. At most one turn runs at a time;
a new one, or an interrupt, cancels it. The protocol is in docs/design/07-api-contracts.md §2.

What gets saved for MAYA's side is what the student actually heard: on an interrupt the device
says which sentence was playing and how far into it, and only that much is kept as the reply
(`content`), with everything generated kept apart (`generated_content`) — so the next reply
doesn't assume they heard the rest.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.ai.orchestrator import NOT_CONFIGURED, Reply, ToolActivity
from app.conversation.chunker import SentenceSplitter
from app.models.chat import Conversation, Message
from app.models.student import StudentProfile
from app.providers.http import ProviderError, warm
from app.providers.registry import get_llm_provider, get_stt_provider, get_tts_provider

logger = logging.getLogger(__name__)

MAX_AUDIO_BYTES = 2 * 1024 * 1024  # ~60 s of 16 kHz WAV; a turn is one utterance

# Whisper "hears" these in silence, fan noise or a cough. Dropped when it also doubted there
# was speech at all.
NO_ANSWER = "Sorry, I don't have an answer for that right now."

HALLUCINATIONS = {"thank you", "thanks for watching", "thank you for watching", "you", "bye",
                  "thank you very much", "subscribe", "धन्यवाद", "शुक्रिया"}


@dataclass
class Sentence:
    text: str
    audio_ms: float = 0.0  # of speech sent so far for it


@dataclass
class Turn:
    id: str
    sentences: list[Sentence] = field(default_factory=list)
    task: asyncio.Task | None = None
    reply: Reply | None = None
    message_id: int | None = None  # MAYA's saved reply, once there is one
    acked_seq: int = -1  # the device finished playing every sentence up to this one
    spoken: bool = False  # any audio went out at all
    language: str | None = None
    latency: dict = field(default_factory=dict)


def _no_speech(text: str, no_speech_prob: float | None) -> bool:
    words = text.strip().lower().strip(" .!?।")
    if not words:
        return True
    doubt = no_speech_prob or 0.0
    return doubt >= 0.8 or (words in HALLUCINATIONS and doubt >= 0.3)


_WORD = re.compile(r"\w+")


def is_echo(heard: str, maya_said: str) -> bool:
    """Was this "interruption" really MAYA's own voice? It is if nearly every word of it is a
    word she was saying. (Only within one script: Whisper may write her Roman Hinglish in
    Devanagari — the echo canceller is the first line of defence; this is the second.)"""
    words = [w.lower() for w in _WORD.findall(heard)]
    if len(words) < 2:
        return False
    said = {w.lower() for w in _WORD.findall(maya_said)}
    return sum(w in said for w in words) / len(words) >= 0.7


def heard_text(turn: Turn, seq: int, played_ms: float) -> str:
    """What the student heard of a turn interrupted while sentence `seq` was `played_ms` in."""
    if not turn.spoken:
        # No audio went out (TTS unavailable): they read every sentence shown so far.
        return " ".join(s.text for s in turn.sentences)
    heard = [s.text for s in turn.sentences[:max(seq, 0)]]
    if 0 <= seq < len(turn.sentences):
        current = turn.sentences[seq]
        if current.audio_ms > 0 and played_ms > 0:
            words = current.text.split()
            share = min(1.0, played_ms / current.audio_ms)
            heard.append(" ".join(words[: int(len(words) * share)]))
    return " ".join(part for part in heard if part).strip()


class ConversationSession:
    def __init__(self, db: Session, profile: StudentProfile, conversation: Conversation,
                 send_json: Callable[[dict], Awaitable[None]], send_bytes: Callable[[bytes], Awaitable[None]]):
        self.db, self.profile, self.conversation = db, profile, conversation
        self._send_json, self._send_bytes = send_json, send_bytes
        # A JSON header and the binary frame it announces must go out back to back.
        self._send_lock = asyncio.Lock()
        self._pending_audio: dict | None = None
        self.turn: Turn | None = None
        self._said_no_voice = False  # told the student, once, that answers will be text only

    async def warm_up(self) -> None:
        """Opens the connections to the AI services while the student is still speaking, so the
        first turn doesn't wait on them."""
        providers = (get_llm_provider(), get_stt_provider(), get_tts_provider())
        urls = {url for p in providers if (url := getattr(p, "base_url", None))}
        await asyncio.gather(*(warm(url) for url in urls))

    # ---------------- sending ----------------

    async def send(self, message: dict, payload: bytes | None = None) -> None:
        async with self._send_lock:
            await self._send_json(message)
            if payload is not None:
                await self._send_bytes(payload)

    # ---------------- receiving ----------------

    async def on_json(self, message: dict) -> None:
        try:
            await self._dispatch(message)
        except (TypeError, ValueError) as e:
            await self.send({"type": "error", "code": "bad_message", "message": str(e), "retryable": False})

    async def _dispatch(self, message: dict) -> None:
        kind = message.get("type")
        if kind == "turn.audio":
            self._pending_audio = message  # the audio itself is the next binary frame
        elif kind == "turn.text":
            text = str(message.get("text") or "").strip()
            if text:
                await self.start_turn(message.get("turn_id"), text=text)
        elif kind == "playback.ack":
            if self.turn and self.turn.id == message.get("turn_id"):
                self.turn.acked_seq = max(self.turn.acked_seq, int(message.get("seq", -1)))
        elif kind == "turn.interrupt":
            await self.interrupt(message.get("turn_id"), int(message.get("seq", 0)),
                                 float(message.get("played_ms", 0.0)))
        elif kind == "ping":
            await self.send({"type": "pong"})
        else:
            await self.send({"type": "error", "code": "bad_message", "message": f"unknown type {kind!r}",
                             "retryable": False})

    async def on_bytes(self, payload: bytes) -> None:
        header, self._pending_audio = self._pending_audio, None
        if header is None:
            await self.send({"type": "error", "code": "bad_message", "message": "audio without a turn.audio header",
                             "retryable": False})
            return
        if len(payload) > MAX_AUDIO_BYTES:
            await self.send({"type": "error", "turn_id": header.get("turn_id"), "code": "audio_too_long",
                             "message": "That was too long to process in one go.", "retryable": False})
            return
        await self.start_turn(header.get("turn_id"), audio=payload, over=header.get("over") if header.get("barge_in") else None)

    # ---------------- turns ----------------

    async def start_turn(self, turn_id: str | None, *, text: str | None = None, audio: bytes | None = None,
                         over: str | None = None) -> None:
        """A new turn implicitly ends the previous one. `over`: what MAYA was saying when this
        utterance cut in (a barge-in), so her own voice leaking past the echo canceller can be
        told apart from the student's."""
        if self.turn is not None:
            await self._end_previous(self.turn)
        await self._continue_or_start_session()
        turn = Turn(id=turn_id or str(uuid.uuid4()))
        self.turn = turn
        turn.task = asyncio.create_task(self._run(turn, text=text, audio=audio, over=over))

    async def _continue_or_start_session(self) -> None:
        """The session may have ended while the page sat open (idle → its memory was written):
        then this turn starts a new one, and the device is told its new id."""
        self.db.refresh(self.conversation)
        if self.conversation.status != "closed":
            return
        self.conversation = Conversation(student_profile_id=self.profile.id, channel=self.conversation.channel)
        self.db.add(self.conversation)
        self.db.commit()
        await self.send({"type": "session.ready", "session_id": self.conversation.id, "opening": None})

    async def interrupt(self, turn_id: str | None, seq: int, played_ms: float) -> None:
        turn = self.turn
        if turn is None or turn.id != turn_id:
            return
        await self._stop(turn)
        self._save_reply(turn, heard_text(turn, seq, played_ms), interrupted=True)
        await self.send({"type": "turn.cancelled", "turn_id": turn.id})
        logger.info("turn %s interrupted at sentence %d (+%.0fms)", turn.id, seq, played_ms)

    async def close(self) -> None:
        if self.turn is not None:
            await self._end_previous(self.turn)

    async def _end_previous(self, turn: Turn) -> None:
        """A turn still running when the next starts (or the connection drops) was heard up to the
        last sentence the device confirmed playing."""
        if turn.task is not None and not turn.task.done():
            await self._stop(turn)
            self._save_reply(turn, heard_text(turn, turn.acked_seq + 1, 0.0), interrupted=True)

    @staticmethod
    async def _stop(turn: Turn) -> None:
        if turn.task is not None and not turn.task.done():
            turn.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await turn.task

    async def _run(self, turn: Turn, *, text: str | None, audio: bytes | None, over: str | None = None) -> None:
        started = time.monotonic()

        def ms() -> int:
            return int((time.monotonic() - started) * 1000)

        stage = "stt"
        try:
            heard_language, stt_confidence = None, None
            if audio is not None:
                stt = get_stt_provider()
                if stt is None:
                    await self._error(turn, "stt_unavailable", "Voice input isn't configured on the server.")
                    return
                heard = await stt.transcribe(audio, "turn.wav")
                turn.latency["stt"] = ms()
                if _no_speech(heard.text, heard.no_speech_prob):
                    await self.send({"type": "turn.no_speech", "turn_id": turn.id})
                    return
                if over and is_echo(heard.text, over):
                    logger.info("turn %s: barge-in was MAYA's own voice: %r", turn.id, heard.text)
                    await self.send({"type": "turn.echo", "turn_id": turn.id})
                    return
                text, heard_language, stt_confidence = heard.text.strip(), heard.language, heard.confidence

            reply = Reply(self.db, self.profile, self.conversation, text, heard_language)
            turn.reply, turn.language = reply, reply.tag.lang
            self.db.add(Message(conversation_id=self.conversation.id, role="user", content=text,
                                turn_id=turn.id, language=reply.tag.lang, stt_confidence=stt_confidence,
                                modality="voice" if audio is not None else "text"))
            self.db.commit()
            await self.send({"type": "turn.transcript", "turn_id": turn.id, "text": text,
                             "language": reply.tag.lang, "script": reply.tag.script, "confidence": stt_confidence})

            stage = "llm"
            llm = get_llm_provider()
            if llm is None:
                await self._error(turn, "llm_unavailable", NOT_CONFIGURED)
                return
            await self.send({"type": "turn.thinking", "turn_id": turn.id})
            await self._stream_reply(turn, reply, llm, ms)
            turn.latency["total"] = ms()
            self._save_reply(turn, reply.text.strip(), interrupted=False)
            await self.send({"type": "reply.done", "turn_id": turn.id, "text": reply.text.strip(),
                             "language": reply.tag.lang, "tool_calls_used": reply.tool_calls_used})
            logger.info("turn %s (%s, %s): %s", turn.id, "voice" if audio is not None else "text",
                        reply.tag.lang, " ".join(f"{k}={v}ms" for k, v in turn.latency.items()))
        except ProviderError as e:
            logger.warning("turn %s failed at %s: %s", turn.id, stage, e)
            self._save_partial(turn)
            await self._error(turn, f"{stage}_unavailable", "I'm having trouble reaching one of my services right "
                                                            "now. Please try again in a moment.")
        except Exception:  # noqa: BLE001 — a bug must still end the turn visibly, not hang it
            logger.exception("turn %s failed", turn.id)
            self._save_partial(turn)
            await self._error(turn, "internal_error", "Something went wrong on my side. Please try again.")

    def _save_partial(self, turn: Turn) -> None:
        """A turn cut short by a failure was heard as far as it got."""
        if turn.reply is not None and turn.reply.text.strip():
            self._save_reply(turn, heard_text(turn, len(turn.sentences), 0.0), interrupted=True)

    async def _stream_reply(self, turn: Turn, reply: Reply, llm, ms: Callable[[], int]) -> None:
        splitter = SentenceSplitter()
        to_speak: asyncio.Queue[int | None] = asyncio.Queue()
        speaker = asyncio.create_task(self._speak(turn, to_speak, reply.tag.voice, ms))
        try:
            async for event in reply.events(llm):
                if isinstance(event, ToolActivity):
                    await self.send({"type": "turn.thinking", "turn_id": turn.id, "activity": event.name})
                    continue
                turn.latency.setdefault("first_token", ms())
                for sentence in splitter.feed(event):
                    await self._sentence(turn, sentence, to_speak)
            for sentence in splitter.flush():
                await self._sentence(turn, sentence, to_speak)
            if not turn.sentences:
                reply.text = NO_ANSWER
                await self._sentence(turn, NO_ANSWER, to_speak)
            await to_speak.put(None)
            await speaker
        finally:
            if not speaker.done():
                speaker.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await speaker

    async def _sentence(self, turn: Turn, text: str, to_speak: asyncio.Queue) -> None:
        seq = len(turn.sentences)
        turn.sentences.append(Sentence(text))
        await self.send({"type": "reply.delta", "turn_id": turn.id, "seq": seq, "text": text})
        await to_speak.put(seq)

    async def _speak(self, turn: Turn, to_speak: asyncio.Queue, voice: str, ms: Callable[[], int]) -> None:
        """Speaks each sentence in order as it comes; synthesis runs faster than speech, so one
        at a time keeps the device ahead. If the voice fails, the rest of the turn is text-only."""
        tts = get_tts_provider()
        if tts is None and not self._said_no_voice:
            self._said_no_voice = True
            await self.send({"type": "error", "turn_id": turn.id, "code": "tts_unavailable",
                             "message": "My voice isn't set up, so I'll answer on screen.", "retryable": False})
        while (seq := await to_speak.get()) is not None:
            if tts is None:
                continue
            sentence = turn.sentences[seq]
            try:
                async for chunk in tts.stream(sentence.text, language=voice):
                    turn.latency.setdefault("first_audio", ms())
                    sentence.audio_ms += len(chunk) / 2 / tts.sample_rate * 1000
                    turn.spoken = True
                    await self.send({"type": "reply.audio", "turn_id": turn.id, "seq": seq,
                                     "sample_rate": tts.sample_rate, "encoding": "pcm_s16le"}, chunk)
            except ProviderError as e:
                logger.warning("turn %s: no voice from here on: %s", turn.id, e)
                await self.send({"type": "error", "turn_id": turn.id, "code": "tts_unavailable",
                                 "message": "My voice isn't working right now, so I'll answer on screen.",
                                 "retryable": True})
                tts = None

    async def _error(self, turn: Turn, code: str, message: str) -> None:
        await self.send({"type": "error", "turn_id": turn.id, "code": code, "message": message, "retryable": True})

    def _save_reply(self, turn: Turn, heard: str, *, interrupted: bool) -> None:
        if turn.reply is None:
            return
        if turn.message_id is not None:
            message = self.db.get(Message, turn.message_id)
        else:
            message = Message(conversation_id=self.conversation.id, role="assistant", turn_id=turn.id,
                              language=turn.language, modality="voice")
            self.db.add(message)
        message.content = heard
        message.generated_content = turn.reply.text.strip()
        message.interrupted = interrupted
        message.latency = dict(turn.latency) or None
        message.tool_calls = list(turn.reply.tool_calls_used)
        self.db.commit()
        turn.message_id = message.id
