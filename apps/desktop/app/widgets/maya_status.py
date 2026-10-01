from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QMovie
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from app.config import mascot_gif
from app.voice import IDLE, LISTENING, SPEAKING, THINKING, Voice

GIF_NAMES = {IDLE: "idle", LISTENING: "listen", THINKING: "think", SPEAKING: "talking"}
STATUS_TEXT = {
    IDLE: "",
    LISTENING: "Listening… go ahead",
    THINKING: "One moment…",
    SPEAKING: "Speaking…",
}


class MayaStatus(QWidget):
    """MAYA's mascot, animated to match what her voice is doing, with a one-line status.

    Animation only runs while the widget is visible: the source GIFs are 1600x960, and
    decoding them for pages that aren't on screen would waste the Pi's CPU and make touch
    input feel sluggish. hold() lets a page show a state the voice controller doesn't know
    about — e.g. "thinking" while a chat reply is on its way from the server.
    """

    def __init__(self, voice: Voice, size: QSize, show_text: bool = True, parent=None, portrait: bool = False):
        """portrait: MAYA cropped tight and standing tall (size should be ~222:320), as the
        redesigned screens show her beside their cards."""
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet("background: transparent;")
        self.voice = voice
        self._portrait = portrait
        self._size = size
        self._held: str | None = None
        self._shown_state: str | None = None
        self._movie: QMovie | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.mascot = QLabel()
        self.mascot.setFixedSize(size)
        self.mascot.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.mascot, alignment=Qt.AlignHCenter)

        self.text = QLabel("")
        self.text.setObjectName("MayaStatusText")
        self.text.setAlignment(Qt.AlignCenter)
        self.text.setVisible(show_text)
        layout.addWidget(self.text)

        voice.state_changed.connect(self._refresh)

    def hold(self, state: str | None) -> None:
        self._held = state
        self._refresh()

    def _current_state(self) -> str:
        if self.voice.state != IDLE:
            return self.voice.state
        return self._held or IDLE

    def _refresh(self, *_args) -> None:
        state = self._current_state()
        self.text.setText(STATUS_TEXT[state])
        if not self.isVisible() or state == self._shown_state:
            return
        self._play(state)

    def _play(self, state: str) -> None:
        old = self._movie
        movie = QMovie(str(mascot_gif(GIF_NAMES[state], portrait=self._portrait)))
        movie.setCacheMode(QMovie.CacheNone)
        movie.setScaledSize(self._size)
        self.mascot.setMovie(movie)
        movie.start()
        self._movie = movie
        self._shown_state = state
        if old is not None:
            old.stop()
            old.deleteLater()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._shown_state = None
        self._refresh()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        if self._movie is not None:
            self._movie.stop()
        self._shown_state = None
