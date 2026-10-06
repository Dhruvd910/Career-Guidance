from datetime import datetime

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout

from app.config import PORTRAIT_RATIO
from app.pages.base import BasePage
from app.theme import FOREGROUND, MUTED, PRIMARY
from app.widgets.brand import Clock, HandText, Logo, Summit
from app.widgets.common import arrow_button
from app.widgets.maya_status import MayaStatus

MASCOT_HEIGHT = 330


def salutation() -> str:
    hour = datetime.now().hour
    if hour < 12:
        return "Good morning"
    if hour < 17:
        return "Good afternoon"
    return "Good evening"


class GreetingPage(BasePage):
    """MAYA's welcome on every launch once she knows you: she waves, says hello out loud,
    and Get Started takes you on (to the dashboard, or the rest of onboarding)."""

    def __init__(self, ctx):
        super().__init__(ctx)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 12, 22, 12)
        outer.setSpacing(0)

        top = QHBoxLayout()
        top.addWidget(Logo(38))
        top.addStretch(1)
        top.addWidget(Clock())
        outer.addLayout(top)

        body = QHBoxLayout()
        body.setSpacing(28)
        self.status = MayaStatus(ctx.voice, QSize(int(MASCOT_HEIGHT * PORTRAIT_RATIO), MASCOT_HEIGHT),
                                 show_text=False, portrait=True)
        body.addSpacing(40)
        body.addWidget(self.status, alignment=Qt.AlignBottom)

        words = QVBoxLayout()
        words.setSpacing(4)
        words.addStretch(1)
        self.salute = QLabel("")
        self.salute.setStyleSheet(f"font-size: 28px; font-weight: 700; color: {FOREGROUND};")
        self.name_label = QLabel("")
        self.name_label.setStyleSheet(f"font-size: 38px; font-weight: 800; color: {PRIMARY};")
        intro = QLabel("I'm MAYA, your AI career\nguidance assistant.")
        intro.setStyleSheet(f"font-size: 17px; color: {FOREGROUND};")
        together = QLabel("Let's explore your future together.")
        together.setStyleSheet(f"font-size: 14px; color: {MUTED};")
        for label in (self.salute, self.name_label, intro, together):
            words.addWidget(label)
            if label is self.name_label:
                words.addSpacing(6)
        words.addSpacing(18)
        self.start_btn = arrow_button("Get Started", "hero")
        self.start_btn.clicked.connect(self._advance)
        # AlignAbsolute: the button is right-to-left (arrow after the text), which would mirror a plain AlignLeft.
        words.addWidget(self.start_btn, alignment=Qt.AlignLeft | Qt.AlignAbsolute)
        words.addStretch(2)
        body.addLayout(words, stretch=1)
        outer.addLayout(body, stretch=1)

        # Decorations float over the page's corners rather than taking space in the layout.
        self.hand = HandText(["Explore", "Learn", "Grow"], size=24, angle=-14, parent=self)
        self.summit = Summit(parent=self)

        self._next_target = "dashboard"
        self._advanced = True

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.hand.move(6, self.height() - self.hand.height() - 18)
        self.summit.move(self.width() - self.summit.width(), self.height() - self.summit.height())
        self.hand.raise_()

    def on_show(self, next_target: str = "dashboard", **kwargs) -> None:
        from app.session import session  # local import avoids a circular import at module load

        self._next_target = next_target
        self._advanced = False

        first_name = (session.profile or {}).get("name", "").split(" ")[0]
        self.salute.setText(f"{salutation()}," if first_name else f"{salutation()}!")
        self.name_label.setText(f"{first_name}!" if first_name else "")  # (no 👋: the Pi's fonts draw a box)
        self.name_label.setVisible(bool(first_name))
        greeting = f"{salutation()}, {first_name}!" if first_name else f"{salutation()}!"
        self.ctx.voice.say(f"{greeting} I'm MAYA, your AI career guidance assistant. "
                           f"Let's explore your future together.")

    def _advance(self) -> None:
        if self._advanced:
            return
        self._advanced = True
        self.ctx.voice.cancel()
        self.ctx.navigate(self._next_target)

