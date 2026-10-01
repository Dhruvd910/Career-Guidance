"""Drag-to-scroll for the touchscreen.

The kiosk panel has no mouse wheel and no room for a fat scrollbar, so every scrollable area
scrolls by dragging anywhere inside it, like a phone.

Qt ships QScroller for this, but its mouse gesture swallows the press and replays it after
the release, at the position the finger was in — so a tap could land on the wrong widget (or
nowhere) whenever the page moved in between, which on this app happens constantly as the
keyboard opens and content arrives. This does the opposite: presses are never intercepted,
so taps behave exactly as they always did. A drag past a small threshold starts scrolling,
and the release that ends a drag is swallowed so the button under the finger doesn't fire.
"""

from PySide6.QtCore import QEvent, QObject, QPointF, Qt
from PySide6.QtWidgets import QAbstractScrollArea, QApplication, QWidget

# How far a finger has to move before it counts as a scroll rather than a tap. A resistive
# panel wobbles a few pixels while a finger settles.
DRAG_THRESHOLD_PX = 12


class DragScroller(QObject):
    """One application-wide filter; scroll areas register themselves with it."""

    def __init__(self):
        super().__init__()
        self._areas: list[QAbstractScrollArea] = []
        self._chain: list[QAbstractScrollArea] = []  # areas under the finger, innermost first
        self._area: QAbstractScrollArea | None = None  # the one being scrolled, once decided
        self._press_key: tuple | None = None
        self._start = QPointF()
        self._from_v = 0
        self._from_h = 0
        self._dragging = False

    def register(self, area: QAbstractScrollArea) -> None:
        if area not in self._areas:
            self._areas.append(area)
            area.destroyed.connect(lambda _obj=None, a=area: self._forget(a))

    def _forget(self, area) -> None:
        if area in self._areas:
            self._areas.remove(area)

    def _areas_under(self, widget: QWidget) -> list[QAbstractScrollArea]:
        """Every registered scroll area this widget sits in, innermost first."""
        viewports = {id(area.viewport()): area for area in self._areas}
        chain = []
        node = widget
        while node is not None:
            area = viewports.get(id(node))
            if area is not None:
                chain.append(area)
            node = node.parentWidget()
        return chain

    @staticmethod
    def _can_scroll(area: QAbstractScrollArea, vertical: bool) -> bool:
        bar = area.verticalScrollBar() if vertical else area.horizontalScrollBar()
        return bar.maximum() > bar.minimum()

    def _reset(self) -> None:
        self._chain = []
        self._area = None
        self._press_key = None
        self._dragging = False

    def eventFilter(self, obj, event) -> bool:
        kind = event.type()
        if kind == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            # A press nobody accepts is re-delivered to each parent in turn, and every one of
            # those passes through here. Only the first delivery — the widget actually under
            # the finger — starts a gesture; otherwise the outermost page would win and a
            # nested list (careers, the chat) would never scroll.
            key = (event.timestamp(), event.globalPosition().x(), event.globalPosition().y())
            if key != self._press_key and isinstance(obj, QWidget):
                self._reset()
                self._press_key = key
                self._chain = self._areas_under(obj)
                self._start = event.globalPosition()
            return False  # never swallow a press: a tap must reach whatever it landed on

        if kind == QEvent.MouseMove and self._chain and event.buttons() & Qt.LeftButton:
            delta = event.globalPosition() - self._start
            if not self._dragging:
                if max(abs(delta.x()), abs(delta.y())) < DRAG_THRESHOLD_PX:
                    return False
                # The innermost area that can actually move in the direction of the drag.
                vertical = abs(delta.y()) >= abs(delta.x())
                self._area = next((a for a in self._chain if self._can_scroll(a, vertical)), None)
                if self._area is None:
                    self._reset()
                    return False
                self._dragging = True
                self._start = event.globalPosition()
                self._from_v = self._area.verticalScrollBar().value()
                self._from_h = self._area.horizontalScrollBar().value()
                return True
            self._area.verticalScrollBar().setValue(int(self._from_v - delta.y()))
            self._area.horizontalScrollBar().setValue(int(self._from_h - delta.x()))
            return True

        if kind == QEvent.MouseButtonRelease and self._chain:
            dragged = self._dragging
            self._reset()
            # After a real drag, swallow the release so the widget under the finger isn't
            # treated as clicked.
            return dragged
        return False


_scroller: DragScroller | None = None


def _instance() -> DragScroller:
    global _scroller
    if _scroller is None:
        _scroller = DragScroller()
        QApplication.instance().installEventFilter(_scroller)
    return _scroller


def enable_touch_scrolling(root: QWidget) -> int:
    """Makes root and every scrollable area inside it drag-scrollable. Returns how many."""
    scroller = _instance()
    areas = root.findChildren(QAbstractScrollArea)
    if isinstance(root, QAbstractScrollArea):
        areas.append(root)
    count = 0
    for area in areas:
        if area.property("touch_scrolling"):
            continue
        area.setProperty("touch_scrolling", True)
        scroller.register(area)
        count += 1
    return count


def scroll_to_top(area: QAbstractScrollArea) -> None:
    area.verticalScrollBar().setValue(0)
    area.horizontalScrollBar().setValue(0)
