#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${ROOT}/.venv/bin/python"
[[ -x "$PYTHON" ]] || PYTHON="${PYTHON_BIN:-python3}"
exec "$PYTHON" "$ROOT/utilities/benchmark_cli.py" "$@"
