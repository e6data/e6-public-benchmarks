# Full benchmark query catalog

This catalog keeps complete TPC-DS and TPC-H SQL inventories separate by
lineage and dialect. Every executable CSV uses the strict
`QUERY_ALIAS,QUERY` runner contract and stable logical aliases:

- TPC-DS vendor/reference suites: `TPCDS_Q01` through `TPCDS_Q99`, including
  `A`/`B` forms for the four split templates (103 executable forms).
- TPC-H: `TPCH_Q01` through `TPCH_Q22` (22 executable queries).

Files are grouped only by benchmark; their names identify source lineage and
dialect. This compact layout does not claim that one SQL file is portable to
every engine. Use `catalog.json` to distinguish public samples, published
reference sources. Optimized, historical, and organization-specific workloads
are runtime inputs and are not tracked here.

## Fair comparisons

For the strictest comparison, run the *same CSV* on each compatible engine.
When dialect-specific CSVs are required, compare by the stable logical alias
and retain the catalog variant ID in the result metadata. Never aggregate two
runs unless they cover the same logical aliases, data scale and semantics and
all required queries succeeded.

The Snowflake files are derived from public documentation samples; their names
do not claim an audited or certified benchmark. The Databricks files retain
the public `spark-sql-perf` lineage. The `2_4` upstream directory remains recorded in
`catalog.json` but is intentionally omitted from the public filename because
it is source lineage, not a Databricks runtime requirement. Trino and Presto do
not currently have separately published full suites in this catalog; validate
the Apache Spark reference against the target engine before use.

For e6data, begin with the Apache Spark reference suite. Add an e6data dialect
variant only after documenting syntax-only changes and validating equivalent
results. Engine-specific optimizations are not dialect-only query suites and
must remain external to this public catalog.

Private, optimized, historical, or organization-specific query suites are
runtime inputs, not public catalog entries. Supply them with the UI's S3
selector or an S3 URI in the CLI;
the downloaded input and its SHA-256 are recorded with the run and remain
git-ignored.

These are query-engine regression workloads. They are not audited TPC
benchmark results.

## Regeneration

The deterministic converter retains SQL semantics, changes aliases to the
stable logical IDs, and normalizes tab indentation:

```bash
python3 utilities/build_benchmark_catalog.py tpcds SOURCE.csv TARGET.csv
python3 utilities/build_benchmark_catalog.py tpch SOURCE.csv TARGET.csv
python3 utilities/build_benchmark_catalog.py tpch snowflake.sql TARGET.csv --snowflake-script
```

See `catalog.json` for pinned upstream sources and SHA-256 hashes.
See `THIRD_PARTY_NOTICES.md` for upstream licensing and trademark notices.
