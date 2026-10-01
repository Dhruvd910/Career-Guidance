"""On-screen keyboard for the kiosk, which has a touchscreen but no physical keyboard.

It lives inside the main window, docked along the bottom, rather than being a separate
program like matchbox-keyboard: the kiosk X session runs no window manager, so a separate
keyboard window would have nothing keeping it on top or stopping it from taking focus away
from the box being typed into.

Tapping a text box shows it and types into that box; tapping anything that isn't a text box
hides it. None of its keys accept focus — otherwise every keypress would move focus off
the box it's typing into. The mic key dictates into the box through the same voice
pipeline MAYA uses, so every text field in the app can be filled by voice or by typing.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QDoubleValidator, QIntValidator, QKeyEvent
from PySide6.QtWidgets import (
    QAbstractSpinBox, QApplication, QFrame, QHBoxLayout, QLineEdit, QPlainTextEdit, QPushButton,
    QScrollArea, QSizePolicy, QSpinBox, QStackedWidget, QTextEdit, QVBoxLayout, QWidget,
)

from app.voice import IDLE, LISTENING, THINKING, Voice
from app.voice_parsing import clean_dictation, parse_number
from app.widgets.icons import mic_icon, stop_icon

BACKSPACE, ENTER, SHIFT, HIDE = "⌫", "↵", "⇧", "⌄"
SPACE, MIC, TO_SYMBOLS, TO_LETTERS = "space", "mic", "?123", "ABC"
SPECIAL_KEYS = {BACKSPACE, ENTER, SHIFT, HIDE, MIC, TO_SYMBOLS, TO_LETTERS}

LETTER_ROWS = [
    list("qwertyuiop") + [BACKSPACE],
    list("asdfghjkl") + ["'", ENTER],
    [SHIFT] + list("zxcvbnm") + [",", ".", "?"],
    [TO_SYMBOLS, MIC, SPACE, "-", HIDE],
]
SYMBOL_ROWS = [
    list("1234567890") + [BACKSPACE],
    ["@", "#", "&", "*", "(", ")", "/", ":", ";", ENTER],
    ["_", "+", "=", "%", '"', "!", "?", ",", "."],
    [TO_LETTERS, MIC, SPACE, "-", HIDE],
]
KEY_STRETCH = {BACKSPACE: 3, ENTER: 3, SHIFT: 3, TO_SYMBOLS: 3, TO_LETTERS: 3, MIC: 3, HIDE: 3, SPACE: 10}
KEY_HEIGHT = 42  # 4 rows fit in ~195px, leaving ~285px of the 480px panel for the page


def is_text_input(widget: QWidget | None) -> bool:
    if isinstance(widget, (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox)):
        return not widget.isReadOnly()
    return False


def _text_input_at(widget: QWidget | None) -> QWidget | None:
    # A press on a QTextEdit lands on its viewport, and on a spin box lands on its inner line
    # edit — walk up a couple of levels to find the actual input.
    for _ in range(3):
        if widget is None:
            return None
        if is_text_input(widget):
            return widget
        widget = widget.parentWidget()
    return None


def is_numeric_input(widget: QWidget | None) -> bool:
    if isinstance(widget, QAbstractSpinBox):
        return True
    return isinstance(widget, QLineEdit) and isinstance(widget.validator(), (QIntValidator, QDoubleValidator))


def _repolish(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class OnScreenKeyboard(QFrame):
    visibility_changed = Signal(bool)

    def __init__(self, voice: Voice, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Osk")
        self.voice = voice
        self._shift = False
        self._dictating = False
        self._letter_keys: list[tuple[QPushButton, str]] = []
        self._shift_keys: list[QPushButton] = []
        self._mic_keys: list[QPushButton] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        self.layers = QStackedWidget()
        self.layers.addWidget(self._build_layer(LETTER_ROWS))
        self.layers.addWidget(self._build_layer(SYMBOL_ROWS))
        layout.addWidget(self.layers)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        # Hiding the keyboard shifts the whole layout, so it waits for the finger to lift:
        # hiding on press would move a "Continue" button out from under the tap before the
        # release lands, and the click would never register.
        self._release_timer = QTimer(self)
        self._release_timer.setInterval(40)
        self._release_timer.timeout.connect(self._hide_if_released_away)

        self._typing_in: QWidget | None = None
        self._keep_in_view = QTimer(self)
        self._keep_in_view.setInterval(250)
        self._keep_in_view.timeout.connect(self._keep_target_visible)

        voice.state_changed.connect(self._on_voice_state)
        QApplication.instance().installEventFilter(self)
        self.hide()

    # ---------------- construction ----------------

    def _build_layer(self, rows: list[list[str]]) -> QWidget:
        page = QWidget()
        column = QVBoxLayout(page)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(5)
        for row in rows:
            line = QHBoxLayout()
            line.setSpacing(5)
            for key in row:
                line.addWidget(self._make_key(key), KEY_STRETCH.get(key, 2))
            column.addLayout(line)
        return page

    def _make_key(self, key: str) -> QPushButton:
        btn = QPushButton()
        btn.setObjectName("OskKey")
        btn.setFocusPolicy(Qt.NoFocus)
        btn.setFixedHeight(KEY_HEIGHT)
        btn.setMinimumWidth(10)
        btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        if key == MIC:
            btn.setIcon(mic_icon())
            btn.setIconSize(QSize(26, 26))
            self._mic_keys.append(btn)
        else:
            btn.setText(key)
        if key in SPECIAL_KEYS:
            btn.setProperty("special", "true")
        if len(key) == 1 and key.isalpha():
            self._letter_keys.append((btn, key))
        if key == SHIFT:
            self._shift_keys.append(btn)
        if key == BACKSPACE:
            btn.setAutoRepeat(True)
            btn.setAutoRepeatDelay(450)
            btn.setAutoRepeatInterval(70)
        btn.clicked.connect(lambda _checked=False, k=key: self._on_key(k))
        return btn

    # ---------------- showing / hiding ----------------

    def show_for(self, widget: QWidget) -> None:
        if not widget.isVisible():
            return
        self._release_timer.stop()
        if not self.isVisible():
            self.layers.setCurrentIndex(1 if is_numeric_input(widget) else 0)
            # Announced *before* showing: Qt lays out synchronously on show(), so anything that
            # makes room for the keyboard (the sidebar, MAYA's mascot column) has to be gone by
            # then — otherwise the window grows past the screen for a moment and never shrinks.
            self.visibility_changed.emit(True)
            QApplication.sendPostedEvents(None, QEvent.LayoutRequest)
            self.show()
        self._auto_shift()
        self._typing_in = widget
        QTimer.singleShot(80, lambda w=widget: self._scroll_into_view(w))
        # Content that arrives from the API a moment later (an exam profile, a prediction)
        # reflows the page and can push the box back under the keyboard, so keep watching
        # while someone is typing.
        self._keep_in_view.start()

    def hide_keyboard(self) -> None:
        self._release_timer.stop()
        self._keep_in_view.stop()
        self._typing_in = None
        if self._dictating:
            self._dictating = False
            self.voice.cancel()
        self._set_shift(False)
        was_visible = self.isVisible()
        self.hide()
        if was_visible:
            self.visibility_changed.emit(False)

    def _keep_target_visible(self) -> None:
        """Is the box being typed into still above the keyboard? If not, bring it back."""
        widget = self._typing_in
        if widget is None or not self.isVisible():
            self._keep_in_view.stop()
            return
        if not widget.isVisible():
            return
        window = self.window()
        bottom = widget.mapTo(window, widget.rect().bottomLeft()).y()
        top = widget.mapTo(window, widget.rect().topLeft()).y()
        keyboard_top = self.mapTo(window, self.rect().topLeft()).y()
        if bottom > keyboard_top or top < 0:
            self._scroll_into_view(widget)

    def _scroll_into_view(self, widget: QWidget) -> None:
        if not self.isVisible() or not widget.isVisible():
            return
        # Innermost first: a box inside a page's own scroll list, inside the window's per-page
        # scroll area, needs both scrolled before it's actually on screen.
        parent = widget.parentWidget()
        while parent is not None:
            if isinstance(parent, QScrollArea):
                # A generous vertical margin so the box lands clear of the keyboard's top edge
                # rather than flush against it.
                parent.ensureWidgetVisible(widget, 16, 56)
            parent = parent.parentWidget()

    def _hide_if_released_away(self) -> None:
        if QApplication.mouseButtons() != Qt.NoButton:
            return
        self._release_timer.stop()
        if not is_text_input(QApplication.focusWidget()):
            self.hide_keyboard()

    def eventFilter(self, obj, event) -> bool:
        if event.type() != QEvent.MouseButtonPress or not isinstance(obj, QWidget):
            return False
        if obj is self or self.isAncestorOf(obj) or obj.window() is not self.window():
            return False  # the keyboard's own keys, or a popup like a combo box's list

        text_input = _text_input_at(obj)
        if text_input is not None:
            # Tapping a text box means "I'll type this" — stop MAYA talking or listening.
            self._dictating = False
            self.voice.cancel()
            QTimer.singleShot(0, lambda w=text_input: self.show_for(w))
        elif self.isVisible():
            self._release_timer.start()
        return False

    # ---------------- typing ----------------

    def _target(self) -> QWidget | None:
        widget = QApplication.focusWidget()
        return widget if is_text_input(widget) else None

    def _send_key(self, key: Qt.Key, text: str = "") -> None:
        target = self._target()
        if target is None:
            return
        for kind in (QEvent.KeyPress, QEvent.KeyRelease):
            QApplication.sendEvent(target, QKeyEvent(kind, key, Qt.NoModifier, text))

    def _on_key(self, key: str) -> None:
        if key == BACKSPACE:
            self._send_key(Qt.Key_Backspace)
        elif key == ENTER:
            self._send_key(Qt.Key_Return)
            self.hide_keyboard()
            return
        elif key == SHIFT:
            self._set_shift(not self._shift)
            return
        elif key == TO_SYMBOLS:
            self.layers.setCurrentIndex(1)
            return
        elif key == TO_LETTERS:
            self.layers.setCurrentIndex(0)
            return
        elif key == HIDE:
            self.hide_keyboard()
            return
        elif key == MIC:
            self._toggle_dictation()
            return
        elif key == SPACE:
            self._send_key(Qt.Key_Space, " ")
        else:
            char = key.upper() if self._shift and key.isalpha() else key
            self._send_key(Qt.Key_unknown, char)
        self._auto_shift()

    def _set_shift(self, on: bool) -> None:
        self._shift = on
        for btn, char in self._letter_keys:
            btn.setText(char.upper() if on else char)
        for btn in self._shift_keys:
            btn.setProperty("active", "true" if on else "false")
            _repolish(btn)

    def _auto_shift(self) -> None:
        """Capitalize the first letter of a box and of each new sentence, like a phone."""
        target = self._target()
        if not isinstance(target, QLineEdit) or is_numeric_input(target):
            self._set_shift(False)
            return
        before_cursor = target.text()[:target.cursorPosition()]
        starts_sentence = before_cursor.strip() == "" or before_cursor.rstrip().endswith((".", "?", "!"))
        self._set_shift(starts_sentence and (before_cursor == "" or before_cursor.endswith(" ")))

    # ---------------- dictation ----------------

    def _toggle_dictation(self) -> None:
        if self._dictating:
            self._dictating = False
            self.voice.cancel()
            return
        target = self._target()
        if target is None:
            return
        self.voice.listen(
            on_answer=lambda transcript, w=target: self._insert_dictation(w, transcript),
            on_no_answer=lambda _reason: self._end_dictation(),
        )
        # Set after listen(): it cancels any previous voice flow first, and a missing mic
        # reports back synchronously — either would otherwise leave a stale "dictating" flag.
        self._dictating = self.voice.state == LISTENING
        self._refresh_mic()

    def _insert_dictation(self, widget: QWidget, transcript: str) -> None:
        self._end_dictation()
        if not widget.isVisible():
            return
        if isinstance(widget, QAbstractSpinBox):
            number = parse_number(transcript)
            if number is not None:
                widget.setValue(int(number) if isinstance(widget, QSpinBox) else number)
            return
        if is_numeric_input(widget):
            number = parse_number(transcript)
            if number is None:
                return
            text = str(int(number)) if float(number).is_integer() else str(number)
        else:
            text = clean_dictation(transcript)
        if isinstance(widget, QLineEdit):
            before_cursor = widget.text()[:widget.cursorPosition()]
            if before_cursor and not before_cursor.endswith(" "):
                text = " " + text
            widget.insert(text)
        elif isinstance(widget, (QTextEdit, QPlainTextEdit)):
            widget.insertPlainText(text)

    def _end_dictation(self) -> None:
        self._dictating = False
        self._refresh_mic()

    def _on_voice_state(self, state: str) -> None:
        if state == IDLE:
            self._dictating = False
        self._refresh_mic()

    def _refresh_mic(self) -> None:
        active = self._dictating and self.voice.state in (LISTENING, THINKING)
        for btn in self._mic_keys:
            btn.setIcon(stop_icon() if active else mic_icon())
            btn.setProperty("listening", "true" if active else "false")
            _repolish(btn)
