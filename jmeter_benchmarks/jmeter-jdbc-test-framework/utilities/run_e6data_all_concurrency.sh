#!/bin/bash
# Run all e6data concurrency tests matching S3 path structure
# Usage: ./run_e6data_all_concurrency.sh <cluster_size> <benchmark>
#
# Arguments match S3 path: s3://bucket/engine=e6data/cluster_size=X/benchmark=Y/
#
# Examples:
#   ./run_e6data_all_concurrency.sh S-2x2 tpcds_29_1tb
#   ./run_e6data_all_concurrency.sh M-4x4 tpcds_51_1tb
#
# Concurrency levels: 1, 2, 4, 8, 12, 16

set -e

# Check arguments
if [ $# -lt 2 ]; then
    echo "Error: cluster_size and benchmark arguments required"
    echo ""
    echo "Usage: $0 <cluster_size> <benchmark>"
    echo ""
    echo "Examples:"
    echo "  $0 S-2x2 tpcds_29_1tb"
    echo "  $0 M-4x4 tpcds_51_1tb"
    echo ""
    echo "Arguments match S3 structure:"
    echo "  s3://e6-jmeter/jmeter-results/engine=e6data/cluster_size=<ARG1>/benchmark=<ARG2>/"
    echo ""
    echo "Available cluster sizes:"
    echo "  - S-2x2  (60 cores: 2 executors × 30 cores)"
    echo "  - M-4x4  (120 cores: 4 executors × 30 cores)"
    exit 1
fi

# Configuration
ENGINE="e6data"
CLUSTER_SIZE="$1"
BENCHMARK="$2"
CONCURRENCY_LEVELS=(1 2 4 8 12 16)
S3_BASE_PATH="s3://e6-jmeter/jmeter-results"

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

# Display configuration
echo -e "${BLUE}=========================================="
echo "e6data ${CLUSTER_SIZE} Cluster - All Concurrency Tests"
echo -e "==========================================${NC}"
echo ""
echo "Configuration:"
echo "   - Cluster: demo-graviton"
echo "   - Size: ${CLUSTER_SIZE}"
if [ "$CLUSTER_SIZE" = "S-2x2" ]; then
    echo "   - 60 cores (2 executors × 30 cores) - Matches DBR S-2x2"
elif [ "$CLUSTER_SIZE" = "M-4x4" ]; then
    echo "   - 120 cores (4 executors × 30 cores) - Matches DBR S-4x4"
fi
echo "   - Benchmark: ${BENCHMARK}"
echo ""
echo "Tests to run:"
for concurrency in "${CONCURRENCY_LEVELS[@]}"; do
    echo "  - Concurrency: ${concurrency} threads"
done
echo ""

# Check if test input files exist
echo "Checking for test input files..."
MISSING_FILES=0
for concurrency in "${CONCURRENCY_LEVELS[@]}"; do
    TEST_INPUT="test_inputs/e6data_${CLUSTER_SIZE_NORMALIZED}_${BENCHMARK}_concurrency_${concurrency}.txt"
    if [ ! -f "$TEST_INPUT" ]; then
        echo -e "${YELLOW}  ⚠ Missing: $TEST_INPUT${NC}"
        MISSING_FILES=$((MISSING_FILES + 1))
    else
        echo "  ✓ Found: $TEST_INPUT"
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

echo ""
read -p "Press Enter to start tests or Ctrl+C to cancel..."

# Create log directory
LOG_DIR="/tmp/jmeter_test_logs"
mkdir -p "$LOG_DIR"

# Run all concurrency tests
for concurrency in "${CONCURRENCY_LEVELS[@]}"; do
    TEST_INPUT="test_inputs/e6data_${CLUSTER_SIZE_NORMALIZED}_${BENCHMARK}_concurrency_${concurrency}.txt"

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
    echo "Running: e6data ${CLUSTER_SIZE} - Concurrency ${concurrency}"
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
echo "✓ All e6data ${CLUSTER_SIZE} concurrency tests completed!"
echo -e "==========================================${NC}"
echo ""
echo "Logs saved in: $LOG_DIR"
echo ""
echo "Next steps:"
echo "  1. Check S3 for uploaded results:"
echo "     ${S3_BASE_PATH}/engine=${ENGINE}/cluster_size=${CLUSTER_SIZE}/benchmark=${BENCHMARK}/run_type=concurrency_X/run_id=YYYYMMDD-HHMMSS/"
echo "  2. Compare with DBR results (if applicable)"
echo "  3. Generate comparison report using utilities/compare_* scripts"
echo ""
