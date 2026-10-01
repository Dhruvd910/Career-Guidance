"""The tap-the-crosshairs screen, shared by MAYA's calibration page and the standalone
calibrate.sh.

Every touch anywhere on the panel counts as the touch for the current crosshair: raw values
come straight from /dev/input, so this works however wrong the current mapping is — which is
the whole point, since a badly calibrated panel can't be trusted to hit a button.
"""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, QPoint, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from app.touch_calibration import (
    GOOD_ENOUGH_PX, RAW_MAX, TARGETS, VERIFY_TARGET, CalibrationError, apply_matrix, full_matrix,
    read_one_touch, solve_affine,
)


class TouchReader(QObject):
    """Reads raw touches off the device in a thread and hands them to the UI thread."""

    touched = Signal(int, int)

    def __init__(self, path: str):
        super().__init__()
        self._path = path
        self._wanted = threading.Event()
        self._stop = threading.Event()
        threading.Thread(target=self._run, name="touch-calibration", daemon=True).start()

    def want_touch(self) -> None:
        self._wanted.set()

    def stop(self) -> None:
        self._stop.set()
        self._wanted.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            self._wanted.wait()
            if self._stop.is_set():
                return
            try:
                point = read_one_touch(self._path, self._stop)
            except OSError:
                continue
            if point is not None and not self._stop.is_set():
                self._wanted.clear()
                self.touched.emit(*point)


class CalibrationView(QWidget):
    """Emits finished(matrix, error_px) after four targets and a check, or failed(message)."""

    finished = Signal(list, float)
    failed = Signal(str)

    def __init__(self, device_path: str, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("background: #0f172a;")
        self.samples: list[tuple[float, float, float, float]] = []
        self.step = 0
        self.affine: tuple[float, ...] | None = None
        self.reader = TouchReader(device_path)
        self.reader.touched.connect(self._on_touch)
        self._active = False

    def start(self) -> None:
        self.samples, self.step, self.affine = [], 0, None
        self._active = True
        self.update()
        # Only once the first crosshair is actually on screen.
        QTimer.singleShot(400, self.reader.want_touch)

    def stop(self) -> None:
        self._active = False

    def shutdown(self) -> None:
        self._active = False
        self.reader.stop()

    def _target(self) -> tuple[str, float, float] | None:
        if self.step < len(TARGETS):
            return TARGETS[self.step]
        if self.step == len(TARGETS):
            return VERIFY_TARGET
        return None

    def _on_touch(self, raw_x: int, raw_y: int) -> None:
        target = self._target()
        if not self._active or target is None:
            return
        _label, fx, fy = target
        tx, ty = raw_x / RAW_MAX, raw_y / RAW_MAX
        if self.step < len(TARGETS):
            self.samples.append((tx, ty, fx, fy))
            self.step += 1
            if self.step == len(TARGETS):
                try:
                    self.affine = solve_affine(self.samples)
                except CalibrationError as e:
                    self._active = False
                    self.failed.emit(str(e))
                    return
            self.reader.want_touch()
            self.update()
            return
        # The check: how far from the centre target does the solved mapping put this touch?
        mapped_x, mapped_y = apply_matrix(self.affine, tx, ty)
        screen = self.screen().geometry()
        error = (((mapped_x - fx) * screen.width()) ** 2 + ((mapped_y - fy) * screen.height()) ** 2) ** 0.5
        self.step += 1
        self._active = False
        self.update()
        self.finished.emit(full_matrix(self.affine), float(error))

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#0f172a"))
        target = self._target()
        if target is None or not self._active:
            return
        label, fx, fy = target
        # Targets are placed in *screen* coordinates — that's what the mapping is solved
        # against — and only then translated into this widget, wherever it sits.
        screen = self.screen().geometry()
        point = self.mapFromGlobal(screen.topLeft() + QPoint(int(fx * screen.width()), int(fy * screen.height())))
        x, y = point.x(), point.y()
        painter.setPen(QPen(QColor("#818cf8"), 2))
        painter.drawLine(int(x - 24), int(y), int(x + 24), int(y))
        painter.drawLine(int(x), int(y - 24), int(x), int(y + 24))
        painter.setPen(QPen(QColor("#c7d2fe"), 2))
        painter.drawEllipse(QRectF(x - 11, y - 11, 22, 22))
        painter.setPen(QPen(QColor("#f8fafc"), 4))
        painter.drawPoint(int(x), int(y))

        verifying = self.step == len(TARGETS)
        painter.setPen(QPen(QColor("#e2e8f0")))
        painter.setFont(QFont("DejaVu Sans", 13))
        headline = ("Last one: touch the centre so I can check it." if verifying
                    else f"Touch the {label} crosshair, as precisely as you can.")
        painter.drawText(self.rect().adjusted(40, int(self.height() * 0.25), -40, 0),
                         Qt.AlignHCenter | Qt.AlignTop, headline)
        painter.setPen(QPen(QColor("#94a3b8")))
        painter.setFont(QFont("DejaVu Sans", 10))
        painter.drawText(self.rect().adjusted(40, 0, -40, -int(self.height() * 0.25)),
                         Qt.AlignHCenter | Qt.AlignBottom,
                         f"{self.step + 1} of {len(TARGETS) + 1} · use a fingertip or stylus")


def describe_result(error_px: float) -> tuple[bool, str]:
    accurate = error_px <= GOOD_ENOUGH_PX
    if accurate:
        return True, f"Touch is calibrated — taps land within about {error_px:.0f}px of your finger."
    return False, (f"Your check tap landed about {error_px:.0f}px off. That's usable, but calibrating "
                   "again with more careful taps will make buttons easier to hit.")
