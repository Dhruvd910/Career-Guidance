from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout

from app.theme import chance_style


class Card(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(16, 16, 16, 16)
        self.layout_.setSpacing(8)

    def addWidget(self, widget):
        self.layout_.addWidget(widget)
        return widget


def heading(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("role", "heading")
    # Wraps rather than widening its page: a college name is longer than a kiosk panel.
    label.setWordWrap(True)
    return label


def subtitle(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("role", "subtitle")
    label.setWordWrap(True)
    return label


def muted(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("role", "muted")
    label.setWordWrap(True)
    return label


def error_label(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setProperty("role", "error")
    label.setWordWrap(True)
    label.setVisible(bool(text))
    return label


def set_error(label: QLabel, text: str | None) -> None:
    label.setText(text or "")
    label.setVisible(bool(text))


def demo_badge() -> QLabel:
    label = QLabel("DEMO DATA")
    label.setProperty("role", "demo-badge")
    label.setToolTip("Sample data for development — not real admissions data")
    return label


def chance_badge(band: str, band_label: str, emoji: str) -> QLabel:
    """The band in its colour. (The emoji the API sends isn't shown: the Pi's fonts lack some of them.)"""
    label = QLabel(band_label)
    label.setStyleSheet(chance_style(band))
    return label


def button_text(text: str) -> str:
    """Names, titles and answers on a button exactly as written: Qt reads "&" in a button's text as a
    keyboard-shortcut marker, so "Science & Engineering" showed as "Science _Engineering"."""
    return text.replace("&", "&&")


def secondary_button(text: str) -> QPushButton:
    btn = QPushButton(text)
    btn.setProperty("variant", "secondary")
    btn.setCursor(Qt.PointingHandCursor)
    return btn


def ghost_button(text: str) -> QPushButton:
    btn = QPushButton(text)
    btn.setProperty("variant", "ghost")
    btn.setCursor(Qt.PointingHandCursor)
    return btn


def primary_button(text: str) -> QPushButton:
    btn = QPushButton(text)
    btn.setCursor(Qt.PointingHandCursor)
    return btn


def arrow_button(text: str, variant: str = "next", icon: str = "arrow-right") -> QPushButton:
    """The design's blue buttons with a trailing arrow: "Get Started →", "Next →"."""
    from app.widgets.svg_icons import svg_icon

    btn = QPushButton(f"{text}  ")
    btn.setProperty("variant", variant)
    size = 20 if variant == "hero" else 18
    btn.setIcon(svg_icon(icon, "#ffffff", size, 2.4))
    btn.setIconSize(QSize(size, size))
    btn.setLayoutDirection(Qt.RightToLeft)  # icon after the text
    btn.setCursor(Qt.PointingHandCursor)
    btn.setMinimumHeight(50 if variant == "hero" else 44)
    return btn


def danger_button(text: str) -> QPushButton:
    btn = QPushButton(text)
    btn.setProperty("variant", "danger")
    btn.setCursor(Qt.PointingHandCursor)
    return btn


def clear_layout(layout) -> None:
    """Empties a layout. Widgets are hidden as they're removed, not just scheduled for
    deletion — otherwise they stay painted over the new content until the event loop gets
    round to deleting them."""
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.hide()
            widget.deleteLater()
        elif item.layout() is not None:
            clear_layout(item.layout())
