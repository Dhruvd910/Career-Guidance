"""Icons drawn with QPainter. The Pi has no emoji font, so glyphs like 🎤 render as empty
boxes — anything that isn't covered by DejaVu Sans gets drawn here instead."""

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QImageReader, QPainter, QPen, QPixmap

from app.config import MAYA_ASSETS_DIR


def mic_icon(color: str = "#0f172a", size: int = 64) -> QIcon:
    s = float(size)
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    c = QColor(color)

    painter.setPen(Qt.NoPen)
    painter.setBrush(c)
    painter.drawRoundedRect(QRectF(s * 0.36, s * 0.08, s * 0.28, s * 0.48), s * 0.14, s * 0.14)

    pen = QPen(c, s * 0.075)
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    painter.drawArc(QRectF(s * 0.24, s * 0.22, s * 0.52, s * 0.46), 180 * 16, 180 * 16)
    painter.drawLine(QPointF(s * 0.5, s * 0.68), QPointF(s * 0.5, s * 0.83))
    painter.drawLine(QPointF(s * 0.36, s * 0.86), QPointF(s * 0.64, s * 0.86))
    painter.end()
    return QIcon(pixmap)


def stop_icon(color: str = "#ffffff", size: int = 64) -> QIcon:
    s = float(size)
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(color))
    painter.drawRoundedRect(QRectF(s * 0.28, s * 0.28, s * 0.44, s * 0.44), s * 0.08, s * 0.08)
    painter.end()
    return QIcon(pixmap)


_maya_face_cache: dict[int, QPixmap] = {}


def maya_face_icon(size: int = 40) -> QIcon:
    """MAYA's face, cropped from the first frame of her idle animation — the wake button."""
    if size not in _maya_face_cache:
        frame = QImageReader(str(MAYA_ASSETS_DIR / "idle.gif")).read()
        face = frame.copy(QRect(590, 50, 440, 440)).scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        _maya_face_cache[size] = QPixmap.fromImage(face)
    return QIcon(_maya_face_cache[size])
