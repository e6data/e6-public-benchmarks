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
    echo "Usage: $0 <engine> <cluster_size> <benchmark>"
    echo ""
    echo "Examples:"
    echo "  $0 e6data S-2x2 tpcds_29_1tb"
    echo "  $0 dbr S-4x4 tpcds_29_1tb"
    echo "  $0 e6data M-4x4 tpcds_51_1tb"
    echo ""
    echo "Arguments match S3 structure:"
    echo "  s3://e6-jmeter/jmeter-results/engine=<ARG1>/cluster_size=<ARG2>/benchmark=<ARG3>/"
    echo ""
    echo "Available engines: e6data, dbr"
    echo ""
    echo "Available cluster sizes:"
    echo "  E6Data: S-2x2, M-4x4, XS-1x1"
    echo "  DBR:    S-2x2, S-4x4, S-1x1"
    exit 1
fi

# Configuration
ENGINE="$1"
CLUSTER_SIZE="$2"
BENCHMARK="$3"
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
if [ "$ENGINE" = "e6data" ]; then
    echo "   - Cluster: demo-graviton"
fi
echo "   - Engine: ${ENGINE}"
echo "   - Size: ${CLUSTER_SIZE}"
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

# Check if test input files exist and extract sample file info
echo "Checking for test input files..."
MISSING_FILES=0
SAMPLE_TEST_INPUT=""
for concurrency in "${CONCURRENCY_LEVELS[@]}"; do
    TEST_INPUT="test_inputs/${ENGINE}_${CLUSTER_SIZE_NORMALIZED}_${BENCHMARK}_concurrency_${concurrency}.txt"
    if [ ! -f "$TEST_INPUT" ]; then
        echo -e "${YELLOW}  ⚠ Missing: $TEST_INPUT${NC}"
        MISSING_FILES=$((MISSING_FILES + 1))
    else
        echo "  ✓ Found: $TEST_INPUT"
        # Save first found test input for reading metadata
        if [ -z "$SAMPLE_TEST_INPUT" ]; then
            SAMPLE_TEST_INPUT="$TEST_INPUT"
        fi
    fi
done

if [ $MISSING_FILES -gt 0 ]; then
    echo ""
    echo -e "${YELLOW}Warning: $MISSING_FILES test input file(s) missing${NC}"
    echo ""
    read -p "Continue anyway? (y/n): " continue_choice
    if [[ ! "$continue_choice" =~ ^[Yy]$ ]]; then
        echo "Exiting..."
        exit 1
    fi
fi

# Extract info from sample test input file
QUERY_FILE=""
CONNECTION_FILE=""
TEST_PROPERTIES_FILE=""
TEST_PLAN_FILE=""
if [ -n "$SAMPLE_TEST_INPUT" ]; then
    QUERY_FILE=$(sed -n '5p' "$SAMPLE_TEST_INPUT")
    CONNECTION_FILE=$(sed -n '4p' "$SAMPLE_TEST_INPUT")
    TEST_PROPERTIES_FILE=$(sed -n '3p' "$SAMPLE_TEST_INPUT")
    TEST_PLAN_FILE=$(sed -n '2p' "$SAMPLE_TEST_INPUT")
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
    TEST_INPUT="test_inputs/${ENGINE}_${CLUSTER_SIZE_NORMALIZED}_${BENCHMARK}_concurrency_${concurrency}.txt"

    # Skip if test input file doesn't exist
    if [ ! -f "$TEST_INPUT" ]; then
        echo ""
        echo -e "${YELLOW}=========================================="
        echo "⚠ Skipping: Concurrency ${concurrency} (test input file not found)"
        echo -e "==========================================${NC}"
        continue
    fi

    # Extract metadata file path (line 1 of test input)
    METADATA_FILE=$(sed -n '1p' "$TEST_INPUT")
    METADATA_PATH="metadata_files/$METADATA_FILE"

    # Extract instance_type from metadata file
    INSTANCE_TYPE="unknown"
    if [ -f "$METADATA_PATH" ]; then
        INSTANCE_TYPE=$(grep -o '"instance_type"[[:space:]]*:[[:space:]]*"[^"]*"' "$METADATA_PATH" | cut -d'"' -f4)
    fi

    # Extract query file name (line 5 of test input)
    QUERY_FILE=$(sed -n '5p' "$TEST_INPUT")
    QUERY_BASENAME=$(basename "$QUERY_FILE" .csv)

    # Create log file name with instance_type and query_file
    LOG_FILE="$LOG_DIR/${ENGINE}_${CLUSTER_SIZE_NORMALIZED}_${INSTANCE_TYPE}_${QUERY_BASENAME}_concurrency${concurrency}_$(date +%Y%m%d_%H%M%S).log"

    echo ""
    echo -e "${BLUE}=========================================="
    echo "Running: ${ENGINE_DISPLAY} ${CLUSTER_SIZE} - Concurrency ${concurrency}"
    echo -e "==========================================${NC}"
    echo "Test input: $TEST_INPUT"
    echo "Log file: $LOG_FILE"
    echo ""

    # Run test
    if ./run_jmeter_tests_interactive.sh < "$TEST_INPUT" 2>&1 | tee "$LOG_FILE"; then
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

    # Wait between tests
    if [[ "$concurrency" != "${CONCURRENCY_LEVELS[-1]}" ]]; then
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
