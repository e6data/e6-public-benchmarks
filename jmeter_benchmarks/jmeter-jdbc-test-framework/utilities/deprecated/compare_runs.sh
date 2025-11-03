#!/bin/bash

# compare_runs.sh
# Utility script to compare performance between different engine/cluster/benchmark combinations
#
# Usage:
#   ./utilities/compare_runs.sh <benchmark> <run_type>
#
# Example:
#   ./utilities/compare_runs.sh tpcds_29_1tb sequential

set -e

if [[ $# -ne 2 ]]; then
    echo "Usage: $0 <benchmark> <run_type>"
    echo ""
    echo "Example:"
    echo "  $0 tpcds_29_1tb sequential"
    echo ""
    echo "This will compare the latest runs across all engines and cluster sizes for the specified benchmark and run type."
    exit 1
fi

BENCHMARK="$1"
RUN_TYPE="$2"

S3_BASE="s3://e6-jmeter/jmeter-results"

echo "==========================================="
echo "Comparing Runs"
echo "==========================================="
echo "Benchmark: $BENCHMARK"
echo "Run Type:  $RUN_TYPE"
echo "==========================================="
echo ""

# Function to fetch and display metrics for a specific path
fetch_metrics() {
    local path="$1"
    local label="$2"

    if aws s3 ls "$path/latest.json" > /dev/null 2>&1; then
        echo "📊 $label"
        aws s3 cp "$path/latest.json" - 2>/dev/null | jq -r '
          "  Run ID:           \(.run_id)",
          "  Avg Time (sec):   \(.performance_metrics.avg_time_sec)",
          "  P95 Latency (sec):\(.performance_metrics.p95_latency_sec)",
          "  P99 Latency (sec):\(.performance_metrics.p99_latency_sec)",
          "  Throughput:       \(.performance_metrics.throughput) queries/sec",
          "  Total Queries:    \(.query_statistics.total_queries)",
          "  Error Rate:       \(.test_results.error_percent)%",
          "  Instance Type:    \(.cluster_config.instance_type // "N/A")"
        '
        echo ""
    else
        echo "⚠️  $label - No runs found"
        echo ""
    fi
}

# Discover all engine/cluster_size combinations for this benchmark/run_type
echo "Discovering available runs..."
echo ""

# List all engines
aws s3 ls "$S3_BASE/" | grep "PRE engine=" | awk -F'=' '{print $2}' | tr -d '/' | while read engine; do
    # List all cluster sizes for this engine
    aws s3 ls "$S3_BASE/engine=$engine/" | grep "PRE cluster_size=" | awk -F'=' '{print $2}' | tr -d '/' | while read cluster_size; do
        path="$S3_BASE/engine=$engine/cluster_size=$cluster_size/benchmark=$BENCHMARK/run_type=$RUN_TYPE"
        fetch_metrics "$path" "$engine / $cluster_size"
    done
done

echo "==========================================="
echo "Comparison complete!"
echo "==========================================="
echo ""
echo "To mark a specific run as 'best' for future comparisons:"
echo "  ./utilities/mark_best_run.sh <engine> <cluster_size> $BENCHMARK $RUN_TYPE <run_id>"
