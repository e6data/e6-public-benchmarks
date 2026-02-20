#!/bin/bash
# Interactive JMeter test runner
# Usage: ./run_jmeter_tests_interactive.sh
#
# Guides users through:
#   1. Select connection properties file
#   2. Select test plan (concurrency, QPS, QPM, load profile, HTTP endpoint, etc.)
#   3. Select or create test properties (with relevant runtime parameters)
#   4. Select query data file (CSV)
#   5. Optionally select metadata file (for S3 upload)
#   6. Run the JMeter test

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

# Directories
CONN_DIR="connection_properties"
TEST_PROPS_DIR="test_properties"
DATA_DIR="data_files"
TEST_PLANS_DIR="Test-Plans"
METADATA_DIR="metadata_files"

# ============================================================================
# Helper functions
# ============================================================================

# Display a numbered list and get user selection
# Usage: select_file "prompt" file1 file2 file3 ...
# Returns: selected file path in SELECTED_FILE variable
select_file() {
    local prompt="$1"
    shift
    local files=("$@")
    local count=${#files[@]}

    if [ "$count" -eq 0 ]; then
        return 1
    fi

    echo -e "${BOLD}${prompt}${NC}"
    echo ""
    for i in "${!files[@]}"; do
        echo "  $((i + 1))) $(basename "${files[$i]}")"
    done
    echo ""

    while true; do
        read -p "Enter choice [1-${count}]: " choice
        if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -ge 1 ] && [ "$choice" -le "$count" ]; then
            SELECTED_FILE="${files[$((choice - 1))]}"
            return 0
        fi
        echo -e "${RED}Invalid choice. Enter a number between 1 and ${count}.${NC}"
    done
}

# Prompt with a default value
# Usage: prompt_with_default "prompt" "default"
prompt_with_default() {
    local prompt="$1"
    local default="$2"
    local result
    read -p "${prompt} [${default}]: " result
    echo "${result:-$default}"
}

# ============================================================================
# Step 1: Select Connection Properties
# ============================================================================

echo -e "${BLUE}=========================================="
echo " JMeter Interactive Test Runner"
echo -e "==========================================${NC}"
echo ""

echo -e "${BLUE}--- Step 1: Connection Properties ---${NC}"
echo ""

CONN_FILES=($(ls -1 "$CONN_DIR"/*.properties 2>/dev/null | grep -v '\.template$' | sort))

if [ ${#CONN_FILES[@]} -eq 0 ]; then
    echo -e "${YELLOW}No connection properties files found in ${CONN_DIR}/${NC}"
    echo ""
    echo "Create one first by running:"
    echo "  ./create_connection.sh"
    echo ""
    exit 1
fi

select_file "Select connection properties:" "${CONN_FILES[@]}"
CONNECTION_FILE="$SELECTED_FILE"
CONNECTION_BASENAME=$(basename "$CONNECTION_FILE")
echo ""
echo -e "  ${GREEN}Selected: ${CONNECTION_BASENAME}${NC}"
echo ""

# Detect connection type (JDBC vs HTTP) from file content
if grep -q "^mainhost=" "$CONNECTION_FILE" 2>/dev/null; then
    CONN_TYPE="http"
else
    CONN_TYPE="jdbc"
fi

# ============================================================================
# Step 2: Select Test Plan
# ============================================================================

echo -e "${BLUE}--- Step 2: Select Test Plan ---${NC}"
echo ""

if [ "$CONN_TYPE" = "jdbc" ]; then
    echo -e "${BOLD}Select test plan type:${NC}"
    echo ""
    echo "  1) Static Concurrency        - Maintain N concurrent queries"
    echo "  2) Run Once                   - Run each query once with N threads"
    echo "  3) Constant QPS              - Fire queries at N per second"
    echo "  4) Constant QPM              - Fire queries at N per minute"
    echo "  5) QPS with Load Profile     - Variable QPS from CSV schedule"
    echo "  6) QPM with Load Profile     - Variable QPM from CSV schedule"
    echo "  7) Variable Concurrency      - Custom thread spawn schedule"
    echo ""

    while true; do
        read -p "Enter choice [1-7]: " plan_choice
        if [[ "$plan_choice" =~ ^[1-7]$ ]]; then break; fi
        echo -e "${RED}Invalid choice.${NC}"
    done

    case "$plan_choice" in
        1) TEST_PLAN="Test-Plans/Test-Plan-Maintain-static-concurrency.jmx"; PLAN_TYPE="concurrency" ;;
        2) TEST_PLAN="Test-Plans/Test-Plan-Run-Once-static-concurrency.jmx"; PLAN_TYPE="run_once" ;;
        3) TEST_PLAN="Test-Plans/Test-Plan-Constant-QPS-On-Arrivals-JSR-Optimized.jmx"; PLAN_TYPE="qps" ;;
        4) TEST_PLAN="Test-Plans/Test-Plan-Constant-QPM-On-Arrivals.jmx"; PLAN_TYPE="qpm" ;;
        5) TEST_PLAN="Test-Plans/Test-Plan-Fire-QPS-with-load-profile.jmx"; PLAN_TYPE="qps_loadprofile" ;;
        6) TEST_PLAN="Test-Plans/Test-Plan-Fire-QPM-with-load-profile.jmx"; PLAN_TYPE="qpm_loadprofile" ;;
        7) TEST_PLAN="Test-Plans/Test-Plan-Maintain-variable-concurrency-with-load-profile.jmx"; PLAN_TYPE="variable_concurrency" ;;
    esac
else
    echo -e "${BOLD}Select HTTP endpoint test plan:${NC}"
    echo ""
    echo "  1) Static Concurrency (HTTP)  - Maintain N concurrent queries"
    echo "  2) Run Once (HTTP)            - Run each query once with N threads"
    echo "  3) QPS with Load Profile (HTTP) - Variable QPS from CSV schedule"
    echo ""

    while true; do
        read -p "Enter choice [1-3]: " plan_choice
        if [[ "$plan_choice" =~ ^[1-3]$ ]]; then break; fi
        echo -e "${RED}Invalid choice.${NC}"
    done

    case "$plan_choice" in
        1) TEST_PLAN="Test-Plans/Test-Plan-Maintain-static-concurrency-http-endpoint-v2.jmx"; PLAN_TYPE="concurrency" ;;
        2) TEST_PLAN="Test-Plans/Test-Plan-Run-Once-http-endpoint.jmx"; PLAN_TYPE="run_once" ;;
        3) TEST_PLAN="Test-Plans/Test-Plan-Fire-QPS-with-load-profile-http-endpoint_v2.jmx"; PLAN_TYPE="qps_loadprofile" ;;
    esac
fi

echo ""
echo -e "  ${GREEN}Selected: $(basename "$TEST_PLAN")${NC}"
echo -e "  ${DIM}Type: ${PLAN_TYPE}${NC}"
echo ""

# ============================================================================
# Step 3: Test Properties (select existing or create new)
# ============================================================================

echo -e "${BLUE}--- Step 3: Test Properties ---${NC}"
echo ""

# List existing test properties files (exclude templates and CSVs)
TEST_PROPS_FILES=($(ls -1 "$TEST_PROPS_DIR"/*.properties 2>/dev/null | grep -v '\.template$' | sort))

echo -e "${BOLD}Select test properties:${NC}"
echo ""
echo "  N) Create new test properties"

if [ ${#TEST_PROPS_FILES[@]} -gt 0 ]; then
    echo ""
    echo -e "  ${DIM}--- Or select existing ---${NC}"
    for i in "${!TEST_PROPS_FILES[@]}"; do
        echo "  $((i + 1))) $(basename "${TEST_PROPS_FILES[$i]}")"
    done
fi
echo ""

while true; do
    read -p "Enter choice [N or 1-${#TEST_PROPS_FILES[@]}]: " props_choice
    if [[ "$props_choice" =~ ^[Nn]$ ]]; then
        break
    fi
    if [ ${#TEST_PROPS_FILES[@]} -gt 0 ] && [[ "$props_choice" =~ ^[0-9]+$ ]] && [ "$props_choice" -ge 1 ] && [ "$props_choice" -le ${#TEST_PROPS_FILES[@]} ]; then
        TEST_PROPERTIES="${TEST_PROPS_FILES[$((props_choice - 1))]}"
        break
    fi
    echo -e "${RED}Invalid choice. Enter N for new or a number.${NC}"
done

# Create new test properties if selected
if [[ "$props_choice" =~ ^[Nn]$ ]]; then
    echo ""
    echo -e "${BLUE}--- Create Test Properties ---${NC}"
    echo ""

    # Common parameters
    REPORT_PATH="reports"
    COPY_TO_S3=$(prompt_with_default "Copy results to S3? (true/false)" "false")
    S3_REPORT_PATH="${S3_REPORT_PATH:-s3://your-s3-bucket/jmeter-results}"
    RANDOM_ORDER=$(prompt_with_default "Random query order? (true/false)" "false")
    RECYCLE_ON_EOF=$(prompt_with_default "Recycle queries at EOF? (true/false)" "false")
    QUERY_TIMEOUT=$(prompt_with_default "Query timeout (seconds)" "300")
    LIMIT_RESULTSET=$(prompt_with_default "Result set limit" "1000")

    # Plan-specific parameters
    case "$PLAN_TYPE" in
        concurrency)
            CONCURRENT_QUERY_COUNT=$(prompt_with_default "Concurrent query count" "4")
            RAMP_UP_TIME=$(prompt_with_default "Ramp up time (seconds)" "1")
            RAMP_UP_STEPS=$(prompt_with_default "Ramp up steps" "1")
            HOLD_PERIOD=$(prompt_with_default "Hold period (seconds)" "300")
            FILENAME_PREFIX="concurrency_${CONCURRENT_QUERY_COUNT}"
            ;;
        run_once)
            CONCURRENT_QUERY_COUNT=$(prompt_with_default "Number of threads" "1")
            RAMP_UP_TIME="0"
            RAMP_UP_STEPS="1"
            HOLD_PERIOD=$(prompt_with_default "Hold period - set long enough for all queries (seconds)" "300")
            RECYCLE_ON_EOF="false"
            STOP_THREAD_ON_EOF="true"
            FILENAME_PREFIX="run_once_${CONCURRENT_QUERY_COUNT}threads"
            ;;
        qps)
            QPS=$(prompt_with_default "Queries per second (QPS)" "1")
            HOLD_PERIOD=$(prompt_with_default "Hold period (seconds)" "300")
            CONCURRENT_QUERY_COUNT="1"
            RAMP_UP_TIME="0"
            RAMP_UP_STEPS="1"
            FILENAME_PREFIX="qps_${QPS}"
            ;;
        qpm)
            QPM=$(prompt_with_default "Queries per minute (QPM)" "10")
            HOLD_PERIOD=$(prompt_with_default "Hold period (seconds)" "300")
            CONCURRENT_QUERY_COUNT="1"
            RAMP_UP_TIME="0"
            RAMP_UP_STEPS="1"
            FILENAME_PREFIX="qpm_${QPM}"
            ;;
        qps_loadprofile)
            echo ""
            echo -e "${DIM}Available load profiles in ${TEST_PROPS_DIR}/:${NC}"
            LOAD_PROFILES=($(ls -1 "$TEST_PROPS_DIR"/*.csv 2>/dev/null | sort))
            if [ ${#LOAD_PROFILES[@]} -gt 0 ]; then
                for i in "${!LOAD_PROFILES[@]}"; do
                    echo "  $((i + 1))) $(basename "${LOAD_PROFILES[$i]}")"
                done
                echo ""
                read -p "Select load profile [1-${#LOAD_PROFILES[@]}]: " lp_choice
                LOAD_PROFILE="${LOAD_PROFILES[$((lp_choice - 1))]}"
            else
                read -p "Load profile CSV path: " LOAD_PROFILE
            fi
            HOLD_PERIOD=$(prompt_with_default "Hold period (seconds)" "600")
            CONCURRENT_QUERY_COUNT="1"
            RAMP_UP_TIME="0"
            RAMP_UP_STEPS="1"
            RECYCLE_ON_EOF="true"
            FILENAME_PREFIX="qps_loadprofile"
            ;;
        qpm_loadprofile)
            echo ""
            echo -e "${DIM}Available load profiles in ${TEST_PROPS_DIR}/:${NC}"
            LOAD_PROFILES=($(ls -1 "$TEST_PROPS_DIR"/*.csv 2>/dev/null | sort))
            if [ ${#LOAD_PROFILES[@]} -gt 0 ]; then
                for i in "${!LOAD_PROFILES[@]}"; do
                    echo "  $((i + 1))) $(basename "${LOAD_PROFILES[$i]}")"
                done
                echo ""
                read -p "Select load profile [1-${#LOAD_PROFILES[@]}]: " lp_choice
                LOAD_PROFILE="${LOAD_PROFILES[$((lp_choice - 1))]}"
            else
                read -p "Load profile CSV path: " LOAD_PROFILE
            fi
            HOLD_PERIOD=$(prompt_with_default "Hold period (seconds)" "600")
            CONCURRENT_QUERY_COUNT="1"
            RAMP_UP_TIME="0"
            RAMP_UP_STEPS="1"
            RECYCLE_ON_EOF="true"
            FILENAME_PREFIX="qpm_loadprofile"
            ;;
        variable_concurrency)
            echo ""
            echo "Enter thread spawn schedule using UTG format:"
            echo -e "${DIM}  Format: spawn(threads, initialDelay, startupTime, holdFor, shutdownTime)${NC}"
            echo -e "${DIM}  Example: spawn(4,0s,0s,80s,0s) spawn(16,0s,0s,80s,0s)${NC}"
            echo ""
            read -p "Thread schedule: " THREADS_SCHEDULE
            HOLD_PERIOD=$(prompt_with_default "Hold period (seconds)" "600")
            CONCURRENT_QUERY_COUNT="1"
            RAMP_UP_TIME="0"
            RAMP_UP_STEPS="1"
            RECYCLE_ON_EOF="true"
            FILENAME_PREFIX="variable_concurrency"
            ;;
    esac

    # Generate filename
    PROPS_FILENAME="${FILENAME_PREFIX}_test.properties"
    TEST_PROPERTIES="${TEST_PROPS_DIR}/${PROPS_FILENAME}"

    # Check if file exists
    if [ -f "$TEST_PROPERTIES" ]; then
        echo ""
        echo -e "${YELLOW}File already exists: ${PROPS_FILENAME}${NC}"
        read -p "Overwrite? (y/n) [y]: " overwrite
        overwrite=${overwrite:-y}
        if [[ ! "$overwrite" =~ ^[Yy]$ ]]; then
            echo "Enter a different name (without .properties extension):"
            read -p "Filename: " custom_name
            PROPS_FILENAME="${custom_name}.properties"
            TEST_PROPERTIES="${TEST_PROPS_DIR}/${PROPS_FILENAME}"
        fi
    fi

    # Write test properties file
    {
        echo "# JMeter Test Properties"
        echo "# Plan type: ${PLAN_TYPE}"
        echo "# Created: $(date +%Y-%m-%d)"
        echo ""
        echo "JMETER_HOME="
        echo ""
        echo "REPORT_PATH=${REPORT_PATH}"
        echo "COPY_TO_S3=${COPY_TO_S3}"
        echo "S3_REPORT_PATH=${S3_REPORT_PATH}"
        echo ""
        echo "CONCURRENT_QUERY_COUNT=${CONCURRENT_QUERY_COUNT}"
        echo "RAMP_UP_TIME=${RAMP_UP_TIME}"
        echo "RAMP_UP_STEPS=${RAMP_UP_STEPS}"
        echo "HOLD_PERIOD=${HOLD_PERIOD}"

        if [ -n "${QPM:-}" ]; then
            echo "QPM=${QPM}"
        fi
        if [ -n "${QPS:-}" ]; then
            echo "QPS=${QPS}"
        fi
        if [ -n "${LOAD_PROFILE:-}" ]; then
            echo "LOAD_PROFILE=${LOAD_PROFILE}"
        fi
        if [ -n "${THREADS_SCHEDULE:-}" ]; then
            echo "threads_schedule=${THREADS_SCHEDULE}"
        fi
        if [ -n "${STOP_THREAD_ON_EOF:-}" ]; then
            echo "STOP_THREAD_ON_EOF=${STOP_THREAD_ON_EOF}"
        fi

        echo ""
        echo "RANDOM_ORDER=${RANDOM_ORDER}"
        echo "RECYCLE_ON_EOF=${RECYCLE_ON_EOF}"
        echo ""
        echo "QUERY_TIMEOUT=${QUERY_TIMEOUT}"
        echo "LIMIT_RESULTSET=${LIMIT_RESULTSET}"
        echo "MAX_CONCURRANCY=900"
    } > "$TEST_PROPERTIES"

    echo ""
    echo -e "  ${GREEN}Created: ${PROPS_FILENAME}${NC}"
fi

echo ""
echo -e "  ${GREEN}Using: $(basename "$TEST_PROPERTIES")${NC}"
echo ""

# ============================================================================
# Step 4: Select Query Data File
# ============================================================================

echo -e "${BLUE}--- Step 4: Query Data File (CSV) ---${NC}"
echo ""

DATA_FILES=($(ls -1 "$DATA_DIR"/*.csv 2>/dev/null | sort))

if [ ${#DATA_FILES[@]} -eq 0 ]; then
    echo -e "${RED}No CSV data files found in ${DATA_DIR}/${NC}"
    exit 1
fi

select_file "Select query data file:" "${DATA_FILES[@]}"
QUERY_FILE="$SELECTED_FILE"
echo ""
echo -e "  ${GREEN}Selected: $(basename "$QUERY_FILE")${NC}"
echo ""

# ============================================================================
# Step 5: Metadata File (optional, for S3 upload)
# ============================================================================

echo -e "${BLUE}--- Step 5: Metadata File (optional) ---${NC}"
echo ""

METADATA_FILES=($(ls -1 "$METADATA_DIR"/*.txt 2>/dev/null | sort))

echo -e "${BOLD}Select metadata file:${NC}"
echo ""
echo "  0) Skip (no metadata)"
if [ ${#METADATA_FILES[@]} -gt 0 ]; then
    for i in "${!METADATA_FILES[@]}"; do
        echo "  $((i + 1))) $(basename "${METADATA_FILES[$i]}")"
    done
fi
echo ""

while true; do
    read -p "Enter choice [0-${#METADATA_FILES[@]}]: " meta_choice
    if [[ "$meta_choice" =~ ^[0-9]+$ ]] && [ "$meta_choice" -ge 0 ] && [ "$meta_choice" -le ${#METADATA_FILES[@]} ]; then
        break
    fi
    echo -e "${RED}Invalid choice.${NC}"
done

METADATA_FILE=""
if [ "$meta_choice" -gt 0 ]; then
    METADATA_FILE="${METADATA_FILES[$((meta_choice - 1))]}"
    echo -e "  ${GREEN}Selected: $(basename "$METADATA_FILE")${NC}"
else
    echo -e "  ${DIM}Skipped${NC}"
fi
echo ""

# ============================================================================
# Step 6: Review and Run
# ============================================================================

echo -e "${BLUE}=========================================="
echo " Test Configuration Summary"
echo -e "==========================================${NC}"
echo ""
echo "  Connection:      $(basename "$CONNECTION_FILE")"
echo "  Test Plan:       $(basename "$TEST_PLAN")"
echo "  Test Properties: $(basename "$TEST_PROPERTIES")"
echo "  Query File:      $(basename "$QUERY_FILE")"
if [ -n "$METADATA_FILE" ]; then
    echo "  Metadata:        $(basename "$METADATA_FILE")"
fi
echo ""

# Show key test parameters from properties file
echo -e "${DIM}Key parameters from test properties:${NC}"
grep -E "^(CONCURRENT_QUERY_COUNT|QPS|QPM|HOLD_PERIOD|COPY_TO_S3|RECYCLE_ON_EOF)=" "$TEST_PROPERTIES" 2>/dev/null | while read -r line; do
    echo "  $line"
done
echo ""

# Source metadata if present (to get COPY_TO_S3 override, ENGINE, etc.)
if [ -n "$METADATA_FILE" ]; then
    echo -e "${DIM}Metadata overrides:${NC}"
    grep -E "^(ENGINE|COPY_TO_S3|S3_BASE_PATH|BENCHMARK_TYPE)=" "$METADATA_FILE" 2>/dev/null | while read -r line; do
        echo "  $line"
    done
    echo ""
fi

read -p "Run test? (y/n): " confirm
if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
    echo "Cancelled."
    exit 0
fi

echo ""

# ============================================================================
# Build and run JMeter command
# ============================================================================

# Source metadata for runtime variables if present
if [ -n "$METADATA_FILE" ]; then
    source "$METADATA_FILE"
fi

# Source test properties for runtime variables
source "$TEST_PROPERTIES"

# Determine JMETER_HOME
if [ -z "$JMETER_HOME" ]; then
    # Try to find JMeter in common locations
    if command -v jmeter &>/dev/null; then
        JMETER_BIN=$(which jmeter)
        JMETER_HOME=$(dirname "$(dirname "$JMETER_BIN")")
    elif [ -d "/opt/homebrew/Cellar/jmeter" ]; then
        JMETER_HOME=$(ls -d /opt/homebrew/Cellar/jmeter/*/libexec 2>/dev/null | head -1)
    elif [ -d "/usr/local/Cellar/jmeter" ]; then
        JMETER_HOME=$(ls -d /usr/local/Cellar/jmeter/*/libexec 2>/dev/null | head -1)
    fi
fi

if [ -z "$JMETER_HOME" ] || [ ! -f "$JMETER_HOME/bin/jmeter" ]; then
    echo -e "${RED}Error: Cannot find JMeter installation.${NC}"
    echo "Set JMETER_HOME in your test properties or install JMeter."
    echo "  brew install jmeter"
    exit 1
fi

echo -e "${GREEN}Using JMeter: ${JMETER_HOME}${NC}"
echo ""

# Generate report directory with timestamp
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
REPORT_DIR="${REPORT_PATH:-reports}/${TIMESTAMP}"
mkdir -p "$REPORT_DIR"

# Build JMeter command
JMETER_CMD="$JMETER_HOME/bin/jmeter -n"
JMETER_CMD+=" -t $TEST_PLAN"
JMETER_CMD+=" -l ${REPORT_DIR}/JmeterResultFile.csv"
JMETER_CMD+=" -e -o ${REPORT_DIR}/dashboard"

# Add all properties as JMeter parameters
JMETER_CMD+=" -JCONNECTION_PROPERTIES=$CONNECTION_FILE"
JMETER_CMD+=" -JQUERY_PATH=$QUERY_FILE"

# Pass test properties as JMeter -J parameters
while IFS='=' read -r key value; do
    # Skip comments, empty lines, and JMETER_HOME
    [[ "$key" =~ ^[[:space:]]*# ]] && continue
    [[ -z "$key" ]] && continue
    [[ "$key" == "JMETER_HOME" ]] && continue
    # Trim whitespace
    key=$(echo "$key" | xargs)
    value=$(echo "$value" | xargs)
    [ -z "$key" ] && continue
    JMETER_CMD+=" -J${key}=${value}"
done < "$TEST_PROPERTIES"

# Override QUERY_PATH with user selection
JMETER_CMD+=" -JQUERY_PATH=$QUERY_FILE"

echo -e "${BLUE}Running JMeter...${NC}"
echo -e "${DIM}${JMETER_CMD}${NC}"
echo ""

# Run JMeter
eval "$JMETER_CMD"

echo ""
echo -e "${GREEN}=========================================="
echo " Test Complete!"
echo -e "==========================================${NC}"
echo ""
echo "  Results: ${REPORT_DIR}/"
echo "  Dashboard: ${REPORT_DIR}/dashboard/index.html"
echo ""

# Copy to S3 if enabled
if [ "${COPY_TO_S3:-false}" = "true" ] && [ -n "${S3_BASE_PATH:-}" ]; then
    echo "Uploading results to S3..."
    # Build S3 path from metadata
    ENGINE_VAL="${ENGINE:-unknown}"
    CLUSTER_SIZE_VAL="${CLUSTER_SIZE:-unknown}"
    BENCHMARK_VAL="${BENCHMARK_TYPE:-unknown}"
    RUN_TYPE_VAL="run_type=${PLAN_TYPE}"
    S3_DEST="${S3_BASE_PATH}/engine=${ENGINE_VAL}/cluster_size=${CLUSTER_SIZE_VAL}/benchmark=${BENCHMARK_VAL}/${RUN_TYPE_VAL}/run_id=${TIMESTAMP}/"

    echo "  S3 path: ${S3_DEST}"
    aws s3 cp "${REPORT_DIR}/" "${S3_DEST}" --recursive
    echo -e "  ${GREEN}Uploaded to S3${NC}"
fi

echo ""
