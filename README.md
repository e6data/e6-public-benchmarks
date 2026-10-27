# e6data Public Benchmarks

This repository contains three independent toolsets for running and comparing analytical-engine benchmarks. Use it in a lab or other non-production environment: the runners can generate substantial load, and the utilities have not been hardened as production services.

## Choose a tool

| Tool | Best for | Engines / interfaces | Start here |
|---|---|---|---|
| JMeter JDBC Test Framework | Repeatable concurrency, QPS/QPM, load-profile, and regression tests | e6data, JDBC-compatible engines, and HTTP endpoints | [JMeter guide](jmeter_benchmarks/jmeter-jdbc-test-framework/README.md) |
| Python benchmarks | Small sequential or batched-concurrency runs from a query CSV | e6data and compatible query interfaces | [Python guide](python_benchmarks/README.md) |
| Benchmark POV Tool | Browser-based query-engine comparisons | Docker Compose deployment of prebuilt UI, API, and database images | [POV guide](pov/README.md) |

The toolsets do not share a common runtime or configuration. Enter the selected tool's directory and follow its README.

## JMeter quick start

The JMeter framework is the recommended starting point for query-engine load tests.
Use the [customer quick start](jmeter_benchmarks/jmeter-jdbc-test-framework/README.md#first-benchmark-a-small-sequential-run)
for EC2 prerequisites, Git clone or Download ZIP, and a first connection test.

After getting the code, run these commands from the framework directory:

```bash
./setup_jmeter.sh
./create_connection.sh
# Create data_files/my_queries.csv using the format in the quick start.
./create_test_config.sh
# Name the configuration my_benchmark in the wizard:
GENERATE_DASHBOARD=true ./run_test.sh test_configs/my_benchmark.env
```

The guided wizard offers **Sequential, Fixed QPS, and Arrival-rate profile**;
specialized concurrency and other plans are under Advanced. Start with
`SELECT 1`, then your real workload sequentially, before increasing load.
It selects the bundled test properties for you. No UI, S3, or monitoring
service is required.

See the [CLI examples and reference](jmeter_benchmarks/jmeter-jdbc-test-framework/README.md#cli-reference)
for repeat runs and overrides. Results are saved under the report directory
printed by the runner.

To share published results for customer validation, use the
[Run This Benchmark Yourself](jmeter_benchmarks/jmeter-jdbc-test-framework/docs/run-this-benchmark.md).
It describes the inputs, environment details and reference results to supply,
and the commands customers use to repeat the experiment.

Suites, baselines, S3 uploads, monitoring and the optional UI are documented in
the JMeter guide's optional reference. They are not required for CLI benchmarks.

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
