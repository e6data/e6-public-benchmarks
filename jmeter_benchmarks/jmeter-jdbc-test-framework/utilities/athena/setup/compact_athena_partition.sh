#!/bin/bash
# Compact multiple timestamped JSONL files in a single Athena partition
#
# Usage:
#   ./utilities/athena/compact_athena_partition.sh <engine> <cluster_size> <benchmark> <run_type>
#
# Example:
#   ./utilities/athena/compact_athena_partition.sh e6data S-2x2 tpcds_29_1tb concurrency_4
#
# What this script does:
#   1. Downloads all data_*.jsonl files from the partition
#   2. Merges them, deduplicating by run_id (keeps latest)
#   3. Creates a single compacted file: data_compacted_YYYYMMDD_HHMMSS.jsonl
#   4. Archives old files to _archive/ prefix in same partition
#   5. Uploads the compacted file

set -e

# Input validation
if [ $# -ne 4 ]; then
    echo "Usage: $0 <engine> <cluster_size> <benchmark> <run_type>"
    echo ""
    echo "Example:"
    echo "  $0 e6data S-2x2 tpcds_29_1tb concurrency_4"
    exit 1
fi

ENGINE="$1"
CLUSTER_SIZE="$2"
BENCHMARK="$3"
RUN_TYPE="$4"

S3_BASE="s3://e6-jmeter/jmeter-results-index"
PARTITION_PATH="${S3_BASE}/runs/engine=${ENGINE}/cluster_size=${CLUSTER_SIZE}/benchmark=${BENCHMARK}/run_type=${RUN_TYPE}/"

echo "=========================================="
echo "Athena Partition Compaction"
echo "=========================================="
echo "Engine: $ENGINE"
echo "Cluster Size: $CLUSTER_SIZE"
echo "Benchmark: $BENCHMARK"
echo "Run Type: $RUN_TYPE"
echo ""
echo "Partition: $PARTITION_PATH"
echo "=========================================="
echo ""

# Create temp directory
TEMP_DIR=$(mktemp -d)
trap "rm -rf $TEMP_DIR" EXIT

# Step 1: List files in partition
echo "1. Listing files in partition..."
aws s3 ls "$PARTITION_PATH" > "$TEMP_DIR/file_list.txt"

if [ ! -s "$TEMP_DIR/file_list.txt" ]; then
    echo "❌ No files found in partition"
    exit 1
fi

FILE_COUNT=$(grep -c '\.jsonl$' "$TEMP_DIR/file_list.txt" || true)

if [ "$FILE_COUNT" -eq 0 ]; then
    echo "❌ No JSONL files found in partition"
    exit 1
fi

echo "   Found $FILE_COUNT JSONL files:"
grep '\.jsonl$' "$TEMP_DIR/file_list.txt" | awk '{print "     - " $4}'
echo ""

if [ "$FILE_COUNT" -eq 1 ]; then
    echo "✓ Only 1 file - no compaction needed"
    exit 0
fi

# Step 2: Download all JSONL files
echo "2. Downloading files..."
mkdir -p "$TEMP_DIR/downloads"

while IFS= read -r line; do
    FILENAME=$(echo "$line" | awk '{print $4}')
    if [[ "$FILENAME" == *.jsonl ]]; then
        echo "   Downloading: $FILENAME"
        aws s3 cp "${PARTITION_PATH}${FILENAME}" "$TEMP_DIR/downloads/${FILENAME}"
    fi
done < "$TEMP_DIR/file_list.txt"

echo ""

# Step 3: Merge and deduplicate
echo "3. Merging and deduplicating..."

# Combine all JSONL files
cat "$TEMP_DIR/downloads"/*.jsonl > "$TEMP_DIR/all_runs.jsonl"

# Deduplicate by run_id (keep latest occurrence)
# This uses jq to:
# - Read all JSON objects
# - Group by run_id
# - Keep the last occurrence of each run_id
# - Output as JSONL

echo "   Deduplicating by run_id..."
jq -s '
  group_by(.run_id) |
  map(last) |
  .[]
' "$TEMP_DIR/all_runs.jsonl" | jq -c '.' > "$TEMP_DIR/deduplicated.jsonl"

TOTAL_RUNS_BEFORE=$(wc -l < "$TEMP_DIR/all_runs.jsonl" | tr -d ' ')
TOTAL_RUNS_AFTER=$(wc -l < "$TEMP_DIR/deduplicated.jsonl" | tr -d ' ')
DUPLICATES=$((TOTAL_RUNS_BEFORE - TOTAL_RUNS_AFTER))

echo "   Before: $TOTAL_RUNS_BEFORE runs"
echo "   After:  $TOTAL_RUNS_AFTER runs"
echo "   Removed: $DUPLICATES duplicates"
echo ""

# Step 4: Create compacted file
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
COMPACTED_FILENAME="data_compacted_${TIMESTAMP}.jsonl"

echo "4. Creating compacted file: $COMPACTED_FILENAME"
cp "$TEMP_DIR/deduplicated.jsonl" "$TEMP_DIR/${COMPACTED_FILENAME}"

FILE_SIZE=$(ls -lh "$TEMP_DIR/${COMPACTED_FILENAME}" | awk '{print $5}')
echo "   Size: $FILE_SIZE"
echo ""

# Step 5: Archive old files
echo "5. Archiving old files..."
ARCHIVE_PATH="${S3_BASE}/runs/engine=${ENGINE}/cluster_size=${CLUSTER_SIZE}/benchmark=${BENCHMARK}/run_type=${RUN_TYPE}/_archive/"

while IFS= read -r line; do
    FILENAME=$(echo "$line" | awk '{print $4}')
    if [[ "$FILENAME" == *.jsonl ]] && [[ "$FILENAME" != _archive* ]]; then
        echo "   Archiving: $FILENAME"
        aws s3 mv "${PARTITION_PATH}${FILENAME}" "${ARCHIVE_PATH}${FILENAME}"
    fi
done < "$TEMP_DIR/file_list.txt"

echo ""

# Step 6: Upload compacted file
echo "6. Uploading compacted file..."
aws s3 cp "$TEMP_DIR/${COMPACTED_FILENAME}" "${PARTITION_PATH}${COMPACTED_FILENAME}"

echo ""
echo "=========================================="
echo "✅ Compaction Complete!"
echo "=========================================="
echo "Result:"
echo "  - Merged $FILE_COUNT files into 1"
echo "  - Removed $DUPLICATES duplicate runs"
echo "  - Final run count: $TOTAL_RUNS_AFTER"
echo "  - New file: $COMPACTED_FILENAME"
echo ""
echo "Old files archived to:"
echo "  ${ARCHIVE_PATH}"
echo ""
echo "Query Athena to verify:"
echo "  SELECT COUNT(*) as run_count"
echo "  FROM jmeter_runs_index"
echo "  WHERE engine = '$ENGINE'"
echo "    AND cluster_size = '$CLUSTER_SIZE'"
echo "    AND benchmark = '$BENCHMARK'"
echo "    AND run_type = '$RUN_TYPE';"
echo ""
