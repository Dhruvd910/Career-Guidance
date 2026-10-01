"""Sitting a practice paper: one question at a time, a countdown, and a review afterwards.

Laid out for a fingertip on an 800x480 panel — four full-width answer buttons, big Previous/
Next, and a question palette so you can jump around the way you would in the real exam. The
timer runs down from the paper's own length and submits when it reaches zero, like the real
thing; nothing is scored until you submit, and every question is explained afterwards.
"""

from __future__ import annotations

import time

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtWidgets import (
    QGridLayout, QHBoxLayout, QLabel, QMessageBox, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from app.api_client import ApiError, api_client
from app.layout import page_margins
from app.pages.base import BasePage
from app.widgets.common import Card, error_label, ghost_button, heading, muted, primary_button, secondary_button, set_error, subtitle
from app.widgets.icons import mic_icon
from app.workers import run_async

OPTION_LABELS = ["A", "B", "C", "D", "E", "F"]
WARNING_SECONDS = 120  # when the clock turns red


def _clock(seconds: int) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


class PracticeTestPage(BasePage):
    def __init__(self, ctx):
        super().__init__(ctx)
        self.attempt: dict | None = None
        self.answers: dict[int, int] = {}  # question id -> chosen option
        self.index = 0
        self._started_at = 0.0
        self._submitting = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(*page_margins())
        outer.setSpacing(8)

        # ---- the paper ----
        self.test_view = QWidget()
        test_layout = QVBoxLayout(self.test_view)
        test_layout.setContentsMargins(0, 0, 0, 0)
        test_layout.setSpacing(8)

        top = QHBoxLayout()
        self.position_label = QLabel("")
        self.position_label.setStyleSheet("font-weight: 700;")
        top.addWidget(self.position_label)
        self.subject_label = muted("")
        top.addWidget(self.subject_label)
        top.addStretch(1)
        self.timer_label = QLabel("")
        self.timer_label.setObjectName("TestClock")
        top.addWidget(self.timer_label)
        test_layout.addLayout(top)

        self.question_card = Card()
        self.stem_label = QLabel("")
        self.stem_label.setWordWrap(True)
        self.stem_label.setStyleSheet("font-size: 16px; font-weight: 600;")
        self.question_card.addWidget(self.stem_label)
        self.option_buttons: list[QPushButton] = []
        for i in range(4):
            btn = QPushButton("")
            btn.setProperty("variant", "option")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setMinimumHeight(44)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
            btn.clicked.connect(lambda _checked=False, index=i: self._choose(index))
            self.question_card.addWidget(btn)
            self.option_buttons.append(btn)
        test_layout.addWidget(self.question_card)

        self.error = error_label()
        test_layout.addWidget(self.error)

        nav = QHBoxLayout()
        self.prev_btn = secondary_button("← Previous")
        self.prev_btn.clicked.connect(lambda: self._go_to(self.index - 1))
        nav.addWidget(self.prev_btn)
        self.clear_btn = ghost_button("Clear")
        self.clear_btn.clicked.connect(self._clear_answer)
        nav.addWidget(self.clear_btn)
        self.read_btn = ghost_button(" Read aloud")
        self.read_btn.setIcon(mic_icon("#4f46e5"))
        self.read_btn.setIconSize(QSize(16, 16))
        self.read_btn.clicked.connect(self._read_aloud)
        nav.addWidget(self.read_btn)
        nav.addStretch(1)
        self.next_btn = primary_button("Next →")
        self.next_btn.clicked.connect(lambda: self._go_to(self.index + 1))
        nav.addWidget(self.next_btn)
        test_layout.addLayout(nav)

        palette_row = QHBoxLayout()
        self.palette_toggle = ghost_button("All questions")
        self.palette_toggle.clicked.connect(self._toggle_palette)
        palette_row.addWidget(self.palette_toggle)
        palette_row.addStretch(1)
        self.submit_btn = primary_button("Submit test")
        self.submit_btn.clicked.connect(self._confirm_submit)
        palette_row.addWidget(self.submit_btn)
        test_layout.addLayout(palette_row)

        self.palette = QWidget()
        self.palette_grid = QGridLayout(self.palette)
        self.palette_grid.setContentsMargins(0, 0, 0, 0)
        self.palette_grid.setSpacing(6)
        self.palette.setVisible(False)
        test_layout.addWidget(self.palette)
        self.palette_buttons: list[QPushButton] = []

        outer.addWidget(self.test_view)

        # ---- the result ----
        self.result_view = QWidget()
        self.result_layout = QVBoxLayout(self.result_view)
        self.result_layout.setContentsMargins(0, 0, 0, 0)
        self.result_layout.setSpacing(8)
        self.result_view.setVisible(False)
        outer.addWidget(self.result_view)
        outer.addStretch(1)

        self.clock = QTimer(self)
        self.clock.setInterval(1000)
        self.clock.timeout.connect(self._tick)

    # ---------------- starting ----------------

    def on_show(self, attempt: dict | None = None, summary: dict | None = None, **kwargs) -> None:
        set_error(self.error, None)
        if summary is not None:
            self._show_result(summary)
            return
        if attempt is None:
            self.ctx.navigate("mock_tests")
            return
        self.attempt = attempt
        self.answers = {}
        self.index = 0
        self._submitting = False
        self._started_at = time.monotonic()
        self.submit_btn.setEnabled(True)
        self.submit_btn.setText("Submit test")
        self.test_view.setVisible(True)
        self.result_view.setVisible(False)
        self._build_palette()
        self._render_question()
        self.clock.start()
        self._tick()
        self.ctx.refresh_chrome()  # the sidebar steps aside while a paper is being sat

    @property
    def questions(self) -> list[dict]:
        return (self.attempt or {}).get("questions", [])

    def _seconds_left(self) -> int:
        if not self.attempt:
            return 0
        return int(self.attempt["duration_seconds"] - (time.monotonic() - self._started_at))

    def _tick(self) -> None:
        left = self._seconds_left()
        self.timer_label.setText(f"⏱ {_clock(left)}")
        self.timer_label.setProperty("warning", "true" if left <= WARNING_SECONDS else "false")
        self.timer_label.style().unpolish(self.timer_label)
        self.timer_label.style().polish(self.timer_label)
        if left <= 0 and not self._submitting:
            self.clock.stop()
            self._submit()  # time's up, exactly like the real exam

    # ---------------- one question ----------------

    def _render_question(self) -> None:
        question = self.questions[self.index]
        self.position_label.setText(f"Question {self.index + 1} of {len(self.questions)}")
        topic = f" · {question['topic']}" if question.get("topic") else ""
        self.subject_label.setText(f"{question['subject']}{topic}")
        self.stem_label.setText(question["stem"])

        chosen = self.answers.get(question["id"])
        for i, btn in enumerate(self.option_buttons):
            if i < len(question["options"]):
                btn.setText(f"{OPTION_LABELS[i]}.  {question['options'][i]}")
                btn.setVisible(True)
                btn.setProperty("selected", "true" if chosen == i else "false")
                btn.style().unpolish(btn)
                btn.style().polish(btn)
            else:
                btn.setVisible(False)

        self.prev_btn.setEnabled(self.index > 0)
        self.next_btn.setEnabled(self.index < len(self.questions) - 1)
        self.clear_btn.setEnabled(chosen is not None)
        self._refresh_palette()

    def _choose(self, option_index: int) -> None:
        question = self.questions[self.index]
        self.answers[question["id"]] = option_index
        # Straight on to the next question, the way you'd expect on a phone — the last one
        # stays put so the Submit button is right there.
        if self.index < len(self.questions) - 1:
            self._go_to(self.index + 1)
        else:
            self._render_question()

    def _clear_answer(self) -> None:
        self.answers.pop(self.questions[self.index]["id"], None)
        self._render_question()

    def _go_to(self, index: int) -> None:
        if 0 <= index < len(self.questions):
            self.index = index
            self.ctx.voice.cancel()
            self._render_question()

    def _read_aloud(self) -> None:
        question = self.questions[self.index]
        options = ". ".join(f"Option {OPTION_LABELS[i]}: {text}" for i, text in enumerate(question["options"]))
        self.ctx.voice.say(f"{question['stem']}. {options}")

    # ---------------- palette ----------------

    def _build_palette(self) -> None:
        while self.palette_grid.count():
            item = self.palette_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.palette_buttons = []
        for i in range(len(self.questions)):
            btn = QPushButton(str(i + 1))
            btn.setObjectName("PaletteKey")
            btn.setFixedSize(40, 34)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _checked=False, index=i: self._jump(index))
            self.palette_grid.addWidget(btn, i // 10, i % 10)
            self.palette_buttons.append(btn)

    def _jump(self, index: int) -> None:
        self._go_to(index)
        self.palette.setVisible(False)

    def _toggle_palette(self) -> None:
        self.palette.setVisible(not self.palette.isVisible())
        self._refresh_palette()

    def _refresh_palette(self) -> None:
        for i, btn in enumerate(self.palette_buttons):
            answered = self.questions[i]["id"] in self.answers
            btn.setProperty("state", "current" if i == self.index else ("answered" if answered else "blank"))
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        answered = len(self.answers)
        self.palette_toggle.setText(f"All questions ({answered}/{len(self.questions)} answered)")

    # ---------------- submitting ----------------

    def _confirm_submit(self) -> None:
        blank = len(self.questions) - len(self.answers)
        question = QMessageBox(self)
        question.setWindowTitle("Submit test")
        question.setText(
            f"Submit now with {blank} question{'s' if blank != 1 else ''} unanswered?"
            if blank else "Submit your answers?"
        )
        question.setStandardButtons(QMessageBox.Cancel | QMessageBox.Ok)
        question.button(QMessageBox.Ok).setText("Submit")
        if question.exec() == QMessageBox.Ok:
            self._submit()

    def _submit(self) -> None:
        if self._submitting or self.attempt is None:
            return
        self._submitting = True
        self.clock.stop()
        self.ctx.voice.cancel()
        self.submit_btn.setEnabled(False)
        self.submit_btn.setText("Marking…")
        answers = [
            {"question_id": q["id"], "selected_index": self.answers.get(q["id"])}
            for q in self.questions
        ]
        taken = int(time.monotonic() - self._started_at)
        run_async(
            api_client.submit_practice, self.attempt["attempt_id"], answers, taken,
            on_success=self._show_result, on_error=self._failed,
        )

    def _failed(self, err: Exception) -> None:
        self._submitting = False
        self.submit_btn.setEnabled(True)
        self.submit_btn.setText("Submit test")
        self.clock.start()
        set_error(self.error, err.message if isinstance(err, ApiError) else "Could not submit the test.")

    # ---------------- the result ----------------

    def _show_result(self, summary: dict) -> None:
        self.clock.stop()
        self.attempt = None
        self.test_view.setVisible(False)
        self.result_view.setVisible(True)
        self.ctx.refresh_chrome()
        while self.result_layout.count():
            item = self.result_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        score_card = Card()
        score_card.addWidget(heading(f"{summary['score']:g} / {summary['max_score']:g}"))
        score_card.addWidget(subtitle(summary["title"]))
        counts = QLabel(
            f"✓ {summary['correct']} correct   ✗ {summary['wrong']} wrong   "
            f"– {summary['unanswered']} unanswered"
        )
        counts.setWordWrap(True)
        score_card.addWidget(counts)
        taken = summary.get("seconds_taken")
        score_card.addWidget(muted(
            f"Accuracy {summary['accuracy']}%"
            + (f" · took {_clock(taken)} of {_clock(summary['duration_seconds'])}" if taken else "")
            + " · +4 for a correct answer, −1 for a wrong one"
        ))
        self.result_layout.addWidget(score_card)

        if len(summary.get("subject_scores", [])) > 1:
            subject_card = Card()
            subject_card.addWidget(heading("By subject"))
            for row in summary["subject_scores"]:
                subject_card.addWidget(QLabel(
                    f"{row['subject']}: {row['score']:g}/{row['max_score']:g} "
                    f"({row['correct']} right, {row['wrong']} wrong, {row['unanswered']} blank)"
                ))
            self.result_layout.addWidget(subject_card)

        weakest = self._weakest_subject(summary)
        if weakest:
            self.result_layout.addWidget(muted(f"Weakest this time: {weakest}. Worth another subject test."))

        self.result_layout.addWidget(heading("Review every question"))
        for item in summary.get("review", []):
            self.result_layout.addWidget(self._review_card(item))

        actions = QHBoxLayout()
        again = primary_button("Practise again")
        again.clicked.connect(lambda: self.ctx.navigate("mock_tests"))
        actions.addWidget(again)
        done = secondary_button("Back to dashboard")
        done.clicked.connect(lambda: self.ctx.navigate("dashboard"))
        actions.addWidget(done)
        actions.addStretch(1)
        actions_widget = QWidget()
        actions_widget.setLayout(actions)
        self.result_layout.addWidget(actions_widget)

    @staticmethod
    def _weakest_subject(summary: dict) -> str | None:
        rows = [r for r in summary.get("subject_scores", []) if r["max_score"]]
        if len(rows) < 2:
            return None
        worst = min(rows, key=lambda r: r["score"] / r["max_score"])
        return worst["subject"]

    def _review_card(self, item: dict) -> Card:
        card = Card()
        header = QLabel(f"Q{item['position'] + 1} · {item['subject']}")
        header.setStyleSheet("font-weight: 700;")
        card.addWidget(header)
        stem = QLabel(item["stem"])
        stem.setWordWrap(True)
        card.addWidget(stem)

        correct_text = f"{OPTION_LABELS[item['correct_index']]}. {item['options'][item['correct_index']]}"
        if item["selected_index"] is None:
            verdict = QLabel(f"You left this blank. Correct answer: {correct_text}")
            colour = "#a16207"
        elif item["is_correct"]:
            verdict = QLabel(f"✓ Correct: {correct_text}")
            colour = "#15803d"
        else:
            chosen = f"{OPTION_LABELS[item['selected_index']]}. {item['options'][item['selected_index']]}"
            verdict = QLabel(f"✗ You chose {chosen}\nCorrect answer: {correct_text}")
            colour = "#b91c1c"
        verdict.setWordWrap(True)
        verdict.setStyleSheet(f"color: {colour}; font-weight: 600;")
        card.addWidget(verdict)

        if item.get("explanation"):
            card.addWidget(muted(item["explanation"]))
        return card

    # ---------------- leaving mid-test ----------------

    def back_mode(self) -> str:
        return "page" if self.attempt is not None else "history"

    def go_back(self) -> None:
        confirm = QMessageBox(self)
        confirm.setWindowTitle("Leave the test?")
        confirm.setText("Your answers so far won't be marked. Leave this test?")
        confirm.setStandardButtons(QMessageBox.Cancel | QMessageBox.Ok)
        confirm.button(QMessageBox.Ok).setText("Leave")
        if confirm.exec() == QMessageBox.Ok:
            self.clock.stop()
            self.attempt = None
            self.ctx.navigate("mock_tests")
