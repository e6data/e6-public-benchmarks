# S3 Structure Reorganization

## Overview

Updated S3 storage structure to include `run_id` folder level for better organization and management of test runs.

## Changes

### New S3 Structure

**Previous (Flat):**
```
s3://bucket/jmeter-results/
└── engine=e6data/
    └── cluster_size=S-2x2/
        └── benchmark=tpcds_29_1tb/
            └── run_type=concurrency_2/
                ├── statistics.json_20251030-171659
                ├── statistics.json_20251031-070614
                ├── JmeterResultFile_20251030-171659.csv
                ├── JmeterResultFile_20251031-070614.csv
                └── ... (many files)
```

**New (Hierarchical with run_id):**
```
s3://bucket/jmeter-results/
└── engine=e6data/
    └── cluster_size=S-2x2/
        └── benchmark=tpcds_29_1tb/
            └── run_type=concurrency_2/
                ├── run_id=20251030-171659/
                │   ├── statistics.json
                │   ├── JmeterResultFile.csv
                │   ├── AggregateReport.csv
                │   ├── SummaryReport.csv
                │   └── test_result.json
                ├── run_id=20251031-070614/
                │   ├── statistics.json
                │   ├── JmeterResultFile.csv
                │   └── ...
                └── latest.json  (reference to most recent run)
```

### Benefits

1. **Better Organization**: All files for a specific run are in one folder
2. **Easier Management**: Can delete/archive entire runs by folder
3. **Cleaner File Names**: No more timestamp suffixes in filenames
4. **Metadata Co-location**: Run metadata stays with the run
5. **Simpler Comparisons**: Easy to identify which runs to compare

## Files Modified

### 1. Metadata Files (Added S3_BASE_PATH)

All metadata files now include:
```bash
S3_BASE_PATH=s3://e6-jmeter/jmeter-results
```

Updated files:
- `metadata_files/e6data_s-2x2_metadata.txt`
- `metadata_files/e6data_m-4x4_metadata.txt`
- `metadata_files/dbr_s-2x2_metadata.txt`
- `metadata_files/dbr_s-4x4_metadata.txt`

### 2. run_jmeter_tests_interactive.sh

**Key Changes:**
- Uses `S3_BASE_PATH` from metadata file (with fallback to default)
- Creates 5-level partition structure: `engine/cluster_size/benchmark/run_type/run_id`
- Files uploaded with original names (no timestamp suffix)
- `latest.json` saved at run_type level for quick access to most recent run
- Updated Athena partition creation for 5-level structure

**Example Upload Path:**
```bash
s3://e6-jmeter/jmeter-results/engine=e6data/cluster_size=S-2x2/benchmark=tpcds_29_1tb/run_type=concurrency_2/run_id=20251031-070614/
```

### 3. utilities/compare_consecutive_runs_from_s3.py

**Updated to:**
- List `run_id=` folders instead of timestamped files
- Extract run IDs from folder names
- Build paths to `statistics.json` inside run_id folders
- New helper function: `format_run_id()` to format timestamps
- New helper function: `extract_run_id_from_path()` to parse paths

### 4. utilities/analyze_single_run_from_s3.py

**Updated to:**
- List `run_id=` folders
- Find statistics.json inside run_id folders
- Support both specific run_id selection and latest run

## Usage Examples

### Running Tests

```bash
# Interactive mode - will automatically use new structure
./run_jmeter_tests_interactive.sh

# Files will be uploaded to:
# s3://e6-jmeter/jmeter-results/engine=e6data/cluster_size=S-2x2/benchmark=tpcds_29_1tb/run_type=concurrency_2/run_id=20251101-123456/
```

### Comparing Consecutive Runs

```bash
# Compare latest 2 runs (automatic)
python utilities/compare_consecutive_runs_from_s3.py s3://e6-jmeter/jmeter-results/engine=e6data/cluster_size=S-2x2/benchmark=tpcds_29_1tb/

# Compare specific runs
python utilities/compare_consecutive_runs_from_s3.py \
    s3://e6-jmeter/jmeter-results/engine=e6data/cluster_size=S-2x2/benchmark=tpcds_29_1tb/ \
    --run-id1 20251030-171659 \
    --run-id2 20251031-070614
```

### Analyzing Single Run

```bash
# Analyze latest run
python utilities/analyze_single_run_from_s3.py s3://e6-jmeter/jmeter-results/engine=e6data/cluster_size=S-2x2/benchmark=tpcds_29_1tb/

# Analyze specific run
python utilities/analyze_single_run_from_s3.py \
    s3://e6-jmeter/jmeter-results/engine=e6data/cluster_size=S-2x2/benchmark=tpcds_29_1tb/ \
    --run-id 20251031-070614
```

## Customization

### Using Different S3 Bucket/Path

Update the `S3_BASE_PATH` in your metadata file:

```bash
# metadata_files/your_metadata.txt
S3_BASE_PATH=s3://your-bucket/your-custom-path
```

No hardcoded paths in the scripts - all use the metadata configuration.

## Migration Notes

**No Migration Needed:**
- Old data remains in flat structure
- New runs will use new structure automatically
- Comparison scripts work only with new structure
- Old runs can be manually reorganized if needed

## Athena Schema Update

Athena tables will need updated schema to include `run_id` partition:

```sql
ALTER TABLE jmeter_performance_db.statistics ADD COLUMNS (run_id string);
ALTER TABLE jmeter_performance_db.detailed_results ADD COLUMNS (run_id string);
ALTER TABLE jmeter_performance_db.aggregate_report ADD COLUMNS (run_id string);
ALTER TABLE jmeter_performance_db.run_summary ADD COLUMNS (run_id string);
```

Then add partitions:
```sql
MSCK REPAIR TABLE jmeter_performance_db.statistics;
MSCK REPAIR TABLE jmeter_performance_db.detailed_results;
MSCK REPAIR TABLE jmeter_performance_db.aggregate_report;
MSCK REPAIR TABLE jmeter_performance_db.run_summary;
```

## Testing

Before deploying to production:

1. Test with one concurrency level
2. Verify files upload to correct path
3. Verify comparison scripts can find runs
4. Verify Athena queries work with new structure

---

**Date**: 2025-11-01
**Version**: 2.0 (Hierarchical run_id structure)
