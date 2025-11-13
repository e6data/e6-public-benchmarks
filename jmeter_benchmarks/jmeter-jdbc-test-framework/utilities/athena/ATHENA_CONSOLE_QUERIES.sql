-- ============================================================================
-- SQL Queries for AWS Athena Console
-- Database: jmeter_analysis
-- Table: jmeter_runs_index
--
-- Copy and paste these queries into AWS Athena Query Editor
-- https://console.aws.amazon.com/athena/
-- ============================================================================

-- ============================================================================
-- 1. VIEW ALL RUNS (Latest 50)
-- ============================================================================
SELECT
    engine,
    run_id,
    run_date,
    cluster_size,
    instance_type,
    run_type,
    ROUND(p50_latency_sec, 2) as p50,
    ROUND(p90_latency_sec, 2) as p90,
    ROUND(p95_latency_sec, 2) as p95,
    ROUND(p99_latency_sec, 2) as p99,
    total_success,
    total_failed
FROM jmeter_analysis.jmeter_runs_index
ORDER BY engine, run_date DESC
LIMIT 50;


-- ============================================================================
-- 2. ENGINE COMPARISON (E6data vs Databricks)
-- ============================================================================
SELECT
    engine,
    cluster_size,
    run_type,
    instance_type,
    COUNT(*) as runs,
    ROUND(AVG(avg_latency_sec), 2) as avg_time,
    ROUND(AVG(p50_latency_sec), 2) as avg_p50,
    ROUND(AVG(p90_latency_sec), 2) as avg_p90,
    ROUND(AVG(p95_latency_sec), 2) as avg_p95,
    ROUND(AVG(p99_latency_sec), 2) as avg_p99,
    SUM(total_success) as total_success,
    SUM(total_failed) as total_failed
FROM jmeter_analysis.jmeter_runs_index
WHERE 1=1
GROUP BY engine, cluster_size, run_type, instance_type
ORDER BY cluster_size, run_type, engine, avg_p90;


-- ============================================================================
-- 3. INSTANCE TYPE COMPARISON (r6id vs r7iz)
-- ============================================================================
SELECT
    engine,
    instance_type,
    cluster_size,
    COUNT(*) as runs,
    ROUND(AVG(avg_latency_sec), 2) as avg_time,
    ROUND(AVG(p50_latency_sec), 2) as avg_p50,
    ROUND(AVG(p90_latency_sec), 2) as avg_p90,
    ROUND(AVG(p95_latency_sec), 2) as avg_p95,
    ROUND(AVG(p99_latency_sec), 2) as avg_p99,
    SUM(total_success) as total_success,
    SUM(total_failed) as total_failed,
    ROUND(MIN(p50_latency_sec), 2) as best_p50,
    ROUND(MIN(p95_latency_sec), 2) as best_p95,
    ROUND(MAX(p50_latency_sec), 2) as worst_p50,
    ROUND(MAX(p95_latency_sec), 2) as worst_p95
FROM jmeter_analysis.jmeter_runs_index
WHERE instance_type != 'unknown'
GROUP BY engine, instance_type, cluster_size
ORDER BY engine, cluster_size, avg_p50;


-- ============================================================================
-- 4. CONCURRENCY SCALING ANALYSIS
-- ============================================================================
WITH concurrency_nums AS (
    SELECT
        engine,
        CAST(REGEXP_EXTRACT(run_type, 'concurrency_(\\d+)', 1) AS INTEGER) as concurrency,
        run_type,
        cluster_size,
        instance_type,
        ROUND(AVG(avg_latency_sec), 2) as avg_time,
        ROUND(AVG(p50_latency_sec), 2) as avg_p50,
        ROUND(AVG(p90_latency_sec), 2) as avg_p90,
        ROUND(AVG(p95_latency_sec), 2) as avg_p95,
        ROUND(AVG(p99_latency_sec), 2) as avg_p99,
        SUM(total_success) as total_success,
        SUM(total_failed) as total_failed
    FROM jmeter_analysis.jmeter_runs_index
    WHERE run_type LIKE 'concurrency_%'
    GROUP BY engine, run_type, cluster_size, instance_type
)
SELECT
    engine,
    concurrency,
    cluster_size,
    instance_type,
    avg_time,
    avg_p50,
    avg_p90,
    avg_p95,
    avg_p99,
    total_success,
    total_failed
FROM concurrency_nums
ORDER BY engine, cluster_size, concurrency, instance_type;


-- ============================================================================
-- 5. CLUSTER SIZE COMPARISON
-- ============================================================================
SELECT
    engine,
    cluster_size,
    run_type,
    COUNT(*) as runs,
    ROUND(AVG(avg_latency_sec), 2) as avg_time,
    ROUND(AVG(p50_latency_sec), 2) as avg_p50,
    ROUND(AVG(p90_latency_sec), 2) as avg_p90,
    ROUND(AVG(p95_latency_sec), 2) as avg_p95,
    ROUND(AVG(p99_latency_sec), 2) as avg_p99,
    SUM(total_success) as total_success,
    SUM(total_failed) as total_failed
FROM jmeter_analysis.jmeter_runs_index
GROUP BY engine, cluster_size, run_type
ORDER BY engine, cluster_size, run_type;


-- ============================================================================
-- 6. BEST PERFORMING RUNS (Top 10 by p90)
-- ============================================================================
SELECT
    engine,
    run_id,
    run_date,
    cluster_size,
    instance_type,
    run_type,
    ROUND(avg_latency_sec, 2) as avg_time,
    ROUND(p50_latency_sec, 2) as p50,
    ROUND(p90_latency_sec, 2) as p90,
    ROUND(p95_latency_sec, 2) as p95,
    total_success
FROM jmeter_analysis.jmeter_runs_index
WHERE run_type LIKE 'concurrency_%'
ORDER BY p90_latency_sec ASC
LIMIT 10;


-- ============================================================================
-- 7. WORST PERFORMING RUNS (Bottom 10 by p90)
-- ============================================================================
SELECT
    engine,
    run_id,
    run_date,
    cluster_size,
    instance_type,
    run_type,
    ROUND(avg_latency_sec, 2) as avg_time,
    ROUND(p50_latency_sec, 2) as p50,
    ROUND(p90_latency_sec, 2) as p90,
    ROUND(p95_latency_sec, 2) as p95,
    total_success
FROM jmeter_analysis.jmeter_runs_index
WHERE run_type LIKE 'concurrency_%'
ORDER BY p90_latency_sec DESC
LIMIT 10;


-- ============================================================================
-- 8. LATEST RUN FOR EACH CONFIGURATION
-- ============================================================================
WITH ranked_runs AS (
    SELECT
        engine,
        cluster_size,
        run_type,
        instance_type,
        run_id,
        run_date,
        ROUND(avg_latency_sec, 2) as avg_time,
        ROUND(p90_latency_sec, 2) as p90,
        ROUND(p95_latency_sec, 2) as p95,
        ROW_NUMBER() OVER (PARTITION BY engine, cluster_size, run_type, instance_type ORDER BY run_date DESC) as rn
    FROM jmeter_analysis.jmeter_runs_index
)
SELECT
    engine,
    cluster_size,
    run_type,
    instance_type,
    run_id,
    run_date,
    avg_time,
    p90,
    p95
FROM ranked_runs
WHERE rn = 1
ORDER BY engine, cluster_size, run_type;


-- ============================================================================
-- 9. FILTER: E6DATA ONLY
-- ============================================================================
SELECT
    engine,
    cluster_size,
    instance_type,
    run_type,
    COUNT(*) as runs,
    ROUND(AVG(p90_latency_sec), 2) as avg_p90,
    ROUND(AVG(p95_latency_sec), 2) as avg_p95,
    ROUND(MIN(p90_latency_sec), 2) as best_p90,
    ROUND(MAX(p90_latency_sec), 2) as worst_p90
FROM jmeter_analysis.jmeter_runs_index
WHERE engine = 'e6data'
GROUP BY engine, cluster_size, instance_type, run_type
ORDER BY cluster_size, run_type, instance_type;


-- ============================================================================
-- 10. FILTER: DATABRICKS ONLY
-- ============================================================================
SELECT
    engine,
    cluster_size,
    run_type,
    COUNT(*) as runs,
    ROUND(AVG(avg_latency_sec), 2) as avg_time,
    ROUND(AVG(p90_latency_sec), 2) as avg_p90,
    ROUND(AVG(p95_latency_sec), 2) as avg_p95,
    ROUND(MIN(p90_latency_sec), 2) as best_p90,
    ROUND(MAX(p90_latency_sec), 2) as worst_p90
FROM jmeter_analysis.jmeter_runs_index
WHERE engine = 'databricks'
GROUP BY engine, cluster_size, run_type
ORDER BY cluster_size, run_type;


-- ============================================================================
-- 11. FILTER: SPECIFIC CLUSTER (e.g., M-4x4)
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
    ROUND(p95_latency_sec, 2) as p95
FROM jmeter_analysis.jmeter_runs_index
WHERE cluster_size = 'M-4x4'
ORDER BY run_date DESC;


-- ============================================================================
-- 12. FILTER: SPECIFIC CONCURRENCY (e.g., concurrency_4)
-- ============================================================================
SELECT
    engine,
    cluster_size,
    instance_type,
    run_id,
    run_date,
    ROUND(avg_latency_sec, 2) as avg_time,
    ROUND(p50_latency_sec, 2) as p50,
    ROUND(p90_latency_sec, 2) as p90,
    ROUND(p95_latency_sec, 2) as p95,
    total_success
FROM jmeter_analysis.jmeter_runs_index
WHERE run_type = 'concurrency_4'
ORDER BY p90_latency_sec ASC;


-- ============================================================================
-- 13. COUNT RUNS BY ENGINE/CLUSTER
-- ============================================================================
SELECT
    engine,
    cluster_size,
    COUNT(*) as total_runs,
    COUNT(DISTINCT run_type) as distinct_run_types,
    MIN(run_date) as first_run,
    MAX(run_date) as latest_run
FROM jmeter_analysis.jmeter_runs_index
GROUP BY engine, cluster_size
ORDER BY engine, cluster_size;


-- ============================================================================
-- 14. EXPORT FOR EXCEL/CSV (All columns, no formatting)
-- ============================================================================
SELECT *
FROM jmeter_analysis.jmeter_runs_index
ORDER BY engine, cluster_size, run_date DESC;


-- ============================================================================
-- 15. CUSTOM: E6data M-4x4 r7iz Performance Trend
-- ============================================================================
SELECT
    run_id,
    run_date,
    run_type,
    ROUND(avg_latency_sec, 2) as avg_time,
    ROUND(p50_latency_sec, 2) as p50,
    ROUND(p90_latency_sec, 2) as p90,
    ROUND(p95_latency_sec, 2) as p95,
    ROUND(p99_latency_sec, 2) as p99,
    total_success
FROM jmeter_analysis.jmeter_runs_index
WHERE engine = 'e6data'
  AND cluster_size = 'M-4x4'
  AND instance_type = 'r7iz.8xlarge'
ORDER BY run_date DESC;
