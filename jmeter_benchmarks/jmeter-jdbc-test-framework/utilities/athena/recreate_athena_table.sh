#!/bin/bash
# Recreate Athena table with updated schema and re-upload data
#
# This script:
# 1. Drops the existing jmeter_runs_index table
# 2. Creates new table with updated schema (includes is_outlier, baseline columns)
# 3. Re-uploads all data for specified configuration
#
# Usage:
#   ./utilities/athena/recreate_athena_table.sh <engine> <cluster_size> <benchmark>
#
# Example:
#   ./utilities/athena/recreate_athena_table.sh e6data S-2x2 tpcds_29_1tb

set -e

ENGINE="${1:-e6data}"
CLUSTER_SIZE="${2:-S-2x2}"
BENCHMARK="${3:-tpcds_29_1tb}"
# Run types to sync: concurrency levels + sequential
RUN_TYPES=("concurrency_2" "concurrency_4" "concurrency_8" "concurrency_12" "concurrency_16" "sequential")

ATHENA_DATABASE="${ATHENA_DATABASE:-jmeter_analysis}"
ATHENA_WORKGROUP="${ATHENA_WORKGROUP:-primary}"
ATHENA_OUTPUT_LOCATION="${ATHENA_OUTPUT_LOCATION:-s3://e6-jmeter/athena-query-results/}"

echo "=========================================="
echo "Athena Table Recreation"
echo "=========================================="
echo "Engine: $ENGINE"
echo "Cluster: $CLUSTER_SIZE"
echo "Benchmark: $BENCHMARK"
echo "Database: $ATHENA_DATABASE"
echo "Workgroup: $ATHENA_WORKGROUP"
echo "=========================================="
echo ""

# Step 1: Drop existing table
echo "Step 1: Dropping existing table..."
echo "----------------------------------------"
DROP_QUERY="DROP TABLE IF EXISTS jmeter_runs_index;"

aws athena start-query-execution \
  --query-string "$DROP_QUERY" \
  --query-execution-context Database="$ATHENA_DATABASE" \
  --work-group "$ATHENA_WORKGROUP" \
  --result-configuration OutputLocation="$ATHENA_OUTPUT_LOCATION" \
  > /tmp/athena_drop_execution.json

DROP_EXECUTION_ID=$(jq -r '.QueryExecutionId' /tmp/athena_drop_execution.json)
echo "Submitted DROP query: $DROP_EXECUTION_ID"

# Wait for DROP to complete
echo -n "Waiting for DROP to complete"
while true; do
  STATUS=$(aws athena get-query-execution --query-execution-id "$DROP_EXECUTION_ID" | jq -r '.QueryExecution.Status.State')
  if [[ "$STATUS" == "SUCCEEDED" ]]; then
    echo " ✓"
    break
  elif [[ "$STATUS" == "FAILED" ]] || [[ "$STATUS" == "CANCELLED" ]]; then
    echo " ✗"
    echo "DROP query failed!"
    aws athena get-query-execution --query-execution-id "$DROP_EXECUTION_ID" | jq '.QueryExecution.Status'
    exit 1
  fi
  echo -n "."
  sleep 2
done

echo ""

# Step 2: Create table with new schema
echo "Step 2: Creating table with updated schema..."
echo "----------------------------------------"
CREATE_SQL_FILE="utilities/athena/setup_athena_runs_index.sql"

if [ ! -f "$CREATE_SQL_FILE" ]; then
  echo "❌ Error: Schema file not found: $CREATE_SQL_FILE"
  exit 1
fi

# Read the CREATE TABLE statement (skip comments and empty lines)
CREATE_QUERY=$(grep -v '^--' "$CREATE_SQL_FILE" | grep -v '^$' | head -n 108)

aws athena start-query-execution \
  --query-string "$CREATE_QUERY" \
  --query-execution-context Database="$ATHENA_DATABASE" \
  --work-group "$ATHENA_WORKGROUP" \
  --result-configuration OutputLocation="$ATHENA_OUTPUT_LOCATION" \
  > /tmp/athena_create_execution.json

CREATE_EXECUTION_ID=$(jq -r '.QueryExecutionId' /tmp/athena_create_execution.json)
echo "Submitted CREATE query: $CREATE_EXECUTION_ID"

# Wait for CREATE to complete
echo -n "Waiting for CREATE to complete"
while true; do
  STATUS=$(aws athena get-query-execution --query-execution-id "$CREATE_EXECUTION_ID" | jq -r '.QueryExecution.Status.State')
  if [[ "$STATUS" == "SUCCEEDED" ]]; then
    echo " ✓"
    break
  elif [[ "$STATUS" == "FAILED" ]] || [[ "$STATUS" == "CANCELLED" ]]; then
    echo " ✗"
    echo "CREATE query failed!"
    aws athena get-query-execution --query-execution-id "$CREATE_EXECUTION_ID" | jq '.QueryExecution.Status'
    exit 1
  fi
  echo -n "."
  sleep 2
done

echo "✅ Table created successfully with updated schema"
echo ""

# Step 3: Re-upload all data
echo "Step 3: Re-uploading data..."
echo "=========================================="
echo ""

TOTAL_RUNS=0
SUCCESSFUL_UPLOADS=0

for RUN_TYPE in "${RUN_TYPES[@]}"; do
    S3_PATH="s3://e6-jmeter/jmeter-results/engine=${ENGINE}/cluster_size=${CLUSTER_SIZE}/benchmark=${BENCHMARK}/run_type=${RUN_TYPE}/"
    INDEX_FILE="/tmp/runs_index_recreate_${RUN_TYPE}.json"

    echo "Processing: $RUN_TYPE"
    echo "----------------------------------------"

    # Generate runs index
    echo "📊 Generating runs index..."
    if python3 utilities/athena/generate_runs_index.py "$S3_PATH" --output "$INDEX_FILE" 2>&1 | grep -q "Successfully processed"; then
        echo "✓ Index generated"
    else
        echo "⚠️  No runs found or generation failed for $RUN_TYPE"
        echo ""
        continue
    fi

    # Count runs
    RUN_COUNT=$(jq '.runs | length' "$INDEX_FILE")
    TOTAL_RUNS=$((TOTAL_RUNS + RUN_COUNT))

    # Verify is_outlier field exists
    OUTLIER_CHECK=$(jq '.runs[0].status_info.is_outlier // "no"' "$INDEX_FILE")
    echo "  Verified: is_outlier=$OUTLIER_CHECK (default: no)"

    # Upload to Athena
    echo "☁️  Uploading to Athena..."
    if python3 utilities/athena/upload_runs_index_to_athena.py "$INDEX_FILE" 2>&1 | grep -q "Successfully uploaded"; then
        echo "✅ Successfully uploaded $RUN_COUNT runs for $RUN_TYPE"
        SUCCESSFUL_UPLOADS=$((SUCCESSFUL_UPLOADS + RUN_COUNT))
    else
        echo "❌ Failed to upload $RUN_TYPE"
    fi

    echo ""
done

echo "=========================================="
echo "Recreation Complete!"
echo "=========================================="
echo "Total runs processed: $TOTAL_RUNS"
echo "Successfully uploaded: $SUCCESSFUL_UPLOADS"
echo "=========================================="
echo ""
echo "Next Steps:"
echo ""
echo "1. Verify table schema:"
echo "   DESCRIBE jmeter_runs_index;"
echo ""
echo "2. Test query with is_outlier:"
echo "   SELECT run_id, is_outlier, is_best, is_baseline, p90_latency_sec"
echo "   FROM jmeter_runs_index"
echo "   WHERE engine='$ENGINE' AND is_outlier='no'"
echo "   LIMIT 10;"
echo ""
echo "3. Query valid runs only:"
echo "   SELECT run_id, cluster_size, run_type, p90_latency_sec"
echo "   FROM jmeter_runs_index"
echo "   WHERE engine='$ENGINE' AND is_outlier='no'"
echo "   ORDER BY run_date DESC;"
echo ""
echo "4. Generate CSV reports using Athena queries:"
echo "   See utilities/athena/ATHENA_QUERY_REFERENCE.md for all available queries"
echo ""
