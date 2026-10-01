"""Exam guidance and college prediction — one page per exam family, with its own questions.

JEE opens with a choice: JEE Main (NITs, IIITs, GFTIs, admission by JEE Main rank) or JEE
Advanced (IITs, by JEE Advanced rank). Each asks what that exam actually needs: JEE Main a
percentile or rank, home state and gender (JoSAA has home-state quotas and female-only
seats); JEE Advanced a JEE Advanced rank; NEET a score out of 720 or an All-India rank.

Students without a result yet can enter an expected percentile (JEE Main), score (NEET) or
rank (JEE Advanced); the prediction says clearly when it's working from an estimate. Results
appear right under the button, with a one-line summary that MAYA also says aloud — the old
page put them below the fold, where it looked as if nothing had happened.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSizePolicy,
    QSpinBox, QVBoxLayout, QWidget,
)

from app.api_client import ApiError, api_client
from app.config import CATEGORIES
from app.goal import target_exam_code
from app.layout import page_margins
from app.pages.base import BasePage
from app.session import session
from app.widgets.common import (
    Card, chance_badge, clear_layout, demo_badge, error_label, ghost_button, heading, muted, primary_button,
    set_error, subtitle,
)
from app.workers import run_async

BAND_TITLES = [
    ("high_probability", "🟢 High chance"),
    ("possible", "🟡 Possible"),
    ("ambitious", "🔴 Ambitious / dream"),
]
STATUSES = [("preparing", "Still preparing"), ("appeared", "Appeared, waiting for result"), ("qualified", "Have my result")]

EXAMS = {
    "JEE_MAIN": {
        "title": "JEE Main", "short": "NITs, IIITs and GFTIs",
        "about": "Admission to NITs, IIITs and other government-funded institutes goes by your JEE Main "
                 "rank through JoSAA. NITs keep half their seats for students from their home state.",
        "estimate_label": "Expected percentile", "result_label": "Your percentile",
        "rank_label": "All-India rank (CRL), if you have it",
    },
    "JEE_ADVANCED": {
        "title": "JEE Advanced", "short": "The IITs",
        "about": "IIT seats go by your JEE Advanced rank. Only about the top 2.5 lakh JEE Main candidates "
                 "can sit JEE Advanced.",
        "estimate_label": "Expected JEE Advanced rank", "result_label": None,
        "rank_label": "JEE Advanced rank (CRL)",
    },
    "NEET_UG": {
        "title": "NEET-UG", "short": "MBBS, BDS and more",
        "about": "15% of government seats are filled All-India by NEET rank (MCC); the other 85% are for "
                 "students of that state, through state counselling.",
        "estimate_label": "Expected score (out of 720)", "result_label": "Your score (out of 720)",
        "rank_label": "All-India rank (AIR), if you have it",
    },
}


def _row_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    return label


class ExamPage(BasePage):
    def __init__(self, ctx, exam_codes: list[str], title: str):
        super().__init__(ctx)
        self.exam_codes = exam_codes
        self.current_exam_code: str | None = exam_codes[0] if len(exam_codes) == 1 else None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(*page_margins())
        outer.setSpacing(10)
        outer.addWidget(heading(title))
        outer.addWidget(subtitle("Tell MAYA where you stand, and see which colleges past cutoffs say you could get."))

        # ---- JEE Main or JEE Advanced? ----
        self.choice_buttons: dict[str, QPushButton] = {}
        if len(exam_codes) > 1:
            choices = QHBoxLayout()
            choices.setSpacing(8)
            for code in exam_codes:
                info = EXAMS[code]
                btn = QPushButton(f"{info['title']}\n{info['short']}")
                btn.setProperty("variant", "choice")
                btn.setMinimumHeight(58)
                btn.setCursor(Qt.PointingHandCursor)
                btn.clicked.connect(lambda _checked=False, c=code: self._choose_exam(c))
                choices.addWidget(btn)
                self.choice_buttons[code] = btn
            holder = QWidget()
            holder.setLayout(choices)
            outer.addWidget(holder)
            self.choose_hint = muted("Which exam are you asking about?")
            outer.addWidget(self.choose_hint)

        # ---- the questions for that exam ----
        self.form_card = Card()
        self.about = muted("")
        self.form_card.addWidget(self.about)
        self.form = QFormLayout()
        self.form.setSpacing(8)
        self.form.setRowWrapPolicy(QFormLayout.WrapLongRows)

        self.status_combo = QComboBox()
        for value, label in STATUSES:
            self.status_combo.addItem(label, value)
        self.status_combo.currentIndexChanged.connect(lambda _i: self._sync_fields())
        self.form.addRow(_row_label("Where are you?"), self.status_combo)

        self.value_input = QDoubleSpinBox()  # percentile or score, depending on the exam
        self.value_input.setDecimals(2)
        self.value_row_label = _row_label("")
        self.form.addRow(self.value_row_label, self.value_input)

        self.rank_input = QSpinBox()
        self.rank_input.setRange(0, 3_000_000)
        self.rank_input.setSpecialValueText("—")
        self.rank_row_label = _row_label("")
        self.form.addRow(self.rank_row_label, self.rank_input)

        self.category_combo = QComboBox()
        self.category_combo.addItems(CATEGORIES)
        self.category_combo.currentIndexChanged.connect(lambda _i: self._sync_fields())
        self.form.addRow(_row_label("Category"), self.category_combo)

        # JoSAA allots reserved seats by category rank, not overall rank.
        self.category_rank_input = QSpinBox()
        self.category_rank_input.setRange(0, 2_000_000)
        self.category_rank_input.setSpecialValueText("—")
        self.category_rank_label = _row_label("Category rank (on your scorecard)")
        self.form.addRow(self.category_rank_label, self.category_rank_input)

        self.gender_combo = QComboBox()
        self.gender_combo.addItem("Male / prefer not to say", "male")
        self.gender_combo.addItem("Female (adds female-only seats)", "female")
        self.gender_label = _row_label("Seat pool")
        self.form.addRow(self.gender_label, self.gender_combo)

        self.branches_input = QLineEdit()
        self.branches_input.setPlaceholderText("e.g. Computer Science, Electronics")
        self.branches_label = _row_label("Preferred branches")
        self.form.addRow(self.branches_label, self.branches_input)

        self.states_input = QLineEdit()
        self.states_input.setPlaceholderText("e.g. Maharashtra, Karnataka")
        self.form.addRow(_row_label("Preferred states"), self.states_input)

        self.college_type_combo = QComboBox()
        self.college_type_combo.addItem("Any", "any")
        self.college_type_combo.addItem("Government only", "government")
        self.college_type_combo.addItem("Private only", "private")
        self.form.addRow(_row_label("College type"), self.college_type_combo)

        form_widget = QWidget()
        form_widget.setLayout(self.form)
        self.form_card.addWidget(form_widget)
        self.home_state_note = muted("")
        self.form_card.addWidget(self.home_state_note)

        self.error = error_label()
        self.form_card.addWidget(self.error)
        self.submit_btn = primary_button("Save & predict colleges")
        self.submit_btn.setMinimumHeight(44)
        self.submit_btn.clicked.connect(self._submit)
        self.form_card.addWidget(self.submit_btn)
        outer.addWidget(self.form_card)

        # ---- the answer, right under the button ----
        self.summary = QLabel("")
        self.summary.setObjectName("PredictionSummary")
        self.summary.setWordWrap(True)
        self.summary.setVisible(False)
        outer.addWidget(self.summary)
        # Predicted colleges can be picked for a side-by-side comparison right here.
        self.compare_ids: list[int] = []
        self.compare_btn = primary_button("")
        self.compare_btn.setVisible(False)
        self.compare_btn.clicked.connect(lambda: self.ctx.navigate("compare", college_ids=list(self.compare_ids)))
        outer.addWidget(self.compare_btn)
        self.results_container = QWidget()
        self.results_layout = QVBoxLayout(self.results_container)
        self.results_layout.setContentsMargins(0, 0, 0, 0)
        self.results_layout.setAlignment(Qt.AlignTop)
        outer.addWidget(self.results_container, stretch=1)

        self._sync_fields()

    # ---------------- which exam ----------------

    def on_show(self, returning: bool = False, **kwargs) -> None:
        set_error(self.error, None)
        profile = session.profile or {}
        idx = self.category_combo.findText(profile.get("category") or "General")
        if idx >= 0:
            self.category_combo.setCurrentIndex(idx)
        if returning:
            return
        if len(self.exam_codes) > 1:
            target = target_exam_code()
            self.current_exam_code = target if target in self.exam_codes else self.current_exam_code
            if self.current_exam_code is None:
                QTimer.singleShot(300, self._ask_which_exam)
        self._sync_fields()
        self._clear_results()
        if self.current_exam_code:
            self._load_existing_profile()

    def _ask_which_exam(self) -> None:
        if self.isVisible() and self.current_exam_code is None:
            self.ctx.voice.ask("Which exam — JEE Main, or JEE Advanced?", on_answer=self._heard_exam,
                               on_no_answer=lambda _r: None)

    def _heard_exam(self, transcript: str) -> None:
        text = transcript.lower()
        if "advance" in text:
            self._choose_exam("JEE_ADVANCED")
        elif "main" in text or "mains" in text:
            self._choose_exam("JEE_MAIN")

    def _choose_exam(self, code: str) -> None:
        self.ctx.voice.cancel()
        self.current_exam_code = code
        self._sync_fields()
        self._clear_results()
        self._load_existing_profile()

    def _sync_fields(self) -> None:
        """Show only the questions that matter for this exam and where the student is."""
        code = self.current_exam_code
        for c, btn in self.choice_buttons.items():
            btn.setProperty("selected", "true" if c == code else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        if self.choice_buttons:
            self.choose_hint.setVisible(code is None)
        self.form_card.setVisible(code is not None)
        if code is None:
            return
        info = EXAMS[code]
        has_result = self.status_combo.currentData() == "qualified"
        self.about.setText(info["about"])

        # The value box: percentile (JEE Main), score (NEET). JEE Advanced has only ranks.
        if code == "JEE_ADVANCED":
            self.form.setRowVisible(self.value_input, False)
        else:
            self.form.setRowVisible(self.value_input, True)
            label = info["result_label"] if has_result else info["estimate_label"]
            self.value_row_label.setText(label)
            if code == "NEET_UG":
                self.value_input.setRange(0, 720)
                self.value_input.setDecimals(0)
            else:
                self.value_input.setRange(0, 100)
                self.value_input.setDecimals(2)
        rank_label = info["rank_label"] if (has_result or code == "JEE_ADVANCED") else None
        if code == "JEE_ADVANCED" and not has_result:
            rank_label = info["estimate_label"]
        self.form.setRowVisible(self.rank_input, rank_label is not None)
        if rank_label:
            self.rank_row_label.setText(rank_label)

        is_jee = code in ("JEE_MAIN", "JEE_ADVANCED")
        reserved = self.category_combo.currentText() != "General"
        self.form.setRowVisible(self.category_rank_input, is_jee and reserved)
        self.form.setRowVisible(self.gender_combo, is_jee)
        self.form.setRowVisible(self.branches_input, is_jee)
        profile = session.profile or {}
        home = profile.get("domicile_state") or profile.get("state")
        if code == "JEE_MAIN" and home:
            self.home_state_note.setText(f"Home state: {home} — NITs in {home} have home-state quota seats for you.")
        elif code == "NEET_UG" and home:
            self.home_state_note.setText(f"Domicile: {home} — you're eligible for {home}'s 85% state-quota seats as well as the All-India quota.")
        else:
            self.home_state_note.setText("")
        self.home_state_note.setVisible(bool(self.home_state_note.text()))

    # ---------------- saved details ----------------

    def _load_existing_profile(self) -> None:
        code = self.current_exam_code
        run_async(api_client.get_exam_profile, code,
                  on_success=lambda p, c=code: self._prefill(c, p), on_error=lambda _e: None)

    def _prefill(self, code: str, profile: dict) -> None:
        if code != self.current_exam_code:
            return
        idx = self.status_combo.findData(profile.get("status"))
        self.status_combo.setCurrentIndex(idx if idx >= 0 else 0)
        value = profile.get("score") if code == "NEET_UG" else profile.get("percentile")
        self.value_input.setValue(value or 0)
        self.rank_input.setValue(profile.get("rank") or 0)
        self.category_rank_input.setValue(profile.get("category_rank") or 0)
        extra = profile.get("extra") or {}
        gidx = self.gender_combo.findData(extra.get("gender"))
        if gidx >= 0:
            self.gender_combo.setCurrentIndex(gidx)
        self.branches_input.setText(", ".join(profile.get("preferred_branches") or []))
        self.states_input.setText(", ".join(profile.get("preferred_states") or []))
        tidx = self.college_type_combo.findData(profile.get("college_type_preference"))
        if tidx >= 0:
            self.college_type_combo.setCurrentIndex(tidx)
        self._sync_fields()

    # ---------------- predicting ----------------

    def _inputs(self) -> dict:
        code = self.current_exam_code
        value = self.value_input.value() or None
        return {
            "rank": self.rank_input.value() or None,
            "percentile": value if code == "JEE_MAIN" else None,
            "score": value if code == "NEET_UG" else None,
            "category": self.category_combo.currentText(),
            "category_rank": self.category_rank_input.value() or None,
            "gender": self.gender_combo.currentData() if code != "NEET_UG" else None,
            "branches": [b.strip() for b in self.branches_input.text().split(",") if b.strip()],
            "states": [s.strip() for s in self.states_input.text().split(",") if s.strip()],
            "college_type": self.college_type_combo.currentData(),
        }

    def _submit(self) -> None:
        set_error(self.error, None)
        code = self.current_exam_code
        i = self._inputs()
        if not (i["rank"] or i["percentile"] or i["score"]):
            what = {"JEE_MAIN": "your percentile (or expected percentile)",
                    "JEE_ADVANCED": "your rank (or the rank you're aiming for)",
                    "NEET_UG": "your score out of 720 (or expected score)"}[code]
            set_error(self.error, f"To predict colleges, enter {what}.")
            self.ctx.voice.say(f"To predict colleges, I need {what}.")
            return
        self.submit_btn.setEnabled(False)
        self.submit_btn.setText("Saving…")
        run_async(
            api_client.save_exam_profile,
            exam_code=code, status=self.status_combo.currentData(),
            rank=i["rank"], percentile=i["percentile"], score=i["score"], category_rank=i["category_rank"],
            extra={"gender": i["gender"]} if i["gender"] else {},
            preferred_branches=i["branches"], preferred_states=i["states"], college_type_preference=i["college_type"],
            on_success=lambda _r: self._predict(i), on_error=self._failed,
        )

    def _predict(self, i: dict) -> None:
        self.submit_btn.setText("Predicting…")
        run_async(
            api_client.predict, self.current_exam_code,
            rank=i["rank"], percentile=i["percentile"], score=i["score"], gender=i["gender"],
            category=i["category"], category_rank=i["category_rank"],
            domicile_state=(session.profile or {}).get("domicile_state") or (session.profile or {}).get("state"),
            preferred_branches=i["branches"], preferred_states=i["states"],
            college_type_preference=i["college_type"],
            on_success=self._render_results, on_error=self._failed,
        )

    def _clear_results(self) -> None:
        self.summary.setVisible(False)
        clear_layout(self.results_layout)

    def _render_results(self, response: dict) -> None:
        self.submit_btn.setEnabled(True)
        self.submit_btn.setText("Save & predict colleges")
        self._clear_results()
        results = response.get("results", [])
        rank = response["student_rank"]
        rank_text = f"estimated rank {rank:,}" if response.get("rank_estimated") else f"rank {rank:,}"
        counts = {band: sum(1 for r in results if r["band"] == band) for band, _t in BAND_TITLES}
        if results:
            summary = (f"With {rank_text}: {counts['high_probability']} high-chance, {counts['possible']} possible "
                       f"and {counts['ambitious']} ambitious options.")
        else:
            summary = f"With {rank_text}, no colleges in MAYA's data are within reach for these filters."
        if response.get("rank_estimated") and response.get("rank_basis"):
            summary += f"\nHow the rank was estimated: {response['rank_basis']}"
        for note in response.get("notes", []):
            summary += f"\nℹ {note}"
        if any(r.get("is_demo_data") for r in results):
            summary += "\n⚠ These colleges are sample data, not real admissions figures."
        self.summary.setText(summary)
        self.summary.setVisible(True)

        for band, band_title in BAND_TITLES:
            items = [r for r in results if r["band"] == band]
            if not items:
                continue
            self.results_layout.addWidget(heading(f"{band_title} ({len(items)})"))
            band_box = QVBoxLayout()
            band_box.setSpacing(8)
            holder = QWidget()
            holder.setLayout(band_box)
            self.results_layout.addWidget(holder)
            self._add_cards(band_box, items, 0)
        if not results:
            self.results_layout.addWidget(muted(
                "Try removing branch or state filters, or choosing 'Any' college type."))
        self.results_layout.addWidget(muted(response.get("disclaimer", "")))

        # Bring the answer on screen and say it: on an 800x480 panel it's below the form.
        QTimer.singleShot(50, self._show_summary)
        spoken = summary.split("\n")[0].replace("rank", "rank", 1)
        self.ctx.voice.say(spoken)

    PAGE_SIZE = 10  # hundreds of options are possible; the Pi shouldn't draw them all at once

    def _add_cards(self, box: QVBoxLayout, items: list[dict], start: int) -> None:
        chunk = items[start:start + self.PAGE_SIZE]
        for r in chunk:
            box.addWidget(self._result_card(r))
        remaining = len(items) - start - len(chunk)
        if remaining > 0:
            more = QPushButton(f"Show {min(remaining, self.PAGE_SIZE)} more ({remaining} left)")
            more.setProperty("variant", "secondary")
            more.setCursor(Qt.PointingHandCursor)

            def show_more(_checked=False, btn=more, next_start=start + self.PAGE_SIZE):
                btn.hide()
                btn.deleteLater()
                self._add_cards(box, items, next_start)

            more.clicked.connect(show_more)
            box.addWidget(more)

    def _show_summary(self) -> None:
        parent = self.parentWidget()
        while parent is not None and not hasattr(parent, "ensureWidgetVisible"):
            parent = parent.parentWidget()
        if parent is not None:
            parent.ensureWidgetVisible(self.summary, 0, 0)
            bar = parent.verticalScrollBar()
            bar.setValue(min(bar.maximum(), self.summary.mapTo(self, self.summary.rect().topLeft()).y() - 8))

    def _result_card(self, r: dict) -> QWidget:
        card = Card()
        header = QHBoxLayout()
        name = QLabel(f"<b>{r['college_name']}</b>")
        name.setWordWrap(True)
        header.addWidget(name, 1)
        if r.get("is_demo_data"):
            header.addWidget(demo_badge())
        holder = QWidget()
        holder.setLayout(header)
        card.addWidget(holder)
        branch = f" · {r['branch_name']}" if r.get("branch_name") else ""
        card.addWidget(muted(f"{r['course_name']}{branch} · {r['city']}, {r['state']}"))
        meta = QHBoxLayout()
        meta.addWidget(chance_badge(r["band"], r["band_label"], r["band_emoji"]))
        seat = "" if r.get("seat_type", "Gender-Neutral") == "Gender-Neutral" else " · female-only seats"
        quota = {"AI": "All-India", "HS": "home-state", "OS": "other-state", "AIQ": "All-India quota",
                 "Open": "open seats", "Deemed": "deemed university", "Delhi": "Delhi quota",
                 "Puducherry": "Puducherry quota"}.get(r["quota"], r["quota"])
        category = "OPEN" if r["category"] == "General" else r["category"]
        details = muted(f"{r['college_type']} · {category} {quota}{seat}")
        details.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        meta.addWidget(details, 1)
        meta_holder = QWidget()
        meta_holder.setLayout(meta)
        card.addWidget(meta_holder)
        reasoning = QLabel(r["explanation"]["reasoning"])
        reasoning.setWordWrap(True)
        card.addWidget(reasoning)
        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        details_btn = ghost_button("College details")
        details_btn.clicked.connect(lambda _c=False, cid=r["college_id"]: self.ctx.navigate("college_detail", college_id=cid))
        buttons.addWidget(details_btn)
        compare = ghost_button(self._compare_label(r["college_id"]))
        compare.college_id = r["college_id"]
        compare.clicked.connect(lambda _c=False, cid=r["college_id"], btn=compare: self._toggle_compare(cid, btn))
        buttons.addWidget(compare)
        buttons.addStretch(1)
        holder = QWidget()
        holder.setLayout(buttons)
        card.addWidget(holder)
        return card

    def _compare_label(self, college_id: int) -> str:
        return "✓ In compare" if college_id in self.compare_ids else "+ Compare"

    def _toggle_compare(self, college_id: int, button) -> None:
        if college_id in self.compare_ids:
            self.compare_ids.remove(college_id)
        elif len(self.compare_ids) < 4:
            self.compare_ids.append(college_id)
        else:
            set_error(self.error, "You can compare up to 4 colleges at a time.")
            return
        set_error(self.error, None)
        button.setText(self._compare_label(college_id))
        # The same college can appear under several seat types; keep those buttons in step.
        for other in self.results_container.findChildren(type(button)):
            if other is not button and other.text() in ("✓ In compare", "+ Compare") \
                    and getattr(other, "college_id", None) == college_id:
                other.setText(self._compare_label(college_id))
        count = len(self.compare_ids)
        self.compare_btn.setText(f"Compare {count} colleges  ›" if count >= 2 else "")
        self.compare_btn.setVisible(count >= 2)

    def _failed(self, err: Exception) -> None:
        self.submit_btn.setEnabled(True)
        self.submit_btn.setText("Save & predict colleges")
        message = err.message if isinstance(err, ApiError) else "Something went wrong. Please try again."
        set_error(self.error, message)
