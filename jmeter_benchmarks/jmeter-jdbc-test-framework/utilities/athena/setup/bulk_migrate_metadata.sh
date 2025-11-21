#!/bin/bash
# Bulk migration script for jmeter_run_metadata (HYBRID APPROACH)
# - Extracts metadata from test_result.json files in S3
# - Transforms to JSONL format
# - Uploads to s3://e6-jmeter/athena-tables/run_metadata/
# - Results table uses existing CSV files (no migration needed)
#
# Usage:
#   ./bulk_migrate_metadata.sh                    # Interactive mode
#   ./bulk_migrate_metadata.sh --engine e6data --cluster S-2x2 --benchmark tpcds_29_1tb

set -e  # Exit on error

# Default values
ENGINE=""
CLUSTER_SIZE=""
BENCHMARK=""
RUN_TYPES=("sequential" "concurrency_1" "concurrency_2" "concurrency_4" "concurrency_8" "concurrency_12" "concurrency_16")
OUTPUT_DIR="/tmp/metadata_migration"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ATHENA_DIR="$(dirname "$SCRIPT_DIR")"
DATABASE="default"

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --engine)
            ENGINE="$2"
            shift 2
            ;;
        --cluster)
            CLUSTER_SIZE="$2"
            shift 2
            ;;
        --benchmark)
            BENCHMARK="$2"
            shift 2
            ;;
        --database)
            DATABASE="$2"
            shift 2
            ;;
        --output)
            OUTPUT_DIR="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--engine ENGINE] [--cluster CLUSTER_SIZE] [--benchmark BENCHMARK]"
            exit 1
            ;;
    esac
done

# Interactive mode if arguments not provided
if [ -z "$ENGINE" ]; then
    echo "Enter engine (e6data, databricks, trino, etc.):"
    read ENGINE
fi

if [ -z "$CLUSTER_SIZE" ]; then
    echo "Enter cluster size (S-2x2, M-4x4, etc.):"
    read CLUSTER_SIZE
fi

if [ -z "$BENCHMARK" ]; then
    echo "Enter benchmark (tpcds_29_1tb, tpcds_51_1tb, etc.):"
    read BENCHMARK
fi

echo "=========================================="
echo "Metadata Bulk Migration (HYBRID APPROACH)"
echo "=========================================="
echo "Engine: $ENGINE"
echo "Cluster: $CLUSTER_SIZE"
echo "Benchmark: $BENCHMARK"
echo "Output: $OUTPUT_DIR"
echo "Database: $DATABASE"
echo ""
echo "HYBRID APPROACH:"
echo "  ✓ Metadata: Transform to JSONL and upload"
echo "  ✓ Results: Use existing CSV files (no migration)"
echo "=========================================="
echo ""

# Create output directory
mkdir -p "$OUTPUT_DIR"

# Track progress
TOTAL_RUN_TYPES=0
SUCCESSFUL_GENERATIONS=0
SUCCESSFUL_UPLOADS=0
TOTAL_RECORDS=0

# Process each run_type
for RUN_TYPE in "${RUN_TYPES[@]}"; do
    S3_PATH="s3://e6-jmeter/jmeter-results/engine=${ENGINE}/cluster_size=${CLUSTER_SIZE}/benchmark=${BENCHMARK}/run_type=${RUN_TYPE}/"

    echo "================================================"
    echo "Processing: $RUN_TYPE"
    echo "================================================"

    # Check if path exists in S3
    if ! aws s3 ls "$S3_PATH" >/dev/null 2>&1; then
        echo "⚠️  Path does not exist in S3, skipping: $S3_PATH"
        echo ""
        continue
    fi

    TOTAL_RUN_TYPES=$((TOTAL_RUN_TYPES + 1))

    # Step 1: Generate metadata index
    echo "📊 Generating metadata index..."
    if python3 "$ATHENA_DIR/generate_metadata_index.py" "$S3_PATH" --output "$OUTPUT_DIR" 2>&1 | grep -q "Successfully processed"; then
        echo "✓ Metadata index generated"
        SUCCESSFUL_GENERATIONS=$((SUCCESSFUL_GENERATIONS + 1))
    else
        echo "❌ Failed to generate metadata index"
        echo ""
        continue
    fi

    # Count records generated
    METADATA_FILE="$OUTPUT_DIR/engine=${ENGINE}/cluster_size=${CLUSTER_SIZE}/metadata.jsonl"
    if [ -f "$METADATA_FILE" ]; then
        RECORD_COUNT=$(wc -l < "$METADATA_FILE")
        TOTAL_RECORDS=$((TOTAL_RECORDS + RECORD_COUNT))
        echo "  Records in metadata file: $RECORD_COUNT"
    fi

    echo ""
done

# Upload all metadata to S3
if [ $SUCCESSFUL_GENERATIONS -gt 0 ]; then
    echo "================================================"
    echo "Uploading Metadata to S3"
    echo "================================================"

    if python3 "$ATHENA_DIR/upload_metadata.py" "$OUTPUT_DIR" --database "$DATABASE" 2>&1 | grep -q "METADATA UPLOAD COMPLETE"; then
        echo "✅ Metadata uploaded successfully"
        SUCCESSFUL_UPLOADS=1
    else
        echo "❌ Metadata upload failed"
    fi

    echo ""
fi

# Repair partitions for query results table (CSV-based)
echo "================================================"
echo "Repairing Query Results Partitions"
echo "================================================"
echo "The jmeter_query_results table uses existing CSV files."
echo "Running MSCK REPAIR TABLE to discover partitions..."
echo ""

QUERY_ID=$(aws athena start-query-execution \
    --query-string "MSCK REPAIR TABLE jmeter_query_results" \
    --query-execution-context Database="$DATABASE" \
    --result-configuration OutputLocation=s3://e6-jmeter/athena-query-results/ \
    --output text \
    --query 'QueryExecutionId' 2>/dev/null || echo "FAILED")

if [ "$QUERY_ID" != "FAILED" ]; then
    echo "✓ Query results partition repair submitted: $QUERY_ID"
    sleep 3

    STATUS=$(aws athena get-query-execution \
        --query-execution-id "$QUERY_ID" \
        --output text \
        --query 'QueryExecution.Status.State' 2>/dev/null || echo "UNKNOWN")

    if [ "$STATUS" = "SUCCEEDED" ]; then
        echo "✅ Query results partitions repaired"
    else
        echo "⚠️  Partition repair status: $STATUS"
    fi
else
    echo "❌ Failed to submit partition repair query"
fi

echo ""
echo "================================================"
echo "Migration Summary"
echo "================================================"
echo "Run types processed: $TOTAL_RUN_TYPES"
echo "Successful metadata generations: $SUCCESSFUL_GENERATIONS"
echo "Total metadata records: $TOTAL_RECORDS"
echo "Metadata uploaded: $([ $SUCCESSFUL_UPLOADS -eq 1 ] && echo 'Yes' || echo 'No')"
echo "================================================"
echo ""

if [ $SUCCESSFUL_UPLOADS -eq 1 ]; then
    echo "✅ MIGRATION COMPLETE!"
    echo ""
    echo "Verify your data in Athena:"
    echo ""
    echo "1. Check metadata table:"
    echo "   SELECT COUNT(*) as metadata_count"
    echo "   FROM ${DATABASE}.jmeter_run_metadata"
    echo "   WHERE engine='$ENGINE' AND cluster_size='$CLUSTER_SIZE';"
    echo ""
    echo "2. Check query results table (CSV-based, no transformation):"
    echo "   SELECT COUNT(*) as results_count"
    echo "   FROM ${DATABASE}.jmeter_query_results"
    echo "   WHERE engine='$ENGINE' AND cluster_size='$CLUSTER_SIZE';"
    echo ""
    echo "3. JOIN metadata with results (query-level analysis):"
    echo "   SELECT m.run_id, m.instance_type, r.label as query_name,"
    echo "          AVG(r.elapsed_time_ms)/1000.0 as avg_response_sec"
    echo "   FROM ${DATABASE}.jmeter_run_metadata m"
    echo "   INNER JOIN ${DATABASE}.jmeter_query_results r ON m.run_id = r.run_id"
    echo "   WHERE m.engine='$ENGINE' AND m.cluster_size='$CLUSTER_SIZE'"
    echo "   GROUP BY m.run_id, m.instance_type, r.label"
    echo "   LIMIT 10;"
    echo ""
    echo "Output directory: $OUTPUT_DIR"
    echo "(Safe to delete after verifying Athena data)"
else
    echo "❌ Migration failed or incomplete"
    echo "Check errors above for details"
    exit 1
fi
