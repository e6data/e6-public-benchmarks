#!/bin/bash

# Compare JMeter test results from S3
# Handles 4-level S3 partitioning: engine/cluster_size/benchmark/run_type

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

S3_BASE="s3://e6-jmeter/jmeter-results"
TEMP_DIR="/tmp/jmeter_s3_comparison"

usage() {
    cat <<EOF
Usage: $0 [OPTIONS]

Compare JMeter test results from S3

OPTIONS:
    -h, --help              Show this help message

COMPARISON MODES:
    --latest                Compare latest runs between two engines
                            Example: $0 --latest --engine1 e6data --engine2 dbr --cluster-size XS --benchmark tpcds_29_1tb --run-type sequential

    --run-id                Compare specific run IDs
                            Example: $0 --run-id --id1 20251029-204836 --id2 20251029-172220

    --best                  Compare best runs (lowest avg response time)
                            Example: $0 --best --engine1 e6data --engine2 dbr --cluster-size XS --benchmark tpcds_29_1tb --run-type sequential

    --list                  List available runs
                            Example: $0 --list --engine e6data --cluster-size XS --benchmark tpcds_29_1tb --run-type sequential

PARAMETERS:
    --engine1 <name>        First engine name (e6data, dbr, etc.)
    --engine2 <name>        Second engine name
    --engine <name>         Engine name (for --list mode)
    --cluster-size <size>   Cluster size (XS, S, M, L, etc.)
    --benchmark <name>      Benchmark name (tpcds_29_1tb, etc.)
    --run-type <type>       Run type (sequential, concurrency_N, etc.)
    --id1 <run_id>          First run ID (for --run-id mode)
    --id2 <run_id>          Second run ID (for --run-id mode)
    --tag <tag>             Filter by tag (run-1, run-2, warmed-up, cold-start)
    --output <file>         Save comparison report to file

EXAMPLES:
    # Compare latest cold-start runs
    $0 --latest --engine1 e6data --engine2 dbr --cluster-size XS --benchmark tpcds_29_1tb --run-type sequential --tag run-1

    # Compare specific run IDs
    $0 --run-id --id1 20251029-204836 --id2 20251029-172220

    # List all available runs for e6data
    $0 --list --engine e6data --cluster-size XS --benchmark tpcds_29_1tb --run-type sequential

    # Compare best runs (lowest average response time)
    $0 --best --engine1 e6data --engine2 dbr --cluster-size XS --benchmark tpcds_29_1tb --run-type sequential

EOF
    exit 0
}

log_info() {
    echo -e "${BLUE}ℹ${NC} $1"
}

log_success() {
    echo -e "${GREEN}✓${NC} $1"
}

log_error() {
    echo -e "${RED}✗${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

# List available runs for an engine
list_runs() {
    local engine=$1
    local cluster_size=$2
    local benchmark=$3
    local run_type=$4

    local s3_path="${S3_BASE}/engine=${engine}/cluster_size=${cluster_size}/benchmark=${benchmark}/run_type=${run_type}"

    log_info "Listing runs in: $s3_path"
    echo ""

    aws s3 ls "$s3_path/" --recursive | grep "test_result.*\.json$" | while read -r line; do
        # Extract run ID from filename
        run_id=$(echo "$line" | grep -oE '[0-9]{8}-[0-9]{6}' | head -1)
        size=$(echo "$line" | awk '{print $3}')
        date=$(echo "$line" | awk '{print $1, $2}')

        if [[ -n "$run_id" ]]; then
            # Download and extract metadata
            temp_file="${TEMP_DIR}/temp_${run_id}.json"
            mkdir -p "$TEMP_DIR"

            aws s3 cp "${s3_path}/test_result_${run_id}.json" "$temp_file" --quiet 2>/dev/null || continue

            tags=$(jq -r '.tags // "no-tags"' "$temp_file" 2>/dev/null || echo "no-tags")
            avg_time=$(jq -r '.performance_metrics.avg_time_sec // "N/A"' "$temp_file" 2>/dev/null || echo "N/A")

            printf "%-20s  %-10s  %-30s  Avg: %-6s  Date: %s\n" "$run_id" "$size" "$tags" "$avg_time" "$date"

            rm -f "$temp_file"
        fi
    done
}

# Get latest run for an engine
get_latest_run() {
    local engine=$1
    local cluster_size=$2
    local benchmark=$3
    local run_type=$4
    local tag_filter=$5

    local s3_path="${S3_BASE}/engine=${engine}/cluster_size=${cluster_size}/benchmark=${benchmark}/run_type=${run_type}"

    mkdir -p "$TEMP_DIR"

    # Get all test_result files, sorted by timestamp
    local latest_file=""
    local latest_run_id=""

    if [[ -n "$tag_filter" ]]; then
        log_info "Finding latest run for $engine with tag filter: $tag_filter"

        # Need to download and check tags
        while read -r line; do
            run_id=$(echo "$line" | grep -oE '[0-9]{8}-[0-9]{6}' | head -1)

            if [[ -n "$run_id" ]]; then
                temp_file="${TEMP_DIR}/temp_${run_id}.json"
                aws s3 cp "${s3_path}/test_result_${run_id}.json" "$temp_file" --quiet 2>/dev/null || continue

                tags=$(jq -r '.tags // ""' "$temp_file" 2>/dev/null || echo "")

                if [[ "$tags" == *"$tag_filter"* ]]; then
                    latest_file="${s3_path}/test_result_${run_id}.json"
                    latest_run_id="$run_id"
                    rm -f "$temp_file"
                    break
                fi

                rm -f "$temp_file"
            fi
        done < <(aws s3 ls "$s3_path/" --recursive | grep "test_result.*\.json$" | sort -r)
    else
        # Just get the latest file by timestamp
        latest_run_id=$(aws s3 ls "$s3_path/" --recursive | grep "test_result.*\.json$" | sort -r | head -1 | grep -oE '[0-9]{8}-[0-9]{6}' | head -1)
        latest_file="${s3_path}/test_result_${latest_run_id}.json"
    fi

    if [[ -z "$latest_file" ]]; then
        log_error "No runs found for $engine"
        return 1
    fi

    log_success "Found latest run: $latest_run_id"
    echo "$latest_file"
}

# Get best run (lowest avg response time)
get_best_run() {
    local engine=$1
    local cluster_size=$2
    local benchmark=$3
    local run_type=$4
    local tag_filter=$5

    local s3_path="${S3_BASE}/engine=${engine}/cluster_size=${cluster_size}/benchmark=${benchmark}/run_type=${run_type}"

    log_info "Finding best run for $engine (lowest avg response time)..."

    mkdir -p "$TEMP_DIR"

    local best_file=""
    local best_run_id=""
    local best_avg=999999

    aws s3 ls "$s3_path/" --recursive | grep "test_result.*\.json$" | while read -r line; do
        run_id=$(echo "$line" | grep -oE '[0-9]{8}-[0-9]{6}' | head -1)

        if [[ -n "$run_id" ]]; then
            temp_file="${TEMP_DIR}/temp_${run_id}.json"
            aws s3 cp "${s3_path}/test_result_${run_id}.json" "$temp_file" --quiet 2>/dev/null || continue

            tags=$(jq -r '.tags // ""' "$temp_file" 2>/dev/null || echo "")
            avg_time=$(jq -r '.performance_metrics.avg_time_sec // 999999' "$temp_file" 2>/dev/null || echo "999999")

            # Check tag filter if specified
            if [[ -n "$tag_filter" ]] && [[ "$tags" != *"$tag_filter"* ]]; then
                rm -f "$temp_file"
                continue
            fi

            # Check if this is the best so far
            if (( $(echo "$avg_time < $best_avg" | bc -l) )); then
                best_avg=$avg_time
                best_file="${s3_path}/test_result_${run_id}.json"
                best_run_id="$run_id"
            fi

            rm -f "$temp_file"
        fi
    done

    if [[ -z "$best_file" ]]; then
        log_error "No runs found for $engine"
        return 1
    fi

    log_success "Found best run: $best_run_id (avg: ${best_avg}s)"
    echo "$best_file"
}

# Download and compare two runs
compare_runs() {
    local file1=$1
    local file2=$2
    local output_file=$3

    mkdir -p "$TEMP_DIR"

    local local_file1="${TEMP_DIR}/run1.json"
    local local_file2="${TEMP_DIR}/run2.json"

    log_info "Downloading run 1..."
    aws s3 cp "$file1" "$local_file1" --quiet
    log_success "Downloaded: $(basename "$file1")"

    log_info "Downloading run 2..."
    aws s3 cp "$file2" "$local_file2" --quiet
    log_success "Downloaded: $(basename "$file2")"

    echo ""
    log_info "Comparing runs..."
    echo ""

    # Run comparison
    if [[ -f "./utilities/compare_jmeter_runs.sh" ]]; then
        if [[ -n "$output_file" ]]; then
            ./utilities/compare_jmeter_runs.sh "$local_file1" "$local_file2" | tee "$output_file"
        else
            ./utilities/compare_jmeter_runs.sh "$local_file1" "$local_file2"
        fi
    else
        # Fallback to manual comparison
        compare_manual "$local_file1" "$local_file2" "$output_file"
    fi
}

# Manual comparison if comparison script not available
compare_manual() {
    local file1=$1
    local file2=$2
    local output_file=$3

    exec > >(tee -a "${output_file:-/dev/stdout}")

    printf "====================================================================================================\n"
    printf "PERFORMANCE COMPARISON\n"
    printf "====================================================================================================\n\n"

    printf "RUN 1:\n"
    jq -r '"  Run ID: \(.run_id)\n  Engine: \(.engine)\n  Tags: \(.tags)\n  Cluster: \(.cluster_hostname // .cluster_config.cluster_id)"' "$file1"

    printf "\nRUN 2:\n"
    jq -r '"  Run ID: \(.run_id)\n  Engine: \(.engine)\n  Tags: \(.tags)\n  Cluster: \(.cluster_hostname // .cluster_config.cluster_id)"' "$file2"

    printf "\nPERFORMANCE METRICS:\n"
    printf -- "----------------------------------------------------------------------------------------------------\n"
    printf "%-25s %-15s %-15s %-20s\n" "Metric" "Run 1" "Run 2" "Winner"
    printf -- "----------------------------------------------------------------------------------------------------\n"

    # Extract and compare metrics
    local avg1=$(jq -r '.performance_metrics.avg_time_sec' "$file1")
    local avg2=$(jq -r '.performance_metrics.avg_time_sec' "$file2")
    local p50_1=$(jq -r '.performance_metrics.p50_latency_sec' "$file1")
    local p50_2=$(jq -r '.performance_metrics.p50_latency_sec' "$file2")
    local p99_1=$(jq -r '.performance_metrics.p99_latency_sec' "$file1")
    local p99_2=$(jq -r '.performance_metrics.p99_latency_sec' "$file2")

    printf "%-25s %-15.2f %-15.2f %-20s\n" "Avg Response Time (s)" "$avg1" "$avg2" \
        "$(if (( $(echo "$avg1 < $avg2" | bc -l) )); then echo "✅ Run 1"; else echo "✅ Run 2"; fi)"
    printf "%-25s %-15.2f %-15.2f %-20s\n" "Median p50 (s)" "$p50_1" "$p50_2" \
        "$(if (( $(echo "$p50_1 < $p50_2" | bc -l) )); then echo "✅ Run 1"; else echo "✅ Run 2"; fi)"
    printf "%-25s %-15.2f %-15.2f %-20s\n" "p99 Latency (s)" "$p99_1" "$p99_2" \
        "$(if (( $(echo "$p99_1 < $p99_2" | bc -l) )); then echo "✅ Run 1"; else echo "✅ Run 2"; fi)"

    printf "====================================================================================================\n"
}

# Parse command line arguments
MODE=""
ENGINE1=""
ENGINE2=""
ENGINE=""
CLUSTER_SIZE=""
BENCHMARK=""
RUN_TYPE=""
RUN_ID1=""
RUN_ID2=""
TAG_FILTER=""
OUTPUT_FILE=""

while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help)
            usage
            ;;
        --latest)
            MODE="latest"
            shift
            ;;
        --run-id)
            MODE="run-id"
            shift
            ;;
        --best)
            MODE="best"
            shift
            ;;
        --list)
            MODE="list"
            shift
            ;;
        --engine1)
            ENGINE1="$2"
            shift 2
            ;;
        --engine2)
            ENGINE2="$2"
            shift 2
            ;;
        --engine)
            ENGINE="$2"
            shift 2
            ;;
        --cluster-size)
            CLUSTER_SIZE="$2"
            shift 2
            ;;
        --benchmark)
            BENCHMARK="$2"
            shift 2
            ;;
        --run-type)
            RUN_TYPE="$2"
            shift 2
            ;;
        --id1)
            RUN_ID1="$2"
            shift 2
            ;;
        --id2)
            RUN_ID2="$2"
            shift 2
            ;;
        --tag)
            TAG_FILTER="$2"
            shift 2
            ;;
        --output)
            OUTPUT_FILE="$2"
            shift 2
            ;;
        *)
            log_error "Unknown option: $1"
            usage
            ;;
    esac
done

# Validate and execute based on mode
case $MODE in
    list)
        if [[ -z "$ENGINE" ]] || [[ -z "$CLUSTER_SIZE" ]] || [[ -z "$BENCHMARK" ]] || [[ -z "$RUN_TYPE" ]]; then
            log_error "Missing required parameters for --list mode"
            usage
        fi
        list_runs "$ENGINE" "$CLUSTER_SIZE" "$BENCHMARK" "$RUN_TYPE"
        ;;

    latest)
        if [[ -z "$ENGINE1" ]] || [[ -z "$ENGINE2" ]] || [[ -z "$CLUSTER_SIZE" ]] || [[ -z "$BENCHMARK" ]] || [[ -z "$RUN_TYPE" ]]; then
            log_error "Missing required parameters for --latest mode"
            usage
        fi

        file1=$(get_latest_run "$ENGINE1" "$CLUSTER_SIZE" "$BENCHMARK" "$RUN_TYPE" "$TAG_FILTER")
        file2=$(get_latest_run "$ENGINE2" "$CLUSTER_SIZE" "$BENCHMARK" "$RUN_TYPE" "$TAG_FILTER")

        compare_runs "$file1" "$file2" "$OUTPUT_FILE"
        ;;

    best)
        if [[ -z "$ENGINE1" ]] || [[ -z "$ENGINE2" ]] || [[ -z "$CLUSTER_SIZE" ]] || [[ -z "$BENCHMARK" ]] || [[ -z "$RUN_TYPE" ]]; then
            log_error "Missing required parameters for --best mode"
            usage
        fi

        file1=$(get_best_run "$ENGINE1" "$CLUSTER_SIZE" "$BENCHMARK" "$RUN_TYPE" "$TAG_FILTER")
        file2=$(get_best_run "$ENGINE2" "$CLUSTER_SIZE" "$BENCHMARK" "$RUN_TYPE" "$TAG_FILTER")

        compare_runs "$file1" "$file2" "$OUTPUT_FILE"
        ;;

    run-id)
        if [[ -z "$RUN_ID1" ]] || [[ -z "$RUN_ID2" ]]; then
            log_error "Missing required parameters for --run-id mode"
            usage
        fi

        # Find files by run ID (search across all engines)
        log_info "Searching for run ID: $RUN_ID1"
        file1=$(aws s3 ls "$S3_BASE/" --recursive | grep "test_result_${RUN_ID1}.json" | head -1 | awk '{print $4}')

        log_info "Searching for run ID: $RUN_ID2"
        file2=$(aws s3 ls "$S3_BASE/" --recursive | grep "test_result_${RUN_ID2}.json" | head -1 | awk '{print $4}')

        if [[ -z "$file1" ]] || [[ -z "$file2" ]]; then
            log_error "Could not find one or both run IDs"
            exit 1
        fi

        compare_runs "${S3_BASE}/${file1}" "${S3_BASE}/${file2}" "$OUTPUT_FILE"
        ;;

    *)
        log_error "No mode specified"
        usage
        ;;
esac

# Cleanup
rm -rf "$TEMP_DIR"

log_success "Done!"
