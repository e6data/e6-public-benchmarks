# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This is a JMeter-based JDBC performance testing framework for benchmarking database query execution across different database engines. The framework uses a property-file-driven architecture to enable reusable, automation-friendly load testing.

## Core Architecture

### Three-File Configuration System

The framework separates concerns into three distinct configuration layers:

1. **Connection Properties** (`connection_properties/*.properties`)
   - JDBC connection settings (hostname, port, driver class, connection string)
   - Database credentials and catalog configuration
   - Driver-specific parameters for E6Data, Trino, etc.

2. **Test Properties** (`test_properties/*.properties`)
   - Load characteristics (concurrency levels, QPS, QPM)
   - Test duration (ramp-up time, hold period)
   - Query behavior (random order, recycling)
   - Report output settings (S3 upload, dashboard generation)
   - References query CSV file path

3. **Query Data Files** (`data_files/*.csv`)
   - CSV files containing SQL queries to execute
   - Each row represents one query to be executed during the test
   - Can contain single-line or multi-line queries

### JMeter Test Plans (`Test-Plans/*.jmx`)

Pre-configured JMeter test plans support different load patterns:

**JDBC Test Plans (most common):**
- **`Test-Plan-Maintain-static-concurrency.jmx`**: Maintains fixed concurrent query count (most common for concurrency testing)
- **`Test-Plan-Run-Once-static-concurrency.jmx`**: Run all queries once at fixed concurrency then complete
- **`Test-Plan-Constant-QPS-On-Arrivals.jmx`**: Fires queries at constant queries-per-second rate
- **`Test-Plan-Constant-QPM-On-Arrivals.jmx`**: Fires queries at constant queries-per-minute rate
- **`Test-Plan-Fire-QPS-with-load-profile.jmx`**: Variable QPS using load profile CSV
- **`Test-Plan-Maintain-variable-concurrency-with-load-profile.jmx`**: Variable concurrency using load profile

**HTTP Endpoint Test Plans:**
- **`Test-Plan-Run-Once-http-endpoint.jmx`**: Run all queries once against HTTP/REST API endpoint
- **`Test-Plan-Maintain-static-concurrency-http-endpoint.jmx`**: Maintain fixed concurrency against HTTP endpoint
- **`Test-Plan-Maintain-static-concurrency-http-endpoint-v2.jmx`**: Updated version with enhanced HTTP endpoint support
- **`Test-Plan-Fire-QPS-with-load-profile-http-endpoint_v2.jmx`**: Variable QPS against HTTP endpoint
- Use `utilities/test_queries_http.py` to test HTTP endpoints directly
- Use `utilities/convert_queries_for_jmeter_http.py` to format queries for HTTP test plans

### Metadata Files (`metadata_files/*.txt`)

Contain cluster-specific metadata for organizing test results:

- Engine type (e.g., e6data)
- Cluster configuration (size, cores, instance types)
- S3 storage settings for results
- Used by batch testing scripts and S3 upload functionality

### Test Config Files (`test_configs/`)

The `test_configs/` directory contains two types of files:

1. **`.env` config files** — complete test configurations for `run_test.sh` (connection + plan + queries + params)
2. **`*_template.txt` files** — template files for batch testing with `run_all_concurrency.sh`

#### Template Files

Template files use a **template system** to eliminate redundancy and enable batch testing. Each template contains 5 lines with placeholders that are substituted at runtime:

**Template Structure:**
```
{ENGINE}_{CLUSTER_SIZE}_metadata.txt
Test-Plan-Maintain-static-concurrency.jmx
concurrency_{CONCURRENCY}_test.properties
{ENGINE}_{CLUSTER}_connection.properties
E6Data_TPCDS_queries_29_1TB.csv
```

**Supported Placeholders:**
- `{ENGINE}` - Engine name (e.g., e6data)
- `{CLUSTER_SIZE}` - Normalized cluster size (xs-1x1, s-2x2, m-4x4, s-4x4, s-1x1)
- `{CLUSTER}` - Cluster identifier for connection file (default, demo-graviton, etc.)
- `{CONCURRENCY}` - Concurrency level (1, 2, 4, 8, 12, 16)
- `{BENCHMARK}` - Benchmark identifier (tpcds_29_1tb, tpcds_51_1tb)

**Template File Naming Convention:**
```
test_configs/{engine}_{cluster_size}_{benchmark}_template.txt
```

**Examples:**
- `test_configs/e6data_s-2x2_tpcds_29_1tb_template.txt`
- `test_configs/e6data_xs-1x1_tpcds_29_1tb_template.txt`

**Non-Template Files (Sequential Tests):**

For tests that don't loop through concurrency levels (e.g., run-once sequential tests), use non-template files:
- `test_configs/e6data_xs_tpcds_29_1tb_sequential.txt`

These files enable automated batch testing without needing separate input files for each concurrency level.

## Running Tests

### Prerequisites Setup

```bash
# Run setup script once to install JMeter 5.6.3, Java 17, and dependencies
./setup_jmeter.sh
```

**Critical**: Java 17 is required. The interactive script validates this before running.

### Create Connection Properties (First Time Setup)

```bash
./create_connection.sh
```

Interactive utility that creates connection properties files for JDBC (e6data, Databricks, Trino) or HTTP endpoints. Run once per cluster/engine — files are saved in `connection_properties/` for reuse.

### Interactive Mode (Recommended)

```bash
./run_jmeter_tests_interactive.sh
```

This script:
1. Lists existing connection properties files for selection (if none exist, directs to `create_connection.sh`)
2. Prompts for test plan type (concurrency, QPS, QPM, load profile, variable concurrency; JDBC or HTTP variants)
3. Offers to select existing test properties or create new ones with relevant runtime parameters
4. Prompts for query CSV data file
5. Optionally selects metadata file (for S3 upload)
6. Shows configuration summary and runs the JMeter test
7. Test properties created during the flow are saved as files for reuse in future runs

### Create Test Config

```bash
./create_test_config.sh
```

Interactive utility that creates a `.env` config file in `test_configs/`. Walks through selecting connection, test plan, query file, and parameters. Config files are reusable and can be overridden at runtime.

### Non-Interactive Mode (Recommended for Repeat Runs)

```bash
# Using a config file
./run_test.sh test_configs/my_test.env

# Override specific values for re-runs
CONCURRENT_QUERY_COUNT=8 ./run_test.sh test_configs/my_test.env

# Using env vars directly
export CONNECTION_FILE=connection_properties/e6data_default_connection.properties
export TEST_PLAN=Test-Plans/Test-Plan-Maintain-static-concurrency.jmx
export QUERY_FILE=data_files/E6Data_TPCDS_queries_29_1TB.csv
export CONCURRENT_QUERY_COUNT=4
./run_test.sh
```

Reads all configuration from a `.env` config file or env vars. No prompts. Change one variable and re-run. Sample config files in `test_configs/`.

### Verifying Test Configuration (GUI Mode)

**⚠️ IMPORTANT**: Before running load tests, verify your configuration in JMeter GUI mode:

```bash
# Open JMeter GUI with your configuration
./apache-jmeter-5.6.3/bin/jmeter \
  -t Test-Plans/Test-Plan-Maintain-static-concurrency.jmx \
  -q connection_properties/sample_connection.properties \
  -q test_properties/sample_test.properties \
  -JQUERY_PATH=data_files/sample_queries.csv
```

**In GUI mode, verify:**
- JDBC connection works (test with 1 thread first)
- Queries load from CSV correctly
- Test plan parameters are correct
- View Results Tree shows successful query execution

**Note:** GUI mode is ONLY for verification. Always use non-GUI mode (CLI) for actual load testing.

### Manual JMeter Command (Non-GUI Mode)

```bash
# Non-GUI mode for actual performance testing
./apache-jmeter-5.6.3/bin/jmeter -n \
  -t Test-Plans/Test-Plan-Maintain-static-concurrency.jmx \
  -q connection_properties/sample_connection.properties \
  -q test_properties/sample_test.properties \
  -JQUERY_PATH=data_files/sample_queries.csv \
  -l reports/results.jtl
```

**Key flags:** `-n` (non-GUI mode), `-t` (test plan), `-q` (properties file), `-l` (log file)

### Batch Testing (Automated Concurrency Sweeps)

Run all concurrency levels (1, 2, 4, 8, 12, 16) sequentially using the unified script:

```bash
# Usage: ./utilities/run_all_concurrency.sh <engine> <cluster_size> <benchmark> [cluster] [test_plan_file]

# E6Data cluster testing (uses default connection)
./utilities/run_all_concurrency.sh e6data S-2x2 tpcds_29_1tb
./utilities/run_all_concurrency.sh e6data M-4x4 tpcds_51_1tb

# With custom cluster connection
./utilities/run_all_concurrency.sh e6data S-2x2 tpcds_29_1tb demo-graviton

# With custom test plan
./utilities/run_all_concurrency.sh e6data M-4x4 tpcds_29_1tb default Test-Plan-Sequential.jmx
```

**Parameters:**
- `engine` (required): Database engine (e.g., e6data)
- `cluster_size` (required): Cluster size (e.g., S-2x2, M-4x4, XS-1x1)
- `benchmark` (required): Benchmark name (tpcds_29_1tb, tpcds_51_1tb)
- `cluster` (optional): Cluster identifier for connection properties (default: "default")
  - Connection file: `connection_properties/{engine}_{cluster}_connection.properties`
- `test_plan_file` (optional): Override test plan file (default: uses template's test plan)

This script:
- Uses template system with runtime placeholder substitution
- Automatically looks up test input templates from `test_configs/` directory
- Validates all required files exist before starting
- Runs all concurrency levels sequentially with 30-second pauses between tests
- Logs each test to `/tmp/jmeter_test_logs/` with descriptive filenames
- Arguments map directly to S3 path structure: `engine=<ARG1>/cluster_size=<ARG2>/benchmark=<ARG3>/`

## S3 Results Structure

Results are uploaded to S3 in a 5-level partitioned hierarchy:

```
s3://bucket/jmeter-results/
  engine=e6data/
    cluster_size=S-2x2/
      benchmark=tpcds_29_1tb/
        run_type=concurrency_4/
          run_id=20251101-123456/
            statistics.json
            JmeterResultFile.csv
            AggregateReport.csv
            test_result.json
```

Key points:
- `run_id` folders contain all files for a single test execution
- `latest.json` at the `run_type` level points to most recent run
- Structure enables Athena partitioning for querying results
- See `utilities/README.md` for S3 path structure details

## Analysis and Comparison Scripts

All Python scripts are in `utilities/` directory:

### Single Run Analysis

```bash
# Analyze latest run for a benchmark
python utilities/analyze_single_run_from_s3.py \
  s3://your-s3-bucket/jmeter-results/engine=e6data/cluster_size=S-2x2/benchmark=tpcds_29_1tb/

# Analyze specific run
python utilities/analyze_single_run_from_s3.py \
  s3://path/to/benchmark/ --run-id 20251101-123456
```

### Comparison Between Engines

```bash
# Compare all matching concurrency levels (RECOMMENDED - most comprehensive)
python utilities/compare_multi_concurrency_from_s3.py \
  s3://your-s3-bucket/jmeter-results/engine=e6data/cluster_size=M/benchmark=tpcds_29_1tb/ \
  s3://your-s3-bucket/jmeter-results/engine=e6data/cluster_size=S-4x4/benchmark=tpcds_29_1tb/

# Compare single concurrency level
python utilities/compare_jmeter_runs_from_s3.py \
  s3://path/to/engine1/.../run_type=concurrency_4/ \
  s3://path/to/engine2/.../run_type=concurrency_4/
```

**Understanding Results:**
- **Positive % (e.g., +50.5%)**: First engine is FASTER
- **Negative % (e.g., -35.2%)**: Second engine is FASTER
- **~0%**: Both engines perform comparably

**Output Files:** Generated in `reports/` directory:
- `{engine1}_{cluster1}_vs_{engine2}_{cluster2}_MultiConcurrency_{timestamp}.csv` - Detailed comparison data
- `{engine1}_{cluster1}_vs_{engine2}_{cluster2}_MultiConcurrency_{timestamp}_SUMMARY.md` - Human-readable summary

See `utilities/README.md` for more comparison examples and detailed documentation.

### Utility Scripts

**Test Setup & Configuration:**
- `create_connection.sh`: Interactive connection properties creator (JDBC and HTTP endpoint)
- `run_jmeter_tests_interactive.sh`: Interactive test runner (select connection, plan, properties, data file)
- `create_test_config.sh`: Interactive test config creator — saves `.env` files to `test_configs/`
- `run_test.sh`: Non-interactive runner — reads from config file (`test_configs/*.env`) or env vars
- `utilities/test_jdbc_connection.sh`: Test JDBC connectivity before running full test
- `utilities/generate_concurrency_test_configs.sh`: Auto-generate test property files for different concurrency levels
- `utilities/cleanup_logs.sh`: Clean up old test logs from `/tmp/jmeter_test_logs/`

**Query Management:**
- `utilities/convert_queries_for_json_api.py`: Convert queries for JSON API format
- `utilities/convert_queries_for_jmeter_http.py`: Format queries for HTTP test plans

**HTTP Endpoint Testing:**
- `utilities/test_queries_http.py`: Test queries against HTTP/REST API endpoints directly (bypasses JMeter)

**Load Profile Management:**
- `utilities/update_load_profile.sh`: Update load profile CSV for variable load test plans

**Analysis & Comparison:**
- `utilities/analyze_single_run_from_s3.py`: Analyze individual test runs from S3
- `utilities/analyze_concurrency_scaling_from_s3.py`: Analyze how performance scales with concurrency
- `utilities/compare_consecutive_runs_from_s3.py`: Compare two consecutive runs to detect regressions
- `utilities/compare_jmeter_runs_from_s3.py`: Compare two specific test runs
- `utilities/compare_multi_concurrency_from_s3.py`: Compare all concurrency levels between two engines (most comprehensive)

**Athena Integration:**
- `utilities/athena/upload_all_runs_to_athena.sh`: Upload all test results to Athena for querying
- `utilities/athena/upload_runs_index_to_athena.py`: Upload runs index with baseline tracking to Athena
- `utilities/athena/upload_metadata.py`: Upload cluster metadata to Athena
- `utilities/athena/run_athena_reports.sh`: Run all standard Athena reports
- `utilities/athena/generate_comprehensive_reports.sh`: Generate comprehensive analysis reports
- `utilities/athena/export_all_fields.sh`: Export all 62 fields to CSV for spreadsheet analysis
- `utilities/athena/setup_all_athena_tables.sh`: Setup all Athena tables at once
- `utilities/athena/recreate_athena_table.sh`: Recreate Athena table with updated schema

**Baseline Management (Dual-Sync System):**

The framework provides automated baseline tracking using a dual-sync approach (S3 metadata + Athena columns):

- **Best Run (`is_best`)**: Automatically identified as the run with lowest `avg_latency_sec` for each configuration
- **Baseline Run (`is_baseline`)**: Manually set reference point for comparing new runs (user-controlled)

**Key Scripts:**
- `utilities/post_test_analysis.sh`: **RECOMMENDED** - Automated post-test workflow that syncs to Athena, compares against baselines, and generates comprehensive reports
- `utilities/athena/manage_baseline.py`: Mark/unmark baselines and compare runs against baseline
- `utilities/athena/verify_baseline_sync.py`: Verify S3 and Athena baseline data are synchronized
- `utilities/athena/query_athena_runs.py`: Query Athena for runs with flexible filtering options

**Quick Usage:**
```bash
# Automated analysis (recommended)
./utilities/post_test_analysis.sh e6data S-2x2 tpcds_29_1tb george

# Manual workflow
# 1. Sync to Athena (auto-detects best run)
python3 utilities/athena/upload_runs_index_to_athena.py --from-s3 <s3_path>

# 2. Compare new run against baseline
python3 utilities/athena/manage_baseline.py compare --run-id <new_run_id> ...

# 3. Mark new baseline (if improved)
python3 utilities/athena/manage_baseline.py mark --run-id <new_run_id> --user <name> ...

# 4. Verify sync
python3 utilities/athena/verify_baseline_sync.py --engine e6data --verify-all
```

**See:** `utilities/README.md` (Athena Integration section) for complete documentation including setup, report generation, and baseline workflow.

**Data Management:**
- `utilities/manage_invalid_runs.sh`: Mark invalid test runs with metadata flag for filtering in analysis
- `utilities/mark_best_run.sh`: Mark the best run for a given run_type for quick identification (legacy - use baseline system instead)

## Key Test Properties

### Concurrency Testing

```properties
# Target number of concurrent queries to maintain
CONCURRENT_QUERY_COUNT=4

# Time to reach target concurrency (minutes)
RAMP_UP_TIME=1
RAMP_UP_STEPS=1

# Duration to hold load after ramp-up (SECONDS not minutes!)
HOLD_PERIOD=300

# Whether queries should repeat until test ends
RECYCLE_ON_EOF=false
```

### CRITICAL: HOLD_PERIOD and RECYCLE_ON_EOF Behavior

**IMPORTANT:** The test **ALWAYS runs for the full HOLD_PERIOD duration**, regardless of RECYCLE_ON_EOF setting or when queries finish.

**HOLD_PERIOD is in SECONDS** (despite misleading comments in properties files saying "minutes"):
- `HOLD_PERIOD=300` = 5 minutes (not 5 hours!)
- Test duration = `RAMP_UP_TIME` + `HOLD_PERIOD` (in seconds)

**When `RECYCLE_ON_EOF=false` (run queries once):**
- Queries from CSV are read once
- When all queries complete, threads become **idle** but remain active
- Test **waits for full HOLD_PERIOD** before stopping
- Example: 29 queries finish in 2 minutes, but HOLD_PERIOD=300 means test runs full 5 minutes

**When `RECYCLE_ON_EOF=true` (repeat queries):**
- Queries from CSV are read repeatedly in a loop
- When EOF is reached, CSV reader restarts from beginning
- Threads continuously execute queries for full HOLD_PERIOD
- Example: 29 queries repeat ~60 times over 5 minutes (HOLD_PERIOD=300)

**Common Misconception:** RECYCLE_ON_EOF does NOT override or stop HOLD_PERIOD early. The hold period is always respected.

### Other Important Notes

- `RANDOM_ORDER=true`: Queries execute in random order (reduces caching effects)

## JDBC Driver Management

JDBC drivers are stored in `jdbc_drivers/` directory:

- E6Data driver: `e6data-jdbc-<version>.jar`
- Drivers must be copied to `apache-jmeter-5.6.3/lib/` for JMeter to load

The `setup_jmeter.sh` script handles this automatically.

## Report Output

Each test execution generates timestamped reports:

```
reports/
  results_YYYYMMDD-HHMMSS.jtl          # Raw JMeter results (CSV)
  AggregateReport_YYYYMMDD-HHMMSS.csv  # Per-query statistics
  statistics_YYYYMMDD-HHMMSS.json      # JSON summary for automation
  test_result_YYYYMMDD-HHMMSS.json     # Test metadata
  dashboard_YYYYMMDD-HHMMSS/           # HTML dashboard (if enabled)
```

Set `GENERATE_DASHBOARD=false` in test properties to skip HTML generation (saves ~50-100MB per test).

## Common Development Tasks

### Creating New Test Template for Batch Testing

To enable batch testing for a new engine/cluster/benchmark combination:

1. **Create metadata file** (if not exists):
   ```bash
   cp metadata_files/e6data_s-2x2_metadata.txt metadata_files/my_engine_my-cluster_metadata.txt
   ```
   Edit cluster configuration JSON, S3 settings, and `S3_BASE_PATH`

2. **Create connection properties** (if not exists):
   ```bash
   cp connection_properties/sample_connection.properties connection_properties/my_engine_my-cluster_connection.properties
   ```
   Edit JDBC connection string, credentials, driver class

3. **Create test properties for each concurrency level** (if not exists):
   ```bash
   # Already exists: concurrency_1_test.properties through concurrency_16_test.properties
   # Only needed if using different concurrency levels
   cp test_properties/concurrency_4_test.properties test_properties/concurrency_24_test.properties
   ```

4. **Add query CSV file** (if not exists):
   ```bash
   cp data_files/sample_queries.csv data_files/My_Benchmark_queries.csv
   ```

5. **Create template file**:
   ```bash
   cat > test_configs/my_engine_my-cluster_my_benchmark_template.txt << 'EOF'
   {ENGINE}_{CLUSTER_SIZE}_metadata.txt
   Test-Plan-Maintain-static-concurrency.jmx
   concurrency_{CONCURRENCY}_test.properties
   {ENGINE}_{CLUSTER}_connection.properties
   My_Benchmark_queries.csv
   EOF
   ```

6. **Run batch tests**:
   ```bash
   ./utilities/run_all_concurrency.sh my_engine my-cluster my_benchmark
   ```

### Creating New Test Configuration (Single Run)

For single test runs:

1. Create connection (if not exists): `./create_connection.sh`
2. Add query CSV file to `data_files/`
3. Create test config: `./create_test_config.sh`
   - Select your connection file
   - Choose test plan type
   - Select query file
   - Set parameters (concurrency, QPS, hold period, etc.)
   - Saves `.env` config to `test_configs/`
4. Run test: `./run_test.sh test_configs/<your_config>.env`
   - Override params inline: `CONCURRENT_QUERY_COUNT=8 ./run_test.sh test_configs/<your_config>.env`

### Adding New Query Set

1. Place CSV file in `data_files/` directory
2. Ensure CSV has no header row or uses optional header comment format
3. For multi-line queries, use `utilities/convert_queries_for_json_api.py` to convert
4. Reference in test properties: `QUERY_PATH=data_files/my_queries.csv`

### Testing Against New Database

1. Add JDBC driver JAR to `jdbc_drivers/` and copy to `apache-jmeter-5.6.3/lib/`
2. Create connection properties file with appropriate `DRIVER_CLASS` and `CONNECTION_STRING`
3. Test connectivity: `./utilities/test_jdbc_connection.sh your_connection.properties`
4. Run test normally

## Troubleshooting

### Java Version Issues

The framework requires Java 17. If you see version errors:

```bash
export JAVA_HOME=/opt/homebrew/opt/openjdk@17  # macOS
export PATH=$JAVA_HOME/bin:$PATH
java -version  # Verify
```

### JDBC Connection Failures

1. Verify driver is in `apache-jmeter-5.6.3/lib/`
2. Check connection string format for your database
3. Use test script: `./utilities/test_jdbc_connection.sh connection.properties`
4. Check JMeter logs in `apache-jmeter-5.6.3/bin/jmeter.log`

### S3 Upload Failures

1. Ensure AWS credentials configured: `aws s3 ls s3://your-bucket/`
2. Check `S3_BASE_PATH` in metadata file
3. Verify `COPY_TO_S3=true` in test properties
4. Check logs in `/tmp/jmeter_test_logs/`
