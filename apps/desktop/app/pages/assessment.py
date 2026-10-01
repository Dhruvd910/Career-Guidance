"""The career assessment as a conversation with MAYA — no sliders, no numbers to pick.

She asks one question at a time, out loud, and listens; every question can also be answered
by tapping. Liking a subject leads to a couple of questions about *what* you like about it,
so the conversation adapts (about 25-35 questions, a few minutes). "Go back" and "skip" work
by voice as well as by tapping.

Afterwards every career is ranked, best match first, with plain reasons — and each one opens
a full guide: how to prepare, where to start, resources, jobs and earnings.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QGridLayout, QHBoxLayout, QLabel, QProgressBar, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from app.api_client import ApiError, api_client
from app.layout import page_margins
from app.pages.base import BasePage
from app.voice import IDLE
from app.voice_parsing import match_option, wants_to_go_back, wants_to_skip
from app.widgets.common import (
    clear_layout,
    Card, error_label, heading, muted, primary_button, secondary_button, set_error, subtitle,
)
from app.widgets.icons import mic_icon
from app.workers import run_async

RETRIES = 1
LABEL_COLOURS = {
    "Best match": "#15803d", "Closest match": "#15803d", "Strong fit": "#16a34a", "Good fit": "#4f46e5",
    "Worth exploring": "#a16207", "Less likely": "#9a3412", "Not a natural fit": "#b91c1c",
}


def _repolish(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class CareerAssessmentPage(BasePage):
    def __init__(self, ctx):
        super().__init__(ctx)
        self.voice = ctx.voice
        self.bank: dict | None = None
        self.answers: dict[str, str] = {}
        self.skipped: set[str] = set()
        self.history: list[str] = []  # question ids in the order they were shown
        self.current: dict | None = None
        self.assessment_type = "class11_12_career"
        self._misses = 0

        outer = QVBoxLayout(self)
        outer.setContentsMargins(*page_margins())
        outer.setSpacing(10)

        # ---- the conversation ----
        self.question_view = QWidget()
        q_layout = QVBoxLayout(self.question_view)
        q_layout.setContentsMargins(0, 0, 0, 0)
        q_layout.setSpacing(8)
        top = QHBoxLayout()
        self.progress_label = muted("")
        top.addWidget(self.progress_label)
        top.addStretch(1)
        self.voice_btn = secondary_button("  Answer by voice")
        self.voice_btn.setIcon(mic_icon())
        self.voice_btn.setIconSize(QSize(16, 16))
        self.voice_btn.clicked.connect(lambda: self._ask(again=True))
        top.addWidget(self.voice_btn)
        q_layout.addLayout(top)
        self.progress = QProgressBar()
        self.progress.setObjectName("AssessmentProgress")
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)
        q_layout.addWidget(self.progress)

        self.question_label = heading("")
        q_layout.addWidget(self.question_label)
        self.hint = muted("Tap an answer, or just say it. You can say \"go back\" or \"skip\".")
        q_layout.addWidget(self.hint)

        self.options_holder = QWidget()
        self.options_grid = QGridLayout(self.options_holder)
        self.options_grid.setContentsMargins(0, 0, 0, 0)
        self.options_grid.setSpacing(8)
        q_layout.addWidget(self.options_holder)

        self.error = error_label()
        q_layout.addWidget(self.error)

        nav = QHBoxLayout()
        self.back_btn = secondary_button("←  Back")
        self.back_btn.clicked.connect(self.go_back)
        nav.addWidget(self.back_btn)
        nav.addStretch(1)
        self.skip_btn = secondary_button("Skip")
        self.skip_btn.clicked.connect(self._skip)
        nav.addWidget(self.skip_btn)
        q_layout.addLayout(nav)
        outer.addWidget(self.question_view)

        # ---- the results ----
        self.results_view = QWidget()
        self.results_layout = QVBoxLayout(self.results_view)
        self.results_layout.setContentsMargins(0, 0, 0, 0)
        self.results_layout.setSpacing(8)
        self.results_view.setVisible(False)
        outer.addWidget(self.results_view)
        outer.addStretch(1)

        self.voice.state_changed.connect(lambda state: self.voice_btn.setEnabled(state == IDLE))

    # ---------------- starting ----------------

    def on_show(self, type: str | None = None, returning: bool = False, **kwargs) -> None:  # noqa: A002
        if returning and (self.results_view.isVisibleTo(self) or self.current is not None):
            return  # back from a career guide (or MAYA): keep the results / the question you were on
        if type:
            self.assessment_type = type
        set_error(self.error, None)
        self.answers, self.skipped, self.history = {}, set(), []
        self.question_view.setVisible(True)
        self.results_view.setVisible(False)
        self.question_label.setText("Getting MAYA's questions ready…")
        if self.bank is None:
            run_async(api_client.assessment_questions, on_success=self._loaded, on_error=self._failed)
        else:
            self._next(intro=True)

    def _loaded(self, bank: dict) -> None:
        self.bank = bank
        if self.isVisible():
            self._next(intro=True)

    # ---------------- which question comes next ----------------

    def _applies(self, question: dict) -> bool:
        requires = question.get("requires") or {}
        return all(self.answers.get(qid) in options for qid, options in requires.items())

    def _remaining(self) -> list[dict]:
        done = set(self.answers) | self.skipped
        return [q for q in self.bank["questions"] if q["id"] not in done and self._applies(q)]

    def _next(self, intro: bool = False) -> None:
        remaining = self._remaining()
        if not remaining:
            self._submit()
            return
        self._show_question(remaining[0], intro=intro)

    def _show_question(self, question: dict, intro: bool = False) -> None:
        self.current = question
        if not self.history or self.history[-1] != question["id"]:
            self.history.append(question["id"])
        self._misses = 0
        set_error(self.error, None)
        asked = len(self.history)
        estimate = asked + len(self._remaining()) - 1
        self.progress_label.setText(f"Question {asked} of about {max(asked, estimate)} · {question['section']}")
        self.progress.setMaximum(max(asked, estimate))
        self.progress.setValue(asked - 1)
        self.question_label.setText(question["text"])
        self.back_btn.setEnabled(len(self.history) > 1)

        clear_layout(self.options_grid)
        options = question["options"]
        # Short answers sit two to a row; long ones get the full width so nothing is cut off.
        columns = 2 if max(len(o["label"]) for o in options) <= 24 and len(options) >= 4 else 1
        chosen = self.answers.get(question["id"])
        for i, option in enumerate(options):
            btn = QPushButton(option["label"])
            btn.setProperty("variant", "choice")
            btn.setProperty("selected", "true" if option["id"] == chosen else "false")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setMinimumHeight(44)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
            btn.clicked.connect(lambda _checked=False, oid=option["id"]: self._choose(oid))
            self.options_grid.addWidget(btn, i // columns, i % columns)
            _repolish(btn)

        self._ask(intro=intro)

    # ---------------- answering ----------------

    def _choose(self, option_id: str) -> None:
        if self.current is None:
            return
        self.voice.cancel()
        self.answers[self.current["id"]] = option_id
        self.skipped.discard(self.current["id"])
        self._drop_stale_follow_ups()
        self._next()

    def _drop_stale_follow_ups(self) -> None:
        """Changing "I love physics" to "I struggle with it" makes the physics follow-ups moot."""
        for q in self.bank["questions"]:
            if q["id"] in self.answers and not self._applies(q):
                del self.answers[q["id"]]

    def _skip(self) -> None:
        if self.current is None:
            return
        self.voice.cancel()
        self.skipped.add(self.current["id"])
        self._next()

    def back_mode(self) -> str:
        return "page" if self.question_view.isVisible() and len(self.history) > 1 else "history"

    def go_back(self) -> None:
        if len(self.history) < 2:
            return
        self.voice.cancel()
        self.history.pop()
        previous = self.history[-1]
        question = next(q for q in self.bank["questions"] if q["id"] == previous)
        # The earlier answer stays (highlighted) until they pick another one.
        self.skipped.discard(previous)
        self._show_question(question)

    # ---------------- voice ----------------

    def _ask(self, intro: bool = False, again: bool = False, retry: bool = False) -> None:
        if self.current is None or not self.isVisible():
            return
        text = self.current["speak"]
        if intro:
            text = ("Let's find careers that fit you. I'll ask about thirty quick questions — just answer "
                    "naturally, or tap. " + text)
        elif retry:
            text = "Sorry, I didn't catch that. " + text
        self.voice.ask(text, on_answer=self._heard, on_no_answer=self._missed)

    def _heard(self, transcript: str) -> None:
        if wants_to_go_back(transcript) and len(self.history) > 1:
            self.go_back()
            return
        if wants_to_skip(transcript):
            self._skip()
            return
        option_id = match_option(transcript, self.current["options"])
        if option_id is None:
            self._missed("unclear")
            return
        self._choose(option_id)

    def _missed(self, reason: str) -> None:
        if reason in ("no_mic", "error"):
            self.hint.setText("Voice isn't available right now — tap an answer instead.")
            return
        self._misses += 1
        if self._misses <= RETRIES:
            self._ask(retry=True)
        else:
            self.hint.setText("No problem — tap an answer, or tap Answer by voice to try again.")

    # ---------------- results ----------------

    def _submit(self) -> None:
        self.voice.cancel()
        self.current = None
        self.question_label.setText("MAYA is working out your matches…")
        self.progress.setValue(self.progress.maximum())
        clear_layout(self.options_grid)
        run_async(
            api_client.submit_career_assessment, self.assessment_type, {"answers": self.answers},
            on_success=self._show_results, on_error=self._failed,
        )

    def _show_results(self, assessment: dict) -> None:
        self.question_view.setVisible(False)
        self.results_view.setVisible(True)
        clear_layout(self.results_layout)

        results = assessment["results"]
        best = results[0]
        self.results_layout.addWidget(heading(f"Your best match: {best['career_name']}"))
        if assessment.get("highlights"):
            self.results_layout.addWidget(subtitle("What stood out: " + ", ".join(assessment["highlights"]) + "."))
        self.results_layout.addWidget(muted(
            "Every career is ranked below, best fit first. Tap any of them for the full guide — how to "
            "start, what to study, and what it pays. This is a guide from your answers, not a verdict; "
            "talk it over with your family."
        ))

        for r in results[:3]:
            self.results_layout.addWidget(self._top_card(r))

        rest = results[3:]
        groups: dict[str, list[dict]] = {}
        for r in rest:
            groups.setdefault(r["fit_label"], []).append(r)
        for label in ("Strong fit", "Good fit", "Worth exploring", "Less likely", "Not a natural fit"):
            if label not in groups:
                continue
            self.results_layout.addWidget(heading(label))
            for r in groups[label]:
                self.results_layout.addWidget(self._compact_row(r))

        again = secondary_button("Take the assessment again")
        again.clicked.connect(lambda: self.on_show())
        self.results_layout.addWidget(again)

        others = [r["career_name"] for r in results[1:3]]
        self.voice.say(
            f"Your best match is {best['career_name']}. "
            + (f"{others[0]} and {others[1]} fit you well too. " if len(others) == 2 else "")
            + "Tap any career to see how to get there."
        )

    def _score_bar(self, r: dict) -> QProgressBar:
        bar = QProgressBar()
        bar.setObjectName("FitBar")
        bar.setRange(0, 100)
        bar.setValue(int(r["fit_score"]))
        bar.setTextVisible(False)
        bar.setFixedHeight(8)
        bar.setStyleSheet(f"QProgressBar#FitBar::chunk {{ background: {LABEL_COLOURS.get(r['fit_label'], '#4f46e5')}; border-radius: 4px; }}")
        return bar

    def _label_chip(self, r: dict) -> QLabel:
        chip = QLabel(f"{r['fit_label']} · {r['fit_score']:.0f}%")
        colour = LABEL_COLOURS.get(r["fit_label"], "#4f46e5")
        chip.setStyleSheet(f"color: {colour}; font-weight: 700;")
        return chip

    def _top_card(self, r: dict) -> Card:
        card = Card()
        title_row = QHBoxLayout()
        title = heading(f"{r['rank']}. {r['career_name']}")
        title_row.addWidget(title, 1)
        title_row.addWidget(self._label_chip(r))
        holder = QWidget()
        holder.setLayout(title_row)
        card.addWidget(holder)
        card.addWidget(self._score_bar(r))
        if r.get("reasons"):
            why = QLabel("✓ " + "\n✓ ".join(reason[0].upper() + reason[1:] for reason in r["reasons"]))
            why.setWordWrap(True)
            card.addWidget(why)
        for w in r.get("watch_outs", []):
            card.addWidget(muted(f"⚠ {w[0].upper() + w[1:]}"))
        guide = primary_button("See how to get there")
        guide.clicked.connect(lambda _checked=False, key=r["career_key"]: self.ctx.navigate("career_detail", key=key))
        card.addWidget(guide)
        return card

    def _compact_row(self, r: dict) -> QWidget:
        btn = QPushButton()
        btn.setProperty("variant", "option")
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(lambda _checked=False, key=r["career_key"]: self.ctx.navigate("career_detail", key=key))
        layout = QVBoxLayout(btn)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(4)
        row = QHBoxLayout()
        name = QLabel(f"{r['rank']}. {r['career_name']}")
        name.setStyleSheet("background: transparent; font-weight: 600;")
        name.setWordWrap(True)
        row.addWidget(name, 1)
        chip = self._label_chip(r)
        chip.setStyleSheet(chip.styleSheet() + " background: transparent;")
        row.addWidget(chip)
        layout.addLayout(row)
        layout.addWidget(self._score_bar(r))
        if r.get("watch_outs"):
            note = QLabel("⚠ " + r["watch_outs"][0])
            note.setWordWrap(True)
            note.setStyleSheet("background: transparent; color: #64748b; font-size: 12px;")
            layout.addWidget(note)
        btn.setMinimumHeight(layout.sizeHint().height())
        return btn

    def _failed(self, err: Exception) -> None:
        message = err.message if isinstance(err, ApiError) else "Couldn't reach MAYA's server just now."
        self.question_view.setVisible(True)
        set_error(self.error, message)
        if self.bank is not None and self.current is None:
            # The answers are all here — only sending them failed. Offer to send again.
            self.question_label.setText("Your answers are saved on this screen.")
            retry = primary_button("Try again")
            retry.clicked.connect(self._submit)
            self.options_grid.addWidget(retry, 0, 0)
