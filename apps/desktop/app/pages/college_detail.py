"""One college, on one scrolling page: ranking, how hard it is to get in (official cutoffs by
category), what it costs, placements, what's around the campus, sources and reviews.

The old tabbed layout put a scroller inside each tab inside the page scroller, which was hard
to drag on the resistive panel, and its fee/hostel tabs only ever had demo data.
"""

from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QGridLayout, QHBoxLayout, QLabel, QTextEdit, QVBoxLayout, QWidget

from app import college_facts as facts
from app.api_client import ApiError, api_client
from app.layout import page_margins
from app.pages.base import BasePage
from app.session import session
from app.widgets.common import (
    Card, clear_layout, demo_badge, error_label, ghost_button, heading, muted, primary_button,
    secondary_button, set_error, subtitle,
)
from app.widgets.links import link_row
from app.workers import run_async

CATEGORIES = ["General", "OBC", "EWS", "SC", "ST"]
PROFILE_CATEGORY = {"general": "General", "obc": "OBC", "ews": "EWS", "sc": "SC", "st": "ST"}
CUTOFF_ROWS_SHOWN = 12


def _text(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    return label


class CollegeDetailPage(BasePage):
    def __init__(self, ctx):
        super().__init__(ctx)
        self.college: dict | None = None
        self.college_id: int | None = None
        self.cutoffs: list[dict] = []
        self.show_all_cutoffs = False
        outer = QVBoxLayout(self)  # MainWindow scrolls the page
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

        self.category_combo = None
        self.cutoff_box: QVBoxLayout | None = None
        self.reviews_box: QVBoxLayout | None = None

    def on_show(self, **kwargs) -> None:
        college_id = kwargs.get("college_id")
        if college_id is None or (college_id == self.college_id and kwargs.get("returning")):
            return
        self.college_id = college_id
        self.show_all_cutoffs = False
        set_error(self.error, None)
        clear_layout(self.body_layout)
        self.body_layout.addWidget(muted("Loading…"))
        run_async(api_client.get_college, college_id, on_success=self._render, on_error=self._failed)

    # ---------------- rendering ----------------

    def _section(self, title: str, note: str | None = None) -> Card:
        card = Card()
        card.addWidget(heading(title))
        if note:
            card.addWidget(muted(note))
        self.body_layout.addWidget(card)
        return card

    def _render(self, college: dict) -> None:
        self.college = college
        clear_layout(self.body_layout)
        profile = college.get("profile")

        title = QHBoxLayout()
        title.addWidget(heading(college["canonical_name"]), 1)
        if college.get("is_demo_data"):
            title.addWidget(demo_badge())
        holder = QWidget()
        holder.setLayout(title)
        self.body_layout.addWidget(holder)
        about = f"{college['city']}, {college['state']} · {college['college_type']} ({college['ownership']})"
        if college.get("established_year"):
            about += f" · since {college['established_year']}"
        self.body_layout.addWidget(subtitle(about))
        ranking = facts.ranking_line(profile)
        if ranking:
            self.body_layout.addWidget(_text(f"<b>{ranking}</b>"))

        actions = QHBoxLayout()
        read = secondary_button("Read it to me")
        read.clicked.connect(self._read_aloud)
        actions.addWidget(read)
        ask = primary_button("Ask MAYA about it")
        ask.clicked.connect(lambda: self.ctx.navigate(
            "maya", ask=f"Tell me about {college['canonical_name']}. Could I get in, and is it a good fit for me?"))
        actions.addWidget(ask)
        actions.addStretch(1)
        holder = QWidget()
        holder.setLayout(actions)
        self.body_layout.addWidget(holder)

        self._render_admission(college.get("admission"))

        if profile:
            fees = facts.fee_lines(profile)
            if fees:
                card = self._section("What it costs")
                card.addWidget(_text(f"<b>{fees[0]}</b>"))
                for line in fees[1:]:
                    card.addWidget(muted(line))
            placements = facts.placement_lines(profile)
            if placements:
                card = self._section("Placements & what graduates do")
                for line in placements:
                    card.addWidget(_text(line))
                note = (profile.get("placements") or {}).get("source_note")
                if note:
                    card.addWidget(muted(note))
            if profile.get("hospital"):
                card = self._section("Teaching hospital")
                card.addWidget(_text(profile["hospital"]))
            around = facts.surroundings_lines(profile)
            if around:
                card = self._section("Around the campus", "Approximate distances — check a map before you travel.")
                for label, value in around:
                    card.addWidget(_text(f"<b>{label}:</b> {value}"))
        else:
            card = self._section("Fees, placements and surroundings")
            card.addWidget(_text(facts.not_researched(college["canonical_name"])))

        sources = list((profile or {}).get("sources", []))
        admission = college.get("admission")
        if admission and admission.get("source_url"):
            sources.append({"name": admission["source"], "url": admission["source_url"]})
        website = college.get("official_website")
        if website or sources:
            card = self._section("Links", "Tap one to open it on your phone.")
            if website:
                card.addWidget(link_row("Official website", website, website, self, compact=True))
            for s in sources:
                card.addWidget(link_row(s["name"], "", s["url"], self, compact=True))

        self._render_reviews_section()

        back = secondary_button("←  Back")
        back.clicked.connect(self.ctx.go_back)
        self.body_layout.addWidget(back)

        cid = college["id"]
        run_async(api_client.get_cutoffs, cid, on_success=lambda rows: self._got_cutoffs(cid, rows),
                  on_error=lambda _e: None)
        run_async(api_client.get_reviews, cid, on_success=self._render_reviews, on_error=lambda _e: None)

    def _render_admission(self, admission: dict | None) -> None:
        card = self._section("Getting in")
        for i, line in enumerate(facts.admission_lines(admission)):
            card.addWidget(muted(line) if i == 0 else _text(line))
        if not admission:
            return
        pick = QHBoxLayout()
        pick.addWidget(QLabel("Closing ranks for:"))
        self.category_combo = QComboBox()
        for c in CATEGORIES:
            self.category_combo.addItem(c, c)
        own = PROFILE_CATEGORY.get(str((session.profile or {}).get("category") or "").lower(), "General")
        self.category_combo.setCurrentIndex(max(0, self.category_combo.findData(own)))
        self.category_combo.currentIndexChanged.connect(lambda _i: self._render_cutoffs())
        pick.addWidget(self.category_combo)
        pick.addStretch(1)
        holder = QWidget()
        holder.setLayout(pick)
        card.addWidget(holder)
        box = QWidget()
        self.cutoff_box = QVBoxLayout(box)
        self.cutoff_box.setContentsMargins(0, 0, 0, 0)
        self.cutoff_box.addWidget(muted("Loading cutoffs…"))
        card.addWidget(box)
        if admission["exam_code"] != "NEET_UG":
            card.addWidget(muted("Reserved categories are compared with your category rank, as JoSAA does."))

    def _got_cutoffs(self, college_id: int, cutoffs: list) -> None:
        if college_id != self.college_id:
            return  # the student has already moved on to another college
        self.cutoffs = cutoffs
        self._render_cutoffs()

    def _render_cutoffs(self) -> None:
        if self.cutoff_box is None:
            return
        clear_layout(self.cutoff_box)
        category = self.category_combo.currentData() if self.category_combo else "General"
        rows = [c for c in self.cutoffs if c["category"] == category and c["seat_type"] == "Gender-Neutral"]
        if rows:
            latest = max(c["year"] for c in rows)
            rows = [c for c in rows if c["year"] == latest]
        if not rows:
            self.cutoff_box.addWidget(muted(f"No {category} seats listed here."))
            return
        rows.sort(key=lambda c: c["closing_rank"])
        shown = rows if self.show_all_cutoffs else rows[:CUTOFF_ROWS_SHOWN]
        grid = QGridLayout()
        grid.setContentsMargins(0, 4, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.addWidget(muted("Program"), 0, 0)
        grid.addWidget(muted("Seats"), 0, 1)
        grid.addWidget(muted("Closed at"), 0, 2)
        paper_2 = (self.college or {}).get("admission", {}) or {}
        paper_2 = paper_2.get("exam_code") == "JEE_MAIN"
        for i, c in enumerate(shown, start=1):
            program = c.get("program") or "—"
            if paper_2 and ("(B.Arch)" in program or "(B.Plan)" in program):
                program += " — by JEE Main Paper 2 rank"
            grid.addWidget(_text(program), i, 0)
            grid.addWidget(muted(facts.QUOTA_POOL.get(c["quota"], c["quota"])), i, 1)
            grid.addWidget(QLabel(f"{c['closing_rank']:,}"), i, 2)
        grid.setColumnStretch(0, 1)
        holder = QWidget()
        holder.setLayout(grid)
        self.cutoff_box.addWidget(holder)
        if len(rows) > len(shown):
            more = ghost_button(f"Show all {len(rows)}")
            more.clicked.connect(self._show_all_cutoffs)
            self.cutoff_box.addWidget(more)

    def _show_all_cutoffs(self) -> None:
        self.show_all_cutoffs = True
        self._render_cutoffs()

    # ---------------- reviews ----------------

    def _render_reviews_section(self) -> None:
        card = self._section("Student reviews", "Opinions from students using this app — not verified facts.")
        box = QWidget()
        self.reviews_box = QVBoxLayout(box)
        self.reviews_box.setContentsMargins(0, 0, 0, 0)
        card.addWidget(box)
        row = QHBoxLayout()
        row.addWidget(QLabel("Your rating:"))
        self.rating_combo = QComboBox()
        for n in range(5, 0, -1):
            self.rating_combo.addItem("★" * n, n)
        row.addWidget(self.rating_combo)
        row.addStretch(1)
        holder = QWidget()
        holder.setLayout(row)
        card.addWidget(holder)
        self.review_text = QTextEdit()
        self.review_text.setPlaceholderText("Hostel, mess, teachers, campus life…")
        self.review_text.setFixedHeight(70)
        card.addWidget(self.review_text)
        submit = secondary_button("Post review")
        submit.clicked.connect(self._submit_review)
        card.addWidget(submit)

    def _render_reviews(self, reviews: list) -> None:
        if self.reviews_box is None:
            return
        clear_layout(self.reviews_box)
        if not reviews:
            self.reviews_box.addWidget(muted("No reviews yet."))
        for r in reviews[:10]:
            self.reviews_box.addWidget(_text(f"{'★' * r['rating']}{'☆' * (5 - r['rating'])}  {r['text']}"))

    def _submit_review(self) -> None:
        text = self.review_text.toPlainText().strip()
        if not text or self.college_id is None:
            return
        college_id = self.college_id
        run_async(
            api_client.add_review, college_id, self.rating_combo.currentData(), text,
            on_success=lambda _r: (self.review_text.clear(), run_async(
                api_client.get_reviews, college_id, on_success=self._render_reviews, on_error=lambda _e: None)),
            on_error=self._failed,
        )

    # ---------------- voice ----------------

    def _read_aloud(self) -> None:
        if not self.college:
            return
        c, profile = self.college, self.college.get("profile")
        parts = [f"{c['canonical_name']}, in {c['city']}, {c['state']}."]
        if facts.ranking_line(profile):
            parts.append(facts.ranking_line(profile) + ".")
        admission = c.get("admission")
        if admission:
            parts.extend(line + "." for line in facts.admission_lines(admission)[1:3])
        fees = facts.fee_lines(profile)
        if fees:
            parts.append(fees[0] + ".")
        placements = facts.placement_lines(profile)
        if placements:
            parts.append(placements[0] + ".")
        s = (profile or {}).get("surroundings") or {}
        if s.get("railway"):
            parts.append("Nearest station: " + s["railway"] + ".")
        self.ctx.voice.say(facts.spoken(" ".join(parts)))

    def _failed(self, err: Exception) -> None:
        set_error(self.error, err.message if isinstance(err, ApiError) else "Couldn't load this college.")
