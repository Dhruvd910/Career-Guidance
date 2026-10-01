from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QPainter
from PySide6.QtCharts import QChart, QChartView, QLineSeries, QValueAxis
from PySide6.QtWidgets import (
    QComboBox, QDateEdit, QFormLayout, QGridLayout, QHBoxLayout, QLineEdit,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from app.api_client import ApiError, api_client
from app.config import SUBJECTS_BY_EXAM
from app.goal import default_exam_code
from app.layout import columns, page_margins
from app.pages.base import BasePage
from app.widgets.common import (
    Card, error_label, heading, muted, primary_button, secondary_button, set_error, subtitle,
)
from app.workers import run_async


class MockTestsPage(BasePage):
    def __init__(self, ctx):
        super().__init__(ctx)
        outer = QVBoxLayout(self)  # MainWindow scrolls the page
        outer.setContentsMargins(*page_margins())
        outer.setSpacing(14)

        outer.addWidget(heading("Mock Tests"))
        outer.addWidget(subtitle("Sit a practice paper here, or log a test you took elsewhere — both count towards your trends."))

        # ---- take a test in the app ----
        practice_card = Card()
        practice_card.addWidget(heading("Practise now"))
        self.practice_hint = muted("Loading practice papers…")
        practice_card.addWidget(self.practice_hint)
        self.subject_buttons = QGridLayout()
        self.subject_buttons.setSpacing(8)
        subject_holder = QWidget()
        subject_holder.setLayout(self.subject_buttons)
        practice_card.addWidget(subject_holder)
        self.full_test_btn = primary_button("Full-length mock test")
        self.full_test_btn.setMinimumHeight(46)
        self.full_test_btn.setVisible(False)
        self.full_test_btn.clicked.connect(lambda: self._start("full", None))
        practice_card.addWidget(self.full_test_btn)
        self.full_test_note = muted("")
        practice_card.addWidget(self.full_test_note)
        self.practice_error = error_label()
        practice_card.addWidget(self.practice_error)
        outer.addWidget(practice_card)

        # ---- log a test taken elsewhere ----
        self.log_toggle = secondary_button("Log a test I took elsewhere")
        self.log_toggle.clicked.connect(self._toggle_log_form)
        outer.addWidget(self.log_toggle)

        form_card = Card()
        self.form_card = form_card
        form_card.setVisible(False)
        form_card.addWidget(heading("Log a test you took elsewhere"))
        form = QFormLayout()

        self.exam_combo = QComboBox()
        self.exam_combo.addItems(list(SUBJECTS_BY_EXAM.keys()))
        self.exam_combo.currentTextChanged.connect(self._rebuild_subject_fields)
        self.exam_combo.activated.connect(lambda _index: self._load_practice_options())
        form.addRow("Exam", self.exam_combo)

        self.test_name_input = QLineEdit()
        form.addRow("Test name", self.test_name_input)

        self.date_input = QDateEdit()
        self.date_input.setDate(QDate.currentDate())
        self.date_input.setCalendarPopup(True)
        form.addRow("Date", self.date_input)

        self.max_score_input = QLineEdit("300")
        form.addRow("Max score", self.max_score_input)

        self.subject_inputs: dict[str, QLineEdit] = {}
        self.subject_form_rows: list[tuple] = []
        form_widget = QWidget()
        form_widget.setLayout(form)
        form_card.addWidget(form_widget)
        self.subject_form = form

        self.error = error_label()
        form_card.addWidget(self.error)

        add_btn = primary_button("Add Mock Test")
        add_btn.clicked.connect(self._add_test)
        form_card.addWidget(add_btn)
        outer.addWidget(form_card)

        self._rebuild_subject_fields(self.exam_combo.currentText())

        stats_grid = QGridLayout()
        self.stat_labels = {}
        for i, key in enumerate(["Average", "Best", "Lowest", "Recent avg"]):
            card = Card()
            card.addWidget(muted(key))
            value_label = heading("—")
            card.addWidget(value_label)
            self.stat_labels[key] = value_label
            stats_grid.addWidget(card, 0, i)
        stats_widget = QWidget()
        stats_widget.setLayout(stats_grid)
        outer.addWidget(stats_widget)

        chart_card = Card()
        chart_card.addWidget(heading("Score trend"))
        self.chart_view = QChartView()
        self.chart_view.setRenderHint(QPainter.Antialiasing)
        self.chart_view.setMinimumHeight(260)
        chart_card.addWidget(self.chart_view)
        outer.addWidget(chart_card)

        insight_row = QHBoxLayout()
        self.strong_card = Card()
        self.strong_card.addWidget(heading("Strengths & weak areas"))
        self.strong_label = muted("—")
        self.weak_label = muted("—")
        self.estimate_label = muted("")
        self.strong_card.addWidget(self.strong_label)
        self.strong_card.addWidget(self.weak_label)
        self.strong_card.addWidget(self.estimate_label)
        insight_row.addWidget(self.strong_card)
        insight_widget = QWidget()
        insight_widget.setLayout(insight_row)
        outer.addWidget(insight_widget)

        history_card = Card()
        history_card.addWidget(heading("History"))
        self.history_table = QTableWidget(0, 3)
        self.history_table.setHorizontalHeaderLabels(["Test", "Date", "Score"])
        self.history_table.horizontalHeader().setStretchLastSection(True)
        history_card.addWidget(self.history_table)
        outer.addWidget(history_card)

    def _rebuild_subject_fields(self, exam_code: str) -> None:
        for _, label_widget, input_widget in self.subject_form_rows:
            self.subject_form.removeRow(label_widget)
        self.subject_form_rows.clear()
        self.subject_inputs.clear()
        for subject in SUBJECTS_BY_EXAM.get(exam_code, []):
            field = QLineEdit()
            self.subject_form.addRow(f"{subject} marks", field)
            self.subject_inputs[subject] = field
            self.subject_form_rows.append((subject, self.subject_form.labelForField(field), field))

    # ---------------- practice papers ----------------

    def _toggle_log_form(self) -> None:
        showing = not self.form_card.isVisible()
        self.form_card.setVisible(showing)
        self.log_toggle.setText("Hide the manual entry form" if showing else "Log a test I took elsewhere")

    def _exam_code(self) -> str:
        return self.exam_combo.currentText()

    def _load_practice_options(self) -> None:
        set_error(self.practice_error, None)
        run_async(api_client.practice_options, self._exam_code(),
                  on_success=self._render_practice_options, on_error=self._practice_failed)

    def _render_practice_options(self, options: dict) -> None:
        while self.subject_buttons.count():
            item = self.subject_buttons.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        subjects = options.get("subjects", [])
        if not subjects:
            self.practice_hint.setText("No practice questions are loaded for this exam yet.")
            self.full_test_btn.setVisible(False)
            self.full_test_note.setText("")
            return

        self.practice_hint.setText(
            f"One subject at a time, {subjects[0]['question_count']} questions each — "
            "marked the way the real paper is (+4 correct, −1 wrong)."
        )
        per_row = columns(3, compact=2)
        for i, subject in enumerate(subjects):
            btn = secondary_button(f"{subject['subject']}\n{subject['question_count']} questions")
            btn.setMinimumHeight(52)
            btn.clicked.connect(lambda _checked=False, name=subject["subject"]: self._start("subject", name))
            self.subject_buttons.addWidget(btn, i // per_row, i % per_row)

        total, minutes = options["full_test_questions"], options["full_test_minutes"]
        self.full_test_btn.setVisible(bool(total))
        self.full_test_btn.setText(f"Full-length mock test · {total} questions · {minutes} min")
        breakdown = ", ".join(f"{n} {s}" for s, n in options["full_test_breakdown"].items())
        self.full_test_note.setText(
            f"{breakdown} — the same subject mix as the real {options['exam_code'].replace('_', ' ')} paper, "
            f"which has {options['real_paper_questions']} questions in {options['real_paper_minutes']} minutes."
        )

    def _start(self, mode: str, subject: str | None) -> None:
        set_error(self.practice_error, None)
        self.full_test_btn.setEnabled(False)
        run_async(api_client.start_practice, self._exam_code(), mode, subject,
                  on_success=self._open_test, on_error=self._practice_failed)

    def _open_test(self, attempt: dict) -> None:
        self.full_test_btn.setEnabled(True)
        self.ctx.navigate("practice_test", attempt=attempt)

    def _practice_failed(self, err: Exception) -> None:
        self.full_test_btn.setEnabled(True)
        set_error(self.practice_error,
                  err.message if isinstance(err, ApiError) else "Could not load the practice papers.")

    def on_show(self, **kwargs) -> None:
        set_error(self.error, None)
        # The goal can be chosen (or changed) after this page was built, so it's applied here.
        self.exam_combo.setCurrentText(default_exam_code(fallback=self.exam_combo.currentText()))
        self._load_practice_options()
        self._load()

    def _load(self) -> None:
        run_async(api_client.mock_test_dashboard, on_success=self._render_dashboard, on_error=self._failed)
        run_async(api_client.mock_test_history, on_success=self._render_history, on_error=lambda _e: None)

    def _add_test(self) -> None:
        set_error(self.error, None)
        exam_code = self.exam_combo.currentText()
        try:
            max_score = float(self.max_score_input.text())
        except ValueError:
            set_error(self.error, "Max score must be a number.")
            return

        subject_scores = {}
        total = 0.0
        for subject, field in self.subject_inputs.items():
            try:
                value = float(field.text() or 0)
            except ValueError:
                value = 0.0
            subject_scores[subject.lower()] = value
            total += value

        if not self.test_name_input.text().strip():
            set_error(self.error, "Give this test a name.")
            return

        run_async(
            api_client.create_mock_test,
            exam_code=exam_code, test_name=self.test_name_input.text().strip(),
            test_date=self.date_input.date().toString("yyyy-MM-dd"),
            total_score=total, max_score=max_score, subject_scores=subject_scores,
            on_success=lambda _r: self._on_added(),
            on_error=self._failed,
        )

    def _on_added(self) -> None:
        self.test_name_input.clear()
        for field in self.subject_inputs.values():
            field.clear()
        self._load()

    def _render_dashboard(self, d: dict) -> None:
        if d.get("test_count", 0) == 0:
            for label in self.stat_labels.values():
                label.setText("—")
            self.strong_label.setText("No mock tests logged yet.")
            self.weak_label.setText("")
            self.estimate_label.setText("")
            self.chart_view.setChart(QChart())
            return

        self.stat_labels["Average"].setText(f"{d['average_score_pct']}%")
        self.stat_labels["Best"].setText(f"{d['best_score_pct']}%")
        self.stat_labels["Lowest"].setText(f"{d['lowest_score_pct']}%")
        self.stat_labels["Recent avg"].setText(f"{d['recent_average_pct']}%")

        self.strong_label.setText(f"Strong: {', '.join(d['strong_subjects']) or 'Not enough data yet'}")
        self.weak_label.setText(f"Needs work: {', '.join(d['weak_subjects']) or 'None flagged yet'}")
        if d.get("estimated_rank_range"):
            self.estimate_label.setText(f"Estimated rank range: {d['estimated_rank_range']} ({d['estimate_disclaimer']})")
        else:
            self.estimate_label.setText(d.get("estimate_disclaimer", ""))

        series = QLineSeries()
        for i, point in enumerate(d["trend"]):
            series.append(i, point["score_pct"])
        chart = QChart()
        chart.addSeries(series)
        chart.legend().hide()
        axis_x = QValueAxis()
        axis_x.setLabelFormat("%d")
        axis_x.setTitleText("Test #")
        axis_y = QValueAxis()
        axis_y.setRange(0, 100)
        axis_y.setTitleText("Score %")
        chart.addAxis(axis_x, Qt.AlignBottom)
        chart.addAxis(axis_y, Qt.AlignLeft)
        series.attachAxis(axis_x)
        series.attachAxis(axis_y)
        chart.setBackgroundVisible(False)
        self.chart_view.setChart(chart)

    def _render_history(self, tests: list) -> None:
        self.history_table.setRowCount(len(tests))
        for row, t in enumerate(tests):
            self.history_table.setItem(row, 0, QTableWidgetItem(t["test_name"]))
            self.history_table.setItem(row, 1, QTableWidgetItem(t["test_date"]))
            self.history_table.setItem(row, 2, QTableWidgetItem(f"{t['total_score']} / {t['max_score']}"))

    def _failed(self, err: Exception) -> None:
        message = err.message if isinstance(err, ApiError) else "Could not load mock test data."
        set_error(self.error, message)
