"""MAYA's live line to the server's conversation socket (WS /api/ws/conversation).

A turn goes up as one utterance (or typed text); the reply comes back as it is made —
sentences for the screen, then speech for each, chunk by chunk — and an interruption goes up
the moment it happens. The protocol is in docs/design/07-api-contracts.md §2.

Built on Qt's own QWebSocket, so everything arrives as signals on the UI thread with no extra
threads. The token goes in a header, not the URL, so it never lands in the server's access log.
If the server restarts, the client reconnects on its own and resumes the same session.
"""

from __future__ import annotations

import json
from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QNetworkRequest
from PySide6.QtWebSockets import QWebSocket

from app.config import API_BASE_URL

WS_PATH = "/api/ws/conversation"
RECONNECT_DELAYS_MS = (1_000, 2_000, 5_000, 10_000, 30_000)


class ConversationClient(QObject):
    message = Signal(dict)  # every server message except reply.audio
    audio = Signal(dict, bytes)  # a reply.audio header and the PCM it announced
    ready_changed = Signal(bool)  # the session is ready to take turns / the connection is gone

    def __init__(self, token: Callable[[], str | None], base_url: str = API_BASE_URL, socket: QWebSocket | None = None):
        super().__init__()
        self._token = token
        self._url = base_url.replace("http", "ws", 1) + WS_PATH
        self._ws = socket or QWebSocket()
        self._ws.textMessageReceived.connect(self._on_text)
        self._ws.binaryMessageReceived.connect(self._on_binary)
        self._ws.disconnected.connect(self._on_disconnected)
        self.session_id: int | None = None
        self.ready = False
        self._wanted = False
        self._attempt = 0
        self._audio_header: dict | None = None
        self._retry = QTimer(self)
        self._retry.setSingleShot(True)
        self._retry.timeout.connect(self._connect)

    # ---------------- connection ----------------

    def open(self) -> None:
        """Connect (once logged in), and keep reconnecting until close()."""
        self._wanted = True
        if not self.ready and not self._retry.isActive():
            self._connect()

    def close(self) -> None:
        self._wanted = False
        self._retry.stop()
        self._ws.close()

    def _connect(self) -> None:
        token = self._token()
        if not token:
            return
        url = QUrl(self._url + (f"?session_id={self.session_id}" if self.session_id else ""))
        request = QNetworkRequest(url)
        request.setRawHeader(b"Authorization", f"Bearer {token}".encode())
        self._ws.open(request)

    def _on_disconnected(self) -> None:
        was_ready, self.ready, self._audio_header = self.ready, False, None
        if was_ready:
            self.ready_changed.emit(False)
        if self._wanted:
            delay = RECONNECT_DELAYS_MS[min(self._attempt, len(RECONNECT_DELAYS_MS) - 1)]
            self._attempt += 1
            self._retry.start(delay)

    # ---------------- sending ----------------

    def send(self, message: dict) -> bool:
        if not self.ready:
            return False
        self._ws.sendTextMessage(json.dumps(message))
        return True

    def send_text_turn(self, turn_id: str, text: str) -> bool:
        return self.send({"type": "turn.text", "turn_id": turn_id, "text": text})

    def send_audio_turn(self, turn_id: str, wav: bytes) -> bool:
        if not self.send({"type": "turn.audio", "turn_id": turn_id, "encoding": "wav"}):
            return False
        self._ws.sendBinaryMessage(wav)  # always straight after its header
        return True

    # ---------------- receiving ----------------

    def _on_text(self, text: str) -> None:
        try:
            message = json.loads(text)
        except ValueError:
            return
        kind = message.get("type")
        if kind == "session.ready":
            self.session_id, self.ready, self._attempt = message.get("session_id"), True, 0
            self.ready_changed.emit(True)
        elif kind == "reply.audio":
            self._audio_header = message  # its PCM is the next binary frame
        else:
            self.message.emit(message)

    def _on_binary(self, data) -> None:
        header, self._audio_header = self._audio_header, None
        if header is not None:
            self.audio.emit(header, bytes(data))
