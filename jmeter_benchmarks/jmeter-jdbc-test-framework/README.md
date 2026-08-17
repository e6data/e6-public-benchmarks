# JMeter JDBC Test Framework

Run **JMeter JDBC performance tests** against any database that supports JDBC connections.

The framework reads connection and test parameters from `.properties` files at runtime — no editing of JMeter test plans required. Queries are loaded from a CSV file, so switching databases, workloads, or test parameters is just a matter of pointing to different files.

**Runner scripts** (`run_test.sh`, `run_jmeter_tests_interactive.sh`) handle JMeter invocation for you. All test settings — connection file, test plan, query file, concurrency, duration — can be passed as environment variables using `export`. This means you can change any parameter and re-run without editing files:

```bash
export HOLD_PERIOD=600    # change duration from 300 to 600
./run_test.sh             # re-run with new value, everything else stays the same
```

Helper scripts (`create_connection.sh`, `create_test_config.sh`) interactively create the `.properties` and `.env` config files you need.

## What this framework measures

This is a **JMeter-based benchmark framework and orchestration wrapper**. JMeter supplies scheduling, threads, timers, JDBC/HTTP samplers, and raw client timings; the repository adds reusable plans, configuration precedence, load-profile injection, result packaging, failure thresholds, and comparison/reporting utilities.

It is suitable for measuring:

- client-observed query latency and throughput;
- fixed and variable concurrent query behavior;
- constant QPS/QPM and ramped arrival-rate behavior;
- queue build-up, saturation, drain time, and error behavior;
- repeatable comparisons across engines or builds.

JMeter measures the workload from the client. Its `elapsed` value includes driver/network/fetch time as well as engine work. For engine-only analysis, correlate each sample's query ID with engine execution, planning, queue, scan, spill, and cache metrics. Keep result fetching and row limits identical across engines, and separate cold-cache, warm-cache, and sustained-load runs.

## Steps to Run

### Step 1: Install JMeter and dependencies

```bash
git clone https://github.com/e6data/e6-public-benchmarks.git
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

### Step 3: Create your queries CSV file

Create `data_files/` (it is intentionally ignored because workloads may be sensitive), then add a CSV with one query per row:

```csv
query_alias,query_string
q1,"SELECT COUNT(*) FROM my_table"
q2,"SELECT col1, col2 FROM my_table WHERE col1 > 100"
```

```bash
mkdir -p data_files
cp my_queries.csv data_files/
```

### Step 4: Run a test

**Option A — One reusable config, choose the load model at runtime (recommended):**

```bash
cp test_configs/sample_benchmark.env test_configs/my_benchmark.env
# Edit CONNECTION_FILE and QUERY_FILE once in my_benchmark.env.
```

The following commands reuse that file and change only the plan plus its controlling parameters:

```bash
# Run every query once at concurrency 1
TEST_PLAN=Test-Plans/Test-Plan-Run-Once-static-concurrency.jmx \
  CONCURRENT_QUERY_COUNT=1 RECYCLE_ON_EOF=false \
  ./run_test.sh test_configs/my_benchmark.env

# Hold four queries in flight for five minutes
TEST_PLAN=Test-Plans/Test-Plan-Maintain-static-concurrency.jmx \
  CONCURRENT_QUERY_COUNT=4 HOLD_PERIOD=300 \
  ./run_test.sh test_configs/my_benchmark.env

# Submit five queries per second for five minutes
TEST_PLAN=Test-Plans/Test-Plan-Constant-QPS-On-Arrivals-JSR-Optimized.jmx \
  QPS=5 HOLD_PERIOD=300 \
  ./run_test.sh test_configs/my_benchmark.env

# Submit 60 queries per minute; this plan interprets HOLD_PERIOD as minutes
TEST_PLAN=Test-Plans/Test-Plan-Constant-QPM-On-Arrivals.jmx \
  QPM=60 HOLD_PERIOD=5 \
  ./run_test.sh test_configs/my_benchmark.env

# Vary arrivals/QPS using a 3-column CSV
TEST_PLAN=Test-Plans/Test-Plan-Fire-QPS-with-load-profile.jmx \
  LOAD_PROFILE=test_properties/load_profile.csv \
  ./run_test.sh test_configs/my_benchmark.env

# Vary concurrent queries using a 5-column CSV
TEST_PLAN=Test-Plans/Test-Plan-Maintain-variable-concurrency-with-load-profile.jmx \
  LOAD_PROFILE=test_properties/utg_load_profile.csv \
  ./run_test.sh test_configs/my_benchmark.env
```

Environment values override the config file, so no JMX editing or separate config per load level is required.

**Option B — Export variables and run:**

```bash
export CONNECTION_FILE=connection_properties/my_connection.properties
export TEST_PLAN=Test-Plans/Test-Plan-Maintain-static-concurrency.jmx
export QUERY_FILE=data_files/my_queries.csv
export CONCURRENT_QUERY_COUNT=4
export HOLD_PERIOD=300

./run_test.sh
```

Change any variable and re-run — no prompts, no file editing.

**Option C — Use a dedicated config file:**

```bash
# Copy sample and edit
cp test_configs/sample_concurrency_test.env test_configs/my_test.env
vi test_configs/my_test.env

# Run
./run_test.sh test_configs/my_test.env
```

**Option D — Fully interactive:**

```bash
./run_jmeter_tests_interactive.sh
```

Guides you through selecting connection, test plan, query file, and parameters.

## Optional local web UI

The CLI remains the primary execution interface. The optional UI calls the same
`run_test.sh` runner and reads the same `JmeterResultFile.csv` and
`run_summary.json` artifacts; it does not replace or modify any JMX plan.

Start it from the framework directory:

```bash
./run_ui.sh
```

Then open <http://127.0.0.1:8765>. The UI supports:

- creating a private local JDBC or HTTP connection properties file, or selecting
  an existing one;
- selecting the same `TEST_PLAN`, `QUERY_FILE`, `LOAD_PROFILE`, concurrency,
  rate, duration, and safety variables accepted by `run_test.sh`;
- starting one engine or the same workload on two engines in parallel;
- live samples, throughput, errors, active threads, latency, and runner logs;
- cancelling only the selected UI-started process;
- comparing any two completed `run_summary.json` reports graphically.

When the UI creates a profile, it writes the same format as
`create_connection.sh` under the git-ignored `connection_properties/` directory
with owner-only (`0600`) permissions. Connection secrets are never returned to
the browser or stored in run metadata. Existing-profile selection is available
through `CONNECTION_FILE mode`. Inputs are restricted to known test plans and
files in `connection_properties/`, `data_files/`, and `test_properties/`. S3
upload and the JMeter HTML dashboard are disabled for UI runs; the UI produces
normal reports under `reports/ui-<run-id>/`.

The server binds to localhost by default. On EC2, prefer SSH port forwarding:

```bash
ssh -L 8765:127.0.0.1:8765 user@your-ec2-host
```

Then open `http://127.0.0.1:8765` locally. Binding to a public interface has no
built-in authentication and should only be done behind authenticated HTTPS.

UI diagnostics are written to `logs/ui.log`. Each UI-started benchmark also
writes its complete runner output to `reports/ui-<run-id>/ui_runner.log`, while
JMeter errors and final metrics remain in the timestamped child directory's
`JmeterResultFile.csv`, `run_report.md`, and `run_summary.json`.

## Test Plans

### JDBC Test Plans

| Test Plan | What it does | Key parameters |
|-----------|-------------|----------------|
| `Test-Plan-Run-Once-static-concurrency.jmx` | Run all queries once at fixed concurrency, then stop | `CONCURRENT_QUERY_COUNT` |
| `Test-Plan-Maintain-static-concurrency.jmx` | Maintain fixed concurrency for the hold period | `CONCURRENT_QUERY_COUNT`, `HOLD_PERIOD` |
| `Test-Plan-Constant-QPS-On-Arrivals.jmx` | Fire queries at constant queries-per-second | `QPS`, `HOLD_PERIOD` |
| `Test-Plan-Constant-QPM-On-Arrivals.jmx` | Fire queries at constant queries-per-minute | `QPM`, `HOLD_PERIOD` |
| `Test-Plan-Fire-QPS-with-load-profile.jmx` | Variable QPS rate from load profile CSV | `load_profile.csv`, `HOLD_PERIOD` |
| `Test-Plan-Maintain-variable-concurrency-with-load-profile.jmx` | Variable concurrency from load profile CSV | `load_profile.csv`, `HOLD_PERIOD` |

### HTTP Endpoint Test Plans

| Test Plan | What it does |
|-----------|-------------|
| `Test-Plan-Run-Once-http-endpoint.jmx` | Run all queries once against HTTP/REST API |
| `Test-Plan-Maintain-static-concurrency-http-endpoint.jmx` | Maintain fixed concurrency against HTTP endpoint |
| `Test-Plan-Fire-QPS-with-load-profile-http-endpoint_v2.jmx` | Variable QPS against HTTP endpoint |

### Switching test plan, properties, or parameters

Just change the relevant `export` and re-run:

```bash
# Switch to a QPS test plan with different parameters
export TEST_PLAN=Test-Plans/Test-Plan-Constant-QPS-On-Arrivals.jmx
export QPS=10
export HOLD_PERIOD=300
./run_test.sh

# Switch connection to a different database
export CONNECTION_FILE=connection_properties/another_connection.properties
./run_test.sh

# Same test plan, just change concurrency
export CONCURRENT_QUERY_COUNT=8
./run_test.sh
```

## Key Parameters

| Parameter | Description | Used by |
|-----------|-------------|---------|
| `CONCURRENT_QUERY_COUNT` | Number of simultaneous queries | Concurrency-based plans |
| `QPS` | Queries per second | QPS-based plans |
| `QPM` | Queries per minute | QPM-based plans |
| `HOLD_PERIOD` | Test duration in seconds; the QPM arrivals plan interprets it as minutes | All plans except Run-Once |
| `RECYCLE_ON_EOF` | Repeat queries when CSV ends (`true`/`false`) | All plans |
| `RANDOM_ORDER` | Shuffle query execution order (`true`/`false`) | All plans |
| `COPY_TO_S3` | Upload results to S3 (`true`/`false`, default `false`) | All plans |
| `S3_REPORT_PATH` | Root path for runner uploads; `S3_BASE_PATH` remains a legacy metadata alias | All plans |
| `RUN_TYPE` | Optional S3 partition label; inferred from plan and concurrency/rate when omitted | All plans |
| `MAX_ERROR_PCT` | Exit nonzero when sample error percentage exceeds this value | All plans |

### Load profile CSV

The two load-profile plans control different things, so they take different CSV formats.
The format is picked from the plan automatically — set `LOAD_PROFILE` to any CSV.

**Arrival rate** — `Test-Plan-Fire-QPS-with-load-profile.jmx`, default
`test_properties/load_profile.csv`. Controls how fast queries are *submitted*:

```csv
StartValue,EndValue,Duration
1,1,5        # 1 QPS for 5s
2,2,10       # 2 QPS for 10s
1,10,5       # ramp 1 -> 10 QPS over 5s
```

**Concurrency** — `Test-Plan-Maintain-variable-concurrency-with-load-profile.jmx`, default
`test_properties/utg_load_profile.csv`. Controls how many run *at once*. Rows stack:

```csv
Threads,StartTime,StartupTime,HoldTime,ShutdownTime
10,0,30,60,10     # ramp to 10 over 30s, hold 60s, wind down over 10s
20,90,30,60,10    # +20 more from t=90 -> 30 concurrent
```

Use `StartupTime=0` and `ShutdownTime=0` for a flat step with no ramp. All times in seconds.
See `CLAUDE.md` for the full reference.

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

- `sample_benchmark.env` — one reusable config for all JDBC load models
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
│   └── connection.properties.template
├── test_properties/                 # Test parameter files
│   ├── test.properties.template
│   └── load_profile.csv
├── test_configs/                    # Ready-to-run config files
│   ├── sample_concurrency_test.env
│   └── sample_qps_test.env
├── data_files/                      # Local query CSV files (ignored; create it)
├── Test-Plans/                      # JMeter test plan files (.jmx)
├── jdbc_drivers/                    # JDBC driver JARs
├── metadata_files/                  # Cluster metadata for S3/Athena
├── utilities/                       # Analysis, comparison, and Athena scripts
└── reports/                         # Test output (generated at runtime)
```

## Test Output

Each test run generates results in the `reports/` directory:

Each run gets its own directory, `reports/<run_id>/`, containing:

- **`JmeterResultFile.csv`** — raw CSV with per-query timing (timestamp, elapsed ms, label, success)
- **`AggregateReport.csv`** / **`SummaryReport.csv`** — per-query and summary statistics
- **`run_report.md`** — human-readable summary, generated automatically after every run
- **`run_summary.json`** — the same metrics in machine-readable form
- **`statistics.json`** and **`dashboard/`** — JMeter's aggregate stats and HTML dashboard

Set `GENERATE_DASHBOARD=false` to skip the HTML dashboard (~3.5 MB per run).

These can be opened in spreadsheet tools or processed with the scripts in `utilities/`.

`run_summary.json` distinguishes raw JMeter samples from query samples, records ignored framework-control samples, and captures the requested load settings, query/profile checksums, original/generated plan names, Java/JMeter versions, and Git commit. This metadata is intended to make historical runs reproducible.

For analysis and comparison tools, see [utilities/README.md](utilities/README.md).

S3 uploads use the common partition layout `engine=.../cluster_size=.../benchmark=.../run_type=.../run_id=.../`. Set `S3_REPORT_PATH` to its root. Existing metadata that defines `S3_BASE_PATH` is supported as a deprecated alias.

## Developer checks

Run the dependency-free regression suite and static checks before changing runners, profile parsing, or reporting:

```bash
python3 -m unittest discover -s utilities/tests -v
./utilities/run_premerge_checks.sh
```

For a bounded live JDBC validation (five plans, real query load):

```bash
./utilities/run_smoke_suite.sh \
  connection_properties/my_connection.properties data_files/my_queries.csv
```

## Important Notes

- **Security**: Do not commit credentials to version control. Connection properties and data files are in `.gitignore`.
- **JDBC drivers**: Place JARs in `jdbc_drivers/`. The setup script copies them to JMeter's lib directory.
- **Start small**: Begin with 1-2 threads in a non-production environment. Monitor target database resources before scaling up.
- **HOLD_PERIOD**: The test always runs for the full duration, even if queries finish early. With `RECYCLE_ON_EOF=true`, queries repeat until time expires.

## Disclaimer

This framework can generate **extremely high load**. Never run against production without explicit approval. Users are solely responsible for obtaining permissions, setting appropriate parameters, and any resulting impact. This is an independent tool using open-source Apache JMeter — not affiliated with any database vendor. No warranty provided.
