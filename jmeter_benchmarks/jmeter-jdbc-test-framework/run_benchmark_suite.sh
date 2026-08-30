#!/bin/bash
# Run a manifest-defined collection of Run Once workloads sequentially.
#
# Usage:
#   ./run_benchmark_suite.sh <manifest.json> <connection.properties> [options]
#
# Options:
#   --dry-run              Print the resolved runs without executing JMeter.
#   --continue-on-failure  Continue after a workload fails (default: fail fast).

set -uo pipefail

CURRENT_CHILD=""
abort_suite() {
    if [ -n "$CURRENT_CHILD" ]; then
        kill -TERM "-$CURRENT_CHILD" 2>/dev/null || kill -TERM "$CURRENT_CHILD" 2>/dev/null || true
        wait "$CURRENT_CHILD" 2>/dev/null || true
    fi
    echo
    echo "Suite interrupted; no additional workloads will be started."
    exit 130
}
trap abort_suite INT TERM

usage() {
    echo "Usage: $0 <manifest.json> <connection.properties> [--dry-run] [--continue-on-failure]"
}

if [ "$#" -lt 2 ]; then
    usage
    exit 1
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

MANIFEST="$1"
CONNECTION_FILE="$2"
shift 2
DRY_RUN=false
CONTINUE_ON_FAILURE=false
for option in "$@"; do
    case "$option" in
        --dry-run) DRY_RUN=true ;;
        --continue-on-failure) CONTINUE_ON_FAILURE=true ;;
        *) echo "Unknown option: $option"; usage; exit 1 ;;
    esac
done

[ -f "$MANIFEST" ] || { echo "Manifest not found: $MANIFEST"; exit 1; }
[ -f "$CONNECTION_FILE" ] || { echo "Connection file not found: $CONNECTION_FILE"; exit 1; }

# Fail before starting a long suite when the runner cannot resolve the JDBC
# endpoint. This prevents every workload from becoming an identical network
# failure while still leaving authentication/query checks to JMeter itself.
if ! $DRY_RUN; then
    if ! python3 - "$CONNECTION_FILE" <<'PY'
import re, socket, sys
from pathlib import Path

values = {}
for raw in Path(sys.argv[1]).read_text(errors="replace").splitlines():
    if "=" in raw and not raw.lstrip().startswith("#"):
        key, value = raw.split("=", 1)
        values[key.strip()] = value.strip()
host = values.get("HOSTNAME", "")
if not host:
    match = re.search(r"jdbc:[^:]+://([^:/;]+)", values.get("CONNECTION_STRING", ""))
    host = match.group(1) if match else ""
if not host:
    raise SystemExit("Unable to determine JDBC hostname from connection profile")
try:
    socket.getaddrinfo(host, None)
except OSError as exc:
    raise SystemExit(f"JDBC hostname is not resolvable from this runner: {host} ({exc})")
print(f"Network preflight: resolved {host}")
PY
    then
        echo "Suite not started. Connect to the required network/VPN and retry."
        exit 1
    fi
fi

MANIFEST="$(cd "$(dirname "$MANIFEST")" && pwd)/$(basename "$MANIFEST")"
MANIFEST_ROOT="$(dirname "$MANIFEST")"
SUITE_ID="${SUITE_RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)-$(python3 -c 'import uuid; print(uuid.uuid4().hex[:6])')}"
SUITE_REPORT_PATH="${SUITE_REPORT_PATH:-reports/suite-${SUITE_ID}}"
mkdir -p "$SUITE_REPORT_PATH"
SUMMARY_TSV="$SUITE_REPORT_PATH/suite_summary.tsv"
printf 'sequence\tworkload\tstatus\tqueries\twarmup\titerations\treport\n' > "$SUMMARY_TSV"
python3 - "$MANIFEST" "$SUITE_REPORT_PATH/suite_manifest.json" <<'PY'
import json, sys
from pathlib import Path
source = Path(sys.argv[1])
manifest = json.loads(source.read_text())
if not isinstance(manifest.get("workloads"), list) or not manifest["workloads"]:
    raise SystemExit("Suite manifest must contain a non-empty workloads array")
Path(sys.argv[2]).write_text(json.dumps(manifest, indent=2) + "\n")
PY

entries() {
    python3 - "$MANIFEST" <<'PY'
import json, sys
from pathlib import Path

manifest = json.loads(Path(sys.argv[1]).read_text())
for index, workload in enumerate(manifest.get("workloads", []), 1):
    schemas = workload.get("schemas") or []
    # UI-created manifests use repository-root-relative paths. The original
    # specialized benchmark catalog keeps files beside each workload entry.
    direct = bool(workload.get("query_file"))
    use_plain = schemas == ["tpcds_1000_delta"]
    query = workload.get("query_file") if direct else (workload.get("queries") if use_plain else workload.get("queries_fqn", workload.get("queries")))
    warmup = workload.get("warmup_query_file", "") if direct else (workload.get("warmup") if use_plain else workload.get("warmup_fqn", workload.get("warmup", "")))
    values = [
        index,
        workload.get("id", f"workload-{index}"),
        query or "",
        warmup or "",
        workload.get("measured_iterations", 1),
        workload.get("required_executors", 1),
        workload.get("engine_config", ""),
        ",".join(schemas),
        "root" if direct else "catalog",
    ]
    print("|".join(str(value).replace("|", " ").replace("\n", " ") for value in values))
PY
}

validate_query_file() {
    python3 "$ROOT/utilities/query_file_info.py" "$1" --validate || return 1
    rows=$(python3 "$ROOT/utilities/query_file_info.py" "$1" --field rows) || return 1
    echo "  Preflight:  ${rows} query rows validated"
}

failures=0
completed=0
while IFS='|' read -r sequence workload query warmup iterations executors engine_config schemas path_mode; do
    if [ "$path_mode" = root ]; then
        query_path="$ROOT/$query"
    else
        query_path="$MANIFEST_ROOT/$workload/$query"
    fi
    warmup_path=""
    if [ -n "$warmup" ]; then
        if [ "$path_mode" = root ]; then warmup_path="$ROOT/$warmup"; else warmup_path="$MANIFEST_ROOT/$workload/$warmup"; fi
    fi
    report_path="$SUITE_REPORT_PATH/$(printf '%02d' "$sequence")-$workload"

    echo
    echo "============================================================"
    echo "Suite ${sequence}: ${workload}"
    echo "  Schemas:    ${schemas:-not declared}"
    echo "  Queries:    ${query_path}"
    echo "  Warm-up:    ${warmup_path:-none}"
    echo "  Iterations: ${iterations}"
    echo "  Executors:  ${executors} required by source experiment"
    if [ -n "$engine_config" ]; then
        echo "  WARNING: source experiment used ${engine_config}; this runner does not apply engine configuration."
    fi

    if [ ! -f "$query_path" ]; then
        echo "  FAILED: query file not found"
        printf '%s\t%s\tfailed-preflight\t%s\t%s\t%s\t%s\n' \
            "$sequence" "$workload" "$query_path" "$warmup_path" "$iterations" "$report_path" >> "$SUMMARY_TSV"
        failures=$((failures + 1))
        $CONTINUE_ON_FAILURE || break
        continue
    fi
    if [ -n "$warmup_path" ] && [ ! -f "$warmup_path" ]; then
        echo "  FAILED: warm-up file not found"
        printf '%s\t%s\tfailed-preflight\t%s\t%s\t%s\t%s\n' \
            "$sequence" "$workload" "$query_path" "$warmup_path" "$iterations" "$report_path" >> "$SUMMARY_TSV"
        failures=$((failures + 1))
        $CONTINUE_ON_FAILURE || break
        continue
    fi
    if ! validate_query_file "$query_path"; then
        printf '%s\t%s\tfailed-preflight\t%s\t%s\t%s\t%s\n' \
            "$sequence" "$workload" "$query_path" "$warmup_path" "$iterations" "$report_path" >> "$SUMMARY_TSV"
        failures=$((failures + 1))
        $CONTINUE_ON_FAILURE || break
        continue
    fi
    if [ -n "$warmup_path" ] && ! validate_query_file "$warmup_path"; then
        printf '%s\t%s\tfailed-preflight\t%s\t%s\t%s\t%s\n' \
            "$sequence" "$workload" "$query_path" "$warmup_path" "$iterations" "$report_path" >> "$SUMMARY_TSV"
        failures=$((failures + 1))
        $CONTINUE_ON_FAILURE || break
        continue
    fi

    if $DRY_RUN; then
        printf '%s\t%s\tdry-run\t%s\t%s\t%s\t%s\n' \
            "$sequence" "$workload" "$query_path" "$warmup_path" "$iterations" "$report_path" >> "$SUMMARY_TSV"
        completed=$((completed + 1))
        continue
    fi

    warmup_enabled=false
    [ -n "$warmup_path" ] && warmup_enabled=true
    env \
        CONNECTION_FILE="$CONNECTION_FILE" \
        TEST_PLAN="Test-Plans/Test-Plan-Run-Once-static-concurrency.jmx" \
        TEST_PROPERTIES_FILE="test_properties/run_once.properties" \
        QUERY_FILE="$query_path" \
        WARMUP_ENABLED="$warmup_enabled" \
        WARMUP_QUERY_FILE="$warmup_path" \
        WARMUP_ITERATIONS=1 \
        MEASURED_ITERATIONS="$iterations" \
        CONCURRENT_QUERY_COUNT=1 \
        RAMP_UP_TIME=0 \
        RECYCLE_ON_EOF=false \
        PROMETHEUS_ENABLED=false \
        REPORT_PATH="$report_path" \
        RUN_TYPE="suite_${workload}" \
        SUITE_ID="${SUITE_ID}" \
        SUITE_RUN_ID="${SUITE_ID}" \
        SUITE_SEQUENCE="${sequence}" \
        SUITE_WORKLOAD="${workload}" \
        RUN_SCOPE="${RUN_SCOPE:-internal}" \
        RUN_PURPOSE="${RUN_PURPOSE:-benchmark}" \
        RUN_VALIDITY="${RUN_VALIDITY:-valid}" \
        COPY_TO_S3="${COPY_TO_S3:-false}" \
        ./run_test.sh &
    CURRENT_CHILD=$!
    if wait "$CURRENT_CHILD"; then
        result=completed
        completed=$((completed + 1))
    else
        result=failed
        failures=$((failures + 1))
    fi
    CURRENT_CHILD=""
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
        "$sequence" "$workload" "$result" "$query_path" "$warmup_path" "$iterations" "$report_path" >> "$SUMMARY_TSV"
    if [ "$result" = failed ] && ! $CONTINUE_ON_FAILURE; then
        break
    fi
done < <(entries)

echo
echo "Suite reports: ${SUITE_REPORT_PATH}"
echo "Suite summary: ${SUMMARY_TSV}"
echo "Completed workloads: ${completed}"
echo "Failed workloads: ${failures}"

if [ "$failures" -ne 0 ]; then
    exit 1
fi
