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

CONN_FILES=($(ls -1 connection_properties/*.properties 2>/dev/null | grep -v '\.template$' || true))

if [ ${#CONN_FILES[@]} -eq 0 ]; then
    echo -e "${YELLOW}No connection files found.${NC}"
    read -p "Create one now? (y/n): " create_conn
    if [[ "$create_conn" =~ ^[Yy]$ ]]; then
        "${PROJECT_ROOT}/create_connection.sh"
        # Re-scan after creation
        CONN_FILES=($(ls -1 connection_properties/*.properties 2>/dev/null | grep -v '\.template$' || true))
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
read -p "Select connection [1-${#CONN_FILES[@]}]: " conn_idx

if [[ ! "$conn_idx" =~ ^[0-9]+$ ]] || [ "$conn_idx" -lt 1 ] || [ "$conn_idx" -gt "${#CONN_FILES[@]}" ]; then
    echo -e "${RED}Invalid selection${NC}"
    exit 1
fi
CONNECTION_FILE="${CONN_FILES[$((conn_idx-1))]}"
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
if [ "$CONN_TYPE" = "jdbc" ]; then
    echo "  JDBC test plans:"
    echo ""
    echo "  1) Static Concurrency        — fixed number of concurrent queries"
    echo "  2) Run Once                   — each query runs exactly once"
    echo "  3) Constant QPS              — maintain steady queries per second"
    echo "  4) Constant QPM              — maintain steady queries per minute"
    echo "  5) QPS with Load Profile     — QPS varies over time (CSV schedule)"
    echo "  6) Variable Concurrency      — concurrency varies over time (CSV schedule)"
    echo "  7) Other                     — show all available test plans"
    echo ""
    read -p "Select test type [1-7]: " plan_choice

    case "$plan_choice" in
        1) TEST_PLAN="Test-Plans/Test-Plan-Maintain-static-concurrency.jmx" ;;
        2) TEST_PLAN="Test-Plans/Test-Plan-Run-Once-static-concurrency.jmx" ;;
        3) TEST_PLAN="Test-Plans/Test-Plan-Constant-QPS-On-Arrivals-JSR-Optimized.jmx" ;;
        4) TEST_PLAN="Test-Plans/Test-Plan-Constant-QPM-On-Arrivals.jmx" ;;
        5) TEST_PLAN="Test-Plans/Test-Plan-Fire-QPS-with-load-profile.jmx" ;;
        6) TEST_PLAN="Test-Plans/Test-Plan-Maintain-variable-concurrency-with-load-profile.jmx" ;;
        7) ;; # handled below
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
echo -e "  ${DIM}(type: ${PLAN_TYPE})${NC}"
echo ""

# ============================================================================
# Step 3: Select query data file
# ============================================================================

echo -e "${BOLD}Step 3: Select query data file${NC}"
echo ""

QUERY_FILES=($(ls -1 data_files/*.csv 2>/dev/null || true))

if [ ${#QUERY_FILES[@]} -eq 0 ]; then
    echo -e "${RED}No CSV query files found in data_files/${NC}"
    exit 1
fi

for i in "${!QUERY_FILES[@]}"; do
    # Show line count as hint
    lines=$(wc -l < "${QUERY_FILES[$i]}" | tr -d ' ')
    echo "  $((i+1))) $(basename "${QUERY_FILES[$i]}") (${lines} queries)"
done
echo ""
read -p "Select query file [1-${#QUERY_FILES[@]}]: " query_idx

if [[ ! "$query_idx" =~ ^[0-9]+$ ]] || [ "$query_idx" -lt 1 ] || [ "$query_idx" -gt "${#QUERY_FILES[@]}" ]; then
    echo -e "${RED}Invalid selection${NC}"
    exit 1
fi
QUERY_FILE="${QUERY_FILES[$((query_idx-1))]}"
echo -e "  ${GREEN}Selected: $(basename "$QUERY_FILE")${NC}"
echo ""

# ============================================================================
# Step 4: Test parameters
# ============================================================================

echo -e "${BOLD}Step 4: Test parameters${NC}"
echo ""

# Parameters depend on test plan type
case "$PLAN_TYPE" in
    concurrency)
        read -p "Concurrent queries [4]: " CONCURRENT_QUERY_COUNT
        CONCURRENT_QUERY_COUNT=${CONCURRENT_QUERY_COUNT:-4}
        read -p "Hold period in seconds [300]: " HOLD_PERIOD
        HOLD_PERIOD=${HOLD_PERIOD:-300}
        read -p "Random query order (true/false) [false]: " RANDOM_ORDER
        RANDOM_ORDER=${RANDOM_ORDER:-false}
        read -p "Recycle queries on EOF (true/false) [true]: " RECYCLE_ON_EOF
        RECYCLE_ON_EOF=${RECYCLE_ON_EOF:-true}
        ;;
    run_once)
        read -p "Concurrent queries [1]: " CONCURRENT_QUERY_COUNT
        CONCURRENT_QUERY_COUNT=${CONCURRENT_QUERY_COUNT:-1}
        HOLD_PERIOD=0
        RANDOM_ORDER=false
        RECYCLE_ON_EOF=false
        ;;
    qps)
        read -p "Queries per second [5]: " QPS
        QPS=${QPS:-5}
        read -p "Hold period in seconds [300]: " HOLD_PERIOD
        HOLD_PERIOD=${HOLD_PERIOD:-300}
        read -p "Random query order (true/false) [false]: " RANDOM_ORDER
        RANDOM_ORDER=${RANDOM_ORDER:-false}
        read -p "Recycle queries on EOF (true/false) [true]: " RECYCLE_ON_EOF
        RECYCLE_ON_EOF=${RECYCLE_ON_EOF:-true}
        ;;
    qpm)
        read -p "Queries per minute [10]: " QPM
        QPM=${QPM:-10}
        read -p "Hold period in seconds [300]: " HOLD_PERIOD
        HOLD_PERIOD=${HOLD_PERIOD:-300}
        read -p "Random query order (true/false) [false]: " RANDOM_ORDER
        RANDOM_ORDER=${RANDOM_ORDER:-false}
        read -p "Recycle queries on EOF (true/false) [true]: " RECYCLE_ON_EOF
        RECYCLE_ON_EOF=${RECYCLE_ON_EOF:-true}
        ;;
    qps_profile|qpm_profile)
        read -p "Load profile CSV [test_properties/load_profile.csv]: " LOAD_PROFILE
        LOAD_PROFILE=${LOAD_PROFILE:-test_properties/load_profile.csv}
        if [ ! -f "$LOAD_PROFILE" ]; then
            echo -e "${YELLOW}Warning: Load profile not found: ${LOAD_PROFILE}${NC}"
        fi
        read -p "Hold period in seconds [300]: " HOLD_PERIOD
        HOLD_PERIOD=${HOLD_PERIOD:-300}
        read -p "Random query order (true/false) [false]: " RANDOM_ORDER
        RANDOM_ORDER=${RANDOM_ORDER:-false}
        RECYCLE_ON_EOF=true
        ;;
    var_concurrency)
        read -p "Load profile CSV [test_properties/load_profile.csv]: " LOAD_PROFILE
        LOAD_PROFILE=${LOAD_PROFILE:-test_properties/load_profile.csv}
        if [ ! -f "$LOAD_PROFILE" ]; then
            echo -e "${YELLOW}Warning: Load profile not found: ${LOAD_PROFILE}${NC}"
        fi
        read -p "Hold period in seconds [300]: " HOLD_PERIOD
        HOLD_PERIOD=${HOLD_PERIOD:-300}
        read -p "Random query order (true/false) [false]: " RANDOM_ORDER
        RANDOM_ORDER=${RANDOM_ORDER:-false}
        RECYCLE_ON_EOF=true
        ;;
esac

echo ""

# ============================================================================
# Step 5: Optional metadata (for S3 upload)
# ============================================================================

echo -e "${BOLD}Step 5: Metadata file (optional — for S3 upload)${NC}"
echo ""

META_FILES=($(ls -1 metadata_files/*.txt 2>/dev/null || true))

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
    echo "CONNECTION_FILE=${CONNECTION_FILE}"
    echo "TEST_PLAN=${TEST_PLAN}"
    echo "QUERY_FILE=${QUERY_FILE}"

    if [ -n "$METADATA_FILE" ]; then
        echo "METADATA_FILE=${METADATA_FILE}"
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
            echo "LOAD_PROFILE=${LOAD_PROFILE}"
            echo "HOLD_PERIOD=${HOLD_PERIOD}"
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
echo "  CONCURRENT_QUERY_COUNT=8 ./run_test.sh ${CONFIG_FILE}"
echo ""
echo -e "${BOLD}Or use env vars directly (copy-paste):${NC}"
echo "  export CONNECTION_FILE=${CONNECTION_FILE}"
echo "  export TEST_PLAN=${TEST_PLAN}"
echo "  export QUERY_FILE=${QUERY_FILE}"
case "$PLAN_TYPE" in
    concurrency)
        echo "  export CONCURRENT_QUERY_COUNT=${CONCURRENT_QUERY_COUNT}"
        ;;
    run_once)
        echo "  export CONCURRENT_QUERY_COUNT=${CONCURRENT_QUERY_COUNT}"
        ;;
    qps)
        echo "  export QPS=${QPS}"
        ;;
    qpm)
        echo "  export QPM=${QPM}"
        ;;
    qps_profile|qpm_profile|var_concurrency)
        echo "  export LOAD_PROFILE=${LOAD_PROFILE}"
        ;;
esac
[ "${HOLD_PERIOD:-0}" != "0" ] && echo "  export HOLD_PERIOD=${HOLD_PERIOD}"
echo "  ./run_test.sh"
echo ""
