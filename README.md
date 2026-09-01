# e6data Public Benchmarks

This repository contains three independent toolsets for running and comparing analytical-engine benchmarks. Use it in a lab or other non-production environment: the runners can generate substantial load, and the utilities have not been hardened as production services.

## Choose a tool

| Tool | Best for | Engines / interfaces | Start here |
|---|---|---|---|
| JMeter JDBC Test Framework | Repeatable concurrency, QPS/QPM, load-profile, and regression tests | JDBC and HTTP endpoints; connection templates cover e6data, Databricks, Snowflake, Trino, and others | [JMeter guide](jmeter_benchmarks/jmeter-jdbc-test-framework/README.md) |
| Python benchmarks | Small sequential or batched-concurrency runs from a query CSV | e6data, Trino, and Amazon Athena | [Python guide](python_benchmarks/README.md) |
| Benchmark POV Tool | Browser-based e6data-versus-Databricks comparisons | Docker Compose deployment of prebuilt UI, API, and MySQL images | [POV guide](pov/README.md) |

The toolsets do not share a common runtime or configuration. Enter the selected tool's directory and follow its README.

## JMeter quick start

The JMeter framework is the recommended entry point for repeatable query-engine load tests. After cloning the repository:

```bash
cd jmeter_benchmarks/jmeter-jdbc-test-framework
./setup_jmeter.sh
./create_connection.sh
mkdir -p data_files
cp /path/to/my_queries.csv data_files/my_queries.csv
cp test_configs/sample_benchmark.env test_configs/my_benchmark.env
```

`setup_jmeter.sh` installs JMeter, required plugins and JDBC drivers, plus the
isolated Benchmark Studio Python environment. It uses SQLite by default. For a
local PostgreSQL registry, use `./setup_jmeter.sh --with-postgres` instead.
For a self-contained runner with PostgreSQL plus local Prometheus and Grafana,
use `./setup_jmeter.sh --with-postgres --with-observability`. These services are
optional; CLI execution remains available without them.

Edit only `CONNECTION_FILE` and `QUERY_FILE` in `my_benchmark.env`, then choose a load model with command-line overrides:

```bash
# Fixed concurrency
CONCURRENT_QUERY_COUNT=4 HOLD_PERIOD=300 \
  ./run_test.sh test_configs/my_benchmark.env

# Constant arrival rate
TEST_PLAN=Test-Plans/Test-Plan-Constant-QPS-On-Arrivals-JSR-Optimized.jmx \
  QPS=5 HOLD_PERIOD=300 ./run_test.sh test_configs/my_benchmark.env

# Variable arrival rate from CSV
TEST_PLAN=Test-Plans/Test-Plan-Fire-QPS-with-load-profile.jmx \
  LOAD_PROFILE=test_properties/load_profile.csv \
  ./run_test.sh test_configs/my_benchmark.env

# Variable concurrency from CSV
TEST_PLAN=Test-Plans/Test-Plan-Maintain-variable-concurrency-with-load-profile.jmx \
  LOAD_PROFILE=test_properties/utg_load_profile.csv \
  ./run_test.sh test_configs/my_benchmark.env
```

See the [complete JMeter guide](jmeter_benchmarks/jmeter-jdbc-test-framework/README.md) for run-once, QPM, HTTP, custom profiles, reports, S3/Athena analysis, and metric definitions.

To apply the same S3, observability, retention, and optional e6 Query History
defaults to CLI, interactive, suite, and UI launches, copy
`config/system_settings.example.json` to the gitignored
`config/system_settings.json`. Keep this owner-readable only: it may contain an
OAuth machine-client secret. Explicit environment and suite overrides take
precedence. The existing runner uploader continues to use `COPY_TO_S3` and
`S3_REPORT_PATH`.

An optional Benchmark Studio UI can create private local connection profiles,
configure the exact inputs accepted by the CLI runner, annotate runs with
cluster/build metadata, show live telemetry and history, manage reusable
execution/metadata profiles, run ordered Performance Suites, and compare or
promote completed results:

```bash
./start_ui.sh
```

Open <http://127.0.0.1:8765>. The CLI remains fully supported and has no UI
dependency. Stop only the UI with `./stop_ui.sh`.

To run an ordered collection of complete saved benchmark forms, use the
**Performance suites** page or invoke the same CLI contract directly. Each
suite entry retains its connection-profile reference, measured/warm-up files,
JMeter plan and settings, iterations, and run metadata:

```bash
./run_benchmark_suite.sh suite_manifests/example_saved_benchmarks.json
```

## Repository layout

```text
.
├── jmeter_benchmarks/jmeter-jdbc-test-framework/
│   ├── Test-Plans/          # JDBC and HTTP JMeter plans
│   ├── test_properties/     # runtime and load-profile examples
│   ├── test_configs/        # runner configuration examples
│   ├── config/              # shared runner settings example (local file ignored)
│   ├── utilities/           # validation, reporting, Query History, and analysis tools
│   ├── ui/                  # optional local control and visualization layer
│   ├── suite_manifests/     # tracked examples + ignored local suite definitions
│   ├── run_benchmark_suite.sh # ordered multi-workload CLI runner
│   ├── setup_ui.sh          # UI-only setup + optional local PostgreSQL
│   ├── start_ui.sh          # optional UI launcher
│   ├── stop_ui.sh           # stop this checkout's UI process
│   └── run_test.sh          # non-interactive runner
├── python_benchmarks/       # one Python runner per supported engine
└── pov/                     # Docker Compose deployment wrapper
```

## Safety and credentials

- Start with a small workload and monitor the target engine before increasing concurrency or arrival rate.
- Keep access tokens, JDBC credentials, AWS credentials, query data, and generated reports out of version control. The repository ignores the common local files, but verify `git status` before committing.
- Pull requests run a public-artifact guard in addition to secret scanning. It
  rejects force-added reports, JMeter result files, connection profiles, local
  registries, logs, private keys, and non-example environment files. Enable the
  same check before every local commit with `git config core.hooksPath .githooks`.
- The separate POV Compose wrapper tracks only `pov/.env.example`, with
  `CHANGE_ME` placeholders. Copy it to the ignored `pov/.env` and set strong
  local values before starting that tool; do not expose its services publicly
  without appropriate authentication and network controls.
- Benchmark like-for-like datasets and cluster sizes, and distinguish client-observed latency from engine execution time when comparing results.

## License

See [LICENSE](LICENSE).
