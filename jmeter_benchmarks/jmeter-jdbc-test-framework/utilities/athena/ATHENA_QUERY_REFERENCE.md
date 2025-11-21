# Athena Query Reference for JMeter Benchmark Results

**Last Updated:** 2025-11-16
**Database:** `jmeter_benchmarks`
**Table:** `jmeter_runs_index`

---

## Table of Contents

1. [Quick Start Queries](#quick-start-queries)
2. [Performance Analysis](#performance-analysis)
3. [Outlier Management](#outlier-management)
4. [Comparison Queries](#comparison-queries)
5. [Data Validation](#data-validation)
6. [Advanced Analytics](#advanced-analytics)
7. [Utility Queries](#utility-queries)
8. [Query Generator Tool](#query-generator-tool)

---

## Quick Start Queries

### 1. Valid Runs Only (Most Common)

**Use Case:** Default query for analyzing benchmark results, excluding outliers

```sql
SELECT
    engine,
    cluster_size,
    instance_type,
    benchmark,
    run_type,
    run_id,
    run_date,
    ROUND(queries_per_second, 2) as qps,
    ROUND(avg_latency_sec, 2) as avg_time,
    ROUND(p50_latency_sec, 2) as p50,
    ROUND(p90_latency_sec, 2) as p90,
    ROUND(p95_latency_sec, 2) as p95,
    ROUND(p99_latency_sec, 2) as p99,
    ROUND(total_time_taken_sec, 2) as test_duration_sec,
    total_success,
    total_failed,
    is_outlier
FROM jmeter_runs_index
WHERE is_outlier = 'no'
  AND engine = 'e6data'
  AND cluster_size = 'S-2x2'
  AND benchmark = 'tpcds_29_1tb'
ORDER BY run_type, run_date DESC;
```

### 2. Recent Runs (Last 20)

**Use Case:** Quick health check of recent test executions

```sql
SELECT
    run_id,
    run_date,
    run_type,
    instance_type,
    is_outlier,
    ROUND(queries_per_second, 2) as qps,
    ROUND(avg_latency_sec, 2) as avg,
    ROUND(p90_latency_sec, 2) as p90,
    ROUND(p99_latency_sec, 2) as p99,
    total_success,
    total_failed
FROM jmeter_runs_index
WHERE engine = 'e6data'
  AND cluster_size = 'S-2x2'
  AND benchmark = 'tpcds_29_1tb'
ORDER BY run_date DESC
LIMIT 20;
```

### 3. Best Runs (Lowest p90)

**Use Case:** Find best performing run for each concurrency level

```sql
WITH ranked_runs AS (
    SELECT
        run_type,
        run_id,
        run_date,
        instance_type,
        ROUND(queries_per_second, 2) as qps,
        ROUND(avg_latency_sec, 2) as avg_time,
        ROUND(p90_latency_sec, 2) as p90,
        ROUND(p95_latency_sec, 2) as p95,
        ROUND(p99_latency_sec, 2) as p99,
        total_success,
        ROW_NUMBER() OVER (PARTITION BY run_type, instance_type ORDER BY p90_latency_sec ASC) as rank
    FROM jmeter_runs_index
    WHERE run_type LIKE 'concurrency_%'
      AND is_outlier = 'no'
      AND engine = 'e6data'
      AND cluster_size = 'S-2x2'
      AND benchmark = 'tpcds_29_1tb'
)
SELECT *
FROM ranked_runs
WHERE rank = 1
ORDER BY run_type, instance_type;
```

---

## Performance Analysis

### 4. Throughput Analysis

**Use Case:** Compare queries-per-second across runs

```sql
SELECT
    run_type,
    run_id,
    run_date,
    ROUND(queries_per_second, 2) as qps,
    ROUND(queries_per_minute, 2) as qpm,
    ROUND(avg_latency_sec, 2) as avg_time,
    ROUND(total_time_taken_sec / 60, 1) as test_duration_min,
    total_success,
    is_outlier
FROM jmeter_runs_index
WHERE is_outlier = 'no'
  AND engine = 'e6data'
  AND cluster_size = 'S-2x2'
  AND benchmark = 'tpcds_29_1tb'
  AND run_type LIKE 'concurrency_%'
ORDER BY run_type, queries_per_second DESC;
```

### 5. Concurrency Scaling Analysis

**Use Case:** See how performance scales with increasing concurrency

```sql
SELECT
    run_type,
    COUNT(*) as valid_runs,
    ROUND(AVG(queries_per_second), 2) as avg_qps,
    ROUND(AVG(avg_latency_sec), 2) as avg_latency,
    ROUND(AVG(p90_latency_sec), 2) as avg_p90,
    ROUND(AVG(p95_latency_sec), 2) as avg_p95,
    ROUND(AVG(p99_latency_sec), 2) as avg_p99,
    ROUND(MIN(p90_latency_sec), 2) as best_p90,
    ROUND(MAX(p90_latency_sec), 2) as worst_p90
FROM jmeter_runs_index
WHERE is_outlier = 'no'
  AND engine = 'e6data'
  AND cluster_size = 'S-2x2'
  AND benchmark = 'tpcds_29_1tb'
  AND run_type LIKE 'concurrency_%'
GROUP BY run_type
ORDER BY run_type;
```

### 6. Performance Summary by Configuration

**Use Case:** Aggregated statistics for each run type and instance type

```sql
SELECT
    run_type,
    instance_type,
    COUNT(*) as total_runs,
    COUNT(CASE WHEN is_outlier = 'no' THEN 1 END) as valid_runs,
    COUNT(CASE WHEN is_outlier = 'yes' THEN 1 END) as outlier_runs,
    ROUND(AVG(CASE WHEN is_outlier = 'no' THEN queries_per_second END), 2) as avg_qps,
    ROUND(AVG(CASE WHEN is_outlier = 'no' THEN avg_latency_sec END), 2) as avg_of_avg,
    ROUND(AVG(CASE WHEN is_outlier = 'no' THEN p90_latency_sec END), 2) as avg_p90,
    ROUND(AVG(CASE WHEN is_outlier = 'no' THEN p95_latency_sec END), 2) as avg_p95,
    ROUND(AVG(CASE WHEN is_outlier = 'no' THEN p99_latency_sec END), 2) as avg_p99,
    ROUND(MIN(CASE WHEN is_outlier = 'no' THEN p90_latency_sec END), 2) as best_p90,
    ROUND(MAX(CASE WHEN is_outlier = 'no' THEN p90_latency_sec END), 2) as worst_p90,
    ROUND(STDDEV(CASE WHEN is_outlier = 'no' THEN p90_latency_sec END), 2) as p90_stddev
FROM jmeter_runs_index
WHERE engine = 'e6data'
  AND cluster_size = 'S-2x2'
  AND benchmark = 'tpcds_29_1tb'
GROUP BY run_type, instance_type
ORDER BY run_type, instance_type;
```

### 7. Latency Percentile Analysis

**Use Case:** Deep dive into latency distribution

```sql
SELECT
    run_type,
    run_id,
    run_date,
    instance_type,
    ROUND(avg_latency_sec, 2) as avg,
    ROUND(median_latency_sec, 2) as median,
    ROUND(p50_latency_sec, 2) as p50,
    ROUND(p90_latency_sec, 2) as p90,
    ROUND(p95_latency_sec, 2) as p95,
    ROUND(p99_latency_sec, 2) as p99,
    ROUND(max_latency_sec, 2) as max,
    -- Percentile gaps
    ROUND(p90_latency_sec - p50_latency_sec, 2) as p50_to_p90_gap,
    ROUND(p99_latency_sec - p90_latency_sec, 2) as p90_to_p99_gap
FROM jmeter_runs_index
WHERE is_outlier = 'no'
  AND engine = 'e6data'
  AND cluster_size = 'S-2x2'
  AND benchmark = 'tpcds_29_1tb'
ORDER BY run_type, run_date DESC;
```

---

## Outlier Management

### 8. Show All Runs (Including Outliers)

**Use Case:** Review all runs including those marked as outliers

```sql
SELECT
    run_type,
    run_id,
    run_date,
    is_outlier,
    ROUND(avg_latency_sec, 2) as avg_time,
    ROUND(p90_latency_sec, 2) as p90,
    ROUND(p95_latency_sec, 2) as p95,
    ROUND(p99_latency_sec, 2) as p99,
    total_success,
    total_failed,
    error_rate_pct
FROM jmeter_runs_index
WHERE engine = 'e6data'
  AND cluster_size = 'S-2x2'
  AND benchmark = 'tpcds_29_1tb'
ORDER BY run_type, is_outlier DESC, run_date DESC;
```

### 9. Outliers Only

**Use Case:** Focus on runs that were marked as outliers

```sql
SELECT
    run_type,
    run_id,
    run_date,
    instance_type,
    ROUND(avg_latency_sec, 2) as avg_time,
    ROUND(p90_latency_sec, 2) as p90,
    ROUND(p99_latency_sec, 2) as p99,
    total_failed,
    error_rate_pct,
    cluster_hostname
FROM jmeter_runs_index
WHERE is_outlier = 'yes'
  AND engine = 'e6data'
  AND cluster_size = 'S-2x2'
  AND benchmark = 'tpcds_29_1tb'
ORDER BY run_date DESC;
```

### 10. Outlier Statistics

**Use Case:** Summary of outlier counts per run type

```sql
SELECT
    run_type,
    COUNT(*) as total_runs,
    COUNT(CASE WHEN is_outlier = 'no' THEN 1 END) as valid_runs,
    COUNT(CASE WHEN is_outlier = 'yes' THEN 1 END) as outlier_runs,
    ROUND(100.0 * COUNT(CASE WHEN is_outlier = 'yes' THEN 1 END) / COUNT(*), 1) as outlier_pct
FROM jmeter_runs_index
WHERE engine = 'e6data'
  AND cluster_size = 'S-2x2'
  AND benchmark = 'tpcds_29_1tb'
GROUP BY run_type
ORDER BY run_type;
```

---

## Comparison Queries

### 11. Compare Two Engines (Same Cluster Size)

**Use Case:** Compare e6data vs DBR performance

```sql
SELECT
    engine,
    run_type,
    COUNT(*) as runs,
    ROUND(AVG(queries_per_second), 2) as avg_qps,
    ROUND(AVG(avg_latency_sec), 2) as avg_latency,
    ROUND(AVG(p90_latency_sec), 2) as avg_p90,
    ROUND(AVG(p99_latency_sec), 2) as avg_p99
FROM jmeter_runs_index
WHERE is_outlier = 'no'
  AND cluster_size = 'S-2x2'
  AND benchmark = 'tpcds_29_1tb'
  AND run_type LIKE 'concurrency_%'
GROUP BY engine, run_type
ORDER BY run_type, engine;
```

### 12. Compare Instance Types

**Use Case:** See performance difference between instance types

```sql
SELECT
    instance_type,
    run_type,
    COUNT(*) as runs,
    ROUND(AVG(avg_latency_sec), 2) as avg_latency,
    ROUND(AVG(p90_latency_sec), 2) as avg_p90,
    ROUND(AVG(p99_latency_sec), 2) as avg_p99,
    ROUND(MIN(p90_latency_sec), 2) as best_p90
FROM jmeter_runs_index
WHERE is_outlier = 'no'
  AND engine = 'e6data'
  AND cluster_size = 'S-2x2'
  AND benchmark = 'tpcds_29_1tb'
GROUP BY instance_type, run_type
ORDER BY run_type, instance_type;
```

### 13. Before/After Comparison

**Use Case:** Compare runs before and after a specific date

```sql
WITH before AS (
    SELECT
        run_type,
        ROUND(AVG(p90_latency_sec), 2) as avg_p90_before
    FROM jmeter_runs_index
    WHERE is_outlier = 'no'
      AND run_date < '2025-11-10'
      AND engine = 'e6data'
      AND cluster_size = 'S-2x2'
    GROUP BY run_type
),
after AS (
    SELECT
        run_type,
        ROUND(AVG(p90_latency_sec), 2) as avg_p90_after
    FROM jmeter_runs_index
    WHERE is_outlier = 'no'
      AND run_date >= '2025-11-10'
      AND engine = 'e6data'
      AND cluster_size = 'S-2x2'
    GROUP BY run_type
)
SELECT
    before.run_type,
    avg_p90_before,
    avg_p90_after,
    ROUND(avg_p90_after - avg_p90_before, 2) as p90_change,
    ROUND(100.0 * (avg_p90_after - avg_p90_before) / avg_p90_before, 1) as pct_change
FROM before
JOIN after ON before.run_type = after.run_type
ORDER BY before.run_type;
```

---

## Data Validation

### 14. Verify New Fields After Migration

**Use Case:** Check that all new fields are populated correctly

```sql
SELECT
    run_id,
    run_date,
    -- New fields
    is_outlier,
    ROUND(queries_per_second, 2) as qps,
    ROUND(queries_per_minute, 2) as qpm,
    ROUND(total_time_taken_sec, 2) as test_duration_sec,
    -- Existing fields
    ROUND(avg_latency_sec, 2) as avg_time,
    ROUND(p99_latency_sec, 2) as p99,
    total_success
FROM jmeter_runs_index
WHERE engine = 'e6data'
  AND cluster_size = 'S-2x2'
ORDER BY run_date DESC
LIMIT 10;
```

### 15. Check for NULL or Missing Values

**Use Case:** Data quality check

```sql
SELECT
    'queries_per_second' as field,
    COUNT(*) as total_rows,
    COUNT(queries_per_second) as non_null,
    COUNT(*) - COUNT(queries_per_second) as null_count
FROM jmeter_runs_index
WHERE engine = 'e6data'

UNION ALL

SELECT
    'is_outlier' as field,
    COUNT(*) as total_rows,
    COUNT(is_outlier) as non_null,
    COUNT(*) - COUNT(is_outlier) as null_count
FROM jmeter_runs_index
WHERE engine = 'e6data'

UNION ALL

SELECT
    'instance_type' as field,
    COUNT(*) as total_rows,
    COUNT(instance_type) as non_null,
    COUNT(*) - COUNT(instance_type) as null_count
FROM jmeter_runs_index
WHERE engine = 'e6data';
```

### 16. Timestamped Files Verification

**Use Case:** Verify that append behavior is working (multiple files per partition)

```sql
SELECT
    run_type,
    COUNT(DISTINCT run_id) as total_runs,
    COUNT(DISTINCT CASE WHEN is_outlier = 'no' THEN run_id END) as valid_runs,
    COUNT(DISTINCT CASE WHEN is_outlier = 'yes' THEN run_id END) as outlier_runs,
    MIN(run_date) as oldest_run,
    MAX(run_date) as latest_run,
    DATEDIFF(day, MIN(run_date), MAX(run_date)) as days_span
FROM jmeter_runs_index
WHERE engine = 'e6data'
  AND cluster_size = 'S-2x2'
  AND benchmark = 'tpcds_29_1tb'
GROUP BY run_type
ORDER BY run_type;
```

---

## Advanced Analytics

### 17. Performance Trend Over Time

**Use Case:** See if performance is improving or degrading

```sql
SELECT
    DATE_TRUNC('day', run_date) as test_day,
    run_type,
    COUNT(*) as runs,
    ROUND(AVG(p90_latency_sec), 2) as avg_p90,
    ROUND(AVG(p99_latency_sec), 2) as avg_p99,
    ROUND(AVG(queries_per_second), 2) as avg_qps
FROM jmeter_runs_index
WHERE is_outlier = 'no'
  AND engine = 'e6data'
  AND cluster_size = 'S-2x2'
  AND benchmark = 'tpcds_29_1tb'
GROUP BY DATE_TRUNC('day', run_date), run_type
ORDER BY test_day DESC, run_type;
```

### 18. Statistical Outlier Detection (Beyond Manual Marking)

**Use Case:** Find runs that are statistical outliers even if not manually marked

```sql
WITH stats AS (
    SELECT
        run_type,
        AVG(p90_latency_sec) as mean_p90,
        STDDEV(p90_latency_sec) as stddev_p90
    FROM jmeter_runs_index
    WHERE is_outlier = 'no'
      AND engine = 'e6data'
      AND cluster_size = 'S-2x2'
    GROUP BY run_type
)
SELECT
    r.run_id,
    r.run_date,
    r.run_type,
    r.is_outlier as manual_outlier,
    ROUND(r.p90_latency_sec, 2) as p90,
    ROUND(s.mean_p90, 2) as mean_p90,
    ROUND(s.stddev_p90, 2) as stddev_p90,
    ROUND((r.p90_latency_sec - s.mean_p90) / s.stddev_p90, 2) as z_score,
    CASE
        WHEN ABS(r.p90_latency_sec - s.mean_p90) > 2 * s.stddev_p90 THEN 'statistical_outlier'
        ELSE 'normal'
    END as statistical_status
FROM jmeter_runs_index r
JOIN stats s ON r.run_type = s.run_type
WHERE r.engine = 'e6data'
  AND r.cluster_size = 'S-2x2'
ORDER BY r.run_type, z_score DESC;
```

### 19. Performance Rating Distribution

**Use Case:** See distribution of performance ratings

```sql
SELECT
    performance_rating,
    COUNT(*) as runs,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) as pct,
    ROUND(AVG(p90_latency_sec), 2) as avg_p90
FROM jmeter_runs_index
WHERE is_outlier = 'no'
  AND engine = 'e6data'
  AND cluster_size = 'S-2x2'
  AND benchmark = 'tpcds_29_1tb'
GROUP BY performance_rating
ORDER BY
    CASE performance_rating
        WHEN 'Excellent' THEN 1
        WHEN 'Good' THEN 2
        WHEN 'Fair' THEN 3
        WHEN 'Poor' THEN 4
        ELSE 5
    END;
```

### 20. Cluster Hostname Analysis

**Use Case:** See if specific clusters perform differently

```sql
SELECT
    cluster_hostname,
    instance_type,
    COUNT(*) as runs,
    ROUND(AVG(avg_latency_sec), 2) as avg_latency,
    ROUND(AVG(p90_latency_sec), 2) as avg_p90,
    ROUND(AVG(p99_latency_sec), 2) as avg_p99,
    ROUND(STDDEV(p90_latency_sec), 2) as p90_stddev
FROM jmeter_runs_index
WHERE is_outlier = 'no'
  AND engine = 'e6data'
  AND cluster_size = 'S-2x2'
  AND benchmark = 'tpcds_29_1tb'
GROUP BY cluster_hostname, instance_type
ORDER BY avg_p90;
```

---

## Utility Queries

### 21. Table Schema / Column List

**Use Case:** See all available columns and their types

```sql
DESCRIBE jmeter_runs_index;
```

### 22. Sample Data

**Use Case:** Quick look at raw data structure

```sql
SELECT *
FROM jmeter_runs_index
WHERE engine = 'e6data'
  AND cluster_size = 'S-2x2'
LIMIT 5;
```

### 23. Run Count by Partition

**Use Case:** Verify data distribution across partitions

```sql
SELECT
    engine,
    cluster_size,
    benchmark,
    run_type,
    COUNT(*) as runs
FROM jmeter_runs_index
GROUP BY engine, cluster_size, benchmark, run_type
ORDER BY engine, cluster_size, benchmark, run_type;
```

### 24. Latest Run per Configuration

**Use Case:** Find the most recent run for each configuration

```sql
WITH latest_runs AS (
    SELECT
        engine,
        cluster_size,
        benchmark,
        run_type,
        MAX(run_date) as latest_date
    FROM jmeter_runs_index
    GROUP BY engine, cluster_size, benchmark, run_type
)
SELECT
    r.engine,
    r.cluster_size,
    r.benchmark,
    r.run_type,
    r.run_id,
    r.run_date,
    ROUND(r.p90_latency_sec, 2) as p90,
    r.is_outlier
FROM jmeter_runs_index r
JOIN latest_runs l
    ON r.engine = l.engine
    AND r.cluster_size = l.cluster_size
    AND r.benchmark = l.benchmark
    AND r.run_type = l.run_type
    AND r.run_date = l.latest_date
ORDER BY r.engine, r.cluster_size, r.run_type;
```

### 25. Export to CSV Format

**Use Case:** Prepare data for export (Athena automatically formats as CSV when downloading)

```sql
-- This query formats nicely for CSV export
SELECT
    engine,
    cluster_size,
    instance_type,
    benchmark,
    run_type,
    run_id,
    run_date,
    queries_per_second as qps,
    avg_latency_sec,
    p50_latency_sec,
    p90_latency_sec,
    p95_latency_sec,
    p99_latency_sec,
    total_time_taken_sec,
    total_success,
    total_failed,
    is_outlier
FROM jmeter_runs_index
WHERE is_outlier = 'no'
  AND engine = 'e6data'
  AND cluster_size = 'S-2x2'
  AND benchmark = 'tpcds_29_1tb'
ORDER BY run_type, run_date DESC;
```

---

## Query Generator Tool

### Automated Query Generation

Instead of manually writing queries, use the query generator script:

```bash
# Generate all parameterized queries for a specific configuration
./utilities/athena/generate_report_queries.sh e6data S-2x2 tpcds_29_1tb

# Output location: reports/athena_reports_YYYYMMDD_HHMMSS/
```

**Generated Files:**
- `01_valid_runs.sql` - Valid runs only
- `02_throughput_analysis.sql` - QPS analysis
- `03_best_runs.sql` - Best run per concurrency
- `04_concurrency_scaling.sql` - Scaling analysis
- `05_outlier_detection.sql` - All runs + outliers
- `06_performance_summary.sql` - Aggregated stats
- `07_recent_runs.sql` - Last 20 runs
- `08_file_verification.sql` - Verify timestamped files
- `README.md` - Usage guide

**Custom Output Directory:**
```bash
./utilities/athena/generate_report_queries.sh e6data S-2x2 tpcds_29_1tb reports/my_analysis
```

---

## Key Metrics Reference

| Metric | Description | Source |
|--------|-------------|--------|
| `qps` / `queries_per_second` | Queries executed per second | JMeter summary |
| `qpm` / `queries_per_minute` | Queries executed per minute | JMeter summary |
| `avg_latency_sec` | Average latency (seconds) | AggregateReport.csv |
| `p50_latency_sec` | 50th percentile latency | AggregateReport.csv |
| `p90_latency_sec` | 90th percentile latency | AggregateReport.csv |
| `p95_latency_sec` | 95th percentile latency | AggregateReport.csv |
| `p99_latency_sec` | 99th percentile latency | AggregateReport.csv |
| `total_time_taken_sec` | Actual test duration (wall-clock) | JMeter summary |
| `is_outlier` | Manual outlier flag ("yes" / "no") | Metadata (editable) |
| `instance_type` | EC2 instance type | Cluster metadata |
| `cluster_hostname` | Cluster endpoint | Connection properties |
| `performance_rating` | Overall rating (Excellent/Good/Fair/Poor) | Calculated |

---

## Best Practices

1. **Always filter by `is_outlier = 'no'`** for analysis queries
2. **Use specific engine/cluster/benchmark filters** to avoid scanning all data
3. **Round decimal values** for readability (`ROUND(value, 2)`)
4. **Include run_type in GROUP BY** for concurrency-level analysis
5. **Use window functions** (ROW_NUMBER, RANK) for best/worst run queries
6. **Export results as CSV** directly from Athena console using "Download results"
7. **Leverage partitions** (engine, cluster_size, benchmark, run_type) for faster queries

---

## Related Documentation

- **Query Generator**: `utilities/athena/generate_report_queries.sh`
- **Full Query Collection**: `utilities/athena/ATHENA_QUERIES_UPDATED.sql`
- **Append Behavior**: `utilities/athena/APPEND_BEHAVIOR_README.md`
- **Athena Setup**: `utilities/athena/ATHENA_SYNC_GUIDE.md`
- **Table Schema**: `utilities/athena/setup_athena_runs_index.sql`

---

## Need Help?

- **Generate custom queries**: Use `./utilities/athena/generate_report_queries.sh`
- **Check data quality**: Run verification queries (#14, #15, #16)
- **Find outliers**: Use outlier management queries (#8, #9, #10)
- **Compare performance**: Use comparison queries (#11, #12, #13)
