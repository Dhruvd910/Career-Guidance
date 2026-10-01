"""My assessment: the five checks, what you've done, and the way into your career directions.

Each check is a card — what it is, how long it takes, when you last took it — with Start,
Continue (an unfinished one picks up where you stopped) or Take again, its latest result, and
"How I've changed" once there are two. The questions can be in English or Hindi.
"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from app.api_client import ApiError, api_client
from app.layout import page_margins
from app.pages.base import BasePage
from app.widgets.common import (
    Card, clear_layout, error_label, ghost_button, heading, muted, primary_button, secondary_button, set_error,
    subtitle,
)
from app.workers import run_async

LANGUAGES = (("en", "English"), ("hi", "हिंदी"))


def short_date(value: str | None) -> str:
    if not value:
        return ""
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%-d %b")
    except ValueError:
        return ""


def preferred_language(ctx) -> str:
    """The language questions are asked in: chosen here, else how the student talks to MAYA."""
    chosen = getattr(ctx, "assessment_language", None)
    if chosen:
        return chosen
    maya = getattr(ctx, "pages", {}).get("maya")
    return "hi" if getattr(maya, "language", "en") in ("hi", "hinglish") else "en"


class AssessmentsPage(BasePage):
    def __init__(self, ctx):
        super().__init__(ctx)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*page_margins())
        layout.setSpacing(10)
        layout.addWidget(heading("My assessment"))
        layout.addWidget(subtitle("Five short checks, in any order. Each one makes your career directions clearer — "
                                  "none of them decides anything for you."))

        language_row = QHBoxLayout()
        language_row.addWidget(muted("Questions in:"))
        self.language_buttons = {}
        for code, label in LANGUAGES:
            button = secondary_button(label)
            button.setCheckable(True)
            button.clicked.connect(lambda _c=False, c=code: self.set_language(c))
            language_row.addWidget(button)
            self.language_buttons[code] = button
        language_row.addStretch(1)
        layout.addLayout(language_row)

        self.directions_btn = primary_button("See my career directions")
        self.directions_btn.setMinimumHeight(44)
        self.directions_btn.clicked.connect(lambda: self.ctx.navigate("directions"))
        layout.addWidget(self.directions_btn)

        self.error = error_label()
        layout.addWidget(self.error)
        self.list_holder = QWidget()
        self.list_layout = QVBoxLayout(self.list_holder)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(8)
        layout.addWidget(self.list_holder)
        layout.addStretch(1)
        self.instruments: list[dict] = []

    def set_language(self, code: str) -> None:
        self.ctx.assessment_language = code
        for c, button in self.language_buttons.items():
            button.setChecked(c == code)
        if self.instruments:
            self._render(self.instruments)

    def on_show(self, **kwargs) -> None:  # an old link may pass type=…: every check is here now
        self.set_language(preferred_language(self.ctx))
        set_error(self.error, None)
        clear_layout(self.list_layout)
        self.list_layout.addWidget(muted("Loading…"))
        run_async(api_client.assessment_instruments, on_success=self._render, on_error=self._failed)

    def _render(self, instruments: list) -> None:
        self.instruments = instruments
        clear_layout(self.list_layout)
        interests_done = any(i["key"] == "interests" and i["last_completed"] for i in instruments)
        self.directions_btn.setEnabled(interests_done)
        self.directions_btn.setText("See my career directions" if interests_done
                                    else "Career directions — start with “What you enjoy”")
        for instrument in instruments:
            self.list_layout.addWidget(self._card(instrument))

    def _card(self, instrument: dict) -> Card:
        card = Card()
        lang = preferred_language(self.ctx)
        minutes = f"about {instrument['est_minutes']} min" if lang == "en" else f"लगभग {instrument['est_minutes']} मिनट"
        card.addWidget(heading(f"{instrument['title'][lang]}  ·  {minutes}"))
        card.addWidget(muted(instrument["about"][lang]))
        done, unfinished = instrument["last_completed"], instrument["in_progress"]
        if unfinished:
            status = f"Unfinished — {unfinished['answered']} answered. It picks up where you stopped."
        elif done:
            times = instrument["times_taken"]
            status = f"Last taken {short_date(done['completed_at'])}" + (f" · {times} times" if times > 1 else "")
        else:
            status = "Not taken yet"
        card.addWidget(muted(status))

        row = QHBoxLayout()
        go = primary_button("Continue" if unfinished else "Take again" if done else "Start")
        go.clicked.connect(lambda _c=False, k=instrument["key"]: self.ctx.navigate(
            "assessment_run", key=k, language=preferred_language(self.ctx)))
        row.addWidget(go)
        if done:
            result = secondary_button("My result")
            result.clicked.connect(lambda _c=False, a=done["attempt_id"]: self.ctx.navigate("assessment_result",
                                                                                         attempt_id=a))
            row.addWidget(result)
        if instrument["times_taken"] >= 2:
            changed = ghost_button("How I've changed")
            changed.clicked.connect(lambda _c=False, k=instrument["key"]: self.ctx.navigate("assessment_history", key=k))
            row.addWidget(changed)
        row.addStretch(1)
        holder = QWidget()
        holder.setLayout(row)
        card.addWidget(holder)
        return card

    def _failed(self, err: Exception) -> None:
        clear_layout(self.list_layout)
        set_error(self.error, err.message if isinstance(err, ApiError) else "Couldn't reach MAYA's server just now.")
