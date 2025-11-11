#!/bin/bash
# Run all concurrency tests matching S3 path structure
# Usage: ./run_all_concurrency.sh <engine> <cluster_size> <benchmark>
#
# Arguments match S3 path: s3://bucket/engine=X/cluster_size=Y/benchmark=Z/
#
# Examples:
#   ./run_all_concurrency.sh e6data S-2x2 tpcds_29_1tb
#   ./run_all_concurrency.sh dbr S-4x4 tpcds_29_1tb
#   ./run_all_concurrency.sh e6data M-4x4 tpcds_51_1tb
#
# Concurrency levels: 1, 2, 4, 8, 12, 16

set -e

# Check arguments
if [ $# -lt 3 ]; then
    echo "Error: engine, cluster_size, and benchmark arguments required"
    echo ""
    echo "Usage: $0 <engine> <cluster_size> <benchmark> [cluster] [test_plan_file]"
    echo ""
    echo "Required Parameters:"
    echo "  engine        - Database engine (e6data, dbr)"
    echo "  cluster_size  - Cluster size (S-2x2, M-4x4, XS-1x1, S-4x4, S-1x1)"
    echo "  benchmark     - Benchmark name (tpcds_29_1tb, tpcds_51_1tb)"
    echo ""
    echo "Optional Parameters:"
    echo "  cluster       - Cluster identifier for connection properties (default: default)"
    echo "                  Connection file: connection_properties/{engine}_{cluster}_connection.properties"
    echo "  test_plan_file - Override test plan (default: uses test plan from test input file)"
    echo ""
    echo "Examples:"
    echo "  # Simple run with defaults (uses {engine}_default_connection.properties)"
    echo "  $0 e6data S-2x2 tpcds_29_1tb"
    echo ""
    echo "  # Run on specific cluster"
    echo "  $0 e6data S-2x2 tpcds_29_1tb demo-graviton"
    echo ""
    echo "  # Run with custom test plan"
    echo "  $0 dbr S-4x4 tpcds_29_1tb default Test-Plan-Sequential.jmx"
    echo ""
    echo "  # Both custom cluster and test plan"
    echo "  $0 e6data S-2x2 tpcds_29_1tb prod-cluster Test-Plan-Stress-Test.jmx"
    echo ""
    echo "Arguments match S3 structure:"
    echo "  s3://e6-jmeter/jmeter-results/engine=<ARG1>/cluster_size=<ARG2>/benchmark=<ARG3>/"
    echo ""
    echo "Note: Test input files use template placeholders substituted at runtime:"
    echo "      {ENGINE}, {CLUSTER_SIZE}, {CONCURRENCY}, {CLUSTER}, {BENCHMARK}"
    exit 1
fi

# Configuration
ENGINE="$1"
CLUSTER_SIZE="$2"
BENCHMARK="$3"
CLUSTER="${4:-default}"  # Default: "default"
TEST_PLAN_OVERRIDE="${5:-}"  # Empty means use test input file's test plan
CONCURRENCY_LEVELS=(1 2 4 8 12 16)
S3_BASE_PATH="s3://e6-jmeter/jmeter-results"

# Validate engine
if [[ ! "$ENGINE" =~ ^(e6data|dbr)$ ]]; then
    echo "Error: Invalid engine '$ENGINE'"
    echo "Valid engines: e6data, dbr"
    exit 1
fi

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Navigate to project root
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

# Normalize cluster size for file paths (lowercase with hyphens)
CLUSTER_SIZE_NORMALIZED=$(echo "$CLUSTER_SIZE" | tr '[:upper:]' '[:lower:]')

# Set engine display name
ENGINE_DISPLAY="$ENGINE"
if [ "$ENGINE" = "e6data" ]; then
    ENGINE_DISPLAY="e6data"
elif [ "$ENGINE" = "dbr" ]; then
    ENGINE_DISPLAY="DBR"
fi

# Display configuration
echo -e "${BLUE}=========================================="
echo "${ENGINE_DISPLAY} ${CLUSTER_SIZE} Cluster - All Concurrency Tests"
echo -e "==========================================${NC}"
echo ""
echo "Configuration:"
echo "   - Engine: ${ENGINE}"
echo "   - Cluster: ${CLUSTER}"
echo "   - Size: ${CLUSTER_SIZE}"
echo "   - Connection: connection_properties/${ENGINE}_${CLUSTER}_connection.properties"
if [ "$ENGINE" = "e6data" ]; then
    if [ "$CLUSTER_SIZE" = "S-2x2" ]; then
        echo "   - 60 cores (2 executors × 30 cores) - Matches DBR S-2x2"
    elif [ "$CLUSTER_SIZE" = "M-4x4" ]; then
        echo "   - 120 cores (4 executors × 30 cores) - Matches DBR S-4x4"
    fi
elif [ "$ENGINE" = "dbr" ]; then
    if [ "$CLUSTER_SIZE" = "S-2x2" ]; then
        echo "   - ~60 cores (Small warehouse, 2 min/max clusters) - Matches E6Data S-2x2"
    elif [ "$CLUSTER_SIZE" = "S-4x4" ]; then
        echo "   - ~120 cores (Small warehouse, 4 min/max clusters) - Matches E6Data M-4x4"
    fi
fi
echo "   - Benchmark: ${BENCHMARK}"
echo ""
echo "Tests to run:"
for concurrency in "${CONCURRENCY_LEVELS[@]}"; do
    echo "  - Concurrency: ${concurrency} threads"
done
echo ""

# DBR warehouse configuration reminder
if [ "$ENGINE" = "dbr" ]; then
    echo "⚠️  IMPORTANT: Verify DBR warehouse configuration:"
    if [ "$CLUSTER_SIZE" == "S-4x4" ]; then
        echo "   - Warehouse Size: Small"
        echo "   - Min Clusters: 4"
        echo "   - Max Clusters: 4"
    elif [ "$CLUSTER_SIZE" == "S-2x2" ]; then
        echo "   - Warehouse Size: Small"
        echo "   - Min Clusters: 2"
        echo "   - Max Clusters: 2"
    fi
    echo ""
fi

# Check if test input template file exists
echo "Checking for test input template file..."
TEST_INPUT_TEMPLATE="test_inputs/${ENGINE}_${CLUSTER_SIZE_NORMALIZED}_${BENCHMARK}_template.txt"
if [ ! -f "$TEST_INPUT_TEMPLATE" ]; then
    echo ""
    echo -e "${YELLOW}==========================================="
    echo "ERROR: Test input template file not found!"
    echo -e "==========================================${NC}"
    echo ""
    echo "Expected: $TEST_INPUT_TEMPLATE"
    echo ""
    echo "Available template files:"
    ls -1 test_inputs/*_template.txt 2>/dev/null || echo "  (none found)"
    echo ""
    exit 1
else
    echo "  ✓ Found: $TEST_INPUT_TEMPLATE"
fi

# Validate connection file exists
CONNECTION_FILE="${ENGINE}_${CLUSTER}_connection.properties"
if [ ! -f "connection_properties/$CONNECTION_FILE" ]; then
    echo ""
    echo -e "${YELLOW}=========================================="
    echo "ERROR: Connection file not found!"
    echo -e "==========================================${NC}"
    echo ""
    echo "Expected: connection_properties/$CONNECTION_FILE"
    echo ""
    echo "Available connection files for $ENGINE:"
    ls -1 connection_properties/${ENGINE}_*_connection.properties 2>/dev/null || echo "  (none found)"
    echo ""
    echo "Tip: Create the connection file or use an existing cluster identifier:"
    echo "     $0 $ENGINE $CLUSTER_SIZE $BENCHMARK <cluster_name>"
    exit 1
fi

# Extract info from test input template file for display
QUERY_FILE_TEMPLATE=$(sed -n '5p' "$TEST_INPUT_TEMPLATE")
CONNECTION_FILE_TEMPLATE=$(sed -n '4p' "$TEST_INPUT_TEMPLATE")
TEST_PROPERTIES_FILE_TEMPLATE=$(sed -n '3p' "$TEST_INPUT_TEMPLATE")
TEST_PLAN_FILE=$(sed -n '2p' "$TEST_INPUT_TEMPLATE")

# Substitute placeholders for display
QUERY_FILE=$(echo "$QUERY_FILE_TEMPLATE" | sed "s/{ENGINE}/$ENGINE/g" | sed "s/{BENCHMARK}/$BENCHMARK/g")
TEST_PROPERTIES_FILE=$(echo "$TEST_PROPERTIES_FILE_TEMPLATE" | sed "s/{CONCURRENCY}/1/g")
CONNECTION_FILE=$(echo "$CONNECTION_FILE_TEMPLATE" | sed "s/{ENGINE}/$ENGINE/g" | sed "s/{CLUSTER}/$CLUSTER/g")

# Override test plan if specified
if [ -n "$TEST_PLAN_OVERRIDE" ]; then
    TEST_PLAN_FILE="$TEST_PLAN_OVERRIDE"
fi

echo ""
echo -e "${GREEN}=========================================="
echo "Test Run Summary"
echo -e "==========================================${NC}"
echo "Engine: ${ENGINE}"
echo "Cluster Size: ${CLUSTER_SIZE}"
echo "Benchmark: ${BENCHMARK}"
echo "Query File: ${QUERY_FILE}"
echo "Connection: ${CONNECTION_FILE}"
echo "Test Properties: ${TEST_PROPERTIES_FILE}"
echo "Test Plan: ${TEST_PLAN_FILE}"
echo "Concurrency Levels: ${CONCURRENCY_LEVELS[@]}"
echo ""
echo "S3 Results Path:"
echo "  ${S3_BASE_PATH}/engine=${ENGINE}/cluster_size=${CLUSTER_SIZE}/benchmark=${BENCHMARK}/"
echo ""
read -p "Press Enter to start tests or Ctrl+C to cancel..."

# Create log directory
LOG_DIR="/tmp/jmeter_test_logs"
mkdir -p "$LOG_DIR"

# Run all concurrency tests
for concurrency in "${CONCURRENCY_LEVELS[@]}"; do
    # Read templates from test input template file
    METADATA_TEMPLATE=$(sed -n '1p' "$TEST_INPUT_TEMPLATE")
    TEST_PLAN_TEMPLATE=$(sed -n '2p' "$TEST_INPUT_TEMPLATE")
    TEST_PROPS_TEMPLATE=$(sed -n '3p' "$TEST_INPUT_TEMPLATE")
    CONNECTION_TEMPLATE=$(sed -n '4p' "$TEST_INPUT_TEMPLATE")
    QUERY_TEMPLATE=$(sed -n '5p' "$TEST_INPUT_TEMPLATE")

    # Substitute placeholders
    METADATA_FILE=$(echo "$METADATA_TEMPLATE" | \
        sed "s/{ENGINE}/$ENGINE/g" | \
        sed "s/{CLUSTER_SIZE}/$CLUSTER_SIZE_NORMALIZED/g")

    TEST_PROPS=$(echo "$TEST_PROPS_TEMPLATE" | \
        sed "s/{CONCURRENCY}/$concurrency/g")

    CONNECTION_FILE=$(echo "$CONNECTION_TEMPLATE" | \
        sed "s/{ENGINE}/$ENGINE/g" | \
        sed "s/{CLUSTER}/$CLUSTER/g")

    QUERY_FILE=$(echo "$QUERY_TEMPLATE" | \
        sed "s/{ENGINE}/$ENGINE/g" | \
        sed "s/{BENCHMARK}/$BENCHMARK/g")

    # Use override or template for test plan
    if [ -n "$TEST_PLAN_OVERRIDE" ]; then
        TEST_PLAN="$TEST_PLAN_OVERRIDE"
    else
        TEST_PLAN="$TEST_PLAN_TEMPLATE"
    fi

    # Extract metadata for logging
    METADATA_PATH="$METADATA_FILE"
    INSTANCE_TYPE="unknown"
    if [ -f "$METADATA_PATH" ]; then
        INSTANCE_TYPE=$(grep -o '"instance_type"[[:space:]]*:[[:space:]]*"[^"]*"' "$METADATA_PATH" | cut -d'"' -f4)
    fi

    QUERY_BASENAME=$(basename "$QUERY_FILE" .csv)
    LOG_FILE="$LOG_DIR/${ENGINE}_${CLUSTER_SIZE_NORMALIZED}_${INSTANCE_TYPE}_${QUERY_BASENAME}_concurrency${concurrency}_$(date +%Y%m%d_%H%M%S).log"

    echo ""
    echo -e "${BLUE}=========================================="
    echo "Running: ${ENGINE_DISPLAY} ${CLUSTER_SIZE} - Concurrency ${concurrency}"
    echo -e "==========================================${NC}"
    echo "Test input template: $TEST_INPUT_TEMPLATE"
    echo "Resolved files:"
    echo "  - Metadata: $METADATA_FILE"
    echo "  - Test Plan: $TEST_PLAN"
    echo "  - Properties: $TEST_PROPS"
    echo "  - Connection: connection_properties/$CONNECTION_FILE"
    echo "  - Queries: $QUERY_FILE"
    echo "Log file: $LOG_FILE"
    echo ""

    # Create temporary resolved test input file
    TEMP_TEST_INPUT="/tmp/test_input_resolved_${concurrency}.txt"
    cat > "$TEMP_TEST_INPUT" << EOF
$METADATA_FILE
$TEST_PLAN
$TEST_PROPS
$CONNECTION_FILE
$QUERY_FILE
EOF

    # Run test with resolved input
    if ./run_jmeter_tests_interactive.sh < "$TEMP_TEST_INPUT" 2>&1 | tee "$LOG_FILE"; then
        echo -e "${GREEN}✓ Test completed: Concurrency ${concurrency}${NC}"
    else
        echo -e "${YELLOW}⚠ Test failed or interrupted: Concurrency ${concurrency}${NC}"
        echo "Check log: $LOG_FILE"
        read -p "Continue with next test? (y/n): " continue_choice
        if [[ ! "$continue_choice" =~ ^[Yy]$ ]]; then
            echo "Exiting..."
            exit 1
        fi
    fi

    # Cleanup temporary file
    rm -f "$TEMP_TEST_INPUT"

    # Wait between tests
    # Get last element in a shell-compatible way
    LAST_CONCURRENCY=""
    for c in "${CONCURRENCY_LEVELS[@]}"; do LAST_CONCURRENCY=$c; done
    if [[ "$concurrency" != "$LAST_CONCURRENCY" ]]; then
        echo ""
        echo "Waiting 30 seconds before next test..."
        sleep 30
    fi
done

echo ""
echo -e "${GREEN}=========================================="
echo "✓ All ${ENGINE_DISPLAY} ${CLUSTER_SIZE} concurrency tests completed!"
echo -e "==========================================${NC}"
echo ""
echo "Logs saved in: $LOG_DIR"
echo ""
echo "Next steps:"
echo "  1. Check S3 for uploaded results:"
echo "     ${S3_BASE_PATH}/engine=${ENGINE}/cluster_size=${CLUSTER_SIZE}/benchmark=${BENCHMARK}/run_type=concurrency_X/run_id=YYYYMMDD-HHMMSS/"
if [ "$ENGINE" = "e6data" ]; then
    echo "  2. Compare with DBR results (if applicable)"
elif [ "$ENGINE" = "dbr" ]; then
    echo "  2. Compare with E6Data results (if applicable)"
fi
echo "  3. Generate comparison report using utilities/compare_* scripts"
echo ""
