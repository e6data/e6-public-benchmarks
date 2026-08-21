#!/bin/bash
# Stop only the UI process recorded by this checkout's run_ui.sh.
set -e

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="${BENCHMARK_UI_PID_FILE:-$ROOT/logs/ui.pid}"

if [ ! -f "$PID_FILE" ]; then
    echo "Benchmark UI is not running (no PID file at $PID_FILE)."
    exit 0
fi

PID=$(tr -cd '0-9' < "$PID_FILE")
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

# Where supported, also verify the process was launched from this checkout.
if command -v lsof >/dev/null 2>&1; then
    PROCESS_CWD=$(lsof -a -p "$PID" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -1)
    if [ -n "$PROCESS_CWD" ] && [ "$PROCESS_CWD" != "$ROOT" ]; then
        echo "Refusing to stop PID $PID: it belongs to another checkout."
        echo "Process directory: $PROCESS_CWD"
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
