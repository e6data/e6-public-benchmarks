#!/bin/bash
# Start the optional Benchmark Studio UI. Existing CLI runners are independent.
set -e
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

if [ -f "$ROOT/.benchmark-ui.env" ]; then
    set -a
    # shellcheck disable=SC1091
    source "$ROOT/.benchmark-ui.env"
    set +a
fi

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

if [ -x "$ROOT/.venv/bin/python" ]; then
    UI_PYTHON="$ROOT/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    UI_PYTHON="$(command -v python3)"
else
    echo "ERROR: Python 3 was not found. Run ./setup_ui.sh first."
    exit 1
fi

# exec preserves this PID for the Python server. stop_ui.sh only stops the
# process recorded for this checkout.
printf '%s\n' "$$" > "$PID_FILE"
exec "$UI_PYTHON" -m ui.server "$@"
