"""Touchscreen calibration: reading raw touches, solving the mapping, and keeping it applied.

The ADS7846 panel reports raw 0-4095 values on both axes with no relation to the screen, and
libinput maps that range straight onto the display, so an uncalibrated panel puts every tap
somewhere else. Calibration solves an affine map from four taps on known targets, checks it
with a fifth, and hands it to libinput as its "Calibration Matrix".

It's saved per user and re-applied every time MAYA starts, neither of which needs root. Where
it goes depends on the session:
- the Raspberry Pi desktop (labwc, Wayland): into labwc's rc.xml, which labwc reloads at once
  (labwc_input.set_calibration). It then holds for every program on the desktop.
- the kiosk's bare X session: onto the running X server (x11_input.set_calibration). X
  forgets it on exit; the system-wide xorg.conf.d snippet (calibrate.sh with sudo) is the
  option for anyone who wants it to hold for other programs too.

Raw values are read from /dev/input directly — never from the display server, since it is
applying the very mapping being replaced. The user needs to be in the `input` group, which
`pi` is by default.
"""

from __future__ import annotations

import json
import os
import re
import select
import struct
import threading
import time
from pathlib import Path

# struct input_event { struct timeval time; __u16 type; __u16 code; __s32 value; }
EVENT_FORMAT = "llHHi"
EVENT_SIZE = struct.calcsize(EVENT_FORMAT)
EV_KEY, EV_ABS = 0x01, 0x03
ABS_X, ABS_Y = 0x00, 0x01
BTN_TOUCH = 0x14A
RAW_MAX = 4095.0  # ADS7846 reports a 12-bit range on both axes

# Where the targets go, as fractions of the screen. Kept off the very edges: resistive panels
# are least accurate right at the bezel.
TARGETS = [
    ("top left", 0.1, 0.1),
    ("top right", 0.9, 0.1),
    ("bottom right", 0.9, 0.9),
    ("bottom left", 0.1, 0.9),
]
VERIFY_TARGET = ("centre", 0.5, 0.5)
GOOD_ENOUGH_PX = 20  # a fingertip is wider than this; beyond it, taps land on the wrong button
IDENTITY = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]

CALIBRATION_FILE = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "AICareerGuide" / "touch_calibration.json"
CONF_NAME = "99-touch-calibration.conf"
CONF_DIR = "/etc/X11/xorg.conf.d"


class NoTouchscreen(Exception):
    pass


# ---------------- the device ----------------

def find_touch_device() -> tuple[str, str]:
    """(event device path, device name) of the first touchscreen."""
    try:
        with open("/proc/bus/input/devices") as f:
            blocks = f.read().split("\n\n")
    except OSError as e:
        raise NoTouchscreen(f"could not read the input device list: {e}") from e
    for block in blocks:
        name_match = re.search(r'N: Name="([^"]*)"', block)
        if not name_match or "touch" not in name_match.group(1).lower():
            continue
        handler_match = re.search(r"H: Handlers=.*?(event\d+)", block)
        if handler_match:
            return f"/dev/input/{handler_match.group(1)}", name_match.group(1)
    raise NoTouchscreen("no touchscreen found")


def read_one_touch(path: str, stop: threading.Event | None = None) -> tuple[int, int] | None:
    """Blocks until one complete touch (press, then release) and returns its median raw point.
    Returns None if `stop` is set first."""
    xs: list[int] = []
    ys: list[int] = []
    touching = False
    with open(path, "rb", buffering=0) as dev:
        while stop is None or not stop.is_set():
            ready, _, _ = select.select([dev], [], [], 0.2)
            if not ready:
                continue
            data = dev.read(EVENT_SIZE)
            if not data:  # end of file — only a stand-in device does that; don't spin
                time.sleep(0.05)
                continue
            if len(data) < EVENT_SIZE:
                continue
            _sec, _usec, etype, code, value = struct.unpack(EVENT_FORMAT, data)
            if etype == EV_KEY and code == BTN_TOUCH:
                if value == 1:
                    touching, xs, ys = True, [], []
                elif value == 0 and touching:
                    touching = False
                    if xs and ys:
                        xs.sort()
                        ys.sort()
                        return xs[len(xs) // 2], ys[len(ys) // 2]
            elif etype == EV_ABS and touching:
                if code == ABS_X:
                    xs.append(value)
                elif code == ABS_Y:
                    ys.append(value)
    return None


# ---------------- the maths ----------------

class CalibrationError(Exception):
    pass


def solve_affine(samples: list[tuple[float, float, float, float]]) -> tuple[float, ...]:
    """Least-squares fit of screen = A * touch, in normalized coordinates.

    Each sample is (touch_x, touch_y, screen_x, screen_y), all 0..1. Returns (a, b, c, d, e, f)
    where screen_x = a*tx + b*ty + c and screen_y = d*tx + e*ty + f.
    """
    def solve_3x3(rows: list[list[float]]) -> list[float]:
        m = [row[:] for row in rows]
        for col in range(3):
            pivot = max(range(col, 3), key=lambda r: abs(m[r][col]))
            if abs(m[pivot][col]) < 1e-12:
                raise CalibrationError("the touches were too close together to solve — try again")
            m[col], m[pivot] = m[pivot], m[col]
            for r in range(3):
                if r != col:
                    factor = m[r][col] / m[col][col]
                    for c in range(col, 4):
                        m[r][c] -= factor * m[col][c]
        return [m[i][3] / m[i][i] for i in range(3)]

    lhs = [[0.0] * 3 for _ in range(3)]
    rhs_x = [0.0] * 3
    rhs_y = [0.0] * 3
    for tx, ty, sx, sy in samples:
        basis = [tx, ty, 1.0]
        for i in range(3):
            for j in range(3):
                lhs[i][j] += basis[i] * basis[j]
            rhs_x[i] += basis[i] * sx
            rhs_y[i] += basis[i] * sy

    a, b, c = solve_3x3([lhs[i][:] + [rhs_x[i]] for i in range(3)])
    d, e, f = solve_3x3([lhs[i][:] + [rhs_y[i]] for i in range(3)])
    return a, b, c, d, e, f


def apply_matrix(matrix: tuple[float, ...], tx: float, ty: float) -> tuple[float, float]:
    a, b, c, d, e, f = matrix[:6]
    return a * tx + b * ty + c, d * tx + e * ty + f


def full_matrix(affine: tuple[float, ...]) -> list[float]:
    """The 6 affine terms as the 9-value matrix libinput expects."""
    return [float(v) for v in affine[:6]] + [0.0, 0.0, 1.0]


def conf_snippet(device_name: str, matrix: str) -> str:
    return f"""Section "InputClass"
    Identifier   "{device_name} calibration"
    MatchProduct "{device_name}"
    MatchDriver  "libinput"
    Option       "CalibrationMatrix" "{matrix}"
EndSection
"""


# ---------------- keeping it ----------------

def load() -> dict | None:
    try:
        data = json.loads(CALIBRATION_FILE.read_text())
    except (OSError, ValueError):
        return None
    matrix = data.get("matrix")
    if not isinstance(matrix, list) or len(matrix) != 9:
        return None
    return data


def save(device_name: str, matrix: list[float], error_px: float | None) -> None:
    CALIBRATION_FILE.parent.mkdir(parents=True, exist_ok=True)
    CALIBRATION_FILE.write_text(json.dumps(
        {"device": device_name, "matrix": matrix, "error_px": error_px}, indent=2,
    ))


def mark_skipped() -> None:
    """Nobody calibrated on first start — don't ask on every start after that."""
    if not CALIBRATION_FILE.exists():
        CALIBRATION_FILE.parent.mkdir(parents=True, exist_ok=True)
        CALIBRATION_FILE.write_text(json.dumps({"skipped": True}))


def apply(matrix: list[float], device_name: str | None = None) -> str | None:
    """Applies a matrix to the running desktop (labwc) or X server. None on success, else why not."""
    from app import labwc_input, x11_input

    if labwc_input.running():
        return labwc_input.set_calibration(matrix, device_name)
    return x11_input.set_calibration(matrix, device_name)


def apply_saved() -> str | None:
    """Called at startup: X forgets the mapping when it exits. On labwc it's already in rc.xml,
    and re-applying the same matrix changes nothing — unless the file lost it since."""
    saved = load()
    if saved is None:
        return "no saved calibration"
    return apply(saved["matrix"], saved.get("device"))


def needs_calibration() -> bool:
    """Should MAYA ask for calibration before anything else? Only in a real graphical session
    with a readable touchscreen, when nothing — ours or a system-wide file — has calibrated it yet."""
    from app import labwc_input

    on_labwc = labwc_input.running()
    if not (on_labwc or os.environ.get("DISPLAY")) or CALIBRATION_FILE.exists():
        return False  # calibrated before — or skipped, and it's on the dashboard any time
    try:
        path, name = find_touch_device()
    except NoTouchscreen:
        return False
    if not os.access(path, os.R_OK):
        return False
    if on_labwc:
        return labwc_input.current_calibration(name) is None
    try:
        from app import x11_input

        with x11_input._X() as x:
            prop = x.atom(x11_input.MATRIX_PROPERTY)
            for dev_id, _dev_name in x.devices():
                current = x.get_floats(dev_id, prop)
                if current is not None and any(abs(a - b) > 1e-4 for a, b in zip(current, IDENTITY)):
                    return False  # already calibrated system-wide
    except OSError:
        return False
    return True
