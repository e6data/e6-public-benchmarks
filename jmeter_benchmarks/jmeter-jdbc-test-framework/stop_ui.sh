#!/bin/bash
# Stop only the UI process recorded by this checkout's start_ui.sh. If the PID
# file is missing (for example, after a manual/nohup start), safely fall back to
# the UI listener owned by this checkout.
set -e

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="${BENCHMARK_UI_PID_FILE:-$ROOT/logs/ui.pid}"
PORT="${BENCHMARK_UI_PORT:-8765}"

if [ "${1:-}" = "--port" ]; then
    if [[ "${2:-}" =~ ^[0-9]+$ ]] && [ "$2" -ge 1 ] && [ "$2" -le 65535 ]; then
        PORT="$2"
    else
        echo "Usage: ./stop_ui.sh [--port 1-65535]"
        exit 2
    fi
elif [ "$#" -gt 0 ]; then
    echo "Usage: ./stop_ui.sh [--port 1-65535]"
    exit 2
fi

if [ ! -f "$PID_FILE" ]; then
    if ! command -v lsof >/dev/null 2>&1; then
        echo "Benchmark UI is not running (no PID file at $PID_FILE)."
        echo "Cannot inspect port $PORT because lsof is unavailable."
        exit 0
    fi
    PID=$(lsof -nP -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | head -1)
    if [ -z "$PID" ]; then
        echo "Benchmark UI is not running (no PID file and no listener on port $PORT)."
        exit 0
    fi
    echo "No PID file found; checking listener PID $PID on port $PORT."
else
    PID=$(tr -cd '0-9' < "$PID_FILE")
fi

if [ -z "$PID" ]; then
    echo "Removing invalid UI PID file: $PID_FILE"
    rm -f "$PID_FILE"
    exit 1
fi

if ! kill -0 "$PID" 2>/dev/null; then
    echo "Removing stale UI PID file for PID $PID."
    rm -f "$PID_FILE"
    exit 0
fi

COMMAND=$(ps -p "$PID" -o command= 2>/dev/null || true)
if [[ "$COMMAND" != *"-m ui.server"* ]]; then
    echo "Refusing to stop PID $PID: it is not the benchmark UI server."
    echo "Recorded command: $COMMAND"
    exit 1
fi

# start_ui.sh launches the checkout-local virtual-environment interpreter by
# absolute path. This remains a reliable ownership signal on hardened Linux
# hosts where /proc/<pid>/cwd cannot be read by lsof/readlink.
COMMAND_BELONGS_TO_ROOT=false
if [[ "$COMMAND" == *"$ROOT/.venv/bin/python"* ]]; then
    COMMAND_BELONGS_TO_ROOT=true
fi

# Where supported, also verify the process was launched from this checkout.
if command -v lsof >/dev/null 2>&1; then
    PROCESS_CWD=$(lsof -a -p "$PID" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -1)
    # Some Amazon Linux/lsof combinations return the literal procfs link and
    # an accompanying "readlink: Permission denied" marker instead of a real
    # directory. Treat that as unavailable, not as another checkout.
    if [[ "$PROCESS_CWD" == /proc/* ]] || [[ "$PROCESS_CWD" == *"Permission denied"* ]]; then
        PROCESS_CWD=""
    fi
    if [ -n "$PROCESS_CWD" ] && [ "$PROCESS_CWD" != "$ROOT" ]; then
        echo "Refusing to stop PID $PID: it belongs to another checkout."
        echo "Process directory: $PROCESS_CWD"
        exit 1
    fi
    if [ -z "$PROCESS_CWD" ] && [ "$COMMAND_BELONGS_TO_ROOT" != true ]; then
        echo "Refusing to stop PID $PID: its checkout could not be verified."
        echo "Recorded command: $COMMAND"
        exit 1
    fi
fi

kill -TERM "$PID"
for _attempt in {1..50}; do
    if ! kill -0 "$PID" 2>/dev/null; then
        rm -f "$PID_FILE"
        echo "Benchmark UI stopped (PID $PID)."
        exit 0
    fi
    sleep 0.1
done

echo "Benchmark UI did not stop within 5 seconds; PID $PID is still running."
echo "The PID file was retained: $PID_FILE"
exit 1
