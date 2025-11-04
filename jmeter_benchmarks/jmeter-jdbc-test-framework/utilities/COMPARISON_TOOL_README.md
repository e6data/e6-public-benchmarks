# JMeter S3 Comparison Tools

Standardized tools for comparing JMeter performance test results stored in S3.

## Overview

This framework provides reusable scripts to compare JMeter test results between different database engines (e.g., E6Data vs DBR) stored in S3. The tools automatically download statistics, perform comparisons, and generate standardized reports.

## Prerequisites

- Python 3.7+
- AWS CLI configured with credentials
- S3 access to JMeter results bucket

## S3 Path Structure

The tools expect JMeter results in the following S3 structure:

```
s3://bucket/jmeter-results/
  engine=<e6data|dbr>/
    cluster_size=<XS|S-2x2|M|S-4x4|etc>/
      benchmark=<tpcds_29_1tb|etc>/
        run_type=<concurrency_X|sequential>/
          statistics_TIMESTAMP.json
          JmeterResultFile_TIMESTAMP.csv
          AggregateReport_TIMESTAMP.csv
          test_result_TIMESTAMP.json
```

## Tools

### 1. `jmeter_s3_utils.py`

Core utility module providing reusable functions:

- **S3 Path Parsing**: Extract metadata (engine, cluster size, concurrency, etc.)
- **S3 Operations**: Download files, list directories
- **Statistics Processing**: Load and parse JMeter statistics.json files
- **Query Mapping**: Map query names between different engines
- **Calculations**: Percentage differences, metric extraction

**Key Classes:**
- `JMeterS3Path`: Parse and validate S3 paths

**Key Functions:**
- `download_jmeter_statistics()`: Download statistics.json from S3
- `load_jmeter_statistics()`: Parse statistics.json file
- `extract_query_metrics()`: Extract metrics for a specific query
- `create_query_mapping()`: Map query names between engines
- `calculate_percentage_diff()`: Calculate percentage differences

### 2. `compare_jmeter_runs.py`

Compare two individual JMeter runs (single concurrency level).

**Usage:**
```bash
python utilities/compare_jmeter_runs.py S3_PATH_1 S3_PATH_2 [--output-dir reports]
```

**Example:**
```bash
python utilities/compare_jmeter_runs.py \
  s3://e6-jmeter/jmeter-results/engine=e6data/cluster_size=M/benchmark=tpcds_29_1tb/run_type=concurrency_2/ \
  s3://e6-jmeter/jmeter-results/engine=dbr/cluster_size=S-4x4/benchmark=tpcds_29_1tb/run_type=concurrency_2/ \
  --output-dir reports
```

**Generated Files:**
- `E6D_M_vs_DAT_S4x4_concurrency2_YYYYMMDD.csv` - Detailed query-level comparison
- `E6D_M_vs_DAT_S4x4_concurrency2_YYYYMMDD_SUMMARY.md` - Executive summary

**CSV Columns:**
- Query name
- Engine 1 metrics: Avg, Median, p90, p95, p99, Min, Max
- Engine 2 metrics: Avg, Median, p90, p95, p99, Min, Max  
- Differences: % difference for each metric (positive = Engine 1 faster)
- Summary statistics at the bottom

**Markdown Summary Includes:**
- Configuration comparison
- Performance summary table
- Key findings
- Overall winner
- Recommendations

### 3. `compare_multi_concurrency.py`

Compare all concurrency levels between two engines automatically.

**Usage:**
```bash
python utilities/compare_multi_concurrency.py ENGINE1_BASE ENGINE2_BASE [--output-dir reports]
```

**Example:**
```bash
python utilities/compare_multi_concurrency.py \
  s3://e6-jmeter/jmeter-results/engine=e6data/cluster_size=M/benchmark=tpcds_29_1tb/ \
  s3://e6-jmeter/jmeter-results/engine=dbr/cluster_size=S-4x4/benchmark=tpcds_29_1tb/ \
  --output-dir reports
```

**How it Works:**
1. Automatically scans both base paths for all `run_type=concurrency_X/` directories
2. Finds matching concurrency levels between the two engines
3. Downloads statistics.json for each matching concurrency
4. Generates comprehensive comparison across ALL concurrency levels

**Generated Files:**
- `e6data_M_vs_dbr_S-4x4_MultiConcurrency_YYYYMMDD.csv` - All concurrencies side-by-side
- `e6data_M_vs_dbr_S-4x4_MultiConcurrency_YYYYMMDD_SUMMARY.md` - Executive summary

**CSV Structure:**
- One row per query
- For each concurrency level (C=2, 4, 8, 12, 16...):
  - Engine 1: Avg, Median, p90, p95, p99, Min, Max
  - Engine 2: Avg, Median, p90, p95, p99, Min, Max
  - Differences: % for each metric
- Summary statistics rows at bottom

**Markdown Summary Includes:**
- Configuration comparison
- Performance breakdown by each concurrency level
- Overall winner across all concurrencies
- Recommendations

## Common Use Cases

### Case 1: Compare Single Concurrency Run

You ran tests at C=4 for both engines and want to compare:

```bash
python utilities/compare_jmeter_runs.py \
  s3://e6-jmeter/jmeter-results/engine=e6data/cluster_size=M/benchmark=tpcds_29_1tb/run_type=concurrency_4/ \
  s3://e6-jmeter/jmeter-results/engine=dbr/cluster_size=S-4x4/benchmark=tpcds_29_1tb/run_type=concurrency_4/
```

### Case 2: Compare All Concurrencies (Most Common)

You ran tests at multiple concurrency levels and want comprehensive comparison:

```bash
python utilities/compare_multi_concurrency.py \
  s3://e6-jmeter/jmeter-results/engine=e6data/cluster_size=M/benchmark=tpcds_29_1tb/ \
  s3://e6-jmeter/jmeter-results/engine=dbr/cluster_size=S-4x4/benchmark=tpcds_29_1tb/
```

This automatically finds all matching concurrency levels and compares them.

### Case 3: Compare Different Cluster Sizes

Compare E6Data small cluster vs DBR small cluster:

```bash
python utilities/compare_multi_concurrency.py \
  s3://e6-jmeter/jmeter-results/engine=e6data/cluster_size=S-2x2/benchmark=tpcds_29_1tb/ \
  s3://e6-jmeter/jmeter-results/engine=dbr/cluster_size=S-2x2/benchmark=tpcds_29_1tb/
```

### Case 4: Compare Sequential Runs

Compare performance without concurrency:

```bash
python utilities/compare_jmeter_runs.py \
  s3://e6-jmeter/jmeter-results/engine=e6data/cluster_size=XS/benchmark=tpcds_29_1tb/run_type=sequential/ \
  s3://e6-jmeter/jmeter-results/engine=dbr/cluster_size=XS/benchmark=tpcds_29_1tb/run_type=sequential/
```

## Understanding the Output

### CSV Files

Open in Excel, Google Sheets, or any CSV viewer:
- Each row is a TPCDS query
- Columns show metrics for both engines side-by-side
- Percentage differences show which engine is faster:
  - **Positive %**: First engine (Engine 1) is faster
  - **Negative %**: Second engine (Engine 2) is faster
- Summary rows at bottom show averages across all queries

### Markdown Files

Open in any text editor or markdown viewer:
- Configuration comparison table
- Performance summary with emoji indicators:
  - ✅ = Winner/Better performance
  - ⚠️ = Slower/Worse performance
  - 📊 = Comparable performance
- Key findings section highlights major differences
- Recommendations for production use

## Query Name Mapping

The tools automatically handle different query naming conventions:

- **E6Data format**: `query-2-TPCDS-2`, `query-13-TPCDS-13-optimised`
- **DBR format**: `TPCDS-2`, `TPCDS-13`

The tools normalize these to `TPCDS-X` format for comparison.

## Metrics Explained

All metrics are in **seconds** unless otherwise noted:

- **Avg (Average)**: Mean response time across all query executions
- **Median (p50)**: Middle value - 50% of queries faster, 50% slower
- **p90**: 90th percentile - 90% of queries completed faster than this
- **p95**: 95th percentile - 95% of queries completed faster than this
- **p99**: 99th percentile - 99% of queries completed faster than this
- **Min**: Fastest query execution time
- **Max**: Slowest query execution time

**Tail latencies (p90, p95, p99)** are critical for production systems - they show worst-case user experience.

## Troubleshooting

### Error: "Invalid S3 path format"

Make sure your S3 path follows the expected structure:
```
s3://bucket/prefix/engine=X/cluster_size=Y/benchmark=Z/run_type=W/
```

### Error: "Could not find statistics.json"

The statistics.json file might not exist in S3. Check:
1. Does the path exist? (`aws s3 ls s3://path/`)
2. Did the JMeter test complete successfully?
3. Was `COPY_TO_S3=true` in test properties?

### Error: "No matching concurrency levels found"

When using `compare_multi_concurrency.py`, ensure both engines have at least one matching concurrency level (e.g., both have `run_type=concurrency_2/`).

### AWS Credentials Issues

Ensure AWS CLI is configured:
```bash
aws configure
# or set environment variables:
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...
export AWS_DEFAULT_REGION=us-east-1
```

## Advanced Usage

### Custom Output Directory

By default, reports go to `reports/` directory. Change it:

```bash
python utilities/compare_jmeter_runs.py path1 path2 --output-dir /path/to/custom/dir
```

### Programmatic Usage

Import the utilities in your own Python scripts:

```python
from utilities.jmeter_s3_utils import (
    JMeterS3Path,
    download_jmeter_statistics,
    load_jmeter_statistics,
    extract_query_metrics,
)

# Parse S3 path
path = JMeterS3Path('s3://bucket/.../')
print(f"Engine: {path.engine}, Concurrency: {path.concurrency}")

# Download and load statistics
stats_file = download_jmeter_statistics(s3_path, local_dir)
stats = load_jmeter_statistics(stats_file)

# Extract metrics for a query
metrics = extract_query_metrics(stats, 'TPCDS-13')
print(f"Average: {metrics['avg']:.2f}s, p99: {metrics['p99']:.2f}s")
```

## Report Standardization

All reports follow consistent naming:

**Single Run Comparison:**
```
{ENGINE1}_{CLUSTER1}_vs_{ENGINE2}_{CLUSTER2}_{RUN_TYPE}_{DATE}.csv
{ENGINE1}_{CLUSTER1}_vs_{ENGINE2}_{CLUSTER2}_{RUN_TYPE}_{DATE}_SUMMARY.md
```

**Multi-Concurrency Comparison:**
```
{ENGINE1}_{CLUSTER1}_vs_{ENGINE2}_{CLUSTER2}_MultiConcurrency_{DATE}.csv
{ENGINE1}_{CLUSTER1}_vs_{ENGINE2}_{CLUSTER2}_MultiConcurrency_{DATE}_SUMMARY.md
```

This ensures reports are:
- Self-documenting (filename tells you what's inside)
- Sortable by date
- Easy to find and reference

## Examples from Production

### Example 1: 120-Core Comparison

```bash
# Compare E6Data M (120 cores) vs DBR S-4x4 (120 cores) across all concurrencies
python utilities/compare_multi_concurrency.py \
  s3://e6-jmeter/jmeter-results/engine=e6data/cluster_size=M/benchmark=tpcds_29_1tb/ \
  s3://e6-jmeter/jmeter-results/engine=dbr/cluster_size=S-4x4/benchmark=tpcds_29_1tb/

# Output:
# - reports/e6data_M_vs_dbr_S-4x4_MultiConcurrency_20251031.csv
# - reports/e6data_M_vs_dbr_S-4x4_MultiConcurrency_20251031_SUMMARY.md
```

### Example 2: 60-Core Comparison

```bash
# Compare E6Data S-2x2 vs DBR S-2x2 (both 60 cores)
python utilities/compare_multi_concurrency.py \
  s3://e6-jmeter/jmeter-results/engine=e6data/cluster_size=S-2x2/benchmark=tpcds_29_1tb/ \
  s3://e6-jmeter/jmeter-results/engine=dbr/cluster_size=S-2x2/benchmark=tpcds_29_1tb/
```

### Example 3: Sequential Execution (No Concurrency)

```bash
# Compare XS clusters running queries sequentially
python utilities/compare_jmeter_runs.py \
  s3://e6-jmeter/jmeter-results/engine=e6data/cluster_size=XS/benchmark=tpcds_29_1tb/run_type=sequential/ \
  s3://e6-jmeter/jmeter-results/engine=dbr/cluster_size=XS/benchmark=tpcds_29_1tb/run_type=sequential/
```

## Tips and Best Practices

1. **Use Multi-Concurrency Tool for Comprehensive Analysis**: When you have multiple concurrency runs, always use `compare_multi_concurrency.py` instead of running `compare_jmeter_runs.py` multiple times.

2. **Check S3 Paths First**: Before running comparisons, verify both S3 paths exist:
   ```bash
   aws s3 ls s3://e6-jmeter/jmeter-results/engine=e6data/cluster_size=M/benchmark=tpcds_29_1tb/
   ```

3. **Keep Reports Organized**: Use descriptive output directories:
   ```bash
   --output-dir reports/JPMC_comparison_$(date +%Y%m%d)
   ```

4. **Archive Old Reports**: Move old reports to archive folder to keep `reports/` clean:
   ```bash
   mkdir -p reports/archive
   mv reports/*_202510*.md reports/archive/
   ```

5. **Version Control Reports**: Commit important comparison reports to git for historical tracking.

## Future Enhancements

Potential improvements for the framework:

- [ ] JSON output format for programmatic consumption
- [ ] HTML report generation with charts
- [ ] Support for multiple benchmarks in one comparison
- [ ] Automated regression detection
- [ ] Email report delivery
- [ ] Dashboard integration

## Support

For issues or questions:
1. Check this README
2. Review CLAUDE.md for JMeter framework details
3. Check tool help: `python utilities/compare_jmeter_runs.py --help`

---

**Last Updated**: October 31, 2025  
**Version**: 1.0
