# Athena Integration for JMeter Test Results

This directory contains tools for uploading JMeter test results to AWS Athena and querying them using SQL.

## Overview

The Athena integration provides **two standard methods** for generating analysis reports from JMeter test results:

1. **Local CSV Reports** - Generate reports offline from local index files using `jq`
2. **Athena SQL Queries** - Query cloud-hosted data in S3 using AWS Athena

**Both methods are fully supported** and documented in `CLAUDE.md`. This integration enables:
- **Multi-dimensional slicing**: By engines, dates, instances, cluster sizes, benchmarks, concurrency
- **Best run identification**: Find optimal performance across any dimension
- **Baseline tracking**: Set and compare against performance baselines
- **Outlier management**: Exclude anomalous runs from analysis
- **Run comparisons**: Compare any two runs or sets of runs
- **Regression detection**: Identify performance degradations automatically
- **Dashboard integration**: Superset, QuickSight, Tableau support

## File Structure

```
utilities/athena/
├── README.md                          # This file
├── ATHENA_QUERY_REFERENCE.md          # 25+ SQL queries for all analysis patterns
├── setup_athena_runs_index.sql        # Athena table schema (DDL)
├── upload_runs_index_to_athena.py     # Upload runs index to S3 for Athena
├── generate_runs_index.py             # Generate runs index from S3 results
├── generate_report_queries.sh         # Generate parameterized SQL query files
├── recreate_athena_table.sh           # Recreate Athena table with updated schema
├── export_all_fields.sh               # Export all fields to CSV for spreadsheet analysis
└── mark_baseline.py                   # Mark a run as baseline for comparison
```

## Recent Fixes (2025-11-16)

### Schema Updates

**Problem**: Athena table schema was missing critical columns that exist in the upload data:
- `is_outlier` - Manual flag to exclude bad runs ("yes"/"no")
- `is_best` - Automatically marks run with best avg_latency_sec
- `is_baseline` - Marks officially approved baseline run
- `baseline_marked_by`, `baseline_marked_date`, `baseline_notes` - Baseline metadata

**Fix**: Updated `setup_athena_runs_index.sql` (utilities/athena/setup_athena_runs_index.sql:77-91) and `upload_runs_index_to_athena.py` (utilities/athena/upload_runs_index_to_athena.py:104) to include these fields.

**Impact**: All 25 SQL queries in `ATHENA_QUERY_REFERENCE.md` now work without column resolution errors.

### Data Upload Format

**Format**: JSONL (JSON Lines) - one JSON object per line
- NOT Delta Lake or Parquet
- Timestamped filenames for true append behavior: `data_YYYYMMDD_HHMMSS.jsonl`
- JMeter CSV reports remain unchanged

**Structure**: Nested JSON is flattened for Athena compatibility
- Example: `run.cluster_info.instance_type` → `instance_type` column
- Example: `run.status_info.is_outlier` → `is_outlier` column

## Quick Start

### 1. Setup Athena Table (First Time Only)

```bash
# Option A: Using AWS CLI
aws athena start-query-execution \
  --query-string "$(cat utilities/athena/setup_athena_runs_index.sql)" \
  --query-execution-context Database=default \
  --result-configuration OutputLocation=s3://e6-jmeter/athena-query-results/

# Option B: Using AWS Console
# - Open Athena console
# - Copy/paste utilities/athena/setup_athena_runs_index.sql
# - Click "Run"
```

### 2. Upload Data to Athena

```bash
# Upload from local runs_index.json
python utilities/athena/upload_runs_index_to_athena.py reports/runs_index.json

# Generate index from S3 and upload directly
python utilities/athena/upload_runs_index_to_athena.py --from-s3 \
  s3://e6-jmeter/jmeter-results/engine=e6data/cluster_size=S-2x2/benchmark=tpcds_29_1tb/run_type=concurrency_4/

# Dry run (show what would be uploaded)
python utilities/athena/upload_runs_index_to_athena.py reports/runs_index.json --dry-run
```

### 3. Recreate Table with Updated Schema

If you need to update the schema (e.g., adding new columns):

```bash
# Recreate table and re-upload all data for a configuration
./utilities/athena/recreate_athena_table.sh e6data S-2x2 tpcds_29_1tb
```

This script:
1. Drops the existing `jmeter_runs_index` table
2. Creates new table with updated schema
3. Re-uploads all data for the specified configuration

## Report Generation Methods

### Method 1: Local CSV Reports (Offline)

Generate CSV reports from local `runs_index.json` files using `jq`:

```bash
# Example: Generate concurrency scaling report
jq -r '.runs[] | [
    .run_type,
    .results_summary.throughput.queries_per_second,
    .results_summary.latency_stats.avg_latency_sec,
    .results_summary.latency_stats.p90_latency_sec,
    .results_summary.latency_stats.p95_latency_sec,
    .results_summary.latency_stats.p99_latency_sec
] | @csv' reports/runs_index.json > concurrency_scaling.csv
```

**When to use**:
- No internet connection or AWS credentials
- Quick local analysis
- Offline processing
- Single configuration analysis

### Method 2: Athena SQL Queries (Cloud)

Query S3-hosted data using SQL in AWS Athena:

```bash
# Example: Valid runs only (exclude outliers)
aws athena start-query-execution \
  --query-string "SELECT run_id, cluster_size, run_type, p90_latency_sec, p99_latency_sec
                  FROM jmeter_runs_index
                  WHERE engine='e6data' AND is_outlier='no'
                  ORDER BY run_date DESC;" \
  --query-execution-context Database=default \
  --result-configuration OutputLocation=s3://e6-jmeter/athena-query-results/
```

**When to use**:
- Cross-configuration comparisons (multiple engines, clusters, benchmarks)
- Large-scale analysis across many runs
- Integration with dashboards (Superset, QuickSight)
- Collaborative analysis (shared data source)

**See `ATHENA_QUERY_REFERENCE.md` for 25+ ready-to-use SQL queries organized by category.**

### Method 3: Full Data Export for Spreadsheet Analysis

Export ALL fields (62 columns) from Athena to CSV for custom analysis in Google Sheets, Excel, or other tools:

```bash
# Export all fields for a specific configuration
./utilities/athena/export_all_fields.sh e6data S-2x2 tpcds_29_1tb reports/full_export.csv

# Auto-generate timestamped filename
./utilities/athena/export_all_fields.sh e6data S-2x2 tpcds_29_1tb
```

**What it exports:**
- All 62 fields from jmeter_runs_index table
- Complete run metadata (engine, cluster, benchmark, instance type, run_type)
- All latency metrics (avg, median, min, max, p50, p90, p95, p99)
- Throughput metrics (QPS, QPM)
- Test configuration (concurrency, hold period, ramp-up time)
- Performance ratings and outlier detection scores
- Baseline tracking information

**When to use:**
- Custom analysis and pivot tables in spreadsheets
- Creating custom charts and visualizations
- Exploring data relationships not covered by standard reports
- Sharing data with team members who prefer Excel/Sheets

### Method 4: Automated CSV Report Generation (Recommended)

Generate all 8 standard reports as CSV files in a single command:

```bash
# Generate reports for a specific configuration
./utilities/athena/run_athena_reports.sh e6data S-2x2 tpcds_29_1tb

# Custom output directory
./utilities/athena/run_athena_reports.sh e6data S-2x2 tpcds_29_1tb reports/my_analysis/
```

**What it does**:
- Executes 8 predefined Athena queries automatically
- Converts JSON results to CSV format using `jq`
- Saves all reports to timestamped output directory
- Creates README.txt with metadata
- Includes progress indicators and error handling

**Reports Generated**:
1. `01_valid_runs.csv` - All valid runs (outliers excluded)
2. `02_throughput_analysis.csv` - QPS/QPM metrics by concurrency
3. `03_best_runs.csv` - Best performing run per concurrency level
4. `04_concurrency_scaling.csv` - Performance scaling analysis
5. `05_recent_runs.csv` - Last 20 runs chronologically
6. `06_performance_summary.csv` - Statistics by instance type
7. `07_outlier_detection.csv` - Outlier metrics and z-scores
8. `08_error_rate_analysis.csv` - Error rates by concurrency

**When to use**:
- Quick comprehensive analysis of a configuration
- Generating reports for sharing/presentation
- Regular performance monitoring
- Comparing historical trends

**Example output**:
```
reports/athena_csv_reports_20251117_093609/
  01_valid_runs.csv              (5.9K) - 34 rows
  02_throughput_analysis.csv     (285B) - 5 rows
  03_best_runs.csv               (513B) - 5 rows
  04_concurrency_scaling.csv     (465B) - 5 rows
  05_recent_runs.csv             (2.1K) - 20 rows
  06_performance_summary.csv     (1.3K) - 12 rows
  07_outlier_detection.csv       (5.9K) - 74 rows
  08_error_rate_analysis.csv     (328B) - 5 rows
  README.txt                     (826B)
```

## Generating Parameterized SQL Queries

```bash
# Generate 8 SQL query files for a specific configuration
./utilities/athena/generate_report_queries.sh e6data S-2x2 tpcds_29_1tb

# Output: reports/athena_reports_TIMESTAMP/
#   01_valid_runs.sql
#   02_throughput_analysis.sql
#   03_best_runs.sql
#   04_concurrency_scaling.sql
#   05_outlier_detection.sql
#   06_performance_summary.sql
#   07_recent_runs.sql
#   08_file_verification.sql
```

## Key Files

**Setup & Schema:**
- `setup_athena_runs_index.sql` - Athena table DDL
- `ATHENA_QUICK_START.md` - Setup guide
- `ATHENA_RUNS_INDEX_README.md` - Architecture details

**Data Management:**
- `generate_runs_index.py` - Generate aggregated index from S3
- `upload_runs_index_to_athena.py` - Upload index to S3/Athena
- `sync_s3_to_athena.py` - Sync all results
- `upload_all_runs_to_athena.sh` - Bulk upload script

**Analysis:**
- `query_athena_runs.py` - Query programmatically
- `compare_runs_athena.py` - Compare runs
- `ATHENA_USEFUL_QUERIES.sql` - Example queries (best/worst runs, comparisons)
- `ATHENA_CONSOLE_QUERIES.sql` - Copy-paste queries for console

## Common Use Cases

### Find Best Run Per Configuration
```sql
WITH ranked AS (
    SELECT *, ROW_NUMBER() OVER (
        PARTITION BY cluster_size, run_type
        ORDER BY p90_latency_sec ASC
    ) as rank
    FROM jmeter_analysis.jmeter_runs_index
    WHERE engine = 'e6data'
)
SELECT run_id, cluster_size, run_type, p90_latency_sec
FROM ranked WHERE rank = 1;
```

### Compare Against Baseline
```sql
WITH baseline AS (
    SELECT cluster_size, AVG(p90_latency_sec) as baseline_p90
    FROM jmeter_analysis.jmeter_runs_index
    WHERE run_date >= CAST('2025-11-02' AS TIMESTAMP)
      AND run_date < CAST('2025-11-03' AS TIMESTAMP)
    GROUP BY cluster_size
)
SELECT r.run_id, r.cluster_size, r.p90_latency_sec,
       ROUND((r.p90_latency_sec - b.baseline_p90) / b.baseline_p90 * 100, 1) as pct_change
FROM jmeter_analysis.jmeter_runs_index r
JOIN baseline b ON r.cluster_size = b.cluster_size
WHERE r.run_date >= CAST('2025-11-06' AS TIMESTAMP)
ORDER BY pct_change DESC;
```

### Compare Engines/Instances
```sql
SELECT engine, instance_type, cluster_size,
       COUNT(*) as runs,
       ROUND(AVG(p90_latency_sec), 2) as avg_p90
FROM jmeter_analysis.jmeter_runs_index
WHERE benchmark = 'tpcds_29_1tb'
GROUP BY engine, instance_type, cluster_size
ORDER BY avg_p90;
```

## Dashboard Integration

**Apache Superset:**
```
Connection: awsathena+rest://athena.us-east-1.amazonaws.com:443/jmeter_analysis
Create dataset from: jmeter_runs_index
```

**AWS QuickSight:**
1. New data source → Athena
2. Select jmeter_analysis.jmeter_runs_index
3. Create visualizations

## Cost

~$5 per TB scanned (typically < $0.01 per query for this dataset)

## Documentation

- `ATHENA_QUICK_START.md` - Quick setup
- `ATHENA_RUNS_INDEX_README.md` - Detailed architecture
- `ATHENA_SYNC_GUIDE.md` - Data sync workflows
- `ATHENA_USEFUL_QUERIES.sql` - Curated query examples
