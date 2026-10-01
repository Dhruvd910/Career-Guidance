"""Your career directions (spec §10–11): several directions in bands, grouped by domain —
Technology → CSE, AI & Data… — never one answer, never a single score.

Each career shows its band and the first reason; tapping it opens why it may fit, what it draws
on (with your own results, or "not measured yet"), your strengths for it, what to work on with a
next step, questions to ask yourself, things to try, and how people get there — plus "Talk to
MAYA about this". Careers less likely from your answers are one tap away, never hidden.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from app.api_client import ApiError, api_client
from app.layout import page_margins
from app.pages.assessment_result import score_row
from app.pages.assessments import LANGUAGES, preferred_language, short_date
from app.pages.base import BasePage
from app.widgets.common import (
    Card, clear_layout, error_label, ghost_button, heading, muted, primary_button, secondary_button, set_error,
    subtitle,
)
from app.workers import run_async

BAND_COLOURS = {"strong": "#15803d", "potential": "#4f46e5", "explore": "#a16207", "weak": "#64748b"}
TITLES = {"interests": "What you enjoy", "aptitude": "Thinking skills", "skills": "Your skills", "academic": "Your marks",
          "coding_check": "Coding check"}
COMPONENT_LABELS = {"interest": ("Interest", "रुचि"), "work_style": ("Way of working and what matters to you",
                                                                    "काम का तरीका और आपकी प्राथमिकताएँ")}


def band_chip(career: dict, lang: str) -> QLabel:
    chip = QLabel(career["band_label"][lang])
    chip.setStyleSheet(f"color: {BAND_COLOURS[career['band']]}; font-weight: 700; background: transparent;")
    return chip


def _language_row(page) -> QHBoxLayout:
    row = QHBoxLayout()
    page.language_buttons = {}
    for code, label in LANGUAGES:
        button = secondary_button(label)
        button.setCheckable(True)
        button.clicked.connect(lambda _c=False, c=code: page.set_language(c))
        row.addWidget(button)
        page.language_buttons[code] = button
    row.addStretch(1)
    return row


class DirectionsPage(BasePage):
    def __init__(self, ctx):
        super().__init__(ctx)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*page_margins())
        layout.setSpacing(10)
        layout.addWidget(heading("Your career directions"))
        layout.addWidget(subtitle("Several directions from your assessments — not one answer. You decide; talk them "
                                  "over with MAYA and your family."))
        layout.addLayout(_language_row(self))
        self.based_on = muted("")
        layout.addWidget(self.based_on)
        self.error = error_label()
        layout.addWidget(self.error)
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(8)
        layout.addWidget(self.body)
        layout.addStretch(1)
        self.data: dict | None = None
        self.show_weak = False

    def set_language(self, code: str) -> None:
        self.ctx.assessment_language = code
        for c, button in self.language_buttons.items():
            button.setChecked(c == code)
        if self.data is not None:
            self._render(self.data)

    def on_show(self, returning: bool = False, **kwargs) -> None:
        self.set_language(preferred_language(self.ctx))
        if returning and self.data is not None:
            return
        self.show_weak = False
        set_error(self.error, None)
        clear_layout(self.body_layout)
        self.body_layout.addWidget(muted("Working out your directions…"))
        run_async(api_client.career_directions, on_success=self._render, on_error=self._failed)

    def _render(self, data: dict) -> None:
        self.data = data
        lang = preferred_language(self.ctx)
        clear_layout(self.body_layout)
        if not data.get("ready"):
            self.based_on.setText("")
            card = Card()
            card.addWidget(heading("Start with “What you enjoy”"))
            card.addWidget(muted("Your directions come from your answers — about six minutes of questions on what "
                                 "you like and how you like to work."))
            start = primary_button("Start")
            start.clicked.connect(lambda: self.ctx.navigate("assessment_run", key="interests", language=lang))
            card.addWidget(start)
            self.body_layout.addWidget(card)
            return
        self.based_on.setText("Based on: " + ", ".join(TITLES.get(k, k) for k in data["inputs"])
                              + (f" · {short_date(data.get('as_of'))}" if data.get("as_of") else ""))
        if data.get("missing"):
            self.body_layout.addWidget(self._missing_card(data["missing"], lang))
        weak_count = 0
        for domain in data["domains"]:
            careers = [c for c in domain["careers"] if self.show_weak or c["band"] != "weak"]
            weak_count += sum(1 for c in domain["careers"] if c["band"] == "weak")
            if not careers:
                continue
            self.body_layout.addWidget(heading(domain["label"][lang]))
            for career in careers:
                self.body_layout.addWidget(self._career_row(career, lang))
        if weak_count and not self.show_weak:
            more = ghost_button(f"Show {weak_count} less likely from your answers")
            more.clicked.connect(self._show_weak)
            self.body_layout.addWidget(more)

    def _show_weak(self) -> None:
        self.show_weak = True
        self._render(self.data)

    def _missing_card(self, missing: list, lang: str) -> Card:
        card = Card()
        card.addWidget(muted("Some things these careers need aren't measured yet. Each check sharpens the picture:"))
        row = QHBoxLayout()
        for key in missing:
            button = secondary_button(TITLES.get(key, key))
            button.clicked.connect(lambda _c=False, k=key: self.ctx.navigate("assessment_run", key=k, language=lang))
            row.addWidget(button)
        row.addStretch(1)
        holder = QWidget()
        holder.setLayout(row)
        card.addWidget(holder)
        return card

    def _career_row(self, career: dict, lang: str) -> QPushButton:
        button = QPushButton()
        button.setProperty("variant", "option")
        button.setCursor(Qt.PointingHandCursor)
        button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        inner = QVBoxLayout(button)
        inner.setContentsMargins(12, 8, 12, 8)
        inner.setSpacing(3)
        top = QHBoxLayout()
        name = QLabel(career["name"] + "  ›")
        name.setWordWrap(True)
        name.setStyleSheet("background: transparent; font-weight: 700;")
        top.addWidget(name, 1)
        top.addWidget(band_chip(career, lang))
        inner.addLayout(top)
        line = (career["why"] or career["questions"] or [{"en": "", "hi": ""}])[0][lang]
        if line:
            note = QLabel(line)
            note.setWordWrap(True)
            note.setStyleSheet("background: transparent; color: #475569; font-size: 13px;")
            inner.addWidget(note)
        for label in button.findChildren(QLabel):
            label.setAttribute(Qt.WA_TransparentForMouseEvents)
        button.setMinimumHeight(inner.sizeHint().height() + 6)
        button.clicked.connect(lambda _c=False, k=career["career_key"]: self.ctx.navigate("direction", key=k))
        return button

    def _failed(self, err: Exception) -> None:
        clear_layout(self.body_layout)
        set_error(self.error, err.message if isinstance(err, ApiError) else "Couldn't reach MAYA's server just now.")


class DirectionPage(BasePage):
    """One career, explained from the student's own results."""

    def __init__(self, ctx):
        super().__init__(ctx)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*page_margins())
        layout.setSpacing(10)
        self.title = heading("")
        layout.addWidget(self.title)
        self.band = QLabel("")
        layout.addWidget(self.band)
        layout.addLayout(_language_row(self))
        self.error = error_label()
        layout.addWidget(self.error)
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(8)
        layout.addWidget(self.body)
        actions = QHBoxLayout()
        self.talk = primary_button("Talk to MAYA about this")
        self.talk.clicked.connect(self._talk)
        actions.addWidget(self.talk)
        self.guide = secondary_button("Full career guide")
        self.guide.clicked.connect(lambda: self.career and self.ctx.navigate("career_detail", key=self.key))
        actions.addWidget(self.guide)
        actions.addStretch(1)
        layout.addLayout(actions)
        layout.addStretch(1)
        self.career: dict | None = None
        self.key: str | None = None

    def set_language(self, code: str) -> None:
        self.ctx.assessment_language = code
        for c, button in self.language_buttons.items():
            button.setChecked(c == code)
        if self.career is not None:
            self._render(self.career)

    def on_show(self, key: str | None = None, returning: bool = False, **kwargs) -> None:
        self.set_language(preferred_language(self.ctx))
        if returning and self.career is not None:
            return
        self.key, self.career = key, None
        set_error(self.error, None)
        self.title.setText("")
        self.band.setText("")
        clear_layout(self.body_layout)
        if key:
            run_async(api_client.career_direction, key, on_success=self._render, on_error=self._failed)

    def _section(self, title: str, lines: list[str]) -> None:
        if not lines:
            return
        card = Card()
        card.addWidget(heading(title))
        for line in lines:
            label = QLabel("•  " + line)
            label.setWordWrap(True)
            card.addWidget(label)
        self.body_layout.addWidget(card)

    def _render(self, career: dict) -> None:
        self.career = career
        lang = preferred_language(self.ctx)
        hi = lang == "hi"
        clear_layout(self.body_layout)
        self.title.setText(career["name"])
        self.band.setText(career["band_label"][lang])
        self.band.setStyleSheet(f"color: {BAND_COLOURS[career['band']]}; font-weight: 700;")

        self._section("Why it may fit" if not hi else "यह क्यों जँच सकता है", [w[lang] for w in career["why"]])

        draws = Card()
        draws.addWidget(heading("What it draws on" if not hi else "इसमें क्या चाहिए"))
        for key, (en, hi_label) in COMPONENT_LABELS.items():
            value = career["components"].get(key)
            if value is not None:
                draws.addWidget(score_row(hi_label if hi else en, f"{round(value * 100)}%", value))
        for measure in career.get("measures", []):
            if measure["score"] is None:
                label = measure["label"][lang]
                draws.addWidget(muted(f"{label[:1].upper() + label[1:]} — "
                                      + ("not measured yet" if not hi else "अभी मापा नहीं गया")))
            else:
                draws.addWidget(score_row(measure["label"][lang], measure["says"][lang], measure["score"]))
        self.body_layout.addWidget(draws)

        self._section("Your strengths for it" if not hi else "इसके लिए आपकी ताक़त", [s[lang] for s in career["strengths"]])
        self._section("To work on" if not hi else "जिन पर काम करना है",
                      [d["text"][lang] + (f" — {d['next_step'][lang]}" if d.get("next_step") else "")
                       for d in career["development_areas"]])
        self._section("Questions to ask yourself" if not hi else "ख़ुद से पूछने के सवाल",
                      [q[lang] for q in career["questions"]])
        self._section("Things to try" if not hi else "आज़माने के लिए", career.get("things_to_try", []))
        path = [career["education_path"]] if career.get("education_path") else []
        if career.get("exams"):
            path.append("Entrance exams: " + ", ".join(e.replace("_", " ") for e in career["exams"]))
        self._section("How people get there" if not hi else "लोग वहाँ कैसे पहुँचते हैं", path)

    def _talk(self) -> None:
        if self.career is None:
            return
        name = self.career["name"]
        if preferred_language(self.ctx) == "hi":
            ask = f"मेरे assessment के हिसाब से {name} मेरे लिए कैसा रहेगा? मुझे क्या आज़माना चाहिए?"
        else:
            ask = f"Based on my assessments, tell me about {name} for me — why it's in this band, and what I should try."
        self.ctx.navigate("maya", ask=ask)

    def _failed(self, err: Exception) -> None:
        set_error(self.error, err.message if isinstance(err, ApiError) else "Couldn't reach MAYA's server just now.")
