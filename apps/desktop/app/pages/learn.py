"""Learn: where to learn each topic of a career path. The career's skills in the order they build on
each other, each with how the student stands on it, a checked video in English and one in Hindi,
and a YouTube search for more — every link a QR code to open on a phone (the Pi has no browser).

Opens on the roadmap's focus career (else the strongest career direction); "Change career" picks
another. Opened with skill=… (from a roadmap step or MAYA), that topic is brought into view.
"""

from __future__ import annotations

import re

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from app.api_client import ApiError, api_client
from app.layout import page_margins
from app.pages.assessments import preferred_language
from app.pages.base import BasePage
from app.theme import FOREGROUND, MUTED
from app.widgets.common import Card, button_text, clear_layout, error_label, heading, muted, primary_button, set_error, subtitle
from app.widgets.links import LinkDialog
from app.workers import run_async

STATUS = {  # how the student stands on a topic, from their own results
    "strong": ("✓  You're strong here", "#15803d", "#dcfce7"),
    "ok": ("On track", "#1d4ed8", "#dbeafe"),
    "gap": ("Work on this", "#b45309", "#fef3c7"),
    "not_measured": ("Not tested yet", "#475569", "#f1f5f9"),
}
WHY = {"focus": "your roadmap focus", "strong": "your strongest match", "potential": "a good match for you",
       "asked": "the career you picked"}


class LearnPage(BasePage):
    def __init__(self, ctx):
        super().__init__(ctx)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*page_margins())
        layout.setSpacing(8)
        layout.addWidget(heading("Learn"))
        self.intro = subtitle("Every topic for your career, in order. Tap a video to get a QR code — scan it "
                              "with a phone to watch.")
        layout.addWidget(self.intro)

        picker = QHBoxLayout()
        self.career_label = QLabel("")
        self.career_label.setWordWrap(True)
        self.career_label.setStyleSheet(f"font-size: 15px; font-weight: 700; color: {FOREGROUND};")
        picker.addWidget(self.career_label, stretch=1)
        self.combo = QComboBox()
        self.combo.setMinimumWidth(230)
        self.combo.activated.connect(self._career_chosen)
        picker.addWidget(self.combo)
        layout.addLayout(picker)

        self.error = error_label()
        layout.addWidget(self.error)
        self.steps = QVBoxLayout()
        self.steps.setSpacing(8)
        layout.addLayout(self.steps)
        layout.addStretch(1)
        self.plan: dict | None = None
        self._cards: dict[str, Card] = {}
        self._skill: str | None = None

    def on_show(self, career: str | None = None, skill: str | None = None, returning: bool = False, **kwargs) -> None:
        set_error(self.error, None)
        self._skill = skill
        if returning and self.plan is not None:
            return
        self.career_label.setText("Loading…")
        run_async(api_client.learn, career, on_success=self._render, on_error=self._failed)

    def _career_chosen(self, index: int) -> None:
        key = self.combo.itemData(index)
        if key and (self.plan or {}).get("career", {}) and key != self.plan["career"]["key"]:
            self._skill = None
            run_async(api_client.learn, key, on_success=self._render, on_error=self._failed)

    def _render(self, plan: dict) -> None:
        self.plan = plan
        lang = preferred_language(self.ctx)
        clear_layout(self.steps)
        self._cards = {}
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItem("Change career…", None)
        for c in sorted(plan["careers"], key=lambda c: c["name"]["en"]):
            self.combo.addItem(c["name"][lang], c["key"])
        self.combo.blockSignals(False)
        career = plan.get("career")
        if career is None:
            self.career_label.setText("Pick a career to see what to learn")
            card = Card()
            card.addWidget(muted("You don't have a focus career yet. Choose one above — or take My Tests and MAYA "
                                 "will suggest careers that fit you."))
            tests = primary_button("Open My Tests")
            tests.clicked.connect(lambda: self.ctx.navigate("assessment"))
            card.addWidget(tests)
            self.steps.addWidget(card)
            return
        why = WHY.get(plan.get("why"), "")
        self.career_label.setText(f"{career['name'][lang]}" + (f"  ·  {why}" if why else ""))
        for n, step in enumerate(plan["steps"], start=1):
            card = self._step_card(n, step, lang)
            self._cards[step["skill"]] = card
            self.steps.addWidget(card)
        if self._skill in self._cards:
            target = self._cards[self._skill]
            target.setStyleSheet("QFrame { border: 2px solid #2563eb; }")
            QTimer.singleShot(50, lambda: self.ctx._holders["learn"].ensureWidgetVisible(target, 0, 40))

    def _step_card(self, n: int, step: dict, lang: str) -> Card:
        card = Card()
        top = QHBoxLayout()
        name = QLabel(f"{n}.  {step['name'][lang]}")
        name.setWordWrap(True)
        name.setStyleSheet(f"font-size: 15px; font-weight: 700; color: {FOREGROUND};")
        top.addWidget(name, stretch=1)
        text, fg, bg = STATUS.get(step["status"], STATUS["not_measured"])
        chip = QLabel(text)
        chip.setStyleSheet(f"background: {bg}; color: {fg}; border-radius: 10px; padding: 3px 10px; font-size: 12px;"
                           " font-weight: 600;")
        top.addWidget(chip, alignment=Qt.AlignTop)
        card.layout_.addLayout(top)
        if step.get("says"):
            card.addWidget(muted(f"Your result: {step['says'][lang]}"))
        videos = sorted(step["videos"], key=lambda v: v["lang"] != lang)  # the student's language first
        for v in videos:
            label = "▶  हिंदी" if v["lang"] == "hi" else "▶  English"
            note = _plain(v["channel"]) + (f"  ·  {v['length']}" if v.get("length") else "")
            card.addWidget(self._link(f"{label}:  {_short(_plain(v['title']))}", note, v["url"], _plain(v["title"])))
        search = step["search"]["hi" if lang == "hi" else "en"]
        card.addWidget(self._link("More videos on this topic", "A YouTube search for it", search,
                                  f"More videos: {step['name'][lang]}"))
        if step.get("try"):
            card.addWidget(muted("Try: " + "; ".join(t["name"][lang] for t in step["try"])))
        return card

    def _link(self, text: str, note: str, url: str, title: str) -> QPushButton:
        """One compact row: what it is, then who made it — tap for the QR code."""
        btn = QPushButton(button_text(f"{text}\n{note}"))
        btn.setProperty("variant", "option")
        btn.setStyleSheet("text-align: left; padding: 6px 10px; font-size: 12px;")
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(lambda: LinkDialog(title, url, self).exec())
        return btn

    def _failed(self, err: Exception) -> None:
        self.career_label.setText("")
        set_error(self.error, err.message if isinstance(err, ApiError) else "Couldn't load this. Please try again.")


# The Pi has no emoji font: a 🔥 or 👉 in a YouTube title would show as an empty box.
_EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0E\uFE0F\u200D]+")


def _plain(title: str) -> str:
    return " ".join(_EMOJI.sub(" ", title).split())


def _short(title: str, most: int = 64) -> str:
    return title if len(title) <= most else title[: most - 1].rstrip() + "…"
