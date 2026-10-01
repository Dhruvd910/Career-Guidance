"""Your career directions (spec §10–11): several directions in bands, grouped by domain —
Technology → Software, AI & Data, Cybersecurity, Robotics… — never one answer, never a single score.

Each career shows its band, the first reason and its usual route. Tapping it opens the whole
picture from the career engine (Phase 4):

- **Why it may fit** — including what you told MAYA.
- **What it draws on**, with your own results.
- **How people get there** — the usual steps, class 11–12 subjects, exams, and other routes.
- **The skills it needs**, with your results where something measured them.
- **A learning path**, foundations first, with things to try.
- **Questions to ask yourself**, **related careers**, and **colleges** that offer a route in, from
  the official programmes.

It works before any assessment too, just without a band. Careers less likely from your answers
are one tap away, never hidden.
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

BAND_COLOURS = {"strong": "#15803d", "potential": "#4f46e5", "explore": "#a16207", "weak": "#64748b", None: "#64748b"}
STATUS_COLOURS = {"strong": "#15803d", "ok": "#4f46e5", "gap": "#a16207", "not_measured": "#64748b"}
TITLES = {"interests": "What you enjoy", "aptitude": "Thinking skills", "skills": "Your skills", "academic": "Your marks",
          "coding_check": "Coding check"}
COMPONENT_LABELS = {"interest": ("Interest", "रुचि"), "work_style": ("Way of working and what matters to you",
                                                                    "काम का तरीका और आपकी प्राथमिकताएँ")}
NOT_ASSESSED = {"en": "Not assessed yet", "hi": "अभी आकलन नहीं हुआ"}
STEP_KINDS = {"stream": ("Stream", "स्ट्रीम"), "exam": ("Exam", "परीक्षा"), "degree": ("Degree", "डिग्री"),
              "roles": ("Then work as", "फिर काम")}


def words(lang: str, en: str, hi: str) -> str:
    return hi if lang == "hi" else en


def link_button(text: str) -> QPushButton:
    """A tappable line whose text wraps and shows "&" as written (a plain QPushButton would cut a
    long career name off and turn "Science & Research" into a keyboard shortcut)."""
    button = QPushButton()
    button.setProperty("variant", "option")
    button.setCursor(Qt.PointingHandCursor)
    button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
    inner = QVBoxLayout(button)
    inner.setContentsMargins(12, 8, 12, 8)
    label = QLabel(text)
    label.setWordWrap(True)
    label.setTextFormat(Qt.PlainText)
    label.setAttribute(Qt.WA_TransparentForMouseEvents)
    label.setStyleSheet("background: transparent; font-weight: 600;")
    inner.addWidget(label)
    button.setMinimumHeight(max(40, inner.sizeHint().height() + 4))
    return button


def band_chip(career: dict, lang: str) -> QLabel:
    label = (career.get("band_label") or NOT_ASSESSED)[lang]
    chip = QLabel(label)
    chip.setStyleSheet(f"color: {BAND_COLOURS.get(career.get('band'), '#64748b')}; font-weight: 700; background: transparent;")
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


def career_row(page, career: dict, lang: str) -> QPushButton:
    """One career as a tappable row: name, band, the first reason, and its usual route."""
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
    reasons = (career.get("from_memory") or []) + (career.get("why") or []) + (career.get("questions") or [])
    if reasons:
        note = QLabel(reasons[0][lang])
        note.setWordWrap(True)
        note.setStyleSheet("background: transparent; color: #475569; font-size: 13px;")
        inner.addWidget(note)
    education = career.get("required_education")
    if education:
        colleges = career.get("colleges") or {}
        route = words(lang, "Usually: ", "आम रास्ता: ") + education["degree"]["name"][lang]
        if colleges.get("in_state"):
            n = colleges["in_state"]
            route += words(lang, f" · {n} college{'s' if n != 1 else ''} in {colleges['state']}",
                           f" · {colleges['state']} में {n} कॉलेज")
        meta = QLabel(route)
        meta.setWordWrap(True)
        meta.setStyleSheet("background: transparent; color: #4f46e5; font-size: 12px; font-weight: 600;")
        inner.addWidget(meta)
    for label in button.findChildren(QLabel):
        label.setAttribute(Qt.WA_TransparentForMouseEvents)
    button.setMinimumHeight(inner.sizeHint().height() + 6)
    button.clicked.connect(lambda _c=False, k=career["career_key"]: page.ctx.navigate("direction", key=k))
    return button


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
        run_async(api_client.career_options, on_success=self._render, on_error=self._failed)

    def _render(self, data: dict) -> None:
        self.data = data
        lang = preferred_language(self.ctx)
        clear_layout(self.body_layout)
        if not data.get("ready"):
            self._not_ready(data, lang)
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
                self.body_layout.addWidget(career_row(self, career, lang))
        if weak_count and not self.show_weak:
            more = ghost_button(f"Show {weak_count} less likely from your answers")
            more.clicked.connect(self._show_weak)
            self.body_layout.addWidget(more)

    def _not_ready(self, data: dict, lang: str) -> None:
        self.based_on.setText("")
        card = Card()
        card.addWidget(heading("Start with “What you enjoy”"))
        card.addWidget(muted("Your directions come from your answers — about six minutes of questions on what "
                             "you like and how you like to work."))
        start = primary_button("Start")
        start.clicked.connect(lambda: self.ctx.navigate("assessment_run", key="interests", language=lang))
        card.addWidget(start)
        explore = secondary_button("Explore all careers")
        explore.clicked.connect(lambda: self.ctx.navigate("careers"))
        card.addWidget(explore)
        self.body_layout.addWidget(card)
        if data.get("from_memory"):
            self.body_layout.addWidget(heading(words(lang, "From what you've told MAYA", "आपने MAYA को जो बताया")))
            for career in data["from_memory"]:
                self.body_layout.addWidget(career_row(self, career, lang))

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

    def _failed(self, err: Exception) -> None:
        clear_layout(self.body_layout)
        set_error(self.error, err.message if isinstance(err, ApiError) else "Couldn't reach MAYA's server just now.")


class DirectionPage(BasePage):
    """One career, explained from the career graph and the student's own results."""

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
            self.body_layout.addWidget(muted("Loading…"))
            run_async(api_client.career_explain, key, on_success=self._render, on_error=self._failed)

    # ---------------- building blocks ----------------

    def _card(self, title: str) -> Card:
        card = Card()
        card.addWidget(heading(title))
        self.body_layout.addWidget(card)
        return card

    @staticmethod
    def _line(text: str, colour: str | None = None, bold: bool = False) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        style = (f"color: {colour};" if colour else "") + (" font-weight: 700;" if bold else "")
        if style:
            label.setStyleSheet(style)
        return label

    def _section(self, title: str, lines: list[str]) -> None:
        if lines:
            card = self._card(title)
            for line in lines:
                card.addWidget(self._line("•  " + line))

    # ---------------- the page ----------------

    def _render(self, career: dict) -> None:
        self.career = career
        lang = preferred_language(self.ctx)
        w = lambda en, hi: words(lang, en, hi)  # noqa: E731
        clear_layout(self.body_layout)
        self.title.setText(career["name"])
        self.band.setText((career.get("band_label") or NOT_ASSESSED)[lang])
        self.band.setStyleSheet(f"color: {BAND_COLOURS.get(career.get('band'), '#64748b')}; font-weight: 700;")

        if career.get("band") is None:
            card = self._card(w("Is it right for you?", "क्या यह आपके लिए सही है?"))
            card.addWidget(muted(w("Take “What you enjoy” and MAYA can show how this career fits you.",
                                   "“आपको क्या पसंद है” कीजिए, फिर MAYA बताएगी कि यह करियर आपसे कितना मेल खाता है।")))
            start = secondary_button(w("Start", "शुरू करें"))
            start.clicked.connect(lambda: self.ctx.navigate("assessment_run", key="interests", language=lang))
            card.addWidget(start)

        self._section(w("Why it may fit", "यह क्यों जँच सकता है"),
                      [r[lang] for r in (career.get("from_memory") or []) + career.get("why", [])])
        if career.get("band") is not None:
            self._draws_on(career, lang)
        self._pathway(career, lang)
        self._skills(career, lang)
        self._learning_path(career, lang)
        self._section(w("Your strengths for it", "इसके लिए आपकी ताक़त"), [s[lang] for s in career.get("strengths", [])])
        self._section(w("To work on", "जिन पर काम करना है"),
                      [d["text"][lang] + (f" — {d['next_step'][lang]}" if d.get("next_step") else "")
                       for d in career.get("development_areas", [])]
                      + [f"{g['skill']['name'][lang]} ({g['skill']['says'][lang]}) — "
                         + w(f"needed for {g['needed_for']['name']['en'].lower()}",
                             f"{g['needed_for']['name']['hi']} के लिए ज़रूरी") for g in career.get("foundation_gaps", [])])
        self._section(w("Questions to ask yourself", "ख़ुद से पूछने के सवाल"), [q[lang] for q in career.get("questions", [])])
        self._section(w("Things to try", "आज़माने के लिए"), career.get("things_to_try", []))
        self._related(career, lang)
        self._colleges(career, lang)
        if career.get("sources"):
            self.body_layout.addWidget(muted(career["sources"]["note"][lang]))

    def _draws_on(self, career: dict, lang: str) -> None:
        card = self._card(words(lang, "What it draws on", "इसमें क्या चाहिए"))
        for key, (en, hi_label) in COMPONENT_LABELS.items():
            value = career.get("components", {}).get(key)
            if value is not None:
                card.addWidget(score_row(hi_label if lang == "hi" else en, f"{round(value * 100)}%", value))
        for measure in career.get("measures", []):
            label = measure["label"][lang]
            if measure["score"] is None:
                card.addWidget(muted(f"{label[:1].upper() + label[1:]} — "
                                     + words(lang, "not measured yet", "अभी मापा नहीं गया")))
            else:
                card.addWidget(score_row(label, measure["says"][lang], measure["score"]))

    def _pathway(self, career: dict, lang: str) -> None:
        education = career.get("required_education")
        if not education and not career.get("education_path"):
            return
        card = self._card(words(lang, "How people get there", "लोग वहाँ कैसे पहुँचते हैं"))
        for n, step in enumerate(career.get("typical_pathway", []), start=1):
            kind = STEP_KINDS.get(step["kind"], (step["kind"], step["kind"]))
            card.addWidget(self._line(f"{n}.  {kind[1] if lang == 'hi' else kind[0]}: "
                                      + ", ".join(item[lang] for item in step["items"])))
        if education:
            must = [s["name"][lang] for s in education["subjects"]["mandatory"]]
            must += [words(lang, " or ", " या ").join(s["name"][lang] for s in group) for group in education["subjects"]["one_of"]]
            if must:
                card.addWidget(muted(words(lang, "Class 11–12 subjects needed: ", "11वीं–12वीं में ज़रूरी विषय: ") + ", ".join(must)))
            for rec in education["subjects"].get("recommended", []):
                if rec.get("note"):
                    card.addWidget(muted(f"{rec['name'][lang]}: {rec['note']}"))
        others = career.get("alternative_pathways") or []
        if others:
            card.addWidget(self._line(words(lang, "Other routes in", "दूसरे रास्ते"), bold=True))
            for route in others:
                text = route["degree"]["name"][lang]
                if route["exams"]:
                    text += " — " + ", ".join(e["name"][lang] for e in route["exams"][:3])
                if route.get("note"):
                    text += f" ({route['note']})"
                card.addWidget(self._line("•  " + text))

    def _skills(self, career: dict, lang: str) -> None:
        skills = career.get("skills") or []
        if not skills:
            return
        card = self._card(words(lang, "Skills it needs", "किन हुनर की ज़रूरत है"))
        for s in skills:
            status = s["status_label"][lang] + (f" · {s['says'][lang]}" if s.get("says") else "")
            row = QHBoxLayout()
            row.addWidget(self._line(s["name"][lang]), 1)
            row.addWidget(self._line(status, STATUS_COLOURS[s["status"]], bold=True))
            holder = QWidget()
            holder.setLayout(row)
            card.addWidget(holder)

    def _learning_path(self, career: dict, lang: str) -> None:
        path = career.get("learning_path") or []
        if not path:
            return
        card = self._card(words(lang, "A learning path, foundations first", "सीखने का रास्ता, बुनियाद से शुरू"))
        for n, step in enumerate(path, start=1):
            card.addWidget(self._line(f"{n}.  {step['name'][lang]}", STATUS_COLOURS[step["status"]], bold=True))
            if step.get("try"):
                card.addWidget(muted(words(lang, "Try: ", "आज़माइए: ") + "; ".join(t["name"][lang] for t in step["try"])))

    def _related(self, career: dict, lang: str) -> None:
        related = career.get("related") or []
        if not related:
            return
        card = self._card(words(lang, "Related careers", "मिलते-जुलते करियर"))
        for r in related:
            button = link_button(r["name"][lang] + "  ›")
            button.clicked.connect(lambda _c=False, k=r["key"].split(":", 1)[1]: self.ctx.navigate("direction", key=k))
            card.addWidget(button)

    def _colleges(self, career: dict, lang: str) -> None:
        counts = career.get("colleges") or {}
        if not counts.get("total"):
            return
        card = self._card(words(lang, "Colleges that offer it", "कौन से कॉलेज यह पढ़ाते हैं"))
        total = counts["total"]
        text = words(lang, f"{total} college{'s have' if total != 1 else ' has'} an official 2026 programme on a route in",
                     f"{total} कॉलेजों में इसका आधिकारिक 2026 प्रोग्राम है")
        if counts.get("state"):
            text += words(lang, f" — {counts['in_state']} in {counts['state']}.", f" — {counts['state']} में {counts['in_state']}।")
        card.addWidget(self._line(text))
        for college in (career.get("colleges_in_state") or {}).get("colleges", []):
            button = link_button(f"{college['name']} · {college['city']}  ›")
            if college.get("college_id"):
                button.clicked.connect(lambda _c=False, cid=college["college_id"]: self.ctx.navigate("college_detail", college_id=cid))
            card.addWidget(button)
        card.addWidget(muted(words(lang, "From the JoSAA and MCC 2026 lists. Fees, hostels and facilities aren't collected yet.",
                                   "JoSAA और MCC 2026 की सूचियों से। फ़ीस, हॉस्टल और सुविधाओं की जानकारी अभी इकट्ठी नहीं हुई है।")))

    def _talk(self) -> None:
        if self.career is None:
            return
        name, hindi = self.career["name"], preferred_language(self.ctx) == "hi"
        if self.career.get("band") is None:
            ask = (f"{name} में लोग कैसे जाते हैं, और क्या यह मेरे लिए सही हो सकता है?" if hindi
                   else f"Tell me about {name} — how do people get into it, and could it suit me?")
        elif hindi:
            ask = f"मेरे assessment के हिसाब से {name} मेरे लिए कैसा रहेगा? मुझे क्या आज़माना चाहिए?"
        else:
            ask = f"Based on my assessments, tell me about {name} for me — why it's in this band, and what I should try."
        self.ctx.navigate("maya", ask=ask)

    def _failed(self, err: Exception) -> None:
        clear_layout(self.body_layout)
        set_error(self.error, err.message if isinstance(err, ApiError) else "Couldn't reach MAYA's server just now.")
