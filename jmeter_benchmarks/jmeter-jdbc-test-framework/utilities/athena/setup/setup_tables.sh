#!/bin/bash
# Setup script for jmeter_run_metadata and jmeter_query_results tables (HYBRID APPROACH)
# - jmeter_run_metadata: JSONL format in s3://e6-jmeter/athena-tables/run_metadata/
# - jmeter_query_results: Points directly at existing CSV files in s3://e6-jmeter/jmeter-results/
#
# Usage: ./setup_tables.sh [--skip-s3] [--database DATABASE_NAME]
#
# Options:
#   --skip-s3          Skip S3 bucket creation for metadata (use if bucket already exists)
#   --database NAME    Specify Athena database name (default: jmeter_analysis)

set -e  # Exit on error

# Parse command line arguments
SKIP_S3=false
DATABASE="jmeter_analysis"

while [[ $# -gt 0 ]]; do
    case $1 in
        --skip-s3)
            SKIP_S3=true
            shift
            ;;
        --database)
            DATABASE="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--skip-s3] [--database DATABASE_NAME]"
            exit 1
            ;;
    esac
done

# Configuration
S3_BUCKET="e6-jmeter"
METADATA_LOCATION="s3://${S3_BUCKET}/athena-tables/run_metadata/"
RESULTS_LOCATION="s3://${S3_BUCKET}/athena-tables/query_results/"
QUERY_RESULTS_BUCKET="s3://${S3_BUCKET}/athena-query-results/"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DDL_DIR="$(dirname "$SCRIPT_DIR")/ddl"

echo "==========================================="
echo "Athena Table Setup"
echo "==========================================="
echo "Database: $DATABASE"
echo "Metadata table location: $METADATA_LOCATION"
echo "Results table location: $RESULTS_LOCATION"
echo "==========================================="
echo ""

# Step 1: Create S3 locations (unless skipped)
if [ "$SKIP_S3" = false ]; then
    echo "Step 1: Creating S3 locations..."

    # Check if locations already exist
    if aws s3 ls "$METADATA_LOCATION" >/dev/null 2>&1; then
        echo "  ✓ Metadata location already exists"
    else
        echo "  Creating $METADATA_LOCATION"
        aws s3 mb "s3://${S3_BUCKET}" 2>/dev/null || true
        aws s3api put-object --bucket "$S3_BUCKET" --key "athena-tables/run_metadata/" || true
        echo "  ✓ Created metadata location"
    fi

    if aws s3 ls "$RESULTS_LOCATION" >/dev/null 2>&1; then
        echo "  ✓ Results location already exists"
    else
        echo "  Creating $RESULTS_LOCATION"
        aws s3api put-object --bucket "$S3_BUCKET" --key "athena-tables/query_results/" || true
        echo "  ✓ Created results location"
    fi

    if aws s3 ls "$QUERY_RESULTS_BUCKET" >/dev/null 2>&1; then
        echo "  ✓ Query results bucket already exists"
    else
        echo "  Creating $QUERY_RESULTS_BUCKET"
        aws s3api put-object --bucket "$S3_BUCKET" --key "athena-query-results/" || true
        echo "  ✓ Created query results bucket"
    fi

    echo ""
else
    echo "Step 1: Skipping S3 bucket creation (--skip-s3 specified)"
    echo ""
fi

# Step 2: Create metadata table
echo "Step 2: Creating jmeter_run_metadata table..."

# Check if DDL file exists
if [ ! -f "$DDL_DIR/create_metadata_table.sql" ]; then
    echo "ERROR: DDL file not found: $DDL_DIR/create_metadata_table.sql"
    exit 1
fi

# Execute DDL
QUERY_ID=$(aws athena start-query-execution \
    --query-string "$(cat "$DDL_DIR/create_metadata_table.sql")" \
    --query-execution-context Database="$DATABASE" \
    --result-configuration OutputLocation="$QUERY_RESULTS_BUCKET" \
    --output text --query 'QueryExecutionId')

echo "  Submitted query: $QUERY_ID"
echo "  Waiting for completion..."

# Wait for query to complete
while true; do
    STATUS=$(aws athena get-query-execution \
        --query-execution-id "$QUERY_ID" \
        --output text --query 'QueryExecution.Status.State')

    if [ "$STATUS" = "SUCCEEDED" ]; then
        echo "  ✓ jmeter_run_metadata table created successfully"
        break
    elif [ "$STATUS" = "FAILED" ] || [ "$STATUS" = "CANCELLED" ]; then
        echo "  ✗ Table creation failed with status: $STATUS"
        aws athena get-query-execution --query-execution-id "$QUERY_ID" --query 'QueryExecution.Status.StateChangeReason' --output text
        exit 1
    fi

    sleep 2
done

echo ""

# Step 3: Create results table
echo "Step 3: Creating jmeter_query_results table..."

# Check if DDL file exists
if [ ! -f "$DDL_DIR/create_results_table_csv.sql" ]; then
    echo "ERROR: DDL file not found: $DDL_DIR/create_results_table_csv.sql"
    exit 1
fi

# Execute DDL
QUERY_ID=$(aws athena start-query-execution \
    --query-string "$(cat "$DDL_DIR/create_results_table_csv.sql")" \
    --query-execution-context Database="$DATABASE" \
    --result-configuration OutputLocation="$QUERY_RESULTS_BUCKET" \
    --output text --query 'QueryExecutionId')

echo "  Submitted query: $QUERY_ID"
echo "  Waiting for completion..."

# Wait for query to complete
while true; do
    STATUS=$(aws athena get-query-execution \
        --query-execution-id "$QUERY_ID" \
        --output text --query 'QueryExecution.Status.State')

    if [ "$STATUS" = "SUCCEEDED" ]; then
        echo "  ✓ jmeter_query_results table created successfully"
        break
    elif [ "$STATUS" = "FAILED" ] || [ "$STATUS" = "CANCELLED" ]; then
        echo "  ✗ Table creation failed with status: $STATUS"
        aws athena get-query-execution --query-execution-id "$QUERY_ID" --query 'QueryExecution.Status.StateChangeReason' --output text
        exit 1
    fi

    sleep 2
done

echo ""

# Step 4: Verify tables
echo "Step 4: Verifying tables..."

# Check metadata table
QUERY_ID=$(aws athena start-query-execution \
    --query-string "SHOW COLUMNS IN jmeter_run_metadata" \
    --query-execution-context Database="$DATABASE" \
    --result-configuration OutputLocation="$QUERY_RESULTS_BUCKET" \
    --output text --query 'QueryExecutionId')

sleep 2
STATUS=$(aws athena get-query-execution --query-execution-id "$QUERY_ID" --output text --query 'QueryExecution.Status.State')

if [ "$STATUS" = "SUCCEEDED" ]; then
    echo "  ✓ jmeter_run_metadata verified"
else
    echo "  ✗ Failed to verify jmeter_run_metadata"
fi

# Check results table
QUERY_ID=$(aws athena start-query-execution \
    --query-string "SHOW COLUMNS IN jmeter_query_results" \
    --query-execution-context Database="$DATABASE" \
    --result-configuration OutputLocation="$QUERY_RESULTS_BUCKET" \
    --output text --query 'QueryExecutionId')

sleep 2
STATUS=$(aws athena get-query-execution --query-execution-id "$QUERY_ID" --output text --query 'QueryExecution.Status.State')

if [ "$STATUS" = "SUCCEEDED" ]; then
    echo "  ✓ jmeter_query_results verified"
else
    echo "  ✗ Failed to verify jmeter_query_results"
fi

echo ""
echo "==========================================="
echo "Setup Complete!"
echo "==========================================="
echo ""
echo "Tables created:"
echo "  - jmeter_run_metadata (metadata for each run)"
echo "  - jmeter_query_results (query-level execution results)"
echo ""
echo "Next steps:"
echo "  1. Generate metadata index: python3 scripts/generate_metadata_index.py <s3_path>"
echo "  2. Generate results index: python3 scripts/generate_results_index.py <s3_path>"
echo "  3. Upload to Athena using upload scripts"
echo "  4. Or use bulk_migrate.sh to migrate all historical data"
echo ""
