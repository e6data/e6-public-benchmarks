# JMeter Utilities & Analysis Tools

Comprehensive guide to all utility scripts for analyzing, comparing, and managing JMeter test results.

## Overview

| Script | Data Source | Purpose | Output |
|--------|-------------|---------|--------|
| `../create_connection.sh` | Interactive | Create connection properties (JDBC or HTTP) | Properties file |
| `../create_test_config.sh` | Interactive | Create test config (connection + plan + queries + params) | `.env` config file |
| `../run_test.sh` | Config file or env vars | Non-interactive test runner | Test results |
| `../run_jmeter_tests_interactive.sh` | Interactive | Run JMeter tests with guided setup | Test results |
| `compare_multi_concurrency_from_s3.py` | S3 | Compare 2 engines across all concurrency levels | CSV + MD |
| `compare_jmeter_runs_from_s3.py` | S3 | Compare 2 engines at single concurrency level | CSV + MD |
| `compare_consecutive_runs_from_s3.py` | S3 | Compare 2 runs of same engine (regression detection) | MD |
| `analyze_concurrency_scaling_from_s3.py` | S3 | Analyze single engine scaling behavior | MD |
| `analyze_aggregate_report.py` | Local | Analyze single run from local aggregate report | Console |
| `post_test_analysis.sh` | S3 | Automated post-test workflow (sync, compare, report) | Multiple |
| `run_all_concurrency.sh` | - | Batch run all concurrency levels (1,2,4,8,12,16) | Test results |

**Athena Integration** (in `athena/` subdirectory):

| Script | Purpose |
|--------|---------|
| `athena/upload_runs_index_to_athena.py` | Upload runs index to S3 for Athena |
| `athena/export_all_fields.sh` | Export all 62 fields to CSV for spreadsheet analysis |
| `athena/run_athena_reports.sh` | Run all 8 standard Athena reports |
| `athena/manage_baseline.py` | Mark/unmark baselines and compare runs |
| `athena/query_athena_runs.py` | Query Athena with flexible filters |
| `athena/verify_baseline_sync.py` | Verify S3 and Athena baseline data sync |

## S3 Path Structure

Results are stored in a 5-level partitioned hierarchy:

```
s3://bucket/jmeter-results/
  engine=<e6data|dbr>/
    cluster_size=<XS-1x1|S-2x2|M-4x4|S-4x4|etc>/
      benchmark=<tpcds_29_1tb|etc>/
        run_type=<concurrency_X|sequential>/
          run_id=<YYYYMMDD-HHMMSS>/
            statistics.json
            JmeterResultFile.csv
            AggregateReport.csv
            test_result.json
          latest.json
```

**Discover available paths:**
```bash
aws s3 ls s3://your-s3-bucket/jmeter-results/                              # engines
aws s3 ls s3://your-s3-bucket/jmeter-results/engine=e6data/                # cluster sizes
aws s3 ls s3://your-s3-bucket/jmeter-results/engine=e6data/cluster_size=S-2x2/  # benchmarks
```

## Quick Start

**Pre-flight checklist:**
1. AWS credentials configured: `aws s3 ls s3://your-s3-bucket/`
2. Python 3.7+ installed: `python3 --version`
3. In correct directory: `cd jmeter-jdbc-test-framework`

**Most common command** — compare all concurrency runs between two engines:

```bash
python utilities/compare_multi_concurrency_from_s3.py \
  s3://your-s3-bucket/jmeter-results/engine=e6data/cluster_size=S-2x2/benchmark=tpcds_29_1tb/ \
  s3://your-s3-bucket/jmeter-results/engine=dbr/cluster_size=S-4x4/benchmark=tpcds_29_1tb/
```

## Comparison Scripts

### `compare_multi_concurrency_from_s3.py`

Compare two engines/clusters across ALL concurrency levels automatically. This is the most comprehensive comparison tool.

```bash
python utilities/compare_multi_concurrency_from_s3.py \
  s3://your-s3-bucket/jmeter-results/engine=ENGINE1/cluster_size=CLUSTER1/benchmark=BENCHMARK/ \
  s3://your-s3-bucket/jmeter-results/engine=ENGINE2/cluster_size=CLUSTER2/benchmark=BENCHMARK/
```

**How it works:**
1. Scans both paths for all `run_type=concurrency_X/` directories
2. Finds matching concurrency levels
3. Downloads statistics.json for each match
4. Generates comparison across all concurrency levels

**Output:** `reports/{engine1}_{cluster1}_vs_{engine2}_{cluster2}_MultiConcurrency_{date}.csv` + `_SUMMARY.md`

### `compare_jmeter_runs_from_s3.py`

Deep-dive comparison of two engines at a single concurrency level.

```bash
python utilities/compare_jmeter_runs_from_s3.py \
  s3://your-s3-bucket/jmeter-results/engine=e6data/cluster_size=M-4x4/benchmark=tpcds_29_1tb/run_type=concurrency_4/ \
  s3://your-s3-bucket/jmeter-results/engine=dbr/cluster_size=S-4x4/benchmark=tpcds_29_1tb/run_type=concurrency_4/
```

**Output:** `reports/{eng1}_{cl1}_vs_{eng2}_{cl2}_C{X}_{date}.csv` + `_SUMMARY.md`

### `compare_consecutive_runs_from_s3.py`

Compare two consecutive runs of the same engine to detect regressions or improvements.

```bash
# Automatic — compares 2 most recent runs
python utilities/compare_consecutive_runs_from_s3.py \
  --base-path s3://your-s3-bucket/jmeter-results/engine=e6data/cluster_size=S-2x2/benchmark=tpcds_29_1tb/

# Specific run IDs
python utilities/compare_consecutive_runs_from_s3.py \
  --base-path s3://your-s3-bucket/jmeter-results/engine=e6data/cluster_size=S-2x2/benchmark=tpcds_29_1tb/ \
  --run-id1 20251030-171659 \
  --run-id2 20251031-070614
```

**Features:**
- Query-by-query comparison showing individual query changes
- Auto-detect latest 2 runs or manual run ID selection
- Cold start detection via BOOTSTRAP query analysis
- Run IDs in filename for traceability

**Output:** `reports/{engine}_{cluster}_ConsecutiveRuns_{id1}_vs_{id2}.md`

## Analysis Scripts

### `analyze_concurrency_scaling_from_s3.py`

Analyze how a single engine scales as concurrency increases.

```bash
python utilities/analyze_concurrency_scaling_from_s3.py \
  --base-path s3://your-s3-bucket/jmeter-results/engine=e6data/cluster_size=S-2x2/benchmark=tpcds_29_1tb/
```

**Reports:**
- Performance by concurrency level
- Degradation analysis (performance loss at each level)
- Scaling efficiency: ratio of concurrency increase to latency increase (100% = baseline, >100% = super-linear, <100% = degrading)
- Production readiness assessment

**Output:** `reports/{engine}_{cluster}_ConcurrencyScaling_{date}_ANALYSIS.md`

### `analyze_aggregate_report.py`

Analyze a single local JMeter aggregate report CSV file. Auto-invoked by `run_jmeter_tests_interactive.sh` after each test.

```bash
python utilities/analyze_aggregate_report.py reports/AggregateReport_20251031_123456.csv
```

## Core Library: `jmeter_s3_utils.py`

Shared utility module used by all S3-based scripts:

- **`JMeterS3Path`** class: Parse and validate S3 paths, extract engine/cluster/concurrency metadata
- **`download_jmeter_statistics()`**: Download statistics.json from S3
- **`load_jmeter_statistics()`**: Parse statistics.json
- **`extract_query_metrics()`**: Extract metrics for a specific query
- **`create_query_mapping()`**: Map query names between engines (E6Data `query-2-TPCDS-2` vs DBR `TPCDS-2`)
- **`calculate_percentage_diff()`**: Calculate percentage differences

```python
from utilities.jmeter_s3_utils import JMeterS3Path, download_jmeter_statistics

path = JMeterS3Path('s3://bucket/.../')
print(f"Engine: {path.engine}, Concurrency: {path.concurrency}")
```

## Understanding Output

### Metrics

All metrics are in **seconds**:
- **Avg**: Mean response time across all executions
- **Median (p50)**: 50th percentile
- **p90/p95/p99**: Tail latencies — critical for production (worst-case user experience)
- **Min/Max**: Fastest and slowest execution times

### Percentage Differences

- **Positive % (e.g., +50.5%)**: First engine (Engine 1) is FASTER
- **Negative % (e.g., -35.2%)**: Second engine (Engine 2) is FASTER
- **~0%**: Both engines are comparable

### Query Name Mapping

Scripts automatically normalize different naming conventions:
- E6Data: `query-2-TPCDS-2`, `query-13-TPCDS-13-optimised`
- DBR: `TPCDS-2`, `TPCDS-13`
- Normalized to: `TPCDS-X` format

### Report Naming Conventions

```
# Multi-concurrency comparison
{engine1}_{cluster1}_vs_{engine2}_{cluster2}_MultiConcurrency_{date}.csv

# Single concurrency comparison
{engine1}_{cluster1}_vs_{engine2}_{cluster2}_C{X}_{date}.csv

# Consecutive runs
{engine}_{cluster}_ConsecutiveRuns_{run_id1}_vs_{run_id2}.md

# Scaling analysis
{engine}_{cluster}_ConcurrencyScaling_{date}_ANALYSIS.md
```

## Decision Guide

### Which Script to Use?

```
Comparing two different engines/clusters?
  |-- All concurrency levels? --> compare_multi_concurrency_from_s3.py
  |-- Single concurrency?     --> compare_jmeter_runs_from_s3.py

Comparing same engine over time?
  --> compare_consecutive_runs_from_s3.py

Understanding scaling behavior?
  --> analyze_concurrency_scaling_from_s3.py

Quick local analysis?
  --> analyze_aggregate_report.py
```

| Script | Answers | Query Details | Multi-Concurrency | Run ID Selection |
|--------|---------|---------------|-------------------|------------------|
| `compare_multi_concurrency_from_s3.py` | "Which engine is better?" | Yes | Auto | Uses latest |
| `compare_jmeter_runs_from_s3.py` | "Which is better at C=X?" | Yes | Single | Uses latest |
| `compare_consecutive_runs_from_s3.py` | "Did performance change?" | Yes | Auto | Auto or manual |
| `analyze_concurrency_scaling_from_s3.py` | "How does it scale?" | No | Auto | Uses latest |
| `analyze_aggregate_report.py` | "What are the results?" | Yes | Single | Local file |

## Common Workflows

### Regression Testing After Code Changes

```bash
# Run new test
./run_jmeter_tests_interactive.sh

# Compare with previous run
python utilities/compare_consecutive_runs_from_s3.py \
  --base-path s3://your-s3-bucket/jmeter-results/engine=e6data/cluster_size=S-2x2/benchmark=tpcds_29_1tb/
```

Look for: BOOTSTRAP query degradation (cold start), uniform improvement (good optimization), specific query regressions (investigate those).

### Cluster Sizing Decision

```bash
# Compare clusters
python utilities/compare_multi_concurrency_from_s3.py \
  s3://your-s3-bucket/jmeter-results/engine=e6data/cluster_size=S-2x2/benchmark=tpcds_29_1tb/ \
  s3://your-s3-bucket/jmeter-results/engine=e6data/cluster_size=M-4x4/benchmark=tpcds_29_1tb/

# Analyze scaling for each
python utilities/analyze_concurrency_scaling_from_s3.py \
  --base-path s3://your-s3-bucket/jmeter-results/engine=e6data/cluster_size=S-2x2/benchmark=tpcds_29_1tb/
```

### Engine Evaluation (E6Data vs DBR)

```bash
# Full comparison + scaling analysis
python utilities/compare_multi_concurrency_from_s3.py \
  s3://your-s3-bucket/jmeter-results/engine=e6data/cluster_size=S-2x2/benchmark=tpcds_29_1tb/ \
  s3://your-s3-bucket/jmeter-results/engine=dbr/cluster_size=S-2x2/benchmark=tpcds_29_1tb/
```

### Automated Post-Test Analysis

```bash
# Recommended: runs sync, comparison, and reporting in one step
./utilities/post_test_analysis.sh e6data S-2x2 tpcds_29_1tb <your_name>
```

## Athena Integration

The `athena/` subdirectory contains tools for uploading JMeter results to AWS Athena and querying them with SQL.

### File Structure

```
utilities/athena/
├── WORKING_QUERIES.sql                # Tested SQL queries for analysis
├── setup_athena_runs_index.sql        # Athena table DDL
├── setup_all_athena_tables.sh         # Setup all tables at once
├── recreate_athena_table.sh           # Recreate table with updated schema
├── upload_runs_index_to_athena.py     # Upload runs index to S3 for Athena
├── upload_metadata.py                 # Upload cluster metadata
├── generate_runs_index.py             # Generate runs index from S3
├── generate_metadata_index.py         # Generate metadata index from S3
├── generate_report_queries.sh         # Generate parameterized SQL files
├── run_athena_reports.sh              # Run all 8 standard reports
├── export_all_fields.sh               # Export all 62 fields to CSV
├── manage_baseline.py                 # Mark/unmark baselines
├── verify_baseline_sync.py            # Verify S3/Athena sync
├── query_athena_runs.py               # Query with flexible filters
├── compare_runs_athena.py             # Compare runs via Athena
├── sync_s3_to_athena.py               # Sync S3 results to Athena
├── ddl/                               # DDL scripts for table creation
└── setup/                             # Setup and migration scripts
```

### Quick Start

**1. Setup Athena Table (first time only):**
```bash
aws athena start-query-execution \
  --query-string "$(cat utilities/athena/setup_athena_runs_index.sql)" \
  --query-execution-context Database=default \
  --result-configuration OutputLocation=s3://your-s3-bucket/athena-query-results/
```

**2. Upload data:**
```bash
# From S3 directly
python utilities/athena/upload_runs_index_to_athena.py --from-s3 \
  s3://your-s3-bucket/jmeter-results/engine=e6data/cluster_size=S-2x2/benchmark=tpcds_29_1tb/run_type=concurrency_4/
```

**3. Query:**
```bash
# Run all 8 standard reports
./utilities/athena/run_athena_reports.sh e6data S-2x2 tpcds_29_1tb
```

### Report Generation Methods

**Method 1: Local CSV Reports (Offline)**

Generate reports from local `runs_index.json` using `jq`:
```bash
jq -r '.runs[] | [.run_type, .results_summary.throughput.queries_per_second,
  .results_summary.latency_stats.avg_latency_sec] | @csv' reports/runs_index.json
```

**Method 2: Athena SQL Queries**

Query S3-hosted data using SQL. See `WORKING_QUERIES.sql` for ready-to-use queries.

```sql
SELECT run_id, cluster_size, run_type, p90_latency_sec
FROM jmeter_runs_index
WHERE engine='e6data' AND is_outlier='no'
ORDER BY run_date DESC;
```

**Method 3: Full Data Export (62 columns)**

```bash
./utilities/athena/export_all_fields.sh e6data S-2x2 tpcds_29_1tb reports/full_export.csv
```

Exports all fields for custom analysis in Google Sheets, Excel, Tableau, etc.

**Method 4: Automated Batch Reports (Recommended)**

```bash
./utilities/athena/run_athena_reports.sh e6data S-2x2 tpcds_29_1tb
```

Generates 8 standard CSV reports:
1. `01_valid_runs.csv` — All valid runs (outliers excluded)
2. `02_throughput_analysis.csv` — QPS/QPM by concurrency
3. `03_best_runs.csv` — Best run per concurrency level
4. `04_concurrency_scaling.csv` — Scaling analysis
5. `05_recent_runs.csv` — Last 20 runs
6. `06_performance_summary.csv` — Stats by instance type
7. `07_outlier_detection.csv` — Outlier metrics and z-scores
8. `08_error_rate_analysis.csv` — Error rates by concurrency

### Baseline Management

The framework provides baseline tracking using a dual-sync approach (S3 metadata + Athena columns):

- **Best Run (`is_best`)**: Automatically identified as lowest `avg_latency_sec` per configuration
- **Baseline Run (`is_baseline`)**: Manually set reference point for comparing new runs

```bash
# Automated post-test workflow (recommended)
./utilities/post_test_analysis.sh e6data S-2x2 tpcds_29_1tb <your_name>

# Manual: sync to Athena
python3 utilities/athena/upload_runs_index_to_athena.py --from-s3 <s3_path>

# Compare against baseline
python3 utilities/athena/manage_baseline.py compare --run-id <new_run_id> ...

# Mark new baseline
python3 utilities/athena/manage_baseline.py mark --run-id <new_run_id> --user <name> ...

# Verify sync
python3 utilities/athena/verify_baseline_sync.py --engine e6data --verify-all
```

### Dashboard Integration

**Apache Superset:**
```
Connection: awsathena+rest://athena.us-east-1.amazonaws.com:443/jmeter_analysis
Dataset: jmeter_runs_index
```

**AWS QuickSight:** New data source -> Athena -> jmeter_analysis.jmeter_runs_index

**Cost:** ~$5 per TB scanned (typically < $0.01 per query for this dataset)

## Troubleshooting

**"Invalid S3 path format"**
Check path follows: `s3://bucket/.../engine=X/cluster_size=Y/benchmark=Z/`

**"Could not find statistics.json"**
Verify: `aws s3 ls s3://path/to/run/` — check the test completed and S3 upload was enabled.

**"No matching concurrency levels found"**
Ensure both engines have at least one matching `run_type=concurrency_X/` directory.

**AWS credentials issue**
Run `aws configure` or set `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`.

## Tips and Best Practices

1. **Use multi-concurrency comparison** for comprehensive analysis instead of running single-concurrency comparisons repeatedly.
2. **Check for cold starts** when seeing regressions — BOOTSTRAP queries with massive degradation indicate cold cluster.
3. **Compare scaling before choosing cluster size** — check scaling efficiency at your target concurrency, not just raw performance.
4. **Track performance over time** — run `compare_consecutive_runs_from_s3.py` regularly to catch regressions early.
5. **Verify S3 paths first**: `aws s3 ls s3://your-s3-bucket/jmeter-results/engine=e6data/cluster_size=S-2x2/`
