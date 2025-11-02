#!/bin/bash

# mark_best_run.sh
# Utility script to mark a specific run as the "best" run for comparison purposes
#
# Usage:
#   ./utilities/mark_best_run.sh <engine> <cluster_size> <benchmark> <run_type> <run_id>
#
# Example:
#   ./utilities/mark_best_run.sh e6data 8xlarge tpcds_29_1tb sequential 20251029-184002

set -e

# Check arguments
if [[ $# -ne 5 ]]; then
    echo "Usage: $0 <engine> <cluster_size> <benchmark> <run_type> <run_id>"
    echo ""
    echo "Example:"
    echo "  $0 e6data 8xlarge tpcds_29_1tb sequential 20251029-184002"
    echo ""
    echo "Available runs:"
    echo "  aws s3 ls s3://e6-jmeter/jmeter-results/engine=e6data/cluster_size=8xlarge/benchmark=tpcds_29_1tb/run_type=sequential/"
    exit 1
fi

ENGINE="$1"
CLUSTER_SIZE="$2"
BENCHMARK="$3"
RUN_TYPE="$4"
RUN_ID="$5"

S3_BASE="s3://e6-jmeter/jmeter-results"
S3_PATH="$S3_BASE/engine=$ENGINE/cluster_size=$CLUSTER_SIZE/benchmark=$BENCHMARK/run_type=$RUN_TYPE"

echo "==========================================="
echo "Marking run as BEST"
echo "==========================================="
echo "Engine:       $ENGINE"
echo "Cluster Size: $CLUSTER_SIZE"
echo "Benchmark:    $BENCHMARK"
echo "Run Type:     $RUN_TYPE"
echo "Run ID:       $RUN_ID"
echo "==========================================="

# Check if the run exists
SOURCE_FILE="$S3_PATH/test_result_${RUN_ID}.json"

if ! aws s3 ls "$SOURCE_FILE" > /dev/null 2>&1; then
    echo "❌ Error: Run not found at $SOURCE_FILE"
    echo ""
    echo "Available runs:"
    aws s3 ls "$S3_PATH/" | grep "test_result_" | grep -v "latest\|best"
    exit 1
fi

echo ""
echo "✅ Found run at: $SOURCE_FILE"
echo ""
echo "Copying to best.json..."

# Copy the specified run to best.json
if aws s3 cp "$SOURCE_FILE" "$S3_PATH/best.json"; then
    echo "✅ Successfully marked run $RUN_ID as BEST"
    echo ""
    echo "Access best run at: $S3_PATH/best.json"
    echo ""
    echo "To view best run details:"
    echo "  aws s3 cp $S3_PATH/best.json - | jq ."
else
    echo "❌ Failed to copy run to best.json"
    exit 1
fi

# Optional: Show summary of the best run
echo ""
echo "Best Run Summary:"
aws s3 cp "$S3_PATH/best.json" - 2>/dev/null | jq -r '
  "Run ID:           \(.run_id)",
  "Avg Time (sec):   \(.performance_metrics.avg_time_sec)",
  "Total Queries:    \(.query_statistics.total_queries)",
  "Error Rate:       \(.test_results.error_percent)%",
  "Throughput:       \(.performance_metrics.throughput) queries/sec"
'

echo ""
echo "==========================================="
echo "Done!"
echo "==========================================="
