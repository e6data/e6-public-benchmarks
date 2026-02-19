#!/bin/bash
# Run all Athena queries and save results as CSV files
#
# This script executes predefined Athena queries and saves results as CSV,
# providing an automated way to generate reports from Athena data.
#
# Usage:
#   ./utilities/athena/run_athena_reports.sh [engine] [cluster_size] [benchmark] [output_dir]
#
# Parameters (use "all" to include all values):
#   engine: e6data, databricks, or "all" (default: all)
#   cluster_size: S-2x2, S-4x4, M-4x4, or "all" (default: all)
#   benchmark: tpcds_29_1tb, tpcds_51_1tb, or "all" (default: all)
#   output_dir: Output directory (default: reports/athena_csv_reports_TIMESTAMP)
#
# Examples:
#   ./utilities/athena/run_athena_reports.sh                    # All data
#   ./utilities/athena/run_athena_reports.sh e6data all all     # All e6data runs
#   ./utilities/athena/run_athena_reports.sh e6data S-2x2 tpcds_29_1tb  # Specific config

set -e

ENGINE="${1:-all}"
CLUSTER_SIZE="${2:-all}"
BENCHMARK="${3:-all}"
OUTPUT_DIR="${4:-reports/athena_csv_reports_$(date +%Y%m%d_%H%M%S)}"

ATHENA_DB="${ATHENA_DB:-default}"
ATHENA_OUTPUT_LOCATION="${ATHENA_OUTPUT_LOCATION:-s3://your-s3-bucket/athena-query-results/}"

# Build WHERE conditions (without WHERE keyword)
WHERE_CONDITIONS=""
if [ "$ENGINE" != "all" ]; then
    WHERE_CONDITIONS="engine = '$ENGINE'"
fi
if [ "$CLUSTER_SIZE" != "all" ]; then
    if [ -n "$WHERE_CONDITIONS" ]; then
        WHERE_CONDITIONS="$WHERE_CONDITIONS AND cluster_size = '$CLUSTER_SIZE'"
    else
        WHERE_CONDITIONS="cluster_size = '$CLUSTER_SIZE'"
    fi
fi
if [ "$BENCHMARK" != "all" ]; then
    if [ -n "$WHERE_CONDITIONS" ]; then
        WHERE_CONDITIONS="$WHERE_CONDITIONS AND benchmark = '$BENCHMARK'"
    else
        WHERE_CONDITIONS="benchmark = '$BENCHMARK'"
    fi
fi

echo "=========================================="
echo "Athena Report Generation"
echo "=========================================="
echo "Engine: $ENGINE"
echo "Cluster: $CLUSTER_SIZE"
echo "Benchmark: $BENCHMARK"
echo "Filter: ${WHERE_CONDITIONS:-No filters (querying all data)}"
echo "Output: $OUTPUT_DIR"
echo "=========================================="
echo ""

# Create output directory
mkdir -p "$OUTPUT_DIR"

# Function to run Athena query and save as CSV
run_athena_csv() {
    local query="$1"
    local output_file="$2"
    local description="$3"

    echo "----------------------------------------"
    echo "Running: $description"
    echo "Output: $output_file"

    # Start query execution
    EXEC_ID=$(aws athena start-query-execution \
        --query-string "$query" \
        --query-execution-context Database="$ATHENA_DB" \
        --result-configuration OutputLocation="$ATHENA_OUTPUT_LOCATION" \
        --query 'QueryExecutionId' --output text 2>&1)

    if [[ "$EXEC_ID" == *"error"* ]] || [[ "$EXEC_ID" == *"Error"* ]]; then
        echo "❌ Failed to start query: $EXEC_ID"
        return 1
    fi

    # Wait for completion (max 2 minutes)
    echo -n "Waiting for query to complete"
    for i in {1..60}; do
        STATUS=$(aws athena get-query-execution \
            --query-execution-id "$EXEC_ID" \
            --query 'QueryExecution.Status.State' --output text 2>&1)

        if [[ "$STATUS" == "SUCCEEDED" ]]; then
            echo " ✓"

            # Get results and convert to CSV
            aws athena get-query-results \
                --query-execution-id "$EXEC_ID" \
                --output json | \
                jq -r '
                    # Extract column names
                    (.ResultSet.ResultSetMetadata.ColumnInfo | map(.Name)) as $headers |
                    # Extract data rows
                    (.ResultSet.Rows | map(.Data | map(.VarCharValue // ""))) as $rows |
                    # Combine headers and data
                    ([$headers] + ($rows | .[1:])) |
                    # Convert to CSV
                    map(@csv) | .[]
                ' > "$output_file"

            ROW_COUNT=$(wc -l < "$output_file" | tr -d ' ')
            echo "✅ Saved $((ROW_COUNT - 1)) rows to $output_file"
            return 0
        elif [[ "$STATUS" == "FAILED" ]]; then
            echo " ✗"
            REASON=$(aws athena get-query-execution \
                --query-execution-id "$EXEC_ID" \
                --query 'QueryExecution.Status.StateChangeReason' --output text)
            echo "❌ Query failed: $REASON"
            return 1
        elif [[ "$STATUS" == "CANCELLED" ]]; then
            echo " ✗"
            echo "⚠️  Query cancelled"
            return 1
        fi

        echo -n "."
        sleep 2
    done

    echo " ✗"
    echo "⚠️  Query timed out after 2 minutes"
    return 1
}

# Report 1: Valid Runs (exclude outliers)
run_athena_csv "
SELECT
    engine, cluster_size, instance_type, benchmark, run_type,
    run_id, run_date,
    ROUND(queries_per_second, 2) as qps,
    ROUND(avg_latency_sec, 2) as avg_time,
    ROUND(p50_latency_sec, 2) as p50,
    ROUND(p90_latency_sec, 2) as p90,
    ROUND(p95_latency_sec, 2) as p95,
    ROUND(p99_latency_sec, 2) as p99,
    ROUND(total_time_taken_sec, 2) as test_duration,
    total_success as success,
    total_failed as failed,
    is_best,
    is_baseline,
    is_outlier
FROM jmeter_runs_index
WHERE ${WHERE_CONDITIONS}${WHERE_CONDITIONS:+ AND} COALESCE(is_outlier, 'no') != 'yes'
ORDER BY engine, cluster_size, run_type, run_date DESC;
" "$OUTPUT_DIR/01_valid_runs.csv" "Valid runs (outliers excluded)"

echo ""

# Report 2: Throughput Analysis
run_athena_csv "
SELECT
    engine,
    cluster_size,
    benchmark,
    run_type,
    COUNT(*) as run_count,
    ROUND(AVG(queries_per_second), 2) as avg_qps,
    ROUND(AVG(queries_per_minute), 2) as avg_qpm,
    ROUND(MIN(queries_per_second), 2) as min_qps,
    ROUND(MAX(queries_per_second), 2) as max_qps
FROM jmeter_runs_index
WHERE ${WHERE_CONDITIONS}${WHERE_CONDITIONS:+ AND} COALESCE(is_outlier, 'no') != 'yes'
GROUP BY engine, cluster_size, benchmark, run_type
ORDER BY engine, cluster_size, run_type;
" "$OUTPUT_DIR/02_throughput_analysis.csv" "Throughput analysis by concurrency"

echo ""

# Report 3: Best Runs per Concurrency
run_athena_csv "
WITH ranked AS (
    SELECT
        engine, cluster_size, benchmark, run_type, run_id, run_date,
        avg_latency_sec, p90_latency_sec, p95_latency_sec, p99_latency_sec,
        is_best, is_baseline, total_time_taken_sec,
        ROW_NUMBER() OVER (PARTITION BY engine, cluster_size, benchmark, run_type ORDER BY avg_latency_sec ASC) as rank
    FROM jmeter_runs_index
    WHERE ${WHERE_CONDITIONS}${WHERE_CONDITIONS:+ AND} COALESCE(is_outlier, 'no') != 'yes'
)
SELECT
    engine, cluster_size, benchmark, run_type, run_id, run_date,
    ROUND(avg_latency_sec, 2) as avg_time,
    ROUND(p90_latency_sec, 2) as p90,
    ROUND(p95_latency_sec, 2) as p95,
    ROUND(p99_latency_sec, 2) as p99,
    ROUND(total_time_taken_sec, 2) as test_duration,
    is_best,
    is_baseline
FROM ranked
WHERE rank = 1
ORDER BY engine, cluster_size, run_type;
" "$OUTPUT_DIR/03_best_runs.csv" "Best run per concurrency level"

echo ""

# Report 4: Concurrency Scaling
run_athena_csv "
SELECT
    engine,
    cluster_size,
    benchmark,
    run_type,
    COUNT(*) as valid_runs,
    ROUND(AVG(queries_per_second), 2) as avg_qps,
    ROUND(AVG(avg_latency_sec), 2) as avg_latency,
    ROUND(AVG(p90_latency_sec), 2) as avg_p90,
    ROUND(AVG(p95_latency_sec), 2) as avg_p95,
    ROUND(AVG(p99_latency_sec), 2) as avg_p99,
    ROUND(AVG(total_time_taken_sec), 2) as avg_test_duration,
    ROUND(MIN(p90_latency_sec), 2) as best_p90,
    ROUND(MAX(p90_latency_sec), 2) as worst_p90
FROM jmeter_runs_index
WHERE ${WHERE_CONDITIONS}${WHERE_CONDITIONS:+ AND} COALESCE(is_outlier, 'no') != 'yes'
GROUP BY engine, cluster_size, benchmark, run_type
ORDER BY engine, cluster_size, run_type;
" "$OUTPUT_DIR/04_concurrency_scaling.csv" "Concurrency scaling analysis"

echo ""

# Report 5: Recent Runs (last 20 per configuration)
run_athena_csv "
WITH ranked_recent AS (
    SELECT *,
        ROW_NUMBER() OVER (PARTITION BY engine, cluster_size, benchmark ORDER BY run_date DESC) as recent_rank
    FROM jmeter_runs_index
    WHERE ${WHERE_CONDITIONS}${WHERE_CONDITIONS:+ AND} 1=1
)
SELECT
    engine, cluster_size, benchmark, run_type,
    run_id, run_date,
    ROUND(avg_latency_sec, 2) as avg_time,
    ROUND(p90_latency_sec, 2) as p90,
    ROUND(p95_latency_sec, 2) as p95,
    ROUND(p99_latency_sec, 2) as p99,
    ROUND(total_time_taken_sec, 2) as test_duration,
    performance_rating,
    is_best,
    is_baseline,
    is_outlier
FROM ranked_recent
WHERE recent_rank <= 20
ORDER BY engine, cluster_size, run_date DESC;
" "$OUTPUT_DIR/05_recent_runs.csv" "Recent runs (last 20 per config)"

echo ""

# Report 6: Performance Summary by Instance Type
run_athena_csv "
SELECT
    engine,
    cluster_size,
    benchmark,
    run_type,
    instance_type,
    COUNT(*) as total_runs,
    COUNT(CASE WHEN COALESCE(is_outlier, 'no') != 'yes' THEN 1 END) as valid_runs,
    COUNT(CASE WHEN is_outlier = 'yes' THEN 1 END) as outlier_runs,
    ROUND(AVG(CASE WHEN COALESCE(is_outlier, 'no') != 'yes' THEN queries_per_second END), 2) as avg_qps,
    ROUND(AVG(CASE WHEN COALESCE(is_outlier, 'no') != 'yes' THEN avg_latency_sec END), 2) as avg_of_avg,
    ROUND(AVG(CASE WHEN COALESCE(is_outlier, 'no') != 'yes' THEN p90_latency_sec END), 2) as avg_p90,
    ROUND(AVG(CASE WHEN COALESCE(is_outlier, 'no') != 'yes' THEN p95_latency_sec END), 2) as avg_p95,
    ROUND(AVG(CASE WHEN COALESCE(is_outlier, 'no') != 'yes' THEN p99_latency_sec END), 2) as avg_p99,
    ROUND(AVG(CASE WHEN COALESCE(is_outlier, 'no') != 'yes' THEN total_time_taken_sec END), 2) as avg_test_duration,
    ROUND(MIN(CASE WHEN COALESCE(is_outlier, 'no') != 'yes' THEN p90_latency_sec END), 2) as best_p90,
    ROUND(MAX(CASE WHEN COALESCE(is_outlier, 'no') != 'yes' THEN p90_latency_sec END), 2) as worst_p90,
    ROUND(STDDEV(CASE WHEN COALESCE(is_outlier, 'no') != 'yes' THEN p90_latency_sec END), 2) as p90_stddev
FROM jmeter_runs_index
WHERE ${WHERE_CONDITIONS}${WHERE_CONDITIONS:+ AND} 1=1
GROUP BY engine, cluster_size, benchmark, run_type, instance_type
ORDER BY engine, cluster_size, run_type, instance_type;
" "$OUTPUT_DIR/06_performance_summary.csv" "Performance summary by instance type"

echo ""

# Report 7: Outlier Detection Summary
run_athena_csv "
SELECT
    engine, cluster_size, benchmark, run_type,
    run_id, run_date,
    ROUND(p90_latency_sec, 2) as p90,
    ROUND(p90_z_score, 2) as p90_z_score,
    ROUND(p90_deviation_pct, 2) as p90_dev_pct,
    ROUND(total_time_taken_sec, 2) as test_duration,
    outlier_severity,
    is_outlier
FROM jmeter_runs_index
WHERE ${WHERE_CONDITIONS}${WHERE_CONDITIONS:+ AND} 1=1
ORDER BY engine, cluster_size, run_type, p90_latency_sec DESC;
" "$OUTPUT_DIR/07_outlier_detection.csv" "Outlier detection summary"

echo ""

# Report 8: Error Rate Analysis
run_athena_csv "
SELECT
    engine,
    cluster_size,
    benchmark,
    run_type,
    COUNT(*) as total_runs,
    SUM(total_success) as total_successful_queries,
    SUM(total_failed) as total_failed_queries,
    ROUND(AVG(CASE WHEN COALESCE(is_outlier, 'no') != 'yes' THEN error_rate_pct END), 2) as avg_error_rate_pct,
    ROUND(MAX(CASE WHEN COALESCE(is_outlier, 'no') != 'yes' THEN error_rate_pct END), 2) as max_error_rate_pct
FROM jmeter_runs_index
WHERE ${WHERE_CONDITIONS}${WHERE_CONDITIONS:+ AND} 1=1
GROUP BY engine, cluster_size, benchmark, run_type
ORDER BY engine, cluster_size, run_type;
" "$OUTPUT_DIR/08_error_rate_analysis.csv" "Error rate analysis"

echo ""

# Create README with metadata
cat > "$OUTPUT_DIR/README.txt" << EOF
Athena Report Generation Results
================================

Generated: $(date)
Engine Filter: $ENGINE
Cluster Size Filter: $CLUSTER_SIZE
Benchmark Filter: $BENCHMARK
WHERE Conditions: ${WHERE_CONDITIONS:-No filters (all data)}

Reports Generated:
-----------------
01_valid_runs.csv              - All valid runs (outliers excluded)
02_throughput_analysis.csv     - Throughput metrics by concurrency
03_best_runs.csv               - Best run for each concurrency level
04_concurrency_scaling.csv     - How performance scales with concurrency
05_recent_runs.csv             - Most recent 20 runs per configuration
06_performance_summary.csv     - Summary statistics by instance type
07_outlier_detection.csv       - Outlier detection metrics
08_error_rate_analysis.csv     - Error rates by concurrency

Query Source: utilities/athena/run_athena_reports.sh
Data Source: AWS Athena table 'jmeter_runs_index'

Note on Data Interpretation:
---------------------------
- total_time_taken_sec: Actual test wall-clock duration from JMeter (typically 301s = 5min 1sec)
- queries_per_second (QPS): Total queries divided by total test duration
  - For tests with recycle=false, QPS remains similar across concurrency levels
  - The key difference is in LATENCY, not throughput:
    * Lower concurrency = lower latency (less resource contention)
    * Higher concurrency = higher latency (more resource contention)
- is_outlier: Runs marked as outliers are excluded from aggregations
- Outlier detection columns (z-score, deviation_pct) may be blank if not calculated
EOF

echo "=========================================="
echo "Report Generation Complete!"
echo "=========================================="
echo ""
echo "Output directory: $OUTPUT_DIR"
echo ""
echo "Generated reports:"
ls -lh "$OUTPUT_DIR"/*.csv | awk '{printf "  %s  (%s)\n", $9, $5}'
echo ""
echo "View README: cat $OUTPUT_DIR/README.txt"
echo ""
