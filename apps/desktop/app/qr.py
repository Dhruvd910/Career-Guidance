"""QR codes for links, so a student can open a resource on their phone — the kiosk itself
has no web browser."""

from __future__ import annotations

import segno
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap


def qr_pixmap(url: str, size: int = 200) -> QPixmap:
    """A crisp QR code, `size` pixels square, with the quiet zone scanners need."""
    code = segno.make(url, error="m", micro=False)
    matrix = list(code.matrix_iter(scale=1, border=4))
    modules = len(matrix)
    scale = max(1, size // modules)
    image = QImage(modules * scale, modules * scale, QImage.Format_RGB32)
    image.fill(QColor("white"))
    painter = QPainter(image)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor("black"))
    for y, row in enumerate(matrix):
        for x, dark in enumerate(row):
            if dark:
                painter.drawRect(x * scale, y * scale, scale, scale)
    painter.end()
    return QPixmap.fromImage(image)
