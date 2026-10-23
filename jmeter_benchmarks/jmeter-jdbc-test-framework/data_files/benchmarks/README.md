# External benchmark workloads

This public repository does not bundle TPC-DS, TPC-H, vendor-specific,
optimized, historical, or organization-specific SQL suites. Benchmark Studio
is a generic JMeter runner: supply a workload that you are authorized to use
as a local file or an `s3://` URI.

Every query CSV must use the framework contract:

```csv
query_alias,query_string
Q01,"select 1"
```

Warm-up files use the same contract. Their samples are written below
`REPORT_PATH/_warmup/` and excluded from measured benchmark statistics.

For reproducible comparisons, retain stable aliases and compare equivalent
data, query semantics, execution policies, and successful query coverage. The
runner records the original input URI and resolved SHA-256 with each run.

Headers are case-insensitive; `QUERY_ALIAS,QUERY` is also accepted. See the
[main guide](../../README.md#first-benchmark-a-small-sequential-run) for setup
and CSV quoting rules. This directory documents the contract, not a bundled suite.
