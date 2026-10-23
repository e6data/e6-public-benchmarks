#!/bin/bash
# Create a test configuration file interactively
# Usage: ./create_test_config.sh
#
# Walks you through selecting:
#   1. Connection properties file
#   2. Test plan type
#   3. Query data file
#   4. Test parameters (concurrency, QPS, hold period, etc.)
#   5. Optional metadata file
#
# Saves a .env config file to test_configs/ for use with ./run_test.sh

set -e
case "${1:-}" in
    ""|--run) ;;
    *) echo "Usage: ./create_test_config.sh [--run]"; exit 2 ;;
esac

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

CONFIG_DIR="test_configs"
mkdir -p "$CONFIG_DIR"

echo -e "${BLUE}=========================================="
echo " Create Test Configuration"
echo -e "==========================================${NC}"
echo ""

# ============================================================================
# Step 1: Select connection file
# ============================================================================

echo -e "${BOLD}Step 1: Select connection file${NC}"
echo ""

shopt -s nullglob
CONN_FILES=(connection_properties/*.properties)

if [ ${#CONN_FILES[@]} -eq 0 ]; then
    echo -e "${YELLOW}No connection files found.${NC}"
    read -p "Create one now? (y/n): " create_conn
    if [[ "$create_conn" =~ ^[Yy]$ ]]; then
        "${PROJECT_ROOT}/create_connection.sh"
        # Re-scan after creation
        CONN_FILES=(connection_properties/*.properties)
        if [ ${#CONN_FILES[@]} -eq 0 ]; then
            echo -e "${RED}No connection file was created. Exiting.${NC}"
            exit 1
        fi
        echo ""
        echo -e "${BOLD}Step 1: Select connection file${NC}"
        echo ""
    else
        echo "Run ./create_connection.sh first to create one."
        exit 1
    fi
fi

for i in "${!CONN_FILES[@]}"; do
    echo "  $((i+1))) $(basename "${CONN_FILES[$i]}")"
done
echo ""
read -p "Select connection [1-${#CONN_FILES[@]}] or enter its path: " conn_idx

if [[ "$conn_idx" =~ ^[0-9]+$ ]] && [ "$conn_idx" -ge 1 ] && [ "$conn_idx" -le "${#CONN_FILES[@]}" ]; then
    CONNECTION_FILE="${CONN_FILES[$((conn_idx-1))]}"
elif [ -f "$conn_idx" ]; then
    CONNECTION_FILE="$conn_idx"
elif [ -f "connection_properties/$conn_idx" ]; then
    CONNECTION_FILE="connection_properties/$conn_idx"
else
    echo -e "${RED}Invalid selection${NC}"
    exit 1
fi
echo -e "  ${GREEN}Selected: $(basename "$CONNECTION_FILE")${NC}"
echo ""

# Detect connection type (JDBC vs HTTP)
if grep -q "mainhost" "$CONNECTION_FILE" 2>/dev/null; then
    CONN_TYPE="http"
else
    CONN_TYPE="jdbc"
fi

# ============================================================================
# Step 2: Select test plan
# ============================================================================

echo -e "${BOLD}Step 2: Select test plan${NC}"
echo ""

# Show common test plans based on connection type, plus "Other" for all remaining
SEQUENTIAL=false
if [ "$CONN_TYPE" = "jdbc" ]; then
    echo "  JDBC test plans:"
    echo ""
    echo "  1) Sequential                — every query once, one at a time"
    echo "  2) Fixed QPS                 — steady query submissions per second"
    echo "  3) Arrival-rate profile      — QPS varies over time (CSV schedule)"
    echo "  4) Advanced                  — concurrency, QPM and other plans"
    echo ""
    read -p "Select test type [1-4]: " plan_choice

    case "$plan_choice" in
        1) TEST_PLAN="Test-Plans/Test-Plan-Run-Once-static-concurrency.jmx"; SEQUENTIAL=true ;;
        2) TEST_PLAN="Test-Plans/Test-Plan-Constant-QPS-On-Arrivals-JSR-Optimized.jmx" ;;
        3) TEST_PLAN="Test-Plans/Test-Plan-Fire-QPS-with-load-profile.jmx" ;;
        4)
            echo "  1) Fixed concurrency"
            echo "  2) Run once concurrently"
            echo "  3) Variable concurrency profile"
            echo "  4) Fixed QPM"
            echo "  5) All available plans"
            read -p "Select advanced plan [1-5]: " advanced_choice
            case "$advanced_choice" in
                1) TEST_PLAN="Test-Plans/Test-Plan-Maintain-static-concurrency.jmx" ;;
                2) TEST_PLAN="Test-Plans/Test-Plan-Run-Once-static-concurrency.jmx" ;;
                3) TEST_PLAN="Test-Plans/Test-Plan-Maintain-variable-concurrency-with-load-profile.jmx" ;;
                4) TEST_PLAN="Test-Plans/Test-Plan-Constant-QPM-On-Arrivals.jmx" ;;
                5) plan_choice=7 ;;
                *) echo "Invalid choice"; exit 1 ;;
            esac ;;
        *) echo -e "${RED}Invalid choice${NC}"; exit 1 ;;
    esac
else
    echo "  HTTP endpoint test plans:"
    echo ""
    echo "  1) Static Concurrency        — fixed number of concurrent queries"
    echo "  2) Run Once                   — each query runs exactly once"
    echo "  3) QPS with Load Profile     — QPS varies over time (CSV schedule)"
    echo "  4) Other                     — show all available test plans"
    echo ""
    read -p "Select test type [1-4]: " plan_choice

    case "$plan_choice" in
        1) TEST_PLAN="Test-Plans/Test-Plan-Maintain-static-concurrency-http-endpoint-v2.jmx" ;;
        2) TEST_PLAN="Test-Plans/Test-Plan-Run-Once-http-endpoint.jmx" ;;
        3) TEST_PLAN="Test-Plans/Test-Plan-Fire-QPS-with-load-profile-http-endpoint_v2.jmx" ;;
        4) ;; # handled below
        *) echo -e "${RED}Invalid choice${NC}"; exit 1 ;;
    esac
fi

# Handle "Other" — list all .jmx files not in the curated list
if { [ "$CONN_TYPE" = "jdbc" ] && [ "$plan_choice" = "7" ]; } || \
   { [ "$CONN_TYPE" = "http" ] && [ "$plan_choice" = "4" ]; }; then
    echo ""
    echo -e "${BOLD}All available test plans:${NC}"
    echo ""
    ALL_PLANS=($(ls -1 Test-Plans/*.jmx 2>/dev/null))
    for i in "${!ALL_PLANS[@]}"; do
        echo "  $((i+1))) $(basename "${ALL_PLANS[$i]}")"
    done
    echo ""
    read -p "Select test plan [1-${#ALL_PLANS[@]}]: " other_idx
    if [[ ! "$other_idx" =~ ^[0-9]+$ ]] || [ "$other_idx" -lt 1 ] || [ "$other_idx" -gt "${#ALL_PLANS[@]}" ]; then
        echo -e "${RED}Invalid selection${NC}"
        exit 1
    fi
    TEST_PLAN="${ALL_PLANS[$((other_idx-1))]}"
fi

echo -e "  ${GREEN}Selected: $(basename "$TEST_PLAN")${NC}"

# Infer PLAN_TYPE from filename for parameter prompts
PLAN_NAME=$(basename "$TEST_PLAN" .jmx | tr '[:upper:]' '[:lower:]')
if echo "$PLAN_NAME" | grep -q "run-once"; then
    PLAN_TYPE="run_once"
elif echo "$PLAN_NAME" | grep -q "variable-concurrency\|load-profile.*concurrency"; then
    PLAN_TYPE="var_concurrency"
elif echo "$PLAN_NAME" | grep -q "qps.*load-profile\|loadprofile.*qps\|qps-loadprofile\|loadprofile"; then
    PLAN_TYPE="qps_profile"
elif echo "$PLAN_NAME" | grep -q "qpm.*load-profile"; then
    PLAN_TYPE="qpm_profile"
elif echo "$PLAN_NAME" | grep -q "qps"; then
    PLAN_TYPE="qps"
elif echo "$PLAN_NAME" | grep -q "qpm"; then
    PLAN_TYPE="qpm"
else
    PLAN_TYPE="concurrency"
fi
case "$PLAN_TYPE" in
    run_once) DEFAULT_PROPERTIES=test_properties/run_once.properties ;;
    concurrency) DEFAULT_PROPERTIES=test_properties/fixed_concurrency.properties ;;
    qps) DEFAULT_PROPERTIES=test_properties/constant_qps.properties ;;
    qpm) DEFAULT_PROPERTIES=test_properties/constant_qpm.properties ;;
    qps_profile|qpm_profile) DEFAULT_PROPERTIES=test_properties/variable_arrivals.properties ;;
    var_concurrency) DEFAULT_PROPERTIES=test_properties/variable_concurrency.properties ;;
esac
TEST_PROPERTIES_FILE="${TEST_PROPERTIES_FILE:-$DEFAULT_PROPERTIES}"
if [ ! -f "$TEST_PROPERTIES_FILE" ]; then
    echo "Test properties must be a readable local file: $TEST_PROPERTIES_FILE"; exit 1
fi
property_default() {
    awk -F= -v key="$1" '$1 == key {sub(/^[^=]*=/, ""); sub(/\r$/, ""); print; exit}' "$TEST_PROPERTIES_FILE"
}
ask_number() {
    local key="$1" label="$2" minimum="$3" maximum="$4" value default
    default=$(property_default "$key")
    if [ -z "$default" ]; then
        default=$(awk -F= -v key="$key" '$1 == key {print $2; exit}' "$DEFAULT_PROPERTIES")
    fi
    read -p "$label [$default]: " value
    value=${value:-$default}
    if [[ ! "$value" =~ ^[0-9]+$ ]] || [ "$value" -lt "$minimum" ] || [ "$value" -gt "$maximum" ]; then
        echo "Invalid $label: expected $minimum to $maximum" >&2; exit 1
    fi
    printf -v "$key" '%s' "$value"
}
ask_bool() {
    local key="$1" label="$2" value default
    default=$(property_default "$key")
    if [ -z "$default" ]; then
        default=$(awk -F= -v key="$key" '$1 == key {print $2; exit}' "$DEFAULT_PROPERTIES")
    fi
    read -p "$label (true/false) [$default]: " value
    value=${value:-$default}
    case "$value" in true|false) ;; *) echo "Expected true or false"; exit 1 ;; esac
    printf -v "$key" '%s' "$value"
}
echo -e "  ${DIM}(type: ${PLAN_TYPE})${NC}"
echo ""

# ============================================================================
# Step 3: Select query data file
# ============================================================================

echo -e "${BOLD}Step 3: Select query data file${NC}"
echo ""

QUERY_FILES=()
while IFS= read -r -d '' file; do QUERY_FILES+=("$file"); done < <(find data_files -type f -name '*.csv' -print0 2>/dev/null)
for i in "${!QUERY_FILES[@]}"; do
    echo "  $((i+1))) ${QUERY_FILES[$i]}"
done
read -p "Select query number or enter local path / s3:// URI: " query_choice
if [[ "$query_choice" =~ ^[0-9]+$ ]]; then
    if [ "$query_choice" -lt 1 ] || [ "$query_choice" -gt "${#QUERY_FILES[@]}" ]; then
        echo "Invalid query selection"; exit 1
    fi
    QUERY_FILE="${QUERY_FILES[$((query_choice-1))]}"
else
    QUERY_FILE="$query_choice"
fi
python3 utilities/wizard_input.py query "$QUERY_FILE"

# ============================================================================
# Step 4: Test parameters
# ============================================================================

echo -e "${BOLD}Step 4: Test parameters${NC}"
echo ""

# Parameters depend on test plan type
case "$PLAN_TYPE" in
    concurrency)
        ask_number CONCURRENT_QUERY_COUNT "Concurrent queries" 1 10000
        ask_number HOLD_PERIOD "Hold period in seconds" 1 86400
        ask_bool RANDOM_ORDER "Random query order"
        ask_bool RECYCLE_ON_EOF "Repeat queries until schedule ends"
        ;;
    run_once)
        if [ "${SEQUENTIAL:-false}" = true ]; then
            CONCURRENT_QUERY_COUNT=1
            echo "Sequential: one query at a time."
        else
        ask_number CONCURRENT_QUERY_COUNT "Concurrent queries" 1 10000
        fi
        ask_number MEASURED_ITERATIONS "Measured iterations" 1 20
        HOLD_PERIOD=0
        RANDOM_ORDER=false
        RECYCLE_ON_EOF=false
        ;;
    qps)
        ask_number QPS "Queries per second" 1 100000
        ask_number HOLD_PERIOD "Hold period in seconds" 1 86400
        RANDOM_ORDER=false
        ask_bool RECYCLE_ON_EOF "Repeat queries until schedule ends"
        ;;
    qpm)
        ask_number QPM "Queries per minute" 1 1000000
        ask_number HOLD_PERIOD "Hold period in minutes" 1 86400
        RANDOM_ORDER=false
        ask_bool RECYCLE_ON_EOF "Repeat queries until schedule ends"
        ;;
    qps_profile|qpm_profile)
        PROFILE_KIND=arrivals
        echo "CSV columns: StartValue,EndValue,Duration (QPS, QPS, seconds)."
        echo "Use a file on this runner; relative paths start at the framework directory."
        read -p "Load profile CSV [test_properties/load_profile.csv]: " LOAD_PROFILE
        LOAD_PROFILE=${LOAD_PROFILE:-$(property_default LOAD_PROFILE)}
        python3 utilities/wizard_input.py "${PROFILE_KIND}" "$LOAD_PROFILE"
        echo "Schedule duration comes from the CSV; Hold period does not apply."
        ask_bool RANDOM_ORDER "Random query order"
        RECYCLE_ON_EOF=true
        ;;
    var_concurrency)
        PROFILE_KIND=concurrency
        echo "CSV columns: Threads,StartTime,StartupTime,HoldTime,ShutdownTime."
        echo "Times are seconds; overlapping rows add workers. Use a runner-local file."
        read -p "Load profile CSV [test_properties/utg_load_profile.csv]: " LOAD_PROFILE
        LOAD_PROFILE=${LOAD_PROFILE:-$(property_default LOAD_PROFILE)}
        python3 utilities/wizard_input.py "${PROFILE_KIND}" "$LOAD_PROFILE"
        echo "Schedule duration comes from the CSV; Hold period does not apply."
        RANDOM_ORDER=false
        RECYCLE_ON_EOF=true
        ;;
esac

echo ""

# ============================================================================
# Step 5: Optional metadata (for S3 upload)
# ============================================================================

WARMUP_ENABLED=false
read -p "Enable excluded sequential warm-up? (y/n) [n]: " warmup
if [[ "$warmup" =~ ^[Yy]$ ]]; then
    WARMUP_ENABLED=true
    read -p "Warm-up query path or s3:// URI [$QUERY_FILE]: " WARMUP_QUERY_FILE
    WARMUP_QUERY_FILE=${WARMUP_QUERY_FILE:-$QUERY_FILE}
    python3 utilities/wizard_input.py query "$WARMUP_QUERY_FILE"
    read -p "Warm-up iterations [1]: " WARMUP_ITERATIONS
    WARMUP_ITERATIONS=${WARMUP_ITERATIONS:-1}
    if [[ ! "$WARMUP_ITERATIONS" =~ ^[0-9]+$ ]] || [ "$WARMUP_ITERATIONS" -lt 1 ] || [ "$WARMUP_ITERATIONS" -gt 20 ]; then
        echo "Warm-up iterations must be between 1 and 20"; exit 1
    fi
fi
echo "Limits, ramp settings and report options use the selected test-properties defaults."
echo "Override them in the saved .env or with environment variables if needed."
echo -e "${BOLD}Step 5: Metadata file (optional — for S3 upload)${NC}"
echo ""

META_FILES=(metadata_files/*.txt)

if [ ${#META_FILES[@]} -gt 0 ]; then
    echo "  0) None (skip)"
    for i in "${!META_FILES[@]}"; do
        echo "  $((i+1))) $(basename "${META_FILES[$i]}")"
    done
    echo ""
    read -p "Select metadata file [0-${#META_FILES[@]}, default=0]: " meta_idx
    meta_idx=${meta_idx:-0}

    if [ "$meta_idx" -gt 0 ] 2>/dev/null && [ "$meta_idx" -le "${#META_FILES[@]}" ]; then
        METADATA_FILE="${META_FILES[$((meta_idx-1))]}"
        echo -e "  ${GREEN}Selected: $(basename "$METADATA_FILE")${NC}"
    else
        METADATA_FILE=""
        echo -e "  ${DIM}Skipped${NC}"
    fi
else
    echo -e "  ${DIM}No metadata files found — skipping${NC}"
    METADATA_FILE=""
fi
echo ""

# ============================================================================
# Step 6: Name and save config file
# ============================================================================

echo -e "${BOLD}Step 6: Save configuration${NC}"
echo ""

# Suggest a name based on selections
CONN_BASE=$(basename "$CONNECTION_FILE" .properties | sed 's/_connection$//')
PLAN_SHORT=$(echo "$PLAN_TYPE" | tr '_' '-')
SUGGESTED_NAME="${CONN_BASE}_${PLAN_SHORT}"

read -p "Config name [${SUGGESTED_NAME}]: " CONFIG_NAME
CONFIG_NAME=${CONFIG_NAME:-$SUGGESTED_NAME}

# Ensure .env extension
if [[ ! "$CONFIG_NAME" =~ ^[A-Za-z0-9_-]+$ ]]; then
    echo "Config name must contain only letters, numbers, hyphens or underscores"; exit 1
fi
CONFIG_FILE="${CONFIG_DIR}/${CONFIG_NAME}.env"

if [ -f "$CONFIG_FILE" ]; then
    echo ""
    echo -e "${YELLOW}File already exists: ${CONFIG_FILE}${NC}"
    read -p "Overwrite? (y/n): " overwrite
    if [[ ! "$overwrite" =~ ^[Yy]$ ]]; then
        echo "Cancelled."
        exit 0
    fi
fi

# Write the config file
{
    echo "# Test Configuration: ${CONFIG_NAME}"
    echo "# Created: $(date +%Y-%m-%d)"
    echo "# Usage: ./run_test.sh ${CONFIG_FILE}"
    echo ""
    echo "# Connection and files"
    printf 'CONNECTION_FILE=%q\n' "$CONNECTION_FILE"
    echo "TEST_PLAN=${TEST_PLAN}"
    printf 'QUERY_FILE=%q\n' "$QUERY_FILE"
    printf 'TEST_PROPERTIES_FILE=%q\n' "$TEST_PROPERTIES_FILE"
    echo "WARMUP_ENABLED=$WARMUP_ENABLED"
    if [ "$WARMUP_ENABLED" = true ]; then
        printf 'WARMUP_QUERY_FILE=%q\n' "$WARMUP_QUERY_FILE"
        echo "WARMUP_ITERATIONS=$WARMUP_ITERATIONS"
    fi

    if [ -n "$METADATA_FILE" ]; then
        printf 'METADATA_FILE=%q\n' "$METADATA_FILE"
    fi

    echo ""
    echo "# Test parameters"

    case "$PLAN_TYPE" in
        concurrency)
            echo "CONCURRENT_QUERY_COUNT=${CONCURRENT_QUERY_COUNT}"
            echo "HOLD_PERIOD=${HOLD_PERIOD}"
            echo "RANDOM_ORDER=${RANDOM_ORDER}"
            echo "RECYCLE_ON_EOF=${RECYCLE_ON_EOF}"
            ;;
        run_once)
            echo "CONCURRENT_QUERY_COUNT=${CONCURRENT_QUERY_COUNT}"
            echo "MEASURED_ITERATIONS=${MEASURED_ITERATIONS}"
            echo "RANDOM_ORDER=${RANDOM_ORDER}"
            echo "RECYCLE_ON_EOF=false"
            ;;
        qps)
            echo "QPS=${QPS}"
            echo "HOLD_PERIOD=${HOLD_PERIOD}"
            echo "RANDOM_ORDER=${RANDOM_ORDER}"
            echo "RECYCLE_ON_EOF=${RECYCLE_ON_EOF}"
            ;;
        qpm)
            echo "QPM=${QPM}"
            echo "HOLD_PERIOD=${HOLD_PERIOD}"
            echo "RANDOM_ORDER=${RANDOM_ORDER}"
            echo "RECYCLE_ON_EOF=${RECYCLE_ON_EOF}"
            ;;
        qps_profile|qpm_profile|var_concurrency)
            printf 'LOAD_PROFILE=%q\n' "$LOAD_PROFILE"
            echo "RANDOM_ORDER=${RANDOM_ORDER}"
            echo "RECYCLE_ON_EOF=${RECYCLE_ON_EOF}"
            ;;
    esac

    echo ""
    echo "# S3 upload (default: disabled)"
    echo "COPY_TO_S3=false"
} > "$CONFIG_FILE"

echo ""
echo -e "${GREEN}=========================================="
echo " Test configuration saved!"
echo -e "==========================================${NC}"
echo ""
echo "  File: ${CONFIG_FILE}"
echo ""
echo -e "${BOLD}To run this test:${NC}"
echo "  ./run_test.sh ${CONFIG_FILE}"
echo ""
echo -e "${BOLD}To re-run with different parameters:${NC}"
case "$PLAN_TYPE" in
    qps) echo "  QPS=2 ./run_test.sh ${CONFIG_FILE}" ;;
    qpm) echo "  QPM=60 ./run_test.sh ${CONFIG_FILE}" ;;
    qps_profile|qpm_profile|var_concurrency) echo "  LOAD_PROFILE=path/to/schedule.csv ./run_test.sh ${CONFIG_FILE}" ;;
    run_once) echo "  MEASURED_ITERATIONS=3 ./run_test.sh ${CONFIG_FILE}" ;;
    *) echo "  CONCURRENT_QUERY_COUNT=8 ./run_test.sh ${CONFIG_FILE}" ;;
esac
echo ""
echo -e "${BOLD}The saved .env is read by run_test.sh, not directly by JMeter.${NC}"
echo "The runner selects the bundled test_properties file automatically."

if [ "${1:-}" = "--run" ]; then
    read -p "Launch this benchmark now? (y/n) [n]: " launch
    if [[ "$launch" =~ ^[Yy]$ ]]; then
        exec ./run_test.sh "$CONFIG_FILE"
    fi
    echo "Saved only; no benchmark launched."
fi
