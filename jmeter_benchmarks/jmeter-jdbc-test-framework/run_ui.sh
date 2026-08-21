#!/bin/bash
# Backwards-compatible alias. New documentation uses start_ui.sh.
set -e
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "NOTE: run_ui.sh is retained for compatibility; use ./start_ui.sh."
exec "$ROOT/start_ui.sh" "$@"
