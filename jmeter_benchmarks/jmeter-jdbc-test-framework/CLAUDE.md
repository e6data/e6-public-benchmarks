# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This is a JMeter-based JDBC performance testing framework for comparing database query execution across different database engines (primarily E6Data and DBR). The framework uses a property-file-driven architecture to enable reusable, automation-friendly load testing.

## Core Architecture

### Three-File Configuration System

The framework separates concerns into three distinct configuration layers:

1. **Connection Properties** (`connection_properties/*.properties`)
   - JDBC connection settings (hostname, port, driver class, connection string)
   - Database credentials and catalog configuration
   - Driver-specific parameters for E6Data, DBR, Trino, etc.

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
- For testing REST API query endpoints instead of JDBC connections
- Use `utilities/test_queries_http.py` to test HTTP endpoints directly
- Use `utilities/convert_queries_for_jmeter_http.py` to format queries for HTTP test plans

### Metadata Files (`metadata_files/*.txt`)

Contain cluster-specific metadata for organizing test results:

- Engine type (e6data, dbr)
- Cluster configuration (size, cores, instance types)
- S3 storage settings for results
- Used by batch testing scripts and S3 upload functionality

### Test Input Files (`test_inputs/*.txt`)

Pre-configured test input files for automated batch testing. Each file contains 5 lines specifying all inputs needed to run a test:

```
<metadata_file>
<test_plan>
<test_properties>
<connection_properties>
<query_csv_file>
```

**Example:** `test_inputs/e6data_m-4x4_tpcds_29_1tb_concurrency_4.txt`
```
e6data_m-4x4_metadata.txt
Test-Plan-Maintain-static-concurrency.jmx
concurrency_4_test.properties
demo-graviton_connection.properties
E6Data_TPCDS_queries_29_1TB.csv
```

These files enable the `run_all_concurrency.sh` script to automatically run tests without interactive prompts. File naming convention: `{engine}_{cluster_size}_{benchmark}_concurrency_{level}.txt`

## Running Tests

### Prerequisites Setup

```bash
# Run setup script once to install JMeter 5.6.3, Java 17, and dependencies
./setup_jmeter.sh
```

**Critical**: Java 17 is required. The interactive script validates this before running.

### Interactive Mode (Recommended)

```bash
./run_jmeter_tests_interactive.sh
```

This script:
1. Prompts for metadata file selection (determines engine/cluster config)
2. Prompts for test plan selection
3. Prompts for test properties file
4. Prompts for connection properties file
5. Prompts for query CSV file
6. Generates timestamped reports in `reports/` directory
7. Optionally uploads results to S3 (if `COPY_TO_S3=true` in test properties)

### Manual JMeter Command

```bash
./apache-jmeter-5.6.3/bin/jmeter -n \
  -t Test-Plans/Test-Plan-Maintain-static-concurrency.jmx \
  -q connection_properties/sample_connection.properties \
  -q test_properties/sample_test.properties \
  -JQUERY_PATH=data_files/sample_queries.csv \
  -l reports/results.jtl
```

### Batch Testing (Automated Concurrency Sweeps)

Run all concurrency levels (1, 2, 4, 8, 12, 16) sequentially using the unified script:

```bash
# Usage: ./utilities/run_all_concurrency.sh <engine> <cluster_size> <benchmark>

# E6Data cluster testing
./utilities/run_all_concurrency.sh e6data S-2x2 tpcds_29_1tb
./utilities/run_all_concurrency.sh e6data M-4x4 tpcds_51_1tb

# DBR cluster testing
./utilities/run_all_concurrency.sh dbr S-2x2 tpcds_29_1tb
./utilities/run_all_concurrency.sh dbr S-4x4 tpcds_51_1tb
```

This script:
- Automatically looks up test input files from `test_inputs/` directory
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
- See `S3_STRUCTURE_UPDATE.md` for migration details

## Analysis and Comparison Scripts

All Python scripts are in `utilities/` directory:

### Single Run Analysis

```bash
# Analyze latest run for a benchmark
python utilities/analyze_single_run_from_s3.py \
  s3://e6-jmeter/jmeter-results/engine=e6data/cluster_size=S-2x2/benchmark=tpcds_29_1tb/

# Analyze specific run
python utilities/analyze_single_run_from_s3.py \
  s3://path/to/benchmark/ --run-id 20251101-123456
```

### Comparison Between Engines

```bash
# Compare all matching concurrency levels (recommended)
python utilities/compare_multi_concurrency.py \
  s3://e6-jmeter/jmeter-results/engine=e6data/cluster_size=M/benchmark=tpcds_29_1tb/ \
  s3://e6-jmeter/jmeter-results/engine=dbr/cluster_size=S-4x4/benchmark=tpcds_29_1tb/

# Compare single concurrency level
python utilities/compare_jmeter_runs.py \
  s3://path/to/engine1/.../run_type=concurrency_4/ \
  s3://path/to/engine2/.../run_type=concurrency_4/
```

See `utilities/QUICK_REFERENCE.md` for more comparison examples and `utilities/COMPARISON_TOOL_README.md` for detailed documentation.

### Utility Scripts

**Test Setup & Configuration:**
- `utilities/test_jdbc_connection.sh`: Test JDBC connectivity before running full test
- `utilities/generate_concurrency_test_configs.sh`: Auto-generate test property files for different concurrency levels
- `utilities/cleanup_logs.sh`: Clean up old test logs from `/tmp/jmeter_test_logs/`

**Query Management:**
- `utilities/convert_multiline_csv.sh`: Convert multi-line SQL queries to single-line for JMeter compatibility
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
- `utilities/compare_jmeter_runs.py`: Compare two specific test runs
- `utilities/compare_multi_concurrency.py`: Compare all concurrency levels between two engines (most comprehensive)

**DBR-Specific:**
- `utilities/get_dbr_query_history.py`: Retrieve query execution history from Databricks
- `utilities/test_dbr_connectivity.sh`: Test Databricks connection before running tests

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
- DBR driver: `DBRJDBC42-<version>.jar`
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

### Creating New Test Configuration

1. Copy metadata template: `cp metadata_files/e6data_s-2x2_metadata.txt metadata_files/my_config.txt`
2. Edit cluster configuration JSON and S3 settings
3. Create/modify test properties: `cp test_properties/sample_test.properties test_properties/my_test.properties`
4. Edit concurrency level, hold period, query file path
5. Run via interactive script

### Adding New Query Set

1. Place CSV file in `data_files/` directory
2. Ensure CSV has no header row or uses optional header comment format
3. For multi-line queries, use `utilities/convert_multiline_csv.sh` to convert
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
