# Athena Quick Start Guide

## ✅ Setup Complete!

Your Athena table is ready to use:
- **Database**: `jmeter_analysis`
- **Table**: `jmeter_runs_index`
- **S3 Data Location**: `s3://e6-jmeter/jmeter-results-index/runs/`
- **Region**: `us-east-1`

## 🚀 Quick Access

### Athena Console
https://us-east-1.console.aws.amazon.com/athena/home?region=us-east-1#/query-editor

### Sample Query (Copy-Paste Ready)
```sql
SELECT
    run_id,
    run_date,
    cluster_size,
    instance_type,
    p50_latency_sec,
    p90_latency_sec,
    p95_latency_sec,
    p99_latency_sec
FROM jmeter_analysis.jmeter_runs_index
WHERE engine = 'e6data'
  AND run_type = 'concurrency_2'
ORDER BY run_date DESC;
```

## 📊 Current Data

**Verified Working:**
- ✅ 2 runs loaded for e6data/M-4x4/tpcds_29_1tb/concurrency_2
- ✅ Instance types: r6id.8xlarge, r7iz.8xlarge
- ✅ SQL queries working
- ✅ Partition projection enabled (auto-discovery)

**Test Results:**
```
Instance Type        Avg P50    Avg P90    Avg P99
-------------------------------------------------
r7iz.8xlarge         3.28s      8.73s      11.56s  ← Faster
r6id.8xlarge         3.99s      11.33s     15.89s
```

## 🔄 Adding More Data

### For New Test Runs:
```bash
# Step 1: Generate index for a specific run_type
python utilities/generate_runs_index.py \
    s3://e6-jmeter/jmeter-results/engine=e6data/cluster_size=M-4x4/benchmark=tpcds_29_1tb/run_type=concurrency_8/

# Step 2: Upload to Athena
python utilities/upload_runs_index_to_athena.py reports/runs_index.json

# Step 3: Query immediately (no MSCK REPAIR needed!)
```

### Bulk Update All Concurrency Levels:
```bash
for concurrency in 2 4 8 12 16; do
    python utilities/upload_runs_index_to_athena.py --from-s3 \
        "s3://e6-jmeter/jmeter-results/engine=e6data/cluster_size=M-4x4/benchmark=tpcds_29_1tb/run_type=concurrency_$concurrency/"
done
```

## 💡 Useful Queries

### 1. Latest 10 Runs
```sql
SELECT run_id, run_date, cluster_size, p50_latency_sec, p90_latency_sec
FROM jmeter_analysis.jmeter_runs_index
WHERE engine = 'e6data'
ORDER BY run_date DESC
LIMIT 10;
```

### 2. Compare All Cluster Sizes
```sql
SELECT
    cluster_size,
    COUNT(*) as num_runs,
    ROUND(AVG(p50_latency_sec), 2) as avg_p50,
    ROUND(AVG(p90_latency_sec), 2) as avg_p90,
    ROUND(AVG(queries_per_minute), 2) as avg_qpm
FROM jmeter_analysis.jmeter_runs_index
WHERE engine = 'e6data'
  AND benchmark_partition = 'tpcds_29_1tb'
GROUP BY cluster_size
ORDER BY avg_p50;
```

### 3. Find Slowest Queries
```sql
SELECT
    slowest.query as query_name,
    ROUND(AVG(slowest.avg_sec), 2) as avg_time_sec,
    COUNT(*) as times_in_top3
FROM jmeter_analysis.jmeter_runs_index
CROSS JOIN UNNEST(top_slowest_queries) as t(slowest)
WHERE engine = 'e6data'
GROUP BY slowest.query
ORDER BY avg_time_sec DESC
LIMIT 10;
```

### 4. Detect Regressions
```sql
WITH avg_metrics AS (
    SELECT AVG(p90_latency_sec) as baseline_p90
    FROM jmeter_analysis.jmeter_runs_index
    WHERE cluster_size = 'M-4x4'
      AND run_type = 'concurrency_2'
)
SELECT
    run_id,
    run_date,
    instance_type,
    p90_latency_sec,
    baseline_p90,
    ROUND((p90_latency_sec - baseline_p90) / baseline_p90 * 100, 1) as pct_slower
FROM jmeter_analysis.jmeter_runs_index, avg_metrics
WHERE cluster_size = 'M-4x4'
  AND run_type = 'concurrency_2'
  AND p90_latency_sec > baseline_p90 * 1.1
ORDER BY pct_slower DESC;
```

### 5. Export to CSV
Run any query in Athena console, then click:
**"Download results"** button → CSV file downloaded

## 📈 Dashboard Setup

### Apache Superset
1. Add database: `awsathena+rest://`
2. Configure AWS credentials
3. Create dataset from `jmeter_analysis.jmeter_runs_index`
4. Build charts and dashboards

### AWS QuickSight
1. New data source → Athena
2. Select `jmeter_analysis` database
3. Import `jmeter_runs_index` to SPICE (optional)
4. Create visualizations

## 🔍 Available Columns

**Performance Metrics:**
- `p50_latency_sec`, `p90_latency_sec`, `p95_latency_sec`, `p99_latency_sec`
- `avg_latency_sec`, `median_latency_sec`, `min_latency_sec`, `max_latency_sec`
- `queries_per_minute`, `queries_per_second`

**Cluster Info:**
- `cluster_size`, `instance_type`, `estimated_cores`, `executors`

**Test Config:**
- `concurrent_threads`, `benchmark`, `test_plan_file`
- `total_query_count`, `actual_considered_queries`

**Results:**
- `total_success`, `total_failed`, `error_rate_pct`
- `performance_rating`, `consistency_rating`

**Partitions (for filtering):**
- `engine` (e6data, databricks, trino, presto, athena)
- `cluster_size_partition` (S-2x2, M-4x4, L-8x8, XL-16x16)
- `benchmark_partition` (tpcds_29_1tb, tpcds_51_1tb, kantar)
- `run_type` (concurrency_2, concurrency_4, concurrency_8, etc.)

## 📝 Notes

- **No MSCK REPAIR needed**: Partition projection handles this automatically
- **Query costs**: ~$5 per TB scanned (very cheap for this data size)
- **Result caching**: Athena caches results for 24 hours
- **Data updates**: Re-upload overwrites previous data for that partition
- **Partition projection**: Only valid partition combinations are queryable

## 📚 Full Documentation

See `utilities/ATHENA_RUNS_INDEX_README.md` for complete details.
