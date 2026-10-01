#!/bin/bash
# One-liner to shut MAYA down: ./stop.sh
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_DIR="$ROOT/.run"

stop_pidfile() {
    local name="$1" pidfile="$2"
    if [ -f "$pidfile" ] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
        kill "$(cat "$pidfile")"
        echo "Stopped $name (PID $(cat "$pidfile"))."
    else
        echo "$name was not running."
    fi
    rm -f "$pidfile"
}

stop_pidfile "MAYA desktop app" "$RUN_DIR/desktop.pid"
stop_pidfile "API" "$RUN_DIR/api.pid"
