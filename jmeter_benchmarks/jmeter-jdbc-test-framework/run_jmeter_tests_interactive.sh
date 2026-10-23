#!/bin/bash
# Compatibility entry point: one wizard and one runner for UI/CLI parity.
# TEST_PROPERTIES_FILE may select custom defaults; runtime overrides remain supported.
set -e
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$ROOT/create_test_config.sh" --run
