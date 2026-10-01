"""Careers: every career in MAYA's library, by domain (spec §11's exploration tree), with ways in.

Technology → Software, AI & Data, Cybersecurity, Robotics, Design; Engineering → …; Medicine &
Health → … A career can sit in two domains. Tap one for how people get there, the skills it
needs and the colleges that offer it — no assessment needed. "Find careers that fit me" opens My
assessment; "What does each stream keep open?" opens the stream explorer. Domains with careers
on the student's own exam track come first: nothing is hidden, but a NEET student shouldn't have
to scroll past engineering to reach medicine.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from app.api_client import ApiError, api_client
from app.goal import target_exam_code
from app.layout import columns, page_margins
from app.pages.assessments import preferred_language
from app.pages.base import BasePage
from app.widgets.common import (
    clear_layout, Card, error_label, heading, muted, primary_button, secondary_button, set_error, subtitle,
)
from app.workers import run_async


def _tree_and_library() -> tuple[dict, list]:
    return api_client.career_explore(), api_client.list_careers()


class CareersPage(BasePage):
    def __init__(self, ctx):
        super().__init__(ctx)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*page_margins())
        layout.setSpacing(12)

        layout.addWidget(heading("Careers"))
        layout.addWidget(subtitle("Explore any career by area, or let MAYA find the ones that fit you."))

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
        self.streams_btn = secondary_button("Choosing a stream? See what each one keeps open")
        self.streams_btn.clicked.connect(lambda: self.ctx.navigate("streams"))
        start.addWidget(self.streams_btn)
        layout.addWidget(start)

        self.error = error_label()
        layout.addWidget(self.error)
        self.list_holder = QWidget()
        self.list_layout = QVBoxLayout(self.list_holder)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(8)
        layout.addWidget(self.list_holder)
        layout.addStretch(1)

    def on_show(self, type: str | None = None, returning: bool = False, **kwargs) -> None:  # noqa: A002 — the navigate() kwarg
        if type:
            # Onboarding sends students straight to the assessments.
            self.ctx.navigate("assessment")
            return
        if returning and self.list_layout.count():
            return
        set_error(self.error, None)
        run_async(_tree_and_library, on_success=self._render, on_error=self._failed)

    def _on_track_first(self, domains: list, library: dict) -> list:
        target = target_exam_code()
        if not target:
            return domains
        return sorted(domains, key=lambda d: not any(
            target in (library.get(c["key"].split(":", 1)[1], {}).get("typical_entrance_exam_codes") or [])
            for c in d["careers"]))

    def _render(self, result: tuple) -> None:
        tree, careers = result
        library = {c.get("key"): c for c in careers}
        lang = preferred_language(self.ctx)
        clear_layout(self.list_layout)
        per_row = columns(2)
        for domain in self._on_track_first(tree["domains"], library):
            if not domain["careers"]:
                continue
            self.list_layout.addWidget(heading(domain["name"][lang]))
            grid = QGridLayout()
            grid.setSpacing(8)
            for i, c in enumerate(domain["careers"]):
                grid.addWidget(self._card(c, library.get(c["key"].split(":", 1)[1], {}), lang), i // per_row, i % per_row)
            holder = QWidget()
            holder.setLayout(grid)
            self.list_layout.addWidget(holder)

    def _card(self, node: dict, career: dict, lang: str) -> QPushButton:
        btn = QPushButton()
        btn.setProperty("variant", "option")
        btn.setCursor(Qt.PointingHandCursor)
        btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        inner = QVBoxLayout(btn)
        inner.setContentsMargins(12, 10, 12, 10)
        inner.setSpacing(3)
        name = QLabel(node["name"][lang] + "  ›")
        name.setWordWrap(True)
        name.setStyleSheet("background: transparent; font-weight: 700; font-size: 15px;")
        inner.addWidget(name)
        if career.get("description"):
            desc = QLabel(career["description"])
            desc.setWordWrap(True)
            desc.setStyleSheet("background: transparent; color: #475569; font-size: 13px;")
            inner.addWidget(desc)
        for label in btn.findChildren(QLabel):
            label.setAttribute(Qt.WA_TransparentForMouseEvents)
        btn.setMinimumHeight(inner.sizeHint().height() + 6)
        key = node["key"].split(":", 1)[1]
        btn.clicked.connect(lambda _checked=False, k=key: self.ctx.navigate("direction", key=k))
        return btn

    def _failed(self, err: Exception) -> None:
        set_error(self.error, err.message if isinstance(err, ApiError) else "Couldn't load careers.")
