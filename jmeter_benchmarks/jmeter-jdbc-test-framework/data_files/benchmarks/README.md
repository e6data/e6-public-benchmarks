# Full benchmark query catalog

This catalog keeps complete TPC-DS and TPC-H SQL inventories separate by
lineage and dialect. Every executable CSV uses the strict
`QUERY_ALIAS,QUERY` runner contract and stable logical aliases:

- TPC-DS vendor/reference suites: `TPCDS_Q01` through `TPCDS_Q99`, including
  `A`/`B` forms for the four split templates (103 executable forms).
- Legacy E6 harness suites: `TPCDS_LEGACY_*`. These aliases are aligned only
  between the E6 and Snowflake legacy files because the source numbers are
  execution-sequence labels, not canonical TPC-DS query numbers.
- TPC-H: `TPCH_Q01` through `TPCH_Q22` (22 executable queries).

The paths under `canonical/`, `databricks/`, `snowflake/`, and `e6data/` are
workload identities, not claims that one SQL file is portable to every engine.
Use `catalog.json` to distinguish vendor-published, portable-reference, and
legacy optimized SQL.

## Fair comparisons

For the strictest comparison, run the *same CSV* on each compatible engine.
When dialect-specific CSVs are required, compare by the stable logical alias
and retain the catalog variant ID in the result metadata. Never aggregate two
runs unless they cover the same logical aliases, data scale and semantics and
all required queries succeeded.

The Databricks and Snowflake directories contain vendor-published SQL. The E6
files preserve an existing optimized legacy harness workload. Trino and Presto
do not currently have a separately published full suite in this catalog; use
the portable Apache Spark reference only after preflight/execution validation
against the target catalog. The catalog deliberately does not create cosmetic
copies and label them as vendor SQL.

These are query-engine regression workloads. They are not audited TPC
benchmark results.

## Regeneration

The deterministic converter retains SQL semantics, changes aliases to the
stable logical IDs, removes explicitly requested legacy bootstrap probes, and
normalizes tab indentation:

```bash
python3 utilities/build_benchmark_catalog.py tpcds SOURCE.csv TARGET.csv
python3 utilities/build_benchmark_catalog.py tpcds SOURCE.csv TARGET.csv --skip-bootstrap
python3 utilities/build_benchmark_catalog.py tpcds SOURCE.csv TARGET.csv --skip-bootstrap --legacy-sequence
python3 utilities/build_benchmark_catalog.py tpch SOURCE.csv TARGET.csv
python3 utilities/build_benchmark_catalog.py tpch snowflake.sql TARGET.csv --snowflake-script
```

See `catalog.json` for pinned upstream sources and SHA-256 hashes.
