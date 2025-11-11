#!/usr/bin/env bash

# Check Java version
java_version=$(java -version 2>&1 | head -n 1 | cut -d'"' -f2 | cut -d'.' -f1)

if [ "$java_version" != "17" ]; then
    echo ""
    echo "❌ ERROR: Java 17 is required but Java $java_version is currently active"
    echo ""
    echo "Please set Java 17 before running this script:"
    echo ""
    echo "  export JAVA_HOME=/path/to/java17"
    echo "  export PATH=\$JAVA_HOME/bin:\$PATH"
    echo ""
    echo "Common Java 17 locations:"
    echo "  • macOS (Homebrew): /opt/homebrew/opt/openjdk@17"
    echo "  • macOS (Intel):    /usr/local/opt/openjdk@17"
    echo "  • Linux:            /usr/lib/jvm/java-17-openjdk"
    echo ""
    exit 1
fi

echo "✅ Java 17 detected"

# Basic configuration
JMETER_HOME=$(pwd)
echo "JMETER_HOME is set to: $JMETER_HOME"

# Directory paths
TEST_PLAN_PATH="${JMETER_HOME}/Test-Plans"
TEST_PROPERTIES_PATH="${JMETER_HOME}/test_properties"
CONNECTION_PROPERTIES_PATH="${JMETER_HOME}/connection_properties"
QUERIES_PATH="${JMETER_HOME}/data_files"
REPORT_PATH="${JMETER_HOME}/reports"
METADATA_PATH="${JMETER_HOME}/metadata_files"

JMETER_BIN="${JMETER_HOME}/apache-jmeter-5.6.3/bin"

# Default files
DEFAULT_TEST_PLAN="Test-Plan-ArrivalsBased-with-Shuffle.jmx"
DEFAULT_TEST_PROPERTIES="sample_test.properties"
DEFAULT_CONNECTION_PROPERTIES="sample_connection.properties"
DEFAULT_QUERIES="sample_jmeter_queries.csv"
DEFAULT_METADATA="sample_metadata.txt"

# Function to display files
show_files() {
    local path="$1"
    local pattern="$2"
    local title="$3"
    
    echo ""
    echo "========================================================================================="
    echo "$title - Please select from below - Just press Enter if no change to Default in Bracket:"
    echo "========================================================================================="
    echo "Directory: $path"
    echo ""
    find "$path" -maxdepth 1 -type f -name "$pattern" -exec basename {} \; | sort
    echo ""
    echo "==========================================================="
}

# Function to get the filename as user input
get_filename() {
    local path="$1"
    local default="$2"
    local title="$3"
    
    # Send headers to stderr
    echo "" >&2
    #echo "================================================" >&2
    #echo " $title - SELECT FILE" >&2
    #echo "================================================" >&2
    
    while true; do
        read -p "Enter filename [$default]: " filename >&2
        [ -z "$filename" ] && filename="$default"

        if [ -f "$path/$filename" ]; then
            echo "Selected: $filename" >&2  # Status message to stderr
            echo "$filename"  # Only output the filename to stdout
            return 0
        else
            echo "Error: File not found. Please try again." >&2
        fi
    done
}

# Main execution
echo "Starting user input file selection..."

# Select  METADATA FILE
show_files "$METADATA_PATH" "*.txt" "METADATA FILE"
SELECTED_METADATA_FILE=$(get_filename "$METADATA_PATH" "$DEFAULT_METADATA" "METADATA FILE")
METADATA_FILE="${METADATA_PATH}/${SELECTED_METADATA_FILE}"
# update defaults and metadata from the selected metadata file
source "$METADATA_FILE"

# TEST PLAN
show_files "$TEST_PLAN_PATH" "*.jmx" "TEST PLAN"
SELECTED_TEST_PLAN=$(get_filename "$TEST_PLAN_PATH" "$DEFAULT_TEST_PLAN" "TEST PLAN")
TEST_PLAN="${TEST_PLAN_PATH}/${SELECTED_TEST_PLAN}"

# TEST PROPERTIES
show_files "$TEST_PROPERTIES_PATH" "*.properties" "TEST PROPERTIES"
SELECTED_TEST_PROPERTIES=$(get_filename "$TEST_PROPERTIES_PATH" "$DEFAULT_TEST_PROPERTIES" "TEST PROPERTIES")
TEST_PROPERTIES="${TEST_PROPERTIES_PATH}/${SELECTED_TEST_PROPERTIES}"

# CONNECTION PROPERTIES
show_files "$CONNECTION_PROPERTIES_PATH" "*.properties" "CONNECTION PROPERTIES"
SELECTED_CONNECTION_PROPERTIES=$(get_filename "$CONNECTION_PROPERTIES_PATH" "$DEFAULT_CONNECTION_PROPERTIES" "CONNECTION PROPERTIES")
CONNECTION_PROPERTIES="${CONNECTION_PROPERTIES_PATH}/${SELECTED_CONNECTION_PROPERTIES}"

# Auto-detect ENGINE from DRIVER_CLASS if not explicitly set in metadata
if [[ -z "${ENGINE:-}" ]] || [[ "${ENGINE}" == "unknown" ]]; then
    DRIVER_CLASS_DETECT=$(grep "^DRIVER_CLASS=" "$CONNECTION_PROPERTIES" 2>/dev/null | cut -d'=' -f2 | tr -d '"' || echo "")
    if [[ -n "$DRIVER_CLASS_DETECT" ]]; then
        case "$DRIVER_CLASS_DETECT" in
            *e6-jdbc-driver*) ENGINE="e6data" ;;
            *dbr-jdbc*) ENGINE="dbr" ;;
            *trino-jdbc*) ENGINE="trino" ;;
            *presto-jdbc*) ENGINE="presto" ;;
            *athena-jdbc*|*AthenaJDBC*) ENGINE="athena" ;;
            *snowflake-jdbc*) ENGINE="snowflake" ;;
            *) ENGINE="unknown" ;;
        esac
        echo "ℹ️  Auto-detected ENGINE='$ENGINE' from DRIVER_CLASS='$DRIVER_CLASS_DETECT'"
    else
        ENGINE="unknown"
        echo "⚠️  WARNING: Could not auto-detect ENGINE, using 'unknown'"
    fi
fi

# QUERIES FILE
show_files "$QUERIES_PATH" "*.csv" "QUERIES FILE"
SELECTED_QUERIES_FILE=$(get_filename "$QUERIES_PATH" "$DEFAULT_QUERIES" "QUERIES FILE")
QUERIES_FILE="${QUERIES_PATH}/${SELECTED_QUERIES_FILE}"


echo ""
echo "================================================"
echo " FINAL SELECTIONS"
echo "================================================"
echo "1. Test Plan: $TEST_PLAN"
echo "2. Test Properties: $TEST_PROPERTIES"
echo "3. Connection Properties: $CONNECTION_PROPERTIES"
echo "4. Queries File: $QUERIES_FILE"
echo "5. Metadata File: $METADATA_FILE"
echo "================================================"


# Get Jmeter hostname and OS info
JMETER_HOSTNAME=$(hostname)

#Get the run_id and run_date from the start time
START_TIME=$(date +%Y%m%d-%H%M%S)
RUN_ID="$START_TIME"
RUN_DATE="${START_TIME:0:8}"  # Extract the date part (first 8 characters)
echo "$START_TIME" > "$REPORT_PATH/start_time.txt"

# Get JDBC_URL from connection properties file
JDBC_URL=$(grep '^CONNECTION_STRING' "$CONNECTION_PROPERTIES" | sed 's/^CONNECTION_STRING=//' | tr -d '"' | tr -d '[:space:]')

# Check if JDBC_URL is empty or invalid
if [[ -z "$JDBC_URL" ]]; then
  echo "ERROR: JDBC_URL not found in $CONNECTION_PROPERTIES"
  exit 1
fi

# Get cluster hostname from JDBC URL
CLUSTER_HOSTNAME=$(echo "$JDBC_URL" | awk -F'/' '{print $3}' | awk -F':' '{print $1}')

# Check if CLUSTER_HOSTNAME is empty or invalid
if [[ -z "$CLUSTER_HOSTNAME" ]]; then
  echo "ERROR: Unable to extract CLUSTER_HOSTNAME from JDBC_URL: $JDBC_URL"
  exit 1
fi


# Define result files
JMETER_RESULT_FILE="$REPORT_PATH/JmeterResultFile_${START_TIME}.csv"
AGGREGATE_REPORT="$REPORT_PATH/AggregateReport_${START_TIME}.csv"
SUMMARY_REPORT="$REPORT_PATH/SummaryReport_${START_TIME}.csv"
TEST_RESULT_FILE="$REPORT_PATH/test_result_${START_TIME}.json"
STATISTICS_FILE="$REPORT_PATH/dashboard_${START_TIME}/statistics.json"
JMETER_LOG="$REPORT_PATH/jmeter_${START_TIME}.log"
CONSOLE_LOG="$REPORT_PATH/jmeter_console_${START_TIME}.log"


# Display the properties and start the test
echo "Starting JMeter test run at $START_TIME"
echo "Test Plan: $TEST_PLAN"
echo "Test Properties: $TEST_PROPERTIES"
echo "Connection Properties: $CONNECTION_PROPERTIES"
echo "JDBC_URL = $JDBC_URL"
echo "CLUSTER_HOSTNAME = $CLUSTER_HOSTNAME"
echo "Results will be saved to: $REPORT_PATH"

# Check if this is a load profile based test plan and update it
if [[ "$TEST_PLAN" == *"load-profile"* ]] || [[ "$TEST_PLAN" == *"load_profile"* ]]; then
  # Check if LOAD_PROFILE property exists in test properties
  if grep -q "LOAD_PROFILE=" "$TEST_PROPERTIES" 2>/dev/null; then
    LOAD_PROFILE_PATH=$(grep "^LOAD_PROFILE=" "$TEST_PROPERTIES" | cut -d'=' -f2 | tr -d '"' | tr -d "'")
    
    if [[ -n "$LOAD_PROFILE_PATH" ]] && [[ -f "$LOAD_PROFILE_PATH" ]]; then
      echo ""
      echo "📊 Detected load profile based test plan"
      echo "📂 Load profile: $LOAD_PROFILE_PATH"
      
      # Check if update script exists
      UPDATE_SCRIPT="$(dirname "$0")/utilities/update_load_profile.sh"
      if [[ -f "$UPDATE_SCRIPT" ]]; then
        echo "🔄 Updating test plan with load profile..."
        "$UPDATE_SCRIPT" "$LOAD_PROFILE_PATH" "$TEST_PLAN"
        
        if [[ $? -eq 0 ]]; then
          echo "✅ Test plan updated with load profile"
        else
          echo "⚠️  Warning: Failed to update test plan with load profile"
        fi
      else
        echo "⚠️  Warning: utilities/update_load_profile.sh not found, using static schedule in test plan"
      fi
      echo ""
    fi
  fi
fi

# Check if required files exist
for file in "$TEST_PLAN" "$TEST_PROPERTIES" "$CONNECTION_PROPERTIES"; do
  if [[ ! -f "$file" ]]; then
    echo "ERROR: Missing required file: $file"
    exit 1
  fi
done


# Check if dashboard generation is enabled (default: true to generate statistics.json)
GENERATE_DASHBOARD=${GENERATE_DASHBOARD:-true}
if [[ "$GENERATE_DASHBOARD" == "true" ]]; then
    DASHBOARD_FLAGS="-e -o $REPORT_PATH/dashboard_${START_TIME}"
    echo "Dashboard generation: ENABLED (will create HTML dashboard in reports/)"
else
    DASHBOARD_FLAGS=""
    echo "Dashboard generation: DISABLED (set GENERATE_DASHBOARD=true in test properties to enable)"
fi

# Start the Jmeter run

"$JMETER_BIN/jmeter" -n -t "$TEST_PLAN"\
    -q "$TEST_PROPERTIES" \
    -q "$CONNECTION_PROPERTIES" \
    -JSTART_TIME="$START_TIME" \
    -JQUERY_PATH="$QUERIES_FILE" \
    -l "$JMETER_RESULT_FILE" \
    $DASHBOARD_FLAGS \
    -j "$JMETER_LOG" 2>&1 | tee "$CONSOLE_LOG"

# Extract final summary line
JMETER_RUN_SUMMARY=$(grep "summary =" "$CONSOLE_LOG" | tail -n 1)
if [[ -z "$JMETER_RUN_SUMMARY" ]]; then
  echo "ERROR: JMeter summary not found. Check logs for more information."
  exit 1
else
  echo "JMeter Summary: $JMETER_RUN_SUMMARY"
fi


#Get End time
END_TIME=$(date +%Y%m%d_%H%M%S)

# Capture JMeter CLI command used (sanitize any passwords)
if [[ "$GENERATE_DASHBOARD" == "true" ]]; then
    JMETER_CLI_COMMAND="jmeter -n -t $(basename "$TEST_PLAN") -q $(basename "$TEST_PROPERTIES") -q $(basename "$CONNECTION_PROPERTIES") -JSTART_TIME=$START_TIME -JQUERY_PATH=$(basename "$QUERIES_FILE") -l $(basename "$JMETER_RESULT_FILE") -e -o dashboard_${START_TIME} -j jmeter_${START_TIME}.log"
else
    JMETER_CLI_COMMAND="jmeter -n -t $(basename "$TEST_PLAN") -q $(basename "$TEST_PROPERTIES") -q $(basename "$CONNECTION_PROPERTIES") -JSTART_TIME=$START_TIME -JQUERY_PATH=$(basename "$QUERIES_FILE") -l $(basename "$JMETER_RESULT_FILE") -j jmeter_${START_TIME}.log"
fi

# Capture all input file absolute paths
INPUT_FILES_JSON=$(jq -n \
    --arg test_plan "$TEST_PLAN" \
    --arg test_properties "$TEST_PROPERTIES" \
    --arg connection_properties "$CONNECTION_PROPERTIES" \
    --arg queries_file "$QUERIES_FILE" \
    --arg metadata_file "$METADATA_FILE" \
    '{
        test_plan: $test_plan,
        test_properties: $test_properties,
        connection_properties: $connection_properties,
        queries_file: $queries_file,
        metadata_file: $metadata_file
    }')

# Sanitize connection string (remove password if present)
CONNECTION_STRING_SANITIZED=$(echo "$JDBC_URL" | sed -E 's/(password|pwd|token|secret)=[^;&]*/\1=***REDACTED***/gi')

# Capture JMeter machine resources
JMETER_MACHINE_CPU_CORES=$(sysctl -n hw.ncpu 2>/dev/null || nproc 2>/dev/null || echo "unknown")
JMETER_MACHINE_MEMORY_GB=$(( $(sysctl -n hw.memsize 2>/dev/null || grep MemTotal /proc/meminfo 2>/dev/null | awk '{print $2*1024}' || echo "0") / 1024 / 1024 / 1024 ))
JMETER_MACHINE_OS=$(uname -s)
JMETER_MACHINE_OS_VERSION=$(uname -r)
JMETER_MACHINE_ARCH=$(uname -m)
JMETER_MACHINE_HOSTNAME=$(hostname)

# Capture JMeter process resource usage at test end (if available)
JMETER_PID=$(pgrep -f "jmeter.*$START_TIME" | head -1)
if [[ -n "$JMETER_PID" ]]; then
    JMETER_MEMORY_USED_MB=$(ps -o rss= -p "$JMETER_PID" 2>/dev/null | awk '{print int($1/1024)}' || echo "unknown")
    JMETER_CPU_PERCENT=$(ps -o %cpu= -p "$JMETER_PID" 2>/dev/null | awk '{print $1}' || echo "unknown")
else
    JMETER_MEMORY_USED_MB="unknown"
    JMETER_CPU_PERCENT="unknown"
fi

# Calculate additional stats from Aggregate Report
if [[ -f "$AGGREGATE_REPORT" ]]; then
  echo "Extracting additional metrics from Aggregate Report..."
fi

# General basic Stats for config file
total_queries=$(awk -F',' 'NR>1 {count++} END {print count+0}' "$AGGREGATE_REPORT")
total_success=$(awk -F',' 'NR>1 && $4 ~ /200/ {count++} END {print count+0}' "$AGGREGATE_REPORT")
total_failed=$((total_queries - total_success))

# Prevent division by zero error
error_percent=$(awk 'BEGIN {if ('$total_queries' > 0) printf "%.2f", ('$total_failed'/'$total_queries')*100; else print "0.00"}')


# Response Times
min_time=$(awk -F',' 'NR>1 {print $2}' "$AGGREGATE_REPORT" | sort -n | head -1)
max_time=$(awk -F',' 'NR>1 {print $2}' "$AGGREGATE_REPORT" | sort -n | tail -1)
avg_time=$(awk -F',' 'NR>1 {sum+=$2; count++} END {if (count>0) printf "%.2f", sum/count; else print "0.00"}' "$AGGREGATE_REPORT")

# Ensure variables are safe for JSON generation
total_queries=${total_queries:-0}
total_success=${total_success:-0}
total_failed=${total_failed:-0}
error_percent=${error_percent:-"0.00"}
min_time=${min_time:-"0"}
max_time=${max_time:-"0"}
avg_time=${avg_time:-"0"}

# Extract statistics from Aggregate Report for test_results file

# Ensure variables are safe for JSON generation
total_queries=${total_queries:-0}
total_success=${total_success:-0}
total_failed=${total_failed:-0}
total_time_taken=${total_time_taken:-0}
error_percent=${error_percent:-"0.00"}
min_time=${min_time:-"0"}
max_time=${max_time:-"0"}
avg_time=${avg_time:-"0"}
median_time=${median_time:-"0"}
throughput=${throughput:-"0"}
unique_queries=${unique_queries:-"0"}
p50_latency=${p50_latency:-"0"}
p90_latency=${p90_latency:-"0"}
p95_latency=${p95_latency:-"0"}
p99_latency=${p99_latency:-"0"}
query_timings=${query_timings:-"0"}
top_10_json=${top_10_json:-"0"}
all_queries_json=${all_queries_json:-"0"}
bootstrap_query_count=${bootstrap_query_count:-"0"}
jsr_sampler_count=${jsr_sampler_count:-"0"}
jdbc_sampler_count=${jsr_sampler_count:-"0"}
actual_considered_queries=${actual_considered_queries:-null}

# Set default values for variables (ensure they are valid JSON)
#jmeter_summary=${jmeter_summary:-'{}'}

bootstrap_query_count=${bootstrap_query_count:-"0"}
jsr_sampler_count=${jsr_sampler_count:-0}
jdbc_sampler_count=${jdbc_sampler_count:-0}

total_queries=${total_queries:-0}
total_success=${total_success:-0}
total_failed=${total_failed:-0}
error_percent=${error_percent:-0}
throughput=${throughput:-0}

total_time_taken=${total_time_taken:-0}
total_time_taken_sec=${total_time_taken_sec:-0}
min_time=${min_time:-0}
max_time=${max_time:-0}
avg_time=${avg_time:-0}
median_time=${median_time:-0}

p50_latency=${p50_latency:-0}
p90_latency=${p90_latency:-0}
p95_latency=${p95_latency:-0}
p99_latency=${p99_latency:-0}


all_queries_json=${all_queries_json:-'[]'}
unique_queries=${unique_queries:-'[]'}
bootstrap_queries=${bootstrap_queries:-'[]'}
actual_considered_queries=${actual_considered_queries:-'[]'}
top_10_json=${top_10_json:-'[]'}


if [[ -f "$AGGREGATE_REPORT" ]]; then
HEADERS=$(head -1 "$AGGREGATE_REPORT" | awk -F',' '{for(i=1;i<=NF;i++) gsub(/"/,"",$i); print tolower($0)}')


# Calculate query type counts
total_query_count=$(awk -F',' 'NR>1 {count++} END {print count}' "$AGGREGATE_REPORT")
bootstrap_query_count=$(awk -F',' 'NR>1 && $3 ~ /BOOTSTRAP/ {count++} END {print count}' "$AGGREGATE_REPORT")
jsr_sampler_count=$(awk -F',' 'NR>1 && $3 ~ /JSR/ {count++} END {print count}' "$AGGREGATE_REPORT")
jdbc_sampler_count=$(awk -F',' 'NR>1 && $3 !~ /BOOTSTRAP/ && $3 !~ /JSR/ {count++} END {print count}' "$AGGREGATE_REPORT")
actual_considered_queries=$jdbc_sampler_count

# Extract relevant stats
total_queries=$(awk -F',' 'NR>1 && $3 !~ /(BOOTSTRAP|JSR)/ {count++} END {print count}' "$AGGREGATE_REPORT")
total_success=$(awk -F',' 'NR>1 && $3 !~ /(BOOTSTRAP|JSR)/ && $4==200 {count++} END {print count}' "$AGGREGATE_REPORT")
total_failed=$((total_queries - total_success))
total_time_taken=$(awk -F',' 'NR>1 && $3 !~ /(BOOTSTRAP|JSR)/ {sum+=$2/1000} END {print sum}' "$AGGREGATE_REPORT")
min_time=$(awk -F',' 'NR>1 && $3 !~ /(BOOTSTRAP|JSR)/ && $4==200 {print $2}' "$AGGREGATE_REPORT" | sort -n | head -1 | awk '{printf "%.2f", $1/1000}' 2>/dev/null)
max_time=$(awk -F',' 'NR>1 && $3 !~ /(BOOTSTRAP|JSR)/ && $4==200 {print $2}' "$AGGREGATE_REPORT" | sort -n | tail -1 | awk '{printf "%.2f", $1/1000}' 2>/dev/null)
avg_time=$(awk -F',' 'NR>1 && $3 !~ /(BOOTSTRAP|JSR)/ && $4==200 {count++; sum+=$2} END {if (count>0) printf "%.2f", (sum/count)/1000; else print "0.00"}' "$AGGREGATE_REPORT")
median_time=$(awk -F',' 'NR>1 && $3 !~ /(BOOTSTRAP|JSR)/ && $4==200 {print $2}' "$AGGREGATE_REPORT" | sort -n | awk 'NF{a[i++]=$1} END{if(i>0) printf "%.2f", (i%2==1?a[int(i/2)]:(a[i/2-1]+a[i/2])/2)/1000; else print "0.00"}')
unique_queries=$(awk -F',' 'NR>1 {gsub(/^"|"$/, "", $3); if ($3 !~ /(BOOTSTRAP|JSR)/) seen[$3]++} END {print length(seen)}' "$AGGREGATE_REPORT")
error_percent=$(awk "BEGIN {printf \"%.2f\", ($total_failed/$total_queries) * 100}")
throughput=$(awk -F',' 'NR>1 && $3 !~ /(BOOTSTRAP|JSR)/ && $4==200 {count++; sum+=$2} END {if (sum>0) printf "%.2f", (count/(sum/1000)); else print "0.00"}' "$AGGREGATE_REPORT")

# Ensure variables have valid values for JSON
min_time=${min_time:-"0.00"}
max_time=${max_time:-"0.00"}
p50_latency=$median_time

# Calculate percentiles (p90, p95, p99)
sorted_values=$(awk -F',' 'NR>1 && $3 !~ /(BOOTSTRAP|JSR)/ {print $2}' "$AGGREGATE_REPORT" | sort -n)
tpcds_count=$(echo "$sorted_values" | wc -l)

p90_index=$(echo "($tpcds_count * 90 / 100) + 1" | bc)
p95_index=$(echo "($tpcds_count * 95 / 100) + 1" | bc)
p99_index=$(echo "($tpcds_count * 99 / 100) + 1" | bc)

[[ $p90_index -gt $tpcds_count ]] && p90_index=$tpcds_count
[[ $p95_index -gt $tpcds_count ]] && p95_index=$tpcds_count
[[ $p99_index -gt $tpcds_count ]] && p99_index=$tpcds_count

p90_latency=$(echo "$sorted_values" | sed -n "${p90_index}p" | awk '{printf "%.2f", $1/1000}')
p95_latency=$(echo "$sorted_values" | sed -n "${p95_index}p" | awk '{printf "%.2f", $1/1000}')
p99_latency=$(echo "$sorted_values" | sed -n "${p99_index}p" | awk '{printf "%.2f", $1/1000}')

# Calculate additional percentiles (p25, p75)
p25_index=$(echo "($tpcds_count * 25 / 100) + 1" | bc)
p75_index=$(echo "($tpcds_count * 75 / 100) + 1" | bc)
[[ $p25_index -gt $tpcds_count ]] && p25_index=$tpcds_count
[[ $p75_index -gt $tpcds_count ]] && p75_index=$tpcds_count
p25_latency=$(echo "$sorted_values" | sed -n "${p25_index}p" | awk '{printf "%.2f", $1/1000}')
p75_latency=$(echo "$sorted_values" | sed -n "${p75_index}p" | awk '{printf "%.2f", $1/1000}')

# Calculate interquartile range
interquartile_range=$(awk "BEGIN {printf \"%.2f\", $p75_latency - $p25_latency}")

# Calculate standard deviation and coefficient of variation
read std_dev coefficient_of_variation <<< $(awk -F',' -v avg="$avg_time" '
NR>1 && $3 !~ /(BOOTSTRAP|JSR)/ && $4==200 {
    time_sec = $2/1000
    sum_sq += (time_sec - avg) * (time_sec - avg)
    count++
}
END {
    if (count > 1) {
        std_dev = sqrt(sum_sq / (count - 1))
        cv = (avg > 0) ? (std_dev / avg) : 0
        printf "%.2f %.4f", std_dev, cv
    } else {
        print "0.00 0.0000"
    }
}' "$AGGREGATE_REPORT")

# Calculate outlier count (values beyond 1.5*IQR from quartiles)
outlier_count=$(awk -F',' -v p25="$p25_latency" -v p75="$p75_latency" -v iqr="$interquartile_range" '
NR>1 && $3 !~ /(BOOTSTRAP|JSR)/ && $4==200 {
    time_sec = $2/1000
    lower_bound = p25 - (1.5 * iqr)
    upper_bound = p75 + (1.5 * iqr)
    if (time_sec < lower_bound || time_sec > upper_bound) outliers++
}
END {print outliers+0}
' "$AGGREGATE_REPORT")

# Data transfer metrics
read bytes_received_total bytes_received_avg bytes_received_min bytes_received_max bytes_sent_total data_transfer_ratio <<< $(awk -F',' '
NR>1 && $3 !~ /(BOOTSTRAP|JSR)/ && $4==200 {
    bytes_recv = $9
    bytes_send = $10
    recv_total += bytes_recv
    send_total += bytes_send
    if (NR==2 || bytes_recv < recv_min) recv_min = bytes_recv
    if (bytes_recv > recv_max) recv_max = bytes_recv
    count++
}
END {
    recv_avg = (count > 0) ? recv_total / count : 0
    ratio = (send_total > 0) ? recv_total / send_total : 0
    printf "%d %.2f %d %d %d %.2f", recv_total, recv_avg, recv_min, recv_max, send_total, ratio
}
' "$AGGREGATE_REPORT")

# Connection & network metrics
read connect_time_avg connect_time_max queries_with_connection_reuse network_latency_avg <<< $(awk -F',' '
NR>1 && $3 !~ /(BOOTSTRAP|JSR)/ && $4==200 {
    connect_time = $19
    latency = $14
    elapsed = $2
    connect_sum += connect_time
    if (connect_time > connect_max) connect_max = connect_time
    if (connect_time == 0) reuse_count++
    network_overhead = (latency > elapsed) ? 0 : (elapsed - latency)
    network_sum += network_overhead
    count++
}
END {
    connect_avg = (count > 0) ? connect_sum / count : 0
    network_avg = (count > 0) ? network_sum / count : 0
    printf "%.2f %.2f %d %.2f", connect_avg, connect_max, reuse_count, network_avg
}
' "$AGGREGATE_REPORT")

# Query timing distribution buckets
read queries_under_1sec queries_1_to_5sec queries_5_to_10sec queries_over_10sec <<< $(awk -F',' '
NR>1 && $3 !~ /(BOOTSTRAP|JSR)/ && $4==200 {
    time_sec = $2/1000
    if (time_sec < 1) bucket_0_1++
    else if (time_sec < 5) bucket_1_5++
    else if (time_sec < 10) bucket_5_10++
    else bucket_10_plus++
}
END {
    printf "%d %d %d %d", bucket_0_1+0, bucket_1_5+0, bucket_5_10+0, bucket_10_plus+0
}
' "$AGGREGATE_REPORT")

# Concurrency metrics
read actual_concurrency_avg actual_concurrency_max <<< $(awk -F',' '
NR>1 && $3 !~ /(BOOTSTRAP|JSR)/ {
    all_threads = $12
    sum += all_threads
    if (all_threads > max_threads) max_threads = all_threads
    count++
}
END {
    avg = (count > 0) ? sum / count : 0
    printf "%.2f %d", avg, max_threads+0
}
' "$AGGREGATE_REPORT")

# Time-based analysis (actual test duration from timestamps)
read actual_test_duration_sec first_query_time last_query_time queries_per_minute_actual <<< $(awk -F',' '
NR>1 && $3 !~ /(BOOTSTRAP|JSR)/ {
    timestamp = $1
    if (NR==2 || timestamp < first_ts) first_ts = timestamp
    if (timestamp > last_ts) {
        last_ts = timestamp
        last_elapsed = $2
    }
    count++
}
END {
    duration_ms = (last_ts + last_elapsed) - first_ts
    duration_sec = duration_ms / 1000
    qpm = (duration_sec > 0) ? (count / duration_sec) * 60 : 0
    printf "%.2f %d %d %.2f", duration_sec, first_ts, last_ts+last_elapsed, qpm
}
' "$AGGREGATE_REPORT")

# Query efficiency metrics
bytes_per_second=$(awk "BEGIN {if ($actual_test_duration_sec > 0) printf \"%.2f\", $bytes_received_total / $actual_test_duration_sec; else print \"0.00\"}")

# Failure analysis - create failed queries array with error details
failed_queries_json=$(awk -F',' '
BEGIN {
    printf "["
    first = 1
}
NR>1 && $3 !~ /(BOOTSTRAP|JSR)/ && $8 == "false" {
    label = $3
    response_code = $4
    response_msg = $5
    gsub(/^"|"$/, "", label)
    gsub(/"/, "\\\"", response_msg)
    if (!first) printf ","
    printf "{\"query\":\"%s\",\"response_code\":\"%s\",\"error_message\":\"%s\"}", label, response_code, response_msg
    first = 0
}
END {
    printf "]"
}
' "$AGGREGATE_REPORT")

# Response codes summary
response_codes_summary=$(awk -F',' '
NR>1 && $3 !~ /(BOOTSTRAP|JSR)/ {
    code = $4
    codes[code]++
}
END {
    printf "{"
    first = 1
    for (code in codes) {
        if (!first) printf ","
        printf "\"%s\":%d", code, codes[code]
        first = 0
    }
    printf "}"
}
' "$AGGREGATE_REPORT")

# First failure time (if any failures)
first_failure_time=$(awk -F',' 'NR>1 && $3 !~ /(BOOTSTRAP|JSR)/ && $8 == "false" {print $1; exit}' "$AGGREGATE_REPORT")
first_failure_time=${first_failure_time:-0}

# Test reliability metrics
read consecutive_failures success_rate_first_half success_rate_second_half <<< $(awk -F',' -v total="$total_queries" '
NR>1 && $3 !~ /(BOOTSTRAP|JSR)/ {
    is_success = ($8 == "true") ? 1 : 0
    query_num++

    # Track consecutive failures
    if (!is_success) {
        current_streak++
        if (current_streak > max_streak) max_streak = current_streak
    } else {
        current_streak = 0
    }

    # Split into halves for trend analysis
    half_point = int(total / 2)
    if (query_num <= half_point) {
        first_half_total++
        if (is_success) first_half_success++
    } else {
        second_half_total++
        if (is_success) second_half_success++
    }
}
END {
    first_half_rate = (first_half_total > 0) ? (first_half_success / first_half_total) * 100 : 0
    second_half_rate = (second_half_total > 0) ? (second_half_success / second_half_total) * 100 : 0
    printf "%d %.2f %.2f", max_streak+0, first_half_rate, second_half_rate
}
' "$AGGREGATE_REPORT")

# Test stability score (composite metric)
test_stability_score=$(awk -v err_pct="$error_percent" -v cv="$coefficient_of_variation" '
BEGIN {
    reliability_factor = 1 - (err_pct / 100)
    consistency_factor = 1 - cv
    if (consistency_factor < 0) consistency_factor = 0
    stability = (reliability_factor * 0.6) + (consistency_factor * 0.4)
    printf "%.4f", stability
}')

# Warmup analysis - compare first 10% vs last 90% average time
read warmup_period_sec warmup_avg_time steady_state_avg_time <<< $(awk -F',' -v total="$total_queries" -v first_ts="$first_query_time" '
NR>1 && $3 !~ /(BOOTSTRAP|JSR)/ && $4==200 {
    query_num++
    time_ms = $2
    timestamp = $1

    warmup_count = int(total * 0.1)
    if (warmup_count < 1) warmup_count = 1

    if (query_num <= warmup_count) {
        warmup_sum += time_ms
        warmup_queries++
        last_warmup_ts = timestamp + time_ms
    } else {
        steady_sum += time_ms
        steady_queries++
    }
}
END {
    warmup_avg = (warmup_queries > 0) ? (warmup_sum / warmup_queries) / 1000 : 0
    steady_avg = (steady_queries > 0) ? (steady_sum / steady_queries) / 1000 : 0
    warmup_duration = (last_warmup_ts - first_ts) / 1000
    printf "%.2f %.2f %.2f", warmup_duration, warmup_avg, steady_avg
}
' "$AGGREGATE_REPORT")


    # Calculate query timings
    all_queries_json=$(awk -F',' '
    BEGIN {
        printf "["
        first = 1
    }
    NR>1 && $3 !~ /(BOOTSTRAP|JSR)/ {
        label=$3
        gsub(/^"|"$/, "", label)  # Remove quotes
        time=$2
        count[label]++
        sum[label]+=time
    }
    END {
        for (label in sum) {
            avg=sum[label]/count[label]/1000
            if (!first) printf ","
            printf "{\"query\":\"%s\",\"avg_time_sec\":%.2f}", label, avg
            first=0
        }
        printf "]"
    }' "$AGGREGATE_REPORT")

    # Sort by avg_time_sec descending and take top 10
    top_10_json=$(echo "$all_queries_json" | jq 'sort_by(.avg_time_sec) | reverse | .[0:10]')

# Create JSON summary
# Ensure jmeter_summary is a valid JSON object (default to empty object if empty)
# Extract connection properties safely (no credentials)
CONNECTION_HOSTNAME=$(grep "^HOSTNAME=" "$CONNECTION_PROPERTIES" 2>/dev/null | cut -d'=' -f2 | tr -d '"' || echo "unknown")
CONNECTION_PORT=$(grep "^PORT=" "$CONNECTION_PROPERTIES" 2>/dev/null | cut -d'=' -f2 | tr -d '"' || echo "unknown")
CONNECTION_CATALOG=$(grep "^CATALOG=" "$CONNECTION_PROPERTIES" 2>/dev/null | cut -d'=' -f2 | tr -d '"' || echo "")
CONNECTION_SCHEMA=$(grep "^DATABASE=" "$CONNECTION_PROPERTIES" 2>/dev/null | cut -d'=' -f2 | tr -d '"' || echo "")
DRIVER_CLASS_USED=$(grep "^DRIVER_CLASS=" "$CONNECTION_PROPERTIES" 2>/dev/null | cut -d'=' -f2 | tr -d '"' || echo "unknown")

# Extract test properties for traceability
TEST_CONCURRENT_THREADS=$(grep "^CONCURRENT_QUERY_COUNT=" "$TEST_PROPERTIES" 2>/dev/null | cut -d'=' -f2 | tr -d '"' || echo "unknown")
TEST_RECYCLE_ON_EOF=$(grep "^RECYCLE_ON_EOF=" "$TEST_PROPERTIES" 2>/dev/null | cut -d'=' -f2 | tr -d '"' || echo "unknown")
TEST_RANDOM_ORDER=$(grep "^RANDOM_ORDER=" "$TEST_PROPERTIES" 2>/dev/null | cut -d'=' -f2 | tr -d '"' || echo "unknown")
TEST_QUERY_TIMEOUT=$(grep "^QUERY_TIMEOUT=" "$TEST_PROPERTIES" 2>/dev/null | cut -d'=' -f2 | tr -d '"' || echo "unknown")
TEST_LIMIT_RESULTSET=$(grep "^LIMIT_RESULTSET=" "$TEST_PROPERTIES" 2>/dev/null | cut -d'=' -f2 | tr -d '"' || echo "unknown")
TEST_HOLD_PERIOD=$(grep "^HOLD_PERIOD=" "$TEST_PROPERTIES" 2>/dev/null | cut -d'=' -f2 | tr -d '"' || echo "unknown")
TEST_RAMP_UP_TIME=$(grep "^RAMP_UP_TIME=" "$TEST_PROPERTIES" 2>/dev/null | cut -d'=' -f2 | tr -d '"' || echo "unknown")
TEST_QPM=$(grep "^QPM=" "$TEST_PROPERTIES" 2>/dev/null | cut -d'=' -f2 | tr -d '"' || echo "")
TEST_QPS=$(grep "^QPS=" "$TEST_PROPERTIES" 2>/dev/null | cut -d'=' -f2 | tr -d '"' || echo "")

# Get Java version
JAVA_VERSION=$(java -version 2>&1 | head -n 1 | cut -d'"' -f2 || echo "unknown")

# Extract metadata fields for comparison context (if they exist)
REGION=${REGION:-"unknown"}
AVAILABILITY_ZONE=${AVAILABILITY_ZONE:-"unknown"}
CATALOG=${CATALOG:-"$CONNECTION_CATALOG"}
SCHEMA=${SCHEMA:-"$CONNECTION_SCHEMA"}
TABLE_FORMAT=${TABLE_FORMAT:-"unknown"}
DATA_SIZE=${DATA_SIZE:-"unknown"}
BASELINE_ENGINE=${BASELINE_ENGINE:-""}
BASELINE_CLUSTER=${BASELINE_CLUSTER:-""}
COMPARISON_GOAL=${COMPARISON_GOAL:-""}

# Additional optional metadata fields (can be specified in metadata file with defaults as "None")
# Note: COMMENTS and TAGS in metadata file provide flexible free-form context
TEST_TRIGGER=${TEST_TRIGGER:-"None"}  # manual, scheduled, CI-CD
TEST_PURPOSE=${TEST_PURPOSE:-"None"}  # benchmark, regression, capacity_planning
PREVIOUS_RUN_ID=${PREVIOUS_RUN_ID:-"None"}  # For comparison tracking

# Extract cluster_size from CLUSTER_CONFIG JSON for S3 partitioning
# This provides consistent partitioning across all engine types (e6data, dbr, snowflake, etc.)
CLUSTER_SIZE=$(echo "$CLUSTER_CONFIG" | jq -r '.cluster_size // "unknown"' 2>/dev/null || echo "unknown")

# Determine BENCHMARK_TYPE (with auto-detection from query filename or explicit metadata)
if [[ -n "${BENCHMARK_TYPE:-}" ]]; then
    # Use explicit value from metadata file if provided
    :
# TPC-DS 29 queries with data size detection
elif [[ "$(basename $QUERIES_FILE)" =~ TPCDS.*29.*1TB ]] || [[ "$(basename $QUERIES_FILE)" =~ tpcds.*29.*1tb ]]; then
    BENCHMARK_TYPE="tpcds_29_1tb"
elif [[ "$(basename $QUERIES_FILE)" =~ TPCDS.*29.*3TB ]] || [[ "$(basename $QUERIES_FILE)" =~ tpcds.*29.*3tb ]]; then
    BENCHMARK_TYPE="tpcds_29_3tb"
elif [[ "$(basename $QUERIES_FILE)" =~ TPCDS.*29.*10TB ]] || [[ "$(basename $QUERIES_FILE)" =~ tpcds.*29.*10tb ]]; then
    BENCHMARK_TYPE="tpcds_29_10tb"
elif [[ "$(basename $QUERIES_FILE)" =~ TPCDS.*29.*30TB ]] || [[ "$(basename $QUERIES_FILE)" =~ tpcds.*29.*30tb ]]; then
    BENCHMARK_TYPE="tpcds_29_30tb"
elif [[ "$(basename $QUERIES_FILE)" =~ TPCDS.*29 ]] || [[ "$(basename $QUERIES_FILE)" =~ tpcds.*29 ]]; then
    # Fallback for files without data size - default to 1TB with warning
    BENCHMARK_TYPE="tpcds_29_1tb"
    echo "⚠️  WARNING: Query file doesn't specify data size, defaulting to tpcds_29_1tb"
# TPC-DS 51 queries with data size detection
elif [[ "$(basename $QUERIES_FILE)" =~ TPCDS.*51.*1TB ]] || [[ "$(basename $QUERIES_FILE)" =~ tpcds.*51.*1tb ]]; then
    BENCHMARK_TYPE="tpcds_51_1tb"
elif [[ "$(basename $QUERIES_FILE)" =~ TPCDS.*51.*10TB ]] || [[ "$(basename $QUERIES_FILE)" =~ tpcds.*51.*10tb ]]; then
    BENCHMARK_TYPE="tpcds_51_10tb"
elif [[ "$(basename $QUERIES_FILE)" =~ TPCDS.*51 ]] || [[ "$(basename $QUERIES_FILE)" =~ 51.*[Jj]meter ]]; then
    BENCHMARK_TYPE="tpcds_51_1tb"
    echo "⚠️  WARNING: Query file doesn't specify data size, defaulting to tpcds_51_1tb"
# TPC-DS 81 queries
elif [[ "$(basename $QUERIES_FILE)" =~ TPCDS.*81.*1TB ]] || [[ "$(basename $QUERIES_FILE)" =~ tpcds.*81.*1tb ]]; then
    BENCHMARK_TYPE="tpcds_81_1tb"
elif [[ "$(basename $QUERIES_FILE)" =~ TPCDS.*81 ]]; then
    BENCHMARK_TYPE="tpcds_81_1tb"
    echo "⚠️  WARNING: Query file doesn't specify data size, defaulting to tpcds_81_1tb"
# TPC-H
elif [[ "$(basename $QUERIES_FILE)" =~ [Tt][Pp][Cc][Hh] ]]; then
    BENCHMARK_TYPE="tpch_22_100gb"
# Kantar custom
elif [[ "$(basename $QUERIES_FILE)" =~ [Kk]antar ]]; then
    BENCHMARK_TYPE="custom_kantar"
else
    # Fallback: use data_type from metadata + query count
    BENCHMARK_TYPE="${DATA_TYPE:-custom}_${QUERY_COUNT:-unknown}queries"
fi

# Determine RUN_TYPE from test configuration (auto-detection)
# CRITICAL: Use ACTUAL values from test_properties (TEST_*), not metadata values
# This ensures S3 path matches actual test execution configuration
if [[ -n "${RUN_TYPE:-}" ]] && [[ "${RUN_TYPE}" != "unknown" ]]; then
    # Use explicit value from metadata file if provided and valid
    echo "ℹ️  Using RUN_TYPE='$RUN_TYPE' from metadata"
elif [[ "$(basename $TEST_PLAN)" =~ "Run-Once" ]] || [[ "$TEST_CONCURRENT_THREADS" == "1" ]]; then
    RUN_TYPE="sequential"
elif [[ "$(basename $TEST_PLAN)" =~ "static-concurrency" ]] && [[ -n "$TEST_CONCURRENT_THREADS" ]] && [[ "$TEST_CONCURRENT_THREADS" != "unknown" ]]; then
    RUN_TYPE="concurrency_${TEST_CONCURRENT_THREADS}"
    echo "ℹ️  Auto-detected RUN_TYPE='$RUN_TYPE' from test_properties CONCURRENT_QUERY_COUNT=$TEST_CONCURRENT_THREADS"
elif [[ "$(basename $TEST_PLAN)" =~ "QPS" ]] && [[ -n "$TEST_QPS" ]] && [[ "$TEST_QPS" != "" ]]; then
    RUN_TYPE="arrivals_${TEST_QPS}qps"
    echo "ℹ️  Auto-detected RUN_TYPE='$RUN_TYPE' from test_properties QPS=$TEST_QPS"
elif [[ "$(basename $TEST_PLAN)" =~ "QPM" ]] && [[ -n "$TEST_QPM" ]] && [[ "$TEST_QPM" != "" ]]; then
    RUN_TYPE="arrivals_${TEST_QPM}qpm"
    echo "ℹ️  Auto-detected RUN_TYPE='$RUN_TYPE' from test_properties QPM=$TEST_QPM"
elif [[ "$(basename $TEST_PLAN)" =~ "load-profile" ]] || [[ "$(basename $TEST_PLAN)" =~ "variable-concurrency" ]]; then
    RUN_TYPE="loadprofile_variable"
else
    RUN_TYPE="unknown"
    echo "⚠️  WARNING: Could not determine RUN_TYPE, using 'unknown'"
fi

# Validation warnings for missing critical metadata
if [[ "$ENGINE" == "unknown" ]] || [[ "$CLUSTER_SIZE" == "unknown" ]]; then
    echo "⚠️  WARNING: Missing critical metadata!"
    echo "   ENGINE: $ENGINE"
    echo "   CLUSTER_SIZE: $CLUSTER_SIZE"
    echo "   Results will be stored in 'unknown' partition."
    echo "   Please update metadata file with ENGINE and CLUSTER_CONFIG.cluster_size"
fi

if [[ "$BENCHMARK_TYPE" == *"unknown"* ]] || [[ "$RUN_TYPE" == "unknown" ]]; then
    echo "⚠️  WARNING: Could not auto-detect benchmark or run type!"
    echo "   BENCHMARK_TYPE: $BENCHMARK_TYPE"
    echo "   RUN_TYPE: $RUN_TYPE"
    echo "   Consider adding BENCHMARK_TYPE and RUN_TYPE to metadata file."
fi

# Set S3_UPLOAD_PATH for JSON (will be "None" if S3 upload is disabled)
# 5-Level partition structure: engine/cluster_size/benchmark/run_type/run_id
if [[ "$COPY_TO_S3" == "true" ]]; then
    # Use S3_BASE_PATH from metadata file (fallback to default if not set)
    S3_BASE_PATH="${S3_BASE_PATH:-s3://e6-jmeter/jmeter-results}"

    S3_UPLOAD_PATH="${S3_BASE_PATH}/engine=$ENGINE/cluster_size=$CLUSTER_SIZE/benchmark=$BENCHMARK_TYPE/run_type=$RUN_TYPE/run_id=$RUN_ID"

    # Display S3 path summary for user verification
    echo ""
    echo "================================================"
    echo " S3 UPLOAD CONFIGURATION"
    echo "================================================"
    echo "Results will be uploaded to:"
    echo "  $S3_UPLOAD_PATH"
    echo ""
    echo "S3 Path Components (used for partitioning):"
    echo "  • base_path: $S3_BASE_PATH"
    echo "  • engine: $ENGINE"
    echo "  • cluster_size: $CLUSTER_SIZE"
    echo "  • benchmark: $BENCHMARK_TYPE"
    echo "  • run_type: $RUN_TYPE"
    echo "  • run_id: $RUN_ID"
    echo "================================================"
    echo ""
else
    S3_UPLOAD_PATH="None"
    echo "ℹ️  S3 upload is disabled (COPY_TO_S3=false)"
fi

JSON_SUMMARY=$(jq -n \
    --arg run_id "$RUN_ID" \
    --arg run_date "$RUN_DATE" \
    --arg start_time "$START_TIME" \
    --arg end_time "$END_TIME" \
    --arg alias "$ALIAS" \
    --arg engine "$ENGINE" \
    --arg jmeter_hostname "$JMETER_HOSTNAME" \
    --arg cluster_hostname "$CLUSTER_HOSTNAME" \
    --arg cloud "$CLOUD" \
    --arg mode "$MODE" \
    --arg tags "$TAGS" \
    --arg comments "$COMMENTS" \
    --argjson cluster_config "$CLUSTER_CONFIG" \
    --arg autoscale "$AUTOSCALE" \
    --arg data_type "$DATA_TYPE" \
    --arg additional_info "$ADDITIONAL_INFO" \
    --arg jmeter_run_summary "$JMETER_RUN_SUMMARY" \
    --arg test_plan_file "$(basename "$TEST_PLAN")" \
    --arg test_properties_file "$(basename "$TEST_PROPERTIES")" \
    --arg connection_properties_file "$(basename "$CONNECTION_PROPERTIES")" \
    --arg queries_file "$(basename "$QUERIES_FILE")" \
    --arg metadata_file "$(basename "$METADATA_FILE")" \
    --arg connection_hostname "$CONNECTION_HOSTNAME" \
    --arg connection_port "$CONNECTION_PORT" \
    --arg connection_catalog "$CATALOG" \
    --arg connection_schema "$SCHEMA" \
    --arg driver_class "$DRIVER_CLASS_USED" \
    --arg concurrent_threads "$TEST_CONCURRENT_THREADS" \
    --arg recycle_on_eof "$TEST_RECYCLE_ON_EOF" \
    --arg random_order "$TEST_RANDOM_ORDER" \
    --arg query_timeout "$TEST_QUERY_TIMEOUT" \
    --arg limit_resultset "$TEST_LIMIT_RESULTSET" \
    --arg hold_period "$TEST_HOLD_PERIOD" \
    --arg ramp_up_time "$TEST_RAMP_UP_TIME" \
    --arg qpm "$TEST_QPM" \
    --arg qps "$TEST_QPS" \
    --arg jmeter_version "5.6.3" \
    --arg java_version "$JAVA_VERSION" \
    --arg region "$REGION" \
    --arg availability_zone "$AVAILABILITY_ZONE" \
    --arg table_format "$TABLE_FORMAT" \
    --arg data_size "$DATA_SIZE" \
    --arg baseline_engine "$BASELINE_ENGINE" \
    --arg baseline_cluster "$BASELINE_CLUSTER" \
    --arg comparison_goal "$COMPARISON_GOAL" \
    --argjson top_10_json "$top_10_json" \
    --argjson all_queries_json "$all_queries_json" \
    --argjson total_query_count "${total_query_count:-0}" \
    --argjson bootstrap_query_count "${bootstrap_query_count:-0}" \
    --argjson jsr_sampler_count "${jsr_sampler_count:-0}" \
    --argjson jdbc_sampler_count "${jdbc_sampler_count:-0}" \
    --argjson actual_considered_queries "$actual_considered_queries" \
    --argjson total_queries "${total_queries:-0}" \
    --argjson total_success "${total_success:-0}" \
    --argjson total_failed "${total_failed:-0}" \
    --argjson total_time_taken "${total_time_taken:-0}" \
    --argjson min_time "${min_time:-0}" \
    --argjson max_time "${max_time:-0}" \
    --argjson avg_time "${avg_time:-0}" \
    --argjson median_time "${median_time:-0}" \
    --argjson p50_latency "${p50_latency:-0}" \
    --argjson p90_latency "${p90_latency:-0}" \
    --argjson p95_latency "${p95_latency:-0}" \
    --argjson p99_latency "${p99_latency:-0}" \
    --argjson unique_queries "$unique_queries" \
    --argjson error_percent "$error_percent" \
    --argjson throughput "$throughput" \
    --arg report_path "$REPORT_PATH" \
    --arg aggregate_report "$AGGREGATE_REPORT" \
    --argjson p25_latency "${p25_latency:-0}" \
    --argjson p75_latency "${p75_latency:-0}" \
    --argjson interquartile_range "${interquartile_range:-0}" \
    --argjson std_dev "${std_dev:-0}" \
    --argjson coefficient_of_variation "${coefficient_of_variation:-0}" \
    --argjson outlier_count "${outlier_count:-0}" \
    --argjson bytes_received_total "${bytes_received_total:-0}" \
    --argjson bytes_received_avg "${bytes_received_avg:-0}" \
    --argjson bytes_received_min "${bytes_received_min:-0}" \
    --argjson bytes_received_max "${bytes_received_max:-0}" \
    --argjson bytes_sent_total "${bytes_sent_total:-0}" \
    --argjson data_transfer_ratio "${data_transfer_ratio:-0}" \
    --argjson connect_time_avg "${connect_time_avg:-0}" \
    --argjson connect_time_max "${connect_time_max:-0}" \
    --argjson queries_with_connection_reuse "${queries_with_connection_reuse:-0}" \
    --argjson network_latency_avg "${network_latency_avg:-0}" \
    --argjson queries_under_1sec "${queries_under_1sec:-0}" \
    --argjson queries_1_to_5sec "${queries_1_to_5sec:-0}" \
    --argjson queries_5_to_10sec "${queries_5_to_10sec:-0}" \
    --argjson queries_over_10sec "${queries_over_10sec:-0}" \
    --argjson actual_concurrency_avg "${actual_concurrency_avg:-0}" \
    --argjson actual_concurrency_max "${actual_concurrency_max:-0}" \
    --argjson actual_test_duration_sec "${actual_test_duration_sec:-0}" \
    --argjson first_query_time "${first_query_time:-0}" \
    --argjson last_query_time "${last_query_time:-0}" \
    --argjson queries_per_minute_actual "${queries_per_minute_actual:-0}" \
    --argjson bytes_per_second "${bytes_per_second:-0}" \
    --argjson failed_queries_json "$failed_queries_json" \
    --argjson response_codes_summary "$response_codes_summary" \
    --argjson first_failure_time "${first_failure_time:-0}" \
    --argjson consecutive_failures "${consecutive_failures:-0}" \
    --argjson success_rate_first_half "${success_rate_first_half:-0}" \
    --argjson success_rate_second_half "${success_rate_second_half:-0}" \
    --argjson test_stability_score "${test_stability_score:-0}" \
    --argjson warmup_period_sec "${warmup_period_sec:-0}" \
    --argjson warmup_avg_time "${warmup_avg_time:-0}" \
    --argjson steady_state_avg_time "${steady_state_avg_time:-0}" \
    --arg test_trigger "$TEST_TRIGGER" \
    --arg test_purpose "$TEST_PURPOSE" \
    --arg previous_run_id "$PREVIOUS_RUN_ID" \
    --arg jmeter_cli_command "$JMETER_CLI_COMMAND" \
    --argjson input_files_json "$INPUT_FILES_JSON" \
    --arg connection_string_sanitized "$CONNECTION_STRING_SANITIZED" \
    --arg s3_upload_path "$S3_UPLOAD_PATH" \
    --arg jmeter_machine_cpu_cores "$JMETER_MACHINE_CPU_CORES" \
    --arg jmeter_machine_memory_gb "$JMETER_MACHINE_MEMORY_GB" \
    --arg jmeter_machine_os "$JMETER_MACHINE_OS" \
    --arg jmeter_machine_os_version "$JMETER_MACHINE_OS_VERSION" \
    --arg jmeter_machine_arch "$JMETER_MACHINE_ARCH" \
    --arg jmeter_machine_hostname "$JMETER_MACHINE_HOSTNAME" \
    --arg jmeter_memory_used_mb "$JMETER_MEMORY_USED_MB" \
    --arg jmeter_cpu_percent "$JMETER_CPU_PERCENT" \
    '{
        run_id: $run_id,
    	run_date: $run_date,
    	start_time: $start_time,
    	end_time: $end_time,
    	alias: $alias,
    	engine: $engine,
	jmeter_hostname: $jmeter_hostname,
	cluster_hostname: $cluster_hostname,
	cloud: $cloud,
	region: $region,
	availability_zone: $availability_zone,
	mode: $mode,
	tags: $tags,
	comments: $comments,
	autoscale: $autoscale,
	data_type: $data_type,
	additional_info: $additional_info,
	jmeter_run_summary: $jmeter_run_summary,
	cluster_config: $cluster_config,
	test_execution_config: {
	    test_plan_file: $test_plan_file,
	    test_properties_file: $test_properties_file,
	    concurrent_threads: $concurrent_threads,
	    ramp_up_time_min: $ramp_up_time,
	    hold_period_min: $hold_period,
	    recycle_on_eof: $recycle_on_eof,
	    random_order: $random_order,
	    query_timeout_sec: $query_timeout,
	    limit_resultset: $limit_resultset,
	    qpm: $qpm,
	    qps: $qps
	},
	connection_config: {
	    connection_properties_file: $connection_properties_file,
	    hostname: $connection_hostname,
	    port: $connection_port,
	    catalog: $connection_catalog,
	    schema: $connection_schema,
	    driver_class: $driver_class
	},
	data_source_config: {
	    queries_file: $queries_file,
	    metadata_file: $metadata_file,
	    table_format: $table_format,
	    data_size: $data_size
	},
	environment_config: {
	    jmeter_version: $jmeter_version,
	    java_version: $java_version
	},
	jmeter_machine_resources: {
	    hostname: $jmeter_machine_hostname,
	    os: $jmeter_machine_os,
	    os_version: $jmeter_machine_os_version,
	    architecture: $jmeter_machine_arch,
	    cpu_cores: $jmeter_machine_cpu_cores,
	    memory_gb: $jmeter_machine_memory_gb,
	    jmeter_process_memory_used_mb: $jmeter_memory_used_mb,
	    jmeter_process_cpu_percent: $jmeter_cpu_percent
	},
	test_execution_details: {
	    jmeter_cli_command: $jmeter_cli_command,
	    connection_string: $connection_string_sanitized,
	    input_files: $input_files_json
	},
	comparison_context: {
	    baseline_engine: $baseline_engine,
	    baseline_cluster: $baseline_cluster,
	    comparison_goal: $comparison_goal,
	    previous_run_id: $previous_run_id
	},
	test_metadata: {
	    test_trigger: $test_trigger,
	    test_purpose: $test_purpose
	},
	query_statistics: {
	    total_query_count: $total_query_count,
	    bootstrap_query_count: $bootstrap_query_count,
	    jsr_sampler_count: $jsr_sampler_count,
	    jdbc_sampler_count: $jdbc_sampler_count,
	    actual_considered_queries: $actual_considered_queries,
	    total_queries: $total_queries,
	    unique_queries: $unique_queries
	},
	test_results: {
	    total_success: $total_success,
	    total_failed: $total_failed,
	    error_percent: $error_percent,
	    consecutive_failures: $consecutive_failures,
	    success_rate_first_half: $success_rate_first_half,
	    success_rate_second_half: $success_rate_second_half,
	    test_stability_score: $test_stability_score
	},
	performance_metrics: {
	    total_time_taken_sec: $total_time_taken,
	    actual_test_duration_sec: $actual_test_duration_sec,
	    min_time_sec: $min_time,
	    max_time_sec: $max_time,
	    avg_time_sec: $avg_time,
	    median_time_sec: $median_time,
	    std_dev_sec: $std_dev,
	    coefficient_of_variation: $coefficient_of_variation,
	    p25_latency_sec: $p25_latency,
	    p50_latency_sec: $p50_latency,
	    p75_latency_sec: $p75_latency,
	    p90_latency_sec: $p90_latency,
	    p95_latency_sec: $p95_latency,
	    p99_latency_sec: $p99_latency,
	    interquartile_range_sec: $interquartile_range,
	    outlier_count: $outlier_count,
	    throughput: $throughput,
	    queries_per_minute_actual: $queries_per_minute_actual
	},
	timing_distribution: {
	    queries_under_1sec: $queries_under_1sec,
	    queries_1_to_5sec: $queries_1_to_5sec,
	    queries_5_to_10sec: $queries_5_to_10sec,
	    queries_over_10sec: $queries_over_10sec
	},
	data_transfer_metrics: {
	    bytes_received_total: $bytes_received_total,
	    bytes_received_avg: $bytes_received_avg,
	    bytes_received_min: $bytes_received_min,
	    bytes_received_max: $bytes_received_max,
	    bytes_sent_total: $bytes_sent_total,
	    data_transfer_ratio: $data_transfer_ratio,
	    bytes_per_second: $bytes_per_second
	},
	connection_metrics: {
	    connect_time_avg_ms: $connect_time_avg,
	    connect_time_max_ms: $connect_time_max,
	    queries_with_connection_reuse: $queries_with_connection_reuse,
	    network_latency_avg_ms: $network_latency_avg
	},
	concurrency_metrics: {
	    actual_concurrency_avg: $actual_concurrency_avg,
	    actual_concurrency_max: $actual_concurrency_max
	},
	warmup_analysis: {
	    warmup_period_sec: $warmup_period_sec,
	    warmup_avg_time_sec: $warmup_avg_time,
	    steady_state_avg_time_sec: $steady_state_avg_time
	},
	failure_analysis: {
	    first_failure_time: $first_failure_time,
	    response_codes_summary: $response_codes_summary,
	    failed_queries: $failed_queries_json
	},
	output_file_locations: {
	    report_path: $report_path,
	    aggregate_report: $aggregate_report,
	    s3_upload_path: $s3_upload_path
	},
        top_10_time_consuming_queries: $top_10_json,
        all_queries_avg_time: $all_queries_json
    }')
fi

# Ensure JSON generation succeeded before proceeding
if [[ $? -ne 0 || -z "$JSON_SUMMARY" ]]; then
    echo "Failed to generate JSON summary. Check jq syntax or input values."
    exit 1
fi

# Write the json summary to the TEST_RESULT_FILE...
echo "$JSON_SUMMARY" > "$TEST_RESULT_FILE"


# Define S3 path with 5-level partitioning: engine/cluster_size/benchmark/run_type/run_id
# Use S3_BASE_PATH from metadata file (fallback to default if not set)
S3_BASE_PATH="${S3_BASE_PATH:-s3://e6-jmeter/jmeter-results}"
S3_PATH_WITH_PARTITIONS="${S3_BASE_PATH}/engine=$ENGINE/cluster_size=$CLUSTER_SIZE/benchmark=$BENCHMARK_TYPE/run_type=$RUN_TYPE/run_id=$RUN_ID"

# Note: Files no longer need run_id suffix in their names since they're organized in run_id folders
# The statistics.json file keeps its original name



# Copy results to S3 (if COPY_TO_S3 is true)
if [[ "$COPY_TO_S3" == "true" ]]; then
    echo "==========================================="
    echo "Copying results to S3..."
    echo "Destination: $S3_PATH_WITH_PARTITIONS/"
    echo "Partitions:"
    echo "  - engine: $ENGINE"
    echo "  - cluster_size: $CLUSTER_SIZE"
    echo "  - benchmark: $BENCHMARK_TYPE"
    echo "  - run_type: $RUN_TYPE"
    echo "  - run_id: $RUN_ID"
    echo "==========================================="

    FILES_TO_COPY=("$JMETER_RESULT_FILE" "$AGGREGATE_REPORT" "$SUMMARY_REPORT" "$TEST_RESULT_FILE" "$STATISTICS_FILE")
    S3_ERROR=0

    for file in "${FILES_TO_COPY[@]}"; do
        if [[ -f "$file" ]]; then
            if aws s3 cp "$file" "$S3_PATH_WITH_PARTITIONS/"; then
                echo "✅ Successfully uploaded: $(basename $file)"
            else
                echo "❌ Failed to upload: $(basename $file)"
                S3_ERROR=1
            fi
        else
            echo "⚠️ File not found, skipping: $file"
        fi
    done

    if [[ $S3_ERROR -eq 0 ]]; then
        echo "✅ All files copied to S3 successfully!"

        # Update latest.json reference at run_type level (parent of run_id)
        # This allows finding the latest run without knowing the run_id
        S3_PARENT_PATH="${S3_BASE_PATH}/engine=$ENGINE/cluster_size=$CLUSTER_SIZE/benchmark=$BENCHMARK_TYPE/run_type=$RUN_TYPE"
        echo ""
        echo "Updating latest.json reference..."
        if aws s3 cp "$TEST_RESULT_FILE" "$S3_PARENT_PATH/latest.json"; then
            echo "✅ Updated latest.json at $S3_PARENT_PATH/latest.json"
        else
            echo "⚠️ Could not update latest.json"
        fi
    else
        echo "❌ Some files failed to copy to S3. Please check logs."
    fi

# After S3 copy succeeds, add Athena partitions (5-level partitioning)
if [[ $S3_ERROR -eq 0 ]]; then
    echo ""
    echo "Adding Athena partitions..."
    echo "  engine='$ENGINE', cluster_size='$CLUSTER_SIZE', benchmark='$BENCHMARK_TYPE', run_type='$RUN_TYPE', run_id='$RUN_ID'"

    # Extract bucket and path from S3_BASE_PATH for Athena
    S3_BUCKET=$(echo "$S3_BASE_PATH" | sed 's|s3://\([^/]*\)/.*|\1|')
    S3_BASE_PREFIX=$(echo "$S3_BASE_PATH" | sed 's|s3://[^/]*/||')

    # Define all tables needing partitions
    declare -A TABLE_PATHS=(
        ["detailed_results"]="engine=$ENGINE/cluster_size=$CLUSTER_SIZE/benchmark=$BENCHMARK_TYPE/run_type=$RUN_TYPE/run_id=$RUN_ID"
        ["aggregate_report"]="engine=$ENGINE/cluster_size=$CLUSTER_SIZE/benchmark=$BENCHMARK_TYPE/run_type=$RUN_TYPE/run_id=$RUN_ID"
        ["run_summary"]="engine=$ENGINE/cluster_size=$CLUSTER_SIZE/benchmark=$BENCHMARK_TYPE/run_type=$RUN_TYPE/run_id=$RUN_ID"
        ["statistics"]="engine=$ENGINE/cluster_size=$CLUSTER_SIZE/benchmark=$BENCHMARK_TYPE/run_type=$RUN_TYPE/run_id=$RUN_ID"
    )

    for table in "${!TABLE_PATHS[@]}"; do
        echo "  Adding partition for $table..."
        aws athena start-query-execution \
            --query-string "ALTER TABLE jmeter_performance_db.$table ADD IF NOT EXISTS PARTITION (engine='$ENGINE', cluster_size='$CLUSTER_SIZE', benchmark='$BENCHMARK_TYPE', run_type='$RUN_TYPE', run_id='$RUN_ID') LOCATION 's3://${S3_BUCKET}/${S3_BASE_PREFIX}/${TABLE_PATHS[$table]}/'" \
            --query-execution-context Database=jmeter_performance_db \
            --result-configuration OutputLocation=s3://e6-jmeter/athena-query-results/ &
    done
    wait
    echo "✅ Athena partitions added"

echo ""
echo "==========================================="
echo "Test and Upload Process Complete!"
echo "==========================================="
echo "S3 Location: $S3_PATH_WITH_PARTITIONS"
echo "Latest Ref:  $S3_PARENT_PATH/latest.json"
echo "Local File:  $TEST_RESULT_FILE"
echo "==========================================="
fi

else
    echo "⏩ Skipping S3 copy (COPY_TO_S3 is not true)."
fi

echo "Test Results :"
cat $TEST_RESULT_FILE
exit 0

