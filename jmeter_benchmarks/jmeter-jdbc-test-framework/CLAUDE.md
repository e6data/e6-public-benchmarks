# Maintainer guidance

This file describes the framework's current entry points and invariants. Use the
[README](README.md) as the single source for customer setup, examples, load-profile
formats, and troubleshooting; do not duplicate those walkthroughs here.

## Entry points

- `setup_jmeter.sh`: installs/checks JMeter, plugins, standard JDBC drivers and,
  by default, the optional UI runtime. `--without-ui` skips the UI runtime.
- `create_connection.sh`: writes a local connection profile.
- `create_test_config.sh`: saves a reusable `.env`. Primary JDBC choices are
  Sequential, Fixed QPS, and Arrival-rate profile; other plans are Advanced.
- `run_test.sh`: executes saved configuration or environment values.
- `run_jmeter_tests_interactive.sh`: compatibility wrapper around
  `create_test_config.sh --run`; saves configuration and asks before launching.
  Do not add a second runner or a separate menu here.
- `run_benchmark_suite.sh` / `utilities/run_benchmark_suite.py`: ordered suites
  using the same runner. Use `--dry-run` for input validation without execution.
- `benchmark.sh` / `utilities/benchmark_cli.py`: current registry-based baseline
  promotion, listing, deactivation and comparison. Baselines are optional.
- `start_ui.sh`: foreground by default for systemd; `--background` provides
  detached manual startup, log append and a health check. `stop_ui.sh` stops a
  manually started UI. Use systemctl for systemd-managed installations.

## Configuration and input contracts

Connection profiles are local `connection_properties/*.properties`; never commit
credentials. Workload inputs normally live under ignored `data_files/`. Use
recognized alias/SQL headers, preferably `query_alias,query_string`. JDBC CSVs
support quoted multiline SQL; HTTP conversion helpers are not required for JDBC.

Saved `.env` files belong to the runner, not JMeter. The runner selects canonical
test properties from `test_properties/` according to the plan. Explicit overrides
can select another local or S3 properties file. Check `run_test.sh` for precedence;
keep wizard and UI defaults aligned with those bundled properties.

The current fixed-QPS choice is
`Test-Plan-Constant-QPS-On-Arrivals-JSR-Optimized.jmx`. Other existing JMX files
remain available for advanced/manual use.

- Run Once: query passes control duration; `MEASURED_ITERATIONS` repeats the input
  with unchanged aliases. Sequential uses one worker.
- Fixed QPS/concurrency: hold duration is seconds. Fixed QPM's legacy plan uses
  minutes. Do not describe every plan as having a fixed hold period.
- Profile plans: CSV defines duration; `HOLD_PERIOD` does not control it.
  `utilities/load_profile.py` is the shared parser, and
  `utilities/apply_load_profile.py` creates a per-run JMX before JMeter starts.
  Do not mutate source plans or re-enable old schedule preprocessors.
- Use recycling for sustained load. At EOF with recycling disabled, workers can
  stop; do not promise that every test always runs for the full hold interval.
- Arrival shortfall is not proof of an engine bottleneck. Check the concurrency
  cap, load-generator health, startup, errors and actual offered load.
- Random query order does not disable result caching. Record cache policy
  separately when comparing engines.

Warm-up runs sequentially in separate JMeter processes and is excluded from
measured results. Warm-up explicitly disables Query History capture and dashboard
generation. Optional measured e6 Query History capture waits for ingestion before
S3 finalization; it can delay the next sequential comparison leg. Parallel legs
share load-generator resources.

## Metrics and artifacts

UI and `run_summary.json` use successful-query JMeter `Latency` when available,
with an identified elapsed fallback for older files. This is client-observed
JDBC latency, not pure server execution time. Duration, throughput and in-flight
reconstruction use elapsed completion timestamps. Standard JMeter dashboard
statistics use elapsed/sample time; do not label them as the UI's latency metrics.

`AggregateReport.csv` and `SummaryReport.csv` are listener-named sample exports
in the current plans, not pre-aggregated tables. With dashboard generation enabled,
JMeter produces `dashboard/statistics.json`, copied to the report root.
The runner also generates `run_summary.json` and `run_report.md`.

Measured runs snapshot query/warm-up/profile inputs under `inputs/`. These can
contain sensitive SQL; review before sharing. Connection and test-property files
are excluded because they can contain credentials. The evidence manifest and
verified S3 upload metadata are separate artifacts.

Current S3 partitions are:
`engine/benchmark/data_size/cluster_size/run_type/run_date/run_id` (each component
is a `key=value` directory). Older S3/Athena utilities use legacy layouts and
schemas; see [utilities](utilities/README.md). Do not assume they consume current
artifacts or share the Studio baseline registry. Reporting migration is separate
work; retain existing tools unless explicitly authorized to retire them.

Report cleanup uses `utilities/cleanup_reports.py`: dry-run first, then explicit
`--apply` quarantines candidates. Supply the actual registry configuration to
protect baselines/active runs; `--require-s3` also protects unpublished reports.

## Drivers and development checks

See [driver provenance](jdbc_drivers/README.md) and
[engine setup](docs/jdbc-engines.md). Standard setup installs the newest bundled
e6 JAR into JMeter's `lib/ext/` and removes older installed e6 copies. Optional
managed bundles live under `jdbc_drivers/managed/` and are selected at runtime.
Do not manually copy every driver into a shared classpath.

Use Java 17 for the supported setup and Python 3.11 for development checks.
The UI requires Python 3.10+; runner-only helpers have separate compatibility tests.

```bash
./utilities/run_premerge_checks.sh
```

This checks tests, public-artifact safety, shell/Python syntax, JMX and profile
injection. It does not validate a fresh host or real engine authentication.
Only run `utilities/run_smoke_suite.sh` against a live cluster when authorized;
it generates real load. Keep customer quick-start steps synchronized with setup
completion messages and retain documentation regression checks.
