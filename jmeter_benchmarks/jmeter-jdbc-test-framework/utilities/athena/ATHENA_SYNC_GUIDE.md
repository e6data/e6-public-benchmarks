# Athena Sync Guide - Keep Athena Updated with Latest Runs

## Problem
When you run new JMeter tests, they are saved to S3 but **NOT automatically added to Athena**. This means:
- `query_athena_runs.py` won't show new runs
- `compare_runs_athena.py` won't find them
- Reports will be incomplete

## Solution: Automated Sync Script

### Script: `sync_s3_to_athena.py`

This script automatically:
1. 🔍 Scans S3 for ALL test runs
2. ✅ Checks which runs are already in Athena
3. 📤 Uploads ONLY the missing runs
4. 📊 Shows summary of what was uploaded

---

## Quick Start

### 1. See What's Missing (Dry Run)
```bash
# Check what new runs need to be uploaded
python utilities/sync_s3_to_athena.py --dry-run
```

**Output Example:**
```
================================================================================
                             S3 to Athena Sync Tool
================================================================================

🔍 Scanning S3 bucket: e6-jmeter/jmeter-results/
✓ Found 87 total runs in S3

🔍 Checking existing runs in Athena...
✓ Found 31 runs already in Athena

📊 Missing runs: 56 (need to upload)

================================================================================
MISSING RUNS BY CONFIGURATION
================================================================================
  e6data/M-4x4/concurrency_2: 8 runs
  e6data/M-4x4/concurrency_4: 10 runs
  e6data/M-4x4/concurrency_8: 12 runs
  databricks/S-4x4/concurrency_2: 5 runs
  ...
================================================================================

🔍 DRY RUN MODE - No uploads will be performed

Would upload: e6data/M-4x4/concurrency_2/20251103-101523
Would upload: e6data/M-4x4/concurrency_2/20251103-102314
...
Total: 56 runs
```

### 2. Upload Missing Runs
```bash
# Actually upload the missing runs
python utilities/sync_s3_to_athena.py
```

**Output Example:**
```
📤 Uploading missing runs to Athena...

[1/56] e6data/M-4x4/concurrency_2/20251103-101523
   ✅ Uploaded successfully

[2/56] e6data/M-4x4/concurrency_2/20251103-102314
   ✅ Uploaded successfully

...

================================================================================
SYNC COMPLETE
================================================================================
✅ Successfully uploaded: 56
❌ Failed: 0
📊 Total in Athena (before): 31
📊 Total in Athena (after): 87
================================================================================

You can now query the updated data:
  python utilities/query_athena_runs.py
  python utilities/query_athena_runs.py --compare-engines
  python utilities/compare_runs_athena.py --engine e6data --cluster M-4x4
```

---

## Advanced Usage

### Filter by Engine
```bash
# Only sync e6data runs
python utilities/sync_s3_to_athena.py --engine e6data --dry-run
python utilities/sync_s3_to_athena.py --engine e6data
```

### Filter by Cluster
```bash
# Only sync M-4x4 cluster runs
python utilities/sync_s3_to_athena.py --cluster M-4x4 --dry-run
python utilities/sync_s3_to_athena.py --cluster M-4x4
```

### Force Re-upload (Overwrite Existing)
```bash
# Re-upload ALL runs (even if already in Athena)
python utilities/sync_s3_to_athena.py --force

# Use with caution! This will re-process everything
```

### Custom S3 Bucket/Prefix
```bash
# If using different bucket or prefix
python utilities/sync_s3_to_athena.py --bucket my-bucket --prefix my-results/
```

---

## When to Run This Script

### Daily Workflow
```bash
# After running new tests, sync to Athena
./run_jmeter_tests_interactive.sh
# ... test completes and uploads to S3 ...

# Now sync to Athena
python utilities/sync_s3_to_athena.py

# Then query/compare
python utilities/query_athena_runs.py
python utilities/compare_runs_athena.py --engine e6data --cluster M-4x4
```

### Weekly/Monthly Maintenance
```bash
# Check if any runs were missed
python utilities/sync_s3_to_athena.py --dry-run

# If any missing, sync them
python utilities/sync_s3_to_athena.py
```

### After Bulk Test Runs
```bash
# Just ran 50 tests across different configurations
# Sync all at once
python utilities/sync_s3_to_athena.py

# Then generate updated reports
python utilities/query_athena_runs.py --compare-engines > reports/LATEST_engine_comparison.txt
python utilities/query_athena_runs.py --scaling-analysis > reports/LATEST_scaling_analysis.txt
```

---

## Comparison: Manual vs Automatic Sync

### ❌ Old Manual Way (`upload_all_runs_to_athena.sh`)
```bash
# Problems:
- Hardcoded paths (need to manually add each new configuration)
- Uploads all runs every time (slow, redundant)
- No intelligence about what's missing
- Need to edit script for new cluster sizes
```

### ✅ New Automatic Way (`sync_s3_to_athena.py`)
```bash
# Benefits:
- Automatically discovers all runs in S3
- Only uploads missing runs (fast, efficient)
- Shows exactly what needs updating
- No configuration needed
- Works with any engine/cluster/benchmark combination
```

---

## Troubleshooting

### Issue: "ExpiredToken" Error
```bash
# AWS credentials expired
# Solution: Refresh credentials
aws sso login
# Or re-run aws configure
```

### Issue: No runs found in S3
```bash
# Check S3 structure
aws s3 ls s3://e6-jmeter/jmeter-results/ --recursive | grep runs_index.json

# Make sure COPY_TO_S3=true in test properties
cat test_properties/your_test.properties | grep COPY_TO_S3
```

### Issue: Upload fails
```bash
# Check individual run manually
python utilities/upload_runs_index_to_athena.py \
    --from-s3 s3://e6-jmeter/jmeter-results/engine=e6data/cluster_size=M-4x4/benchmark=tpcds_29_1tb/run_type=concurrency_2/
```

---

## Workflow Integration

### Recommended Daily Process:

1. **Run Tests**
   ```bash
   ./run_jmeter_tests_interactive.sh
   ```

2. **Sync to Athena**
   ```bash
   python utilities/sync_s3_to_athena.py
   ```

3. **Generate Reports**
   ```bash
   python utilities/query_athena_runs.py > reports/all_runs_$(date +%Y%m%d).txt
   python utilities/query_athena_runs.py --compare-engines > reports/engine_comparison_$(date +%Y%m%d).txt
   ```

4. **Compare Latest Runs**
   ```bash
   python utilities/compare_runs_athena.py --engine e6data --cluster M-4x4 --run-type concurrency_4
   ```

---

## Automated Scheduling (Optional)

### Cron Job (Run Daily)
```bash
# Add to crontab (crontab -e)
0 2 * * * cd /path/to/jmeter-jdbc-test-framework && python utilities/sync_s3_to_athena.py >> logs/athena_sync.log 2>&1
```

### AWS Lambda (Trigger on S3 Upload)
```python
# Lambda function to auto-sync when new test completes
# Trigger: S3 PUT event on runs_index.json
def lambda_handler(event, context):
    # Parse S3 event
    # Call sync_s3_to_athena.py
    # Return success
```

---

## Related Tools

After syncing to Athena, use these tools:

### Query Tools
- `query_athena_runs.py` - Various aggregate queries
- `compare_runs_athena.py` - Compare specific runs

### Manual Tools (Still Useful)
- `compare_consecutive_runs_from_s3.py` - Detailed query-by-query analysis
- `upload_runs_index_to_athena.py` - Single run upload

---

## Summary

**OLD**: Manually edit `upload_all_runs_to_athena.sh` every time you add a new configuration

**NEW**: Just run `python utilities/sync_s3_to_athena.py` and it figures out what's missing!

**Best Practice**: Run sync after every batch of tests to keep Athena up-to-date.
