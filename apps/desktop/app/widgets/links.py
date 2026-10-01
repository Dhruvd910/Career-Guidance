"""Links on a kiosk with no web browser: tapping one shows the address in large text and, when
available, a QR code to scan with a phone."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from app.widgets.common import heading, muted, primary_button


class LinkDialog(QDialog):
    def __init__(self, title: str, url: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.addWidget(heading(title))
        pixmap = None
        try:
            from app.qr import qr_pixmap

            pixmap = qr_pixmap(url, 200)
        except Exception:  # noqa: BLE001 — no QR support: the address alone still works
            pixmap = None
        if pixmap is not None:
            code = QLabel()
            code.setPixmap(pixmap)
            code.setAlignment(Qt.AlignCenter)
            layout.addWidget(code)
            layout.addWidget(muted("Scan with your phone's camera to open it."))
        else:
            layout.addWidget(muted("Open this on your phone or computer:"))
        link = QLabel(url)
        link.setWordWrap(True)
        link.setTextInteractionFlags(Qt.TextSelectableByMouse)
        link.setStyleSheet("font-size: 16px; font-weight: 700; color: #4f46e5;")
        layout.addWidget(link)
        close = primary_button("Done")
        close.clicked.connect(self.accept)
        layout.addWidget(close)


def link_row(title: str, note: str, url: str, parent: QWidget, compact: bool = False) -> QPushButton:
    """A tappable row for a link: its name, an optional note, and a chevron."""
    btn = QPushButton()
    btn.setProperty("variant", "option")
    btn.setCursor(Qt.PointingHandCursor)
    btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
    layout = QVBoxLayout(btn)
    layout.setContentsMargins(10, 6, 10, 6)
    layout.setSpacing(2)
    name = QLabel(title + ("" if compact else "  ›"))
    name.setWordWrap(True)
    name.setStyleSheet("background: transparent; font-weight: 600;" + (" font-size: 12px;" if compact else ""))
    layout.addWidget(name)
    if note:
        sub = QLabel(note)
        sub.setWordWrap(True)
        sub.setStyleSheet("background: transparent; color: #64748b; font-size: 12px;")
        layout.addWidget(sub)
    btn.setMinimumHeight(layout.sizeHint().height() + 4)
    btn.clicked.connect(lambda: LinkDialog(title, url, parent).exec())
    return btn
