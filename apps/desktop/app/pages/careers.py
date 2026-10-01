"""Careers: every career in MAYA's library, with a way in to the assessments.

Tap a career for its full guide. "Find careers that fit me" opens My assessment, whose checks
turn into career directions — bands with reasons, never a ranking. Careers on the student's own exam track come
first — this page is for exploring, so nothing is hidden, but a NEET student shouldn't have
to scroll past engineering to reach medicine.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from app.api_client import ApiError, api_client
from app.goal import target_exam_code
from app.layout import columns, page_margins
from app.pages.base import BasePage
from app.widgets.common import clear_layout, Card, error_label, heading, muted, primary_button, set_error, subtitle
from app.workers import run_async


class CareersPage(BasePage):
    def __init__(self, ctx):
        super().__init__(ctx)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*page_margins())
        layout.setSpacing(12)

        layout.addWidget(heading("Careers"))
        layout.addWidget(subtitle("Explore any career, or let MAYA find the ones that fit you."))

        start = Card()
        start.addWidget(heading("Not sure what suits you?"))
        start.addWidget(muted(
            "Short checks — what you enjoy, how you think, your skills and marks — turn into career "
            "directions: strong, potential and worth exploring, each with the reasons. Answer by voice or tap."
        ))
        self.start_btn = primary_button("Find careers that fit me")
        self.start_btn.setMinimumHeight(46)
        self.start_btn.clicked.connect(lambda: self.ctx.navigate("assessment"))
        start.addWidget(self.start_btn)
        layout.addWidget(start)

        self.error = error_label()
        layout.addWidget(self.error)
        self.list_holder = QWidget()
        self.list_layout = QVBoxLayout(self.list_holder)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(8)
        layout.addWidget(self.list_holder)
        layout.addStretch(1)

    def on_show(self, type: str | None = None, **kwargs) -> None:  # noqa: A002 — the navigate() kwarg
        if type:
            # Onboarding sends students straight to the assessments.
            self.ctx.navigate("assessment")
            return
        set_error(self.error, None)
        run_async(api_client.list_careers, on_success=self._render, on_error=self._failed)

    def _students_track_first(self, careers: list) -> list:
        target = target_exam_code()
        if not target:
            return careers
        return sorted(careers, key=lambda c: target not in (c.get("typical_entrance_exam_codes") or []))

    def _render(self, careers: list) -> None:
        clear_layout(self.list_layout)
        per_row = columns(2)
        grid = QGridLayout()
        grid.setSpacing(8)
        for i, c in enumerate(self._students_track_first(careers)):
            grid.addWidget(self._card(c), i // per_row, i % per_row)
        holder = QWidget()
        holder.setLayout(grid)
        self.list_layout.addWidget(holder)

    def _card(self, career: dict) -> QPushButton:
        btn = QPushButton()
        btn.setProperty("variant", "option")
        btn.setCursor(Qt.PointingHandCursor)
        btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        inner = QVBoxLayout(btn)
        inner.setContentsMargins(12, 10, 12, 10)
        inner.setSpacing(3)
        name = QLabel(career["name"] + "  ›")
        name.setWordWrap(True)
        name.setStyleSheet("background: transparent; font-weight: 700; font-size: 15px;")
        inner.addWidget(name)
        meta = QLabel(career["category"])
        meta.setStyleSheet("background: transparent; color: #4f46e5; font-size: 12px; font-weight: 600;")
        inner.addWidget(meta)
        desc = QLabel(career.get("description", ""))
        desc.setWordWrap(True)
        desc.setStyleSheet("background: transparent; color: #475569; font-size: 13px;")
        inner.addWidget(desc)
        btn.setMinimumHeight(inner.sizeHint().height() + 6)
        key = career.get("key")
        if key:
            btn.clicked.connect(lambda _checked=False, k=key: self.ctx.navigate("career_detail", key=k))
        return btn

    def _failed(self, err: Exception) -> None:
        set_error(self.error, err.message if isinstance(err, ApiError) else "Couldn't load careers.")
