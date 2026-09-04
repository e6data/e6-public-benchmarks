#!/bin/bash
# Non-interactive JMeter test runner — runs from env vars or a suite file
#
# Usage:
#   ./run_test.sh                     # reads from env vars
#   ./run_test.sh test_configs/my.env  # sources config file, then runs
#   QPS=10 ./run_test.sh test_configs/my.env # config file + override specific values
#
# Required (set via env or suite file):
#   CONNECTION_FILE   - path to connection properties file
#   TEST_PLAN         - path to test plan .jmx file
#   QUERY_FILE        - path to query CSV data file
#   TEST_PROPERTIES_FILE - optional local or s3:// JMeter properties file;
#                          inferred from TEST_PLAN when omitted
#
# Optional (with defaults):
#   METADATA_FILE             - metadata file for S3 upload (default: none)
#   CONCURRENT_QUERY_COUNT    - number of concurrent queries (default: 2)
#   QPS                       - queries per second (default: 1)
#   QPM                       - queries per minute (default: 10)
#   HOLD_PERIOD               - test duration in seconds (default: 300)
#   RAMP_UP_TIME              - ramp up time in seconds; 0 starts immediately (default: 0)
#   RAMP_UP_STEPS             - ramp up steps (default: 1)
#   LOAD_PROFILE              - load profile CSV path (default: test_properties/load_profile.csv)
#   RANDOM_ORDER              - random query order true/false (default: false)
#   RECYCLE_ON_EOF            - repeat queries true/false (default: false)
#   COPY_TO_S3                - upload results to S3 true/false (default: false)
#   S3_REPORT_PATH            - S3 path for results (default: s3://your-s3-bucket/jmeter-results)
#   REPORT_PATH               - local report directory (default: reports)
#   QUERY_TIMEOUT             - query timeout in seconds (default: 300)
#   LIMIT_RESULTSET           - max result rows (default: 1000)
#   MAX_CONCURRANCY           - max threads (default: 900)
#   JMETER_HOME               - JMeter installation path (auto-detected if not set)
#   MAX_ERROR_PCT             - fail the run above this error rate (default: 5)
#   RUN_TYPE                  - S3 partition label (inferred from the plan if omitted)
#   PROMETHEUS_ENABLED        - expose live JMeter metrics for Prometheus (default: false)
#   JMETER_RESULT_AUTOFLUSH   - flush each result row for live readers (default: false)
#   PROMETHEUS_IP             - metrics listener bind address (default: 127.0.0.1)
#   PROMETHEUS_PORT           - metrics listener port (default: 9270)
#   PROMETHEUS_DELAY          - seconds to keep endpoint after the test (default: 15)
#   PROMETHEUS_URL            - informational Prometheus UI URL (default: empty)
#   GRAFANA_URL               - informational dashboard URL (default: empty)
#   WARMUP_ENABLED            - run an excluded sequential warm-up first (default: false)
#   WARMUP_QUERY_FILE         - warm-up query CSV; local path or s3:// URI
#   WARMUP_ITERATIONS         - number of separate warm-up passes (default: 1)
#   MEASURED_ITERATIONS       - query-file passes included in a Run Once result (default: 1)
#   E6_QUERY_HISTORY_ENABLED  - capture e6 Query History after the run (default: false)
#   E6_MACHINE_CLIENT_ID      - OAuth2 machine-client ID (deployment secret env)
#   E6_MACHINE_CLIENT_SECRET  - OAuth2 machine-client secret (deployment secret env)
#   E6_QUERY_HISTORY_EMAIL    - optional Query History user/email filter
#   E6_QUERY_HISTORY_WAIT_SECONDS - wait for history ingestion (default: 5)
#
# Exit codes:
#   0  the run completed and the error rate was within MAX_ERROR_PCT
#   1  the run is not a usable result - no samples recorded, or too many errors.
#      The results directory is still written so the failure can be diagnosed.
#      Set MAX_ERROR_PCT=100 to accept any error rate.
#
# Examples:
#
#   # Simple concurrency test
#   export CONNECTION_FILE=connection_properties/e6data_default_connection.properties
#   export TEST_PLAN=Test-Plans/Test-Plan-Maintain-static-concurrency.jmx
#   export QUERY_FILE=data_files/E6Data_TPCDS_queries_29_1TB.csv
#   export CONCURRENT_QUERY_COUNT=4
#   ./run_test.sh
#
#   # Change just QPS and re-run
#   export QPS=10
#   export TEST_PLAN=Test-Plans/Test-Plan-Constant-QPS-On-Arrivals-JSR-Optimized.jmx
#   ./run_test.sh
#
#   # Using a suite file
#   ./run_test.sh test_configs/e6data_qps_test.env

set -e

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

# Navigate to project root
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

S3_INPUT_DIR=""
cleanup_s3_inputs() {
    if [ -n "$S3_INPUT_DIR" ] && [ -d "$S3_INPUT_DIR" ]; then
        rm -rf -- "$S3_INPUT_DIR"
    fi
}
trap cleanup_s3_inputs EXIT

materialize_s3_input() {
    local variable="$1" kind="$2" uri="${!1:-}" filename destination
    case "$uri" in
        s3://*) ;;
        *) return 0 ;;
    esac
    if ! command -v aws >/dev/null 2>&1; then
        echo -e "${RED}Error: AWS CLI is required for ${variable}=${uri}${NC}"
        exit 1
    fi
    if [ -z "$S3_INPUT_DIR" ]; then
        umask 077
        S3_INPUT_DIR=$(mktemp -d "${TMPDIR:-/tmp}/e6-jmeter-s3-inputs.XXXXXX")
    fi
    filename="${uri%%\?*}"
    filename="$(basename "$filename")"
    filename="$(printf '%s' "$filename" | tr -cs 'A-Za-z0-9._-' '_')"
    [ -n "$filename" ] || filename="input.csv"
    destination="$S3_INPUT_DIR/${kind}-${filename}"
    echo "Downloading ${variable} from ${uri}"
    if ! aws s3 cp "$uri" "$destination" --only-show-errors; then
        echo -e "${RED}Error: failed to download ${variable} from ${uri}${NC}"
        exit 1
    fi
    if [ ! -s "$destination" ]; then
        echo -e "${RED}Error: downloaded ${variable} is empty: ${uri}${NC}"
        exit 1
    fi
    printf -v "${variable}_SOURCE" '%s' "$uri"
    printf -v "$variable" '%s' "$destination"
}

# ============================================================================
# Source suite file if provided (env vars override suite file values)
# ============================================================================

if [ -n "$1" ]; then
    SUITE_FILE="$1"
    if [ ! -f "$SUITE_FILE" ]; then
        echo -e "${RED}Error: Suite file not found: ${SUITE_FILE}${NC}"
        exit 1
    fi
    echo -e "${BLUE}Loading suite file: ${SUITE_FILE}${NC}"

    # Save any pre-set env vars so they take priority over config file
    _SAVE_CONNECTION_FILE="${CONNECTION_FILE:-}"
    _SAVE_TEST_PLAN="${TEST_PLAN:-}"
    _SAVE_TEST_PROPERTIES_FILE="${TEST_PROPERTIES_FILE:-}"
    _SAVE_QUERY_FILE="${QUERY_FILE:-}"
    _SAVE_METADATA_FILE="${METADATA_FILE:-}"
    _SAVE_CONCURRENT_QUERY_COUNT="${CONCURRENT_QUERY_COUNT:-}"
    _SAVE_QPS="${QPS:-}"
    _SAVE_QPM="${QPM:-}"
    _SAVE_HOLD_PERIOD="${HOLD_PERIOD:-}"
    _SAVE_RAMP_UP_TIME="${RAMP_UP_TIME:-}"
    _SAVE_RAMP_UP_STEPS="${RAMP_UP_STEPS:-}"
    _SAVE_LOAD_PROFILE="${LOAD_PROFILE:-}"
    _SAVE_RANDOM_ORDER="${RANDOM_ORDER:-}"
    _SAVE_RECYCLE_ON_EOF="${RECYCLE_ON_EOF:-}"
    _SAVE_COPY_TO_S3="${COPY_TO_S3:-}"
    _SAVE_S3_REPORT_PATH="${S3_REPORT_PATH:-}"
    _SAVE_REPORT_PATH="${REPORT_PATH:-}"
    _SAVE_QUERY_TIMEOUT="${QUERY_TIMEOUT:-}"
    _SAVE_LIMIT_RESULTSET="${LIMIT_RESULTSET:-}"
    _SAVE_MAX_CONCURRANCY="${MAX_CONCURRANCY:-}"
    _SAVE_JMETER_HOME="${JMETER_HOME:-}"
    _SAVE_MAX_ERROR_PCT="${MAX_ERROR_PCT:-}"
    _SAVE_GENERATE_DASHBOARD="${GENERATE_DASHBOARD:-}"
    _SAVE_RUN_TYPE="${RUN_TYPE:-}"
    _SAVE_PROMETHEUS_ENABLED="${PROMETHEUS_ENABLED:-}"
    _SAVE_PROMETHEUS_IP="${PROMETHEUS_IP:-}"
    _SAVE_PROMETHEUS_PORT="${PROMETHEUS_PORT:-}"
    _SAVE_PROMETHEUS_DELAY="${PROMETHEUS_DELAY:-}"
    _SAVE_PROMETHEUS_URL="${PROMETHEUS_URL:-}"
    _SAVE_GRAFANA_URL="${GRAFANA_URL:-}"
    _SAVE_WARMUP_ENABLED="${WARMUP_ENABLED:-}"
    _SAVE_WARMUP_QUERY_FILE="${WARMUP_QUERY_FILE:-}"
    _SAVE_WARMUP_ITERATIONS="${WARMUP_ITERATIONS:-}"
    _SAVE_MEASURED_ITERATIONS="${MEASURED_ITERATIONS:-}"

    source "$SUITE_FILE"

    # Restore env vars that were set before sourcing (env overrides config)
    [ -n "$_SAVE_CONNECTION_FILE" ] && CONNECTION_FILE="$_SAVE_CONNECTION_FILE"
    [ -n "$_SAVE_TEST_PLAN" ] && TEST_PLAN="$_SAVE_TEST_PLAN"
    [ -n "$_SAVE_TEST_PROPERTIES_FILE" ] && TEST_PROPERTIES_FILE="$_SAVE_TEST_PROPERTIES_FILE"
    [ -n "$_SAVE_QUERY_FILE" ] && QUERY_FILE="$_SAVE_QUERY_FILE"
    [ -n "$_SAVE_METADATA_FILE" ] && METADATA_FILE="$_SAVE_METADATA_FILE"
    [ -n "$_SAVE_CONCURRENT_QUERY_COUNT" ] && CONCURRENT_QUERY_COUNT="$_SAVE_CONCURRENT_QUERY_COUNT"
    [ -n "$_SAVE_QPS" ] && QPS="$_SAVE_QPS"
    [ -n "$_SAVE_QPM" ] && QPM="$_SAVE_QPM"
    [ -n "$_SAVE_HOLD_PERIOD" ] && HOLD_PERIOD="$_SAVE_HOLD_PERIOD"
    [ -n "$_SAVE_RAMP_UP_TIME" ] && RAMP_UP_TIME="$_SAVE_RAMP_UP_TIME"
    [ -n "$_SAVE_RAMP_UP_STEPS" ] && RAMP_UP_STEPS="$_SAVE_RAMP_UP_STEPS"
    [ -n "$_SAVE_LOAD_PROFILE" ] && LOAD_PROFILE="$_SAVE_LOAD_PROFILE"
    [ -n "$_SAVE_RANDOM_ORDER" ] && RANDOM_ORDER="$_SAVE_RANDOM_ORDER"
    [ -n "$_SAVE_RECYCLE_ON_EOF" ] && RECYCLE_ON_EOF="$_SAVE_RECYCLE_ON_EOF"
    [ -n "$_SAVE_COPY_TO_S3" ] && COPY_TO_S3="$_SAVE_COPY_TO_S3"
    [ -n "$_SAVE_S3_REPORT_PATH" ] && S3_REPORT_PATH="$_SAVE_S3_REPORT_PATH"
    [ -n "$_SAVE_REPORT_PATH" ] && REPORT_PATH="$_SAVE_REPORT_PATH"
    [ -n "$_SAVE_QUERY_TIMEOUT" ] && QUERY_TIMEOUT="$_SAVE_QUERY_TIMEOUT"
    [ -n "$_SAVE_LIMIT_RESULTSET" ] && LIMIT_RESULTSET="$_SAVE_LIMIT_RESULTSET"
    [ -n "$_SAVE_MAX_CONCURRANCY" ] && MAX_CONCURRANCY="$_SAVE_MAX_CONCURRANCY"
    [ -n "$_SAVE_JMETER_HOME" ] && JMETER_HOME="$_SAVE_JMETER_HOME"
    [ -n "$_SAVE_MAX_ERROR_PCT" ] && MAX_ERROR_PCT="$_SAVE_MAX_ERROR_PCT"
    [ -n "$_SAVE_GENERATE_DASHBOARD" ] && GENERATE_DASHBOARD="$_SAVE_GENERATE_DASHBOARD"
    [ -n "$_SAVE_RUN_TYPE" ] && RUN_TYPE="$_SAVE_RUN_TYPE"
    [ -n "$_SAVE_PROMETHEUS_ENABLED" ] && PROMETHEUS_ENABLED="$_SAVE_PROMETHEUS_ENABLED"
    [ -n "$_SAVE_PROMETHEUS_IP" ] && PROMETHEUS_IP="$_SAVE_PROMETHEUS_IP"
    [ -n "$_SAVE_PROMETHEUS_PORT" ] && PROMETHEUS_PORT="$_SAVE_PROMETHEUS_PORT"
    [ -n "$_SAVE_PROMETHEUS_DELAY" ] && PROMETHEUS_DELAY="$_SAVE_PROMETHEUS_DELAY"
    [ -n "$_SAVE_PROMETHEUS_URL" ] && PROMETHEUS_URL="$_SAVE_PROMETHEUS_URL"
    [ -n "$_SAVE_GRAFANA_URL" ] && GRAFANA_URL="$_SAVE_GRAFANA_URL"
    [ -n "$_SAVE_WARMUP_ENABLED" ] && WARMUP_ENABLED="$_SAVE_WARMUP_ENABLED"
    [ -n "$_SAVE_WARMUP_QUERY_FILE" ] && WARMUP_QUERY_FILE="$_SAVE_WARMUP_QUERY_FILE"
    [ -n "$_SAVE_WARMUP_ITERATIONS" ] && WARMUP_ITERATIONS="$_SAVE_WARMUP_ITERATIONS"
    [ -n "$_SAVE_MEASURED_ITERATIONS" ] && MEASURED_ITERATIONS="$_SAVE_MEASURED_ITERATIONS"
fi

# Load shared deployment defaults after the optional suite. This file is
# shared by CLI and Benchmark Studio; the UI is only an editor for the same
# runner contract. It is gitignored and may contain the optional Query History
# machine secret. Explicit environment variables and suite values always win.
SYSTEM_SETTINGS_FILE="${BENCHMARK_SYSTEM_SETTINGS_FILE:-${BENCHMARK_UI_SETTINGS_FILE:-$PROJECT_ROOT/config/system_settings.json}}"
if [ -f "$SYSTEM_SETTINGS_FILE" ]; then
    if ! command -v jq >/dev/null 2>&1; then
        echo -e "${YELLOW}Warning: jq is unavailable; ignoring ${SYSTEM_SETTINGS_FILE}.${NC}"
    else
        _system_default() {
            local shell_name="$1" json_name="$2" value
            [ -n "${!shell_name:-}" ] && return 0
            value="$(jq -r --arg key "$json_name" 'if has($key) then .[$key] | if type == "boolean" then tostring else . end else empty end' "$SYSTEM_SETTINGS_FILE")"
            [ -n "$value" ] && printf -v "$shell_name" '%s' "$value"
            return 0
        }
        _system_default COPY_TO_S3 copy_to_s3
        _system_default S3_REPORT_PATH s3_report_path
        _system_default GENERATE_DASHBOARD generate_dashboard
        _system_default PROMETHEUS_ENABLED prometheus_enabled
        _system_default PROMETHEUS_PORT prometheus_port
        _system_default PROMETHEUS_URL prometheus_url
        _system_default GRAFANA_URL grafana_url
        _system_default E6_QUERY_HISTORY_ENABLED e6_query_history_enabled
        _system_default E6_MACHINE_CLIENT_ID e6_machine_client_id
        _system_default E6_MACHINE_CLIENT_SECRET e6_machine_client_secret
        _system_default E6_QUERY_HISTORY_EMAIL e6_query_history_email
        _system_default E6_QUERY_HISTORY_WAIT_SECONDS e6_query_history_wait_seconds
        unset -f _system_default
    fi
fi

# ============================================================================
# Validate required variables
# ============================================================================

MISSING=()
[ -z "${CONNECTION_FILE:-}" ] && MISSING+=("CONNECTION_FILE")
[ -z "${TEST_PLAN:-}" ] && MISSING+=("TEST_PLAN")
[ -z "${QUERY_FILE:-}" ] && MISSING+=("QUERY_FILE")

if [ ${#MISSING[@]} -gt 0 ]; then
    echo -e "${RED}Error: Missing required variables: ${MISSING[*]}${NC}"
    echo ""
    echo "Usage:"
    echo ""
    echo "  Option 1 — Config file (recommended):"
    echo "    ./run_test.sh test_configs/my_test.env"
    echo ""
    echo "  Option 2 — Export environment variables, then run:"
    echo "    export CONNECTION_FILE=connection_properties/e6data_default_connection.properties"
    echo "    export TEST_PLAN=Test-Plans/Test-Plan-Maintain-static-concurrency.jmx"
    echo "    export QUERY_FILE=data_files/E6Data_TPCDS_queries_29_1TB.csv"
    echo "    ./run_test.sh"
    echo ""
    echo "  Option 3 — Inline (single command):"
    echo "    CONNECTION_FILE=... TEST_PLAN=... QUERY_FILE=... ./run_test.sh"
    echo ""
    echo "To re-run with different parameters, override individual values:"
    echo "    CONCURRENT_QUERY_COUNT=8 ./run_test.sh test_configs/my_test.env"
    echo "    QPS=10 HOLD_PERIOD=600 ./run_test.sh test_configs/my_test.env"
    echo ""
    echo "Create a config interactively:  ./create_test_config.sh"
    echo "See sample config files in test_configs/ for reference."
    exit 1
fi

# JMeter requires filesystem paths. Resolve a fresh copy for every CLI run so
# an updated S3 object is never hidden behind a stale local cache.
materialize_s3_input QUERY_FILE query

# Every supported plan has one canonical JMeter properties file. A caller may
# select another local/S3 file; already-resolved suite or environment values
# remain higher precedence and are emitted as explicit -J overrides below.
if [ -z "${TEST_PROPERTIES_FILE:-}" ]; then
    case "$(basename "$TEST_PLAN")" in
        *Run-Once*) TEST_PROPERTIES_FILE="test_properties/run_once.properties" ;;
        *Maintain-static-concurrency*) TEST_PROPERTIES_FILE="test_properties/fixed_concurrency.properties" ;;
        *Constant-QPS*) TEST_PROPERTIES_FILE="test_properties/constant_qps.properties" ;;
        *Constant-QPM*) TEST_PROPERTIES_FILE="test_properties/constant_qpm.properties" ;;
        *Fire-QPS-with-load-profile*) TEST_PROPERTIES_FILE="test_properties/variable_arrivals.properties" ;;
        *Maintain-variable-concurrency*) TEST_PROPERTIES_FILE="test_properties/variable_concurrency.properties" ;;
        *) TEST_PROPERTIES_FILE="test_properties/default.properties" ;;
    esac
fi
materialize_s3_input TEST_PROPERTIES_FILE test-properties

# Read only runner-supported keys from the properties file, without sourcing
# it as shell code. Arbitrary JMeter/plugin keys are still loaded by JMeter via
# the second -q argument. Existing env/suite values win.
TEST_PROPERTY_KEYS="CONCURRENT_QUERY_COUNT QPS QPM HOLD_PERIOD RAMP_UP_TIME RAMP_UP_STEPS LOAD_PROFILE RANDOM_ORDER RECYCLE_ON_EOF QUERY_TIMEOUT LIMIT_RESULTSET MAX_CONCURRANCY MAX_ERROR_PCT MEASURED_ITERATIONS GENERATE_DASHBOARD"
if [ -f "$TEST_PROPERTIES_FILE" ]; then
    while IFS='=' read -r raw_key raw_value; do
        key="$(printf '%s' "$raw_key" | xargs)"
        case " $TEST_PROPERTY_KEYS " in *" $key "*) ;; *) continue ;; esac
        value="${raw_value%%[[:space:]]#*}"
        value="$(printf '%s' "$value" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
        [ -n "${!key:-}" ] || printf -v "$key" '%s' "$value"
    done < "$TEST_PROPERTIES_FILE"
fi

# Validate files exist
for var in CONNECTION_FILE TEST_PLAN TEST_PROPERTIES_FILE QUERY_FILE; do
    val="${!var}"
    if [ ! -f "$val" ]; then
        echo -e "${RED}Error: ${var} file not found: ${val}${NC}"
        exit 1
    fi
done

# Use the same strict query-file validation as the UI before creating a run or
# starting JMeter. This prevents unresolved ${QUERY} samples from malformed,
# blank, or duplicate CSV records.
if ! python3 "${PROJECT_ROOT}/utilities/query_file_info.py" "$QUERY_FILE" --validate; then
    echo -e "${RED}Error: QUERY_FILE preflight validation failed.${NC}"
    exit 1
fi

ORIGINAL_TEST_PLAN="$TEST_PLAN"

if [ -n "${METADATA_FILE:-}" ] && [ ! -f "$METADATA_FILE" ]; then
    echo -e "${RED}Error: METADATA_FILE not found: ${METADATA_FILE}${NC}"
    exit 1
fi

# ============================================================================
# Apply defaults for optional variables
# ============================================================================

CONCURRENT_QUERY_COUNT="${CONCURRENT_QUERY_COUNT:-2}"
QPS="${QPS:-1}"
QPM="${QPM:-10}"
HOLD_PERIOD="${HOLD_PERIOD:-300}"
RAMP_UP_TIME="${RAMP_UP_TIME:-0}"
RAMP_UP_STEPS="${RAMP_UP_STEPS:-1}"
# The two load-profile plan families take different CSV formats, so the default
# follows the plan: 5-column concurrency waves for UltimateThreadGroup,
# 3-column arrival-rate steps for FreeFormArrivalsThreadGroup.
if grep -q "UltimateThreadGroup" "$TEST_PLAN" 2>/dev/null; then
    LOAD_PROFILE="${LOAD_PROFILE:-test_properties/utg_load_profile.csv}"
else
    LOAD_PROFILE="${LOAD_PROFILE:-test_properties/load_profile.csv}"
fi
RANDOM_ORDER="${RANDOM_ORDER:-false}"
RECYCLE_ON_EOF="${RECYCLE_ON_EOF:-false}"
COPY_TO_S3="${COPY_TO_S3:-false}"
S3_REPORT_PATH="${S3_REPORT_PATH:-s3://your-s3-bucket/benchmark-results/v1}"
REPORT_PATH="${REPORT_PATH:-reports}"
QUERY_TIMEOUT="${QUERY_TIMEOUT:-300}"
LIMIT_RESULTSET="${LIMIT_RESULTSET:-1000}"
MAX_CONCURRANCY="${MAX_CONCURRANCY:-900}"
JMETER_RESULT_AUTOFLUSH="${JMETER_RESULT_AUTOFLUSH:-false}"
PROMETHEUS_ENABLED="${PROMETHEUS_ENABLED:-false}"
PROMETHEUS_IP="${PROMETHEUS_IP:-127.0.0.1}"
PROMETHEUS_PORT="${PROMETHEUS_PORT:-9270}"
PROMETHEUS_DELAY="${PROMETHEUS_DELAY:-15}"
E6_QUERY_HISTORY_ENABLED="${E6_QUERY_HISTORY_ENABLED:-false}"
E6_QUERY_HISTORY_WAIT_SECONDS="${E6_QUERY_HISTORY_WAIT_SECONDS:-5}"
WARMUP_ENABLED="${WARMUP_ENABLED:-false}"
WARMUP_ITERATIONS="${WARMUP_ITERATIONS:-1}"
MEASURED_ITERATIONS="${MEASURED_ITERATIONS:-1}"

if [ "$WARMUP_ENABLED" != "true" ] && [ "$WARMUP_ENABLED" != "false" ]; then
    echo -e "${RED}Error: WARMUP_ENABLED must be true or false.${NC}"
    exit 1
fi
if ! [[ "$WARMUP_ITERATIONS" =~ ^[1-9][0-9]*$ ]]; then
    echo -e "${RED}Error: WARMUP_ITERATIONS must be a positive integer.${NC}"
    exit 1
fi
if ! [[ "$MEASURED_ITERATIONS" =~ ^[1-9][0-9]*$ ]]; then
    echo -e "${RED}Error: MEASURED_ITERATIONS must be a positive integer.${NC}"
    exit 1
fi
if [ "$MEASURED_ITERATIONS" -gt 1 ] && ! basename "$TEST_PLAN" | grep -qi "run-once"; then
    echo -e "${RED}Error: MEASURED_ITERATIONS greater than 1 is supported only by Run Once plans.${NC}"
    exit 1
fi
if [ "$WARMUP_ENABLED" = "true" ] && [ -z "${WARMUP_QUERY_FILE:-}" ]; then
    echo -e "${RED}Error: WARMUP_QUERY_FILE is required when WARMUP_ENABLED=true.${NC}"
    exit 1
fi

materialize_s3_input LOAD_PROFILE profile

if [ "$PROMETHEUS_ENABLED" != "true" ] && [ "$PROMETHEUS_ENABLED" != "false" ]; then
    echo -e "${RED}Error: PROMETHEUS_ENABLED must be true or false.${NC}"
    exit 1
fi
if ! [[ "$PROMETHEUS_PORT" =~ ^[0-9]+$ ]] || [ "$PROMETHEUS_PORT" -lt 1 ] || [ "$PROMETHEUS_PORT" -gt 65535 ]; then
    echo -e "${RED}Error: PROMETHEUS_PORT must be between 1 and 65535.${NC}"
    exit 1
fi
if ! [[ "$PROMETHEUS_DELAY" =~ ^[0-9]+$ ]]; then
    echo -e "${RED}Error: PROMETHEUS_DELAY must be a non-negative integer.${NC}"
    exit 1
fi
if [ "$E6_QUERY_HISTORY_ENABLED" != "true" ] && [ "$E6_QUERY_HISTORY_ENABLED" != "false" ]; then
    echo -e "${RED}Error: E6_QUERY_HISTORY_ENABLED must be true or false.${NC}"
    exit 1
fi
if ! [[ "$E6_QUERY_HISTORY_WAIT_SECONDS" =~ ^[0-9]+$ ]]; then
    echo -e "${RED}Error: E6_QUERY_HISTORY_WAIT_SECONDS must be a non-negative integer.${NC}"
    exit 1
fi

# Source metadata if present (may override COPY_TO_S3, ENGINE, etc.)
if [ -n "${METADATA_FILE:-}" ]; then
    source "$METADATA_FILE"
fi

# S3_REPORT_PATH is the public runner setting. Older metadata files use
# S3_BASE_PATH; keep that as a backwards-compatible alias while ensuring the
# documented setting is sufficient on its own.
if [ -n "${S3_BASE_PATH:-}" ] && [ -n "${S3_REPORT_PATH:-}" ] \
   && [ "$S3_BASE_PATH" != "$S3_REPORT_PATH" ]; then
    echo -e "${YELLOW}Warning: S3_BASE_PATH overrides S3_REPORT_PATH; migrate metadata to S3_REPORT_PATH.${NC}"
fi
S3_UPLOAD_ROOT="${S3_BASE_PATH:-$S3_REPORT_PATH}"

# ============================================================================
# Find JMeter
# ============================================================================

if [ -z "${JMETER_HOME:-}" ]; then
    if command -v jmeter &>/dev/null; then
        JMETER_BIN=$(which jmeter)
        JMETER_HOME=$(dirname "$(dirname "$JMETER_BIN")")
    elif [ -d "/opt/homebrew/Cellar/jmeter" ]; then
        JMETER_HOME=$(ls -d /opt/homebrew/Cellar/jmeter/*/libexec 2>/dev/null | head -1)
    elif [ -d "/usr/local/Cellar/jmeter" ]; then
        JMETER_HOME=$(ls -d /usr/local/Cellar/jmeter/*/libexec 2>/dev/null | head -1)
    elif [ -d "apache-jmeter-5.6.3" ]; then
        JMETER_HOME="$(pwd)/apache-jmeter-5.6.3"
    fi
fi

if [ -z "${JMETER_HOME:-}" ] || [ ! -f "$JMETER_HOME/bin/jmeter" ]; then
    echo -e "${RED}Error: Cannot find JMeter. Set JMETER_HOME or install JMeter.${NC}"
    exit 1
fi

# Run warm-up in one or more separate JMeter processes. Each pass uses the
# run-once plan at concurrency 1 and writes below REPORT_PATH/_warmup/. The
# measured invocation therefore never sees warm-up samples in its result CSV,
# dashboard, summary, percentiles, throughput, or comparison registry entry.
if [ "$WARMUP_ENABLED" = "true" ]; then
    echo ""
    echo -e "${BLUE}=========================================="
    echo " Benchmark warm-up (excluded)"
    echo -e "==========================================${NC}"
    echo "  Queries:    ${WARMUP_QUERY_FILE}"
    echo "  Iterations: ${WARMUP_ITERATIONS}"
    echo "  Results:    ${REPORT_PATH}/_warmup/"
    echo ""
    _warmup_iteration=1
    while [ "$_warmup_iteration" -le "$WARMUP_ITERATIONS" ]; do
        echo -e "${BLUE}Warm-up pass ${_warmup_iteration}/${WARMUP_ITERATIONS}${NC}"
        if ! env \
            WARMUP_ENABLED=false \
            MEASURED_ITERATIONS=1 \
            QUERY_FILE="$WARMUP_QUERY_FILE" \
            TEST_PLAN="${PROJECT_ROOT}/Test-Plans/Test-Plan-Run-Once-static-concurrency.jmx" \
            TEST_PROPERTIES_FILE="${PROJECT_ROOT}/test_properties/run_once.properties" \
            CONCURRENT_QUERY_COUNT=1 \
            RANDOM_ORDER=false \
            RECYCLE_ON_EOF=false \
            REPORT_PATH="${REPORT_PATH}/_warmup" \
            RUN_ID="${RUN_ID:-warmup}-warmup-${_warmup_iteration}" \
            RUN_TYPE=warmup \
            RUN_PURPOSE=warmup \
            RUN_VALIDITY=invalid \
            COPY_TO_S3=false \
            GENERATE_DASHBOARD=false \
            PROMETHEUS_ENABLED=false \
            MAX_ERROR_PCT=0 \
            "${PROJECT_ROOT}/run_test.sh"; then
            echo -e "${RED}Error: warm-up pass ${_warmup_iteration} failed; measured run was not started.${NC}"
            exit 1
        fi
        _warmup_iteration=$((_warmup_iteration + 1))
    done
    echo -e "${GREEN}Warm-up complete; starting measured run with a fresh JMeter process.${NC}"
fi

# ============================================================================
# Display configuration
# ============================================================================

TIMESTAMP=$(python3 -c 'from datetime import datetime; print(datetime.now().strftime("%Y%m%d-%H%M%S-%f"))')
RUN_ID="${RUN_ID:-$(python3 -c 'import uuid; print(uuid.uuid4().hex[:12])')}"
RUN_DATE="${TIMESTAMP:0:4}-${TIMESTAMP:4:2}-${TIMESTAMP:6:2}"
REPORT_DIR="${REPORT_PATH}/${TIMESTAMP}"
mkdir -p "$REPORT_PATH"
if ! mkdir "$REPORT_DIR"; then
    echo -e "${RED}Error: report directory already exists: ${REPORT_DIR}${NC}"
    exit 1
fi

# Run Once consumes a shared CSV until EOF. Repeating its validated data rows
# creates exact measured passes without modifying the JMX or enabling endless
# CSV recycling. Preserving aliases lets JMeter aggregate the N observations of
# each query into its standard per-label count/average/median/percentiles.
ORIGINAL_QUERY_FILE="$QUERY_FILE"

# Preserve the exact non-secret workload inputs beside the measured results.
# REPORT_DIR is uploaded recursively, so these immutable copies make a run
# reproducible and let users download its query/load CSVs from S3 later. Never
# copy CONNECTION_FILE or TEST_PROPERTIES_FILE because they may contain secrets.
mkdir -p "${REPORT_DIR}/inputs"
cp "$ORIGINAL_QUERY_FILE" "${REPORT_DIR}/inputs/query.csv"
if [ -n "${LOAD_PROFILE:-}" ] && [ -f "$LOAD_PROFILE" ] \
   && grep -qE "FreeFormArrivalsThreadGroup|UltimateThreadGroup" "$TEST_PLAN" 2>/dev/null; then
    cp "$LOAD_PROFILE" "${REPORT_DIR}/inputs/load-profile.csv"
fi
if [ "$WARMUP_ENABLED" = "true" ] && [ -n "${WARMUP_QUERY_FILE:-}" ] \
   && [ -f "$WARMUP_QUERY_FILE" ]; then
    cp "$WARMUP_QUERY_FILE" "${REPORT_DIR}/inputs/warmup-query.csv"
fi

if [ "$MEASURED_ITERATIONS" -gt 1 ]; then
    REPEATED_QUERY_FILE="${REPORT_DIR}/measured-queries-${MEASURED_ITERATIONS}x.csv"
    python3 "${PROJECT_ROOT}/utilities/repeat_query_file.py" \
        "$ORIGINAL_QUERY_FILE" "$REPEATED_QUERY_FILE" "$MEASURED_ITERATIONS" >/dev/null
    QUERY_FILE="$REPEATED_QUERY_FILE"
fi

# Count logical query rows, excluding a recognized CSV header.
QUERY_COUNT=$(python3 "${PROJECT_ROOT}/utilities/query_file_info.py" "$QUERY_FILE" --field rows)
UNIQUE_QUERY_COUNT=$(python3 "${PROJECT_ROOT}/utilities/query_file_info.py" "$ORIGINAL_QUERY_FILE" --field rows)

# Infer test type from test plan filename for display
PLAN_BASENAME=$(basename "$TEST_PLAN" .jmx | tr '[:upper:]' '[:lower:]')
if echo "$PLAN_BASENAME" | grep -q "run-once"; then
    TEST_TYPE="Run Once"
elif echo "$PLAN_BASENAME" | grep -q "variable-concurrency\|load-profile.*concurrency"; then
    TEST_TYPE="Variable Concurrency (load profile)"
elif echo "$PLAN_BASENAME" | grep -q "qps.*load-profile\|loadprofile.*qps\|qps-loadprofile\|loadprofile"; then
    TEST_TYPE="QPS with Load Profile"
elif echo "$PLAN_BASENAME" | grep -q "qpm.*load-profile"; then
    TEST_TYPE="QPM with Load Profile"
elif echo "$PLAN_BASENAME" | grep -q "qps"; then
    TEST_TYPE="Constant QPS"
elif echo "$PLAN_BASENAME" | grep -q "qpm"; then
    TEST_TYPE="Constant QPM"
else
    TEST_TYPE="Static Concurrency"
fi

# Keep uploads compatible with the partition layout consumed by the S3 and
# Athena utilities. Callers can set RUN_TYPE explicitly for custom plans.
if [ -z "${RUN_TYPE:-}" ]; then
    case "$TEST_TYPE" in
        "Run Once")
            if [ "$CONCURRENT_QUERY_COUNT" = "1" ]; then
                RUN_TYPE="sequential"
            else
                RUN_TYPE="concurrency_${CONCURRENT_QUERY_COUNT}"
            fi
            ;;
        "Static Concurrency") RUN_TYPE="concurrency_${CONCURRENT_QUERY_COUNT}" ;;
        "Constant QPS") RUN_TYPE="qps_${QPS}" ;;
        "Constant QPM") RUN_TYPE="qpm_${QPM}" ;;
        "Variable Concurrency (load profile)") RUN_TYPE="variable_concurrency" ;;
        "QPS with Load Profile") RUN_TYPE="qps_load_profile" ;;
        *) RUN_TYPE="custom" ;;
    esac
fi
# Partition values must remain a single safe path component.
RUN_TYPE=$(printf '%s' "$RUN_TYPE" | tr -cs 'A-Za-z0-9._-' '_')

# Extract connection details for display
CONN_HOST=$(grep -E "^HOSTNAME=|^mainhost=" "$CONNECTION_FILE" 2>/dev/null | head -1 | cut -d= -f2)
CONN_ENGINE=$(grep -E "^# Engine:" "$CONNECTION_FILE" 2>/dev/null | cut -d: -f2 | tr -d ' ')

echo ""
echo -e "${BLUE}=========================================="
echo " JMeter Test Runner"
echo -e "==========================================${NC}"
echo ""
echo -e "  ${BOLD}Connection${NC}"
echo "    File:       $(basename "$CONNECTION_FILE")"
[ -n "$CONN_HOST" ] && echo "    Host:       ${CONN_HOST}"
[ -n "$CONN_ENGINE" ] && echo "    Engine:     ${CONN_ENGINE}"
echo ""
echo -e "  ${BOLD}Test${NC}"
echo "    Plan:       $(basename "$TEST_PLAN")"
echo "    Properties: $(basename "$TEST_PROPERTIES_FILE")"
[ -n "${TEST_PROPERTIES_FILE_SOURCE:-}" ] && echo "    Properties source: ${TEST_PROPERTIES_FILE_SOURCE}"
echo "    Type:       ${TEST_TYPE}"
echo "    Run type:   ${RUN_TYPE}"
echo "    Queries:    $(basename "$ORIGINAL_QUERY_FILE") (${UNIQUE_QUERY_COUNT} unique queries)"
[ "$MEASURED_ITERATIONS" -gt 1 ] && echo "    Measured passes: ${MEASURED_ITERATIONS} (${QUERY_COUNT} total samples planned; same labels aggregated by JMeter)"
[ -n "${QUERY_FILE_SOURCE:-}" ] && echo "    Query source: ${QUERY_FILE_SOURCE}"
[ -n "${METADATA_FILE:-}" ] && echo "    Metadata:   $(basename "$METADATA_FILE")"
echo ""
echo -e "  ${BOLD}Parameters${NC}"

# Show only relevant parameters based on test type
case "$TEST_TYPE" in
    "Static Concurrency")
        echo "    Concurrency:     ${CONCURRENT_QUERY_COUNT}"
        echo "    Hold Period:     ${HOLD_PERIOD}s"
        echo "    Recycle on EOF:  ${RECYCLE_ON_EOF}"
        ;;
    "Run Once")
        echo "    Concurrency:     ${CONCURRENT_QUERY_COUNT}"
        ;;
    "Constant QPS")
        echo "    QPS:             ${QPS}"
        echo "    Hold Period:     ${HOLD_PERIOD}s"
        echo "    Recycle on EOF:  ${RECYCLE_ON_EOF}"
        ;;
    "Constant QPM")
        echo "    QPM:             ${QPM}"
        echo "    Hold Period:     ${HOLD_PERIOD}s"
        echo "    Recycle on EOF:  ${RECYCLE_ON_EOF}"
        ;;
    *"Load Profile"*)
        echo "    Load Profile:    ${LOAD_PROFILE}"
        [ -n "${LOAD_PROFILE_SOURCE:-}" ] && echo "    Profile source:  ${LOAD_PROFILE_SOURCE}"
        echo "    Hold Period:     ${HOLD_PERIOD}s"
        ;;
    *)
        echo "    Concurrency:     ${CONCURRENT_QUERY_COUNT}"
        echo "    Hold Period:     ${HOLD_PERIOD}s"
        echo "    Recycle on EOF:  ${RECYCLE_ON_EOF}"
        ;;
esac
echo "    Random Order:    ${RANDOM_ORDER}"
[ "${COPY_TO_S3}" = "true" ] && echo "    Copy to S3:      ${COPY_TO_S3}"
echo ""
echo -e "  ${BOLD}Output${NC}"
echo "    JMeter:  ${JMETER_HOME}"
echo "    Results: ${REPORT_DIR}/"
[ "$PROMETHEUS_ENABLED" = "true" ] && echo "    Metrics: http://${PROMETHEUS_IP}:${PROMETHEUS_PORT}/metrics"
[ -n "${GRAFANA_URL:-}" ] && echo "    Grafana: ${GRAFANA_URL}"
echo ""

# ============================================================================
# Build and run JMeter command
# ============================================================================

# Apply the load profile CSV to the plan's thread-group schedule.
# Covers both families: FreeFormArrivalsThreadGroup (arrival rate) and
# UltimateThreadGroup (concurrency waves).
# The plans' own JSR223 PreProcessors cannot do this: they run when a sampler
# fires, by which point the thread group has already read its schedule and
# started threads. So the schedule is injected here, before JMeter starts.
if grep -qE "FreeFormArrivalsThreadGroup|UltimateThreadGroup" "$TEST_PLAN" 2>/dev/null; then
    if [ -z "${LOAD_PROFILE:-}" ]; then
        echo -e "${YELLOW}Warning: load-profile plan selected but LOAD_PROFILE is not set.${NC}"
        echo -e "${YELLOW}The plan's built-in schedule will be used instead.${NC}"
        echo ""
    elif [ ! -f "$LOAD_PROFILE" ]; then
        echo -e "${RED}Error: LOAD_PROFILE file not found: ${LOAD_PROFILE}${NC}"
        exit 1
    else
        GENERATED_PLAN="${REPORT_DIR}/$(basename "${TEST_PLAN%.jmx}")-generated.jmx"
        python3 "${PROJECT_ROOT}/utilities/apply_load_profile.py" \
            "$TEST_PLAN" "$LOAD_PROFILE" "$GENERATED_PLAN" || exit 1
        echo ""
        TEST_PLAN="$GENERATED_PLAN"
    fi
fi

# JMeter's DBCP pool does not expose its generic password in the form expected
# by Databricks Driver 3 PAT auth. Engine selection already determines the
# driver, so adapt this internally without adding another user-facing input.
JDBC_DRIVER=$(grep -E '^DRIVER_CLASS=' "$CONNECTION_FILE" 2>/dev/null | tail -1 | cut -d= -f2-)
PROFILE_JDBC_INIT_SQL=$(grep -E '^JDBC_INIT_SQL=' "$CONNECTION_FILE" 2>/dev/null | tail -1 | cut -d= -f2-)
JDBC_INIT_SQL="${JDBC_INIT_SQL:-$PROFILE_JDBC_INIT_SQL}"
if [ "$JDBC_DRIVER" = "com.databricks.client.jdbc.Driver" ]; then
    JDBC_PLAN="${REPORT_DIR}/$(basename "${TEST_PLAN%.jmx}")-jdbc-configured.jmx"
    python3 "${PROJECT_ROOT}/utilities/configure_jdbc_connection.py" \
        "$TEST_PLAN" "$JDBC_PLAN" 'PWD=${PASSWORD}' || exit 1
    TEST_PLAN="$JDBC_PLAN"
    echo "  Databricks Driver 3: PAT authentication configured"
    echo ""
fi
if [ "$JDBC_DRIVER" = "net.snowflake.client.api.driver.SnowflakeDriver" ]; then
    # Disable Snowflake persisted-result reuse once for every physical pooled
    # connection. This preserves JMeter connection reuse and avoids adding a
    # control query to every measured sample.
    JDBC_INIT_SQL="${JDBC_INIT_SQL:-ALTER SESSION SET USE_CACHED_RESULT = FALSE}"
    # Snowflake's result path uses Apache Arrow. Java 9+ requires this narrow
    # module opening or every query can fail while materializing its result.
    # Append without replacing caller-provided heap/tuning options.
    case " ${JVM_ARGS:-} " in
        *" --add-opens=java.base/java.nio=ALL-UNNAMED "*) ;;
        *) JVM_ARGS="${JVM_ARGS:+$JVM_ARGS }--add-opens=java.base/java.nio=ALL-UNNAMED" ;;
    esac
    export JVM_ARGS
    echo "  Snowflake Arrow: Java NIO module access configured"
    echo "  Snowflake result cache: disabled for every pooled connection"
    echo ""
fi

# Opt-in only: derive another run-local plan containing the upstream listener.
# Source JMX files and the normal CLI path remain untouched when disabled.
if [ "$PROMETHEUS_ENABLED" = "true" ]; then
    PROMETHEUS_PLUGIN=""
    for _plugin in "$JMETER_HOME/lib/ext/jmeter-prometheus-plugin-0.6.0.jar" \
        "$PROJECT_ROOT/apache-jmeter-5.6.3/lib/ext/jmeter-prometheus-plugin-0.6.0.jar"; do
        [ -f "$_plugin" ] && PROMETHEUS_PLUGIN="$_plugin" && break
    done
    if [ -z "$PROMETHEUS_PLUGIN" ]; then
        echo -e "${RED}Error: PROMETHEUS_ENABLED=true but jmeter-prometheus-plugin-0.6.0.jar was not found.${NC}"
        exit 1
    fi
    # The plugin releases its server asynchronously after prometheus.delay.
    # Allow a bounded grace period so sequential suites can safely reuse a port.
    if ! python3 - "$PROMETHEUS_IP" "$PROMETHEUS_PORT" "$PROMETHEUS_DELAY" <<'PY'
import socket, sys, time
host, port = sys.argv[1], int(sys.argv[2])
deadline = time.monotonic() + max(30, int(sys.argv[3]) + 10)
while True:
    s = socket.socket()
    try:
        s.bind((host, port))
        break
    except OSError:
        if time.monotonic() >= deadline:
            raise
        time.sleep(0.25)
    finally:
        s.close()
PY
    then
        echo -e "${RED}Error: Prometheus metrics address ${PROMETHEUS_IP}:${PROMETHEUS_PORT} is unavailable.${NC}"
        exit 1
    fi
    PROMETHEUS_PLAN="${REPORT_DIR}/$(basename "${TEST_PLAN%.jmx}")-prometheus.jmx"
    python3 "${PROJECT_ROOT}/utilities/enable_prometheus_listener.py" "$TEST_PLAN" "$PROMETHEUS_PLAN"
    TEST_PLAN="$PROMETHEUS_PLAN"
fi

# Built as an array so values containing spaces or shell metacharacters
# (e.g. a query path with spaces, or a value containing parentheses) reach
# JMeter intact rather than being re-split by the shell
JMETER_CMD=("$JMETER_HOME/bin/jmeter" -n)
JMETER_CMD+=(-t "$TEST_PLAN")
JMETER_CMD+=(-q "$CONNECTION_FILE")
JMETER_CMD+=(-q "$TEST_PROPERTIES_FILE")
JMETER_CMD+=(-l "${REPORT_DIR}/JmeterResultFile.csv")
# HTML dashboard is ~3.5MB of vendored assets per run. CLAUDE.md documents
# GENERATE_DASHBOARD=false to skip it; honour that here.
if [ "${GENERATE_DASHBOARD:-true}" != "false" ]; then
    JMETER_CMD+=(-e -o "${REPORT_DIR}/dashboard")
fi

# Pass all test parameters as JMeter -J properties
JMETER_CMD+=("-JQUERY_PATH=$QUERY_FILE")
# Point REPORT_PATH at this run's directory so the plan's
# AggregateReport_<START_TIME>.csv / SummaryReport_... land with the run
# instead of the reports/ root (where they are orphaned and never uploaded).
JMETER_CMD+=("-JREPORT_PATH=$REPORT_DIR")
JMETER_CMD+=("-JCOPY_TO_S3=$COPY_TO_S3")
JMETER_CMD+=("-JS3_REPORT_PATH=$S3_REPORT_PATH")
JMETER_CMD+=("-JCONCURRENT_QUERY_COUNT=$CONCURRENT_QUERY_COUNT")
JMETER_CMD+=("-JQPS=$QPS")
JMETER_CMD+=("-JQPM=$QPM")
JMETER_CMD+=("-JHOLD_PERIOD=$HOLD_PERIOD")
JMETER_CMD+=("-JRAMP_UP_TIME=$RAMP_UP_TIME")
JMETER_CMD+=("-JRAMP_UP_STEPS=$RAMP_UP_STEPS")
JMETER_CMD+=("-JLOAD_PROFILE=$LOAD_PROFILE")
JMETER_CMD+=("-JRANDOM_ORDER=$RANDOM_ORDER")
JMETER_CMD+=("-JRECYCLE_ON_EOF=$RECYCLE_ON_EOF")
JMETER_CMD+=("-JQUERY_TIMEOUT=$QUERY_TIMEOUT")
JMETER_CMD+=("-JLIMIT_RESULTSET=$LIMIT_RESULTSET")
JMETER_CMD+=("-JMAX_CONCURRANCY=$MAX_CONCURRANCY")
JMETER_CMD+=("-JJDBC_INIT_SQL=${JDBC_INIT_SQL:-}")
JMETER_CMD+=("-Jjmeter.save.saveservice.autoflush=$JMETER_RESULT_AUTOFLUSH")
if [ "$PROMETHEUS_ENABLED" = "true" ]; then
    JMETER_CMD+=("-Jprometheus.ip=$PROMETHEUS_IP" "-Jprometheus.port=$PROMETHEUS_PORT" "-Jprometheus.delay=$PROMETHEUS_DELAY")
    if [ "$(dirname "$PROMETHEUS_PLUGIN")" != "$JMETER_HOME/lib/ext" ]; then
        JMETER_CMD+=("-Jsearch_paths=$(dirname "$PROMETHEUS_PLUGIN")")
    fi
fi

echo -e "${DIM}${JMETER_CMD[*]}${NC}"
echo ""
# The QPM plan uses Unit=M on its thread group, which governs BOTH the arrival rate
# (QPM = per minute) and the hold duration - so HOLD_PERIOD is MINUTES there, unlike
# every other plan where it is seconds. The two cannot be separated: setting Unit=S
# would make QPM mean per-second. Warn rather than silently run 60x too long.
if grep -q '<stringProp name="Unit">M</stringProp>' "$TEST_PLAN" 2>/dev/null; then
    echo -e "${YELLOW}  Note: this plan measures time in MINUTES.${NC}"
    echo -e "${YELLOW}  HOLD_PERIOD=${HOLD_PERIOD:-?} means ${HOLD_PERIOD:-?} minute(s), not seconds.${NC}"
    echo ""
fi

echo -e "${BLUE}Running JMeter...${NC}"
echo ""

# Run JMeter. Preserve its status but continue through report capture and output
# normalization so failed starts/runs leave useful diagnostics behind.
set +e
"${JMETER_CMD[@]}"
JMETER_RC=$?
set -e
RUN_FAILED=0
if [ "$JMETER_RC" -ne 0 ]; then
    RUN_FAILED=1
    echo -e "${RED}JMeter exited with status ${JMETER_RC}; finalizing available artifacts.${NC}"
fi

# Capture a standard run report alongside the raw results, so every run is
# self-describing and the analysis does not depend on anyone remembering to run
# it. Writes run_summary.json + run_report.md into the run directory.
if [ -f "${PROJECT_ROOT}/utilities/capture_run_report.py" ]; then
    CAPTURE_ARGS=("$REPORT_DIR")
    # Only compare against a load profile when the plan is actually profile-driven.
    # LOAD_PROFILE defaults to an existing file, so passing it unconditionally made
    # every non-profile run report a bogus "SHORTFALL" against a schedule it never used.
    if grep -qE "FreeFormArrivalsThreadGroup|UltimateThreadGroup" "$TEST_PLAN" 2>/dev/null \
       && [ -n "${LOAD_PROFILE:-}" ] && [ -f "$LOAD_PROFILE" ]; then
        CAPTURE_ARGS+=(--profile "$LOAD_PROFILE")
    fi
    CAPTURE_ARGS+=(--meta "run_id=${RUN_ID}" --meta "run_date=${RUN_DATE}")
    CAPTURE_ARGS+=(--meta "engine=${ENGINE:-unknown}" --meta "cluster_size=${CLUSTER_SIZE:-unknown}")
    CAPTURE_ARGS+=(--meta "benchmark=${BENCHMARK_TYPE:-unknown}" --meta "run_type=${RUN_TYPE}")
    # Optional descriptive metadata. These values annotate reports only; none
    # participate in JMeter load generation or query execution.
    for _meta_var in DATA_SIZE DATA_TYPE RUN_MODE CUSTOMER CONFIG TAGS COMMENTS \
        ESTIMATED_CORES MEMORY_GB INSTANCE_TYPE EXECUTORS CORES_PER_EXECUTOR \
        SERVERLESS ENGINE_BUILD RUN_SCOPE RUN_PURPOSE RUN_VALIDITY \
        SUITE_ID SUITE_RUN_ID SUITE_SEQUENCE SUITE_WORKLOAD SUITE_NAME \
        SUITE_COMPARISON_KEY; do
        _meta_value="${!_meta_var:-}"
        [ -n "$_meta_value" ] && CAPTURE_ARGS+=(--meta "${_meta_var}=${_meta_value}")
    done
    CAPTURE_ARGS+=(--meta "test_plan=$(basename "$ORIGINAL_TEST_PLAN")" --meta "queries=$(basename "$ORIGINAL_QUERY_FILE")")
    [ -n "${QUERY_FILE_SOURCE:-}" ] && CAPTURE_ARGS+=(--meta "query_source=${QUERY_FILE_SOURCE}")
    [ -n "${GENERATED_PLAN:-}" ] && CAPTURE_ARGS+=(--meta "generated_plan=$(basename "$GENERATED_PLAN")")
    QUERY_SHA=$(python3 "${PROJECT_ROOT}/utilities/query_file_info.py" "$ORIGINAL_QUERY_FILE" --field sha256)
    CAPTURE_ARGS+=(--meta "query_sha256=${QUERY_SHA}" --meta "measured_iterations=${MEASURED_ITERATIONS}" --meta "requested_concurrency=${CONCURRENT_QUERY_COUNT}")
    CAPTURE_ARGS+=(--meta "requested_qps=${QPS}" --meta "requested_qpm=${QPM}")
    CAPTURE_ARGS+=(--meta "hold_period=${HOLD_PERIOD}" --meta "ramp_up_time=${RAMP_UP_TIME}" --meta "ramp_up_steps=${RAMP_UP_STEPS}")
    CAPTURE_ARGS+=(--meta "max_concurrency=${MAX_CONCURRANCY}" --meta "recycle_on_eof=${RECYCLE_ON_EOF}" --meta "random_order=${RANDOM_ORDER}")
    CAPTURE_ARGS+=(--meta "jmeter_result_autoflush=${JMETER_RESULT_AUTOFLUSH}")
    CAPTURE_ARGS+=(--meta "warmup_enabled=${WARMUP_ENABLED}" --meta "warmup_iterations=${WARMUP_ITERATIONS}")
    if [ "$WARMUP_ENABLED" = "true" ]; then
        CAPTURE_ARGS+=(--meta "warmup_queries=$(basename "$WARMUP_QUERY_FILE")")
    fi
    CAPTURE_ARGS+=(--meta "prometheus_enabled=${PROMETHEUS_ENABLED}")
    [ "$PROMETHEUS_ENABLED" = "true" ] && CAPTURE_ARGS+=(--meta "prometheus_endpoint=http://${PROMETHEUS_IP}:${PROMETHEUS_PORT}/metrics")
    [ -n "${PROMETHEUS_URL:-}" ] && CAPTURE_ARGS+=(--meta "prometheus_url=${PROMETHEUS_URL}")
    [ -n "${GRAFANA_URL:-}" ] && CAPTURE_ARGS+=(--meta "grafana_url=${GRAFANA_URL}")
    CAPTURE_ARGS+=(--meta "jmeter_version=$(basename "$JMETER_HOME")" --meta "java_version=$(java -version 2>&1 | head -1)")
    CAPTURE_ARGS+=(--meta "git_commit=$(git rev-parse --short HEAD 2>/dev/null || echo unknown)")
    if [ -n "${LOAD_PROFILE:-}" ] && [ -f "$LOAD_PROFILE" ] \
       && grep -qE "FreeFormArrivalsThreadGroup|UltimateThreadGroup" "$TEST_PLAN" 2>/dev/null; then
        CAPTURE_ARGS+=(--meta "profile=$(basename "$LOAD_PROFILE")" --meta "profile_sha256=$(python3 "${PROJECT_ROOT}/utilities/query_file_info.py" "$LOAD_PROFILE" --field sha256)")
        [ -n "${LOAD_PROFILE_SOURCE:-}" ] && CAPTURE_ARGS+=(--meta "profile_source=${LOAD_PROFILE_SOURCE}")
    fi
    # Exit 2 from the report means the run itself failed (no samples, or an error
    # rate above MAX_ERROR_PCT). Propagate it: a run where the queries did not
    # succeed must not report success, or callers and CI treat it as a result.
    set +e
    python3 "${PROJECT_ROOT}/utilities/capture_run_report.py" "${CAPTURE_ARGS[@]}"
    CAPTURE_RC=$?
    set -e
    if [ "$CAPTURE_RC" -eq 2 ]; then
        RUN_FAILED=1
    elif [ "$CAPTURE_RC" -ne 0 ]; then
        echo -e "  ${YELLOW}run report capture failed (results are unaffected)${NC}"
    fi
fi

# The plan stamps these with JMeter's own START_TIME, which differs from run_id by
# a few seconds. Normalise to the names the analysis and Athena scripts expect.
for _f in "${REPORT_DIR}"/AggregateReport_*.csv; do
    [ -e "$_f" ] && mv -f "$_f" "${REPORT_DIR}/AggregateReport.csv" && break
done
for _f in "${REPORT_DIR}"/SummaryReport_*.csv; do
    [ -e "$_f" ] && mv -f "$_f" "${REPORT_DIR}/SummaryReport.csv" && break
done

# JMeter writes statistics.json under dashboard/; downstream analysis and Athena
# scripts look for it at the run root, so publish a copy there.
[ -f "${REPORT_DIR}/dashboard/statistics.json" ] && \
    cp "${REPORT_DIR}/dashboard/statistics.json" "${REPORT_DIR}/statistics.json"

# Optional e6-only enrichment. Machine-client credentials are deployment
# secrets rather than JDBC properties and are never copied into artifacts.
# Capture errors are non-fatal because they must not alter JMeter pass/fail.
if [ "$E6_QUERY_HISTORY_ENABLED" = "true" ]; then
    _e6_connection_string=$(grep -E '^CONNECTION_STRING=' "$CONNECTION_FILE" 2>/dev/null | tail -1 | cut -d= -f2-)
    if printf '%s' "$_e6_connection_string" | grep -q '^jdbc:e6data://'; then
        _e6_host=$(printf '%s' "$_e6_connection_string" | sed -E 's#^jdbc:e6data://([^/:;]+).*#\1#')
        _e6_cluster=$(printf '%s' "$_e6_connection_string" | sed -nE 's#.*[?&;]cluster-name=([^&;]+).*#\1#p')
        E6_QH_ARGS=(
            --base-url "https://${_e6_host}"
            --jmeter-results "${REPORT_DIR}/JmeterResultFile.csv"
            --output "${REPORT_DIR}/e6_query_history.csv"
            --status-output "${REPORT_DIR}/e6_query_history_capture.json"
            --wait-seconds "$E6_QUERY_HISTORY_WAIT_SECONDS"
        )
        [ -n "$_e6_cluster" ] && E6_QH_ARGS+=(--cluster "$_e6_cluster")
        [ -n "${E6_QUERY_HISTORY_EMAIL:-}" ] && E6_QH_ARGS+=(--email "$E6_QUERY_HISTORY_EMAIL")
        echo ""
        echo "Capturing e6 Query History..."
        set +e
        python3 "${PROJECT_ROOT}/utilities/get_e6_query_history.py" "${E6_QH_ARGS[@]}"
        E6_QH_RC=$?
        set -e
        [ "$E6_QH_RC" -ne 0 ] && echo -e "  ${YELLOW}Query History capture failed; JMeter results are unaffected.${NC}"
        unset _e6_connection_string _e6_host _e6_cluster E6_QH_ARGS E6_QH_RC
    else
        echo -e "${YELLOW}Warning: E6_QUERY_HISTORY_ENABLED=true ignored for a non-e6 JDBC connection.${NC}"
    fi
fi

echo ""
if [ "${RUN_FAILED:-0}" -eq 1 ]; then
    echo -e "${RED}=========================================="
    echo " Test FAILED"
    echo -e "==========================================${NC}"
else
    echo -e "${GREEN}=========================================="
    echo " Test Complete!"
    echo -e "==========================================${NC}"
fi
echo ""
echo "  Results:   ${REPORT_DIR}/"
echo "  Report:    ${REPORT_DIR}/run_report.md"
if [ "${GENERATE_DASHBOARD:-true}" != "false" ]; then
    echo "  Dashboard: ${REPORT_DIR}/dashboard/index.html"
else
    echo "  Dashboard: disabled"
fi

# Copy to S3 if enabled
if [ "${COPY_TO_S3}" = "true" ] && [ -n "${S3_UPLOAD_ROOT:-}" ]; then
    s3_partition_value() {
        printf '%s' "${1:-unknown}" | tr '[:space:]/' '__' | tr -cd '[:alnum:]_.-'
    }
    ENGINE_VAL="$(s3_partition_value "${ENGINE:-unknown}")"
    BENCHMARK_VAL="$(s3_partition_value "${BENCHMARK_TYPE:-unknown}")"
    DATA_SIZE_VAL="$(s3_partition_value "${DATA_SIZE:-unknown}")"
    CLUSTER_SIZE_VAL="$(s3_partition_value "${CLUSTER_SIZE:-unknown}")"
    RUN_TYPE_VAL="$(s3_partition_value "${RUN_TYPE:-unknown}")"
    RUN_ID_VAL="$(s3_partition_value "${TIMESTAMP}-${RUN_ID}")"
    S3_DEST="${S3_UPLOAD_ROOT%/}/engine=${ENGINE_VAL}/benchmark=${BENCHMARK_VAL}/data_size=${DATA_SIZE_VAL}/cluster_size=${CLUSTER_SIZE_VAL}/run_type=${RUN_TYPE_VAL}/run_date=${RUN_DATE}/run_id=${RUN_ID_VAL}/"

    echo ""
    echo "Uploading results to S3..."
    echo "  ${S3_DEST}"
    # The JMeter HTML dashboard vendors jQuery/Bootstrap/font-awesome/flot -
    # ~120 files and ~3.5MB per run, byte-identical every time and read by
    # nothing downstream. Upload the data and the dashboard pages, skip the
    # vendored assets. Set S3_UPLOAD_DASHBOARD_ASSETS=true to include them.
    if [ "${S3_UPLOAD_DASHBOARD_ASSETS:-false}" = "true" ]; then
        aws s3 cp "${REPORT_DIR}/" "${S3_DEST}" --recursive
    else
        aws s3 cp "${REPORT_DIR}/" "${S3_DEST}" --recursive \
            --exclude "dashboard/sbadmin2-1.0.7/*" \
            --exclude "dashboard/content/css/*" \
            --exclude "dashboard/content/js/*"
    fi
    jq -n --arg uri "${S3_DEST}" --arg uploaded_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        '{status:"verified",uri:$uri,uploaded_at:$uploaded_at}' > "${REPORT_DIR}/s3_upload.json"
    aws s3 cp "${REPORT_DIR}/s3_upload.json" "${S3_DEST}s3_upload.json" --only-show-errors
    echo -e "  ${GREEN}Uploaded to S3${NC}"
fi

echo ""
# Exit non-zero when the run produced no usable result, so callers and CI can
# tell a real benchmark from one where every query failed.
exit "${RUN_FAILED:-0}"
