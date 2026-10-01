#!/bin/bash
# Launched by ~/.xinitrc via `startx` — starts the FastAPI backend, waits for it to be
# ready, then runs MAYA full-screen. Kills the backend when the app exits.
set -e

DESKTOP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
API_DIR="$(dirname "$DESKTOP_DIR")/api"

(cd "$API_DIR" && exec "$API_DIR/.venv/bin/uvicorn" app.main:app --host 127.0.0.1 --port 8000) &
API_PID=$!

for _ in $(seq 1 30); do
    if curl -s -o /dev/null "http://127.0.0.1:8000/api/health"; then
        break
    fi
    sleep 0.5
done

cd "$DESKTOP_DIR"
"$DESKTOP_DIR/.venv/bin/python" main.py --kiosk

kill "$API_PID" 2>/dev/null || true
