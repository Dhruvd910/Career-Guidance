#!/usr/bin/env python3
"""Touch calibration from a terminal, for when MAYA isn't running.

MAYA calibrates the panel itself — on first start, and from "Calibrate touch" on the
dashboard — so normally you won't need this. It's here for a headless session (no X) or
for installing the calibration system-wide so other programs get it too.

    ./calibrate.sh                     crosshairs on screen (starts X if needed)
    python3 calibrate_touch.py --text  no X: prompts in the terminal instead
    sudo ... either of the above       also installs it to /etc/X11/xorg.conf.d

The maths and device handling live in app/touch_calibration.py, shared with MAYA.
"""

import os
import sys

from app.touch_calibration import (  # noqa: F401 — re-exported for tests and older callers
    CONF_DIR, CONF_NAME, RAW_MAX, TARGETS, CalibrationError, NoTouchscreen, apply, apply_matrix,
    conf_snippet, find_touch_device, full_matrix, read_one_touch, save, solve_affine,
)


def save_and_install(device_name: str, matrix: list[float], error_px: float | None = None) -> str:
    """Saves for MAYA (applied at every start), applies it now if a desktop or X is running,
    and — as root — installs it system-wide for X. Returns what happened, in words."""
    save(device_name, matrix, error_px)
    lines = ["Saved — MAYA applies it every time she starts."]
    if os.environ.get("DISPLAY") or os.environ.get("LABWC_PID"):
        problem = apply(matrix, device_name)
        lines.append("Applied now." if problem is None else f"Not applied right now: {problem}.")
    matrix_text = " ".join(f"{v:.6f}" for v in matrix)
    if os.geteuid() == 0:
        os.makedirs(CONF_DIR, exist_ok=True)
        path = os.path.join(CONF_DIR, CONF_NAME)
        with open(path, "w") as f:
            f.write(conf_snippet(device_name, matrix_text))
        lines.append(f"Also installed system-wide to {path}.")
    return "\n".join(lines)


def main() -> None:
    try:
        path, name = find_touch_device()
    except NoTouchscreen as e:
        sys.exit(str(e))
    print(f"Touch device: {name}  ({path})")
    if not os.access(path, os.R_OK):
        sys.exit(f"Cannot read {path}. Add yourself to the 'input' group or run with sudo.")

    print(f"\nTouch each spot as accurately as you can. {len(TARGETS)} touches total. Ctrl+C to stop.\n")
    samples = []
    for label, fx, fy in TARGETS:
        print(f"  Touch the {label.upper()} area ({int(fx * 100)}% across, {int(fy * 100)}% down)... ", end="", flush=True)
        tx, ty = read_one_touch(path)
        print(f"got raw ({tx}, {ty})")
        samples.append((tx / RAW_MAX, ty / RAW_MAX, fx, fy))

    try:
        matrix = full_matrix(solve_affine(samples))
    except CalibrationError as e:
        sys.exit(str(e))
    print("\nCalibration matrix:\n  " + " ".join(f"{v:.6f}" for v in matrix))
    print(save_and_install(name, matrix))


if __name__ == "__main__":
    if "--text" in sys.argv or not os.environ.get("DISPLAY"):
        main()
    else:
        from calibrate_gui import run_gui

        run_gui()
