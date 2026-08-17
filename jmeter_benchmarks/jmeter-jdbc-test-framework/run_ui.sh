#!/bin/bash
# Optional local UI. Existing CLI runners do not depend on this script.
set -e
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
exec python3 -m ui.server "$@"
