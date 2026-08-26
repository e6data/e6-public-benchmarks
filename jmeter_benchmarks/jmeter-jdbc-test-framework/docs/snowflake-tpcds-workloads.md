# Snowflake public TPC-DS sample

The public catalog contains one Snowflake-oriented TPC-DS sample. It must not
be described as an audited, certified, or compliant TPC benchmark result.

## Public documentation sample

`data_files/benchmarks/tpcds/snowflake_public_sample_103.csv` contains 103 executable query
forms (99 query numbers, with two forms each for queries 14, 23, 24, and 39)
from Snowflake's public TPC-DS sample script. Source order and SQL semantics are
preserved. Surrounding session/timing statements are excluded, indentation is
normalized, and stable `TPCDS_Qnn` aliases are used in the framework's
`QUERY_ALIAS,QUERY` CSV contract.

- Source: `https://docs.snowflake.com/static/samples/tpc-ds-all-queries.sql`
- Source SHA-256: `d7d35ba55bba8225a5bd850e007f1e6abff5eab7d726384bd6f17d9e090136ff`
- Generated CSV SHA-256: `fa841cf6ee0f5ba360f57d385279c6967d83d327b7f5cedcddc0e38714f00abf`
- Retrieved: 2026-08-26
- Intended schemas: Snowflake's TPC-DS sample/Marketplace schemas

Regenerate it with:

```bash
curl -fL -o /tmp/tpc-ds-all-queries.sql \
  https://docs.snowflake.com/static/samples/tpc-ds-all-queries.sql
python3 utilities/import_snowflake_tpcds.py official \
  /tmp/tpc-ds-all-queries.sql /tmp/snowflake-source-order.csv
python3 utilities/build_benchmark_catalog.py tpcds \
  /tmp/snowflake-source-order.csv \
  data_files/benchmarks/tpcds/snowflake_public_sample_103.csv
```

## Private workloads

Internal, curated, customer-specific, or changing Snowflake workloads are not
tracked in this public repository. Select an `s3://` query file in Benchmark
Studio or pass an S3 URI as `QUERY_FILE` to `run_test.sh`. The runner downloads
the object on the runner host, validates the CSV, and records both its source
URI and SHA-256 with the run.

Always compare runs using the exact query-file hash and equivalent logical
aliases. A private workload and this public sample are not interchangeable.
