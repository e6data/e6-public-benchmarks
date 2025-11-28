#!/bin/bash
# Export all fields from jmeter_runs_index for spreadsheet analysis

if [ "$#" -lt 3 ]; then
    echo "Usage: $0 <engine> <cluster_size> <benchmark> [output_file]"
    echo "Example: $0 e6data S-2x2 tpcds_29_1tb reports/full_export.csv"
    exit 1
fi

ENGINE="$1"
CLUSTER_SIZE="$2"
BENCHMARK="$3"
OUTPUT_FILE="${4:-reports/full_export_$(date +%Y%m%d_%H%M%S).csv}"

ATHENA_DATABASE="${ATHENA_DATABASE:-jmeter_analysis}"

echo "==========================================="
echo "Full Data Export for Spreadsheet Analysis"
echo "==========================================="
echo "Engine: $ENGINE"
echo "Cluster: $CLUSTER_SIZE"
echo "Benchmark: $BENCHMARK"
echo "Output: $OUTPUT_FILE"
echo "==========================================="
echo ""

# Create output directory if needed
mkdir -p "$(dirname "$OUTPUT_FILE")"

# SQL query to export all fields (except complex array types)
QUERY="
SELECT
    run_id,
    run_date,
    engine,
    cluster_size,
    instance_type,
    benchmark,
    run_type,
    status,
    s3_path,
    estimated_cores,
    executors,
    cores_per_executor,
    serverless,
    cluster_hostname,
    test_plan_file,
    concurrent_threads,
    total_query_count,
    hold_period_min,
    ramp_up_time_sec,
    query_timeout_sec,
    random_order,
    total_samples,
    actual_considered_queries,
    excluded_queries,
    total_success,
    total_failed,
    error_rate_pct,
    total_time_taken_sec,
    avg_latency_sec,
    median_latency_sec,
    min_latency_sec,
    max_latency_sec,
    p50_latency_sec,
    p90_latency_sec,
    p95_latency_sec,
    p99_latency_sec,
    queries_per_minute,
    queries_per_second,
    avg_throughput_qpm,
    performance_rating,
    consistency_rating,
    bytes_received_total,
    bytes_sent_total,
    avg_bytes_per_query,
    run_mode,
    customer,
    config,
    tags,
    comments,
    is_outlier,
    outlier_severity,
    p90_z_score,
    p90_deviation_pct,
    p95_z_score,
    p95_deviation_pct,
    p99_z_score,
    p99_deviation_pct,
    is_best,
    is_baseline,
    baseline_marked_by,
    baseline_marked_date,
    baseline_notes
FROM jmeter_runs_index
WHERE engine = '$ENGINE'
  AND cluster_size = '$CLUSTER_SIZE'
  AND benchmark = '$BENCHMARK'
ORDER BY run_date DESC, run_type, run_id DESC
"

echo "Executing query..."
EXEC_ID=$(aws athena start-query-execution \
    --query-string "$QUERY" \
    --query-execution-context Database="$ATHENA_DATABASE" \
    --result-configuration OutputLocation=s3://e6-jmeter/athena-query-results/ \
    --output text --query 'QueryExecutionId')

echo "Query ID: $EXEC_ID"
echo -n "Waiting for results"

# Wait for completion
for i in {1..60}; do
    STATUS=$(aws athena get-query-execution \
        --query-execution-id "$EXEC_ID" \
        --output text --query 'QueryExecution.Status.State')
    
    if [[ "$STATUS" == "SUCCEEDED" ]]; then
        echo " ✓"
        break
    elif [[ "$STATUS" == "FAILED" ]] || [[ "$STATUS" == "CANCELLED" ]]; then
        echo " ✗"
        echo "Query failed!"
        aws athena get-query-execution --query-execution-id "$EXEC_ID" | \
            jq -r '.QueryExecution.Status.StateChangeReason'
        exit 1
    fi
    
    echo -n "."
    sleep 2
done

# Download results and convert to CSV
echo "Downloading results..."
aws athena get-query-results \
    --query-execution-id "$EXEC_ID" \
    --output json | \
    jq -r '.ResultSet.Rows[] | .Data | map(.VarCharValue // "") | @csv' > "$OUTPUT_FILE"

ROW_COUNT=$(wc -l < "$OUTPUT_FILE")

echo ""
echo "==========================================="
echo "Export Complete!"
echo "==========================================="
echo "File: $OUTPUT_FILE"
echo "Rows: $((ROW_COUNT - 1)) (plus header)"
echo "Size: $(du -h "$OUTPUT_FILE" | awk '{print $1}')"
echo ""
echo "This CSV contains ALL fields and can be imported into:"
echo "  - Google Sheets"
echo "  - Microsoft Excel"
echo "  - Tableau"
echo "  - Any other data analysis tool"
echo ""
echo "You can now slice and dice the data by any dimension!"
echo "==========================================="
