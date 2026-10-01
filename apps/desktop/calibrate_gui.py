#!/usr/bin/env python3
"""The crosshair calibration as a window of its own, for ./calibrate.sh — the same screen
MAYA shows on first start and from "Calibrate touch" on the dashboard."""

import os
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from app.touch_calibration import NoTouchscreen, find_touch_device
from app.widgets.calibration_view import CalibrationView, describe_result
from calibrate_touch import save_and_install


def run_gui() -> None:
    try:
        path, name = find_touch_device()
    except NoTouchscreen as e:
        sys.exit(str(e))
    if not os.access(path, os.R_OK):
        sys.exit(f"Cannot read {path}. Add yourself to the 'input' group, or run with sudo.")
    print(f"Touch device: {name}  ({path})")

    app = QApplication(sys.argv)
    view = CalibrationView(path)

    def finished(matrix: list, error_px: float) -> None:
        _accurate, message = describe_result(error_px)
        print(message)
        print(save_and_install(name, matrix, error_px))
        QTimer.singleShot(500, app.quit)

    def failed(message: str) -> None:
        print(message)
        view.start()

    view.finished.connect(finished)
    view.failed.connect(failed)
    view.setGeometry(app.primaryScreen().geometry())
    view.showFullScreen()
    view.start()
    sys.exit(app.exec())


if __name__ == "__main__":
    run_gui()
