"""Dragging anywhere in a scrollable area scrolls it — the kiosk panel has no wheel."""

import time

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from app.widgets.touch import enable_touch_scrolling, scroll_to_top

EVENTS = {
    "press": QEvent.MouseButtonPress,
    "move": QEvent.MouseMove,
    "release": QEvent.MouseButtonRelease,
}


def pump(seconds: float) -> None:
    end = time.time() + seconds
    while time.time() < end:
        QApplication.processEvents()
        time.sleep(0.01)


def send(widget, kind: str, pos: QPoint) -> None:
    buttons = Qt.LeftButton if kind != "release" else Qt.NoButton
    QApplication.sendEvent(widget, QMouseEvent(
        EVENTS[kind], QPointF(pos), widget.mapToGlobal(QPointF(pos)), Qt.LeftButton, buttons, Qt.NoModifier,
    ))


def drag(viewport, start: tuple[int, int], dy: int, steps: int = 8) -> None:
    send(viewport, "press", QPoint(*start))
    pump(0.02)
    for i in range(1, steps + 1):
        send(viewport, "move", QPoint(start[0], start[1] + dy * i // steps))
        pump(0.02)
    send(viewport, "release", QPoint(start[0], start[1] + dy))
    pump(0.6)


def make_scroll_area(rows: int = 40) -> QScrollArea:
    area = QScrollArea()
    area.setWidgetResizable(True)
    content = QWidget()
    layout = QVBoxLayout(content)
    for i in range(rows):
        layout.addWidget(QLabel(f"row {i}"))
    area.setWidget(content)
    area.resize(300, 200)
    area.show()
    return area


def test_dragging_up_scrolls_down(qapp):
    area = make_scroll_area()
    enable_touch_scrolling(area)
    pump(0.1)
    assert area.verticalScrollBar().maximum() > 0, "test needs content taller than the viewport"

    drag(area.viewport(), (150, 150), -100)
    assert area.verticalScrollBar().value() > 0
    area.deleteLater()


def test_a_tap_still_reaches_the_widget_under_it(qapp):
    area = make_scroll_area()
    clicks = []
    button = QPushButton("tap me")
    button.clicked.connect(lambda: clicks.append(1))
    area.widget().layout().insertWidget(0, button)
    enable_touch_scrolling(area)
    pump(0.1)

    send(button, "press", QPoint(20, 10))
    pump(0.08)
    send(button, "release", QPoint(20, 10))
    pump(0.2)
    assert clicks == [1], "a tap inside a scrollable page must still press the button"
    area.deleteLater()


def test_a_drag_over_a_button_scrolls_without_clicking_it(qapp):
    area = make_scroll_area()
    clicks = []
    button = QPushButton("do not press")
    button.clicked.connect(lambda: clicks.append(1))
    area.widget().layout().insertWidget(0, button)
    enable_touch_scrolling(area)
    pump(0.1)

    send(button, "press", QPoint(20, 10))
    pump(0.05)
    for dy in range(10, 90, 10):  # the finger slides up the page
        send(button, "move", QPoint(20, 10 - dy))
        pump(0.02)
    send(button, "release", QPoint(20, -80))
    pump(0.2)
    assert clicks == [], "dragging is scrolling, not clicking"
    assert area.verticalScrollBar().value() > 0
    area.deleteLater()


def test_a_tap_does_not_scroll(qapp):
    area = make_scroll_area()
    enable_touch_scrolling(area)
    pump(0.1)

    send(area.viewport(), "press", QPoint(150, 150))
    pump(0.05)
    send(area.viewport(), "release", QPoint(150, 152))  # a finger wobbles a couple of pixels
    pump(0.4)
    assert area.verticalScrollBar().value() == 0
    area.deleteLater()


def test_scroll_to_top_resets_a_scrolled_page(qapp):
    area = make_scroll_area()
    enable_touch_scrolling(area)
    pump(0.1)
    drag(area.viewport(), (150, 150), -120)
    assert area.verticalScrollBar().value() > 0

    scroll_to_top(area)
    pump(0.1)
    assert area.verticalScrollBar().value() == 0
    area.deleteLater()


def test_setting_it_up_twice_keeps_one_gesture(qapp):
    area = make_scroll_area()
    assert enable_touch_scrolling(area) == 1
    assert enable_touch_scrolling(area) == 0
    area.deleteLater()


def test_a_list_inside_a_scrolling_page_scrolls_when_dragged_on_plain_text(qapp):
    """The careers page: a scrolling list inside the window's scrolling page. A press on a
    label isn't accepted by anything, so it bubbles up through every parent — the inner list
    must still be the one that scrolls."""
    outer = QScrollArea()
    outer.setWidgetResizable(True)
    page = QWidget()
    page_layout = QVBoxLayout(page)
    inner = make_scroll_area(rows=60)
    inner.setParent(None)
    page_layout.addWidget(inner)
    outer.setWidget(page)
    outer.resize(300, 250)
    outer.show()
    enable_touch_scrolling(outer)
    pump(0.1)
    assert inner.verticalScrollBar().maximum() > 0
    assert outer.verticalScrollBar().maximum() == 0, "only the inner list overflows"

    label = inner.widget().findChildren(QLabel)[2]
    drag(label, (20, 10), -100)
    assert inner.verticalScrollBar().value() > 0
    outer.deleteLater()
