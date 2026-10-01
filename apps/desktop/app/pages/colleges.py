from PySide6.QtWidgets import (
    QComboBox, QGridLayout, QHBoxLayout, QLineEdit, QVBoxLayout, QWidget,
)

from app.api_client import ApiError, api_client
from app.goal import default_exam_code
from app.layout import columns, page_margins
from app.pages.base import BasePage
from app.widgets.common import (
    Card, clear_layout, demo_badge, error_label, ghost_button, heading, muted, primary_button, secondary_button, set_error,
)
from app.workers import run_async


PAGE_SIZE = 20


class CollegesPage(BasePage):
    def __init__(self, ctx):
        super().__init__(ctx)
        # The whole page scrolls as one (MainWindow puts every page in a scroll area): with the
        # on-screen keyboard open for the search box, fixed filters above a separate results
        # scroller no longer fit an 800x480 panel.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(*page_margins())
        outer.setSpacing(10)

        outer.addWidget(heading("College Discovery"))
        outer.addWidget(muted("Search and filter colleges by exam, location, and ownership."))

        # One row on a monitor; two per row on the kiosk panel, where five side by side would
        # be three times wider than the screen.
        per_row = columns(5, compact=2)
        filters = QGridLayout()
        filters.setContentsMargins(0, 0, 0, 0)
        filters.setSpacing(8)
        self.q_input = QLineEdit()
        self.q_input.setPlaceholderText("College name or city")
        self.q_input.returnPressed.connect(self._search)

        self.exam_combo = QComboBox()
        self.exam_combo.addItem("Any exam", "")
        self.exam_combo.addItem("JEE Main", "JEE_MAIN")
        self.exam_combo.addItem("JEE Advanced", "JEE_ADVANCED")
        self.exam_combo.addItem("NEET-UG", "NEET_UG")

        self.ownership_combo = QComboBox()
        self.ownership_combo.addItem("Any ownership", "")
        self.ownership_combo.addItem("Government", "government")
        self.ownership_combo.addItem("Private", "private")

        self.state_input = QLineEdit()
        self.state_input.setPlaceholderText("State")

        search_btn = primary_button("Search")
        search_btn.clicked.connect(self._search)

        for i, widget in enumerate([self.q_input, self.exam_combo, self.ownership_combo,
                                    self.state_input, search_btn]):
            widget.setMinimumWidth(110)
            filters.addWidget(widget, i // per_row, i % per_row)
        filters_widget = QWidget()
        filters_widget.setLayout(filters)
        outer.addWidget(filters_widget)

        self.error = error_label()
        outer.addWidget(self.error)

        compare_row = QHBoxLayout()
        self.compare_label = muted("")
        compare_row.addWidget(self.compare_label)
        self.compare_btn = primary_button("Compare selected")
        self.compare_btn.setVisible(False)
        self.compare_btn.clicked.connect(self._go_compare)
        compare_row.addWidget(self.compare_btn)
        compare_row.addStretch(1)
        compare_widget = QWidget()
        compare_widget.setLayout(compare_row)
        outer.addWidget(compare_widget)

        self._result_columns = columns(3)
        self.results_content = QWidget()
        self.results_grid = QGridLayout(self.results_content)
        self.results_grid.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.results_content, stretch=1)

        self.compare_ids: set[int] = set()
        self.results: list[dict] = []
        self.more_btn = None
        self.shown = 0
        self._filters_touched = False
        for widget in (self.exam_combo, self.ownership_combo):
            widget.activated.connect(self._filters_changed)
        for widget in (self.q_input, self.state_input):
            widget.textEdited.connect(self._filters_changed)

    def on_show(self, **kwargs) -> None:
        set_error(self.error, None)
        # Start on the student's own exam: a NEET student searching "colleges" means medical ones.
        # They can still widen it to "Any exam" themselves.
        if not self._filters_touched:
            index = self.exam_combo.findData(default_exam_code())
            self.exam_combo.setCurrentIndex(max(0, index))
        self._search()

    def _filters_changed(self, *_args) -> None:
        self._filters_touched = True

    def _search(self) -> None:
        params = {
            "q": self.q_input.text().strip(),
            "exam_code": self.exam_combo.currentData(),
            "ownership": self.ownership_combo.currentData(),
            "state": self.state_input.text().strip(),
        }
        run_async(api_client.search_colleges, **params, on_success=self._render_results, on_error=self._failed)

    def _render_results(self, colleges: list) -> None:
        # Hundreds of colleges match "NEET" — building a card for each at once freezes the Pi
        # for seconds, so show a page at a time. The best-known ones come first.
        self.results = colleges
        self.shown = 0
        self.more_btn = None  # cleared with the rest of the grid
        clear_layout(self.results_grid)
        if not colleges:
            self.results_grid.addWidget(muted("No colleges matched. Try broadening your filters."), 0, 0)
            return
        self._show_more()

    def _show_more(self) -> None:
        if self.more_btn is not None:
            self.more_btn.hide()
            self.more_btn.deleteLater()
            self.more_btn = None
        start, end = self.shown, min(self.shown + PAGE_SIZE, len(self.results))
        for i in range(start, end):
            self._add_card(i, self.results[i])
        self.shown = end
        if end < len(self.results):
            self.more_btn = secondary_button(f"Show more ({len(self.results) - end} left)")
            self.more_btn.clicked.connect(self._show_more)
            row = (end + self._result_columns - 1) // self._result_columns
            self.results_grid.addWidget(self.more_btn, row, 0, 1, self._result_columns)

    def _add_card(self, i: int, c: dict) -> None:
        card = Card()
        header = QHBoxLayout()
        header.addWidget(heading(c["canonical_name"]))
        header.addStretch(1)
        if c.get("is_demo_data"):
            header.addWidget(demo_badge())
        header_widget = QWidget()
        header_widget.setLayout(header)
        card.addWidget(header_widget)
        card.addWidget(muted(f"{c['city']}, {c['state']} · {c['college_type']} ({c['ownership']})"))
        if c.get("nirf_rank"):
            card.addWidget(muted(f"NIRF 2025: #{c['nirf_rank']}  ·  fees, placements & surroundings researched"))
        elif c.get("researched"):
            card.addWidget(muted("Fees, placements & surroundings researched"))
        if c.get("average_rating") is not None:
            card.addWidget(muted(f"★ {c['average_rating']} ({c['review_count']} reviews)"))

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        view_btn = secondary_button("View Details")
        view_btn.clicked.connect(lambda checked=False, cid=c["id"]: self.ctx.navigate("college_detail", college_id=cid))
        btn_row.addWidget(view_btn)
        compare_btn = ghost_button("Compare" if c["id"] not in self.compare_ids else "Remove from compare")
        compare_btn.clicked.connect(
            lambda checked=False, cid=c["id"], btn=compare_btn: self._toggle_compare(cid, btn))
        btn_row.addWidget(compare_btn)
        btn_row_widget = QWidget()
        btn_row_widget.setLayout(btn_row)
        card.addWidget(btn_row_widget)

        self.results_grid.addWidget(card, i // self._result_columns, i % self._result_columns)

    def _toggle_compare(self, college_id: int, button=None) -> None:
        if college_id in self.compare_ids:
            self.compare_ids.remove(college_id)
        elif len(self.compare_ids) < 4:
            self.compare_ids.add(college_id)
        else:
            set_error(self.error, "You can compare up to 4 colleges at a time.")
        if button is not None:  # just relabel it: re-searching would lose the student's place
            button.setText("Remove from compare" if college_id in self.compare_ids else "Compare")
        count = len(self.compare_ids)
        self.compare_label.setText(
            f"{count} selected" + (" — pick one more to compare" if count == 1 else "") if count else "")
        self.compare_btn.setVisible(count >= 2)

    def _go_compare(self) -> None:
        self.ctx.navigate("compare", college_ids=list(self.compare_ids))

    def _failed(self, err: Exception) -> None:
        message = err.message if isinstance(err, ApiError) else "Could not load colleges."
        set_error(self.error, message)
