"""Pieces of the redesign that appear on several screens: MAYA's logo, the segmented
progress bar, the date/time, and the handwritten touches ("Explore · Learn · Grow")."""

from datetime import datetime

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from app.theme import HAND_FONT, PRIMARY
from app.widgets.icons import maya_face_icon


class Logo(QWidget):
    """MAYA's face, her name, and "Your Career Guide". Tapping it goes home."""

    clicked = Signal()

    def __init__(self, face: int = 34, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        icon = QLabel()
        icon.setPixmap(maya_face_icon(face).pixmap(QSize(face, face)))
        row.addWidget(icon)
        words = QVBoxLayout()
        words.setSpacing(0)
        name = QLabel("MAYA")
        name.setStyleSheet(f"font-size:{int(face * 0.5)}px; font-weight:800; color:{PRIMARY}; background:transparent;")
        tag = QLabel("Your Career Guide")
        tag.setStyleSheet("font-size:8px; color:#5f6f8f; background:transparent;")
        words.addWidget(name)
        words.addWidget(tag)
        row.addLayout(words)
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, event) -> None:
        self.clicked.emit()
        super().mousePressEvent(event)


class SegmentBar(QWidget):
    """The design's progress: a row of rounded segments, `filled` of them blue."""

    def __init__(self, segments: int = 6, parent=None):
        super().__init__(parent)
        self.segments, self.filled = segments, 0
        self.setFixedSize(120, 8)

    def set_progress(self, filled: int, segments: int) -> None:
        self.filled, self.segments = filled, max(1, segments)
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        gap = 3.0
        w = (self.width() - gap * (self.segments - 1)) / self.segments
        for i in range(self.segments):
            painter.setPen(Qt.NoPen if i < self.filled else QPen(QColor("#b9cdf3"), 1))
            painter.setBrush(QColor(PRIMARY) if i < self.filled else QColor("#ffffff"))
            painter.drawRoundedRect(QRectF(i * (w + gap) + 0.5, 0.5, w - 1, self.height() - 1), 3.5, 3.5)


class StepProgress(QWidget):
    """"1/6" (or "Almost done", "Ready!") above the segment bar, right-aligned in the top bar."""

    def __init__(self, parent=None):
        super().__init__(parent)
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(3)
        self.text = QLabel("")
        self.text.setObjectName("ProgressText")
        self.text.setAlignment(Qt.AlignCenter)
        self.bar = SegmentBar()
        col.addWidget(self.text, alignment=Qt.AlignHCenter)
        col.addWidget(self.bar)

    def set_progress(self, text: str, filled: int, segments: int) -> None:
        self.text.setText(text)
        self.bar.set_progress(filled, segments)


class Clock(QLabel):
    """ "Fri, 19 Sep 2026 / 09:45 AM", as in the top corner of the design."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Clock")
        self.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(15_000)
        self._tick()

    def _tick(self) -> None:
        now = datetime.now()
        # AM/PM by hand: the locale spells it "pm".
        self.setText(f"{now:%a, %d %b %Y}\n{now:%I:%M} {'AM' if now.hour < 12 else 'PM'}")


class HandText(QWidget):
    """Handwritten (Caveat) lines, tilted a little — "Explore / Learn / Grow"."""

    def __init__(self, lines: list[str], size: int = 22, angle: float = -12, color: str = "#3b5bdb",
                 underline: bool = False, parent=None):
        super().__init__(parent)
        self.lines, self.angle, self.color, self.underline = lines, angle, color, underline
        self.font_ = QFont(HAND_FONT)
        self.font_.setPixelSize(size)
        self.font_.setWeight(QFont.Medium)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setFixedSize(int(size * 5.2), int(size * (len(lines) + 1.2)))

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setFont(self.font_)
        painter.setPen(QColor(self.color))
        painter.translate(self.width() / 2, self.height() / 2)
        painter.rotate(self.angle)
        step = self.font_.pixelSize() * 0.95
        top = -step * len(self.lines) / 2
        for i, line in enumerate(self.lines):
            painter.drawText(QRectF(-self.width() / 2, top + i * step, self.width(), step),
                             Qt.AlignCenter, line)
        if self.underline:
            y = top + len(self.lines) * step + 2
            path = QPainterPath(QPointF(-self.width() * 0.32, y))
            path.cubicTo(QPointF(-self.width() * 0.1, y - 4), QPointF(self.width() * 0.15, y + 3),
                         QPointF(self.width() * 0.36, y - 6))
            painter.setPen(QPen(QColor(self.color), 2, Qt.SolidLine, Qt.RoundCap))
            painter.drawPath(path)


class Summit(QWidget):
    """The bottom-right corner of the welcome screen: pale mountains, a flag on the top,
    and "A Brighter Tomorrow" written up the slope."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(170, 110)
        self.font_ = QFont(HAND_FONT)
        self.font_.setPixelSize(19)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        back = QPainterPath(QPointF(20, h))
        back.lineTo(w * 0.78, 18)
        back.lineTo(w, h * 0.45)
        back.lineTo(w, h)
        back.closeSubpath()
        p.fillPath(back, QColor("#c9dcfb"))
        front = QPainterPath(QPointF(w * 0.35, h))
        front.lineTo(w * 0.8, h * 0.42)
        front.lineTo(w, h * 0.62)
        front.lineTo(w, h)
        front.closeSubpath()
        p.fillPath(front, QColor("#a9c5f7"))
        p.setPen(QPen(QColor("#1e3a8a"), 1.6))
        p.drawLine(QPointF(w * 0.78, 18), QPointF(w * 0.78, 2))
        flag = QPainterPath(QPointF(w * 0.78, 2))
        flag.lineTo(w * 0.78 + 14, 6)
        flag.lineTo(w * 0.78, 10)
        flag.closeSubpath()
        p.fillPath(flag, QColor(PRIMARY))
        p.setFont(self.font_)
        p.setPen(QColor("#1e3a8a"))
        p.translate(8, h - 16)
        p.rotate(-24)
        p.drawText(QPointF(0, 0), "A Brighter")
        p.drawText(QPointF(14, 20), "Tomorrow")
