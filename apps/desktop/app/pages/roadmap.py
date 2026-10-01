"""The roadmap: where you are on the way to your goal, and exactly what to study next.

For a JEE or NEET student it's a chapter-by-chapter plan: each subject, every NCERT chapter in
the order to cover it, which book and chapter to learn it from, which chapters carry the most
marks, free resources (shown as QR codes to open on a phone), and a one-tap practice test for
the subject. Students still exploring get the milestones and a nudge towards the career
assessment instead.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from app.api_client import ApiError, api_client
from app.layout import page_margins
from app.pages.base import BasePage
from app.widgets.common import (
    Card, clear_layout, error_label, heading, muted, primary_button, secondary_button, set_error, subtitle,
)
from app.widgets.links import link_row
from app.workers import run_async

STATUS_MARK = {"done": "✓", "current": "▶", "upcoming": "○"}
STATUS_COLOUR = {"done": "#15803d", "current": "#4f46e5", "upcoming": "#94a3b8"}


class RoadmapPage(BasePage):
    def __init__(self, ctx):
        super().__init__(ctx)
        self.plan: dict | None = None
        self.subject_index = 0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*page_margins())
        layout.setSpacing(10)
        self.title = heading("My Roadmap")
        layout.addWidget(self.title)
        self.subtitle_label = subtitle("")
        layout.addWidget(self.subtitle_label)
        self.error = error_label()
        layout.addWidget(self.error)
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(10)
        layout.addWidget(self.body)
        layout.addStretch(1)

    def on_show(self, returning: bool = False, **kwargs) -> None:
        if returning and self.plan is not None:
            return
        set_error(self.error, None)
        run_async(api_client.get_roadmap, on_success=self._render, on_error=self._failed)

    # ---------------- the whole page ----------------

    def _render(self, roadmap: dict) -> None:
        clear_layout(self.body_layout)
        self.plan = roadmap.get("study_plan")
        self.subtitle_label.setText(f"Now: {roadmap['current_milestone']}. Next: {roadmap['next_action']}")
        self._milestones(roadmap["steps"])
        if self.plan:
            self.title.setText(f"My {self.plan['exam_name']} Roadmap")
            self._phases()
            self.subject_holder = QWidget()
            self.subject_layout = QVBoxLayout(self.subject_holder)
            self.subject_layout.setContentsMargins(0, 0, 0, 0)
            self.subject_layout.setSpacing(8)
            self._subject_tabs()
            self.body_layout.addWidget(self.subject_holder)
            self._show_subject(self.subject_index)
            sources = Card()
            sources.addWidget(heading("Where this plan comes from"))
            sources.addWidget(muted(self.plan["note"]))
            for src in self.plan["sources"]:
                sources.addWidget(link_row(src["name"], "", src["url"], self, compact=True))
            self.body_layout.addWidget(sources)
        else:
            self.title.setText("My Roadmap")
            card = Card()
            card.addWidget(heading("Want a study plan?"))
            card.addWidget(muted(
                "Once you pick JEE or NEET as your goal, this page becomes a chapter-by-chapter plan — "
                "what to study, where to learn it, and what carries the most marks. Not sure yet? "
                "MAYA's career assessment can help you decide."
            ))
            row = QHBoxLayout()
            assess = primary_button("Find careers that fit me")
            assess.clicked.connect(lambda: self.ctx.navigate("assessment"))
            row.addWidget(assess)
            goal = secondary_button("Choose JEE or NEET")
            goal.clicked.connect(lambda: self.ctx.navigate("onboarding"))
            row.addWidget(goal)
            holder = QWidget()
            holder.setLayout(row)
            card.addWidget(holder)
            self.body_layout.addWidget(card)

    def _milestones(self, steps: list[dict]) -> None:
        card = Card()
        card.addWidget(heading("Milestones"))
        for step in steps:
            row = QLabel(f"<span style='color:{STATUS_COLOUR[step['status']]}; font-weight:700'>"
                         f"{STATUS_MARK[step['status']]}</span>&nbsp; <b>{step['title']}</b>"
                         + (f" — {step['description']}" if step["status"] == "current" else ""))
            row.setWordWrap(True)
            card.addWidget(row)
        self.body_layout.addWidget(card)

    def _phases(self) -> None:
        card = Card()
        card.addWidget(heading("How to pace it"))
        for phase in self.plan["phases"]:
            row = QLabel(f"<b>{phase['title']}:</b> {phase['detail']}")
            row.setWordWrap(True)
            card.addWidget(row)
        self.body_layout.addWidget(card)

    # ---------------- one subject at a time ----------------

    def _subject_tabs(self) -> None:
        row = QHBoxLayout()
        row.setSpacing(8)
        self.subject_buttons = []
        for i, subject in enumerate(self.plan["subjects"]):
            btn = QPushButton(subject["name"])
            btn.setProperty("variant", "choice")
            btn.setMinimumHeight(44)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _checked=False, index=i: self._show_subject(index))
            row.addWidget(btn)
            self.subject_buttons.append(btn)
        holder = QWidget()
        holder.setLayout(row)
        self.body_layout.addWidget(holder)

    def _show_subject(self, index: int) -> None:
        self.subject_index = index = min(index, len(self.plan["subjects"]) - 1)
        for i, btn in enumerate(self.subject_buttons):
            btn.setProperty("selected", "true" if i == index else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        clear_layout(self.subject_layout)
        subject = self.plan["subjects"][index]

        practise = primary_button(f"Practise {subject['name']} now (10 questions)")
        practise.clicked.connect(lambda: self._practise(subject["name"]))
        self.subject_layout.addWidget(practise)

        for tip in subject.get("tips", []):
            self.subject_layout.addWidget(muted(f"💡 {tip}"))

        for block in subject["classes"]:
            card = Card()
            high = sum(1 for c in block["chapters"] if c["weight"] == "high")
            card.addWidget(heading(f"{block['focus']}"))
            card.addWidget(muted(f"{len(block['chapters'])} chapters · ★ {high} carry the most marks"))
            for i, chapter in enumerate(block["chapters"], start=1):
                star = "★ " if chapter["weight"] == "high" else ""
                row = QLabel(f"<b>{i}. {star}{chapter['name']}</b><br>"
                             f"<span style='color:#64748b; font-size:12px'>Learn from: {chapter['where']}</span>")
                row.setWordWrap(True)
                row.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
                card.addWidget(row)
            self.subject_layout.addWidget(card)

        if subject.get("extra"):
            card = Card()
            card.addWidget(heading("Also in the exam syllabus"))
            for item in subject["extra"]:
                text = QLabel(f"•  {item}")
                text.setWordWrap(True)
                card.addWidget(text)
            self.subject_layout.addWidget(card)

        card = Card()
        card.addWidget(heading(f"Free resources for {subject['name']}"))
        for r in subject.get("resources", []):
            card.addWidget(link_row(r["name"], r.get("kind", ""), r["url"], self))
        self.subject_layout.addWidget(card)

    def _practise(self, subject: str) -> None:
        exam = self.plan["exam"]
        # JEE Advanced shares the JEE question bank.
        run_async(api_client.start_practice, exam, "subject", subject,
                  on_success=lambda attempt: self.ctx.navigate("practice_test", attempt=attempt),
                  on_error=self._failed)

    def _failed(self, err: Exception) -> None:
        set_error(self.error, err.message if isinstance(err, ApiError) else "Could not load your roadmap.")
