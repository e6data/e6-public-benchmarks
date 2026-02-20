# JMeter JDBC Test Framework

Run **JMeter JDBC performance tests** against any database that supports JDBC connections.

Queries are read from a CSV file, test parameters from a `.properties` file — no editing of JMeter test plans required.

## Steps to Run

### Step 1: Install JMeter and dependencies

```bash
git clone <repo-url>
cd e6-public-benchmarks/jmeter_benchmarks/jmeter-jdbc-test-framework

# Installs Java 17, JMeter 5.6.3, plugins, and Groovy 4.0.29
./setup_jmeter.sh
```

If any dependency fails to install automatically, install it manually: Java 17+, jq 1.5+, git 2.x+.

### Step 2: Create a connection properties file

```bash
./create_connection.sh
```

Interactive prompts for JDBC URL, credentials, driver class. Supports e6data, Databricks, Trino, and HTTP endpoints.

This creates a file in `connection_properties/` — e.g., `connection_properties/my_connection.properties`.

### Step 3: Add your queries

Place a CSV file in `data_files/`:

```bash
cp my_queries.csv data_files/
```

CSV format — one query per row with an alias:

```csv
query_alias,query_string
q1,"SELECT COUNT(*) FROM my_table"
q2,"SELECT col1, col2 FROM my_table WHERE col1 > 100"
```

### Step 4: Run a test

**Option A — Export variables and run (recommended):**

```bash
export CONNECTION_FILE=connection_properties/e6data_prod_connection.properties
export TEST_PLAN=Test-Plans/Test-Plan-Maintain-static-concurrency.jmx
export QUERY_FILE=data_files/my_queries.csv
export CONCURRENT_QUERY_COUNT=4
export HOLD_PERIOD=300

./run_test.sh
```

Change one variable and re-run — no prompts, no file editing.

**Option B — Use a config file:**

```bash
# Copy sample and edit
cp test_configs/sample_concurrency_test.env test_configs/my_test.env
vi test_configs/my_test.env

# Run
./run_test.sh test_configs/my_test.env
```

**Option C — Fully interactive:**

```bash
./run_jmeter_tests_interactive.sh
```

Guides you through selecting connection, test plan, query file, and parameters.

## Test Plans

### JDBC Test Plans

| Test Plan | What it does | Key parameters |
|-----------|-------------|----------------|
| `Test-Plan-Run-Once-static-concurrency.jmx` | Run all queries once at fixed concurrency, then stop | `CONCURRENT_QUERY_COUNT` |
| `Test-Plan-Maintain-static-concurrency.jmx` | Maintain fixed concurrency for the hold period | `CONCURRENT_QUERY_COUNT`, `HOLD_PERIOD` |
| `Test-Plan-Constant-QPS-On-Arrivals.jmx` | Fire queries at constant queries-per-second | `QPS`, `HOLD_PERIOD` |
| `Test-Plan-Constant-QPM-On-Arrivals.jmx` | Fire queries at constant queries-per-minute | `QPM`, `HOLD_PERIOD` |
| `Test-Plan-Fire-QPS-with-load-profile.jmx` | Variable QPS rate from load profile CSV | `load_profile.csv`, `HOLD_PERIOD` |
| `Test-Plan-Fire-QPM-with-load-profile.jmx` | Variable QPM rate from load profile CSV | `load_profile.csv`, `HOLD_PERIOD` |
| `Test-Plan-Maintain-variable-concurrency-with-load-profile.jmx` | Variable concurrency from load profile CSV | `load_profile.csv`, `HOLD_PERIOD` |

### HTTP Endpoint Test Plans

| Test Plan | What it does |
|-----------|-------------|
| `Test-Plan-Run-Once-http-endpoint.jmx` | Run all queries once against HTTP/REST API |
| `Test-Plan-Maintain-static-concurrency-http-endpoint.jmx` | Maintain fixed concurrency against HTTP endpoint |
| `Test-Plan-Fire-QPS-with-load-profile-http-endpoint_v2.jmx` | Variable QPS against HTTP endpoint |

### Switching test plans

Just change the `TEST_PLAN` export:

```bash
export TEST_PLAN=Test-Plans/Test-Plan-Constant-QPS-On-Arrivals.jmx
export QPS=10
export HOLD_PERIOD=300
./run_test.sh
```

## Key Parameters

| Parameter | Description | Used by |
|-----------|-------------|---------|
| `CONCURRENT_QUERY_COUNT` | Number of simultaneous queries | Concurrency-based plans |
| `QPS` | Queries per second | QPS-based plans |
| `QPM` | Queries per minute | QPM-based plans |
| `HOLD_PERIOD` | Test duration in seconds | All plans except Run-Once |
| `RECYCLE_ON_EOF` | Repeat queries when CSV ends (`true`/`false`) | All plans |
| `RANDOM_ORDER` | Shuffle query execution order (`true`/`false`) | All plans |
| `COPY_TO_S3` | Upload results to S3 (`true`/`false`, default `false`) | All plans |

### Load profile CSV

For load-profile-based test plans, edit `test_properties/load_profile.csv`:

```csv
StartValue,EndValue,Duration
1,1,5
2,2,10
4,4,10
2,2,5
```

Each row: hold `StartValue`-to-`EndValue` concurrency/QPS/QPM for `Duration` seconds.

## Configuration Reference

| Script | What it does |
|--------|-------------|
| `setup_jmeter.sh` | Install JMeter, plugins, Groovy, drivers |
| `create_connection.sh` | Create a connection properties file (interactive) |
| `create_test_config.sh` | Create a full test config file (interactive) |
| `run_test.sh` | Run a test (config file or env vars) |
| `run_jmeter_tests_interactive.sh` | Run a test (interactive prompts) |

### Sample configs

Ready-to-copy templates in `test_configs/`:

- `sample_concurrency_test.env` — static concurrency test
- `sample_qps_test.env` — constant QPS test

```bash
cp test_configs/sample_concurrency_test.env test_configs/my_test.env
```

## File Structure

```
.
├── setup_jmeter.sh                  # Install JMeter + dependencies
├── create_connection.sh             # Create connection properties (interactive)
├── create_test_config.sh            # Create test config (interactive)
├── run_test.sh                      # Run test (config file or env vars)
├── run_jmeter_tests_interactive.sh  # Run test (interactive)
├── connection_properties/           # JDBC connection files
│   └── sample_connection.properties
├── test_properties/                 # Test parameter files
│   ├── sample_test.properties
│   └── load_profile.csv
├── test_configs/                    # Ready-to-run config files
│   ├── sample_concurrency_test.env
│   └── sample_qps_test.env
├── data_files/                      # Query CSV files
│   └── sample_jmeter_queries.csv
├── Test-Plans/                      # JMeter test plan files (.jmx)
├── jdbc_drivers/                    # JDBC driver JARs
├── metadata_files/                  # Cluster metadata for S3/Athena
├── utilities/                       # Analysis, comparison, and Athena scripts
└── reports/                         # Test output (generated at runtime)
```

## Test Output

Each test run generates results in the `reports/` directory:

- **JTL file** (`results.jtl`) — raw CSV with per-query timing (timestamp, elapsed ms, label, success)
- **Aggregate report** (`AggregateReport_TIMESTAMP.csv`) — same data with timestamped filename
- **Dashboard** (`statistics.json`) — summary statistics when dashboard generation is enabled

These can be opened in spreadsheet tools or processed with the scripts in `utilities/`.

For analysis and comparison tools, see [utilities/README.md](utilities/README.md).

## Important Notes

- **Security**: Do not commit credentials to version control. Connection properties and data files are in `.gitignore`.
- **JDBC drivers**: Place JARs in `jdbc_drivers/`. The setup script copies them to JMeter's lib directory.
- **Start small**: Begin with 1-2 threads in a non-production environment. Monitor target database resources before scaling up.
- **HOLD_PERIOD**: The test always runs for the full duration, even if queries finish early. With `RECYCLE_ON_EOF=true`, queries repeat until time expires.

## Disclaimer

This framework can generate **extremely high load**. Never run against production without explicit approval. Users are solely responsible for obtaining permissions, setting appropriate parameters, and any resulting impact. This is an independent tool using open-source Apache JMeter — not affiliated with any database vendor. No warranty provided.
