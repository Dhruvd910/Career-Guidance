"""One career, in full: what it is, how to prepare, where to start this week, entrance exams,
free resources, the jobs it leads to, the future, and what it pays — with where those
numbers came from.

The kiosk has no web browser, so links open as a big URL (and a QR code when available)
to scan with a phone.
"""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.api_client import ApiError, api_client
from app.layout import page_margins
from app.pages.base import BasePage
from app.widgets.common import (
    clear_layout,
    Card, error_label, ghost_button, heading, muted, primary_button, secondary_button, set_error, subtitle,
)
from app.widgets.links import link_row
from app.workers import run_async


def _bullets(items: list[str], numbered: bool = False) -> QLabel:
    lines = [f"{i + 1}. {t}" if numbered else f"•  {t}" for i, t in enumerate(items)]
    label = QLabel("\n".join(lines))
    label.setWordWrap(True)
    return label


class CareerDetailPage(BasePage):
    def __init__(self, ctx):
        super().__init__(ctx)
        self.career: dict | None = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(*page_margins())
        outer.setSpacing(10)
        self.error = error_label()
        outer.addWidget(self.error)
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(10)
        outer.addWidget(self.body)
        outer.addStretch(1)

    def on_show(self, key: str | None = None, **kwargs) -> None:
        set_error(self.error, None)
        if not key:
            self.ctx.navigate("careers")
            return
        self._clear()
        self.body_layout.addWidget(muted("Loading…"))
        run_async(api_client.career_by_key, key, on_success=self._render, on_error=self._failed)

    def _clear(self) -> None:
        clear_layout(self.body_layout)

    def _section(self, title: str) -> Card:
        card = Card()
        card.addWidget(heading(title))
        self.body_layout.addWidget(card)
        return card

    def _render(self, career: dict) -> None:
        self.career = career
        self._clear()
        d = career.get("details") or {}

        self.body_layout.addWidget(heading(career["name"]))
        self.body_layout.addWidget(subtitle(career["category"]))
        if career.get("key"):
            learn = primary_button("▶  What to learn for this career — videos")
            learn.clicked.connect(lambda: self.ctx.navigate("learn", career=career["key"]))
            self.body_layout.addWidget(learn)
        if d.get("overview"):
            overview = QLabel(d["overview"])
            overview.setWordWrap(True)
            self.body_layout.addWidget(overview)

        actions = QHBoxLayout()
        read = secondary_button("Read it to me")
        read.clicked.connect(self._read_aloud)
        actions.addWidget(read)
        ask = primary_button("Ask MAYA about it")
        ask.clicked.connect(lambda: self.ctx.navigate(
            "maya", ask=f"How do I become a professional in {career['name']}? What should I do first?"))
        actions.addWidget(ask)
        actions.addStretch(1)
        holder = QWidget()
        holder.setLayout(actions)
        self.body_layout.addWidget(holder)

        if d.get("start_now"):
            card = self._section("Start this week")
            card.addWidget(_bullets(d["start_now"]))
        if d.get("how_to_prepare"):
            card = self._section("How to prepare, step by step")
            card.addWidget(_bullets(d["how_to_prepare"], numbered=True))
            if career.get("timeline"):
                card.addWidget(muted(f"Time it takes: {career['timeline']}"))
        if d.get("entrance_exams"):
            card = self._section("Entrance exams")
            for exam in d["entrance_exams"]:
                card.addWidget(self._link_row(exam["name"], exam.get("note", ""), exam["url"]))
        if d.get("resources"):
            card = self._section("Where to learn (free)")
            for r in d["resources"]:
                card.addWidget(self._link_row(r["name"], r.get("kind", ""), r["url"]))
        if d.get("day_in_life"):
            card = self._section("A day in the job")
            text = QLabel(d["day_in_life"])
            text.setWordWrap(True)
            card.addWidget(text)
        if d.get("roles") or d.get("sectors"):
            card = self._section("Jobs you can do")
            if d.get("roles"):
                card.addWidget(_bullets(d["roles"]))
            if d.get("sectors"):
                card.addWidget(muted("Where you'd work: " + ", ".join(d["sectors"])))
        if d.get("after_completion"):
            card = self._section("After you finish, you can become")
            card.addWidget(_bullets(d["after_completion"]))
        if d.get("future_scope"):
            card = self._section("The future of this career")
            text = QLabel(d["future_scope"])
            text.setWordWrap(True)
            card.addWidget(text)
        if d.get("earnings"):
            self._earnings(d["earnings"])
        if career.get("possible_challenges"):
            card = self._section("Things to be ready for")
            card.addWidget(_bullets(career["possible_challenges"]))

        back = secondary_button("←  Back")
        back.clicked.connect(self.ctx.go_back)
        self.body_layout.addWidget(back)

    def _earnings(self, e: dict) -> None:
        card = self._section("What it pays (India)")
        for label, key in (("Starting out", "entry"), ("With experience", "mid"), ("Senior", "senior")):
            if e.get(key):
                row = QLabel(f"<b>{label}:</b> {e[key]}")
                row.setWordWrap(True)
                card.addWidget(row)
        if e.get("note"):
            card.addWidget(muted(e["note"]))
        if e.get("sources"):
            card.addWidget(muted("Figures are indicative ranges gathered in 2025–26 and vary by city, employer and skill. Sources:"))
            for s in e["sources"]:
                card.addWidget(self._link_row(s["name"], "", s["url"], compact=True))
        else:
            card.addWidget(muted("Indicative range; MAYA hasn't attached a published source for this one yet."))

    def _link_row(self, title: str, note: str, url: str, compact: bool = False) -> QWidget:
        return link_row(title, note, url, self, compact)

    def _read_aloud(self) -> None:
        if not self.career:
            return
        d = self.career.get("details") or {}
        parts = [self.career["name"] + ".", d.get("overview", "")]
        if d.get("start_now"):
            parts.append("To start this week: " + "; ".join(d["start_now"]) + ".")
        if d.get("earnings", {}).get("entry"):
            parts.append("Starting pay: " + d["earnings"]["entry"].replace("₹", "rupees ").replace("LPA", "lakh a year") + ".")
        self.ctx.voice.say(" ".join(p for p in parts if p))

    def _failed(self, err: Exception) -> None:
        self._clear()
        set_error(self.error, err.message if isinstance(err, ApiError) else "Couldn't load this career.")
