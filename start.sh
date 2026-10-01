#!/bin/bash
# One-liner to bring up MAYA for interactive use: ./start.sh [--fullscreen]
# Starts the FastAPI backend in the background, waits for it to be healthy, then opens
# the desktop app in a normal (windowed, resizable) window, or full screen with --fullscreen
# (what the desktop icon uses). Use stop.sh to shut both down.
# For full-screen kiosk boot instead, use apps/desktop/run_kiosk.sh (what ~/.xinitrc calls).
set -e

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_DIR="$ROOT/.run"
mkdir -p "$RUN_DIR"

APP_ARGS=()
[ "$1" = "--fullscreen" ] && APP_ARGS=(--kiosk)

is_running() {
    [ -f "$1" ] && kill -0 "$(cat "$1")" 2>/dev/null
}

if is_running "$RUN_DIR/api.pid"; then
    echo "API already running (PID $(cat "$RUN_DIR/api.pid"))."
else
    (cd "$ROOT/apps/api" && exec setsid ./.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000) \
        > "$RUN_DIR/api.log" 2>&1 &
    echo $! > "$RUN_DIR/api.pid"
    echo "API starting (PID $!, log: $RUN_DIR/api.log)..."
fi

for _ in $(seq 1 30); do
    curl -s -o /dev/null "http://127.0.0.1:8000/api/health" && break
    sleep 0.5
done

if is_running "$RUN_DIR/desktop.pid"; then
    echo "Desktop app already running (PID $(cat "$RUN_DIR/desktop.pid"))."
elif [ -z "$DISPLAY" ] && [ -z "$WAYLAND_DISPLAY" ]; then
    # Without a real display, Qt falls back to a plugin that never crashes but never
    # renders anywhere either, and the GIF animation timer spins the CPU at 100%+ forever.
    # Confirmed on this exact Pi over SSH with no X/Wayland session — refusing to launch
    # into that trap is safer than a silent runaway process.
    echo "No display detected (DISPLAY and WAYLAND_DISPLAY are both unset)."
    echo "API is running, but MAYA needs a graphical session — run this from the Pi's"
    echo "console after 'startx', or over VNC/remote desktop, not a plain SSH shell."
else
    (cd "$ROOT/apps/desktop" && exec setsid ./.venv/bin/python main.py "${APP_ARGS[@]}") \
        > "$RUN_DIR/desktop.log" 2>&1 &
    echo $! > "$RUN_DIR/desktop.pid"
    echo "MAYA starting (PID $!, log: $RUN_DIR/desktop.log)..."
fi
