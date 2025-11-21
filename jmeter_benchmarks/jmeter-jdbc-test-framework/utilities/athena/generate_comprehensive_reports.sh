#!/bin/bash
# Comprehensive JMeter Analysis Report Generator
# Generates multiple CSV reports from jmeter_query_results table

# Configuration
ATHENA_DATABASE="${ATHENA_DATABASE:-jmeter_analysis}"
ATHENA_WORKGROUP="${ATHENA_WORKGROUP:-primary}"
ATHENA_OUTPUT_LOCATION="${ATHENA_OUTPUT_LOCATION:-s3://e6-jmeter/athena-query-results/}"

# Parse command line arguments
if [ "$#" -lt 3 ]; then
    echo "Usage: $0 <engine> <cluster_size> <benchmark> [output_dir]"
    echo "Example: $0 e6data S-2x2 tpcds_29_1tb /tmp/reports"
    exit 1
fi

ENGINE="$1"
CLUSTER_SIZE="$2"
BENCHMARK="$3"
OUTPUT_DIR="${4:-/tmp/jmeter_reports_$(date +%Y%m%d_%H%M%S)}"

# Create output directory
mkdir -p "$OUTPUT_DIR"

echo "=========================================="
echo "JMeter Comprehensive Report Generator"
echo "=========================================="
echo "Engine: $ENGINE"
echo "Cluster Size: $CLUSTER_SIZE"
echo "Benchmark: $BENCHMARK"
echo "Output: $OUTPUT_DIR"
echo "=========================================="
echo ""

# Function to execute Athena query and save as CSV
execute_query() {
    local query="$1"
    local output_file="$2"
    local description="$3"

    echo "Generating: $description"

    # Start query execution
    local query_id=$(aws athena start-query-execution \
        --query-string "$query" \
        --query-execution-context Database="$ATHENA_DATABASE" \
        --work-group "$ATHENA_WORKGROUP" \
        --result-configuration OutputLocation="$ATHENA_OUTPUT_LOCATION" \
        --output text --query 'QueryExecutionId')

    echo "  Query ID: $query_id"
    echo -n "  Waiting"

    sleep 3

    # Wait for completion
    while true; do
        local status=$(aws athena get-query-execution \
            --query-execution-id "$query_id" \
            --output text --query 'QueryExecution.Status.State')

        if [[ "$status" == "SUCCEEDED" ]]; then
            echo " ✓"

            # Get results and convert to CSV
            aws athena get-query-results \
                --query-execution-id "$query_id" \
                --output json | \
                jq -r '.ResultSet.Rows[] | .Data | map(.VarCharValue // "") | @csv' > "$output_file"

            local row_count=$(wc -l < "$output_file")
            echo "  ✅ Success: $row_count rows saved to $output_file"
            echo ""
            return 0
        elif [[ "$status" == "FAILED" ]] || [[ "$status" == "CANCELLED" ]]; then
            echo " ✗"
            echo "  ❌ Failed!"
            aws athena get-query-execution --query-execution-id "$query_id" | \
                jq -r '.QueryExecution.Status.StateChangeReason'
            echo ""
            return 1
        fi
        echo -n "."
        sleep 2
    done
}

# Track report generation
REPORTS_GENERATED=0
REPORTS_FAILED=0

# ========================================
# REPORT 1: Concurrency Scaling Analysis
# ========================================
QUERY=$(cat <<EOF
SELECT
    run_type,
    run_id,
    COUNT(*) as total_queries,
    ROUND(AVG(CAST(elapsed_time_ms AS DOUBLE)) / 1000.0, 2) as avg_latency_sec,
    ROUND(APPROX_PERCENTILE(CAST(elapsed_time_ms AS DOUBLE) / 1000.0, 0.50), 2) as p50_sec,
    ROUND(APPROX_PERCENTILE(CAST(elapsed_time_ms AS DOUBLE) / 1000.0, 0.90), 2) as p90_sec,
    ROUND(APPROX_PERCENTILE(CAST(elapsed_time_ms AS DOUBLE) / 1000.0, 0.95), 2) as p95_sec,
    ROUND(APPROX_PERCENTILE(CAST(elapsed_time_ms AS DOUBLE) / 1000.0, 0.99), 2) as p99_sec,
    SUM(CASE WHEN success = 'true' THEN 1 ELSE 0 END) as successful_queries,
    SUM(CASE WHEN success != 'true' THEN 1 ELSE 0 END) as failed_queries
FROM jmeter_query_results
WHERE engine = '$ENGINE'
  AND cluster_size = '$CLUSTER_SIZE'
  AND benchmark = '$BENCHMARK'
  AND elapsed_time_ms IS NOT NULL
GROUP BY run_type, run_id
ORDER BY run_type, run_id DESC
EOF
)

if execute_query "$QUERY" "$OUTPUT_DIR/01_concurrency_scaling.csv" "Concurrency Scaling Analysis"; then
    ((REPORTS_GENERATED++))
else
    ((REPORTS_FAILED++))
fi

# ========================================
# REPORT 2: Query-Level Performance Breakdown
# ========================================
QUERY=$(cat <<EOF
SELECT
    label as query_name,
    COUNT(*) as execution_count,
    ROUND(AVG(CAST(elapsed_time_ms AS DOUBLE)) / 1000.0, 2) as avg_latency_sec,
    ROUND(MIN(CAST(elapsed_time_ms AS DOUBLE)) / 1000.0, 2) as min_latency_sec,
    ROUND(MAX(CAST(elapsed_time_ms AS DOUBLE)) / 1000.0, 2) as max_latency_sec,
    ROUND(APPROX_PERCENTILE(CAST(elapsed_time_ms AS DOUBLE) / 1000.0, 0.50), 2) as p50_sec,
    ROUND(APPROX_PERCENTILE(CAST(elapsed_time_ms AS DOUBLE) / 1000.0, 0.90), 2) as p90_sec,
    ROUND(APPROX_PERCENTILE(CAST(elapsed_time_ms AS DOUBLE) / 1000.0, 0.99), 2) as p99_sec
FROM jmeter_query_results
WHERE engine = '$ENGINE'
  AND cluster_size = '$CLUSTER_SIZE'
  AND benchmark = '$BENCHMARK'
  AND elapsed_time_ms IS NOT NULL
GROUP BY label
ORDER BY avg_latency_sec DESC
LIMIT 50
EOF
)

if execute_query "$QUERY" "$OUTPUT_DIR/02_query_performance.csv" "Query-Level Performance"; then
    ((REPORTS_GENERATED++))
else
    ((REPORTS_FAILED++))
fi

# ========================================
# REPORT 3: Run Comparison (Latest vs Previous)
# ========================================
QUERY=$(cat <<EOF
WITH run_metrics AS (
    SELECT
        run_type,
        run_id,
        COUNT(*) as total_queries,
        ROUND(AVG(CAST(elapsed_time_ms AS DOUBLE)) / 1000.0, 2) as avg_sec,
        ROUND(APPROX_PERCENTILE(CAST(elapsed_time_ms AS DOUBLE) / 1000.0, 0.90), 2) as p90_sec,
        ROUND(APPROX_PERCENTILE(CAST(elapsed_time_ms AS DOUBLE) / 1000.0, 0.99), 2) as p99_sec,
        ROW_NUMBER() OVER (PARTITION BY run_type ORDER BY run_id DESC) as run_rank
    FROM jmeter_query_results
    WHERE engine = '$ENGINE'
      AND cluster_size = '$CLUSTER_SIZE'
      AND benchmark = '$BENCHMARK'
      AND elapsed_time_ms IS NOT NULL
    GROUP BY run_type, run_id
)
SELECT
    run_type,
    MAX(CASE WHEN run_rank = 1 THEN run_id END) as latest_run,
    MAX(CASE WHEN run_rank = 1 THEN avg_sec END) as latest_avg_sec,
    MAX(CASE WHEN run_rank = 1 THEN p90_sec END) as latest_p90_sec,
    MAX(CASE WHEN run_rank = 1 THEN p99_sec END) as latest_p99_sec,
    MAX(CASE WHEN run_rank = 2 THEN run_id END) as previous_run,
    MAX(CASE WHEN run_rank = 2 THEN avg_sec END) as previous_avg_sec,
    MAX(CASE WHEN run_rank = 2 THEN p90_sec END) as previous_p90_sec,
    MAX(CASE WHEN run_rank = 2 THEN p99_sec END) as previous_p99_sec,
    ROUND((MAX(CASE WHEN run_rank = 1 THEN avg_sec END) - MAX(CASE WHEN run_rank = 2 THEN avg_sec END)) /
          NULLIF(MAX(CASE WHEN run_rank = 2 THEN avg_sec END), 0) * 100, 2) as avg_change_pct,
    ROUND((MAX(CASE WHEN run_rank = 1 THEN p99_sec END) - MAX(CASE WHEN run_rank = 2 THEN p99_sec END)) /
          NULLIF(MAX(CASE WHEN run_rank = 2 THEN p99_sec END), 0) * 100, 2) as p99_change_pct
FROM run_metrics
WHERE run_rank <= 2
GROUP BY run_type
ORDER BY run_type
EOF
)

if execute_query "$QUERY" "$OUTPUT_DIR/03_run_comparison.csv" "Run Comparison (Latest vs Previous)"; then
    ((REPORTS_GENERATED++))
else
    ((REPORTS_FAILED++))
fi

# ========================================
# REPORT 4: Top 10 Slowest Queries
# ========================================
QUERY=$(cat <<EOF
SELECT
    run_id,
    label as query_name,
    CAST(elapsed_time_ms AS BIGINT) / 1000.0 as elapsed_sec,
    CAST(latency_ms AS BIGINT) / 1000.0 as latency_sec,
    thread_name,
    success,
    response_message
FROM jmeter_query_results
WHERE engine = '$ENGINE'
  AND cluster_size = '$CLUSTER_SIZE'
  AND benchmark = '$BENCHMARK'
  AND elapsed_time_ms IS NOT NULL
ORDER BY elapsed_time_ms DESC
LIMIT 10
EOF
)

if execute_query "$QUERY" "$OUTPUT_DIR/04_slowest_queries.csv" "Top 10 Slowest Queries"; then
    ((REPORTS_GENERATED++))
else
    ((REPORTS_FAILED++))
fi

# ========================================
# REPORT 5: Success Rate by Concurrency
# ========================================
QUERY=$(cat <<EOF
SELECT
    run_type,
    COUNT(*) as total_queries,
    SUM(CASE WHEN success = 'true' THEN 1 ELSE 0 END) as successful,
    SUM(CASE WHEN success != 'true' THEN 1 ELSE 0 END) as failed,
    ROUND(SUM(CASE WHEN success = 'true' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) as success_rate_pct,
    COUNT(DISTINCT run_id) as num_runs
FROM jmeter_query_results
WHERE engine = '$ENGINE'
  AND cluster_size = '$CLUSTER_SIZE'
  AND benchmark = '$BENCHMARK'
GROUP BY run_type
ORDER BY run_type
EOF
)

if execute_query "$QUERY" "$OUTPUT_DIR/05_success_rate.csv" "Success Rate by Concurrency"; then
    ((REPORTS_GENERATED++))
else
    ((REPORTS_FAILED++))
fi

# ========================================
# REPORT 6: Throughput Analysis
# ========================================
QUERY=$(cat <<EOF
SELECT
    run_id,
    run_type,
    COUNT(*) as total_queries,
    ROUND((MAX(CAST(timestamp_epoch AS BIGINT)) - MIN(CAST(timestamp_epoch AS BIGINT))) / 1000.0, 2) as duration_sec,
    ROUND(COUNT(*) * 1.0 / ((MAX(CAST(timestamp_epoch AS BIGINT)) - MIN(CAST(timestamp_epoch AS BIGINT))) / 1000.0), 2) as queries_per_sec,
    ROUND(COUNT(*) * 60.0 / ((MAX(CAST(timestamp_epoch AS BIGINT)) - MIN(CAST(timestamp_epoch AS BIGINT))) / 1000.0), 2) as queries_per_min
FROM jmeter_query_results
WHERE engine = '$ENGINE'
  AND cluster_size = '$CLUSTER_SIZE'
  AND benchmark = '$BENCHMARK'
  AND timestamp_epoch IS NOT NULL
GROUP BY run_id, run_type
HAVING (MAX(CAST(timestamp_epoch AS BIGINT)) - MIN(CAST(timestamp_epoch AS BIGINT))) > 0
ORDER BY run_type, run_id DESC
EOF
)

if execute_query "$QUERY" "$OUTPUT_DIR/06_throughput.csv" "Throughput Analysis"; then
    ((REPORTS_GENERATED++))
else
    ((REPORTS_FAILED++))
fi

# ========================================
# REPORT 7: Thread Performance Analysis
# ========================================
QUERY=$(cat <<EOF
SELECT
    run_id,
    thread_name,
    COUNT(*) as queries_executed,
    ROUND(AVG(CAST(elapsed_time_ms AS DOUBLE)) / 1000.0, 2) as avg_latency_sec,
    ROUND(APPROX_PERCENTILE(CAST(elapsed_time_ms AS DOUBLE) / 1000.0, 0.90), 2) as p90_sec,
    ROUND(APPROX_PERCENTILE(CAST(elapsed_time_ms AS DOUBLE) / 1000.0, 0.99), 2) as p99_sec
FROM jmeter_query_results
WHERE engine = '$ENGINE'
  AND cluster_size = '$CLUSTER_SIZE'
  AND benchmark = '$BENCHMARK'
  AND elapsed_time_ms IS NOT NULL
GROUP BY run_id, thread_name
ORDER BY run_id DESC, avg_latency_sec DESC
LIMIT 50
EOF
)

if execute_query "$QUERY" "$OUTPUT_DIR/07_thread_performance.csv" "Thread Performance"; then
    ((REPORTS_GENERATED++))
else
    ((REPORTS_FAILED++))
fi

# ========================================
# REPORT 8: Query Performance Over Time
# ========================================
QUERY=$(cat <<EOF
SELECT
    label as query_name,
    run_id,
    run_type,
    COUNT(*) as executions,
    ROUND(AVG(CAST(elapsed_time_ms AS DOUBLE)) / 1000.0, 2) as avg_sec,
    ROUND(APPROX_PERCENTILE(CAST(elapsed_time_ms AS DOUBLE) / 1000.0, 0.99), 2) as p99_sec
FROM jmeter_query_results
WHERE engine = '$ENGINE'
  AND cluster_size = '$CLUSTER_SIZE'
  AND benchmark = '$BENCHMARK'
  AND elapsed_time_ms IS NOT NULL
GROUP BY label, run_id, run_type
ORDER BY label, run_id DESC
EOF
)

if execute_query "$QUERY" "$OUTPUT_DIR/08_query_trends.csv" "Query Performance Over Time"; then
    ((REPORTS_GENERATED++))
else
    ((REPORTS_FAILED++))
fi

# ========================================
# REPORT 9: Latest Run Summary
# ========================================
QUERY=$(cat <<EOF
WITH latest_runs AS (
    SELECT run_type, MAX(run_id) as run_id
    FROM jmeter_query_results
    WHERE engine = '$ENGINE'
      AND cluster_size = '$CLUSTER_SIZE'
      AND benchmark = '$BENCHMARK'
    GROUP BY run_type
)
SELECT
    r.run_type,
    r.run_id,
    COUNT(*) as total_queries,
    SUM(CASE WHEN success = 'true' THEN 1 ELSE 0 END) as successful,
    ROUND(AVG(CAST(elapsed_time_ms AS DOUBLE)) / 1000.0, 2) as avg_sec,
    ROUND(APPROX_PERCENTILE(CAST(elapsed_time_ms AS DOUBLE) / 1000.0, 0.50), 2) as p50_sec,
    ROUND(APPROX_PERCENTILE(CAST(elapsed_time_ms AS DOUBLE) / 1000.0, 0.90), 2) as p90_sec,
    ROUND(APPROX_PERCENTILE(CAST(elapsed_time_ms AS DOUBLE) / 1000.0, 0.95), 2) as p95_sec,
    ROUND(APPROX_PERCENTILE(CAST(elapsed_time_ms AS DOUBLE) / 1000.0, 0.99), 2) as p99_sec,
    ROUND(MIN(CAST(elapsed_time_ms AS DOUBLE)) / 1000.0, 2) as min_sec,
    ROUND(MAX(CAST(elapsed_time_ms AS DOUBLE)) / 1000.0, 2) as max_sec
FROM jmeter_query_results r
INNER JOIN latest_runs l ON r.run_type = l.run_type AND r.run_id = l.run_id
WHERE r.engine = '$ENGINE'
  AND r.cluster_size = '$CLUSTER_SIZE'
  AND r.benchmark = '$BENCHMARK'
  AND r.elapsed_time_ms IS NOT NULL
GROUP BY r.run_type, r.run_id
ORDER BY r.run_type
EOF
)

if execute_query "$QUERY" "$OUTPUT_DIR/09_latest_run_summary.csv" "Latest Run Summary"; then
    ((REPORTS_GENERATED++))
else
    ((REPORTS_FAILED++))
fi

# ========================================
# REPORT 10: Error Analysis
# ========================================
QUERY=$(cat <<EOF
SELECT
    run_id,
    response_code,
    response_message,
    COUNT(*) as error_count,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) as error_pct
FROM jmeter_query_results
WHERE engine = '$ENGINE'
  AND cluster_size = '$CLUSTER_SIZE'
  AND benchmark = '$BENCHMARK'
  AND success != 'true'
GROUP BY run_id, response_code, response_message
ORDER BY error_count DESC
LIMIT 50
EOF
)

if execute_query "$QUERY" "$OUTPUT_DIR/10_error_analysis.csv" "Error Analysis"; then
    ((REPORTS_GENERATED++))
else
    ((REPORTS_FAILED++))
fi

# ========================================
# Generate Summary README
# ========================================
cat > "$OUTPUT_DIR/README.txt" <<EOF
JMeter Comprehensive Analysis Reports
======================================

Generated: $(date)
Engine: $ENGINE
Cluster Size: $CLUSTER_SIZE
Benchmark: $BENCHMARK

Reports Generated:
------------------
01_concurrency_scaling.csv    - Performance metrics by concurrency level
02_query_performance.csv      - Individual query performance breakdown
03_run_comparison.csv          - Latest vs previous run comparison
04_slowest_queries.csv         - Top 10 slowest query executions
05_success_rate.csv            - Success/failure rates by concurrency
06_throughput.csv              - QPS and QPM analysis
07_thread_performance.csv      - Per-thread performance metrics
08_query_trends.csv            - Query performance trends over time
09_latest_run_summary.csv      - Summary of most recent runs
10_error_analysis.csv          - Error breakdown and analysis

Usage:
------
All files are in CSV format and can be opened in Excel, imported into
data analysis tools, or processed with command-line tools like csvkit.

Examples:
  # View in terminal
  column -t -s, < 01_concurrency_scaling.csv | less -S

  # Sort by specific column
  csvcut -c query_name,avg_latency_sec 02_query_performance.csv | csvsort -c avg_latency_sec -r

Notes:
------
- All latency values are in seconds
- Timestamps are in epoch milliseconds
- NULL values indicate missing or invalid data
- Percentiles: p50 (median), p90, p95, p99

EOF

echo "=========================================="
echo "Report Generation Complete"
echo "=========================================="
echo "✅ Successfully generated: $REPORTS_GENERATED reports"
echo "❌ Failed: $REPORTS_FAILED reports"
echo ""
echo "Output directory: $OUTPUT_DIR"
echo ""
echo "Available reports:"
ls -lh "$OUTPUT_DIR"/*.csv 2>/dev/null | awk '{print "  " $9 " (" $5 ")"}'
echo ""
echo "View README: cat $OUTPUT_DIR/README.txt"
echo "=========================================="
