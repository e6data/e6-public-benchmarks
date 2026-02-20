# JMeter JDBC Test Framework

Framework to run **JMeter JDBC test plans** for database load and performance testing.

## 🔹 Key Features
- **Pre-configured JMeter test plans** that use `.properties` files to make test execution simple, reusable, and automation-friendly.  
  - Connection parameters are defined in a `connection_properties` file inside the `connection_properties/` folder  
  - Test parameters are defined in a `test_properties` file inside the `test_properties/` folder  
  - Queries are stored in a `.csv` file inside the `data_files/` folder  

- **Flexible query execution**:  
  Queries are read from a CSV file, making this framework flexible to run queries against a database using:  
  - Connection settings from the `connection_properties` file  
  - Test parameters from the `test_properties` file  
  - Queries from the `data_files` CSV  

- **Simple setup**:  
  You only need to:  
  1. Create a `connection_properties` file using `./create_connection.sh`  
  2. Add your queries as a `.csv` file in the `data_files/` folder  
  3. Run `./run_test.sh` or `./run_jmeter_tests_interactive.sh` for guided setup  

- **Multi-database support**:
  The JMeter JDBC test plans can run against multiple databases that support JDBC connections (e.g., **E6Data** and others) using the appropriate `.properties` file.  

- **Wrapper scripts**:  
  Includes helper scripts that can run the JMeter tests by taking user inputs interactively from the above folders through the command prompt.  

## Test Plans Available

**JDBC Test Plans:**
- **Test-Plan-Run-Once-static-concurrency.jmx** - Run all queries once at a fixed concurrency level and then complete
- **Test-Plan-Maintain-static-concurrency.jmx** - Maintain fixed load/concurrency as per concurrency till hold period in test.properties 
- **Test-Plan-Constant-QPS-On-Arrivals.jmx** - Fire queries at constant queries-per-second rate using QPS till hold period in test.properties
- **Test-Plan-Constant-QPM-On-Arrivals.jmx** - Fire queries at constant queries-per-minute rate using QPM till hold period in test.properties
- **Test-Plan-Fire-QPS-with-load-profile.jmx** - Variable QPS rate using load profile CSV file
- **Test-Plan-Fire-QPM-with-load-profile.jmx** - Variable QPM rate using load profile CSV file
- **Test-Plan-Maintain-variable-concurrency-with-load-profile.jmx** - Variable concurrency using load profile CSV file

**HTTP Endpoint Test Plans:**
- **Test-Plan-Run-Once-http-endpoint.jmx** - Run all queries once against HTTP/REST API endpoint
- **Test-Plan-Maintain-static-concurrency-http-endpoint.jmx** - Maintain fixed concurrency against HTTP endpoint
- **Test-Plan-Fire-QPS-with-load-profile-http-endpoint_v2.jmx** - Variable QPS against HTTP endpoint

## Prerequisites

#### Take checkout of this repo and run the setup_jmeter.sh script. It will install Apache Jmeter and its dependencies

```bash
cd e6-public-benchmarks/jmeter_benchmarks/jmeter-jdbc-test-framework
./setup_jmeter.sh
```
Follow the instructions.
The setup script will attempt to install the following in your system, If some of them failed to install, please install them manually
- Java: openjdk version "17.0.16" 2025-07-15 LTS
- jq: jq-1.5
- git: git version 2.47.3
- JMeter: 5.6.3

# Steps to run

## Quick Start

### 1. Create a connection properties file
```bash
./create_connection.sh
```
Interactive utility — prompts for JDBC URL, credentials, driver. Supports e6data, Databricks, Trino, HTTP endpoints.

### 2. Add your queries as a CSV file
```bash
cp <YOUR_TEST_QUERIES>.csv data_files/
```

### 3. Run a test
**Option A — Non-interactive (recommended for repeat runs):**
```bash
export CONNECTION_FILE=connection_properties/e6data_prod_connection.properties
export TEST_PLAN=Test-Plans/Test-Plan-Maintain-static-concurrency.jmx
export QUERY_FILE=data_files/my_queries.csv
export CONCURRENT_QUERY_COUNT=4
export HOLD_PERIOD=300
./run_test.sh
```
Change one variable and re-run — no prompts, no file editing.

**Option B — Using a config file:**
```bash
# Create config interactively
./create_test_config.sh

# Or copy a sample and edit
cp test_configs/sample_concurrency_test.env test_configs/my_test.env
# Edit my_test.env with your settings
./run_test.sh test_configs/my_test.env
```

**Option C — Fully interactive:**
```bash
./run_jmeter_tests_interactive.sh
```
Guides you through selecting connection, test plan, test properties (create new or pick existing), query file, and metadata.

## ⚠️ Verify Test Plan in GUI Mode First

**Before running load tests, always verify your configuration in JMeter GUI mode:**

```bash
# Open JMeter GUI with your configuration
./apache-jmeter-5.6.3/bin/jmeter -t Test-Plans/Test-Plan-Maintain-static-concurrency.jmx \
  -q connection_properties/sample_connection.properties \
  -q test_properties/sample_test.properties \
  -JQUERY_PATH=data_files/sample_jmeter_queries.csv
```

**In GUI, verify:**
- JDBC connection works (test with 1 thread first)
- Queries load from CSV correctly
- Test plan parameters are correct
- View Results Tree shows successful query execution

**Note:** GUI mode is ONLY for verification. Always use non-GUI mode (CLI) for actual load testing.

---

## Run Tests Using Non-GUI Mode

Once verified, run tests in non-GUI mode for actual performance testing:

```bash
# Non-GUI mode (recommended for all load tests)
./apache-jmeter-5.6.3/bin/jmeter -n \
  -t Test-Plans/Test-Plan-Maintain-static-concurrency.jmx \
  -q connection_properties/sample_connection.properties \
  -q test_properties/sample_test.properties \
  -JQUERY_PATH=data_files/sample_jmeter_queries.csv \
  -l reports/results.jtl
```

**Key flags:** `-n` (non-GUI mode), `-t` (test plan), `-q` (properties file), `-l` (log file)

## JMeter Output Reports

Each test run generates the following report files in the `reports/` directory:

### 1. JTL File (results.jtl)

Raw CSV file with one row per query execution containing detailed timing metrics.

**Example:**

| timeStamp | elapsed | label | responseCode | success | threadName | Latency |
|-----------|---------|-------|--------------|---------|------------|---------|
| 1730556234567 | 2847 | query_01 | 200 | true | Thread Group 1-1 | 2842 |
| 1730556235123 | 3156 | query_02 | 200 | true | Thread Group 1-2 | 3151 |
| 1730556236789 | 4523 | query_01 | 200 | true | Thread Group 1-3 | 4518 |
| 1730556237456 | 2134 | query_03 | 200 | true | Thread Group 1-4 | 2129 |

**Key columns:**
- `timeStamp` - Unix epoch time in milliseconds when request started
- `elapsed` - Total query execution time in **milliseconds** (e.g., 2847ms = 2.847 seconds)
- `label` - Query alias from the CSV query file (e.g., query_01, tpcds_29, etc.)
- `success` - true/false indicating request success/failure
- `Latency` - Time to first byte in **milliseconds**

### 2. Aggregate Report (AggregateReport_TIMESTAMP.csv)

CSV file with same format as JTL, generated by the framework with timestamp for easy identification.

Both files can be:
- Imported into JMeter GUI for visualization (File > Open)
- Analyzed with spreadsheet tools (Excel, Google Sheets)
- Processed with custom scripts for percentile calculations

# Running Tests — All Options

| Script | Mode | Best for |
|--------|------|----------|
| `create_connection.sh` | Interactive prompts | One-time connection setup |
| `create_test_config.sh` | Interactive prompts | Create test config (connection + plan + queries + params) |
| `run_test.sh` | Config file or env vars | Run tests — repeat runs, CI/CD, tweak-and-rerun |
| `run_jmeter_tests_interactive.sh` | Interactive prompts | Run tests — guided setup for first-time users |
| `utilities/run_all_concurrency.sh` | CLI args | Batch sweep across concurrency levels |

## Automated Batch Testing

### Unified Concurrency Test Runner
Run all concurrency levels (1, 2, 4, 8, 12, 16) for any engine, cluster, and benchmark:

```bash
# Usage: ./utilities/run_all_concurrency.sh <engine> <cluster_size> <benchmark>

# E6Data S-2x2 (60 cores) with TPCDS 29 queries on 1TB dataset
./utilities/run_all_concurrency.sh e6data S-2x2 tpcds_29_1tb

# E6Data M-4x4 (120 cores) with TPCDS 29 queries on 1TB dataset
./utilities/run_all_concurrency.sh e6data M-4x4 tpcds_29_1tb

# Run with different benchmark (e.g., TPCDS 51 queries on 1TB)
./utilities/run_all_concurrency.sh e6data M-4x4 tpcds_51_1tb
```

**Arguments map directly to S3 path structure:**
```
s3://your-s3-bucket/jmeter-results/engine=<ARG1>/cluster_size=<ARG2>/benchmark=<ARG3>/
```

**Features:**
- Single unified script for all engines
- Runs all concurrency levels sequentially
- Uses template system with runtime substitution for test inputs
- Validates template files before starting
- Shows comprehensive test run summary before execution
- Logs each test to `/tmp/jmeter_test_logs/` with instance_type and query_file in name
- 30-second pause between tests
- Automatic S3 upload (if enabled in metadata)
- Dashboard generation enabled by default (generates statistics.json for analysis)

### Template System for Test Inputs

The batch runner uses a **template-based system** to eliminate redundancy. Instead of maintaining separate test input files for each concurrency level (1, 2, 4, 8, 12, 16), a single template file per engine/cluster/benchmark combination is used.

**Template File Naming:**
```
test_configs/{ENGINE}_{CLUSTER_SIZE}_{BENCHMARK}_template.txt
```

**Examples:**
- `test_configs/e6data_s-2x2_tpcds_29_1tb_template.txt`
- `test_configs/e6data_m-4x4_tpcds_29_1tb_template.txt`
- `test_configs/e6data_xs-1x1_tpcds_29_1tb_template.txt`

**Template Structure:**

Each template contains 5 lines with placeholders that are substituted at runtime:

```
{ENGINE}_{CLUSTER_SIZE}_metadata.txt
Test-Plan-Maintain-static-concurrency.jmx
concurrency_{CONCURRENCY}_test.properties
{ENGINE}_{CLUSTER}_connection.properties
E6Data_TPCDS_queries_29_1TB.csv
```

**Supported Placeholders:**
- `{ENGINE}` - Engine name (e.g., e6data)
- `{CLUSTER_SIZE}` - Normalized cluster size (xs-1x1, s-2x2, m-4x4, s-4x4)
- `{CLUSTER}` - Cluster identifier used in connection properties
- `{CONCURRENCY}` - Concurrency level (1, 2, 4, 8, 12, 16)
- `{BENCHMARK}` - Benchmark identifier (tpcds_29_1tb, etc.)

**How It Works:**

When you run `./utilities/run_all_concurrency.sh e6data S-2x2 tpcds_29_1tb`:
1. Script locates template: `test_configs/e6data_s-2x2_tpcds_29_1tb_template.txt`
2. For each concurrency level (1, 2, 4, 8, 12, 16):
   - Reads template and substitutes placeholders with actual values
   - Creates temporary resolved input file
   - Passes it to the interactive script via stdin
3. Cleans up temporary files after test completion


## File Structure

```
.
├── README.md
├── CLAUDE.md                       # AI assistant context for this framework
├── setup_jmeter.sh
├── create_connection.sh             # Interactive connection properties creator
├── create_test_config.sh            # Interactive test config creator
├── run_test.sh                      # Non-interactive runner (config file or env vars)
├── run_jmeter_tests_interactive.sh  # Interactive test runner
├── apache-jmeter-5.6.3/           # JMeter installation (created by setup script)
├── connection_properties/
│   ├── sample_connection.properties
│   └── [Your connection config files]
├── data_files/
│   ├── sample_jmeter_queries.csv
│   └── [Your query CSV files]
├── jdbc_drivers/                   # JDBC driver JARs (copied to lib/ by setup script)
├── JSR_scripts/                    # JSR223 Groovy scripts for advanced test plans
├── metadata_files/
│   └── [Cluster metadata files for S3 upload and Athena integration]
├── test_properties/
│   ├── sample_test.properties
│   ├── load_profile.csv
│   └── [Your test config files]
├── test_configs/
│   ├── sample_concurrency_test.env  # Sample config for concurrency testing
│   ├── sample_qps_test.env         # Sample config for QPS testing
│   └── *_template.txt              # Template files for batch test execution
├── Test-Plans/
│   ├── Test-Plan-Run-Once-static-concurrency.jmx
│   ├── Test-Plan-Maintain-static-concurrency.jmx
│   ├── Test-Plan-Constant-QPS-On-Arrivals.jmx
│   ├── Test-Plan-Constant-QPM-On-Arrivals.jmx
│   ├── Test-Plan-Fire-QPS-with-load-profile.jmx
│   ├── Test-Plan-Run-Once-http-endpoint.jmx
│   ├── Test-Plan-Maintain-static-concurrency-http-endpoint.jmx
│   └── [Other test plans]
├── utilities/
│   ├── run_all_concurrency.sh      # Batch concurrency sweep runner
│   ├── post_test_analysis.sh       # Automated post-test workflow
│   ├── athena/                     # Athena integration (upload, query, reports, baselines)
│   ├── archive_adhoc_scripts/      # Deprecated/legacy scripts
│   └── [Analysis and comparison scripts]
└── reports/                        # Test results (generated at runtime)
```

## Configuration Files

See sample files in the repository for complete configuration options:

- **connection_properties/sample_connection.properties** - JDBC connection settings (hostname, port, database, credentials, driver class)
- **test_properties/sample_test.properties** - Test execution parameters (concurrency, duration, query settings)
- **test_properties/load_profile.csv** - Variable load pattern for ramping (optional, for load-profile-based test plans)

**Key test.properties settings:**
- `CONCURRENT_QUERY_COUNT` - Number of simultaneous queries (for concurrency-based tests)
- `QPS` / `QPM` - Queries per second/minute (for arrivals-based tests)
- `HOLD_PERIOD` - Test duration in **SECONDS** (not minutes, despite comment in properties file)
- `QUERY_PATH` - Path to your query CSV file
- `RECYCLE_ON_EOF` - Repeat queries until duration ends (true/false)
- `COPY_TO_S3` - Enable S3 upload of test results (true/false)

**CRITICAL: Understanding HOLD_PERIOD and RECYCLE_ON_EOF:**

The test **ALWAYS runs for the full HOLD_PERIOD duration**, regardless of when queries finish:

- **`RECYCLE_ON_EOF=false`** (run queries once):
  - Queries from CSV are read once
  - When all queries complete, threads become **idle** but remain active
  - Test waits for full HOLD_PERIOD before stopping
  - Example: 29 queries finish in 2 minutes, but HOLD_PERIOD=300 means test runs 5 minutes total

- **`RECYCLE_ON_EOF=true`** (repeat queries):
  - Queries from CSV are read repeatedly in a loop
  - When EOF is reached, CSV reader restarts from beginning
  - Threads continuously execute queries for full HOLD_PERIOD
  - Example: 29 queries repeat ~60 times over 5 minutes (HOLD_PERIOD=300)

**The HOLD_PERIOD is NOT overridden by RECYCLE_ON_EOF** - it always determines total test duration.

## Important Notes

### Security & Data Privacy

- **DO NOT** put sensitive credentials (usernames, passwords, tokens) in properties files or test plans that will be committed to version control
- Check the `.gitignore` file - connection properties and data files are excluded to prevent accidental credential commits
- Test queries should use synthetic or anonymized data only
- Review S3 bucket permissions before enabling result upload features
- Use environment variables or secure vaults for production credentials

### JDBC Configuration

- Refer to your target system's JDBC documentation for the correct connection string format
- Place JDBC driver JARs in the `jdbc_drivers/` directory
- The setup script will copy drivers to JMeter's lib directory automatically

### Test Data

- For TPCDS benchmark queries, generate datasets using the official TPC-DS tools: https://www.tpc.org/tpcds/
- Ensure you have appropriate licenses and permissions to use benchmark datasets
- Sample queries in this repo are for demonstration purposes only

## Testing Best Practices

⚠️ **Start Small and Scale Gradually**
- Always test in non-production environments first
- Start with low concurrency (1-2 threads) and gradually increase
- Monitor target database resources (CPU, memory, connections)

**Load Configuration Tips:**
- **Concurrency tests:** `CONCURRENT_QUERY_COUNT=4` means 4 simultaneous queries at all times
- **QPS/QPM tests:** Fire queries without waiting - Example: `QPS=10` + `HOLD_PERIOD=300` = 3,000 total queries. Start low (QPS=1-5)
- **Load profile tests:** Run `utilities/update_load_profile.sh` before execution to update test plan
- Monitor JMeter's own resource usage - it can become the bottleneck

## DISCLAIMER

**USE AT YOUR OWN RISK**

- This framework can generate **extremely high load** that may overload, crash, or damage target systems
- **NEVER** run high-load tests against production systems without explicit approval and preparation
- Improper configuration can bring down databases, consume resources, or cause data issues
- Users are **solely responsible** for:
  - Obtaining necessary permissions before load testing
  - Setting appropriate test parameters for their environment
  - Any damage, downtime, or issues caused by testing
  - Compliance with database licensing terms during testing

- This is an independent testing utility using open-source Apache JMeter
- **Not officially affiliated with or endorsed by any database vendor**
- No warranty is provided - use at your own risk
- The maintainers are **not responsible** for any system damage, data loss, or issues arising from use of this framework

### Third-Party Components

- **Apache JMeter 5.6.3** - Apache License 2.0
- JDBC drivers are subject to their respective vendor licenses
- Refer to individual component licenses for terms and conditions 

