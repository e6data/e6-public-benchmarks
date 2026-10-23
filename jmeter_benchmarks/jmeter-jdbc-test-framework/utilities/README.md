# JMeter Utilities & Analysis Tools

Utility reference for current runs and retained legacy reporting workflows.
For customer onboarding use the [main guide](../README.md); most helpers below
are internal runner components or optional diagnostics, not additional setup steps.

## Script Inventory

The inventory below is grouped by purpose. Counts are intentionally omitted because this directory evolves frequently; use `find utilities -type f` for the current file list.

### Analysis & Comparison

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
| `benchmark_cli.py` | Shared UI/CLI baseline promotion, listing, deactivation, and threshold comparison |
| `artifact_manifest.py` | Build SHA-256 evidence manifests and verify every published S3 object |
| `cleanup_reports.py` | Dry-run/quarantine old reports; protects registered baselines, active/recent runs, and unpublished evidence with `--require-s3` |
| `generator_monitor.py` | Capture and summarize portable load-generator health telemetry |
| `inject_jdbc_observer.py` | Record materialized JDBC row counts without executing another query |
| `post_test_analysis.sh` | End-to-end post-test workflow: sync to Athena, compare baseline, generate reports |

### Runner & Config

| Script | Purpose |
|--------|---------|
| `run_all_concurrency.sh` | Run all concurrency levels (1, 2, 4, 8, 12, 16) for a given engine/cluster/benchmark |
| `generate_concurrency_test_configs.sh` | Generate legacy metadata and test-input files for concurrency testing |

Current shared helpers include `wizard_input.py` (wizard validation),
`query_file_info.py` (query CSV contract), `load_profile.py` (schedule parsing),
`configure_jdbc_connection.py` (runtime connection transformation),
`install_jdbc_drivers.py` / `jdbc_engines.py` (driver installation and presets),
`repeat_query_file.py` (measured passes), and `run_benchmark_suite.py` (suite runner).
`migrate_ui_registry.py` is an explicit administrative migration, not routine setup.

### Query Conversion

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

`apply_load_profile.py` is called automatically by `run_test.sh` (also used by the interactive wizard) whenever the
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
MAX_CONCURRANCY=200      # arrivals safety cap; size for peak rate and tail latency
```

Both profile plans derive their schedule duration from the CSV; `HOLD_PERIOD` does not
control their duration. In-flight queries may finish after the schedule ends.
The concurrency plan also ignores `MAX_CONCURRANCY` — its CSV sets concurrency.

**You do not need a properties file per profile.** Environment values override the file, so one
config serves every profile:

```bash
LOAD_PROFILE=test_properties/spike.csv ./run_test.sh test_configs/my.env
```

`run_test.sh` accepts environment overrides. Also overridable this way: `HOLD_PERIOD`,
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
  'reports/<timestamp>/JmeterResultFile.csv' test_properties/my_profile.csv
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
load profile applied (arrival rate): 15 steps, 17s, peak 56/s, ~482 expected samples
```

If actual samples fall short, inspect `MAX_CONCURRANCY`, generator health, failures,
and startup timing. Shortfall alone does not prove engine saturation.

### Testing & Diagnostics

| Script | Purpose |
|--------|---------|
| `test_jdbc_connection.sh` | Test JDBC connectivity by compiling and running TestDriver.java |
| `test_queries_http.py` | Test SQL queries via e6data HTTP API (bypasses JMeter) |
| `fix_jmeter_jar_conflicts.sh` | Quarantine duplicate e6 JDBC drivers and zero-byte jars (`--dry-run` supported) |
| `run_premerge_checks.sh` | Run unit, Python, shell, JMX, and profile-injection checks used by CI |
| `run_smoke_suite.sh` | Run a bounded five-plan JDBC smoke suite against a real target |

**When to run `fix_jmeter_jar_conflicts.sh`:** if every query fails instantly with
`UNIMPLEMENTED: No cluster-name header or unknown cluster`, more than one
`e6-jdbc-driver-*.jar` is probably on the classpath and an old one is winning.
Load order depends on the filesystem, so this can reproduce on Linux but not macOS.
Check installed classpath copies with
`find apache-jmeter-5.6.3/lib -name "e6-jdbc-driver-*.jar"`.
Files under `lib_quarantine/` are not active classpath copies.

The checker also reports embedded SLF4J and Netty classes in fat JDBC drivers. Those are informational because removing individual classes from a signed/vendor artifact is unsafe; prefer a vendor-approved thin or correctly shaded driver when one becomes available.

### Housekeeping

| Script | Purpose |
|--------|---------|
| `cleanup_reports.py` | Baseline-aware report retention; dry-run by default and quarantine on `--apply` |
| `manage_invalid_runs.sh` | Move invalid runs to INVALID/ subfolder to exclude from analysis |
| `mark_best_run.sh` | Mark a run as "best" for comparison/baseline purposes |

For report cleanup, run `python3 utilities/cleanup_reports.py` from the framework
directory to preview candidates. Add `--apply` only after reviewing the output;
eligible reports are moved to `reports/.trash`, not permanently deleted. Use the
same registry configuration as the UI so registered baselines and active runs are
protected. This does not rotate standalone console logs or truncate running logs.

Use `compare_multi_concurrency_from_s3.py` for cross-engine concurrency analysis,
and `test_jdbc_connection.sh` for JDBC connection checks. Profile injection is
automatic; do not edit the source JMX to install a load schedule.

### Shared Library

| Script | Purpose |
|--------|---------|
| `jmeter_s3_utils.py` | Reusable functions for S3 path parsing, file downloading, statistics loading |

### Athena — Setup & DDL

| Script | Purpose |
|--------|---------|
| `athena/setup_all_athena_tables.sh` | Create all 3 Athena tables (runs_index, run_metadata, query_results) |
| `athena/setup_athena_runs_index.sql` | DDL for jmeter_runs_index table |
| `athena/ddl/create_metadata_table.sql` | DDL for jmeter_run_metadata table |
| `athena/ddl/create_results_table_csv.sql` | DDL for jmeter_query_results table |
| `athena/recreate_athena_table.sh` | Drop and recreate runs_index table with updated schema |
| `athena/setup/setup_tables.sh` | Setup metadata + query_results tables (hybrid approach) |
| `athena/setup/repair_partitions.sh` | Run MSCK REPAIR TABLE to discover S3 partitions |

### Athena — Data Upload & Sync

| Script | Purpose |
|--------|---------|
| `athena/sync_s3_to_athena.py` | Auto-discover S3 runs and upload only missing ones to Athena |
| `athena/upload_runs_index_to_athena.py` | Convert runs_index.json to partitioned JSONL and upload to S3 |
| `athena/upload_metadata.py` | Upload partitioned JSONL metadata to S3 with dry-run support |
| `athena/generate_runs_index.py` | Generate consolidated runs index from S3 test results |
| `athena/generate_metadata_index.py` | Generate metadata JSONL index from test_result.json files |

### Athena — Querying & Reports

| Script | Purpose |
|--------|---------|
| `athena/WORKING_QUERIES.sql` | Reference SQL queries for JMeter analysis |
| `athena/query_athena_runs.py` | Query runs with multiple modes (engine comparison, scaling, variance, custom SQL) |
| `athena/compare_runs_athena.py` | Compare runs via Athena instead of direct S3 access |
| `athena/run_athena_reports.sh` | Execute predefined Athena queries and save as CSV |
| `athena/generate_report_queries.sh` | Generate parameterized SQL files from WORKING_QUERIES.sql |

### Athena — Baseline Management

| Script | Purpose |
|--------|---------|
| `athena/manage_baseline.py` | Mark/show legacy baseline runs and compare against them |
| `athena/verify_baseline_sync.py` | Verify S3 metadata and Athena baseline info are in sync |

### Athena — Maintenance

| Script | Purpose |
|--------|---------|
| `athena/setup/compact_athena_partition.sh` | Merge and deduplicate JSONL files within a partition |
| `athena/export_all_fields.sh` | Export all 62 fields from runs_index to CSV for spreadsheets |

## S3 Path Structure

Current runner results are stored in an immutable partitioned hierarchy:

```
s3://bucket/jmeter-results/
  engine=<engine-name>/
    benchmark=<tpcds_29_1tb|etc>/
      data_size=<1tb|etc>/
        cluster_size=<XS-1x1|S-2x2|M-4x4|S-4x4|etc>/
          run_type=<concurrency_X|sequential>/
            run_date=<YYYY-MM-DD>/
              run_id=<timestamp>-<stable-run-id>/
                statistics.json
                JmeterResultFile.csv
                AggregateReport.csv
                run_summary.json
                e6_query_history.csv          # optional
                inputs/query.csv
                inputs/warmup-query.csv       # when warm-up is enabled
                inputs/load-profile.csv       # profile-driven plans
```

The `inputs/` files are snapshots for reproduction and UI download; SQL can still
be sensitive. Connection/test-property files are excluded from these snapshots.
Older utility scripts may require the legacy engine/cluster/benchmark/run-type
layout rather than this current layout; see the legacy-workflow section below.

**Discover available paths:**
```bash
aws s3 ls s3://your-s3-bucket/jmeter-results/                              # engines
aws s3 ls s3://your-s3-bucket/jmeter-results/engine=e6data/                # benchmarks
aws s3 ls s3://your-s3-bucket/jmeter-results/engine=e6data/benchmark=tpcds_29_1tb/  # data sizes
```

## Current run analysis and baselines

Start with the [main quick start](../README.md#first-benchmark-a-small-sequential-run).
Run commands below from the framework directory, not from `utilities/`.
Use the setup-provided Python environment for tooling; Python 3.11 is recommended.
AWS CLI credentials are needed only for tools that access S3/Athena.

For current reports, use `run_report.md`, `run_summary.json`, and the shared
baseline CLI. Promotion is optional; direct report-path comparisons need no registry:

```bash
./benchmark.sh compare \
  --baseline-report 'reports/<baseline>/run_summary.json' \
  --candidate-report 'reports/<candidate>/run_summary.json' \
  --warning-pct 5 --critical-pct 10
./benchmark.sh baseline list
```

Replace placeholders with real report paths. For promotion and registry selection,
see [baseline comparisons](../README.md#baselines-and-cli-comparison).

Metric sources differ: current summaries/UI prefer successful-query JMeter
`Latency`; standard JMeter `statistics.json`/HTML use elapsed response times.
The latter are generated only when dashboard generation is enabled.
Neither client metric is pure engine execution time. Compare like-for-like
metrics and read each tool's units and percentage-sign convention.

For a local sample CSV, the older `analyze_aggregate_report.py` is an explicit
diagnostic, not an automatic runner step:

```bash
python3 utilities/analyze_aggregate_report.py 'reports/<run-id>/JmeterResultFile.csv'
```

Despite its name, it reads sample rows, not a pre-aggregated JMeter GUI table.
Use the current run summary for primary latency and validity decisions.

## Legacy S3 and Athena workflows

These utilities are retained for existing reporting installations; they are
**not required for a new benchmark** and are not automatically called by
`run_test.sh`. They have not been migrated to the current report/baseline contract.

In particular, `jmeter_s3_utils.JMeterS3Path` recognizes the older
`engine/cluster_size/benchmark/run_type` ordering (or a direct concurrency
directory), not the current `engine/benchmark/data_size/cluster_size/...` layout.
Some tools also expect historical `test_result.json`, `runs_index.json`, or
timestamped statistics files. Do not assume that pointing them at a current
upload will work. Do not rename or move published evidence to satisfy a legacy
parser; use the current report-path comparison above or plan a separate migration.

### Retained tools

- `compare_jmeter_runs_from_s3.py`, `compare_multi_concurrency_from_s3.py`,
  `compare_multiple_runs_from_s3.py`, and
  `compare_consecutive_runs_from_s3.py`: historical result comparisons.
- `analyze_single_run_from_s3.py` and
  `analyze_concurrency_scaling_from_s3.py`: historical run/scaling analysis.
- `jmeter_s3_utils.py`: shared legacy path/statistics helpers. Its inferred
  cluster-core mappings are assumptions, not verified engine configuration.
- `post_test_analysis.sh`: explicit legacy sync/comparison/report orchestration.
- `athena/`: optional table setup, index upload, queries, reports and a
  **separate** baseline metadata system.

Consult each script's `--help` (Python tools) or usage text/source (shell tools)
for its required arguments. Inspect its expected schema/path and output metric
before using it. Historical scripts may infer query-label mappings; verify
matched query coverage rather than assuming SQL equivalence.

### Athena prerequisites and safety

Use AWS credentials with access to the specific S3 prefixes, Athena workgroup,
query-result location and catalog/database. Review the supplied SQL and script
configuration for your deployment before running DDL or uploads. Table creation,
recreation, partition repair and compaction are explicit administrative operations,
not part of runner setup. Recreating tables or changing published indexes can
affect existing consumers.

`athena/manage_baseline.py` uses S3/Athena baseline metadata; it does not promote
a run in the Studio/`benchmark.sh` registry. Its current commands are `mark`,
`show`, and `compare`; there is no `unmark` subcommand. For example, in an
already configured legacy installation:

```bash
python3 utilities/athena/manage_baseline.py show --engine e6data
python3 utilities/athena/manage_baseline.py compare \
  --engine e6data --cluster S-2x2 --benchmark my_benchmark \
  --run-type concurrency_4 --run-id '<run-id>'
```

`mark_best_run.sh` writes a legacy S3 `best.json` pointer. It is not a substitute
for current baseline promotion or retention protection.

### Troubleshooting analysis

- Missing `statistics.json`: check whether dashboard generation was enabled
  and inspect the actual uploaded object list.
- Invalid S3 path/no matching runs: verify the tool supports that layout and
  schema; current and historical partitions differ.
- Authentication failures: use your organization's AWS role/SSO workflow; never
  put access keys or secrets in shared examples or reports.
- Arrival shortfall: inspect the requested profile, concurrency cap, generator
  health, errors and timestamps before attributing it to the query engine.
- Baseline not listed: verify which registry or legacy baseline store the tool
  uses. These systems are not automatically synchronized.
