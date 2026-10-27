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

BACKGROUND=false
HOST="${BENCHMARK_UI_HOST:-127.0.0.1}"
PORT="${BENCHMARK_UI_PORT:-8765}"
while [ "$#" -gt 0 ]; do
    case "$1" in
        --background) BACKGROUND=true; shift ;;
        --host|--port)
            [ "$#" -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
            if [ "$1" = --host ]; then HOST="$2"; else PORT="$2"; fi
            shift 2 ;;
        -h|--help)
            echo "Usage: ./start_ui.sh [--background] [--host ADDRESS] [--port PORT]"
            echo "Foreground by default (for systemd). --background appends logs/ui-console.log."
            exit 0 ;;
        *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
done
if ! [[ "$PORT" =~ ^[0-9]+$ ]] || [ "$PORT" -lt 1 ] || [ "$PORT" -gt 65535 ]; then
    echo "Port must be between 1 and 65535." >&2
    exit 2
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

if [ "$BACKGROUND" = true ]; then
    command -v curl >/dev/null || { echo "curl is required for the startup health check." >&2; exit 1; }
    mkdir -p "$ROOT/logs"
    LOG="$ROOT/logs/ui-console.log"
    nohup bash "$ROOT/start_ui.sh" --host "$HOST" --port "$PORT" >> "$LOG" 2>&1 < /dev/null &
    PID=$!
    CHECK_HOST="$HOST"
    case "$HOST" in
        0.0.0.0) CHECK_HOST=127.0.0.1 ;;
        ::) CHECK_HOST='[::1]' ;;
        *:*) CHECK_HOST="[$HOST]" ;;
    esac
    for _attempt in {1..15}; do
        sleep 1
        if ! kill -0 "$PID" 2>/dev/null; then
            echo "UI startup failed. Inspect: $LOG" >&2
            exit 1
        fi
        if [ -f "$PID_FILE" ] && [ "$(tr -cd '0-9' < "$PID_FILE")" = "$PID" ] && \
           curl --noproxy '*' --fail --silent --max-time 1 "http://$CHECK_HOST:$PORT/healthz" >/dev/null; then
            echo "Benchmark UI started (PID $PID): http://$CHECK_HOST:$PORT"
            echo "Log: $LOG"
            echo "Stop: ./stop_ui.sh"
            exit 0
        fi
    done
    echo "UI process $PID is still alive, but health was not confirmed. Inspect: $LOG" >&2
    echo "No process was killed. Stop it with ./stop_ui.sh before retrying." >&2
    exit 1
fi

# exec preserves this PID for the Python server. stop_ui.sh only stops the
# process recorded for this checkout.
printf '%s\n' "$$" > "$PID_FILE"
exec "$UI_PYTHON" -m ui.server --host "$HOST" --port "$PORT"
