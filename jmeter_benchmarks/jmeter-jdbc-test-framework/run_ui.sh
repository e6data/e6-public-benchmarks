#!/bin/bash
# Optional local UI. Existing CLI runners do not depend on this script.
set -e
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
PID_FILE="${BENCHMARK_UI_PID_FILE:-$ROOT/logs/ui.pid}"
mkdir -p "$(dirname "$PID_FILE")"

if [ -f "$PID_FILE" ]; then
    EXISTING_PID=$(tr -cd '0-9' < "$PID_FILE")
    if [ -n "$EXISTING_PID" ] && kill -0 "$EXISTING_PID" 2>/dev/null; then
        echo "Benchmark UI is already running with PID $EXISTING_PID"
        echo "Stop it with: ./stop_ui.sh"
        exit 1
    fi
    rm -f "$PID_FILE"
fi

# exec preserves this PID for the Python server. A normal restart removes a
# stale file above; stop_ui.sh removes it immediately after a successful stop.
printf '%s\n' "$$" > "$PID_FILE"
exec python3 -m ui.server "$@"
