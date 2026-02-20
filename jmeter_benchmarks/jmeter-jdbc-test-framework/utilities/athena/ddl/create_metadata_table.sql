-- Create jmeter_run_metadata table
-- Purpose: Stores test run configuration and cluster metadata
-- Cardinality: 1 row per run_id
-- Data Source: test_result.json files from S3

CREATE EXTERNAL TABLE IF NOT EXISTS jmeter_run_metadata (
    -- Run identifiers
    run_id STRING COMMENT 'Unique run identifier (YYYYMMDD-HHMMSS)',
    run_date STRING COMMENT 'Formatted run date (YYYY-MM-DD HH:MM:SS)',
    s3_path STRING COMMENT 'S3 path to run files',
    status STRING COMMENT 'Run status (completed, failed, etc.)',

    -- Cluster configuration
    cluster_hostname STRING COMMENT 'Cluster hostname',
    instance_type STRING COMMENT 'EC2 instance type (e.g., r7iz.16xlarge)',
    estimated_cores INT COMMENT 'Total cores in cluster',
    executors INT COMMENT 'Number of executors',
    cores_per_executor INT COMMENT 'Cores per executor',
    serverless BOOLEAN COMMENT 'Whether cluster is serverless',

    -- Test configuration
    test_plan_file STRING COMMENT 'JMeter test plan filename',
    concurrent_threads INT COMMENT 'Number of concurrent threads',
    benchmark STRING COMMENT 'Benchmark name (e.g., tpcds_29_1tb)',
    total_query_count INT COMMENT 'Total queries in test',
    hold_period_sec INT COMMENT 'Hold period in seconds',
    ramp_up_time_sec INT COMMENT 'Ramp-up time in seconds',
    query_timeout_sec INT COMMENT 'Query timeout in seconds',
    random_order BOOLEAN COMMENT 'Whether queries were randomized',

    -- Run metadata
    run_mode STRING COMMENT 'Run mode (prod, test, etc.)',
    customer STRING COMMENT 'Customer name',
    config STRING COMMENT 'Configuration name',
    tags STRING COMMENT 'Tags for the run',
    comments STRING COMMENT 'Run comments',

    -- Outlier detection (from parent aggregated analysis)
    is_outlier STRING COMMENT 'Whether run is an outlier (yes/no)',
    outlier_severity STRING COMMENT 'Outlier severity level',
    p90_z_score DOUBLE COMMENT 'Z-score for P90 latency',
    p90_deviation_pct DOUBLE COMMENT 'P90 deviation percentage',
    p95_z_score DOUBLE COMMENT 'Z-score for P95 latency',
    p95_deviation_pct DOUBLE COMMENT 'P95 deviation percentage'
)
PARTITIONED BY (
    engine STRING COMMENT 'Engine type (e6data, databricks, etc.)',
    cluster_size STRING COMMENT 'Cluster size (XS-1x1, S-2x2, M-4x4, etc.)'
)
ROW FORMAT SERDE 'org.openx.data.jsonserde.JsonSerDe'
-- UPDATE: Replace with your S3 bucket
LOCATION 's3://your-s3-bucket/athena-tables/run_metadata/'
TBLPROPERTIES ('has_encrypted_data'='false');
