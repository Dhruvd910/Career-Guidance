"""How MAYA works: one screen that maps every part of the app — what it's for, what it leads to —
and the buttons that are on every screen. Opened from the "?" on the home screen or the settings
menu. Each part has an Open button, so the map is also a way in.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from app.layout import page_margins
from app.pages.base import BasePage
from app.session import session
from app.theme import FOREGROUND, MUTED, TILE_COLORS
from app.widgets.common import Card, heading, muted, subtitle
from app.widgets.svg_icons import icon_pixmap

# (title, what it's for → what it leads to, glyph, colour, page) — the home screen's tiles, in order.
PARTS = [
    ("1. My Tests", "Short quizzes: what you enjoy, how you think, your skills and marks. "
                    "Your answers decide which careers MAYA shows you as a good fit.", "bulb", "blue", "assessment"),
    ("2. Career Paths", "Every career, with why it may suit you. Open one for its guide, and tap "
                        "“Make this my focus” to build your roadmap around it.", "compass", "teal", "careers"),
    ("3. My Roadmap", "Your plan, step by step, for your class and your focus career: what to do, "
                      "by when, and how you'll know it's done.", "road", "yellow", "roadmap"),
    ("4. Learn", "A video for each topic on your roadmap, in English and Hindi. Scan the QR code to "
                 "watch it on a phone.", "video", "red", "learn"),
    ("Colleges", "Real colleges: fees, hostel, cutoffs and how far they are. Save favourites to your "
                 "shortlist and compare them side by side.", "cap", "green", "colleges"),
    ("Exams", "JEE and NEET: dates, and your chances at each college from last year's cutoffs.",
     "exam", "orange", "exams"),
    ("Mock Tests", "Practice papers marked like the real exam (+4 right, −1 wrong).", "clipboard", "purple",
     "mock_tests"),
    ("My Progress", "How your skills and your plan have moved since you started.", "chart", "pink", "progress"),
]

BUTTONS = [
    ("←  Back", "Goes to the screen you came from."),
    ("⌂  Home", "Back to the home screen, from anywhere."),
    ("MAYA", "Ask her anything by voice — or just say “Hey Maya”."),
    ("✕", "Closes MAYA. Tap it twice."),
    ("⚙  (on Home)", "Your details, what MAYA remembers, and touch calibration."),
]


class GuidePage(BasePage):
    def __init__(self, ctx):
        super().__init__(ctx)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*page_margins())
        layout.setSpacing(8)
        layout.addWidget(heading("How MAYA works"))
        layout.addWidget(subtitle("Start at 1 and go in order — or open any part whenever you like."))
        for title, what, glyph, colour, target in PARTS:
            layout.addWidget(self._part(title, what, glyph, colour, target))

        buttons = Card()
        buttons.addWidget(heading("Buttons on every screen"))
        for label, what in BUTTONS:
            row = QHBoxLayout()
            name = QLabel(label)
            name.setFixedWidth(130)
            name.setStyleSheet(f"font-weight: 700; color: {FOREGROUND};")
            row.addWidget(name)
            line = QLabel(what)
            line.setWordWrap(True)
            line.setStyleSheet(f"color: {MUTED};")
            row.addWidget(line, stretch=1)
            buttons.layout_.addLayout(row)
        layout.addWidget(buttons)
        layout.addStretch(1)

    def _part(self, title: str, what: str, glyph: str, colour: str, target: str) -> QWidget:
        bg, accent, _ = TILE_COLORS[colour]
        card = Card()
        row = QHBoxLayout()
        row.setSpacing(12)
        icon = QLabel()
        icon.setPixmap(icon_pixmap(glyph, accent, 34))
        icon.setFixedSize(46, 46)
        icon.setAlignment(Qt.AlignCenter)
        icon.setStyleSheet(f"background: {bg}; border-radius: 12px;")
        row.addWidget(icon, alignment=Qt.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(2)
        name = QLabel(title)
        name.setStyleSheet(f"font-size: 15px; font-weight: 700; color: {FOREGROUND};")
        text.addWidget(name)
        text.addWidget(muted(what))
        row.addLayout(text, stretch=1)
        go = QPushButton("Open  ›")
        go.setProperty("variant", "option")
        go.setCursor(Qt.PointingHandCursor)
        go.clicked.connect(lambda: self._open(target))
        row.addWidget(go, alignment=Qt.AlignVCenter)
        card.layout_.addLayout(row)
        return card

    def _open(self, target: str) -> None:
        if target == "exams":
            target = "neet" if (session.profile or {}).get("target_exam_code") == "NEET_UG" else "jee"
        self.ctx.navigate(target)
