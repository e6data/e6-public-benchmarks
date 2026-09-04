#!/bin/bash
# Stable CLI entry point for engine-specific Performance Suites.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -x "$ROOT/.venv/bin/python" ]; then
    SUITE_PYTHON="$ROOT/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    SUITE_PYTHON="$(command -v python3)"
else
    echo "ERROR: Python 3 was not found. Run ./setup_jmeter.sh first." >&2
    exit 1
fi

exec "$SUITE_PYTHON" "$ROOT/utilities/run_benchmark_suite.py" "$@"
