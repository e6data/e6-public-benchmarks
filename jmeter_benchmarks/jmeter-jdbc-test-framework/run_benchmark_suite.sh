#!/bin/bash
# Stable CLI entry point for engine-specific Performance Suites.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$ROOT/utilities/run_benchmark_suite.py" "$@"
