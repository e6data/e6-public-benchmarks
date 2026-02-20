-- Create jmeter_query_results table (CSV-based - points directly at existing data)
-- Purpose: Query-level execution results from JMeter CSV files
-- Cardinality: Many rows per run_id (30-100 queries per run)
-- Data Source: Existing JmeterResultFile.csv files in s3://your-s3-bucket/jmeter-results/
--
-- HYBRID APPROACH: This table reads CSV files directly (no transformation needed)
-- Companion table jmeter_run_metadata uses JSONL transformation for metadata

CREATE EXTERNAL TABLE IF NOT EXISTS jmeter_query_results (
    -- JMeter standard CSV columns (in order)
    timestamp_epoch BIGINT COMMENT 'Query execution timestamp (epoch milliseconds)',
    elapsed_time_ms BIGINT COMMENT 'Total elapsed time (response time) in milliseconds',
    label STRING COMMENT 'Query name/label from JMeter test plan',
    response_code STRING COMMENT 'Response code from JDBC driver',
    response_message STRING COMMENT 'Response message (error details if failed)',
    thread_name STRING COMMENT 'JMeter thread that executed the query',
    data_type STRING COMMENT 'Data type (usually "text" for JDBC)',
    success STRING COMMENT 'Whether query succeeded (true/false)',
    failure_message STRING COMMENT 'Failure message if query failed',
    bytes_received BIGINT COMMENT 'Bytes received in response',
    bytes_sent BIGINT COMMENT 'Bytes sent in request',
    grp_threads INT COMMENT 'Active threads in this thread group',
    all_threads INT COMMENT 'Total active threads across all groups',
    url STRING COMMENT 'JDBC connection URL',
    latency_ms BIGINT COMMENT 'Time to first byte in milliseconds',
    idle_time_ms BIGINT COMMENT 'Idle time before request',
    connect_time_ms BIGINT COMMENT 'Connection establishment time'
)
PARTITIONED BY (
    engine STRING COMMENT 'Engine type (e6data, databricks, etc.)',
    cluster_size STRING COMMENT 'Cluster size (S-2x2, M-4x4, etc.)',
    benchmark STRING COMMENT 'Benchmark name (tpcds_29_1tb, etc.)',
    run_type STRING COMMENT 'Run type (concurrency_2, concurrency_4, etc.)',
    run_id STRING COMMENT 'Run identifier (YYYYMMDD-HHMMSS)'
)
ROW FORMAT SERDE 'org.apache.hadoop.hive.serde2.lazy.LazySimpleSerDe'
WITH SERDEPROPERTIES (
   'field.delim' = ',',
   'serialization.format' = ','
)
-- UPDATE: Replace with your S3 bucket
LOCATION 's3://your-s3-bucket/jmeter-results/'
TBLPROPERTIES (
    'skip.header.line.count'='1',
    'has_encrypted_data'='false',
    'projection.enabled'='false',
    'exclude.file.pattern'='.*\\.json|.*SummaryReport.*\\.csv|.*AggregateReport.*\\.csv'
);
