#!/usr/bin/env bash
#
# JMeter Test Run Comparison Wrapper Script
#
# Easy-to-use wrapper around compare_jmeter_runs.py
#
# Usage:
#   ./compare_jmeter_runs.sh <run_id1> <run_id2> [format]
#
# Examples:
#   # Compare two runs by run_id (from S3)
#   ./compare_jmeter_runs.sh 20251029-083259 20251029-084324
#
#   # Compare with markdown output
#   ./compare_jmeter_runs.sh 20251029-083259 20251029-084324 markdown > comparison.md
#
#   # Compare local files
#   ./compare_jmeter_runs.sh local:reports/test_result_1.json local:reports/test_result_2.json
#
#   # Compare local vs S3
#   ./compare_jmeter_runs.sh local:reports/test_result_1.json 20251029-084324
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_SCRIPT="$SCRIPT_DIR/compare_jmeter_runs.py"
S3_BASE_PATH="s3://e6-jmeter/jmeter-results"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print usage
usage() {
    cat << EOF
Usage: $0 <run1> <run2> [format]

Arguments:
    run1    Run ID (e.g., 20251029-083259) or local:<path> or s3://<full-path>
    run2    Run ID (e.g., 20251029-084324) or local:<path> or s3://<full-path>
    format  Output format: text (default), json, or markdown

Examples:
    # Compare two runs from S3 by run_id
    $0 20251029-083259 20251029-084324

    # Output as markdown
    $0 20251029-083259 20251029-084324 markdown > comparison.md

    # Compare local files
    $0 local:reports/test_result_20251029-083259.json local:reports/test_result_20251029-084324.json

    # Mix local and S3
    $0 local:reports/test_result_1.json 20251029-084324

    # Full S3 paths
    $0 s3://bucket/path/test_result_1.json s3://bucket/path/test_result_2.json

Run IDs from Recent Tests:
EOF

    # List recent runs from S3 (if aws cli is available)
    if command -v aws &> /dev/null; then
        echo ""
        echo "  Recent S3 runs:"
        aws s3 ls "$S3_BASE_PATH/" --recursive 2>/dev/null | \
            grep "test_result" | \
            awk '{print "    " $4}' | \
            sed 's/.*run_id=//' | \
            sed 's/\/test_result.*//' | \
            sort -r | \
            head -10 || echo "    (Unable to list S3 runs)"
    fi

    # List local runs
    if [ -d "$SCRIPT_DIR/../reports" ]; then
        echo ""
        echo "  Recent local runs:"
        find "$SCRIPT_DIR/../reports" -name "test_result_*.json" -type f 2>/dev/null | \
            xargs ls -t 2>/dev/null | \
            head -10 | \
            while read file; do
                basename "$file" | sed 's/test_result_/    /' | sed 's/\.json//'
            done || echo "    (No local runs found)"
    fi

    echo ""
}

# Function to resolve file path
resolve_path() {
    local input="$1"

    # Check if it's a local file reference
    if [[ "$input" == local:* ]]; then
        # Remove 'local:' prefix
        echo "${input#local:}"
        return 0
    fi

    # Check if it's already an S3 path
    if [[ "$input" == s3://* ]]; then
        echo "$input"
        return 0
    fi

    # Check if it's a local file path
    if [[ -f "$input" ]]; then
        echo "$input"
        return 0
    fi

    # Try to find run_date for the run_id
    # Extract date from run_id (format: YYYYMMDD-HHMMSS)
    if [[ "$input" =~ ^([0-9]{8})-([0-9]{6})$ ]]; then
        local run_date="${BASH_REMATCH[1]}"
        local run_id="$input"
        local s3_path="$S3_BASE_PATH/run_date=$run_date/run_id=$run_id/test_result_$run_id.json"
        echo "$s3_path"
        return 0
    fi

    # Invalid format
    echo "Error: Invalid run identifier: $input" >&2
    echo "Expected: run_id (YYYYMMDD-HHMMSS), local:<path>, or s3://<path>" >&2
    return 1
}

# Check arguments
if [ $# -lt 2 ]; then
    usage
    exit 1
fi

RUN1="$1"
RUN2="$2"
FORMAT="${3:-text}"

# Validate format
if [[ ! "$FORMAT" =~ ^(text|json|markdown)$ ]]; then
    echo -e "${RED}Error: Invalid format '$FORMAT'. Must be text, json, or markdown${NC}" >&2
    exit 1
fi

# Check if Python script exists
if [ ! -f "$PYTHON_SCRIPT" ]; then
    echo -e "${RED}Error: Python script not found: $PYTHON_SCRIPT${NC}" >&2
    exit 1
fi

# Check if Python 3 is available
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Error: Python 3 is required but not found${NC}" >&2
    exit 1
fi

# Resolve paths
echo -e "${YELLOW}Resolving run paths...${NC}" >&2
RUN1_PATH=$(resolve_path "$RUN1") || exit 1
RUN2_PATH=$(resolve_path "$RUN2") || exit 1

echo -e "${GREEN}Run 1: $RUN1_PATH${NC}" >&2
echo -e "${GREEN}Run 2: $RUN2_PATH${NC}" >&2
echo "" >&2

# Execute Python script
python3 "$PYTHON_SCRIPT" "$RUN1_PATH" "$RUN2_PATH" --format "$FORMAT"

EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    echo "" >&2
    echo -e "${GREEN}✅ Comparison completed successfully${NC}" >&2
else
    echo "" >&2
    echo -e "${RED}❌ Comparison failed with exit code $EXIT_CODE${NC}" >&2
fi

exit $EXIT_CODE
