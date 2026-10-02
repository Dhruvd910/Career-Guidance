"""My shortlist: the colleges the student saved, each with the facts that matter when choosing —
fees, hostel, medical facility, nearest station, NIRF — and where each comes from and how fresh it
is. Tap a college for its page; Compare puts them side by side."""

from __future__ import annotations

from PySide6.QtWidgets import QVBoxLayout, QWidget

from app.api_client import ApiError, api_client
from app.layout import page_margins
from app.pages.assessments import preferred_language
from app.pages.base import BasePage
from app.pages.directions import link_button, words
from app.widgets.common import Card, clear_layout, error_label, heading, muted, primary_button, set_error, subtitle
from app.widgets.facts import cell_text
from app.workers import run_async


class ShortlistPage(BasePage):
    def __init__(self, ctx):
        super().__init__(ctx)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*page_margins())
        layout.setSpacing(10)
        layout.addWidget(heading("My shortlist"))
        layout.addWidget(subtitle("Colleges you're considering, with where each fact comes from."))
        self.error = error_label()
        layout.addWidget(self.error)
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(8)
        layout.addWidget(self.body)
        layout.addStretch(1)
        self.items: list[dict] = []

    def on_show(self, **kwargs) -> None:
        set_error(self.error, None)
        clear_layout(self.body_layout)
        self.body_layout.addWidget(muted("Loading…"))
        run_async(api_client.shortlist, on_success=self._render, on_error=self._failed)

    def _render(self, items: list[dict]) -> None:
        self.items = items
        lang = preferred_language(self.ctx)
        clear_layout(self.body_layout)
        if not items:
            self.body_layout.addWidget(muted(words(lang, "Nothing yet. On a college's page, tap “Save to my shortlist”.",
                                                   "अभी कुछ नहीं। किसी कॉलेज के पेज पर “मेरी सूची में जोड़ें” दबाइए।")))
            find = primary_button(words(lang, "Find colleges", "कॉलेज खोजें"))
            find.clicked.connect(lambda: self.ctx.navigate("college_find"))
            self.body_layout.addWidget(find)
            return
        for c in items:
            card = Card()
            name = link_button(f"{c['name']} · {c['city']}  ›")
            name.clicked.connect(lambda _c=False, cid=c["id"]: self.ctx.navigate("college_detail", college_id=cid))
            card.addWidget(name)
            if not c["facts"]:
                card.addWidget(muted(words(lang, "Nothing verified about it yet.", "अभी इसकी कोई जानकारी पक्की नहीं।")))
            for cell in c["facts"].values():
                value, note = cell_text(cell, lang)
                card.addWidget(muted(f"{cell['what']}: {value} — {note}"))
            self.body_layout.addWidget(card)
        if len(items) >= 2:
            compare = primary_button(words(lang, "Compare them", "इनकी तुलना करें"))
            compare.clicked.connect(lambda: self.ctx.navigate("compare", college_ids=[c["id"] for c in self.items[:4]]))
            self.body_layout.addWidget(compare)

    def _failed(self, err: Exception) -> None:
        clear_layout(self.body_layout)
        set_error(self.error, err.message if isinstance(err, ApiError) else "Couldn't reach MAYA's server just now.")
