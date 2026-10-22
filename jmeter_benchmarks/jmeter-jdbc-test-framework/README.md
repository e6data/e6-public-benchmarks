# JMeter JDBC Test Framework

Run repeatable **JMeter JDBC performance tests** against any query engine that
supports JDBC connections.

The framework reads connection and test parameters from `.properties` files at runtime — no editing of JMeter test plans required. Queries are loaded from a CSV file, so switching databases, workloads, or test parameters is just a matter of pointing to different files.

## First benchmark: a small sequential run

Use a Linux or macOS terminal with Git installed. Setup installs/checks runner
dependencies; Java 17 and Python 3.11 are recommended. You need a reachable JDBC
endpoint and credentials. For TPC-DS, TPC-H or ClickBench, provision the dataset
and supply SQL appropriate to your engine; setup does not load benchmark data.

1. Clone and set up the runner:

   ```bash
   git clone https://github.com/e6data/e6-public-benchmarks.git
   cd e6-public-benchmarks/jmeter_benchmarks/jmeter-jdbc-test-framework
   ./setup_jmeter.sh
   ```

2. Create a connection profile and note its saved path:

   ```bash
   ./create_connection.sh
   ```

   For additional engines, install the selected driver first, for example
   `python3 utilities/install_jdbc_drivers.py athena`. See
   [engine setup](docs/jdbc-engines.md) for authentication prerequisites.

3. Create `data_files/my_queries.csv` in a text editor (create the directory
   with `mkdir -p data_files` if needed). Start with this connection smoke test:

   ```csv
   query_alias,query_string
   smoke_test,"SELECT 1"
   ```

   Replace it with your workload after the connection works. Quote SQL containing
   commas and escape embedded double quotes as `""`. Query files are not bundled
   in this framework's Git-ignored `data_files/` directory.

4. Create one reusable configuration:

   ```bash
   cp test_configs/sample_benchmark.env test_configs/my_benchmark.env
   ```

   Edit `CONNECTION_FILE` to the path saved in step 2 and set
   `QUERY_FILE=data_files/my_queries.csv`. Then run:

   ```bash
   TEST_PLAN=Test-Plans/Test-Plan-Run-Once-static-concurrency.jmx \
   CONCURRENT_QUERY_COUNT=1 RECYCLE_ON_EOF=false \
   MEASURED_ITERATIONS=1 GENERATE_DASHBOARD=true COPY_TO_S3=false \
   ./run_test.sh test_configs/my_benchmark.env
   ```

5. Use the report directory printed by the runner under `reports/`. Inspect
   `JmeterResultFile.csv` and open `dashboard/index.html` for the JMeter report.
   A successful `SELECT 1` validates connectivity, not benchmark performance.

No S3 account, monitoring service or UI is required for this first run. To test
another engine, create its connection profile and equivalent query CSV, then
reuse the same load settings. See [baseline comparisons](#baselines-and-cli-comparison).

## Choose a load model

Start with sequential, fixed QPS or an arrival-rate profile. Keep concurrency
tests for questions about a fixed number of simultaneous clients.

| Model | What you control | When to use it |
| --- | --- | --- |
| Sequential | One query at a time; finite query passes | First connection test and unloaded query timings |
| Fixed QPS | Queries submitted per second for a duration | Latency and errors at a known offered load |
| Arrival-rate profile | QPS changing over time in a CSV | Ramps, peaks and recovery |
| Fixed concurrency | Number of active query workers | Throughput at a fixed number of clients; each worker waits for its query |
| Variable concurrency | Worker counts changing over time in a CSV | Increasing or decreasing concurrent-client pressure |
| Run once concurrently / fixed QPM | Finite parallel passes / submissions per minute | Specialized cases; not needed for a first benchmark |

Concurrency is not QPS: slower queries reduce the submission rate of a fixed
worker pool. An arrival-rate test attempts to maintain the requested submissions,
so in-flight work can increase until engine or runner limits are reached.

**Runner scripts** (`run_test.sh`, `run_jmeter_tests_interactive.sh`) handle JMeter invocation for you. After configuring a run, parameters can be overridden without editing JMX files:

```bash
HOLD_PERIOD=600 ./run_test.sh test_configs/my_benchmark.env
```

Helper scripts (`create_connection.sh`, `create_test_config.sh`) interactively create the `.properties` and `.env` config files you need.

See [JDBC engine setup](docs/jdbc-engines.md) for additional engine presets,
connection templates, driver installation and authentication requirements.

## What this framework measures

This is a **JMeter-based benchmark framework and orchestration wrapper**. JMeter supplies scheduling, threads, timers, JDBC/HTTP samplers, and raw client timings; the repository adds reusable plans, configuration precedence, load-profile injection, result packaging, failure thresholds, and comparison/reporting utilities.

It is suitable for measuring:

- client-observed query latency and throughput;
- fixed and variable concurrent query behavior;
- constant QPS/QPM and ramped arrival-rate behavior;
- queue build-up, saturation, drain time, and error behavior;
- repeatable comparisons across engines or builds.

JMeter `Latency` measures request start through the first response exposed by
JDBC. `elapsed` also includes the remaining network/result fetch, JDBC decoding,
and client processing. For engine-only analysis, correlate samples with engine
execution, planning, queue, scan, spill, and cache metrics.

## Steps to Run

### Step 1: Install JMeter and dependencies

```bash
git clone https://github.com/e6data/e6-public-benchmarks.git
cd e6-public-benchmarks/jmeter_benchmarks/jmeter-jdbc-test-framework

# Installs Java 17, JMeter 5.6.3, plugins, JDBC drivers, and runner dependencies.
./setup_jmeter.sh
```

Setup is safe to rerun and does not replace the system Python.

If any dependency fails to install automatically, install it manually: Java 17+, jq 1.5+, git 2.x+.

### Step 2: Create a connection properties file

```bash
./create_connection.sh
```

Interactive prompts collect the JDBC URL, credentials, and driver class. The
generated connection profile remains local and is ignored by Git. Supply the
driver class and connection properties documented by the target JDBC provider.
The setup script installs the repository-supported dependencies and removes
superseded downloaded driver versions from JMeter's classpath.

This creates a file in `connection_properties/` — e.g., `connection_properties/my_connection.properties`.

For third-party drivers, follow the provider's JDBC documentation and keep all
passwords or access tokens only in the git-ignored connection profile. The
runner does not place protected values in generated report metadata.

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

Provide a workload you are authorized to use as a local CSV or an `s3://` URI.
S3 inputs are downloaded afresh for each run. The CLI validates the two-column
query CSV and records its source URI and resolved SHA-256.

For cross-engine comparisons, use stable logical aliases and equivalent data
and execution policies. Dialect-specific files should contain the same logical
aliases in the same order. Keep optimized or proprietary workloads outside
version control.

### Step 4: Run a test

Every bundled plan family has one canonical file under `test_properties/`:
`run_once.properties`, `fixed_concurrency.properties`,
`constant_qps.properties`, `constant_qpm.properties`,
`variable_arrivals.properties`, or `variable_concurrency.properties`.
`run_test.sh` selects the matching file automatically. You may select a local
or `s3://` file with `TEST_PROPERTIES_FILE`; the runner downloads S3 inputs
fresh for that run.

The effective precedence is JMX fallback, then connection and test `-q`
files, then explicit environment values emitted as JMeter `-J` overrides.
For example, this uses `fixed_concurrency.properties` but runs at concurrency
5 without creating another properties file:

```bash
export TEST_PLAN=Test-Plans/Test-Plan-Maintain-static-concurrency.jmx
export CONCURRENT_QUERY_COUNT=5
CONNECTION_FILE=connection_properties/my_connection.properties \
QUERY_FILE=data_files/my_queries.csv ./run_test.sh
```

The equivalent raw JMeter shape is:

```bash
./apache-jmeter-5.6.3/bin/jmeter -n \
  -t Test-Plans/Test-Plan-Maintain-static-concurrency.jmx \
  -q connection_properties/my_connection.properties \
  -q test_properties/fixed_concurrency.properties \
  -JQUERY_PATH=data_files/my_queries.csv \
  -JCONCURRENT_QUERY_COUNT=5 \
  -l reports/results.csv
```

JVM startup options such as `HEAP` and `JVM_ARGS` must remain environment
variables because Java has already started before JMeter reads `-q` files.

**Option A — One reusable config, choose the load model at runtime (recommended):**

```bash
cp test_configs/sample_benchmark.env test_configs/my_benchmark.env
# Edit CONNECTION_FILE and QUERY_FILE once in my_benchmark.env.
```

#### Three common CLI plans

The following commands reuse that file. Environment values override the config,
so no JMX editing or separate config per load level is required.

**1. Sequential — run every query once, one at a time.**

```bash
TEST_PLAN=Test-Plans/Test-Plan-Run-Once-static-concurrency.jmx \
  CONCURRENT_QUERY_COUNT=1 RECYCLE_ON_EOF=false MEASURED_ITERATIONS=1 \
  ./run_test.sh test_configs/my_benchmark.env
```

**2. Fixed QPS — target 2 query submissions/second for a 300-second hold.**

```bash
TEST_PLAN=Test-Plans/Test-Plan-Constant-QPS-On-Arrivals-JSR-Optimized.jmx \
  QPS=2 HOLD_PERIOD=300 RAMP_UP_TIME=0 RECYCLE_ON_EOF=true \
  ./run_test.sh test_configs/my_benchmark.env
```

**3. Arrival-rate profile — follow the QPS schedule in a CSV.**

```bash
TEST_PLAN=Test-Plans/Test-Plan-Fire-QPS-with-load-profile.jmx \
  LOAD_PROFILE=test_properties/load_profile.csv \
  RECYCLE_ON_EOF=true \
  ./run_test.sh test_configs/my_benchmark.env
```

Start with the bundled profile above or replace the path with your own CSV.
The CSV determines the schedule duration; `HOLD_PERIOD` does not apply. See
[load-profile formats and column meanings](#load-profile-files-path-columns-and-duration).
QPS is an offered load, not a guarantee of completed throughput.

#### Advanced CLI examples

Use these when you specifically need worker-count control, finite parallel
passes or a per-minute arrival rate. All existing plans remain available.

```bash
# Hold four query workers for five minutes
TEST_PLAN=Test-Plans/Test-Plan-Maintain-static-concurrency.jmx \
  CONCURRENT_QUERY_COUNT=4 HOLD_PERIOD=300 RECYCLE_ON_EOF=true \
  ./run_test.sh test_configs/my_benchmark.env

# Run every query once, using up to four workers
TEST_PLAN=Test-Plans/Test-Plan-Run-Once-static-concurrency.jmx \
  CONCURRENT_QUERY_COUNT=4 RECYCLE_ON_EOF=false MEASURED_ITERATIONS=1 \
  ./run_test.sh test_configs/my_benchmark.env

# Submit 60 queries per minute; HOLD_PERIOD is in minutes for this plan
TEST_PLAN=Test-Plans/Test-Plan-Constant-QPM-On-Arrivals.jmx \
  QPM=60 HOLD_PERIOD=5 RECYCLE_ON_EOF=true \
  ./run_test.sh test_configs/my_benchmark.env

# Vary concurrent queries using a 5-column CSV
TEST_PLAN=Test-Plans/Test-Plan-Maintain-variable-concurrency-with-load-profile.jmx \
  LOAD_PROFILE=test_properties/utg_load_profile.csv \
  RECYCLE_ON_EOF=true \
  ./run_test.sh test_configs/my_benchmark.env
```

**Sequential** and **Run once (concurrent)** both reuse the same run-once JMX. Sequential forces
concurrency to 1, while concurrent Run Once lets threads consume the query CSV
together. Neither uses `HOLD_PERIOD`—both stop when every query-file row has
been consumed for the configured `MEASURED_ITERATIONS` (default `1`). For
example, `MEASURED_ITERATIONS=3` produces three samples per query label in one
standard JMeter result. The JMeter Aggregate Report and per-query view then
provide count, average, median, and percentiles across those three samples.

### Load-profile files: path, columns and duration

`LOAD_PROFILE` is a schedule CSV, not the query CSV. The selected plan determines
which of the following two formats to use. Use integer values and the shown header.

For an **arrival-rate profile**, save a file such as
`test_properties/my_arrivals.csv`:

```csv
StartValue,EndValue,Duration
1,1,60
1,4,60
4,4,120
4,1,60
```

- `StartValue`: starting submission rate in queries/second.
- `EndValue`: ending submission rate; a different value creates a linear ramp.
- `Duration`: length of that row in seconds, greater than zero.

Rows run one after another. This example schedules 300 seconds (five minutes),
starting at 1 QPS, ramping to 4 QPS, holding there, then ramping down.

```bash
TEST_PLAN=Test-Plans/Test-Plan-Fire-QPS-with-load-profile.jmx \
LOAD_PROFILE=test_properties/my_arrivals.csv \
RECYCLE_ON_EOF=true ./run_test.sh test_configs/my_benchmark.env
```

For a **variable-concurrency profile**, use a separate file such as
`test_properties/my_concurrency.csv`:

```csv
Threads,StartTime,StartupTime,HoldTime,ShutdownTime
4,0,30,120,30
```

- `Threads`: workers added by this row, greater than zero; not QPS.
- `StartTime`: delay from test start, in seconds.
- `StartupTime`: seconds to ramp up this row's workers.
- `HoldTime`: seconds to hold those workers, greater than zero.
- `ShutdownTime`: seconds to ramp them down.

Rows are independent waves; overlapping rows add their workers together. The
example ramps to four workers over 30 seconds, holds for 120, then ramps down
over 30: a 180-second schedule. Select the variable-concurrency plan for this format.

**Which path do I use?** CLI paths refer to files on the runner; relative paths
are resolved from the framework directory. `LOAD_PROFILE` can also be an `s3://`
URI if the runner has permission to download it. In the optional UI, select a
runner file, use **Local CSV** to upload a file from your computer, or use
**S3 URI** to import one. A path on your laptop is not a path on a remote runner.

**What about Hold duration?** For both profile-driven plans, the CSV defines the
schedule. The separate `HOLD_PERIOD` setting does not extend or truncate it,
and the UI shows the calculated schedule duration instead. For fixed QPS and fixed concurrency it
controls the hold interval in seconds; fixed QPM uses minutes. Sequential and
run-once plans stop after their configured query passes, not a hold interval.
Actual wall-clock duration can include startup and completion of in-flight work.
Keep query recycling enabled for sustained-load tests so the input does not run out.

#### Optional excluded warm-up

Warm a suspended engine without contaminating the measured JMeter CSV,
percentiles, throughput, dashboard, or comparison result:

```bash
WARMUP_ENABLED=true \
WARMUP_QUERY_FILE=s3://my-private-bucket/workloads/warmup.csv \
WARMUP_ITERATIONS=1 \
TEST_PLAN=Test-Plans/Test-Plan-Run-Once-static-concurrency.jmx \
CONCURRENT_QUERY_COUNT=1 \
./run_test.sh test_configs/my_benchmark.env
```

The runner executes each warm-up pass in a separate JMeter process using the
unchanged run-once JMX at concurrency 1. Warm-up artifacts are written below
`REPORT_PATH/_warmup/`; the measured run starts only after every pass succeeds.
Warm-up inputs remain local or in configured object storage. Engine-specific
cache or persisted-result behavior remains the responsibility of the selected
connection and workload.

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

Guides you through selecting a connection, test plan, query file, optional metadata,
and the workload values relevant to the selected plan. The plan automatically selects
its canonical file under `test_properties/`; interactive answers override those defaults
for that run and the script delegates execution to `run_test.sh`.

## Performance Suites

Run an ordered suite through the same CLI contract used by individual tests:

```bash
./run_benchmark_suite.sh suite_manifests/example_saved_benchmarks.json \
  --continue-on-failure
```

Use `--dry-run` to validate its query files, plans, properties, and load
profiles without starting JMeter.

## Baselines and CLI comparison

A baseline is a completed, valid, zero-failure run selected as a trusted
reference. Benchmark Studio and `benchmark.sh` share the same SQLite registry
by default; set `BENCHMARK_UI_DATABASE_URL` for a shared PostgreSQL registry.
Promoting a newer run with the same engine and exact workload configuration
supersedes the previous active reference without deleting its history.

```bash
# Promote and inspect references
./benchmark.sh baseline promote --run-id <run-id> \
  --reason "Validated release reference" --promoted-by <name-or-team>
./benchmark.sh baseline list
./benchmark.sh baseline list --all

# Compare with the active reference for the same engine and configuration
./benchmark.sh compare --baseline active --run-id <candidate-run-id>

# Compare any two runs, including sequential versus a load/concurrency run
./benchmark.sh compare --baseline <baseline-run-id> --run-id <candidate-run-id> \
  --warning-pct 5 --critical-pct 10

# Retire an active reference while preserving its history
./benchmark.sh baseline deactivate --run-id <baseline-run-id>
```

Comparisons report throughput, successful-query latency, errors, configuration
differences, and threshold verdicts. Lower latency/error and higher throughput
are treated as improvements. Direct report paths require no registry:

```bash
./benchmark.sh compare \
  --baseline-report reports/<baseline>/run_summary.json \
  --candidate-report reports/<candidate>/run_summary.json
```

Use `--format json` for automation. Baseline promotion stores only governance
metadata; the original report directory or its S3 artifacts must be retained.

## Optional Benchmark Studio

The included web interface can configure and monitor the same CLI workflows.
It invokes the existing runners and reads the same JMeter artifacts; the CLI
remains fully supported for local and automated execution.

### Optional e6 Query History capture

An e6 run can export the matching workspace Query History after JMeter
finishes. The capture window is derived from the first sample start and last
sample end in `JmeterResultFile.csv`; the workspace and cluster are derived
from the selected e6 JDBC URL. It writes `e6_query_history.csv` and
`e6_query_history_capture.json` into the run report directory before the normal
S3 upload. Capture failure is reported but never changes the JMeter result.

Configure the OAuth2 machine client through environment variables, not in a
JDBC connection properties file:

```bash
export E6_QUERY_HISTORY_ENABLED=true
export E6_MACHINE_CLIENT_ID='<machine-client-id>'
export E6_MACHINE_CLIENT_SECRET='<machine-client-secret>'
export E6_QUERY_HISTORY_EMAIL='optional-query-user@example.com'
./run_test.sh test_configs/my_benchmark.env
```

`E6_QUERY_HISTORY_WAIT_SECONDS` defaults to `5` to allow history ingestion.
Deployments whose Query History is eventually consistent should increase it;
`300` seconds is a practical value when history can take several minutes to
publish completed queries.

### Optional Prometheus and Grafana observability

Prometheus support is opt-in and does not change the normal CLI execution
path. When enabled, the runner creates a run-local copy of the selected JMX,
adds the bundled upstream Prometheus Listener, and exposes live metrics for
Prometheus to scrape. Source JMX files are never modified.

The JMeter listener exists only while an enabled test is running, so the
Prometheus `jmeter` target is expected to show down between runs.

```bash
PROMETHEUS_ENABLED=true \
PROMETHEUS_IP=0.0.0.0 PROMETHEUS_PORT=9270 \
PROMETHEUS_DELAY=15 \
PROMETHEUS_URL=http://localhost:9090 \
GRAFANA_URL='http://localhost:3000/d/jbtLA0-Wk5/jmeter?orgId=1' \
  ./run_test.sh test_configs/my_benchmark.env
```

`PROMETHEUS_URL` and `GRAFANA_URL` are informational links recorded with the
run and displayed by the UI. JMeter does not send samples to those URLs; it
exposes `http://PROMETHEUS_IP:PROMETHEUS_PORT/metrics`, which Prometheus must
scrape. For the supplied local Docker stack, the target is
`host.docker.internal:9270`. A production Prometheus server needs network
access to the load generator, so bind to its private interface (or `0.0.0.0`)
and restrict the port to Prometheus at the firewall/security-group level.

To switch from the local stack to company Prometheus and Grafana later, keep
the same JMeter listener and update `PROMETHEUS_URL` and `GRAFANA_URL`. The
company Prometheus must also be configured to scrape the runner's private
address on port `9270`; changing the navigation URLs alone does not create that
scrape target. After the company scrape target is verified, the local
containers can be stopped without removing their retained data:

```bash
docker compose --env-file .benchmark-ui.env -f deploy/docker-compose.observability.yml stop
```

The listener exports the upstream dashboard-compatible `ResponseTime` summary,
`Ratio_success`, `Ratio_failure`, and `Ratio_total` counters, plus the plugin's
standard JVM/thread metrics. These names work with the live panels in the
existing `jmeter-prom` dashboard.
Its finalized `jmeter_run_*` panels belong to
the other framework's Pushgateway reporting contract and are not duplicated
here; use this framework's JMeter dashboard and `run_summary.json` for final
results.

One process owns one metrics port. Sequential comparison runs can reuse port
9270. Parallel runs require distinct ports and matching Prometheus scrape
targets. Prometheus collection is intended for live observability; the raw JTL,
JMeter dashboard, and generated summary remain the benchmark evidence.

### Run metadata

Optional descriptive metadata can be added through environment variables. It is
recorded in `run_summary.json` and `run_report.md` but does not affect JMeter
load generation or SQL execution:

```bash
CLUSTER_SIZE=S-2x2 ESTIMATED_CORES=60 MEMORY_GB=512 \
ENGINE_BUILD=2026.08.18 BENCHMARK_TYPE=tpcds_25_1tb \
  ./run_test.sh test_configs/my_benchmark.env
```

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
| `RECYCLE_ON_EOF` | Repeat queries when CSV ends (`true`/`false`); forced `false` for Run Once | Duration/profile plans |
| `RANDOM_ORDER` | Shuffle query execution order (`true`/`false`) | Plans whose JMX contains the shuffle preprocessor; not Run Once |
| `WARMUP_ENABLED` | Run excluded sequential warm-up pass(es) before measurement; default `false` | All JDBC plans |
| `WARMUP_QUERY_FILE` | Warm-up query CSV, local path or `s3://` URI | When warm-up is enabled |
| `WARMUP_ITERATIONS` | Number of separate excluded warm-up passes; default `1` | When warm-up is enabled |
| `MEASURED_ITERATIONS` | Number of query-file passes included in one JMeter result; aliases remain unchanged for standard per-label aggregation | Run Once plans |
| `COPY_TO_S3` | Upload results to S3 (`true`/`false`, default `false`) | All plans |
| `S3_REPORT_PATH` | Results root used by the existing runner uploader, for example `s3://my-bucket/benchmark-results/v1`; `S3_BASE_PATH` remains a legacy metadata alias | All plans |
| `RUN_TYPE` | Optional S3 partition label; inferred from plan and concurrency/rate when omitted | All plans |
| `MAX_ERROR_PCT` | Exit nonzero when sample error percentage exceeds this value | All plans |
| `PROMETHEUS_ENABLED` | Expose live JMeter metrics for Prometheus; default `false` | All plans |
| `PROMETHEUS_IP`, `PROMETHEUS_PORT` | Listener bind address and port; defaults `127.0.0.1:9270` | All plans |
| `PROMETHEUS_DELAY` | Seconds to retain the endpoint after completion; default `15` | All plans |
| `PROMETHEUS_URL`, `GRAFANA_URL` | Optional UI/report navigation links | All plans |
| `E6_QUERY_HISTORY_ENABLED` | Export matching e6 Query History after a measured run; default `false` | e6 JDBC runs |
| `E6_MACHINE_CLIENT_ID`, `E6_MACHINE_CLIENT_SECRET` | OAuth2 machine-client credentials used only for Query History export | e6 JDBC runs when capture is enabled |
| `E6_QUERY_HISTORY_EMAIL` | Optional query-user filter for Query History export | e6 JDBC runs when capture is enabled |
| `E6_QUERY_HISTORY_WAIT_SECONDS` | Delay before export to allow Query History ingestion; default `5` | e6 JDBC runs when capture is enabled |

### Load profile CSV

See [load-profile files](#load-profile-files-path-columns-and-duration) for
copyable examples, column meanings, units and duration rules. The format must
match the selected plan. Do not put inline comments in numeric CSV cells.
Both `QUERY_FILE` and `LOAD_PROFILE` may be local paths or complete `s3://`
URIs. CLI runs download a fresh, private temporary copy for every invocation,
validate it, record the source URI and SHA-256 in run metadata, and remove the
temporary copy on exit.

The bundled examples are `test_properties/load_profile.csv` (arrivals) and
`test_properties/utg_load_profile.csv` (concurrency).

## Configuration Reference

| Script | What it does |
|--------|-------------|
| `setup_jmeter.sh` | Install JMeter, plugins, Groovy, drivers, and UI runtime |
| `setup_ui.sh` | Install only the UI runtime; optionally start local PostgreSQL |
| `start_ui.sh` / `stop_ui.sh` | Start or stop the optional Benchmark Studio UI |
| `create_connection.sh` | Create a connection properties file (interactive) |
| `create_test_config.sh` | Create a full test config file (interactive) |
| `run_test.sh` | Run a test (config file or env vars) |
| `benchmark.sh` | Promote, list, deactivate, and compare reference baselines |
| `run_benchmark_suite.sh` | Run an ordered Performance Suite through `run_test.sh` |
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
├── setup_ui.sh                      # Install UI runtime + optional PostgreSQL
├── start_ui.sh / stop_ui.sh         # Start/stop Benchmark Studio
├── create_connection.sh             # Create connection properties (interactive)
├── create_test_config.sh            # Create test config (interactive)
├── run_test.sh                      # Run test (config file or env vars)
├── benchmark.sh                     # Baseline governance and comparison CLI
├── run_benchmark_suite.sh           # Ordered multi-benchmark runner
├── run_jmeter_tests_interactive.sh  # Run test (interactive)
├── config/
│   └── system_settings.example.json # Shared CLI/UI runner settings template
├── suite_manifests/                 # Tracked examples + ignored local suites
├── connection_properties/           # JDBC connection files
│   └── connection.properties.template
├── test_properties/                 # Test parameter files
│   ├── run_once.properties
│   ├── fixed_concurrency.properties
│   ├── constant_qps.properties
│   ├── constant_qpm.properties
│   ├── variable_arrivals.properties
│   ├── variable_concurrency.properties
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
- **`AggregateReport.csv`** / **`SummaryReport.csv`** — listener-named sample
  exports retained for compatibility; in the current plans these contain raw
  sample rows rather than pre-aggregated tables
- **`run_report.md`** — human-readable summary, generated automatically after every run
- **`run_summary.json`** — the same metrics in machine-readable form
- **`statistics.json`** and **`dashboard/`** — JMeter's authoritative per-label
  aggregate statistics and HTML dashboard
- **`e6_query_history.csv`** and **`e6_query_history_capture.json`** — optional
  e6 workspace Query History export and capture metadata
- **`s3_upload.json`** — verified immutable S3 destination when upload succeeds
- **`inputs/query.csv`**, **`inputs/warmup-query.csv`**, and
  **`inputs/load-profile.csv`** — exact non-secret workload inputs used by the
  measured run (only applicable files are present); these are included in S3
  uploads. Connection and test-property files are
  deliberately excluded because they may contain credentials.

Set `GENERATE_DASHBOARD=false` to skip the HTML dashboard (~3.5 MB per run).

These can be opened in spreadsheet tools or processed with the scripts in `utilities/`.

`run_summary.json` distinguishes raw JMeter samples from query samples, records
ignored framework-control samples, and captures the requested load settings,
query/profile checksums, original/generated plan names, Java/JMeter versions,
and Git commit. It also records successful-query latency percentiles, complete
failure classification (`cancelled`, `timed_out`, and `other`), and aggregate
plus active-one-second-bucket completion rates. The CSV, `statistics.json`, and
generated JMeter dashboard remain authoritative. This metadata is intended to
make historical runs reproducible.

Each measured run also records portable load-generator CPU, memory, swap, load,
and network telemetry in `load_generator_metrics.csv`. Sustained CPU or memory
saturation, or any swap use, marks the result invalid; detailed JVM and host
diagnostics remain available through Prometheus/Grafana. JDBC runs record the
number of rows already materialized by each sampler without issuing another
database request. `artifact_manifest.json` seals the published evidence with
file sizes and SHA-256 digests, and S3 publication verifies every uploaded
object before writing `s3_upload.json`.

For analysis and comparison tools, see [utilities/README.md](utilities/README.md).

The `run_test.sh` uploader is controlled by `COPY_TO_S3` and `S3_REPORT_PATH`.
Defaults can be stored in the gitignored `config/system_settings.json` file:

```bash
cp config/system_settings.example.json config/system_settings.json
```

Explicit CLI exports and suite-file values take precedence over this file.
Services can move it outside the checkout with
`BENCHMARK_SYSTEM_SETTINGS_FILE=/etc/e6-benchmark-studio/system_settings.json`.

The same two values may instead be supplied directly as `COPY_TO_S3` and
`S3_REPORT_PATH` environment variables.

S3 uploads use the partition layout
`engine=.../benchmark=.../data_size=.../cluster_size=.../run_type=.../run_date=.../run_id=.../`.
Set `S3_REPORT_PATH` to the versioned results root, such as
`s3://my-bucket/benchmark-results/v1`. Query CSVs, warm-up files, and load
profiles may independently be read from `s3://.../benchmark-workloads/...`;
connection profiles and credentials must remain on the runner host. Existing
metadata that defines `S3_BASE_PATH` is supported as a deprecated alias.

Old reports can be reviewed safely with a dry-run cleanup. Active baselines,
in-progress runs, recent runs, and (with `--require-s3`) unpublished runs are
protected. `--apply` quarantines candidates below `reports/.trash`; it does not
permanently delete them:

```bash
python3 utilities/cleanup_reports.py --keep-days 30 --keep-latest 10 \
  --keep-per-configuration 3 --require-s3
python3 utilities/cleanup_reports.py --keep-days 30 --keep-latest 10 \
  --keep-per-configuration 3 --require-s3 --apply
```

When Query History enrichment is enabled, compare like-for-like fields:
JMeter `Latency` normally aligns with Query History client/total time, while
Query History execution duration excludes planning, queuing, transport, and
driver response overhead. `LIMIT_RESULTSET` can also make a query appear
successful to JMeter but `CANCELLED` in engine history: JDBC exposed a valid
response and JMeter deliberately closed the result set after reaching the row
limit. Treat that as a result-consumption status difference, not automatically
as an engine execution failure, and retain both artifacts for audit.

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
- JMeter uses one global classpath. Setup quarantines signed fat JARs that embed
  conflicting dependencies. The
  original JAR remains in `jdbc_drivers/`; use an isolated JMeter installation
  when benchmarking a driver that requires the quarantined signed bundle.
- **Start small**: Begin with 1-2 threads in a non-production environment. Monitor target database resources before scaling up.
- **HOLD_PERIOD**: The test always runs for the full duration, even if queries finish early. With `RECYCLE_ON_EOF=true`, queries repeat until time expires.

## Disclaimer

This framework can generate **extremely high load**. Never run against production without explicit approval. Users are solely responsible for obtaining permissions, setting appropriate parameters, and any resulting impact. This is an independent tool using open-source Apache JMeter — not affiliated with any database vendor. No warranty provided.
