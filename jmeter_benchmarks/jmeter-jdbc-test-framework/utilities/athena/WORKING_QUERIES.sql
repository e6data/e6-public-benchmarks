-- ============================================================================
-- ATHENA WORKING QUERIES - JMETER BENCHMARK ANALYSIS
-- ============================================================================
-- Database: default
-- Tables:
--   - jmeter_query_results (query-level performance data)
--   - jmeter_run_metadata (run configuration and cluster metadata)
-- ============================================================================

-- ============================================================================
-- CATEGORY 1: METADATA TABLE - RUN CONFIGURATION ANALYSIS
-- ============================================================================
-- Purpose: Analyze test configurations and cluster metadata
-- Note: Metadata table does NOT contain performance metrics
-- ============================================================================

-- 1A. List All Runs with Configuration Details
-- Shows run identifiers, cluster info, and test configuration
SELECT
    run_id,
    run_date,
    instance_type,
    estimated_cores,
    concurrent_threads,
    benchmark,
    test_plan_file,
    hold_period_sec,
    ramp_up_time_sec
FROM jmeter_run_metadata
WHERE engine = 'e6data'
  AND cluster_size = 'S-2x2'
ORDER BY run_date DESC
LIMIT 20;

-- 1B. Instance Type Inventory
-- Shows which instance types were used for testing
SELECT
    instance_type,
    COUNT(DISTINCT run_id) as total_runs,
    MIN(run_date) as first_run,
    MAX(run_date) as latest_run,
    AVG(estimated_cores) as avg_cores,
    AVG(concurrent_threads) as avg_concurrency
FROM jmeter_run_metadata
WHERE engine = 'e6data'
GROUP BY instance_type
ORDER BY total_runs DESC;

-- 1C. Test Configuration Summary by Concurrency
-- Analyzes test configurations grouped by concurrency level
SELECT
    concurrent_threads,
    COUNT(DISTINCT run_id) as run_count,
    COUNT(DISTINCT instance_type) as instance_types_tested,
    AVG(hold_period_sec) as avg_hold_period_sec,
    AVG(ramp_up_time_sec) as avg_ramp_up_sec
FROM jmeter_run_metadata
WHERE engine = 'e6data'
  AND cluster_size = 'S-2x2'
GROUP BY concurrent_threads
ORDER BY concurrent_threads;


-- ============================================================================
-- CATEGORY 2: RESULTS TABLE - SINGLE-RUN DEEP DIVE
-- ============================================================================
-- Purpose: Detailed query-level analysis for a specific test run
-- Limitation: Must specify specific run_id(s) in WHERE clause
-- ============================================================================

-- 2A. Top 10 Slowest Queries - Specific Run
-- IMPORTANT: Replace '20251117-072011' with your actual run_id
SELECT
    label as query_name,
    ROUND(CAST(elapsed_time_ms AS DOUBLE) / 1000.0, 2) as elapsed_sec,
    response_code,
    success,
    thread_name
FROM jmeter_query_results
WHERE run_id = '20251117-072011'
  AND elapsed_time_ms IS NOT NULL
ORDER BY elapsed_time_ms DESC
LIMIT 10;

-- 2B. Performance Summary - Specific Run
-- Calculate percentiles and averages for a single run
SELECT
    run_id,
    COUNT(*) as total_queries,
    ROUND(AVG(CAST(elapsed_time_ms AS DOUBLE)) / 1000.0, 2) as avg_sec,
    ROUND(APPROX_PERCENTILE(CAST(elapsed_time_ms AS DOUBLE) / 1000.0, 0.50), 2) as p50_sec,
    ROUND(APPROX_PERCENTILE(CAST(elapsed_time_ms AS DOUBLE) / 1000.0, 0.90), 2) as p90_sec,
    ROUND(APPROX_PERCENTILE(CAST(elapsed_time_ms AS DOUBLE) / 1000.0, 0.95), 2) as p95_sec,
    ROUND(APPROX_PERCENTILE(CAST(elapsed_time_ms AS DOUBLE) / 1000.0, 0.99), 2) as p99_sec,
    ROUND(MIN(CAST(elapsed_time_ms AS DOUBLE)) / 1000.0, 2) as min_sec,
    ROUND(MAX(CAST(elapsed_time_ms AS DOUBLE)) / 1000.0, 2) as max_sec,
    SUM(CASE WHEN success = 'true' THEN 1 ELSE 0 END) as success_count,
    ROUND(100.0 * SUM(CASE WHEN success = 'true' THEN 1 ELSE 0 END) / COUNT(*), 2) as success_pct
FROM jmeter_query_results
WHERE run_id = '20251117-072011'
  AND elapsed_time_ms IS NOT NULL
GROUP BY run_id;

-- 2C. Query-by-Query Breakdown - Specific Run
-- Performance stats aggregated by query name
SELECT
    label as query_name,
    COUNT(*) as execution_count,
    ROUND(AVG(CAST(elapsed_time_ms AS DOUBLE)) / 1000.0, 2) as avg_sec,
    ROUND(MIN(CAST(elapsed_time_ms AS DOUBLE)) / 1000.0, 2) as min_sec,
    ROUND(MAX(CAST(elapsed_time_ms AS DOUBLE)) / 1000.0, 2) as max_sec,
    ROUND(APPROX_PERCENTILE(CAST(elapsed_time_ms AS DOUBLE) / 1000.0, 0.95), 2) as p95_sec,
    SUM(CASE WHEN success = 'true' THEN 1 ELSE 0 END) as success_count,
    ROUND(100.0 * SUM(CASE WHEN success = 'true' THEN 1 ELSE 0 END) / COUNT(*), 2) as success_rate_pct
FROM jmeter_query_results
WHERE run_id = '20251117-072011'
  AND elapsed_time_ms IS NOT NULL
GROUP BY label
ORDER BY avg_sec DESC
LIMIT 20;

-- 2D. Latency Distribution - Specific Run
-- Shows query distribution across latency buckets
SELECT
    CAST(FLOOR(elapsed_time_ms / 1000) AS INTEGER) as latency_bucket_sec,
    COUNT(*) as query_count,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER(), 2) as percentage
FROM jmeter_query_results
WHERE run_id = '20251117-072011'
  AND elapsed_time_ms IS NOT NULL
GROUP BY CAST(FLOOR(elapsed_time_ms / 1000) AS INTEGER)
ORDER BY latency_bucket_sec;

-- 2E. Response Code Distribution - Specific Run
-- Analyze HTTP response codes
SELECT
    response_code,
    COUNT(*) as count,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER(), 2) as percentage
FROM jmeter_query_results
WHERE run_id = '20251117-072011'
  AND label IS NOT NULL
GROUP BY response_code
ORDER BY count DESC;


-- ============================================================================
-- CATEGORY 3: COMPARING SPECIFIC RUNS (2-5 runs)
-- ============================================================================
-- Purpose: Compare performance between specific test runs
-- Limitation: Must explicitly list run_ids in WHERE clause
-- ============================================================================

-- 3A. Compare Recent Runs - Summary Metrics
-- Replace run_ids with actual values from your tests
SELECT
    m.run_id,
    m.run_date,
    m.instance_type,
    m.concurrent_threads,
    COUNT(r.label) as total_queries,
    ROUND(AVG(CAST(r.elapsed_time_ms AS DOUBLE)) / 1000.0, 2) as avg_sec,
    ROUND(APPROX_PERCENTILE(CAST(r.elapsed_time_ms AS DOUBLE) / 1000.0, 0.99), 2) as p99_sec,
    SUM(CASE WHEN r.success = 'true' THEN 1 ELSE 0 END) as successful,
    ROUND(100.0 * SUM(CASE WHEN r.success = 'true' THEN 1 ELSE 0 END) / COUNT(*), 1) as success_pct
FROM jmeter_run_metadata m
JOIN jmeter_query_results r ON m.run_id = r.run_id
WHERE m.run_id IN ('20251117-072011', '20251114-075524', '20251113-143843')
  AND r.elapsed_time_ms IS NOT NULL
GROUP BY m.run_id, m.run_date, m.instance_type, m.concurrent_threads
ORDER BY m.run_date DESC;

-- 3B. Query-Level Comparison Across Runs
-- Compare specific queries across multiple runs
SELECT
    r.label as query_name,
    m.run_id,
    m.run_date,
    m.instance_type,
    COUNT(*) as execution_count,
    ROUND(AVG(CAST(r.elapsed_time_ms AS DOUBLE)) / 1000.0, 2) as avg_sec,
    ROUND(APPROX_PERCENTILE(CAST(r.elapsed_time_ms AS DOUBLE) / 1000.0, 0.95), 2) as p95_sec
FROM jmeter_run_metadata m
JOIN jmeter_query_results r ON m.run_id = r.run_id
WHERE m.run_id IN ('20251117-072011', '20251114-075524')
  AND r.elapsed_time_ms IS NOT NULL
GROUP BY r.label, m.run_id, m.run_date, m.instance_type
ORDER BY r.label, m.run_date DESC;

-- 3C. Instance Type Performance Comparison
-- Compare performance across different instance types for specific concurrency
SELECT
    m.instance_type,
    COUNT(DISTINCT m.run_id) as total_runs,
    COUNT(r.label) as total_queries,
    ROUND(AVG(CAST(r.elapsed_time_ms AS DOUBLE)) / 1000.0, 2) as avg_sec,
    ROUND(APPROX_PERCENTILE(CAST(r.elapsed_time_ms AS DOUBLE) / 1000.0, 0.90), 2) as p90_sec,
    ROUND(APPROX_PERCENTILE(CAST(r.elapsed_time_ms AS DOUBLE) / 1000.0, 0.99), 2) as p99_sec,
    ROUND(100.0 * SUM(CASE WHEN r.success = 'true' THEN 1 ELSE 0 END) / COUNT(*), 2) as success_pct
FROM jmeter_run_metadata m
JOIN jmeter_query_results r ON m.run_id = r.run_id
WHERE m.engine = 'e6data'
  AND m.cluster_size = 'S-2x2'
  AND m.concurrent_threads = 4
  AND r.run_type = 'concurrency_4'
  AND r.elapsed_time_ms IS NOT NULL
GROUP BY m.instance_type
ORDER BY avg_sec;


-- ============================================================================
-- CATEGORY 4: FINDING AVAILABLE RUNS
-- ============================================================================
-- Purpose: Discover which runs are available for analysis
-- ============================================================================

-- 4A. List All Available Runs
-- Shows all test runs with basic metadata
SELECT
    m.run_id,
    m.run_date,
    m.engine,
    m.cluster_size,
    m.instance_type,
    m.concurrent_threads,
    m.benchmark
FROM jmeter_run_metadata m
WHERE m.engine = 'e6data'
ORDER BY m.run_date DESC
LIMIT 50;

-- 4B. Runs by Date Range
-- Find runs within specific date range
SELECT
    m.run_id,
    m.run_date,
    m.instance_type,
    m.concurrent_threads,
    m.benchmark
FROM jmeter_run_metadata m
WHERE m.engine = 'e6data'
  AND m.run_date >= '2025-11-10'
  AND m.run_date <= '2025-11-18'
ORDER BY m.run_date DESC;

-- 4C. Latest Run Per Concurrency Level
-- Identifies most recent run for each concurrency level
SELECT
    m.concurrent_threads,
    MAX(m.run_id) as latest_run_id,
    MAX(m.run_date) as latest_run_date,
    MAX(m.instance_type) as instance_type
FROM jmeter_run_metadata m
WHERE m.engine = 'e6data'
  AND m.cluster_size = 'S-2x2'
  AND m.benchmark = 'tpcds_29_1tb'
GROUP BY m.concurrent_threads
ORDER BY m.concurrent_threads;


-- ============================================================================
-- CATEGORY 5: CONCURRENCY SCALING ANALYSIS
-- ============================================================================
-- Purpose: Analyze how performance changes with concurrency
-- Note: Requires specific run_ids for each concurrency level
-- ============================================================================

-- 5A. Concurrency Scaling - Manual Run Selection
-- Replace run_ids with actual values for different concurrency levels
-- This example assumes you have runs at concurrency 2, 4, 8, 12
WITH concurrency_runs AS (
    SELECT '20251117-072011' as run_id, 2 as concurrency UNION ALL
    SELECT '20251117-073015', 4 UNION ALL
    SELECT '20251117-074520', 8 UNION ALL
    SELECT '20251117-080125', 12
)
SELECT
    c.concurrency,
    COUNT(r.label) as total_queries,
    ROUND(AVG(CAST(r.elapsed_time_ms AS DOUBLE)) / 1000.0, 2) as avg_sec,
    ROUND(APPROX_PERCENTILE(CAST(r.elapsed_time_ms AS DOUBLE) / 1000.0, 0.50), 2) as p50_sec,
    ROUND(APPROX_PERCENTILE(CAST(r.elapsed_time_ms AS DOUBLE) / 1000.0, 0.90), 2) as p90_sec,
    ROUND(APPROX_PERCENTILE(CAST(r.elapsed_time_ms AS DOUBLE) / 1000.0, 0.99), 2) as p99_sec,
    SUM(CASE WHEN r.success = 'true' THEN 1 ELSE 0 END) as success_count
FROM concurrency_runs c
JOIN jmeter_query_results r ON c.run_id = r.run_id
WHERE r.elapsed_time_ms IS NOT NULL
GROUP BY c.concurrency
ORDER BY c.concurrency;


-- ============================================================================
-- CATEGORY 6: ADVANCED FILTERING AND ANALYSIS
-- ============================================================================
-- Purpose: More sophisticated query patterns
-- ============================================================================

-- 6A. Failed Queries Analysis - Specific Run
-- Identify and analyze query failures
SELECT
    label as query_name,
    response_code,
    response_message,
    ROUND(CAST(elapsed_time_ms AS DOUBLE) / 1000.0, 2) as elapsed_sec,
    thread_name
FROM jmeter_query_results
WHERE run_id = '20251117-072011'
  AND success = 'false'
ORDER BY elapsed_time_ms DESC;

-- 6B. Queries Exceeding Threshold - Specific Run
-- Find queries slower than threshold (e.g., 10 seconds)
SELECT
    label as query_name,
    ROUND(CAST(elapsed_time_ms AS DOUBLE) / 1000.0, 2) as elapsed_sec,
    success,
    response_code
FROM jmeter_query_results
WHERE run_id = '20251117-072011'
  AND elapsed_time_ms IS NOT NULL
  AND CAST(elapsed_time_ms AS DOUBLE) / 1000.0 > 10.0
ORDER BY elapsed_time_ms DESC;

-- 6C. Thread Execution Distribution - Specific Run
-- Analyze query distribution across JMeter threads
SELECT
    thread_name,
    COUNT(*) as queries_executed,
    ROUND(AVG(CAST(elapsed_time_ms AS DOUBLE)) / 1000.0, 2) as avg_sec,
    SUM(CASE WHEN success = 'true' THEN 1 ELSE 0 END) as successful
FROM jmeter_query_results
WHERE run_id = '20251117-072011'
  AND elapsed_time_ms IS NOT NULL
GROUP BY thread_name
ORDER BY thread_name;

-- 6D. Variance Analysis - Specific Run
-- Find queries with high performance variance
SELECT
    label as query_name,
    COUNT(*) as execution_count,
    ROUND(AVG(CAST(elapsed_time_ms AS DOUBLE)) / 1000.0, 2) as avg_sec,
    ROUND(STDDEV(CAST(elapsed_time_ms AS DOUBLE)) / 1000.0, 2) as stddev_sec,
    ROUND(MIN(CAST(elapsed_time_ms AS DOUBLE)) / 1000.0, 2) as min_sec,
    ROUND(MAX(CAST(elapsed_time_ms AS DOUBLE)) / 1000.0, 2) as max_sec,
    ROUND((MAX(CAST(elapsed_time_ms AS DOUBLE)) - MIN(CAST(elapsed_time_ms AS DOUBLE))) / 1000.0, 2) as range_sec
FROM jmeter_query_results
WHERE run_id = '20251117-072011'
  AND elapsed_time_ms IS NOT NULL
GROUP BY label
HAVING COUNT(*) > 1
ORDER BY stddev_sec DESC
LIMIT 20;


-- ============================================================================
-- IMPORTANT NOTES AND LIMITATIONS
-- ============================================================================
--
-- ✅ QUERIES THAT WORK (90% of use cases):
--    - Single-run analysis with specific run_id filter
--    - Comparing 2-5 specific runs using IN clause
--    - Metadata-only queries (configuration, cluster info)
--    - Queries with explicit partition filters (run_id, engine, cluster_size, benchmark, run_type)
--
-- ❌ QUERIES THAT FAIL (10% limitation):
--    - Cross-partition aggregates WITHOUT explicit run_id filters
--    - Global percentiles across ALL runs (no run_id specified)
--    - Queries with only metadata table filters (e.g., GROUP BY instance_type without run_id list)
--
-- 🔑 KEY RULE:
--    Always include 'WHERE run_id = X' or 'WHERE run_id IN (X, Y, Z)' in results table queries
--    Always include 'AND elapsed_time_ms IS NOT NULL' to filter out invalid data
--
-- 📊 DASHBOARD BUILDING:
--    - Use metadata table for: configuration tracking, run inventory
--    - Use results table for: performance metrics, query-level analysis
--    - For trends: Query specific runs and aggregate in your dashboard tool
--
-- ============================================================================
