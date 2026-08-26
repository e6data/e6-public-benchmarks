# Snowflake TPC-DS workloads

Two Snowflake-oriented query files are shipped separately so their provenance
and intended use remain clear. Neither should be described as an audited or
compliant TPC benchmark result.

## Snowflake official sample

`data_files/TPCDS_Snowflake_Official_103.csv` contains the 103 executable query
forms (99 query numbers, with two forms each for queries 14, 23, 24, and 39)
from Snowflake's public TPC-DS sample script. Source order and SQL semantics are
preserved; only the surrounding session/timing statements are excluded, tab
indentation is normalized to spaces, and the queries are wrapped in the
framework's `QUERY_ALIAS,QUERY` CSV contract.

- Source: `https://docs.snowflake.com/static/samples/tpc-ds-all-queries.sql`
- Source SHA-256: `d7d35ba55bba8225a5bd850e007f1e6abff5eab7d726384bd6f17d9e090136ff`
- Generated CSV SHA-256: `f7610b953542d64a6e312832010efd797d6531c35a4dfa32b28cec8c8c780c06`
- Retrieved: 2026-08-26
- Intended schemas: Snowflake's TPC-DS sample/Marketplace schemas

Regenerate it with:

```bash
curl -fL -o /tmp/tpc-ds-all-queries.sql \
  https://docs.snowflake.com/static/samples/tpc-ds-all-queries.sql
python3 utilities/import_snowflake_tpcds.py official \
  /tmp/tpc-ds-all-queries.sql data_files/TPCDS_Snowflake_Official_103.csv
```

## Existing e6-perf-test legacy subset

`data_files/TPCDS_Snowflake_e6_perf_test_Legacy_Subset.csv` is a format-only
conversion of the existing tracked workload from the sibling
`e6data/e6-perf-test` repository. It includes its bootstrap checks and curated
subset and is retained for cross-framework comparison; it is not the same
workload as Snowflake's official sample.

- Source repository: `https://github.com/e6data/e6-perf-test`
- Source path: `src/main/resources/Data-Files/SF_TPCDS_1TB_Subset_queries.csv`
- Source commit: `a6c050bd77f05fbc2de71b745af45e625f1578a3`
- Source SHA-256: `ad668c1c753a17dade80d98b057b72c72f815a11ac1114bc479783f4654aff6f`
- Generated CSV SHA-256: `3c7e42d0f0cad2579cfa242a2a71b02082a20ee6a3c0fc366d6c27d49b1bfd1c`
- Conversion: retain `QUERY_ALIAS` and `QUERY`; discard DSL-only metadata columns

Regenerate from a sibling checkout with:

```bash
python3 utilities/import_snowflake_tpcds.py legacy \
  ../../../e6-perf-test/src/main/resources/Data-Files/SF_TPCDS_1TB_Subset_queries.csv \
  data_files/TPCDS_Snowflake_e6_perf_test_Legacy_Subset.csv
```

Always compare runs using the exact query-file hash. Do not compare these two
files as though they were identical workloads.
