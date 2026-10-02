"""Side-by-side college comparison: a quick verdict (best ranked, cheapest, best placements,
hardest/easiest to get into), then ranking, getting in, cost, placements and what's around
each campus — every figure with where it came from.

On the 800x480 panel colleges stack under each heading; on a wider screen they sit side by side.
"""

from __future__ import annotations

from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app import college_facts as facts
from app.api_client import ApiError, api_client
from app.layout import is_compact, page_margins
from app.pages.base import BasePage
from app.widgets.common import (
    Card, clear_layout, demo_badge, error_label, heading, muted, primary_button, secondary_button,
    set_error,
)
from app.widgets.facts import cell_text, osm_note
from app.widgets.links import link_row
from app.workers import run_async


def _text(text: str, bold: bool = False) -> QLabel:
    label = QLabel(f"<b>{text}</b>" if bold else text)
    label.setWordWrap(True)
    return label


def verdicts(rows: list[dict]) -> list[str]:
    """One line each for the questions students ask first. Only compares like with like: NIRF
    ranks within one ranking list, closing ranks within one exam."""
    out = []
    name = lambda r: facts.short_name(r["college"]["canonical_name"])  # noqa: E731

    for attribute in ("ranking.nirf.engineering", "ranking.nirf.medical"):  # one ranking list at a time
        ranked = [(r, int(str(r["facts"][attribute]["value"]).split()[0])) for r in rows
                  if (r.get("facts") or {}).get(attribute) and str(r["facts"][attribute]["value"]).split()[0].isdigit()]
        if len(ranked) >= 2:
            r, rank = min(ranked, key=lambda x: x[1])
            out.append(f"Best ranked: {name(r)} (NIRF #{rank})")

    costs = [(r, r["approximate_annual_cost"]) for r in rows if r.get("approximate_annual_cost")]
    if len(costs) >= 2:
        r, c = min(costs, key=lambda x: x[1])
        out.append(f"Lowest tuition: {name(r)} ({facts.lakh(c)} a year)")

    admissions = [(r, r["admission"]) for r in rows if r.get("admission")]
    if len(admissions) >= 2 and len({a["exam_code"] for _, a in admissions}) == 1:
        r, a = min(admissions, key=lambda x: x[1]["toughest"]["closing_rank"])
        out.append(f"Hardest to get into: {name(r)} (closed at {a['toughest']['closing_rank']:,})")
        r, a = max(admissions, key=lambda x: x[1]["easiest"]["closing_rank"])
        out.append(f"Easiest way in: {name(r)} — {a['easiest']['program']} closed at "
                   f"{a['easiest']['closing_rank']:,}")
    elif len({a["exam_code"] for _, a in admissions}) > 1:
        out.append("These colleges admit through different exams, so their closing ranks can't be "
                   "compared directly.")
    return out


class ComparePage(BasePage):
    def __init__(self, ctx):
        super().__init__(ctx)
        self.result: dict | None = None
        outer = QVBoxLayout(self)  # MainWindow scrolls the page
        outer.setContentsMargins(*page_margins())
        outer.setSpacing(10)
        outer.addWidget(heading("Compare colleges"))
        self.error = error_label()
        outer.addWidget(self.error)
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(10)
        outer.addWidget(self.body)
        outer.addStretch(1)

    def on_show(self, **kwargs) -> None:
        college_ids = kwargs.get("college_ids")
        if college_ids is None:
            return  # coming back to the page: keep what's shown
        set_error(self.error, None)
        clear_layout(self.body_layout)
        if len(college_ids) < 2:
            set_error(self.error, "Pick at least 2 colleges on the Colleges page, then tap Compare.")
            return
        self.body_layout.addWidget(muted("Comparing…"))
        run_async(api_client.compare_colleges, college_ids, on_success=self._render, on_error=self._failed)

    # ---------------- rendering ----------------

    def _section(self, title: str, note: str | None = None) -> Card:
        card = Card()
        card.addWidget(heading(title))
        if note:
            card.addWidget(muted(note))
        self.body_layout.addWidget(card)
        return card

    def _per_college(self, card: Card, rows: list[dict], build) -> None:
        """One block per college: stacked on the kiosk, side by side on a wide screen."""
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(8)
        per_row = 1 if is_compact() else len(rows)
        for i, row in enumerate(rows):
            block = QVBoxLayout()
            block.setSpacing(2)
            block.addWidget(_text(facts.short_name(row["college"]["canonical_name"]), bold=True))
            for widget in build(row):
                block.addWidget(widget)
            holder = QWidget()
            holder.setLayout(block)
            grid.addWidget(holder, i // per_row, i % per_row)
        holder = QWidget()
        holder.setLayout(grid)
        card.addWidget(holder)

    def _render(self, result: dict) -> None:
        self.result = result
        clear_layout(self.body_layout)
        rows = result["rows"]

        names = Card()
        for row in rows:
            c = row["college"]
            line = QHBoxLayout()
            line.addWidget(_text(f"<b>{c['canonical_name']}</b> — {c['city']}, {c['state']} · {c['college_type']}"), 1)
            if c.get("is_demo_data"):
                line.addWidget(demo_badge())
            holder = QWidget()
            holder.setLayout(line)
            names.addWidget(holder)
        self.body_layout.addWidget(names)

        actions = QHBoxLayout()
        read = secondary_button("Read it to me")
        read.clicked.connect(self._read_aloud)
        actions.addWidget(read)
        ask = primary_button("Ask MAYA which suits me")
        ask.clicked.connect(lambda: self.ctx.navigate("maya", ask=(
            "Which of these colleges suits me better, and why: "
            + ", ".join(r["college"]["canonical_name"] for r in rows) + "?")))
        actions.addWidget(ask)
        actions.addStretch(1)
        holder = QWidget()
        holder.setLayout(actions)
        self.body_layout.addWidget(holder)

        quick = verdicts(rows)
        if quick:
            card = self._section("At a glance")
            for line in quick:
                card.addWidget(_text("•  " + line))

        card = self._section("Ranking", "NIRF, from the Ministry of Education's own ranking pages.")
        self._per_college(card, rows, lambda r: self._cells(r, ("ranking.nirf.engineering", "ranking.nirf.medical"),
                                                            "Not in NIRF's ranked list"))

        card = self._section("Getting in", "Official closing ranks from JoSAA (engineering) and MCC (medical).")
        self._per_college(card, rows, lambda r: [_text(line) for line in facts.admission_lines(r.get("admission"))])

        card = self._section("What it costs", "From each college's own fee notice where MAYA found one.")
        self._per_college(card, rows, lambda r: self._cells(r, ("fee.tuition.annual", "fee.hostel.annual", "fee.mess.annual")))

        card = self._section("Campus")
        self._per_college(card, rows, lambda r: self._cells(r, ("facility.hostel", "facility.medical")))

        card = self._section("Around the campus", osm_note("en"))
        self._per_college(card, rows, lambda r: self._cells(r, ("near.railway_station", "near.airport", "near.hospital")))

        if result.get("ai_summary"):
            card = self._section("MAYA's take")
            card.addWidget(_text(result["ai_summary"]))
            card.addWidget(muted("Written from the figures above — nothing extra."))

        sources = []
        for r in rows:
            for cell in (r.get("facts") or {}).values():
                if cell and cell.get("url") and not any(s["url"] == cell["url"] for s in sources):
                    sources.append({"name": cell["source"], "url": cell["url"]})
            a = r.get("admission")
            if a and a.get("source_url") and not any(s["url"] == a["source_url"] for s in sources):
                sources.append({"name": a["source"], "url": a["source_url"]})
        if sources:
            card = self._section("Sources", "Tap one to open it on your phone.")
            for s in sources:
                card.addWidget(link_row(s["name"], "", s["url"], self, compact=True))

        back = secondary_button("←  Back")
        back.clicked.connect(self.ctx.go_back)
        self.body_layout.addWidget(back)

    def _cells(self, row: dict, attributes: tuple[str, ...], empty: str = "Not known") -> list[QWidget]:
        out = []
        for attribute in attributes:
            cell = (row.get("facts") or {}).get(attribute)
            if not cell or cell.get("status") == "not_available":
                continue
            value, note = cell_text(cell)
            out.append(_text(f"<b>{cell['what']}:</b> {value}"))
            out.append(muted(note))
        return out or [muted(empty)]

    def _read_aloud(self) -> None:
        if not self.result:
            return
        rows = self.result["rows"]
        parts = verdicts(rows) or ["Here's how they compare."]
        for r in rows:
            cell = (r.get("facts") or {}).get("fee.tuition.annual")
            if cell and cell.get("status") != "not_available":
                parts.append(f"{facts.short_name(r['college']['canonical_name'])}: tuition {cell['value']}, "
                             f"according to {cell['source']}")
        self.ctx.voice.say(facts.spoken(". ".join(parts)))

    def _failed(self, err: Exception) -> None:
        clear_layout(self.body_layout)
        set_error(self.error, err.message if isinstance(err, ApiError) else "Couldn't compare these colleges.")
