#!/bin/bash
# Non-interactive JMeter test runner — runs from env vars or a suite file
#
# Usage:
#   ./run_test.sh                     # reads from env vars
#   ./run_test.sh my_suite.env        # sources suite file, then runs
#
# Required (set via env or suite file):
#   CONNECTION_FILE   - path to connection properties file
#   TEST_PLAN         - path to test plan .jmx file
#   QUERY_FILE        - path to query CSV data file
#
# Optional (with defaults):
#   METADATA_FILE             - metadata file for S3 upload (default: none)
#   CONCURRENT_QUERY_COUNT    - number of concurrent queries (default: 2)
#   QPS                       - queries per second (default: 1)
#   QPM                       - queries per minute (default: 10)
#   HOLD_PERIOD               - test duration in seconds (default: 300)
#   RAMP_UP_TIME              - ramp up time in seconds (default: 1)
#   RAMP_UP_STEPS             - ramp up steps (default: 1)
#   LOAD_PROFILE              - load profile CSV path (default: test_properties/load_profile.csv)
#   RANDOM_ORDER              - random query order true/false (default: false)
#   RECYCLE_ON_EOF            - repeat queries true/false (default: false)
#   COPY_TO_S3                - upload results to S3 true/false (default: false)
#   S3_REPORT_PATH            - S3 path for results (default: s3://e6-jmeter/jmeter-results)
#   REPORT_PATH               - local report directory (default: reports)
#   QUERY_TIMEOUT             - query timeout in seconds (default: 300)
#   LIMIT_RESULTSET           - max result rows (default: 1000)
#   MAX_CONCURRANCY           - max threads (default: 900)
#   JMETER_HOME               - JMeter installation path (auto-detected if not set)
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
#   ./run_test.sh test_suites/e6data_qps_test.env

set -e

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
DIM='\033[2m'
NC='\033[0m'

# Navigate to project root
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

# ============================================================================
# Source suite file if provided
# ============================================================================

if [ -n "$1" ]; then
    SUITE_FILE="$1"
    if [ ! -f "$SUITE_FILE" ]; then
        echo -e "${RED}Error: Suite file not found: ${SUITE_FILE}${NC}"
        exit 1
    fi
    echo -e "${BLUE}Loading suite file: ${SUITE_FILE}${NC}"
    source "$SUITE_FILE"
fi

# ============================================================================
# Validate required variables
# ============================================================================

MISSING=()
[ -z "${CONNECTION_FILE:-}" ] && MISSING+=("CONNECTION_FILE")
[ -z "${TEST_PLAN:-}" ] && MISSING+=("TEST_PLAN")
[ -z "${QUERY_FILE:-}" ] && MISSING+=("QUERY_FILE")

if [ ${#MISSING[@]} -gt 0 ]; then
    echo -e "${RED}Error: Missing required variables:${NC}"
    for var in "${MISSING[@]}"; do
        echo "  - $var"
    done
    echo ""
    echo "Set them via environment variables or pass a suite file:"
    echo "  $0 <suite_file.env>"
    echo ""
    echo "Required:"
    echo "  CONNECTION_FILE   - e.g., connection_properties/e6data_default_connection.properties"
    echo "  TEST_PLAN         - e.g., Test-Plans/Test-Plan-Maintain-static-concurrency.jmx"
    echo "  QUERY_FILE        - e.g., data_files/E6Data_TPCDS_queries_29_1TB.csv"
    exit 1
fi

# Validate files exist
for var in CONNECTION_FILE TEST_PLAN QUERY_FILE; do
    val="${!var}"
    if [ ! -f "$val" ]; then
        echo -e "${RED}Error: ${var} file not found: ${val}${NC}"
        exit 1
    fi
done

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
RAMP_UP_TIME="${RAMP_UP_TIME:-1}"
RAMP_UP_STEPS="${RAMP_UP_STEPS:-1}"
LOAD_PROFILE="${LOAD_PROFILE:-test_properties/load_profile.csv}"
RANDOM_ORDER="${RANDOM_ORDER:-false}"
RECYCLE_ON_EOF="${RECYCLE_ON_EOF:-false}"
COPY_TO_S3="${COPY_TO_S3:-false}"
S3_REPORT_PATH="${S3_REPORT_PATH:-s3://e6-jmeter/jmeter-results}"
REPORT_PATH="${REPORT_PATH:-reports}"
QUERY_TIMEOUT="${QUERY_TIMEOUT:-300}"
LIMIT_RESULTSET="${LIMIT_RESULTSET:-1000}"
MAX_CONCURRANCY="${MAX_CONCURRANCY:-900}"

# Source metadata if present (may override COPY_TO_S3, ENGINE, etc.)
if [ -n "${METADATA_FILE:-}" ]; then
    source "$METADATA_FILE"
fi

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

# ============================================================================
# Display configuration
# ============================================================================

TIMESTAMP=$(date +%Y%m%d-%H%M%S)
REPORT_DIR="${REPORT_PATH}/${TIMESTAMP}"
mkdir -p "$REPORT_DIR"

echo ""
echo -e "${BLUE}=========================================="
echo " JMeter Test Runner"
echo -e "==========================================${NC}"
echo ""
echo "  Connection:   $(basename "$CONNECTION_FILE")"
echo "  Test Plan:    $(basename "$TEST_PLAN")"
echo "  Query File:   $(basename "$QUERY_FILE")"
[ -n "${METADATA_FILE:-}" ] && echo "  Metadata:     $(basename "$METADATA_FILE")"
echo ""
echo "  Parameters:"
echo "    CONCURRENT_QUERY_COUNT = ${CONCURRENT_QUERY_COUNT}"
echo "    QPS = ${QPS}"
echo "    QPM = ${QPM}"
echo "    HOLD_PERIOD = ${HOLD_PERIOD}s"
echo "    RAMP_UP_TIME = ${RAMP_UP_TIME}s"
echo "    RANDOM_ORDER = ${RANDOM_ORDER}"
echo "    RECYCLE_ON_EOF = ${RECYCLE_ON_EOF}"
echo "    COPY_TO_S3 = ${COPY_TO_S3}"
echo ""
echo "  JMeter:  ${JMETER_HOME}"
echo "  Output:  ${REPORT_DIR}/"
echo ""

# ============================================================================
# Build and run JMeter command
# ============================================================================

JMETER_CMD="$JMETER_HOME/bin/jmeter -n"
JMETER_CMD+=" -t $TEST_PLAN"
JMETER_CMD+=" -q $CONNECTION_FILE"
JMETER_CMD+=" -l ${REPORT_DIR}/JmeterResultFile.csv"
JMETER_CMD+=" -e -o ${REPORT_DIR}/dashboard"

# Pass all test parameters as JMeter -J properties
JMETER_CMD+=" -JQUERY_PATH=$QUERY_FILE"
JMETER_CMD+=" -JREPORT_PATH=$REPORT_PATH"
JMETER_CMD+=" -JCOPY_TO_S3=$COPY_TO_S3"
JMETER_CMD+=" -JS3_REPORT_PATH=$S3_REPORT_PATH"
JMETER_CMD+=" -JCONCURRENT_QUERY_COUNT=$CONCURRENT_QUERY_COUNT"
JMETER_CMD+=" -JQPS=$QPS"
JMETER_CMD+=" -JQPM=$QPM"
JMETER_CMD+=" -JHOLD_PERIOD=$HOLD_PERIOD"
JMETER_CMD+=" -JRAMP_UP_TIME=$RAMP_UP_TIME"
JMETER_CMD+=" -JRAMP_UP_STEPS=$RAMP_UP_STEPS"
JMETER_CMD+=" -JLOAD_PROFILE=$LOAD_PROFILE"
JMETER_CMD+=" -JRANDOM_ORDER=$RANDOM_ORDER"
JMETER_CMD+=" -JRECYCLE_ON_EOF=$RECYCLE_ON_EOF"
JMETER_CMD+=" -JQUERY_TIMEOUT=$QUERY_TIMEOUT"
JMETER_CMD+=" -JLIMIT_RESULTSET=$LIMIT_RESULTSET"
JMETER_CMD+=" -JMAX_CONCURRANCY=$MAX_CONCURRANCY"

# Optional: threads_schedule for variable concurrency
if [ -n "${THREADS_SCHEDULE:-}" ]; then
    JMETER_CMD+=" -Jthreads_schedule=$THREADS_SCHEDULE"
fi

echo -e "${DIM}${JMETER_CMD}${NC}"
echo ""
echo -e "${BLUE}Running JMeter...${NC}"
echo ""

# Run JMeter
eval "$JMETER_CMD"

echo ""
echo -e "${GREEN}=========================================="
echo " Test Complete!"
echo -e "==========================================${NC}"
echo ""
echo "  Results:   ${REPORT_DIR}/"
echo "  Dashboard: ${REPORT_DIR}/dashboard/index.html"

# Copy to S3 if enabled
if [ "${COPY_TO_S3}" = "true" ] && [ -n "${S3_BASE_PATH:-}" ]; then
    ENGINE_VAL="${ENGINE:-unknown}"
    CLUSTER_SIZE_VAL="${CLUSTER_SIZE:-unknown}"
    BENCHMARK_VAL="${BENCHMARK_TYPE:-unknown}"
    S3_DEST="${S3_BASE_PATH}/engine=${ENGINE_VAL}/cluster_size=${CLUSTER_SIZE_VAL}/benchmark=${BENCHMARK_VAL}/run_id=${TIMESTAMP}/"

    echo ""
    echo "Uploading results to S3..."
    echo "  ${S3_DEST}"
    aws s3 cp "${REPORT_DIR}/" "${S3_DEST}" --recursive
    echo -e "  ${GREEN}Uploaded to S3${NC}"
fi

echo ""
