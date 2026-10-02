from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from app.api_client import api_client
from app.pages.base import BasePage
from app.session import session
from app.theme import FOREGROUND, MUTED, PRIMARY, TILE_COLORS
from app.widgets.brand import HandText
from app.widgets.icons import maya_face_icon
from app.widgets.svg_icons import icon_pixmap, svg_icon
from app.workers import run_async


class Tile(QFrame):
    """One of the dashboard's five pastel cards: glyph, title, a line under it, and a round
    arrow. The whole card is the tap target."""

    clicked = Signal()

    def __init__(self, title: str, blurb: str, glyph: str, colour: str):
        super().__init__()
        bg, accent, _ = TILE_COLORS[colour]
        self.setObjectName("Tile")
        self.setStyleSheet(f"QFrame#Tile {{ background: {bg}; border-radius: 16px; border: none; }}"
                           f"QFrame#Tile QLabel {{ background: transparent; }}")
        self.setCursor(Qt.PointingHandCursor)
        col = QVBoxLayout(self)
        col.setContentsMargins(8, 18, 8, 14)
        col.setSpacing(4)
        self.setMaximumHeight(270)
        icon = QLabel()
        icon.setPixmap(icon_pixmap(glyph, accent, 52))
        icon.setAlignment(Qt.AlignCenter)
        col.addWidget(icon)
        col.addSpacing(4)
        name = QLabel(title)
        name.setAlignment(Qt.AlignCenter)
        name.setWordWrap(True)
        name.setStyleSheet(f"font-size: 15px; font-weight: 700; color: {FOREGROUND};")
        col.addWidget(name)
        line = QLabel(blurb)
        line.setAlignment(Qt.AlignCenter)
        line.setWordWrap(True)
        line.setStyleSheet(f"font-size: 11px; color: {MUTED};")
        col.addWidget(line)
        col.addStretch(1)
        col.addSpacing(8)
        arrow = QLabel()
        arrow.setFixedSize(34, 34)
        arrow.setAlignment(Qt.AlignCenter)
        arrow.setPixmap(icon_pixmap("arrow-right", FOREGROUND, 16, 2.4))
        arrow.setStyleSheet("background: white; border-radius: 17px;")
        col.addWidget(arrow, alignment=Qt.AlignHCenter)

    def mouseReleaseEvent(self, event) -> None:
        if self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class DashboardPage(BasePage):
    # (title, line under it, glyph, colour, page)
    TILES = [
        ("Career Paths", "Find the right\npath for you", "compass", "blue", "careers"),
        ("Colleges", "Compare\ncolleges & cutoffs", "cap", "green", "colleges"),
        ("Exams", "JEE, NEET\nand more", "exam", "red", "exams"),
        ("Mock Tests", "Practice\nand improve", "clipboard", "purple", "mock_tests"),
        ("Roadmap", "Your step-by-step\nplan", "road", "yellow", "roadmap"),
    ]

    def __init__(self, ctx):
        super().__init__(ctx)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 8, 14, 12)
        layout.setSpacing(14)

        # Where we are: the most pressing thing, one tap from the full page (Phase 7).
        self.next_strip = QPushButton("Where we are  ›")
        self.next_strip.setObjectName("NextStrip")
        self.next_strip.setFlat(True)
        self.next_strip.setStyleSheet("text-align: left; padding: 6px 10px; color: #1e3a8a; font-weight: 600;")
        self.next_strip.clicked.connect(lambda: self.ctx.navigate("where_we_are"))
        layout.addWidget(self.next_strip)

        tiles = QHBoxLayout()
        tiles.setSpacing(10)
        for title, blurb, glyph, colour, target in self.TILES:
            tile = Tile(title, blurb, glyph, colour)
            tile.clicked.connect(lambda t=target: self._open(t))
            tiles.addWidget(tile)
        layout.addStretch(1)
        layout.addLayout(tiles, stretch=3)
        layout.addStretch(1)

        ask_row = QHBoxLayout()
        ask_row.setSpacing(10)
        face = QLabel()
        face.setPixmap(maya_face_icon(46).pixmap(QSize(46, 46)))
        ask_row.addWidget(face)

        bar = QFrame()
        bar.setObjectName("AskBar")
        bar_row = QHBoxLayout(bar)
        bar_row.setContentsMargins(14, 5, 5, 5)
        bar_row.setSpacing(6)
        self.ask_input = QLineEdit()
        self.ask_input.setPlaceholderText("Ask me anything about careers, colleges, exams...")
        self.ask_input.returnPressed.connect(self._ask)
        bar_row.addWidget(self.ask_input, stretch=1)
        mic = QPushButton()
        mic.setObjectName("MicButton")
        mic.setIcon(svg_icon("mic", PRIMARY, 20))
        mic.setIconSize(QSize(20, 20))
        mic.setFixedSize(40, 40)
        mic.setCursor(Qt.PointingHandCursor)
        mic.clicked.connect(lambda: self.ctx.navigate("maya", wake=True, greet=False))
        bar_row.addWidget(mic)
        send = QPushButton()
        send.setObjectName("SendButton")
        send.setIcon(svg_icon("send", "#ffffff", 20))
        send.setIconSize(QSize(20, 20))
        send.setFixedSize(48, 40)
        send.setCursor(Qt.PointingHandCursor)
        send.clicked.connect(self._ask)
        bar_row.addWidget(send)
        ask_row.addWidget(bar, stretch=1)
        ask_row.addSpacing(96)  # room for "Dream / Plan / Achieve"
        layout.addLayout(ask_row)

        self.hand = HandText(["Dream", "Plan", "Achieve"], size=19, angle=-14, color="#1e3a8a",
                             underline=True, parent=self)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.hand.move(self.width() - self.hand.width() + 4, self.height() - self.hand.height() + 2)
        self.hand.raise_()

    def _open(self, target: str) -> None:
        if target == "exams":
            # The exam page for the student's own goal; JEE for anyone still exploring.
            target = "neet" if (session.profile or {}).get("target_exam_code") == "NEET_UG" else "jee"
        self.ctx.navigate(target)

    def _ask(self) -> None:
        question = self.ask_input.text().strip()
        if not question:
            self.ctx.navigate("maya", wake=True, greet=False)
            return
        self.ask_input.clear()
        self.ctx.keyboard.hide_keyboard()
        self.ctx.navigate("maya", ask=question)

    def on_show(self, **kwargs) -> None:
        profile = session.profile or {}
        if not profile.get("onboarding_completed"):
            self.ctx.navigate("onboarding")
            return
        run_async(api_client.mentor_agenda, on_success=self._show_next, on_error=lambda _e: None)

    def _show_next(self, items: list) -> None:
        from app.pages.assessments import preferred_language

        lang = preferred_language(self.ctx)
        if items:
            first = items[0]
            label = "आगे" if lang == "hi" else "Next"
            self.next_strip.setText(f"{label}: {first['title'][lang]} — {first['why'][lang]}  ›")
        else:
            self.next_strip.setText("हम कहाँ हैं  ›" if lang == "hi" else "Where we are  ›")

    def change_goal(self) -> None:
        """Back to the question that decides everything else — MAYA asks it again."""
        run_async(
            api_client.update_profile_fields, {"knows_career_goal": None, "target_exam_code": None},
            on_success=lambda _r: self._goal_cleared(), on_error=lambda _e: None,
        )

    def _goal_cleared(self) -> None:
        session.refresh_profile()
        self.ctx.navigate("onboarding")
