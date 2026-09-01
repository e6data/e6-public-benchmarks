# JMeter Utilities & Analysis Tools

Comprehensive guide to all utility scripts for analyzing, comparing, and managing JMeter test results.

## Script Inventory

The inventory below is grouped by purpose. Counts are intentionally omitted because this directory evolves frequently; use `find utilities -type f` for the current file list.

### Analysis & Comparison (9)

| Script | Purpose |
|--------|---------|
| `analyze_aggregate_report.py` | Analyze JMeter aggregate report CSV with performance stats and error categorization |
| `analyze_concurrency_scaling_from_s3.py` | Show how performance changes as concurrency increases for one engine |
| `analyze_single_run_from_s3.py` | Fetch a single run from S3 and generate detailed markdown report |
| `compare_consecutive_runs_from_s3.py` | Compare two consecutive runs for regression testing |
| `compare_jmeter_runs_from_s3.py` | Compare any two JMeter runs from S3 (CSV + markdown output) |
| `get_e6_query_history.py` | Export e6 Query History for the exact time window represented by a JMeter result CSV |
| `compare_multi_concurrency_from_s3.py` | Find and compare all concurrency levels between two engines |
| `compare_multiple_runs_from_s3.py` | Compare N runs with metadata columns, supports batch directory scanning |
| `compare_engines_concurrency.sh` | Compare concurrency scaling between two engines (text/markdown/json output) |
| `post_test_analysis.sh` | End-to-end post-test workflow: sync to Athena, compare baseline, generate reports |

### Runner & Config (3)

| Script | Purpose |
|--------|---------|
| `run_all_concurrency.sh` | Run all concurrency levels (1, 2, 4, 8, 12, 16) for a given engine/cluster/benchmark |
| `generate_concurrency_test_configs.sh` | Generate metadata + test property files for concurrency testing |
| `update_load_profile.sh` | Update JMX test plan with load profile from CSV file |

### Query Conversion (2)

| Script | Purpose |
|--------|---------|
| `convert_queries_for_jmeter_http.py` | Convert multiline SQL to single-line for JMeter HTTP API (no quote escaping) |
| `convert_queries_for_json_api.py` | Convert multiline SQL to single-line with JSON/e6data fixes (backticks, keywords, CTEs) |

### Load Profile

| Script | Purpose |
|--------|---------|
| `apply_load_profile.py` | Inject a load-profile CSV into a plan's thread-group schedule before JMeter starts |
| `capture_run_report.py` | Write `run_summary.json` + `run_report.md` into a run dir (called automatically by both runners) |
| `verify_load_profile.py` | Confirm arrivals matched the profile, per second |
| `analyze_queue_buildup.py` | Queue depth / drain reconstruction for arrivals runs |

Called automatically by `run_jmeter_tests_interactive.sh` and `run_test.sh` whenever the
selected plan contains a `FreeFormArrivalsThreadGroup` or an `UltimateThreadGroup`. Point
`LOAD_PROFILE` at any CSV — no per-profile test plan is needed.

Two formats, chosen from the plan rather than a flag (header optional, times in seconds):

| Plan controls | Thread group | Block rewritten | CSV columns |
|---|---|---|---|
| arrival rate | `FreeFormArrivalsThreadGroup` | `Schedule` | `StartValue,EndValue,Duration` |
| concurrency | `UltimateThreadGroup` | `ultimatethreadgroupdata` | `Threads,StartTime,StartupTime,HoldTime,ShutdownTime` |

Concurrency rows **stack** — each wave adds its threads on top of any still running — and
ramp linearly over `StartupTime` / `ShutdownTime`. Set both to `0` for a flat step.

```properties
LOAD_PROFILE=test_properties/my_profile.csv
RECYCLE_ON_EOF=true      # required for both: without it threads hit EOF and vanish
MAX_CONCURRANCY=200      # arrivals plan only; must exceed peak_qps x avg_latency_sec
HOLD_PERIOD=60           # arrivals plan only; >= the profile's total duration
```

The concurrency plan ignores `MAX_CONCURRANCY` and `HOLD_PERIOD` — its CSV sets both the
concurrency and the run length.

**You do not need a properties file per profile.** Environment values override the file, so one
config serves every profile:

```bash
LOAD_PROFILE=test_properties/spike.csv ./run_jmeter_tests_interactive.sh
LOAD_PROFILE=test_properties/spike.csv ./run_test.sh test_configs/my.env
```

Both runners print what was overridden. Also overridable this way: `HOLD_PERIOD`,
`MAX_CONCURRANCY`, `COPY_TO_S3`, `RECYCLE_ON_EOF`, `RANDOM_ORDER`, `QPS`, `QPM`,
`CONCURRENT_QUERY_COUNT`, `RAMP_UP_TIME`, `RAMP_UP_STEPS`, `QUERY_TIMEOUT`.

**Why this is needed:** the plan ships a JSR223 PreProcessor that tries to apply the profile
via `ctx.getThreadGroup().setData()`. A PreProcessor runs when a sampler fires, by which point
the thread group has already read its `Schedule` — so the CSV was silently ignored and the
plan's hardcoded schedule (25 arrivals over 15s) was used instead. The schedule is now
injected before JMeter launches. The generated plan is written into the run's own
`reports/<timestamp>/` directory as a per-run artifact.

Verify the queries actually fired at the requested rate:

```bash
python3 utilities/verify_load_profile.py \
  reports/<timestamp>/JmeterResultFile.csv test_properties/my_profile.csv
```

JMeter's `timeStamp` column is each sample's *start* time, so bucketing it per second
reconstructs the true arrival curve — unaffected by how long queries took to finish, which
matters because a saturated cluster stretches completions well past the profile window.

```
 sec | expected | actual |
   8 |       56 |     56 | ########################################################
...
expected : 482
actual   : 480  (99.6%)
```

Confirm what was applied — the line is printed on every run:

```
load profile applied: 15 steps, 17s, peak 56/s, ~482 expected samples
```

If actual samples fall well short of expected, the cluster is saturating and arrivals are
being throttled by `MAX_CONCURRANCY`. That is a capacity result, not a tooling failure.

### Testing & Diagnostics

| Script | Purpose |
|--------|---------|
| `test_jdbc_connection.sh` | Test JDBC connectivity by compiling and running TestDriver.java |
| `test_dbr_connectivity.sh` | Diagnose DBR connectivity issues with repeated DNS/HTTPS tests |
| `test_queries_http.py` | Test SQL queries via e6data HTTP API (bypasses JMeter) |
| `fix_jmeter_jar_conflicts.sh` | Quarantine duplicate e6 JDBC drivers and zero-byte jars (`--dry-run` supported) |
| `run_premerge_checks.sh` | Run unit, Python, shell, JMX, and profile-injection checks used by CI |
| `run_smoke_suite.sh` | Run a bounded five-plan JDBC smoke suite against a real target |

**When to run `fix_jmeter_jar_conflicts.sh`:** if every query fails instantly with
`UNIMPLEMENTED: No cluster-name header or unknown cluster`, more than one
`e6-jdbc-driver-*.jar` is probably on the classpath and an old one is winning.
Load order depends on the filesystem, so this can reproduce on Linux but not macOS.
Check with `find apache-jmeter-5.6.3 -name "e6-jdbc-driver-*.jar"` — more than one line means ambiguity.

The checker also reports embedded SLF4J and Netty classes in fat JDBC drivers. Those are informational because removing individual classes from a signed/vendor artifact is unsafe; prefer a vendor-approved thin or correctly shaded driver when one becomes available.

### Housekeeping (3)

| Script | Purpose |
|--------|---------|
| `cleanup_logs.sh` | Clean up JMeter logs and temp files with configurable retention |
| `manage_invalid_runs.sh` | Move invalid runs to INVALID/ subfolder to exclude from analysis |
| `mark_best_run.sh` | Mark a run as "best" for comparison/baseline purposes |

### Shared Library (1)

| Script | Purpose |
|--------|---------|
| `jmeter_s3_utils.py` | Reusable functions for S3 path parsing, file downloading, statistics loading |

### DBR-specific (1)

| Script | Purpose |
|--------|---------|
| `get_dbr_query_history.py` | Fetch DBR SQL query history and export to CSV |

### Athena — Setup & DDL (7)

| Script | Purpose |
|--------|---------|
| `athena/setup_all_athena_tables.sh` | Create all 3 Athena tables (runs_index, run_metadata, query_results) |
| `athena/setup_athena_runs_index.sql` | DDL for jmeter_runs_index table |
| `athena/ddl/create_metadata_table.sql` | DDL for jmeter_run_metadata table |
| `athena/ddl/create_results_table_csv.sql` | DDL for jmeter_query_results table |
| `athena/recreate_athena_table.sh` | Drop and recreate runs_index table with updated schema |
| `athena/setup/setup_tables.sh` | Setup metadata + query_results tables (hybrid approach) |
| `athena/setup/repair_partitions.sh` | Run MSCK REPAIR TABLE to discover S3 partitions |

### Athena — Data Upload & Sync (5)

| Script | Purpose |
|--------|---------|
| `athena/sync_s3_to_athena.py` | Auto-discover S3 runs and upload only missing ones to Athena |
| `athena/upload_runs_index_to_athena.py` | Convert runs_index.json to partitioned JSONL and upload to S3 |
| `athena/upload_metadata.py` | Upload partitioned JSONL metadata to S3 with dry-run support |
| `athena/generate_runs_index.py` | Generate consolidated runs index from S3 test results |
| `athena/generate_metadata_index.py` | Generate metadata JSONL index from test_result.json files |

### Athena — Querying & Reports (5)

| Script | Purpose |
|--------|---------|
| `athena/WORKING_QUERIES.sql` | Reference SQL queries for JMeter analysis |
| `athena/query_athena_runs.py` | Query runs with multiple modes (engine comparison, scaling, variance, custom SQL) |
| `athena/compare_runs_athena.py` | Compare runs via Athena instead of direct S3 access |
| `athena/run_athena_reports.sh` | Execute predefined Athena queries and save as CSV |
| `athena/generate_report_queries.sh` | Generate parameterized SQL files from WORKING_QUERIES.sql |

### Athena — Baseline Management (2)

| Script | Purpose |
|--------|---------|
| `athena/manage_baseline.py` | Mark/unmark baseline runs and compare against baselines |
| `athena/verify_baseline_sync.py` | Verify S3 metadata and Athena baseline info are in sync |

### Athena — Maintenance (2)

| Script | Purpose |
|--------|---------|
| `athena/setup/compact_athena_partition.sh` | Merge and deduplicate JSONL files within a partition |
| `athena/export_all_fields.sh` | Export all 62 fields from runs_index to CSV for spreadsheets |

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
├── ddl/
│   ├── create_metadata_table.sql      # DDL for jmeter_run_metadata
│   └── create_results_table_csv.sql   # DDL for jmeter_query_results
└── setup/
    ├── compact_athena_partition.sh     # Merge/deduplicate partition files
    ├── repair_partitions.sh           # MSCK REPAIR TABLE for partitions
    └── setup_tables.sh                # Setup metadata + query_results tables
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
