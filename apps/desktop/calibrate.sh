#!/bin/bash
# Touch calibration for the kiosk panel: tap five crosshairs, and the mapping from the
# panel's raw values to screen pixels is solved, checked, and installed.
#
#   ./calibrate.sh          run it (starts its own X session if you're at a plain console)
#   sudo ./calibrate.sh     same, but also installs the result system-wide for you
#
# Without sudo it saves the snippet next to this script and prints the one command to
# install it. Either way, restart X afterwards for it to take effect.
set -e
cd "$(dirname "$0")"
PYTHON="$PWD/.venv/bin/python"

if [ -n "$DISPLAY" ]; then
    exec "$PYTHON" calibrate_gui.py
fi
if command -v xinit >/dev/null; then
    echo "No X session — starting one just for the calibration…"
    exec xinit "$PYTHON" "$PWD/calibrate_gui.py" -- :0 vt$(fgconsole 2>/dev/null || echo 1)
fi
echo "No X available; falling back to the terminal version."
exec "$PYTHON" calibrate_touch.py --text
