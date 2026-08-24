# JMeter JDBC Test Framework

## Public repository and bring-your-own configuration

This is a public, reusable benchmark framework. A fresh clone contains JMX
plans, scripts, sample workload shapes and connection templates only. It does
not contain an e6data/Databricks credential, a usable connection profile, or
AWS infrastructure configuration.

Users may run the complete CLI/UI workflow or invoke a JMX plan directly with
their own JMeter property files. Runtime connection profiles, query datasets,
custom load profiles, generated reports, UI databases and local environment
files are ignored by Git. Before committing, always check `git status` and
never force-add those files. The optional EC2 runner is disabled by default and
operates only after an administrator supplies their own instance, private S3
prefix and IAM permissions outside the repository.

The repository secret-scan workflow checks complete Git history on pushes and
pull requests. Repository administrators should additionally enable GitHub
Secret Scanning and Push Protection so recognized credentials are blocked
before they enter public history.

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

# Installs Java 17, JMeter 5.6.3, thread-group/Prometheus plugins, JDBC drivers, Groovy 4.0.29,
# and the isolated Benchmark Studio Python environment.
./setup_jmeter.sh
```

The default uses the built-in local SQLite registry and does not require
Docker. To provision the supplied local PostgreSQL registry as part of setup:

```bash
./setup_jmeter.sh --with-postgres
```

Both setup modes are safe to rerun. PostgreSQL credentials are generated into
the ignored, permission-protected `.benchmark-ui.env`; they are not committed.
If the operating system's `python3` is older than 3.10, setup automatically
checks for a side-by-side `python3.13`, `python3.12`, `python3.11`, or
`python3.10`. Set `BENCHMARK_UI_PYTHON=/path/to/python3.11` to choose one
explicitly. If none exists, setup installs one. On Amazon Linux 2 it builds a
pinned, checksum-verified CPython 3.11 under
`~/.local/e6-benchmark-python-3.11`; this can take several minutes. The system
Python is never replaced.

If any dependency fails to install automatically, install it manually: Java 17+, jq 1.5+, git 2.x+.

### Step 2: Create a connection properties file

```bash
./create_connection.sh
```

Interactive prompts for JDBC URL, credentials, driver class. Supports e6data, Databricks, Trino, and HTTP endpoints.

This creates a file in `connection_properties/` — e.g., `connection_properties/my_connection.properties`.

For Databricks JDBC Driver 3, copy the short URL from the SQL warehouse
connection page and leave `USER` empty. Store the PAT only as `PASSWORD`:

```properties
CONNECTION_STRING=jdbc:databricks://workspace-host:443;HttpPath=/sql/1.0/warehouses/warehouse-id;ConnCatalog=hive_metastore;ConnSchema=my_schema
USER=
PASSWORD=<access-token>
DRIVER_CLASS=com.databricks.client.jdbc.Driver
```

Engine selection supplies the driver adapter. For Databricks Driver 3, the
runner maps the protected PAT to the driver's required `PWD` property in a
run-local JMX. No additional UI, interactive, or CLI input is required. The
runner does not modify source plans or place the token in the command line or
generated report metadata.

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
./start_ui.sh
```

Stop a UI started by `start_ui.sh` without affecting JMeter runs:

```bash
./stop_ui.sh
```

The scripts use `logs/ui.pid` by default. Set `BENCHMARK_UI_PID_FILE` on both
commands to use a different PID-file location. For a systemd deployment, use
`systemctl stop e6-benchmark-ui` instead.

`run_ui.sh` remains as a backwards-compatible alias for `start_ui.sh`.

Then open <http://127.0.0.1:8765>. The UI supports:

- creating a private local JDBC or HTTP connection properties file, or selecting
  an existing one;
- selecting the same `TEST_PLAN`, `QUERY_FILE`, `LOAD_PROFILE`, concurrency,
  rate, duration, and safety variables accepted by `run_test.sh`;
- choosing an already-local CSV, uploading a CSV from the browser, or importing
  one from S3 using the UI host's configured AWS CLI credentials;
- starting one engine or the same workload on two engines;
- running two engines sequentially for cleaner measurements (the default) or
  in parallel for a live side-by-side demonstration;
- live samples, throughput, errors, active threads, latency, and runner logs;
- opening JMeter's standard HTML dashboard after a run when
  `GENERATE_DASHBOARD` is enabled;
- cancelling only the selected UI-started process;
- comparing completed `run_summary.json` reports with query-file/test-plan
  candidate matching, run identity cards, quality warnings, rich workload/date filters,
  visual deltas, cross-engine per-query JMeter statistics, and JSON/CSV/print
  export. Candidate compatibility restriction is opt-in; failed or cancelled
  runs stay hidden unless explicitly included;
- previewing the backend-resolved planned workload before launch and comparing
  it with actual arrivals/in-flight behavior read from JMeter's result CSV;
- applying tracked or locally-created workload and metadata presets through the
  **Presets** tab. Presets populate visible Launch fields and never
  bypass the resolved-configuration preview.

The **Advanced runner settings** section exposes `RAMP_UP_TIME`,
`RAMP_UP_STEPS`, `QUERY_TIMEOUT`, and `LIMIT_RESULTSET`. The resolved preview
shows the exact non-secret values that will be passed to `run_test.sh`, and can
export or import a reusable `.env` file. Importing a configuration never imports
connection secrets; it references the local `CONNECTION_FILE`, just like CLI
configuration.

UI-created workload presets are stored as ignored
`test_properties/ui_*.properties` files; metadata presets use ignored
`metadata_files/ui_*.txt` files. Existing tracked examples remain available on
a fresh clone. Administrator-owned defaults such as authentication, report
storage, Prometheus/Grafana links, dashboard generation, and optional S3 upload
are read from the UI server environment and shown in the **System settings**
tab. They are read-only by default. An administrator can set
`BENCHMARK_UI_ALLOW_SETTINGS_WRITE=true` to edit the non-secret defaults in the
browser; changes persist to `ui/system_settings.json` (or
`BENCHMARK_UI_SETTINGS_FILE`). Protect an enabled editor with
`BENCHMARK_UI_TOKEN` and restricted network access. Database URLs, credentials,
the authentication token, bind address, and AWS credentials remain service
settings that require a restart and are never exposed by the browser.

### Optional PostgreSQL registry and S3 artifact storage

SQLite remains the default. For a local PostgreSQL registry, the setup script
installs the Python driver, generates a protected password, starts the supplied
container, and configures `start_ui.sh` automatically:

```bash
./setup_ui.sh --with-postgres
./start_ui.sh
```

The same option is available during full first-time setup:

```bash
./setup_jmeter.sh --with-postgres
```

For production, supply `BENCHMARK_UI_DATABASE_URL` and its password through the
service environment/secret manager instead of using the local Docker helper.

Migrate existing local run cards idempotently:

```bash
python3 utilities/migrate_ui_registry.py \
  --sqlite ui/benchmark_ui.db \
  --database-url "$BENCHMARK_UI_DATABASE_URL"
```

Keep raw JMeter artifacts out of PostgreSQL. Enable the existing runner upload
path with `BENCHMARK_UI_COPY_TO_S3=true` and `S3_REPORT_PATH=s3://...`; the
registry stores run state while CSV/JSON/dashboard artifacts remain local and
optionally in S3. Successful uploads create `s3_upload.json` locally and in S3.
The browser never receives the database password or AWS credentials.

PostgreSQL also maintains normalized `run_facts` and `query_results` tables for
UI search, comparisons, and trend analysis. `run_facts` contains one compact
summary per run (workload identity, engine/cluster context, percentiles,
throughput, status, and verified S3 URI); `query_results` contains JMeter's
per-label aggregate statistics. Raw JMeter samples and dashboard assets are not
inserted into PostgreSQL.

New S3 uploads are immutable and date partitioned:

```text
engine=<engine>/cluster_size=<size>/benchmark=<name>/run_type=<type>/
run_date=YYYY-MM-DD/run_id=<timestamp>-<stable-run-id>/
```

The stable run ID is shared by the UI card, PostgreSQL facts, `run_summary.json`,
and S3 prefix. This makes PostgreSQL the searchable catalog and S3 the durable
artifact store; Athena is not required for normal operation.

### Optional Prometheus and Grafana observability

Prometheus support is opt-in and does not change the normal CLI/UI execution
path. When enabled, the runner creates a run-local copy of the selected JMX,
adds the bundled upstream Prometheus Listener, and exposes live metrics for
Prometheus to scrape. Source JMX files are never modified.

```bash
PROMETHEUS_ENABLED=true \
PROMETHEUS_IP=0.0.0.0 PROMETHEUS_PORT=9270 \
PROMETHEUS_DELAY=15 \
PROMETHEUS_URL=http://localhost:9090 \
GRAFANA_URL='http://localhost:3000/d/jmeter-prom/jmeter-performance?orgId=1' \
  ./run_test.sh test_configs/my_benchmark.env
```

`PROMETHEUS_URL` and `GRAFANA_URL` are informational links recorded with the
run and displayed by the UI. JMeter does not send samples to those URLs; it
exposes `http://PROMETHEUS_IP:PROMETHEUS_PORT/metrics`, which Prometheus must
scrape. For the supplied local Docker stack, the target is
`host.docker.internal:9270`. A production Prometheus server needs network
access to the load generator, so bind to its private interface (or `0.0.0.0`)
and restrict the port to Prometheus at the firewall/security-group level.

The listener exports `jmeter_response_time`, `jmeter_success_success_total`,
`jmeter_success_failure_total`, and the plugin's standard JVM/thread metrics.
These names work with the live panels in the existing `jmeter-prom` dashboard.
Its finalized `jmeter_run_*` panels belong to
the other framework's Pushgateway reporting contract and are not duplicated
here; use this framework's JMeter dashboard and `run_summary.json` for final
results.

One process owns one metrics port. Sequential comparison runs can reuse port
9270. Parallel runs require distinct ports and matching Prometheus scrape
targets. Prometheus collection is intended for live observability; the raw JTL,
JMeter dashboard, and generated summary remain the benchmark evidence.

### Run metadata

The UI can annotate a run with cluster size, estimated cores, memory, executor
count, cores per executor, instance type, engine build, benchmark/data labels,
run mode, configuration, tags, and comments. These values are descriptive only:
they are added to `run_summary.json` and `run_report.md` but do not participate
in JMeter load generation, connection configuration, or SQL execution.

The Compare page can filter reports by engine, cluster size, and engine build.
This makes it possible to compare the same workload across differently sized
clusters while keeping the sizing context visible. CLI runs receive the same
metadata when their corresponding environment variables are set, for example:

```bash
CLUSTER_SIZE=S-2x2 ESTIMATED_CORES=60 MEMORY_GB=512 \
ENGINE_BUILD=2026.08.18 BENCHMARK_TYPE=tpcds_25_1tb \
  ./run_test.sh test_configs/my_benchmark.env
```

When the UI creates a profile, it writes the same format as
`create_connection.sh` under the git-ignored `connection_properties/` directory
with owner-only (`0600`) permissions. Connection secrets are never returned to
the browser or stored in run metadata. Existing-profile selection is available
through `CONNECTION_FILE mode`. Inputs are restricted to known test plans and
files in `connection_properties/`, `data_files/`, and `test_properties/`. Local
browser uploads and S3 imports are copied into those git-ignored input
directories before the unchanged runner starts. Result upload to S3 remains
disabled for UI runs. The UI produces normal reports under
`reports/ui-<run-id>/`.

The live workload chart is calculated from the actively growing
`JmeterResultFile.csv`; JMeter does not produce its standard HTML graphs while a
test is running. After completion, use **Per-query results → Open standard
JMeter dashboard** for the standard report. Dashboard generation is enabled by
default in the UI and can be disabled with `GENERATE_DASHBOARD` for lower disk
usage.

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

### Persistent and production operation

Localhost remains zero-configuration. The UI stores its run registry in
`ui/benchmark_ui.db` by default, so completed/interrupted run records survive a
UI restart; JMeter artifacts remain ordinary files under `reports/`.

For a fixed production URL, run the service on localhost behind authenticated
HTTPS. Remote binding is refused unless `BENCHMARK_UI_TOKEN` is set. The token
is used as the password for HTTP Basic authentication (the username can be any
value); TLS must be terminated by the reverse proxy.

Deployment templates are provided under `deploy/`:

```bash
sudo install -d -o e6benchmark -g e6benchmark /var/lib/e6-benchmark-ui
sudo install -m 600 deploy/benchmark-ui.env.example /etc/e6-benchmark-ui.env
# Edit the token and paths/server name in the three deployment templates.
sudo install deploy/e6-benchmark-ui.service /etc/systemd/system/
sudo install deploy/nginx-benchmark-ui.conf /etc/nginx/conf.d/e6-benchmark-ui.conf
sudo systemctl daemon-reload
sudo systemctl enable --now e6-benchmark-ui
sudo nginx -t
sudo systemctl reload nginx
```

Operational endpoints:

- `GET /healthz` — process liveness;
- `GET /readyz` — registry and runner readiness.

Every UI launch performs a query/configuration preflight and writes
`ui_manifest.json` with the resolved non-secret environment, query/JMX/profile
hashes, and load-generator host snapshots. Comparisons warn when workload
signatures differ. These checks improve trustworthiness but do not modify the
JMeter result files or metric calculations.

### On-demand EC2 load generator

The UI runs JMeter locally by default. To keep an expensive load generator
stopped between tests, configure `BENCHMARK_UI_RUNNER=ec2`. The UI then remains
the control plane, starts the configured EC2 instance, waits for SSM readiness,
and invokes the same unmodified `run_test.sh` on that worker. Result files are
synchronized through a private S3 control prefix so browser disconnection does
not interrupt a run.

Worker installation, least-privilege IAM examples and configuration are in
[`deploy/ec2-worker/`](deploy/ec2-worker/README.md). The important controls are:

```bash
BENCHMARK_UI_RUNNER=ec2
BENCHMARK_EC2_INSTANCE_ID=i-xxxxxxxxxxxxxxxxx
BENCHMARK_EC2_REGION=us-east-1
BENCHMARK_EC2_CONTROL_S3_URI=s3://your-private-bucket/benchmark-control
BENCHMARK_EC2_IDLE_STOP_MINUTES=20
BENCHMARK_EC2_MAX_PARALLEL=1
BENCHMARK_EC2_WORKER_ROOT=/home/ec2-user/e6-public-benchmarks/jmeter_benchmarks/jmeter-jdbc-test-framework
```

On the EC2 host, clone the repository and run `./setup_jmeter.sh --without-ui`,
followed by `sudo ./deploy/ec2-worker/install_worker.sh`, from the framework
directory. Run setup as the normal EC2 user. The worker does not host Benchmark
Studio, so Amazon Linux 2's system Python is sufficient. The worker installer
detects the checkout location; it does not require an `/opt` path.

Job bundles contain the selected connection profile temporarily. Block public
S3 access, restrict both IAM roles to the control prefix, enable bucket
encryption, and apply an S3 lifecycle expiration rule. The worker deletes the
input bundle after download and removes its local job directory after the run.
Use sequential execution unless the worker has been sized and validated for two
simultaneous load generators; contention on the worker can invalidate engine
comparisons.

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
| `PROMETHEUS_ENABLED` | Expose live JMeter metrics for Prometheus; default `false` | All plans |
| `PROMETHEUS_IP`, `PROMETHEUS_PORT` | Listener bind address and port; defaults `127.0.0.1:9270` | All plans |
| `PROMETHEUS_DELAY` | Seconds to retain the endpoint after completion; default `15` | All plans |
| `PROMETHEUS_URL`, `GRAFANA_URL` | Optional UI/report navigation links | All plans |

### Load profile CSV

The two load-profile plans control different things, so they take different CSV formats.
The format is picked from the plan automatically — set `LOAD_PROFILE` to any CSV.
Both `QUERY_FILE` and `LOAD_PROFILE` may be local paths or complete `s3://`
URIs. CLI runs download a fresh, private temporary copy for every invocation,
validate it, record the source URI and SHA-256 in run metadata, and remove the
temporary copy on exit.

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
| `setup_jmeter.sh` | Install JMeter, plugins, Groovy, drivers, and UI runtime |
| `setup_ui.sh` | Install only the UI runtime; optionally start local PostgreSQL |
| `start_ui.sh` / `stop_ui.sh` | Start or stop the optional Benchmark Studio UI |
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
├── setup_ui.sh                      # Install UI runtime + optional PostgreSQL
├── start_ui.sh / stop_ui.sh         # Start/stop Benchmark Studio
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
- **`AggregateReport.csv`** / **`SummaryReport.csv`** — listener-named sample
  exports retained for compatibility; in the current plans these contain raw
  sample rows rather than pre-aggregated tables
- **`run_report.md`** — human-readable summary, generated automatically after every run
- **`run_summary.json`** — the same metrics in machine-readable form
- **`statistics.json`** and **`dashboard/`** — JMeter's authoritative per-label
  aggregate statistics and HTML dashboard; the UI displays these fields directly

Set `GENERATE_DASHBOARD=false` to skip the HTML dashboard (~3.5 MB per run).

These can be opened in spreadsheet tools or processed with the scripts in `utilities/`.

`run_summary.json` distinguishes raw JMeter samples from query samples, records
ignored framework-control samples, and captures the requested load settings,
query/profile checksums, original/generated plan names, Java/JMeter versions,
and Git commit. It also records successful-query latency percentiles, complete
failure classification (`cancelled`, `timed_out`, and `other`), and aggregate
plus active-one-second-bucket completion rates. The UI organizes these JMeter
results into outcome, workload delivery/throughput, timing/load, and latency
sections; failure messages and raw runner inputs remain collapsible. Derived
fields are labelled as such, and the CSV, `statistics.json`, and generated
JMeter dashboard remain authoritative. This metadata is intended to make
historical runs reproducible.

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
- JMeter uses one global classpath. Setup quarantines signed fat JARs that embed
  Netty when they would conflict with the e6/Databricks shared classpath. The
  original JAR remains in `jdbc_drivers/`; use an isolated JMeter installation
  when benchmarking a driver that requires the quarantined signed bundle.
- **Start small**: Begin with 1-2 threads in a non-production environment. Monitor target database resources before scaling up.
- **HOLD_PERIOD**: The test always runs for the full duration, even if queries finish early. With `RECYCLE_ON_EOF=true`, queries repeat until time expires.

## Disclaimer

This framework can generate **extremely high load**. Never run against production without explicit approval. Users are solely responsible for obtaining permissions, setting appropriate parameters, and any resulting impact. This is an independent tool using open-source Apache JMeter — not affiliated with any database vendor. No warranty provided.
