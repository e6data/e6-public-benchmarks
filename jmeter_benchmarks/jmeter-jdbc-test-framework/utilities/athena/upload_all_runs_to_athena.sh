#!/bin/bash
# Upload all test runs from S3 to Athena index

echo "=========================================="
echo "Uploading All Test Runs to Athena"
echo "=========================================="
echo ""

# Define all the paths to process
S3_BASE="${S3_RESULTS_PATH:-s3://your-s3-bucket/jmeter-results}"

# UPDATE: Add your S3 paths below
# Example format: "${S3_BASE}/engine=<engine>/cluster_size=<size>/benchmark=<benchmark>/run_type=<type>/"
PATHS=(
    # E6Data example runs (update with your actual paths)
    "${S3_BASE}/engine=e6data/cluster_size=M-4x4/benchmark=tpcds_29_1tb/run_type=concurrency_2/"
    "${S3_BASE}/engine=e6data/cluster_size=M-4x4/benchmark=tpcds_29_1tb/run_type=concurrency_4/"
    "${S3_BASE}/engine=e6data/cluster_size=M-4x4/benchmark=tpcds_29_1tb/run_type=concurrency_8/"
    "${S3_BASE}/engine=e6data/cluster_size=M-4x4/benchmark=tpcds_29_1tb/run_type=concurrency_12/"
    "${S3_BASE}/engine=e6data/cluster_size=M-4x4/benchmark=tpcds_29_1tb/run_type=concurrency_16/"
)

SUCCESS=0
FAILED=0
SKIPPED=0

for path in "${PATHS[@]}"; do
    echo "----------------------------------------"
    echo "Processing: $path"
    echo "----------------------------------------"

    # Check if path has any run_id folders
    run_count=$(aws s3 ls "$path" | grep "run_id=" | wc -l | tr -d ' ')

    if [ "$run_count" -eq 0 ]; then
        echo "⚠️  No run_id folders found, skipping..."
        SKIPPED=$((SKIPPED + 1))
        echo ""
        continue
    fi

    echo "✓ Found $run_count run_id folder(s)"

    # Generate and upload directly from S3
    if python utilities/upload_runs_index_to_athena.py --from-s3 "$path"; then
        echo "✅ Successfully uploaded"
        SUCCESS=$((SUCCESS + 1))
    else
        echo "❌ Failed to upload"
        FAILED=$((FAILED + 1))
    fi

    echo ""
done

echo "=========================================="
echo "SUMMARY"
echo "=========================================="
echo "✅ Successful: $SUCCESS"
echo "❌ Failed: $FAILED"
echo "⚠️  Skipped (no data): $SKIPPED"
echo "=========================================="
echo ""
echo "Now you can run queries to see all data:"
echo "  python utilities/query_athena_runs.py --compare-engines"
echo "  python utilities/query_athena_runs.py --instance-by-concurrency"
echo "  python utilities/query_athena_runs.py --compare-concurrency"
