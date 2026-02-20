#!/bin/bash
# Unified Athena Table Setup Script
# Creates all JMeter Athena tables in the jmeter_analysis database
#
# This script creates:
# 1. jmeter_runs_index - Aggregated run-level metrics (older implementation)
# 2. jmeter_run_metadata - Run configuration metadata (hybrid approach)
# 3. jmeter_query_results - Query-level performance data (hybrid approach)
#
# Usage:
#   ./utilities/athena/setup_all_athena_tables.sh [--database DB_NAME] [--drop-existing]
#
# Options:
#   --database NAME    Specify Athena database name (default: jmeter_analysis)
#   --drop-existing    Drop existing tables before recreating
#
# Example:
#   ./utilities/athena/setup_all_athena_tables.sh --database jmeter_analysis --drop-existing

set -e

# Parse command line arguments
DROP_EXISTING=false
ATHENA_DATABASE="${ATHENA_DATABASE:-jmeter_analysis}"
ATHENA_WORKGROUP="${ATHENA_WORKGROUP:-primary}"
ATHENA_OUTPUT_LOCATION="${ATHENA_OUTPUT_LOCATION:-s3://your-s3-bucket/athena-query-results/}"

while [[ $# -gt 0 ]]; do
    case $1 in
        --database)
            ATHENA_DATABASE="$2"
            shift 2
            ;;
        --drop-existing)
            DROP_EXISTING=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--database DATABASE_NAME] [--drop-existing]"
            exit 1
            ;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DDL_DIR="$SCRIPT_DIR/ddl"

echo "=========================================="
echo "Unified Athena Table Setup"
echo "=========================================="
echo "Database: $ATHENA_DATABASE"
echo "Workgroup: $ATHENA_WORKGROUP"
echo "Drop existing tables: $DROP_EXISTING"
echo "=========================================="
echo ""

# Function to execute Athena query and wait for completion
execute_athena_query() {
    local query="$1"
    local description="$2"

    echo "$description..."

    local execution_json=$(aws athena start-query-execution \
        --query-string "$query" \
        --query-execution-context Database="$ATHENA_DATABASE" \
        --work-group "$ATHENA_WORKGROUP" \
        --result-configuration OutputLocation="$ATHENA_OUTPUT_LOCATION")

    local execution_id=$(echo "$execution_json" | jq -r '.QueryExecutionId')
    echo "  Query ID: $execution_id"

    echo -n "  Waiting for completion"
    while true; do
        local status=$(aws athena get-query-execution --query-execution-id "$execution_id" | jq -r '.QueryExecution.Status.State')
        if [[ "$status" == "SUCCEEDED" ]]; then
            echo " ✓"
            return 0
        elif [[ "$status" == "FAILED" ]] || [[ "$status" == "CANCELLED" ]]; then
            echo " ✗"
            echo "  ERROR: Query failed!"
            aws athena get-query-execution --query-execution-id "$execution_id" | jq '.QueryExecution.Status'
            return 1
        fi
        echo -n "."
        sleep 2
    done
}

# Step 1: Drop existing tables (if requested)
if [ "$DROP_EXISTING" = true ]; then
    echo "Step 1: Dropping existing tables..."
    echo "----------------------------------------"

    execute_athena_query "DROP TABLE IF EXISTS jmeter_runs_index;" "Dropping jmeter_runs_index"
    execute_athena_query "DROP TABLE IF EXISTS jmeter_run_metadata;" "Dropping jmeter_run_metadata"
    execute_athena_query "DROP TABLE IF EXISTS jmeter_query_results;" "Dropping jmeter_query_results"

    echo ""
fi

# Step 2: Create jmeter_runs_index table
echo "Step 2: Creating jmeter_runs_index table..."
echo "----------------------------------------"

CREATE_SQL_FILE="$SCRIPT_DIR/setup_athena_runs_index.sql"

if [ ! -f "$CREATE_SQL_FILE" ]; then
    echo "❌ Error: Schema file not found: $CREATE_SQL_FILE"
    exit 1
fi

# Read the CREATE TABLE statement (skip comments and empty lines)
CREATE_QUERY=$(grep -v '^--' "$CREATE_SQL_FILE" | grep -v '^$' | head -n 108)

if ! execute_athena_query "$CREATE_QUERY" "Creating jmeter_runs_index"; then
    echo "❌ Failed to create jmeter_runs_index table"
    exit 1
fi

echo "✅ jmeter_runs_index created successfully"
echo ""

# Step 3: Create jmeter_run_metadata table
echo "Step 3: Creating jmeter_run_metadata table..."
echo "----------------------------------------"

METADATA_DDL_FILE="$DDL_DIR/create_metadata_table.sql"

if [ ! -f "$METADATA_DDL_FILE" ]; then
    echo "❌ Error: Metadata DDL file not found: $METADATA_DDL_FILE"
    exit 1
fi

METADATA_QUERY=$(cat "$METADATA_DDL_FILE")

if ! execute_athena_query "$METADATA_QUERY" "Creating jmeter_run_metadata"; then
    echo "❌ Failed to create jmeter_run_metadata table"
    exit 1
fi

echo "✅ jmeter_run_metadata created successfully"
echo ""

# Step 4: Create jmeter_query_results table
echo "Step 4: Creating jmeter_query_results table..."
echo "----------------------------------------"

RESULTS_DDL_FILE="$DDL_DIR/create_results_table_csv.sql"

if [ ! -f "$RESULTS_DDL_FILE" ]; then
    echo "❌ Error: Results DDL file not found: $RESULTS_DDL_FILE"
    exit 1
fi

RESULTS_QUERY=$(cat "$RESULTS_DDL_FILE")

if ! execute_athena_query "$RESULTS_QUERY" "Creating jmeter_query_results"; then
    echo "❌ Failed to create jmeter_query_results table"
    exit 1
fi

echo "✅ jmeter_query_results created successfully"
echo ""

# Step 5: Verify all tables
echo "Step 5: Verifying tables..."
echo "=========================================="

echo "Listing tables in $ATHENA_DATABASE..."
execute_athena_query "SHOW TABLES;" "Listing tables"

echo ""
echo "Verifying table columns..."
execute_athena_query "DESCRIBE jmeter_runs_index;" "Describing jmeter_runs_index"
execute_athena_query "DESCRIBE jmeter_run_metadata;" "Describing jmeter_run_metadata"
execute_athena_query "DESCRIBE jmeter_query_results;" "Describing jmeter_query_results"

echo ""
echo "=========================================="
echo "✅ All Tables Created Successfully!"
echo "=========================================="
echo ""
echo "Database: $ATHENA_DATABASE"
echo ""
echo "Tables created:"
echo "  1. jmeter_runs_index      - Aggregated run-level metrics"
echo "  2. jmeter_run_metadata    - Run configuration metadata"
echo "  3. jmeter_query_results   - Query-level performance data"
echo ""
echo "=========================================="
echo "Next Steps:"
echo "=========================================="
echo ""
echo "1. Query tables using WORKING_QUERIES.sql:"
echo "   cat utilities/athena/WORKING_QUERIES.sql"
echo ""
echo "2. Verify data in tables:"
echo "   SELECT COUNT(*) FROM jmeter_analysis.jmeter_runs_index;"
echo "   SELECT COUNT(*) FROM jmeter_analysis.jmeter_run_metadata;"
echo "   SELECT run_id FROM jmeter_analysis.jmeter_run_metadata LIMIT 5;"
echo ""
echo "4. Update queries to use database prefix:"
echo "   SELECT * FROM jmeter_analysis.jmeter_run_metadata WHERE ..."
echo ""
