import logging
import time
import uuid

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QLineEdit, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from app.api_client import ApiError, api_client
from app.config import PORTRAIT_RATIO
from app.conversation_client import ConversationClient
from app.theme import CARD_BORDER, FOREGROUND, PRIMARY
from app.pages.base import BasePage
from app.voice import LISTENING, THINKING
from app.widgets.common import error_label, heading, primary_button, set_error, subtitle
from app.widgets.icons import mic_icon, stop_icon
from app.widgets.maya_status import MayaStatus
from app.workers import run_async

logger = logging.getLogger(__name__)

# The kiosk panel is only 800x480, where a 420px-wide mascot plus a 460px side panel
# overflows the screen before the chat column even gets a say. Scale both down on small
# displays rather than letting the layout force a window bigger than the screen.
MASCOT_SIZE = QSize(int(300 * PORTRAIT_RATIO), 300)
MASCOT_SIZE_COMPACT = QSize(int(130 * PORTRAIT_RATIO), 130)
COMPACT_SCREEN_WIDTH = 1000


class ChatBubble(QLabel):
    def __init__(self, role: str, text: str):
        super().__init__(text)
        self.setWordWrap(True)
        self.setMaximumWidth(420)
        self.setTextInteractionFlags(Qt.TextSelectableByMouse)
        if role == "user":
            self.setStyleSheet(f"background:{PRIMARY}; color:white; border-radius:12px; padding:8px 12px;")
        else:
            self.setStyleSheet(f"background:white; color:{FOREGROUND}; border:1px solid {CARD_BORDER};"
                               " border-radius:12px; padding:8px 12px;")


class MayaPage(BasePage):
    def __init__(self, ctx):
        super().__init__(ctx)
        self.voice = ctx.voice
        self.conversation_id: int | None = None
        self._request_id = 0  # newest chat request; older replies are shown but never spoken
        self._mic_session = False  # the current listen was started from this page's mic button
        # The language the student last spoke or typed ("en"/"hi"/"hinglish"), as the server
        # judged it, so MAYA's own short prompts ("Yes? How can I help?") follow it too.
        self.language = "en"

        # The live conversation: replies streamed and spoken sentence by sentence. Until it's
        # connected (or if it can't be), questions go the older way, one whole reply at a time.
        self.client = ConversationClient(lambda: api_client.token)
        self.client.message.connect(self._on_live_message)
        self.client.audio.connect(self._on_live_audio)
        self.voice.stream_stopped.connect(self._on_stream_stopped)
        self.voice.stream_sentence_played.connect(self._on_sentence_played)
        self.voice.barge_in.connect(self._on_barge_in)
        self._turn: str | None = None  # the live turn being answered
        self._turn_sent_at, self._turn_heard_at = 0.0, None
        self._turn_by_voice = False
        self._turn_bubble: ChatBubble | None = None
        self._follow_up = False  # listening for the answer to a question MAYA just asked

        compact = QApplication.primaryScreen().availableGeometry().width() < COMPACT_SCREEN_WIDTH
        mascot_size = MASCOT_SIZE_COMPACT if compact else MASCOT_SIZE

        outer = QVBoxLayout(self) if compact else QHBoxLayout(self)
        outer.setContentsMargins(*((16, 12, 16, 12) if compact else (28, 28, 28, 28)))
        outer.setSpacing(12 if compact else 20)

        # ---- MAYA herself: a column beside the chat, or a band above it on a small panel ----
        titles = QVBoxLayout()
        titles.setAlignment(Qt.AlignVCenter if compact else (Qt.AlignTop | Qt.AlignHCenter))
        titles.addWidget(heading("MAYA"))
        titles.addWidget(subtitle("Your AI career counsellor"))

        self.status = MayaStatus(self.voice, mascot_size, portrait=True)

        self.mic_btn = primary_button("  Speak")
        self.mic_btn.setIcon(mic_icon("#ffffff"))
        self.mic_btn.setIconSize(QSize(22, 22))
        self.mic_btn.clicked.connect(self._toggle_listening)

        self.not_configured_label = error_label()

        if compact:
            # Two columns don't fit 800x480: the chat ends up too narrow to read or type in.
            # So MAYA sits in a band across the top, and the chat gets the full width.
            titles.addWidget(self.mic_btn)
            titles_widget = QWidget()
            titles_widget.setLayout(titles)
            band = QHBoxLayout()
            band.setSpacing(12)
            band.addWidget(self.status)
            band.addWidget(titles_widget, stretch=1)
            left_widget = QWidget()
            left_widget.setLayout(band)
        else:
            left = QVBoxLayout()
            left.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
            left.addLayout(titles)
            left.addWidget(self.status)
            left.addWidget(self.mic_btn)
            left.addWidget(self.not_configured_label)
            left_widget = QWidget()
            left_widget.setLayout(left)
            left_widget.setFixedWidth(mascot_size.width() + 40)
        outer.addWidget(left_widget)
        if compact:
            # 480px minus the keyboard leaves ~285px — not enough for the mascot band too, so
            # it steps aside while typing and the chat gets the room.
            ctx.keyboard.visibility_changed.connect(lambda shown: left_widget.setVisible(not shown))

        # ---- the conversation ----
        right = QVBoxLayout()
        right.setSpacing(8)
        if compact:
            right.addWidget(self.not_configured_label)  # the mascot band has no room for it
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        # The transcript stretches into whatever room is left instead of asking for a height of
        # its own: otherwise a long conversation makes the page taller than the panel, and the
        # window's own scroll area pushes the text box off the bottom of the screen.
        self.scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Ignored)
        self.messages_container = QWidget()
        self.messages_layout = QVBoxLayout(self.messages_container)
        self.messages_layout.setAlignment(Qt.AlignTop)
        self.scroll.setWidget(self.messages_container)
        self.scroll.verticalScrollBar().rangeChanged.connect(lambda _min, mx: self.scroll.verticalScrollBar().setValue(mx))
        right.addWidget(self.scroll, stretch=1)

        input_row = QHBoxLayout()
        self.text_input = QLineEdit()
        self.text_input.setPlaceholderText("Ask about a career, exam, or college…")
        self.text_input.returnPressed.connect(self._send_text)
        input_row.addWidget(self.text_input)
        self.send_btn = primary_button("Send")
        self.send_btn.clicked.connect(self._send_text)
        input_row.addWidget(self.send_btn)
        input_row_widget = QWidget()
        input_row_widget.setLayout(input_row)
        right.addWidget(input_row_widget)

        right_widget = QWidget()
        right_widget.setLayout(right)
        right_widget.setMinimumHeight(140)  # the chat keeps room to read even beside the keyboard
        outer.addWidget(right_widget, stretch=1)

        self.voice.state_changed.connect(self._refresh_mic_button)
        self._add_bubble(
            "assistant",
            "Hi! I'm MAYA, your AI career counsellor. Ask me about careers, JEE/NEET, or any "
            "college — by voice or by typing, in English or Hindi. I'll only use real data from "
            "our database, and I'll say so if something isn't available yet.",
        )

    def on_show(self, wake: bool = False, greet: bool = True, ask: str | None = None, **kwargs) -> None:
        set_error(self.not_configured_label, None)
        self.client.open()
        if ask:
            # Another screen's "Ask MAYA about it": the question goes straight in.
            self.text_input.setText(ask)
            self._send_text()
        elif wake:
            self.wake(greet=greet)

    def wake(self, greet: bool = True) -> None:
        """Someone tapped MAYA's wake button or said "Hey Maya": answer, then listen. After
        an interruption she skips the "Yes?" — they're already talking."""
        set_error(self.not_configured_label, None)
        self._mic_session = False
        if greet:
            prompt = "Yes? How can I help?" if self.language == "en" else "हाँ? बताइए, मैं कैसे मदद करूँ?"
            self.voice.say(prompt, on_done=self._listen_after_wake)
        else:
            self.voice.cancel()
            self._listen_after_wake()

    def _listen_after_wake(self) -> None:
        if self.isVisible() and not self.ctx.keyboard.isVisible():
            self._toggle_listening()

    # ---------------- transcript ----------------

    def _add_bubble(self, role: str, text: str) -> ChatBubble:
        row = QHBoxLayout()
        bubble = ChatBubble(role, text)
        if role == "user":
            row.addStretch(1)
            row.addWidget(bubble)
        else:
            row.addWidget(bubble)
            row.addStretch(1)
        row_widget = QWidget()
        row_widget.setLayout(row)
        self.messages_layout.addWidget(row_widget)
        return bubble

    def _begin_request(self) -> int:
        self._request_id += 1
        self.status.hold(THINKING)
        self.send_btn.setEnabled(False)
        return self._request_id

    def _end_request(self, request_id: int) -> bool:
        """Returns True if this reply is still the one the person is waiting on."""
        if request_id != self._request_id:
            return False
        self.status.hold(None)
        self.send_btn.setEnabled(True)
        return True

    def _should_speak(self, request_id: int) -> bool:
        # Don't talk over someone who has started typing, or from a page they've left.
        return request_id == self._request_id and self.isVisible() and not self.ctx.keyboard.isVisible()

    # ---------------- typed questions ----------------

    def _send_text(self) -> None:
        text = self.text_input.text().strip()
        if not text:
            return
        self.text_input.clear()
        self._add_bubble("user", text)
        if self._start_live_turn(by_voice=False, send=lambda turn_id: self.client.send_text_turn(turn_id, text)):
            return
        request_id = self._begin_request()
        run_async(
            api_client.chat, text, self.conversation_id,
            on_success=lambda r: self._on_chat_reply(request_id, r),
            on_error=lambda e: self._on_error(request_id, e),
        )

    def _on_chat_reply(self, request_id: int, response: dict) -> None:
        self.conversation_id = response["conversation_id"]
        current = self._end_request(request_id)
        if not response.get("ai_configured", True):
            set_error(self.not_configured_label, response["reply"])
            return
        self.language = response.get("language") or "en"
        self._add_bubble("assistant", response["reply"])
        if current and self._should_speak(request_id):
            self.voice.say(response["reply"], language=self.language)

    # ---------------- spoken questions ----------------

    def _toggle_listening(self) -> None:
        if self._mic_session and self.voice.state in (LISTENING, THINKING):
            self._mic_session = False
            self.voice.cancel()
            return
        set_error(self.not_configured_label, None)
        self.voice.listen_for_audio(on_audio=self._send_voice, on_no_answer=self._on_no_voice)
        self._mic_session = self.voice.state == LISTENING
        self._refresh_mic_button()

    def _send_voice(self, wav_bytes: bytes, over: str | None = None) -> None:
        self._mic_session = False
        self._follow_up = False
        if self._start_live_turn(by_voice=True,
                                 send=lambda turn_id: self.client.send_audio_turn(turn_id, wav_bytes, over)):
            return
        request_id = self._begin_request()
        run_async(
            api_client.voice_chat, wav_bytes, self.conversation_id,
            on_success=lambda r: self._on_voice_reply(request_id, r),
            on_error=lambda e: self._on_error(request_id, e),
        )

    def _on_voice_reply(self, request_id: int, response: dict) -> None:
        self.conversation_id = response["conversation_id"]
        current = self._end_request(request_id)
        if not response.get("ai_configured", True):
            set_error(self.not_configured_label, response["reply"])
            return
        self.language = response.get("language") or "en"
        self._add_bubble("user", response.get("transcript") or "(voice message)")
        self._add_bubble("assistant", response["reply"])
        if current and self._should_speak(request_id) and response.get("audio_base64"):
            self.voice.play_audio(response["audio_base64"])

    def _on_no_voice(self, reason: str) -> None:
        self._mic_session = False
        self._refresh_mic_button()
        follow_up, self._follow_up = self._follow_up, False
        if follow_up and reason in ("silence", "unclear"):
            return  # no answer to her question is an answer too; tap Speak to carry on
        if reason == "no_mic":
            set_error(self.not_configured_label, "No microphone detected. You can still type your questions.")
        elif reason == "silence":
            set_error(self.not_configured_label, "I didn't hear anything — tap Speak and try again.")
        elif reason == "unclear":
            set_error(self.not_configured_label, "Sorry, I didn't catch that. Tap Speak to try again.")
        else:
            set_error(self.not_configured_label, "Voice input isn't working right now. You can still type.")

    def _on_error(self, request_id: int, err: Exception) -> None:
        self._end_request(request_id)
        message = err.message if isinstance(err, ApiError) else "Could not reach the AI assistant."
        self._add_bubble("assistant", f"⚠ {message}")

    def _refresh_mic_button(self, *_args) -> None:
        listening = self._mic_session and self.voice.state in (LISTENING, THINKING)
        if not listening:
            self._mic_session = False
        self.mic_btn.setIcon(stop_icon() if listening else mic_icon("#ffffff"))
        self.mic_btn.setText("  Stop" if listening else "  Speak")

    # ---------------- the live conversation ----------------

    def _start_live_turn(self, by_voice: bool, send) -> bool:
        """Sends a turn over the live connection; False if it isn't connected (the caller then
        asks the older way)."""
        if not self.client.ready:
            return False
        turn_id = uuid.uuid4().hex
        self.voice.begin_stream(turn_id)  # stops anything she was saying, and tells the server
        if not send(turn_id):
            self.voice.cancel()
            return False
        self._turn, self._turn_by_voice, self._turn_bubble = turn_id, by_voice, None
        # For the one latency the student feels: end of their speech (or Send) to MAYA's first sound.
        self._turn_sent_at, self._turn_heard_at = time.monotonic(), None
        set_error(self.not_configured_label, None)
        return True

    def _on_live_message(self, message: dict) -> None:
        if self._turn is None or message.get("turn_id") != self._turn:
            return  # an earlier turn, already cut short
        kind = message["type"]
        if kind == "turn.transcript":
            self.language = message.get("language") or self.language
            if self._turn_by_voice:
                self._add_bubble("user", message["text"])
        elif kind == "reply.delta":
            self.voice.stream_text(self._turn, message["text"])
            if self._turn_bubble is None:
                self._turn_bubble = self._add_bubble("assistant", message["text"])
            else:
                self._turn_bubble.setText(f"{self._turn_bubble.text()} {message['text']}")
        elif kind == "reply.done":
            turn, self._turn = self._turn, None
            self.language = message.get("language") or self.language
            # Asked something by voice and answered with a question: listen for the answer.
            asks = self._turn_by_voice and message.get("text", "").rstrip().endswith("?")
            self.voice.end_stream(turn, on_done=self._listen_for_answer if asks else None)
        elif kind == "turn.no_speech":
            turn, self._turn = self._turn, None
            self.voice.end_stream(turn)
            self._on_no_voice("unclear")
        elif kind == "turn.echo":
            # The "interruption" was her own voice getting past the echo canceller.
            turn, self._turn = self._turn, None
            self.voice.end_stream(turn)
            self.voice.note_echo()
        elif kind == "error":
            if message.get("code") == "tts_unavailable":
                set_error(self.not_configured_label, message.get("message"))  # the words still come
                return
            turn, self._turn = self._turn, None
            self.voice.end_stream(turn)
            self._add_bubble("assistant", f"⚠ {message.get('message') or 'Something went wrong.'}")

    def _on_live_audio(self, header: dict, pcm: bytes) -> None:
        if header.get("turn_id") == self._turn:
            if self._turn_heard_at is None:
                self._turn_heard_at = time.monotonic()
                logger.info("turn %s (%s): first audio %.0f ms after the question was sent", self._turn,
                            "voice" if self._turn_by_voice else "text", (self._turn_heard_at - self._turn_sent_at) * 1000)
            self.voice.stream_audio(self._turn, int(header["seq"]), int(header["sample_rate"]), pcm)

    def _on_sentence_played(self, turn_id: str, seq: int) -> None:
        self.client.send({"type": "playback.ack", "turn_id": turn_id, "seq": seq})

    def _on_stream_stopped(self, turn_id: str, seq: int, played_ms: float) -> None:
        """She was cut off — by "Stop Maya", a tap, a new question, leaving the page: the server
        keeps only what was heard."""
        self.client.send({"type": "turn.interrupt", "turn_id": turn_id, "seq": seq, "played_ms": played_ms})
        if turn_id == self._turn:
            self._turn = None

    def _on_barge_in(self, wav: bytes, over: str) -> None:
        """The student talked over MAYA: what they said is the next question."""
        if self.isVisible():
            self._send_voice(wav, over=over)

    def _listen_for_answer(self) -> None:
        if self.isVisible() and not self.ctx.keyboard.isVisible():
            self._follow_up = True
            self._toggle_listening()
