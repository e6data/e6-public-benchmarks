#!/bin/bash
# Repair partitions for jmeter_query_results table
# This discovers all partitions in S3 and makes them queryable in Athena

ATHENA_DATABASE="${ATHENA_DATABASE:-jmeter_analysis}"
ATHENA_WORKGROUP="${ATHENA_WORKGROUP:-primary}"
ATHENA_OUTPUT_LOCATION="${ATHENA_OUTPUT_LOCATION:-s3://your-s3-bucket/athena-query-results/}"

echo "=========================================="
echo "Athena Partition Repair"
echo "=========================================="
echo "Database: $ATHENA_DATABASE"
echo "Table: jmeter_query_results"
echo "=========================================="
echo ""

# Run MSCK REPAIR TABLE command
echo "Running MSCK REPAIR TABLE..."
REPAIR_QUERY="MSCK REPAIR TABLE jmeter_query_results;"

aws athena start-query-execution \
  --query-string "$REPAIR_QUERY" \
  --query-execution-context Database="$ATHENA_DATABASE" \
  --work-group "$ATHENA_WORKGROUP" \
  --result-configuration OutputLocation="$ATHENA_OUTPUT_LOCATION" \
  > /tmp/athena_repair_execution.json

EXECUTION_ID=$(jq -r '.QueryExecutionId' /tmp/athena_repair_execution.json)
echo "Submitted MSCK REPAIR query: $EXECUTION_ID"

# Wait for completion
echo -n "Waiting for partition discovery"
while true; do
  STATUS=$(aws athena get-query-execution --query-execution-id "$EXECUTION_ID" | jq -r '.QueryExecution.Status.State')
  if [[ "$STATUS" == "SUCCEEDED" ]]; then
    echo " ✓"
    break
  elif [[ "$STATUS" == "FAILED" ]] || [[ "$STATUS" == "CANCELLED" ]]; then
    echo " ✗"
    echo "Partition repair failed!"
    aws athena get-query-execution --query-execution-id "$EXECUTION_ID" | jq '.QueryExecution.Status'
    exit 1
  fi
  echo -n "."
  sleep 2
done

echo ""
echo "=========================================="
echo "✅ Partition Repair Complete!"
echo "=========================================="
echo ""
echo "You can now query jmeter_query_results table."
echo ""
echo "Example query:"
echo "  SELECT run_id, label, elapsed_time_ms"
echo "  FROM jmeter_analysis.jmeter_query_results"
echo "  WHERE engine='e6data'"
echo "    AND cluster_size='S-2x2'"
echo "    AND run_id='20251117-072557'"
echo "  LIMIT 10;"
echo ""
