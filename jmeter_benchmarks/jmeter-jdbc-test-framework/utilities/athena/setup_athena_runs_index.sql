-- Athena table schema for JMeter Runs Index
-- This table stores comprehensive metadata about all test runs for easy querying and dashboard creation

-- Drop table if exists (use with caution)
-- DROP TABLE IF EXISTS jmeter_runs_index;

CREATE EXTERNAL TABLE IF NOT EXISTS jmeter_runs_index (
    -- Run identification
    run_id STRING,
    run_date TIMESTAMP,
    s3_path STRING,
    status STRING,

    -- Cluster information
    cluster_size STRING,
    estimated_cores INT,
    instance_type STRING,
    executors INT,
    cores_per_executor INT,
    serverless BOOLEAN,
    cluster_hostname STRING,

    -- Test configuration
    test_plan_file STRING,
    concurrent_threads INT,
    benchmark STRING,
    total_query_count INT,
    hold_period_min INT,
    ramp_up_time_sec INT,
    query_timeout_sec INT,
    random_order BOOLEAN,

    -- Results summary
    total_samples INT,
    actual_considered_queries INT,
    excluded_queries INT,
    total_success INT,
    total_failed INT,
    error_rate_pct DOUBLE,
    total_time_taken_sec DOUBLE,

    -- Latency statistics
    avg_latency_sec DOUBLE,
    median_latency_sec DOUBLE,
    min_latency_sec DOUBLE,
    max_latency_sec DOUBLE,
    p50_latency_sec DOUBLE,
    p90_latency_sec DOUBLE,
    p95_latency_sec DOUBLE,
    p99_latency_sec DOUBLE,

    -- Throughput metrics
    queries_per_minute DOUBLE,
    queries_per_second DOUBLE,
    avg_throughput_qpm DOUBLE,

    -- Performance ratings
    performance_rating STRING,
    consistency_rating STRING,

    -- Data transfer
    bytes_received_total BIGINT,
    bytes_sent_total BIGINT,
    avg_bytes_per_query BIGINT,

    -- Top slowest queries (array of structs)
    top_slowest_queries ARRAY<STRUCT<query:STRING, avg_sec:DOUBLE>>,

    -- Run metadata (classification fields for filtering)
    run_mode STRING,
    customer STRING,
    config STRING,
    tags STRING,
    comments STRING,

    -- Outlier detection info (for anomaly filtering)
    outlier_severity STRING,
    p90_z_score DOUBLE,
    p90_deviation_pct DOUBLE,
    p95_z_score DOUBLE,
    p95_deviation_pct DOUBLE,
    p99_z_score DOUBLE,
    p99_deviation_pct DOUBLE
)
PARTITIONED BY (
    engine STRING,
    cluster_size_partition STRING,
    benchmark_partition STRING,
    run_type STRING
)
ROW FORMAT SERDE 'org.openx.data.jsonserde.JsonSerDe'
WITH SERDEPROPERTIES (
    'ignore.malformed.json' = 'true'
)
LOCATION 's3://e6-jmeter/jmeter-results-index/runs/'
TBLPROPERTIES (
    'projection.enabled' = 'true',
    'projection.engine.type' = 'enum',
    'projection.engine.values' = 'e6data,databricks,trino,presto,athena',
    'projection.cluster_size_partition.type' = 'enum',
    'projection.cluster_size_partition.values' = 'XS-1x1,S-1x1,S-2x2,S-4x4,M-4x4,L-8x8,XL-16x16',
    'projection.benchmark_partition.type' = 'enum',
    'projection.benchmark_partition.values' = 'tpcds_29_1tb,tpcds_51_1tb,kantar',
    'projection.run_type.type' = 'enum',
    'projection.run_type.values' = 'concurrency_1,concurrency_2,concurrency_4,concurrency_8,concurrency_12,concurrency_16,sequential',
    'storage.location.template' = 's3://e6-jmeter/jmeter-results-index/runs/engine=${engine}/cluster_size=${cluster_size_partition}/benchmark=${benchmark_partition}/run_type=${run_type}'
);

-- Sample queries for common analysis patterns:

-- 1. Get all runs sorted by latest first
-- SELECT run_id, run_date, cluster_size, instance_type, p50_latency_sec, p90_latency_sec, p95_latency_sec
-- FROM jmeter_runs_index
-- WHERE engine = 'e6data'
-- ORDER BY run_date DESC
-- LIMIT 20;

-- 2. Compare performance across cluster sizes
-- SELECT
--     cluster_size,
--     instance_type,
--     COUNT(*) as num_runs,
--     AVG(p50_latency_sec) as avg_p50,
--     AVG(p90_latency_sec) as avg_p90,
--     AVG(p95_latency_sec) as avg_p95,
--     AVG(queries_per_minute) as avg_qpm
-- FROM jmeter_runs_index
-- WHERE engine = 'e6data'
--   AND benchmark = 'tpcds_29_1tb'
--   AND run_type = 'concurrency_8'
-- GROUP BY cluster_size, instance_type
-- ORDER BY avg_p50;

-- 3. Find runs with high error rates
-- SELECT run_id, run_date, cluster_size, concurrent_threads,
--        total_failed, error_rate_pct, performance_rating
-- FROM jmeter_runs_index
-- WHERE error_rate_pct > 0
-- ORDER BY error_rate_pct DESC;

-- 4. Compare instance types (r6id vs r7iz)
-- SELECT
--     instance_type,
--     COUNT(*) as runs,
--     AVG(p50_latency_sec) as avg_p50,
--     AVG(p90_latency_sec) as avg_p90,
--     AVG(p99_latency_sec) as avg_p99,
--     MIN(p50_latency_sec) as min_p50,
--     MAX(p50_latency_sec) as max_p50
-- FROM jmeter_runs_index
-- WHERE cluster_size = 'M-4x4'
--   AND benchmark = 'tpcds_29_1tb'
-- GROUP BY instance_type;

-- 5. Trend analysis over time
-- SELECT
--     DATE_TRUNC('day', run_date) as run_day,
--     cluster_size,
--     AVG(p90_latency_sec) as avg_p90,
--     AVG(queries_per_minute) as avg_qpm,
--     COUNT(*) as num_runs
-- FROM jmeter_runs_index
-- WHERE engine = 'e6data'
--   AND run_date >= DATE_ADD('day', -7, CURRENT_DATE)
-- GROUP BY DATE_TRUNC('day', run_date), cluster_size
-- ORDER BY run_day DESC, cluster_size;

-- 6. Identify slowest queries across all runs
-- SELECT
--     run_id,
--     run_date,
--     cluster_size,
--     slowest.query as query_name,
--     slowest.avg_sec as query_time_sec
-- FROM jmeter_runs_index
-- CROSS JOIN UNNEST(top_slowest_queries) as t(slowest)
-- WHERE engine = 'e6data'
-- ORDER BY slowest.avg_sec DESC
-- LIMIT 50;

-- 7. Performance consistency check
-- SELECT
--     cluster_size,
--     run_type,
--     COUNT(*) as runs,
--     AVG(p50_latency_sec) as avg_p50,
--     STDDEV(p50_latency_sec) as stddev_p50,
--     (STDDEV(p50_latency_sec) / AVG(p50_latency_sec) * 100) as cv_pct
-- FROM jmeter_runs_index
-- WHERE engine = 'e6data'
-- GROUP BY cluster_size, run_type
-- HAVING COUNT(*) >= 3
-- ORDER BY cv_pct;
