# Athena-Based Runs Index Analysis

Query and visualize JMeter test runs using AWS Athena, enabling powerful SQL-based analysis and dashboard creation with Superset/QuickSight/Tableau.

## Overview

Instead of generating CSV files from runs_index.json, we upload the data to S3 in a partitioned structure that Athena can query directly. This enables:

- **SQL Queries**: Complex filtering, aggregations, joins
- **Dashboard Tools**: Superset, QuickSight, Tableau connectivity
- **CSV Export**: Export any query result directly from Athena console
- **Performance**: Partitioned by engine/cluster/benchmark/run_type for fast queries
- **Scalability**: Handles thousands of test runs efficiently

## Architecture

```
S3 Structure:
s3://e6-jmeter/jmeter-results-index/runs/
    engine=e6data/
        cluster_size=M-4x4/
            benchmark=tpcds_29_1tb/
                run_type=concurrency_2/
                    data.jsonl     ← All runs for this combination
                run_type=concurrency_4/
                    data.jsonl
            benchmark=tpcds_51_1tb/
                ...
    engine=databricks/
        ...

Athena Table:
- Query using standard SQL
- Partition projection for automatic partition discovery
- JSON SerDe for flexible schema
```

## Setup (One-Time)

### Step 1: Upload Data to S3

Upload runs index data to S3 in Athena-compatible format:

```bash
# From existing runs_index.json
python utilities/upload_runs_index_to_athena.py reports/runs_index.json

# Or generate from S3 and upload directly
python utilities/upload_runs_index_to_athena.py --from-s3 \
    s3://e6-jmeter/jmeter-results/engine=e6data/cluster_size=M-4x4/benchmark=tpcds_29_1tb/run_type=concurrency_2/

# Dry run to see what would be uploaded
python utilities/upload_runs_index_to_athena.py reports/runs_index.json --dry-run
```

### Step 2: Create Athena Table

1. Open AWS Athena Console
2. Select your database (or create one: `CREATE DATABASE jmeter_analysis;`)
3. Run the DDL from `utilities/setup_athena_runs_index.sql`

```sql
-- Copy and paste the CREATE TABLE statement from setup_athena_runs_index.sql
-- This creates the jmeter_runs_index table with partition projection
```

### Step 3: Verify Data

```sql
-- Check if data loaded correctly
SELECT COUNT(*) as total_runs
FROM jmeter_runs_index;

-- View sample data
SELECT run_id, run_date, cluster_size, p50_latency_sec, p90_latency_sec
FROM jmeter_runs_index
ORDER BY run_date DESC
LIMIT 10;
```

## Usage Examples

### 1. Compare Performance Across Cluster Sizes

```sql
SELECT
    cluster_size,
    instance_type,
    COUNT(*) as num_runs,
    ROUND(AVG(p50_latency_sec), 2) as avg_p50,
    ROUND(AVG(p90_latency_sec), 2) as avg_p90,
    ROUND(AVG(p95_latency_sec), 2) as avg_p95,
    ROUND(AVG(queries_per_minute), 2) as avg_qpm
FROM jmeter_runs_index
WHERE engine = 'e6data'
  AND benchmark = 'tpcds_29_1tb'
  AND run_type = 'concurrency_8'
GROUP BY cluster_size, instance_type
ORDER BY avg_p50;
```

### 2. Find Regressions (Runs Slower Than Average)

```sql
WITH avg_metrics AS (
    SELECT
        cluster_size,
        run_type,
        AVG(p90_latency_sec) as avg_p90,
        STDDEV(p90_latency_sec) as stddev_p90
    FROM jmeter_runs_index
    WHERE engine = 'e6data'
      AND benchmark = 'tpcds_29_1tb'
    GROUP BY cluster_size, run_type
)
SELECT
    r.run_id,
    r.run_date,
    r.cluster_size,
    r.run_type,
    r.p90_latency_sec,
    a.avg_p90,
    ROUND((r.p90_latency_sec - a.avg_p90) / a.avg_p90 * 100, 2) as pct_slower
FROM jmeter_runs_index r
JOIN avg_metrics a
    ON r.cluster_size = a.cluster_size
    AND r.run_type = a.run_type
WHERE r.engine = 'e6data'
  AND r.benchmark = 'tpcds_29_1tb'
  AND r.p90_latency_sec > a.avg_p90 + a.stddev_p90
ORDER BY pct_slower DESC;
```

### 3. Instance Type Comparison (r6id vs r7iz)

```sql
SELECT
    instance_type,
    COUNT(*) as runs,
    ROUND(AVG(p50_latency_sec), 2) as avg_p50,
    ROUND(AVG(p90_latency_sec), 2) as avg_p90,
    ROUND(AVG(p99_latency_sec), 2) as avg_p99,
    ROUND(MIN(p50_latency_sec), 2) as best_p50,
    ROUND(MAX(p50_latency_sec), 2) as worst_p50
FROM jmeter_runs_index
WHERE cluster_size = 'M-4x4'
  AND benchmark = 'tpcds_29_1tb'
  AND run_type = 'concurrency_2'
GROUP BY instance_type;
```

### 4. Identify Consistently Slow Queries

```sql
SELECT
    slowest.query as query_name,
    COUNT(*) as times_in_top3,
    ROUND(AVG(slowest.avg_sec), 2) as avg_time_sec,
    ROUND(MIN(slowest.avg_sec), 2) as min_time_sec,
    ROUND(MAX(slowest.avg_sec), 2) as max_time_sec
FROM jmeter_runs_index
CROSS JOIN UNNEST(top_slowest_queries) as t(slowest)
WHERE engine = 'e6data'
  AND benchmark = 'tpcds_29_1tb'
GROUP BY slowest.query
HAVING COUNT(*) >= 3
ORDER BY times_in_top3 DESC, avg_time_sec DESC;
```

### 5. Performance Trend Over Time

```sql
SELECT
    DATE_TRUNC('day', CAST(run_date AS TIMESTAMP)) as run_day,
    cluster_size,
    run_type,
    ROUND(AVG(p90_latency_sec), 2) as avg_p90,
    ROUND(AVG(queries_per_minute), 2) as avg_qpm,
    COUNT(*) as num_runs
FROM jmeter_runs_index
WHERE engine = 'e6data'
  AND run_date >= CAST(DATE_ADD('day', -7, CURRENT_DATE) AS VARCHAR)
GROUP BY DATE_TRUNC('day', CAST(run_date AS TIMESTAMP)), cluster_size, run_type
ORDER BY run_day DESC, cluster_size;
```

### 6. Export to CSV from Athena Console

1. Run any query in Athena console
2. Click "Download results" button
3. CSV file downloaded to your local machine

## Updating Data

### Add New Runs to Existing Partition

When you run new tests, generate a fresh index and re-upload:

```bash
# Generate index for new runs
python utilities/generate_runs_index.py \
    s3://e6-jmeter/jmeter-results/engine=e6data/cluster_size=M-4x4/benchmark=tpcds_29_1tb/run_type=concurrency_2/ \
    --output reports/runs_index_concurrency_2.json

# Upload to Athena (overwrites previous data.jsonl for this partition)
python utilities/upload_runs_index_to_athena.py reports/runs_index_concurrency_2.json
```

**Note**: This overwrites the previous `data.jsonl` file for that partition. All runs are regenerated from scratch each time.

### Bulk Update for All Run Types

```bash
# Generate and upload for all concurrency levels
for concurrency in 2 4 8 12 16; do
    echo "Processing concurrency=$concurrency..."
    python utilities/upload_runs_index_to_athena.py --from-s3 \
        "s3://e6-jmeter/jmeter-results/engine=e6data/cluster_size=M-4x4/benchmark=tpcds_29_1tb/run_type=concurrency_$concurrency/"
done
```

## Dashboard Integration

### Apache Superset

1. Add Athena as a database:
   - Connection: `awsathena+rest://`
   - Configure AWS credentials (IAM role or access keys)
   - Select database: `jmeter_analysis`

2. Create dataset from `jmeter_runs_index` table

3. Build charts:
   - Line chart: p90 latency over time by cluster_size
   - Bar chart: Average latency by instance_type
   - Table: Latest 20 runs with key metrics
   - Scatter plot: p90 vs throughput colored by cluster_size

4. Create dashboard combining multiple charts

### AWS QuickSight

1. Create new data source → Athena
2. Select `jmeter_analysis` database and `jmeter_runs_index` table
3. Import to SPICE for faster performance (optional)
4. Create analysis with visualizations

### Tableau

1. Connect to Athena using JDBC driver
2. Configure AWS credentials
3. Select `jmeter_runs_index` table
4. Create worksheets and dashboards

## Schema Reference

### Main Columns

| Column | Type | Description |
|--------|------|-------------|
| `run_id` | STRING | YYYYMMDD-HHMMSS timestamp |
| `run_date` | TIMESTAMP | Human-readable date |
| `cluster_size` | STRING | M-4x4, S-2x2, etc. |
| `instance_type` | STRING | r6id.8xlarge, r7iz.8xlarge, etc. |
| `estimated_cores` | INT | Total cores in cluster |
| `concurrent_threads` | INT | JMeter concurrent threads |
| `p50_latency_sec` | DOUBLE | Median latency |
| `p90_latency_sec` | DOUBLE | 90th percentile latency |
| `p95_latency_sec` | DOUBLE | 95th percentile latency |
| `p99_latency_sec` | DOUBLE | 99th percentile latency |
| `queries_per_minute` | DOUBLE | Throughput |
| `total_success` | INT | Successful queries |
| `total_failed` | INT | Failed queries |
| `error_rate_pct` | DOUBLE | Error percentage |
| `top_slowest_queries` | ARRAY | Top 3 slowest queries |

### Partition Columns

| Partition | Values |
|-----------|--------|
| `engine` | e6data, databricks, trino, presto, athena |
| `cluster_size_partition` | S-2x2, M-4x4, L-8x8, XL-16x16 |
| `benchmark_partition` | tpcds_29_1tb, tpcds_51_1tb, kantar |
| `run_type` | concurrency_2, concurrency_4, concurrency_8, concurrency_12, concurrency_16 |

## Benefits vs CSV Export

| Aspect | CSV Export | Athena Approach |
|--------|-----------|-----------------|
| **Query Power** | Excel filters only | Full SQL (joins, aggregations, window functions) |
| **Scalability** | Limited to Excel row limits | Handles millions of rows |
| **Versioning** | Manual file management | Automatic via S3 partitions |
| **Sharing** | Email files | Share Athena queries or dashboard links |
| **Automation** | Manual export each time | Query results via API/SDK |
| **Cost** | Free | ~$5 per TB scanned (very low for this data) |
| **Dashboards** | Manual charts in Excel | Professional dashboards in Superset/QuickSight |

## Troubleshooting

### Query returns no results

```sql
-- Check if partitions exist
SHOW PARTITIONS jmeter_runs_index;

-- If empty, verify S3 data exists
-- aws s3 ls s3://e6-jmeter/jmeter-results-index/runs/ --recursive
```

### Permission errors

Ensure your IAM role/user has:
- `s3:GetObject` on `s3://e6-jmeter/jmeter-results-index/*`
- `athena:*` permissions
- `glue:*` permissions (for Data Catalog)

### Data not updating after upload

Athena caches query results. Either:
1. Wait 5-10 minutes for cache to expire
2. Run a different query to bypass cache
3. Clear query result cache in Athena settings

## Advanced: Joining with Test Results

You can join the runs index with the actual test results table:

```sql
-- Find queries that are consistently slow across runs
SELECT
    ri.run_id,
    ri.cluster_size,
    tr.query_name,
    ROUND(AVG(tr.latency_ms) / 1000.0, 2) as avg_latency_sec
FROM jmeter_runs_index ri
JOIN jmeter_test_results tr
    ON ri.run_id = tr.run_id
WHERE ri.engine = 'e6data'
  AND tr.success = true
GROUP BY ri.run_id, ri.cluster_size, tr.query_name
HAVING AVG(tr.latency_ms) / 1000.0 > 10
ORDER BY avg_latency_sec DESC;
```

## See Also

- `utilities/generate_runs_index.py` - Generate index from S3 test results
- `utilities/setup_athena_runs_index.sql` - Athena table DDL and sample queries
- `utilities/upload_runs_index_to_athena.py` - Upload data to S3 for Athena
