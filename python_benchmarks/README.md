# Python Benchmark Runners

These scripts run the same CSV workload against e6data, Trino, or Amazon Athena. They support sequential execution and batched concurrent execution, log a run summary, and write a timestamped result CSV beside the script.

## Requirements

- Python 3
- Network access and credentials for the selected engine
- A C/C++ compiler and Python development headers if installation of the e6data connector requires a local build
- AWS credentials discoverable by the AWS SDK when running Athena

From this directory, create an isolated environment and install the pinned connector plus the remaining dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip wheel
python -m pip install -r requirements.txt
```

On Debian/Ubuntu, build prerequisites can be installed with `apt install python3-dev g++`; on Amazon Linux/CentOS, use `yum install python3-devel gcc-c++`.

## Query CSV

Use the exact headers `QUERY_ALIAS` and `QUERY`. The database is supplied by the run-level `DB_NAME` variable for every row.

```csv
QUERY_ALIAS,QUERY
q1,"SELECT COUNT(*) FROM store_sales"
q2,"SELECT COUNT(*) FROM catalog_sales"
```

See [sample.csv](sample.csv). `QUERY_CSV_COLUMN_NAME` can select a differently named query-text column, but the alias column remains `QUERY_ALIAS`.

## Common configuration

Shell assignments must not contain spaces around `=`.

```bash
export DB_NAME=tpcds_1000
export INPUT_CSV_PATH="$PWD/sample.csv"
export QUERYING_MODE=SEQUENTIAL
export SHUFFLE_QUERY=false
```

| Variable | Required | Default | Meaning |
|---|---:|---|---|
| `DB_NAME` | yes | — | Default database/schema for the workload |
| `INPUT_CSV_PATH` | yes | — | Path to the query CSV |
| `QUERYING_MODE` | no | `SEQUENTIAL` | Use exactly `CONCURRENT` for batched concurrency |
| `CONCURRENT_QUERY_COUNT` | concurrent only | `5` | Processes in each submitted batch |
| `CONCURRENCY_INTERVAL` | concurrent only | `5` | Seconds between batch submissions |
| `SHUFFLE_QUERY` | no | `false` | Shuffle only when the value is exactly `true` |

Concurrent mode submits the CSV in batches; it is not a fixed-duration load generator. Use the JMeter framework for sustained concurrency or a target arrival rate.

## Run against e6data

```bash
export ENGINE_IP=cluster.example.com
export E6_USER=user@example.com
export E6_TOKEN='<personal-access-token>'
export CATALOG_NAME=my_catalog
python e6_benchmark.py
```

The connector uses port 80. The report includes query ID, planner parsing/queue/execution time, and output row count when exposed by `explain_analyse`.

## Run against Trino

```bash
export ENGINE_IP=trino.example.com
export ENGINE_PORT=8889
export TRINO_USER=test
export TRINO_CATALOG=test
python trino_benchmark.py
```

`ENGINE_PORT`, `TRINO_USER`, and `TRINO_CATALOG` use the defaults shown above when omitted.

## Run against Amazon Athena

```bash
export RESULT_BUCKET=my-athena-results-bucket
export GLUE_REGION=us-east-1
python athena_benchmark.py
```

`RESULT_BUCKET` must be a bucket name, not an `s3://` URL. Results are staged under `s3://<bucket>/Athena/<timestamp>`. Standard AWS credential resolution is used.

## Output and exit behavior

- e6data: `e6data_results_<timestamp>.csv`
- Trino: `trino_results_<timestamp>.csv`
- Athena: `athena_results_<timestamp>.csv`

The scripts raise an error after writing the report if any query failed, which makes them suitable for CI smoke checks. Result files may contain query text and error details; review them before sharing or committing.
