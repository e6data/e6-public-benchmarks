#!/bin/bash
# Generate Athena SQL Query Files for Analysis
#
# This script creates a timestamped directory with ready-to-use SQL queries
# extracted from ATHENA_QUERIES_UPDATED.sql and parameterized for your engine/cluster.
#
# Usage:
#   ./utilities/athena/generate_report_queries.sh <engine> <cluster_size> <benchmark> [output_dir]
#
# Examples:
#   ./utilities/athena/generate_report_queries.sh e6data S-2x2 tpcds_29_1tb
#   ./utilities/athena/generate_report_queries.sh dbr S-4x4 tpcds_51_1tb reports/my_analysis
#
# Output:
#   Creates directory with 8 parameterized SQL query files ready for Athena

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Input validation
if [ $# -lt 3 ]; then
    echo "Usage: $0 <engine> <cluster_size> <benchmark> [output_dir]"
    echo ""
    echo "Arguments:"
    echo "  engine        - Database engine (e.g., e6data, dbr)"
    echo "  cluster_size  - Cluster size (e.g., S-2x2, M-4x4)"
    echo "  benchmark     - Benchmark name (e.g., tpcds_29_1tb)"
    echo "  output_dir    - Optional output directory (default: reports/athena_reports_TIMESTAMP)"
    echo ""
    echo "Examples:"
    echo "  $0 e6data S-2x2 tpcds_29_1tb"
    echo "  $0 dbr S-4x4 tpcds_51_1tb reports/my_custom_analysis"
    exit 1
fi

ENGINE="$1"
CLUSTER_SIZE="$2"
BENCHMARK="$3"
OUTPUT_DIR="${4:-reports/athena_reports_$(date +%Y%m%d_%H%M%S)}"

mkdir -p "$OUTPUT_DIR"

echo "=========================================="
echo "Generating Athena Query Files"
echo "=========================================="
echo "Engine:       $ENGINE"
echo "Cluster:      $CLUSTER_SIZE"
echo "Benchmark:    $BENCHMARK"
echo "Output:       $OUTPUT_DIR"
echo "=========================================="
echo ""

# Query 1: Valid Runs Only (Exclude Outliers)
echo "📊 Creating Query 1: Valid Runs Only"
cat > "$OUTPUT_DIR/01_valid_runs.sql" << EOF
-- Valid Runs Only - Exclude outliers
-- Use this as your default query
SELECT
    engine,
    cluster_size,
    instance_type,
    benchmark,
    run_type,
    run_id,
    run_date,
    ROUND(queries_per_second, 2) as qps,
    ROUND(avg_latency_sec, 2) as avg_time,
    ROUND(p50_latency_sec, 2) as p50,
    ROUND(p90_latency_sec, 2) as p90,
    ROUND(p95_latency_sec, 2) as p95,
    ROUND(p99_latency_sec, 2) as p99,
    ROUND(total_time_taken_sec, 2) as test_duration_sec,
    total_success,
    total_failed,
    is_outlier
FROM jmeter_runs_index
WHERE is_outlier = 'no'
  AND engine = '$ENGINE'
  AND cluster_size = '$CLUSTER_SIZE'
  AND benchmark = '$BENCHMARK'
ORDER BY run_type, run_date DESC;
EOF

# Query 2: Throughput Analysis
echo "📊 Creating Query 2: Throughput Analysis"
cat > "$OUTPUT_DIR/02_throughput_analysis.sql" << EOF
-- Throughput Analysis - Compare QPS across runs
SELECT
    run_type,
    run_id,
    run_date,
    ROUND(queries_per_second, 2) as qps,
    ROUND(queries_per_minute, 2) as qpm,
    ROUND(avg_latency_sec, 2) as avg_time,
    ROUND(total_time_taken_sec / 60, 1) as test_duration_min,
    total_success,
    is_outlier
FROM jmeter_runs_index
WHERE is_outlier = 'no'
  AND engine = '$ENGINE'
  AND cluster_size = '$CLUSTER_SIZE'
  AND benchmark = '$BENCHMARK'
  AND run_type LIKE 'concurrency_%'
ORDER BY run_type, queries_per_second DESC;
EOF

# Query 3: Best Runs (Lowest p90 per Configuration)
echo "📊 Creating Query 3: Best Runs"
cat > "$OUTPUT_DIR/03_best_runs.sql" << EOF
-- Best runs per configuration (lowest p90)
WITH ranked_runs AS (
    SELECT
        run_type,
        run_id,
        run_date,
        instance_type,
        ROUND(queries_per_second, 2) as qps,
        ROUND(avg_latency_sec, 2) as avg_time,
        ROUND(p90_latency_sec, 2) as p90,
        ROUND(p95_latency_sec, 2) as p95,
        ROUND(p99_latency_sec, 2) as p99,
        total_success,
        ROW_NUMBER() OVER (PARTITION BY run_type, instance_type ORDER BY p90_latency_sec ASC) as rank
    FROM jmeter_runs_index
    WHERE run_type LIKE 'concurrency_%'
      AND is_outlier = 'no'
      AND engine = '$ENGINE'
      AND cluster_size = '$CLUSTER_SIZE'
      AND benchmark = '$BENCHMARK'
)
SELECT *
FROM ranked_runs
WHERE rank = 1
ORDER BY run_type, instance_type;
EOF

# Query 4: Concurrency Scaling Analysis
echo "📊 Creating Query 4: Concurrency Scaling"
cat > "$OUTPUT_DIR/04_concurrency_scaling.sql" << EOF
-- How performance scales with concurrency
SELECT
    run_type,
    COUNT(*) as valid_runs,
    ROUND(AVG(queries_per_second), 2) as avg_qps,
    ROUND(AVG(avg_latency_sec), 2) as avg_latency,
    ROUND(AVG(p90_latency_sec), 2) as avg_p90,
    ROUND(AVG(p95_latency_sec), 2) as avg_p95,
    ROUND(AVG(p99_latency_sec), 2) as avg_p99,
    ROUND(MIN(p90_latency_sec), 2) as best_p90,
    ROUND(MAX(p90_latency_sec), 2) as worst_p90
FROM jmeter_runs_index
WHERE is_outlier = 'no'
  AND engine = '$ENGINE'
  AND cluster_size = '$CLUSTER_SIZE'
  AND benchmark = '$BENCHMARK'
  AND run_type LIKE 'concurrency_%'
GROUP BY run_type
ORDER BY run_type;
EOF

# Query 5: Outlier Detection
echo "📊 Creating Query 5: Outlier Detection"
cat > "$OUTPUT_DIR/05_outlier_detection.sql" << EOF
-- Show all runs including marked outliers
SELECT
    run_type,
    run_id,
    run_date,
    is_outlier,
    ROUND(avg_latency_sec, 2) as avg_time,
    ROUND(p90_latency_sec, 2) as p90,
    ROUND(p95_latency_sec, 2) as p95,
    ROUND(p99_latency_sec, 2) as p99,
    total_success,
    total_failed,
    error_rate_pct
FROM jmeter_runs_index
WHERE engine = '$ENGINE'
  AND cluster_size = '$CLUSTER_SIZE'
  AND benchmark = '$BENCHMARK'
ORDER BY run_type, is_outlier DESC, run_date DESC;
EOF

# Query 6: Performance Summary
echo "📊 Creating Query 6: Performance Summary"
cat > "$OUTPUT_DIR/06_performance_summary.sql" << EOF
-- Aggregated stats by configuration
SELECT
    run_type,
    instance_type,
    COUNT(*) as valid_runs,
    COUNT(CASE WHEN is_outlier = 'yes' THEN 1 END) as outlier_runs,
    ROUND(AVG(queries_per_second), 2) as avg_qps,
    ROUND(AVG(avg_latency_sec), 2) as avg_of_avg,
    ROUND(AVG(p90_latency_sec), 2) as avg_p90,
    ROUND(AVG(p95_latency_sec), 2) as avg_p95,
    ROUND(AVG(p99_latency_sec), 2) as avg_p99,
    ROUND(MIN(p90_latency_sec), 2) as best_p90,
    ROUND(MAX(p90_latency_sec), 2) as worst_p90,
    ROUND(STDDEV(p90_latency_sec), 2) as p90_stddev
FROM jmeter_runs_index
WHERE engine = '$ENGINE'
  AND cluster_size = '$CLUSTER_SIZE'
  AND benchmark = '$BENCHMARK'
GROUP BY run_type, instance_type
ORDER BY run_type, instance_type;
EOF

# Query 7: Recent Runs Health Check
echo "📊 Creating Query 7: Recent Runs Health Check"
cat > "$OUTPUT_DIR/07_recent_runs.sql" << EOF
-- Last 20 runs with key metrics
SELECT
    run_id,
    run_date,
    run_type,
    instance_type,
    is_outlier,
    ROUND(queries_per_second, 2) as qps,
    ROUND(avg_latency_sec, 2) as avg,
    ROUND(p90_latency_sec, 2) as p90,
    ROUND(p99_latency_sec, 2) as p99,
    total_success,
    total_failed
FROM jmeter_runs_index
WHERE engine = '$ENGINE'
  AND cluster_size = '$CLUSTER_SIZE'
  AND benchmark = '$BENCHMARK'
ORDER BY run_date DESC
LIMIT 20;
EOF

# Query 8: Timestamped Files Verification
echo "📊 Creating Query 8: File Verification"
cat > "$OUTPUT_DIR/08_file_verification.sql" << EOF
-- Verify append behavior is working (multiple files per partition)
SELECT
    run_type,
    COUNT(DISTINCT run_id) as total_runs,
    COUNT(DISTINCT CASE WHEN is_outlier = 'no' THEN run_id END) as valid_runs,
    COUNT(DISTINCT CASE WHEN is_outlier = 'yes' THEN run_id END) as outlier_runs,
    MIN(run_date) as oldest_run,
    MAX(run_date) as latest_run
FROM jmeter_runs_index
WHERE engine = '$ENGINE'
  AND cluster_size = '$CLUSTER_SIZE'
  AND benchmark = '$BENCHMARK'
GROUP BY run_type
ORDER BY run_type;
EOF

# Create README
echo "📊 Creating README"
cat > "$OUTPUT_DIR/README.md" << EOF
# Athena Query Reports - $ENGINE / $CLUSTER_SIZE / $BENCHMARK

Generated: $(date '+%Y-%m-%d %H:%M:%S')

## Configuration

- **Engine**: $ENGINE
- **Cluster Size**: $CLUSTER_SIZE
- **Benchmark**: $BENCHMARK

## Available Queries

### 1. Valid Runs Only (\`01_valid_runs.sql\`)
Default query excluding marked outliers. Use this for standard analysis.

### 2. Throughput Analysis (\`02_throughput_analysis.sql\`)
Compare queries-per-second (QPS) across runs to identify throughput variations.

### 3. Best Runs (\`03_best_runs.sql\`)
Find the best performing run (lowest p90) for each concurrency level and instance type.

### 4. Concurrency Scaling (\`04_concurrency_scaling.sql\`)
Analyze how performance scales as concurrency increases.

### 5. Outlier Detection (\`05_outlier_detection.sql\`)
Show ALL runs including those marked as outliers for review.

### 6. Performance Summary (\`06_performance_summary.sql\`)
Aggregated statistics across all valid runs per configuration.

### 7. Recent Runs Health Check (\`07_recent_runs.sql\`)
Quick health check showing last 20 runs with key metrics.

### 8. Timestamped Files Verification (\`08_file_verification.sql\`)
Verify that multiple timestamped files per partition are working correctly.

## How to Use

### In Athena Console:

1. Open AWS Athena Console
2. Select database: \`jmeter_benchmarks\`
3. Open any \`.sql\` file from this directory
4. Copy/paste the query into Athena
5. Click "Run query"
6. Download results as CSV using "Download results" button

### Command Line:

\`\`\`bash
aws athena start-query-execution \\
  --query-string file://$OUTPUT_DIR/01_valid_runs.sql \\
  --result-configuration OutputLocation=s3://your-bucket/results/ \\
  --query-execution-context Database=jmeter_benchmarks
\`\`\`

### Python (boto3):

\`\`\`python
import boto3

athena = boto3.client('athena')

with open('$OUTPUT_DIR/01_valid_runs.sql', 'r') as f:
    query = f.read()

response = athena.start_query_execution(
    QueryString=query,
    QueryExecutionContext={'Database': 'jmeter_benchmarks'},
    ResultConfiguration={'OutputLocation': 's3://your-bucket/results/'}
)
\`\`\`

## File Format

- **Athena Index**: JSONL format (JSON Lines)
- **S3 Files**: Timestamped for append behavior (\`data_YYYYMMDD_HHMMSS.jsonl\`)
- **JMeter Reports**: CSV format (AggregateReport.csv, JmeterResultFile.csv)
- **Query Results**: Can be exported as CSV from Athena

## Related Documentation

- Full queries: \`utilities/athena/ATHENA_QUERIES_UPDATED.sql\`
- Append behavior: \`utilities/athena/APPEND_BEHAVIOR_README.md\`
- Setup guide: \`utilities/athena/ATHENA_SYNC_GUIDE.md\`
- Compaction: \`utilities/athena/compact_athena_partition.sh\`
EOF

echo ""
echo "=========================================="
echo "✅ Query Files Generated!"
echo "=========================================="
echo "Location: $OUTPUT_DIR"
echo ""
echo "Generated Files:"
ls -1 "$OUTPUT_DIR"/*.sql | sed 's/^/  /'
echo ""
echo "  README.md"
echo ""
echo "Next Steps:"
echo "  1. Open any .sql file in Athena Console"
echo "  2. Copy/paste the query"
echo "  3. Run and download results as CSV"
echo ""
echo "Or run all queries programmatically:"
echo "  for sql in $OUTPUT_DIR/*.sql; do"
echo "    aws athena start-query-execution --query-string file://\$sql ..."
echo "  done"
echo ""
