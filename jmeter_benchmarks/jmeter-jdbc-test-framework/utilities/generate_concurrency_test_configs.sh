#!/bin/bash
# Generator script to create metadata files and test input files for concurrency testing
# Generates files for e6data and DBR across cluster sizes S, M, and L with concurrency 2,4,8,12,16

set -e

# Configuration
CLUSTER_SIZES=("S" "M" "L")
CONCURRENCY_LEVELS=(2 4 8 12 16)
ENGINES=("e6data" "dbr")

# Directories
METADATA_DIR="metadata_files"
TEST_INPUT_DIR="test_inputs"
TEST_PROPS_DIR="test_properties"

# Base paths (relative to project root)
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

echo "=========================================="
echo "Concurrency Test Configuration Generator"
echo "=========================================="
echo ""
echo "Generating files for:"
echo "  Cluster Sizes: ${CLUSTER_SIZES[*]}"
echo "  Concurrency Levels: ${CONCURRENCY_LEVELS[*]}"
echo "  Engines: ${ENGINES[*]}"
echo ""

# Function to create test properties file if it doesn't exist
create_test_properties_file() {
    local concurrency=$1
    local props_file="$TEST_PROPS_DIR/concurrency_${concurrency}_test.properties"

    if [[ -f "$props_file" ]]; then
        echo "  ✓ Properties file exists: $props_file"
        return
    fi

    echo "  Creating properties file: $props_file"
    cat > "$props_file" << EOF
# JMeter Test Properties - Concurrency ${concurrency}

JMETER_HOME=

#Change below for Report directory path. Reports will be written in this directory
REPORT_PATH=reports

#Change below to copy the reports to s3. The copy script will use the aws configure credentials, so you should run aws creds in env set.
COPY_TO_S3=true
S3_REPORT_PATH=s3://e6-jmeter/jmeter-results

#Change below for concurrency based test plan which will maintain this concurrency. This applicable only for concurrency based plan
CONCURRENT_QUERY_COUNT=${concurrency}

#Change below if u want to add RAMP_TIME(min) and RAMP_UP_STEPS (counts) to reach target concurrency
RAMP_UP_TIME=1
RAMP_UP_STEPS=1

#Total time to run the test in minutes i.e hold the load. This is after ramp up time
HOLD_PERIOD=300

#Change below for QPM based Test Plan which will fire below number of queries per minute. This is applicable only for static QPM based test Plan
QPM=30

#Change below for QPS based Test Plan which will fire below number of queries per sec. This is applicable only for static QPS based test Plan
QPS=1

#Change below for load_profile based Test Plan. This will be applicable only if u select the load profile based test plan i.e QPS/QPM on arrivals.
LOAD_PROFILE=test_properties/load_profile.csv

#To select queries from the CSV in Random Order set below to true
RANDOM_ORDER=false

#Set below variable to true if you want to Repeat the queries in the CSV, this essentially means queries will repeat till the test duration
RECYCLE_ON_EOF=false

#Change below to the absolute path of your query file. This will be the query file used unless overwritten.
QUERY_PATH=data_files/Jmeter_15-queries-sub-2-sec_v3.csv

# These values are only to control the jmeter tests running out of resources, Change if required carefully as per machine resources
QUERY_TIMEOUT=300
LIMIT_RESULTSET=1000
MAX_CONCURRANCY=900
MAX_POOL=300
EOF
}

# Function to create DBR metadata file
create_dbr_metadata() {
    local cluster_size=$1
    local concurrency=$2

    # Map cluster size to new format with min/max clusters
    # All DBR tests use min=1, max=1 (no autoscaling)
    local cluster_size_formatted="${cluster_size}-1x1"

    local metadata_file="$METADATA_DIR/dbr_dbc-33354dfe-277f_${cluster_size,,}_concurrency${concurrency}_metadata.txt"

    echo "  Creating: $metadata_file"
    cat > "$metadata_file" << EOF
# ========================================
# DBR Cluster Test Metadata
# Cluster Size: ${cluster_size}-1x1 - ${concurrency} Concurrent Threads
# ========================================

# Test Run Identification
ALIAS="dbr-${cluster_size,,}-1x1-concurrency${concurrency}"
ENGINE="dbr"
MODE="benchmark"
TAGS="performance,benchmark,dbr,tpcds,azure,JPMC,concurrency-${concurrency},${cluster_size,,}-1x1,run-1"
COMMENTS="DBR SQL Warehouse ${cluster_size}-1x1 cluster - 29 TPCDS queries on 1TB dataset with ${concurrency} concurrent threads - Cold start, Run 1"

# Cloud & Region
CLOUD="Azure"
REGION="eastus"
AVAILABILITY_ZONE="unknown"

# DBR Cluster/Warehouse Configuration
CLUSTER_CONFIG='{
  "warehouse_id": "e020ff73ae69ed5a",
  "warehouse_type": "SQL Warehouse",
  "cluster_size": "${cluster_size_formatted}",
  "warehouse_size": "$(case $cluster_size in S) echo "Small";; M) echo "Medium";; L) echo "Large";; *) echo "Unknown";; esac)",
  "cluster_mode": "serverless",
  "min_clusters": 1,
  "max_clusters": 1,
  "runtime_version": "unknown",
  "driver_node_type": "unknown",
  "worker_node_type": "unknown",
  "min_workers": "unknown",
  "max_workers": "unknown",
  "autoscaling_enabled": "false",
  "spot_instances": "unknown",
  "photon_enabled": "unknown",
  "delta_cache_enabled": "unknown"
}'

# Cluster Endpoints
CLUSTER_HOSTNAME="dbc-33354dfe-277f.cloud.dbr.com"
HTTP_PATH="/sql/1.0/warehouses/e020ff73ae69ed5a"
JDBC_PORT="443"

# Database Configuration
CATALOG="hive_metastore"
SCHEMA="tpcds_1000_delta"
TABLE_FORMAT="delta"
DATA_SIZE="1TB"
PARTITION_STRATEGY="unknown"

# Data & Workload
DATA_TYPE="TPCDS"
DATASET_NAME="TPCDS 1TB"
QUERY_COUNT="29"
QUERY_SOURCE="JPMC selected TPCDS queries"
ADDITIONAL_INFO="DBR SQL Warehouse ${cluster_size} cluster on Azure, ${concurrency} concurrent threads, hive_metastore catalog, tpcds_1000_delta schema, Delta Lake format, 29 optimized TPCDS queries"

# Benchmark & Run Type (Optional - auto-detected if not specified)
BENCHMARK_TYPE="tpcds_29_1tb"

# RUN_TYPE: Execution pattern (auto-detected from test plan if not specified)
# RUN_TYPE="concurrency_${concurrency}"  # Uncomment to override auto-detection

# Performance Settings
AUTOSCALE="unknown"
CACHE_SETTINGS="use_cached_result=false"
ARROW_ENABLED="false"
CONNECTION_POOLING="enabled"

# Cost & Billing (optional)
COST_CENTER="unknown"
PROJECT="unknown"
OWNER="jagannath@e6x.io"

# Comparison Baseline
BASELINE_ENGINE="e6data"
BASELINE_CLUSTER="${cluster_size} cluster comparison"
COMPARISON_GOAL="Compare DBR ${cluster_size} cluster vs e6data on TPCDS 29 queries with ${concurrency} concurrent threads"

# S3 Upload Configuration
COPY_TO_S3=true
S3_PATH="s3://e6-jmeter/jmeter-results"

# Default file references
DEFAULT_TEST_PLAN="Test-Plan-Maintain-static-concurrency.jmx"
DEFAULT_TEST_PROPERTIES="concurrency_${concurrency}_test.properties"
DEFAULT_CONNECTION_PROPERTIES="dbr_dbc-33354dfe-277f_connection.properties"
DEFAULT_QUERIES="DBR_TPCDS_1TB_29_queries_singleline_3.csv"
DEFAULT_METADATA="dbr_dbc-33354dfe-277f_${cluster_size,,}_concurrency${concurrency}_metadata.txt"

# Test Execution Details
CONCURRENCY="${concurrency}"
TEST_PATTERN="static-concurrency"
RAMP_UP_TIME="1"
HOLD_PERIOD="300"
RECYCLE_ON_EOF="false"
RANDOM_ORDER="false"
EOF
}

# Function to create e6data metadata file
create_e6data_metadata() {
    local cluster_size=$1
    local concurrency=$2

    # Map cluster size to new format with executor counts
    # e6data sizing: S=2 executors, M=4 executors, L=8 executors (30 cores each)
    local executor_count=$(case $cluster_size in
        S) echo "2";;
        M) echo "4";;
        L) echo "8";;
        *) echo "unknown";;
    esac)
    local cluster_size_formatted="${cluster_size}-${executor_count}x${executor_count}"

    local metadata_file="$METADATA_DIR/e6data_demo-graviton_${cluster_size,,}_concurrency${concurrency}_metadata.txt"

    echo "  Creating: $metadata_file"
    cat > "$metadata_file" << EOF
# ========================================
# e6data demo-graviton Cluster Test Metadata
# Cluster Size: ${cluster_size}-${executor_count}x${executor_count} - ${concurrency} Concurrent Threads
# ========================================

# Test Run Identification
ALIAS="e6data-demo-graviton-${cluster_size,,}-${executor_count}x${executor_count}-concurrency${concurrency}"
ENGINE="e6data"
MODE="benchmark"
TAGS="performance,benchmark,e6data,tpcds,aws,JPMC,concurrency-${concurrency},${cluster_size,,}-${executor_count}x${executor_count},run-1"
COMMENTS="e6data graviton ${cluster_size}-${executor_count}x${executor_count} cluster - 29 TPCDS queries on 1TB dataset with ${concurrency} concurrent threads - Cold start, Run 1"

# Cloud & Region
CLOUD="AWS"
REGION="us-east-1"
AVAILABILITY_ZONE="unknown"

# e6data Cluster Configuration
CLUSTER_CONFIG='{
  "cluster_id": "demo-graviton",
  "cluster_name": "demo-graviton",
  "cluster_size": "${cluster_size_formatted}",
  "executors": ${executor_count},
  "cores_per_executor": 30,
  "total_cores": $((executor_count * 30)),
  "nodes": "1",
  "instance_type": "r7iz.8xlarge",
  "vcpus_per_node": "32",
  "memory_per_node_gb": "256",
  "serverless": "false",
  "autoscaling_enabled": "false",
  "storage_type": "NVMe SSD"
}'

# Cluster Endpoints
CLUSTER_HOSTNAME="t2mhr5k871-us-east-1.e6data.io"
JDBC_PORT="443"
HTTP_PATH="/"

# Database Configuration
CATALOG="glue_catalog"
SCHEMA="tpcds_1000_delta"
TABLE_FORMAT="delta"
DATA_SIZE="1TB"
PARTITION_STRATEGY="unknown"

# Data & Workload
DATA_TYPE="TPCDS"
DATASET_NAME="TPCDS 1TB"
QUERY_COUNT="29"
QUERY_SOURCE="JPMC selected TPCDS queries (sorted)"
ADDITIONAL_INFO="e6data demo-graviton ${cluster_size}-${executor_count}x${executor_count} cluster, ${concurrency} concurrent threads, ${executor_count} executors × 30 cores = $((executor_count * 30)) cores, glue_catalog, tpcds_1000_delta schema, Delta Lake format, 29 TPCDS queries"

# Benchmark & Run Type (Optional - auto-detected if not specified)
BENCHMARK_TYPE="tpcds_29_1tb"

# RUN_TYPE: Execution pattern (auto-detected from test plan if not specified)
# RUN_TYPE="concurrency_${concurrency}"  # Uncomment to override auto-detection

# Performance Settings
AUTOSCALE="unknown"
CACHE_SETTINGS="enabled"
QUERY_PUSHDOWN="enabled"
VECTORIZED_EXECUTION="enabled"
CONNECTION_POOLING="enabled"

# Cost & Billing (optional)
COST_CENTER="unknown"
PROJECT="unknown"
OWNER="jagannath@e6x.io"

# Comparison Baseline
BASELINE_ENGINE="dbr"
BASELINE_CLUSTER="${cluster_size}-1x1 cluster comparison"
COMPARISON_GOAL="Compare e6data ${cluster_size}-${executor_count}x${executor_count} ($((executor_count * 30)) cores) vs DBR ${cluster_size}-1x1 on TPCDS 29 queries with ${concurrency} concurrent threads"

# S3 Upload Configuration
COPY_TO_S3=true
S3_PATH="s3://e6-jmeter/jmeter-results"

# Default file references
DEFAULT_TEST_PLAN="Test-Plan-Maintain-static-concurrency.jmx"
DEFAULT_TEST_PROPERTIES="concurrency_${concurrency}_test.properties"
DEFAULT_CONNECTION_PROPERTIES="demo-graviton_connection.properties"
DEFAULT_QUERIES="E6Data_TPCDS_queries_29.csv"
DEFAULT_METADATA="e6data_demo-graviton_${cluster_size,,}_concurrency${concurrency}_metadata.txt"

# Test Execution Details
CONCURRENCY="${concurrency}"
TEST_PATTERN="static-concurrency"
RAMP_UP_TIME="1"
HOLD_PERIOD="300"
RECYCLE_ON_EOF="false"
RANDOM_ORDER="false"
EOF
}

# Function to create test input file
create_test_input() {
    local engine=$1
    local cluster_size=$2
    local concurrency=$3
    local input_file="$TEST_INPUT_DIR/${engine}_${cluster_size,,}_tpcds29_concurrency_${concurrency}.txt"

    echo "  Creating: $input_file"

    if [[ "$engine" == "dbr" ]]; then
        cat > "$input_file" << EOF
dbr_dbc-33354dfe-277f_${cluster_size,,}_concurrency${concurrency}_metadata.txt
Test-Plan-Maintain-static-concurrency.jmx
concurrency_${concurrency}_test.properties
dbr_dbc-33354dfe-277f_connection.properties
DBR_TPCDS_1TB_29_queries_singleline_3.csv
EOF
    else  # e6data
        cat > "$input_file" << EOF
e6data_demo-graviton_${cluster_size,,}_concurrency${concurrency}_metadata.txt
Test-Plan-Maintain-static-concurrency.jmx
concurrency_${concurrency}_test.properties
demo-graviton_connection.properties
E6Data_TPCDS_queries_29.csv
EOF
    fi
}

# Main generation loop
echo "Creating test properties files..."
for concurrency in "${CONCURRENCY_LEVELS[@]}"; do
    create_test_properties_file "$concurrency"
done

echo ""
echo "Creating metadata and test input files..."
file_count=0

for engine in "${ENGINES[@]}"; do
    for cluster_size in "${CLUSTER_SIZES[@]}"; do
        for concurrency in "${CONCURRENCY_LEVELS[@]}"; do
            echo ""
            echo "[$((++file_count))/20] Generating ${engine} ${cluster_size} concurrency=${concurrency}..."

            # Create metadata file
            if [[ "$engine" == "dbr" ]]; then
                create_dbr_metadata "$cluster_size" "$concurrency"
            else
                create_e6data_metadata "$cluster_size" "$concurrency"
            fi

            # Create test input file
            create_test_input "$engine" "$cluster_size" "$concurrency"
        done
    done
done

echo ""
echo "=========================================="
echo "✓ Generation Complete!"
echo "=========================================="
echo "Created:"
echo "  - $(ls -1 $METADATA_DIR/*_concurrency*.txt 2>/dev/null | wc -l) metadata files"
echo "  - $(ls -1 $TEST_INPUT_DIR/*_concurrency_*.txt 2>/dev/null | wc -l) test input files"
echo "  - $(ls -1 $TEST_PROPS_DIR/concurrency_*_test.properties 2>/dev/null | wc -l) test properties files"
echo ""
echo "Next steps:"
echo "  1. Review generated files in $METADATA_DIR/ and $TEST_INPUT_DIR/"
echo "  2. Update DBR warehouse to desired cluster size"
echo "  3. Run execution scripts:"
echo "     - ./utilities/run_dbr_s_all_concurrency.sh"
echo "     - ./utilities/run_dbr_m_all_concurrency.sh"
echo "     - ./utilities/run_e6data_s_all_concurrency.sh"
echo "     - ./utilities/run_e6data_m_all_concurrency.sh"
echo ""
