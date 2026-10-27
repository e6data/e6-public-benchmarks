# How to Run Benchmarks Using This Repository

Run benchmarks in your environment using this repository, or reproduce a shared
benchmark using its supplied queries, configuration and reference results.
For your own workload, start with the [CLI quick start](../README.md#first-benchmark-a-small-sequential-run)
and choose sequential, fixed QPS or an arrival-rate profile. The steps below
explain how to prepare and run a shared benchmark on a Linux/EC2 runner, using
TPC-DS as an example. The same CLI flow applies to TPC-H, ClickBench or your own
SQL: supply the appropriate query CSV and prepare its dataset on the target engine.
No UI or S3 account is required. Matching the experiment
does not guarantee identical timings: hardware, data layout, software and cache
state matter.

The repository does **not** provision the engine or generate/load the dataset.
Its tracked `E6Data_TPCDS_queries_29_1TB.csv` is a subset with bootstrap queries,
not a complete TPC-DS workload. Use the exact query file supplied with the
publication; do not substitute another file based on its name. Describe these
as TPC-DS-derived workload results unless the publication establishes otherwise.

## Publisher: prepare the handoff

Send a reviewed folder containing the following, alongside the commit-specific
repository link. Include a short `reproduction-details.md` with the actual values
listed below, not an unfilled template.

| File | Required contents |
| --- | --- |
| `reproduction-details.md` | Exact repository commit, environment, methodology, commands and expected counts |
| `queries.csv` | Exact measured SQL and aliases, including any dialect changes or bootstrap queries |
| `benchmark.env` | Reviewed run settings; connection path only, no credentials |
| `dataset/` | Authorized data location or generation instructions, generator version/seed/scale, DDL and load instructions, table row counts and layout |
| `reference-results/` | Reviewed report, summary, raw samples and artifact manifest for all reported repeats |
| `warmup.csv` / `load-profile.csv` | Include when different warm-up SQL or a load schedule was used |
| `SHA256SUMS` | Checksums for the supplied files, excluding this checksum file itself |

Do not include connection files, tokens or an unreviewed checkout. An `.env`
file is sourced as shell code: inspect it before running. The runner's artifact
manifest covers results; it does not automatically package the repository,
dataset or reproduction instructions. On Linux, create handoff checksums from
inside the reviewed folder with:

```bash
find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS
```

### What to record in reproduction-details.md

- Repository commit/download link and exact CLI command.
- Query count/checksum, dataset source or generator version/seed/scale, DDL,
  expected table counts, table format and physical layout.
- Engine version/compute/settings; runner OS/CPU/RAM/region; Java, JMeter and
  JDBC driver versions; catalog/schema mapping and SQL changes.
- Cache policy, warm-up, measured passes, load/duration, timeout, result-row
  limit and fetch settings. Include expected sample counts and correctness checks.
- All reference run IDs, metric definition, repeat-selection/aggregation rule,
  comparison tolerance and known limitations.

Customers return their run IDs/results plus any differences from these settings.

## Customer: set up and verify inputs

1. Obtain the handoff, an accessible engine, credentials and permission to read
   the dataset. Follow its dataset setup instructions before benchmarking.
   Match compute, data layout and cache settings where possible; record differences.
2. Follow the [EC2 prerequisites and setup](../README.md#first-benchmark-a-small-sequential-run).
   Clone and check out the **supplied commit**, or download its commit-specific
   ZIP. Run `./setup_jmeter.sh` from the framework directory. Match the published
   Java, JMeter and JDBC driver versions; record any differences.
3. In the handoff directory run `sha256sum -c SHA256SUMS`. Then, from the
   framework directory, copy the handoff inputs to the paths specified in its
   `benchmark.env`. For the example below, use:

   ```bash
   mkdir -p data_files/customer-tpcds test_configs
   cp /path/to/handoff/queries.csv data_files/customer-tpcds/queries.csv
   cp /path/to/handoff/benchmark.env test_configs/customer-tpcds.env
   ./create_connection.sh
   ```

4. Select the appropriate engine in the connection wizard and supply your own
   endpoint and credentials. Set `CONNECTION_FILE` in the copied config to the
   saved path. Its default catalog/schema must match the SQL. If fully qualified
   SQL needs different identifiers, record those edits and new checksums; that
   is an adapted reproduction, not byte-identical input.
5. Run the README's small `SELECT 1` smoke test first. Verify table access and
   expected dataset row counts separately, outside the timed benchmark.

## Example sequential configuration

The publisher must supply settings matching the reported experiment. This
example performs one excluded warm-up pass followed by three measured passes
with one query at a time. It is not a universal TPC-DS configuration.

```bash
CONNECTION_FILE=connection_properties/customer_connection.properties
QUERY_FILE=data_files/customer-tpcds/queries.csv
TEST_PLAN=Test-Plans/Test-Plan-Run-Once-static-concurrency.jmx
TEST_PROPERTIES_FILE=test_properties/run_once.properties
CONCURRENT_QUERY_COUNT=1
RAMP_UP_TIME=0
RAMP_UP_STEPS=1
RANDOM_ORDER=false
RECYCLE_ON_EOF=false
WARMUP_ENABLED=true
WARMUP_QUERY_FILE=data_files/customer-tpcds/queries.csv
WARMUP_ITERATIONS=1
MEASURED_ITERATIONS=3
QUERY_TIMEOUT=300
LIMIT_RESULTSET=1000
MAX_ERROR_PCT=0
GENERATE_DASHBOARD=true
COPY_TO_S3=false
PROMETHEUS_ENABLED=false
E6_QUERY_HISTORY_ENABLED=false
REPORT_PATH=reports/customer-tpcds
```

The result-row limit and query timeout must match the publication. A JDBC timeout
is not a guaranteed process deadline if a driver stalls. Warm-up does not disable
result caching: configure and document engine cache policy separately. Start in
a fresh shell without previously exported benchmark overrides, then run:

```bash
./run_test.sh test_configs/customer-tpcds.env
```

The runner selects no additional interactive settings. Its printed report path
identifies this run; excluded warm-up results are under the `_warmup` directory.
For a QPS or profile publication, use the publisher's corresponding configuration
and schedule rather than replacing it with this sequential example.

## Validate and compare

- Confirm the process succeeded, there are no failed measured queries, and the
  measured query sample count equals CSV data rows × measured passes. For this
  example that is `N × 3`, excluding the `N` warm-up executions. Do not assume
  a workload named “99” contains exactly 99 SQL statements.
- Check generator health and verify representative query results against the
  supplied expectations outside the timed run. A successful response or capped
  materialized row count alone does not prove result equivalence.
- Compare the same metric, query population and repetition rule. Use successful
  JMeter latency for client-observed latency comparisons; native JMeter dashboard
  percentiles use full elapsed time. Neither is interchangeable with server
  execution time. Do not compare a best pass with an average across all passes.
- Return the reviewed run report, summary, CSV, manifest and completed environment
  details. Include failures and deviations rather than silently omitting them.
  Use the publisher's stated tolerance; matching timings exactly is not expected.

See the [output descriptions](../README.md#test-output) for the evidence files.
