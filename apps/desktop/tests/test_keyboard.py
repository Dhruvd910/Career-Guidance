"""On-screen keyboard, driven by simulated taps through Qt's real event path (the same
MouseButtonPress/Release a touchscreen produces), not by calling its methods directly."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QObject, Qt, Signal  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QLineEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget  # noqa: E402

from app.widgets.keyboard import BACKSPACE, ENTER, HIDE, TO_LETTERS, OnScreenKeyboard  # noqa: E402


class FakeVoice(QObject):
    state_changed = Signal(str)

    def __init__(self):
        super().__init__()
        self.state = "idle"
        self.cancels = 0
        self._pending = None

    def _set(self, state):
        if state != self.state:
            self.state = state
            self.state_changed.emit(state)

    def cancel(self):
        self.cancels += 1
        self._pending = None
        self._set("idle")

    def listen(self, on_answer, on_no_answer=None):
        self.cancel()
        self._pending = (on_answer, on_no_answer)
        self._set("listening")

    def hear(self, transcript):
        on_answer, _ = self._pending
        self._pending = None
        self._set("idle")
        on_answer(transcript)


@pytest.fixture()
def ui(qapp):
    voice = FakeVoice()
    window = QWidget()
    layout = QVBoxLayout(window)
    name = QLineEdit()
    rank = QSpinBox()
    rank.setMaximum(10_000_000)
    button = QPushButton("Continue")
    submitted = []
    name.returnPressed.connect(lambda: submitted.append(name.text()))
    keyboard = OnScreenKeyboard(voice)
    for w in (name, rank, button, keyboard):
        layout.addWidget(w)
    window.resize(800, 480)
    window.show()
    window.activateWindow()
    QTest.qWaitForWindowActive(window)
    yield type("UI", (), dict(window=window, name=name, rank=rank, button=button,
                              keyboard=keyboard, voice=voice, submitted=submitted))
    keyboard.hide_keyboard()
    window.close()
    QApplication.instance().removeEventFilter(keyboard)


def settle(ms=60):
    QTest.qWait(ms)


def tap(widget):
    QTest.mouseClick(widget, Qt.LeftButton)
    settle()


def key(keyboard, label):
    """Tap the visible key with this label (case-insensitive for letters)."""
    page = keyboard.layers.currentWidget()
    for btn in page.findChildren(QPushButton, "OskKey"):
        if btn.text() == label or (len(label) == 1 and btn.text().lower() == label.lower()):
            tap(btn)
            return
    raise AssertionError(f"no key {label!r} on the current layer")


def mic_key(keyboard):
    page = keyboard.layers.currentWidget()
    return next(b for b in keyboard._mic_keys if page.isAncestorOf(b))


def test_tapping_a_text_box_shows_the_keyboard(ui):
    assert not ui.keyboard.isVisible()
    tap(ui.name)
    assert ui.keyboard.isVisible()
    assert ui.keyboard.layers.currentIndex() == 0  # letters


def test_typing_capitalizes_the_first_letter_and_keeps_focus_in_the_box(ui):
    tap(ui.name)
    for ch in "dhruv":
        key(ui.keyboard, ch)
    assert ui.name.text() == "Dhruv"
    assert QApplication.focusWidget() is ui.name  # keys never steal focus


def test_backspace_and_space(ui):
    tap(ui.name)
    for ch in "ab":
        key(ui.keyboard, ch)
    key(ui.keyboard, BACKSPACE)
    key(ui.keyboard, "space")
    key(ui.keyboard, "c")
    assert ui.name.text() == "A c"


def test_enter_submits_and_hides(ui):
    tap(ui.name)
    for ch in "hi":
        key(ui.keyboard, ch)
    key(ui.keyboard, ENTER)
    assert ui.submitted == ["Hi"]
    assert not ui.keyboard.isVisible()


def test_hide_key(ui):
    tap(ui.name)
    key(ui.keyboard, HIDE)
    assert not ui.keyboard.isVisible()


def test_tapping_the_box_again_after_hiding_brings_it_back(ui):
    tap(ui.name)
    key(ui.keyboard, HIDE)
    tap(ui.name)  # already focused, so no focus change — must still reopen
    assert ui.keyboard.isVisible()


def test_number_box_opens_on_the_number_layer(ui):
    tap(ui.rank)
    assert ui.keyboard.isVisible()
    assert ui.keyboard.layers.currentIndex() == 1
    ui.rank.lineEdit().selectAll()
    for digit in "45000":
        key(ui.keyboard, digit)
    assert ui.rank.value() == 45000


def test_switching_layers(ui):
    tap(ui.rank)
    key(ui.keyboard, TO_LETTERS)
    assert ui.keyboard.layers.currentIndex() == 0


def test_tapping_a_button_hides_the_keyboard_and_the_click_still_lands(ui):
    clicks = []
    ui.button.clicked.connect(lambda: clicks.append(1))
    tap(ui.name)
    assert ui.keyboard.isVisible()
    tap(ui.button)
    settle(150)
    assert clicks == [1]  # hiding waited for the release, so the button didn't move mid-tap
    assert not ui.keyboard.isVisible()


def test_tapping_a_text_box_stops_maya_talking_or_listening(ui):
    ui.voice.state = "speaking"
    before = ui.voice.cancels
    tap(ui.name)
    assert ui.voice.cancels > before


def test_mic_key_dictates_into_the_box_without_the_trailing_period(ui):
    tap(ui.name)
    tap(mic_key(ui.keyboard))
    assert ui.voice.state == "listening"
    assert mic_key(ui.keyboard).property("listening") == "true"
    ui.voice.hear("Maharashtra.")
    settle()
    assert ui.name.text() == "Maharashtra"
    assert mic_key(ui.keyboard).property("listening") == "false"


def test_dictation_appends_with_a_space(ui):
    tap(ui.name)
    for ch in "new":
        key(ui.keyboard, ch)
    tap(mic_key(ui.keyboard))
    ui.voice.hear("Delhi.")
    settle()
    assert ui.name.text() == "New Delhi"


def test_dictating_a_number_into_a_number_box(ui):
    tap(ui.rank)
    tap(mic_key(ui.keyboard))
    ui.voice.hear("My rank is 45,000.")
    settle()
    assert ui.rank.value() == 45000


def test_tapping_mic_again_stops_dictation(ui):
    tap(ui.name)
    tap(mic_key(ui.keyboard))
    assert ui.voice.state == "listening"
    tap(mic_key(ui.keyboard))
    assert ui.voice.state == "idle"
