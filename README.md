# e6data Public Benchmarks

This repository contains three independent toolsets for running and comparing analytical-engine benchmarks. Use it in a lab or other non-production environment: the runners can generate substantial load, and the utilities have not been hardened as production services.

## Choose a tool

| Tool | Best for | Engines / interfaces | Start here |
|---|---|---|---|
| JMeter JDBC Test Framework | Repeatable concurrency, QPS/QPM, load-profile, and regression tests | JDBC and HTTP endpoints; connection templates cover e6data, Databricks, Trino, and others | [JMeter guide](jmeter_benchmarks/jmeter-jdbc-test-framework/README.md) |
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

An optional local UI can launch the same unchanged CLI runner, show live runs,
start the same workload on two engines, and compare completed reports:

```bash
./run_ui.sh
```

Open <http://127.0.0.1:8765>. The CLI remains fully supported and has no UI
dependency.

## Repository layout

```text
.
├── jmeter_benchmarks/jmeter-jdbc-test-framework/
│   ├── Test-Plans/          # JDBC and HTTP JMeter plans
│   ├── test_properties/     # runtime and load-profile examples
│   ├── test_configs/        # runner configuration examples
│   ├── utilities/           # local, S3, and Athena analysis tools
│   ├── ui/                  # optional local control and visualization layer
│   ├── run_ui.sh            # optional UI launcher
│   └── run_test.sh          # non-interactive runner
├── python_benchmarks/       # one Python runner per supported engine
└── pov/                     # Docker Compose deployment wrapper
```

## Safety and credentials

- Start with a small workload and monitor the target engine before increasing concurrency or arrival rate.
- Keep access tokens, JDBC credentials, AWS credentials, query data, and generated reports out of version control. The repository ignores the common local files, but verify `git status` before committing.
- The POV Compose file ships demonstration credentials in `pov/.env`; replace them before exposing it beyond localhost.
- Benchmark like-for-like datasets and cluster sizes, and distinguish client-observed latency from engine execution time when comparing results.

## License

See [LICENSE](LICENSE).
