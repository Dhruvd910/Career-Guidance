"""One assessment's result, and how your results changed between attempts.

Results are shown the way they were measured: "7 of 10 right", "level 3 of 4", "78%", or — for
what you enjoy — a bar per thing, grouped (subjects, the kind of person you are, how you'd like
to work, what matters to you, how you learn). Problems can be gone through afterwards with the
right answers and why. Every result can be deleted.

"How I've changed" only calls something a change when it's bigger than the noise for that
many questions; otherwise it says "about the same".
"""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QVBoxLayout, QWidget

from app.api_client import ApiError, api_client
from app.layout import page_margins
from app.pages.assessments import preferred_language, short_date
from app.pages.base import BasePage
from app.widgets.common import (
    Card, clear_layout, error_label, ghost_button, heading, muted, primary_button, secondary_button,
    set_error, subtitle,
)
from app.workers import run_async

GROUPS = (  # how an interests result is split up, in order
    ("subject", "Subjects and topics you enjoy", "आपको पसंद विषय"),
    ("riasec", "The kind of person you are", "आप किस तरह के इंसान हैं"),
    ("work_style", "How you'd like to work", "आप कैसे काम करना चाहेंगे"),
    ("values", "What matters to you", "आपके लिए क्या ज़रूरी है"),
    ("learning", "How you learn", "आप कैसे सीखते हैं"),
)
CHANGE = {1: ("Improved", "#15803d"), 0: ("About the same", "#64748b"), -1: ("Lower this time", "#a16207")}
CONFIRM_MS = 4000


def score_row(label: str, says: str, score: float) -> QWidget:
    row = QWidget()
    layout = QVBoxLayout(row)
    layout.setContentsMargins(0, 2, 0, 2)
    layout.setSpacing(2)
    top = QHBoxLayout()
    name = QLabel(label[:1].upper() + label[1:])
    name.setWordWrap(True)
    top.addWidget(name, 1)
    value = QLabel(says)
    value.setStyleSheet("font-weight: 700;")
    top.addWidget(value)
    layout.addLayout(top)
    bar = QProgressBar()
    bar.setObjectName("FitBar")
    bar.setRange(0, 100)
    bar.setValue(round(score * 100))
    bar.setTextVisible(False)
    bar.setFixedHeight(8)
    layout.addWidget(bar)
    return row


class AssessmentResultPage(BasePage):
    def __init__(self, ctx):
        super().__init__(ctx)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*page_margins())
        layout.setSpacing(10)
        self.title = heading("")
        layout.addWidget(self.title)
        self.when = subtitle("")
        layout.addWidget(self.when)
        layout.addWidget(muted("This shows how you answered on the day — not a fixed ability, and not a verdict "
                               "on what you should become."))
        self.error = error_label()
        layout.addWidget(self.error)
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(8)
        layout.addWidget(self.body)
        actions = QHBoxLayout()
        directions = primary_button("See my career directions")
        directions.clicked.connect(lambda: self.ctx.navigate("directions"))
        actions.addWidget(directions)
        hub = secondary_button("My assessments")
        hub.clicked.connect(lambda: self.ctx.navigate("assessment"))
        actions.addWidget(hub)
        actions.addStretch(1)
        layout.addLayout(actions)
        self.delete_btn = ghost_button("Delete this result")
        self.delete_btn.clicked.connect(self._delete)
        layout.addWidget(self.delete_btn)
        layout.addStretch(1)
        self.result: dict | None = None
        self._confirming = False

    def on_show(self, result: dict | None = None, attempt_id: int | None = None, fresh: bool = False,
                returning: bool = False, **kwargs) -> None:
        if returning and self.result is not None:
            return
        set_error(self.error, None)
        self._confirming = False
        self.delete_btn.setText("Delete this result")
        if result is not None:
            self._render(result, fresh)
        elif attempt_id is not None:
            clear_layout(self.body_layout)
            self.body_layout.addWidget(muted("Loading…"))
            run_async(api_client.assessment_result, attempt_id, on_success=self._render, on_error=self._failed)

    def _render(self, result: dict, fresh: bool = False) -> None:
        self.result = result
        lang = preferred_language(self.ctx)
        self.title.setText(result["title"][lang])
        self.when.setText(("Taken " + short_date(result.get("completed_at"))) if result.get("completed_at") else "")
        clear_layout(self.body_layout)
        scores = result["scores"]
        if result["method"] == "weighted_options":
            for group, en, hi in GROUPS:
                rows = [s for s in scores if s["group"] == group]
                if not rows:
                    continue
                card = Card()
                card.addWidget(heading(en if lang == "en" else hi))
                for s in rows[:8]:
                    card.addWidget(score_row(s["label"][lang], f"{round(s['score'] * 100)}%", s["score"]))
                self.body_layout.addWidget(card)
        else:
            card = Card()
            for s in scores:
                card.addWidget(score_row(s["label"][lang], s["says"][lang], s["score"]))
            if not scores:
                card.addWidget(muted("Everything was skipped, so there's nothing to show."))
            self.body_layout.addWidget(card)
        if result.get("review"):
            self._review_button(result["review"], lang)
        if fresh:
            done = "All done — here's how it went." if lang == "en" else "हो गया! ये रहे आपके नतीजे।"
            self.ctx.voice.say(done, language=lang)

    def _review_button(self, review: list, lang: str) -> None:
        holder = QWidget()
        holder_layout = QVBoxLayout(holder)
        holder_layout.setContentsMargins(0, 0, 0, 0)
        show = secondary_button("Go through the answers")
        holder_layout.addWidget(show)

        def expand() -> None:
            show.setVisible(False)
            for r in review:
                card = Card()
                card.addWidget(QLabel(("✓  " if r["right"] else "✗  ") + r["prompt"][lang]))
                if r.get("code"):
                    code = QLabel(r["code"])
                    code.setStyleSheet("font-family: 'DejaVu Sans Mono', monospace;")
                    card.addWidget(code)
                labels = {o["key"]: o["label"][lang] for o in r["options"]}
                picked = labels.get(r["picked"], "skipped" if lang == "en" else "छोड़ा")
                card.addWidget(muted(f"You: {picked}   ·   Right answer: {labels[r['answer']]}"))
                if r.get("explanation"):
                    card.addWidget(muted(r["explanation"][lang]))
                holder_layout.addWidget(card)

        show.clicked.connect(expand)
        self.body_layout.addWidget(holder)

    def _delete(self) -> None:
        """Two taps: the first asks, the second deletes."""
        if self.result is None:
            return
        if not self._confirming:
            self._confirming = True
            self.delete_btn.setText("Tap again to delete it for good")
            return
        run_async(api_client.delete_assessment_attempt, self.result["attempt_id"],
                  on_success=lambda _r: self.ctx.navigate("assessment"), on_error=self._failed)

    def _failed(self, err: Exception) -> None:
        set_error(self.error, err.message if isinstance(err, ApiError) else "Couldn't reach MAYA's server just now.")


class AssessmentHistoryPage(BasePage):
    def __init__(self, ctx):
        super().__init__(ctx)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*page_margins())
        layout.setSpacing(10)
        self.title = heading("How I've changed")
        layout.addWidget(self.title)
        self.sub = subtitle("")
        layout.addWidget(self.sub)
        layout.addWidget(muted("A change only counts when it's bigger than the usual ups and downs for that many "
                               "questions — otherwise it's “about the same”."))
        self.error = error_label()
        layout.addWidget(self.error)
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(8)
        layout.addWidget(self.body)
        layout.addStretch(1)

    def on_show(self, key: str | None = None, returning: bool = False, **kwargs) -> None:
        if returning or not key:
            return
        set_error(self.error, None)
        clear_layout(self.body_layout)
        self.body_layout.addWidget(muted("Loading…"))
        run_async(api_client.assessment_history, key, on_success=self._render, on_error=self._failed)

    def _render(self, history: dict) -> None:
        clear_layout(self.body_layout)
        lang = preferred_language(self.ctx)
        attempts = history["attempts"]
        if len(attempts) < 2:
            self.sub.setText("")
            self.body_layout.addWidget(muted("There's nothing to compare yet — take it again in a few weeks."))
            return
        self.title.setText(f"How I've changed — {attempts[-1]['title'][lang]}")
        self.sub.setText(f"First taken {short_date(attempts[0]['completed_at'])}, latest "
                         f"{short_date(attempts[-1]['completed_at'])} ({len(attempts)} times)")
        for heading_text, rows in (("Since the first time", history["since_first"]),
                                   ("Since last time", history["since_previous"] if len(attempts) > 2 else None)):
            if not rows:
                continue
            card = Card()
            card.addWidget(heading(heading_text))
            for row in rows:
                if row["dimension"].startswith("learning:"):
                    continue
                text, colour = CHANGE[row["change"]]
                line = QLabel(f"{row['label'][lang][:1].upper() + row['label'][lang][1:]}:  "
                              f"{row['before'][lang]}  →  {row['after'][lang]}")
                line.setWordWrap(True)
                card.addWidget(line)
                chip = QLabel(text + (f"  ·  {row['note']}" if row.get("note") else ""))
                chip.setStyleSheet(f"color: {colour}; font-weight: 700;")
                card.addWidget(chip)
            self.body_layout.addWidget(card)

    def _failed(self, err: Exception) -> None:
        clear_layout(self.body_layout)
        set_error(self.error, err.message if isinstance(err, ApiError) else "Couldn't reach MAYA's server just now.")
