#!/bin/bash
# Bounded JDBC smoke suite. This generates real query load.
# Usage: utilities/run_smoke_suite.sh <connection.properties> <queries.csv>
set -uo pipefail

if [ "$#" -ne 2 ]; then
    echo "Usage: $0 <connection.properties> <queries.csv>"
    exit 1
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
CONNECTION_FILE="$1"
QUERY_FILE="$2"
[ -f "$CONNECTION_FILE" ] || { echo "Connection file not found: $CONNECTION_FILE"; exit 1; }
[ -f "$QUERY_FILE" ] || { echo "Query file not found: $QUERY_FILE"; exit 1; }

SUITE_ID=$(python3 -c 'from datetime import datetime; print(datetime.now().strftime("%Y%m%d-%H%M%S-%f"))')
SUITE_REPORT_PATH="${SMOKE_REPORT_PATH:-reports/smoke-${SUITE_ID}}"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
printf '%s\n' 'StartValue,EndValue,Duration' '1,1,8' > "$tmp/arrivals.csv"
printf '%s\n' 'Threads,StartTime,StartupTime,HoldTime,ShutdownTime' '2,0,0,10,0' > "$tmp/concurrency.csv"

failures=0
run_case() {
    name="$1"; plan="$2"; shift 2
    echo "===== smoke: ${name} ====="
    env CONNECTION_FILE="$CONNECTION_FILE" TEST_PLAN="Test-Plans/$plan" \
        QUERY_FILE="$QUERY_FILE" REPORT_PATH="$SUITE_REPORT_PATH" \
        GENERATE_DASHBOARD=false COPY_TO_S3=false MAX_ERROR_PCT="${MAX_ERROR_PCT:-5}" \
        RUN_TYPE="smoke_${name}" "$@" ./run_test.sh || failures=$((failures + 1))
}

run_case run_once Test-Plan-Run-Once-static-concurrency.jmx \
    CONCURRENT_QUERY_COUNT=1 RECYCLE_ON_EOF=false
run_case static_c2 Test-Plan-Maintain-static-concurrency.jmx \
    CONCURRENT_QUERY_COUNT=2 HOLD_PERIOD=10 RECYCLE_ON_EOF=true
run_case qps_1 Test-Plan-Constant-QPS-On-Arrivals-JSR-Optimized.jmx \
    QPS=1 HOLD_PERIOD=8 MAX_CONCURRANCY=10 RECYCLE_ON_EOF=true
run_case arrivals Test-Plan-Fire-QPS-with-load-profile.jmx \
    LOAD_PROFILE="$tmp/arrivals.csv" HOLD_PERIOD=8 MAX_CONCURRANCY=10 RECYCLE_ON_EOF=true
run_case variable_c2 Test-Plan-Maintain-variable-concurrency-with-load-profile.jmx \
    LOAD_PROFILE="$tmp/concurrency.csv" RECYCLE_ON_EOF=true

echo "Smoke reports: ${SUITE_REPORT_PATH}"
if [ "$failures" -ne 0 ]; then
    echo "Smoke suite failed: ${failures}/5 plans failed."
    exit 1
fi
echo "Smoke suite passed: 5/5 plans."
