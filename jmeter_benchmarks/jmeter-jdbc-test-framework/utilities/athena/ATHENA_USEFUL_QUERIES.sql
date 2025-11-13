-- ============================================================================
-- USEFUL ATHENA QUERIES - Individual Run Level Analysis
-- These queries show EACH RUN separately (no averaging!)
-- ============================================================================

-- ============================================================================
-- 1. ALL RUNS - Individual Run Performance (Most Useful!)
-- Shows every single run with all metrics - use this to find best/worst
-- ============================================================================
SELECT
    engine,
    cluster_size,
    instance_type,
    benchmark,
    run_type,
    run_id,
    run_date,
    ROUND(avg_latency_sec, 2) as avg_time,
    ROUND(p50_latency_sec, 2) as p50,
    ROUND(p90_latency_sec, 2) as p90,
    ROUND(p95_latency_sec, 2) as p95,
    ROUND(p99_latency_sec, 2) as p99,
    total_success,
    total_failed,
    error_rate_pct
FROM jmeter_analysis.jmeter_runs_index
ORDER BY engine, cluster_size, benchmark, run_type, run_date DESC;


-- ============================================================================
-- 2. E6DATA M-4x4 - ALL Individual Runs (No Averaging!)
-- Compare each run_id for same concurrency level
-- ============================================================================
SELECT
    instance_type,
    benchmark,
    run_type,
    run_id,
    run_date,
    ROUND(avg_latency_sec, 2) as avg_time,
    ROUND(p50_latency_sec, 2) as p50,
    ROUND(p90_latency_sec, 2) as p90,
    ROUND(p95_latency_sec, 2) as p95,
    ROUND(p99_latency_sec, 2) as p99,
    total_success,
    total_failed
FROM jmeter_analysis.jmeter_runs_index
WHERE engine = 'e6data'
  AND cluster_size = 'M-4x4'
ORDER BY benchmark, run_type, instance_type, run_date DESC;


-- ============================================================================
-- 3. FIND BEST RUN for Each Configuration
-- Shows the single best run (lowest p90) for each engine/cluster/benchmark/concurrency/instance
-- ============================================================================
WITH ranked_runs AS (
    SELECT
        engine,
        cluster_size,
        instance_type,
        benchmark,
        run_type,
        run_id,
        run_date,
        ROUND(avg_latency_sec, 2) as avg_time,
        ROUND(p50_latency_sec, 2) as p50,
        ROUND(p90_latency_sec, 2) as p90,
        ROUND(p95_latency_sec, 2) as p95,
        ROUND(p99_latency_sec, 2) as p99,
        total_success,
        ROW_NUMBER() OVER (PARTITION BY engine, cluster_size, instance_type, benchmark, run_type ORDER BY p90_latency_sec ASC) as rank
    FROM jmeter_analysis.jmeter_runs_index
    WHERE run_type LIKE 'concurrency_%'
)
SELECT
    engine,
    cluster_size,
    instance_type,
    benchmark,
    run_type,
    run_id,
    run_date,
    avg_time,
    p50,
    p90,
    p95,
    p99,
    total_success
FROM ranked_runs
WHERE rank = 1
ORDER BY engine, cluster_size, benchmark, run_type, instance_type;


-- ============================================================================
-- 4. FIND WORST RUN for Each Configuration
-- Shows the single worst run (highest p90) for each config
-- ============================================================================
WITH ranked_runs AS (
    SELECT
        engine,
        cluster_size,
        instance_type,
        run_type,
        run_id,
        run_date,
        ROUND(avg_latency_sec, 2) as avg_time,
        ROUND(p50_latency_sec, 2) as p50,
        ROUND(p90_latency_sec, 2) as p90,
        ROUND(p95_latency_sec, 2) as p95,
        ROUND(p99_latency_sec, 2) as p99,
        total_success,
        ROW_NUMBER() OVER (PARTITION BY engine, cluster_size, instance_type, run_type ORDER BY p90_latency_sec DESC) as rank
    FROM jmeter_analysis.jmeter_runs_index
    WHERE run_type LIKE 'concurrency_%'
)
SELECT
    engine,
    cluster_size,
    instance_type,
    run_type,
    run_id,
    run_date,
    avg_time,
    p50,
    p90,
    p95,
    p99,
    total_success
FROM ranked_runs
WHERE rank = 1
ORDER BY engine, cluster_size, run_type, instance_type;


-- ============================================================================
-- 5. COMPARE ALL RUNS for Specific Configuration
-- Example: E6data M-4x4 concurrency_4 with r7iz.8xlarge
-- Shows ALL runs side-by-side (no averaging!) so you can see which was best
-- ============================================================================
SELECT
    run_id,
    run_date,
    ROUND(avg_latency_sec, 2) as avg_time,
    ROUND(p50_latency_sec, 2) as p50,
    ROUND(p90_latency_sec, 2) as p90,
    ROUND(p95_latency_sec, 2) as p95,
    ROUND(p99_latency_sec, 2) as p99,
    ROUND(max_latency_sec, 2) as max,
    total_success,
    total_failed,
    error_rate_pct
FROM jmeter_analysis.jmeter_runs_index
WHERE engine = 'e6data'
  AND cluster_size = 'M-4x4'
  AND run_type = 'concurrency_4'
  AND instance_type = 'r7iz.8xlarge'
ORDER BY run_date DESC;


-- ============================================================================
-- 6. PERFORMANCE TREND Over Time
-- See how performance changed across runs for specific config
-- ============================================================================
SELECT
    run_id,
    run_date,
    engine,
    cluster_size,
    instance_type,
    run_type,
    ROUND(avg_latency_sec, 2) as avg_time,
    ROUND(p90_latency_sec, 2) as p90,
    ROUND(p95_latency_sec, 2) as p95,
    total_success
FROM jmeter_analysis.jmeter_runs_index
WHERE engine = 'e6data'
  AND cluster_size = 'M-4x4'
  AND run_type = 'concurrency_4'
ORDER BY run_date ASC;


-- ============================================================================
-- 7. BEST vs LATEST RUN (Side by Side)
-- Compare best historical run with most recent run
-- ============================================================================
WITH best_run AS (
    SELECT
        'BEST' as type,
        engine,
        cluster_size,
        instance_type,
        run_type,
        run_id,
        run_date,
        ROUND(avg_latency_sec, 2) as avg_time,
        ROUND(p90_latency_sec, 2) as p90,
        ROUND(p95_latency_sec, 2) as p95,
        total_success
    FROM jmeter_analysis.jmeter_runs_index
    WHERE engine = 'e6data'
      AND cluster_size = 'M-4x4'
      AND run_type = 'concurrency_4'
      AND instance_type = 'r7iz.8xlarge'
    ORDER BY p90_latency_sec ASC
    LIMIT 1
),
latest_run AS (
    SELECT
        'LATEST' as type,
        engine,
        cluster_size,
        instance_type,
        run_type,
        run_id,
        run_date,
        ROUND(avg_latency_sec, 2) as avg_time,
        ROUND(p90_latency_sec, 2) as p90,
        ROUND(p95_latency_sec, 2) as p95,
        total_success
    FROM jmeter_analysis.jmeter_runs_index
    WHERE engine = 'e6data'
      AND cluster_size = 'M-4x4'
      AND run_type = 'concurrency_4'
      AND instance_type = 'r7iz.8xlarge'
    ORDER BY run_date DESC
    LIMIT 1
)
SELECT * FROM best_run
UNION ALL
SELECT * FROM latest_run;


-- ============================================================================
-- 8. ALL RUNS GROUPED by Configuration (Shows Count per Config with Comprehensive Stats)
-- Use this to see how many runs you have for each config with best/worst metrics
-- ============================================================================
SELECT
    engine,
    cluster_size,
    instance_type,
    benchmark,
    run_type,
    COUNT(*) as num_runs,
    MIN(run_date) as first_run,
    MAX(run_date) as latest_run,
    ROUND(MIN(avg_latency_sec), 2) as best_avg_time,
    ROUND(MAX(avg_latency_sec), 2) as worst_avg_time,
    ROUND(MIN(p90_latency_sec), 2) as best_p90,
    ROUND(MAX(p90_latency_sec), 2) as worst_p90,
    ROUND(MIN(p95_latency_sec), 2) as best_p95,
    ROUND(MAX(p95_latency_sec), 2) as worst_p95,
    ROUND(MIN(p99_latency_sec), 2) as best_p99,
    ROUND(MAX(p99_latency_sec), 2) as worst_p99,
    SUM(total_success) as total_queries_run,
    SUM(total_failed) as total_failures
FROM jmeter_analysis.jmeter_runs_index
GROUP BY engine, cluster_size, instance_type, benchmark, run_type
HAVING COUNT(*) > 1  -- Only show configs with multiple runs
ORDER BY engine, cluster_size, benchmark, run_type, instance_type;


-- ============================================================================
-- 9. DETECT OUTLIERS / Bad Runs
-- Shows runs where p95 is significantly higher than p90 (potential issues)
-- ============================================================================
SELECT
    engine,
    cluster_size,
    instance_type,
    run_type,
    run_id,
    run_date,
    ROUND(p90_latency_sec, 2) as p90,
    ROUND(p95_latency_sec, 2) as p95,
    ROUND(p99_latency_sec, 2) as p99,
    ROUND((p95_latency_sec - p90_latency_sec) / p90_latency_sec * 100, 1) as p95_p90_diff_pct,
    total_success,
    total_failed
FROM jmeter_analysis.jmeter_runs_index
WHERE run_type LIKE 'concurrency_%'
  AND (p95_latency_sec - p90_latency_sec) / p90_latency_sec > 0.5  -- p95 is >50% higher than p90
ORDER BY (p95_latency_sec - p90_latency_sec) / p90_latency_sec DESC;


-- ============================================================================
-- 10. INSTANCE COMPARISON - Individual Runs (No Averaging!)
-- See EACH run for r6id vs r7iz side by side
-- ============================================================================
SELECT
    engine,
    cluster_size,
    run_type,
    instance_type,
    run_id,
    run_date,
    ROUND(avg_latency_sec, 2) as avg_time,
    ROUND(p50_latency_sec, 2) as p50,
    ROUND(p90_latency_sec, 2) as p90,
    ROUND(p95_latency_sec, 2) as p95,
    total_success
FROM jmeter_analysis.jmeter_runs_index
WHERE engine = 'e6data'
  AND instance_type IN ('r6id.8xlarge', 'r7iz.8xlarge')
ORDER BY engine, cluster_size, run_type, instance_type, run_date DESC;


-- ============================================================================
-- 11. EXPORT ALL RUNS (For Excel Analysis)
-- Download this as CSV and analyze in Excel/Python
-- ============================================================================
SELECT
    engine,
    cluster_size,
    instance_type,
    run_type,
    run_id,
    run_date,
    avg_latency_sec,
    p50_latency_sec,
    p90_latency_sec,
    p95_latency_sec,
    p99_latency_sec,
    max_latency_sec,
    min_latency_sec,
    total_success,
    total_failed,
    error_rate_pct,
    queries_per_minute,
    s3_path
FROM jmeter_analysis.jmeter_runs_index
ORDER BY engine, cluster_size, run_type, run_date DESC;


-- ============================================================================
-- 12. DATABRICKS vs E6DATA - Individual Runs (Fair Comparison)
-- Shows each run separately for same concurrency level
-- ============================================================================
SELECT
    engine,
    cluster_size,
    run_type,
    run_id,
    run_date,
    ROUND(avg_latency_sec, 2) as avg_time,
    ROUND(p50_latency_sec, 2) as p50,
    ROUND(p90_latency_sec, 2) as p90,
    ROUND(p95_latency_sec, 2) as p95,
    ROUND(p99_latency_sec, 2) as p99,
    total_success
FROM jmeter_analysis.jmeter_runs_index
WHERE run_type = 'concurrency_4'  -- Change this to compare different concurrency
ORDER BY engine, cluster_size, run_date DESC;


-- ============================================================================
-- 13. FILTER: Show Only Recent Runs (Last 7 days)
-- ============================================================================
SELECT
    engine,
    cluster_size,
    instance_type,
    run_type,
    run_id,
    run_date,
    ROUND(avg_latency_sec, 2) as avg_time,
    ROUND(p90_latency_sec, 2) as p90,
    ROUND(p95_latency_sec, 2) as p95,
    total_success
FROM jmeter_analysis.jmeter_runs_index
WHERE run_date >= DATE_ADD('day', -7, CURRENT_DATE)
ORDER BY run_date DESC;


-- ============================================================================
-- 14. FIND SPECIFIC RUN by run_id
-- ============================================================================
SELECT
    engine,
    cluster_size,
    instance_type,
    run_type,
    run_id,
    run_date,
    ROUND(avg_latency_sec, 2) as avg_time,
    ROUND(p50_latency_sec, 2) as p50,
    ROUND(p90_latency_sec, 2) as p90,
    ROUND(p95_latency_sec, 2) as p95,
    ROUND(p99_latency_sec, 2) as p99,
    ROUND(max_latency_sec, 2) as max,
    total_success,
    total_failed,
    error_rate_pct,
    queries_per_minute,
    s3_path
FROM jmeter_analysis.jmeter_runs_index
WHERE run_id = '20251102-105503';  -- Change this to your run_id


-- ============================================================================
-- 15. COMPARE TWO SPECIFIC RUNS (Side by Side)
-- ============================================================================
SELECT
    engine,
    cluster_size,
    instance_type,
    run_type,
    run_id,
    run_date,
    ROUND(avg_latency_sec, 2) as avg_time,
    ROUND(p50_latency_sec, 2) as p50,
    ROUND(p90_latency_sec, 2) as p90,
    ROUND(p95_latency_sec, 2) as p95,
    ROUND(p99_latency_sec, 2) as p99,
    total_success,
    total_failed
FROM jmeter_analysis.jmeter_runs_index
WHERE run_id IN ('20251102-091004', '20251102-105503')  -- Change these run_ids
ORDER BY run_date;
