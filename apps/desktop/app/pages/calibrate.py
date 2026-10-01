"""Touch calibration inside MAYA: tap five crosshairs, and taps land where you put them.

Runs by itself on the first start when the panel has never been calibrated, and any time
from the dashboard ("Calibrate touch"). The result is applied immediately and saved, so it
holds on every later start without root or an X restart.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app import touch_calibration
from app.pages.base import BasePage
from app.widgets.calibration_view import CalibrationView, describe_result
from app.widgets.common import primary_button, secondary_button

# On first start nobody may be there to calibrate (or the panel may be the wrong one): carry
# on after this long without a touch rather than stranding the device on crosshairs.
FIRST_RUN_TIMEOUT_MS = 90_000


class CalibrationPage(BasePage):
    def __init__(self, ctx):
        super().__init__(ctx)
        self.first_run = False
        self.view: CalibrationView | None = None
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("CalibrationPage { background: #0f172a; }")

        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(0, 0, 0, 0)
        self.layout_.setSpacing(0)

        self.result = QWidget()
        result_layout = QVBoxLayout(self.result)
        result_layout.setContentsMargins(40, 40, 40, 40)
        result_layout.addStretch(1)
        self.result_title = QLabel("")
        self.result_title.setWordWrap(True)
        self.result_title.setAlignment(Qt.AlignCenter)
        self.result_title.setStyleSheet("background: transparent; color: #f8fafc; font-size: 18px; font-weight: 700;")
        result_layout.addWidget(self.result_title)
        self.result_detail = QLabel("")
        self.result_detail.setWordWrap(True)
        self.result_detail.setAlignment(Qt.AlignCenter)
        self.result_detail.setStyleSheet("background: transparent; color: #cbd5e1;")
        result_layout.addWidget(self.result_detail)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.again_btn = secondary_button("Calibrate again")
        self.again_btn.clicked.connect(self._restart)
        buttons.addWidget(self.again_btn)
        self.done_btn = primary_button("Done")
        self.done_btn.clicked.connect(self._done)
        buttons.addWidget(self.done_btn)
        buttons.addStretch(1)
        result_layout.addSpacing(16)
        result_layout.addLayout(buttons)
        result_layout.addStretch(1)
        self.result.setVisible(False)
        self.layout_.addWidget(self.result)

        self._timeout = QTimer(self)
        self._timeout.setSingleShot(True)
        self._timeout.timeout.connect(self._give_up_waiting)

    # ---------------- starting ----------------

    def on_show(self, first_run: bool = False, **kwargs) -> None:
        self.first_run = first_run
        try:
            path, self.device_name = touch_calibration.find_touch_device()
        except touch_calibration.NoTouchscreen as e:
            self._show_result("No touchscreen found", str(e), can_retry=False)
            return
        if self.view is None:
            self.view = CalibrationView(path)
            self.view.finished.connect(self._calibrated)
            self.view.failed.connect(lambda message: self._show_result("Let's try that again", message))
            self.layout_.insertWidget(0, self.view, 1)
        self._restart()

    def _restart(self) -> None:
        self.result.setVisible(False)
        self.view.setVisible(True)
        self.view.start()
        if self.first_run:
            self._timeout.start(FIRST_RUN_TIMEOUT_MS)

    # ---------------- finishing ----------------

    def _calibrated(self, matrix: list, error_px: float) -> None:
        self._timeout.stop()
        touch_calibration.save(self.device_name, matrix, error_px)
        problem = touch_calibration.apply(matrix, self.device_name)
        accurate, message = describe_result(error_px)
        if problem:
            self._show_result(
                "Calibration saved",
                f"{message}\nIt couldn't be applied right now ({problem}); it will be the next time MAYA starts.",
            )
        else:
            self._show_result("All set" if accurate else "Nearly there", message)

    def _show_result(self, title: str, detail: str, can_retry: bool = True) -> None:
        if self.view is not None:
            self.view.stop()
            self.view.setVisible(False)
        self.result_title.setText(title)
        self.result_detail.setText(detail)
        self.again_btn.setVisible(can_retry)
        self.result.setVisible(True)

    def _give_up_waiting(self) -> None:
        # Nobody tapped: remember that, so the next start doesn't ask again (it's always on
        # the dashboard), and carry on.
        if self.view is not None:
            self.view.stop()
        touch_calibration.mark_skipped()
        self._done()

    def _done(self) -> None:
        self._timeout.stop()
        if self.view is not None:
            self.view.stop()
        if self.first_run:
            self.ctx.start_session()
        else:
            self.ctx.go_back()

    def back_mode(self) -> str:
        return "history"

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:  # a USB keyboard or mouse user can always get out
            self._done()
