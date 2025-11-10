# Athena Analysis Utilities (Optional)

SQL-based analysis tools for querying JMeter test results using AWS Athena.

## Overview

These utilities enable advanced analysis capabilities:
- **Multi-dimensional slicing**: By engines, dates, instances, cluster sizes, benchmarks, concurrency
- **Best run identification**: Find optimal performance across any dimension
- **Baseline tracking**: Set and compare against performance baselines
- **Run comparisons**: Compare any two runs or sets of runs
- **Regression detection**: Identify performance degradations automatically
- **Dashboard integration**: Superset, QuickSight, Tableau support

## Quick Start

### 1. Setup Athena Table (One-Time)

```bash
# Open Athena Console and run:
# https://console.aws.amazon.com/athena

CREATE DATABASE IF NOT EXISTS jmeter_analysis;

# Then run the DDL from setup_athena_runs_index.sql
```

### 2. Upload Test Data

```bash
# Upload specific configuration
python utilities/athena/upload_runs_index_to_athena.py --from-s3 \
    "s3://e6-jmeter/jmeter-results/engine=e6data/cluster_size=S-2x2/benchmark=tpcds_29_1tb/run_type=concurrency_2/"

# Or bulk upload all concurrency levels
bash utilities/athena/upload_all_runs_to_athena.sh
```

### 3. Query Data

```sql
-- Find best runs
SELECT run_id, cluster_size, p90_latency_sec, p95_latency_sec
FROM jmeter_analysis.jmeter_runs_index
WHERE engine = 'e6data'
ORDER BY p90_latency_sec ASC
LIMIT 10;
```

See `ATHENA_USEFUL_QUERIES.sql` for more examples.

## Key Files

**Setup & Schema:**
- `setup_athena_runs_index.sql` - Athena table DDL
- `ATHENA_QUICK_START.md` - Setup guide
- `ATHENA_RUNS_INDEX_README.md` - Architecture details

**Data Management:**
- `generate_runs_index.py` - Generate aggregated index from S3
- `upload_runs_index_to_athena.py` - Upload index to S3/Athena
- `sync_s3_to_athena.py` - Sync all results
- `upload_all_runs_to_athena.sh` - Bulk upload script

**Analysis:**
- `query_athena_runs.py` - Query programmatically
- `compare_runs_athena.py` - Compare runs
- `ATHENA_USEFUL_QUERIES.sql` - Example queries (best/worst runs, comparisons)
- `ATHENA_CONSOLE_QUERIES.sql` - Copy-paste queries for console

## Common Use Cases

### Find Best Run Per Configuration
```sql
WITH ranked AS (
    SELECT *, ROW_NUMBER() OVER (
        PARTITION BY cluster_size, run_type
        ORDER BY p90_latency_sec ASC
    ) as rank
    FROM jmeter_analysis.jmeter_runs_index
    WHERE engine = 'e6data'
)
SELECT run_id, cluster_size, run_type, p90_latency_sec
FROM ranked WHERE rank = 1;
```

### Compare Against Baseline
```sql
WITH baseline AS (
    SELECT cluster_size, AVG(p90_latency_sec) as baseline_p90
    FROM jmeter_analysis.jmeter_runs_index
    WHERE run_date >= CAST('2025-11-02' AS TIMESTAMP)
      AND run_date < CAST('2025-11-03' AS TIMESTAMP)
    GROUP BY cluster_size
)
SELECT r.run_id, r.cluster_size, r.p90_latency_sec,
       ROUND((r.p90_latency_sec - b.baseline_p90) / b.baseline_p90 * 100, 1) as pct_change
FROM jmeter_analysis.jmeter_runs_index r
JOIN baseline b ON r.cluster_size = b.cluster_size
WHERE r.run_date >= CAST('2025-11-06' AS TIMESTAMP)
ORDER BY pct_change DESC;
```

### Compare Engines/Instances
```sql
SELECT engine, instance_type, cluster_size,
       COUNT(*) as runs,
       ROUND(AVG(p90_latency_sec), 2) as avg_p90
FROM jmeter_analysis.jmeter_runs_index
WHERE benchmark = 'tpcds_29_1tb'
GROUP BY engine, instance_type, cluster_size
ORDER BY avg_p90;
```

## Dashboard Integration

**Apache Superset:**
```
Connection: awsathena+rest://athena.us-east-1.amazonaws.com:443/jmeter_analysis
Create dataset from: jmeter_runs_index
```

**AWS QuickSight:**
1. New data source → Athena
2. Select jmeter_analysis.jmeter_runs_index
3. Create visualizations

## Cost

~$5 per TB scanned (typically < $0.01 per query for this dataset)

## Documentation

- `ATHENA_QUICK_START.md` - Quick setup
- `ATHENA_RUNS_INDEX_README.md` - Detailed architecture
- `ATHENA_SYNC_GUIDE.md` - Data sync workflows
- `ATHENA_USEFUL_QUERIES.sql` - Curated query examples
