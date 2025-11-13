#!/bin/bash
# Utility to manage invalid JMeter test runs by moving them to INVALID/ subfolder
# This automatically excludes them from index generation and analysis

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

S3_BUCKET="s3://e6-jmeter/jmeter-results"
INVALID_RUNS_LOG="utilities/invalidated_runs.txt"

show_usage() {
    cat << EOF
${BLUE}JMeter Invalid Runs Management Utility${NC}

Usage: $0 <action> <run_id> [reason]

${YELLOW}Actions:${NC}
  invalidate      Mark a run as invalid (move to INVALID/ folder)
  restore         Restore an invalid run (move back to valid location)
  list-invalid    List all invalid runs across all configurations
  list-valid      List all valid runs (optionally filter by run_id pattern)

${YELLOW}Arguments:${NC}
  run_id          Run ID in format YYYYMMDD-HHMMSS
  reason          Reason for invalidation (optional but recommended)

${YELLOW}Examples:${NC}
  # Mark run as invalid with reason
  $0 invalidate 20251102-112518 "Wrong cluster configuration - was 2x2 instead of 4x4"

  # Mark run as invalid without reason
  $0 invalidate 20251102-112518

  # Restore run to valid status
  $0 restore 20251102-112518

  # List all invalid runs
  $0 list-invalid

  # List all valid runs
  $0 list-valid

${YELLOW}Structure:${NC}
  Valid:   s3://.../run_type=concurrency_2/run_id=20251102-112518/
  Invalid: s3://.../run_type=concurrency_2/INVALID/20251102-112518/

${YELLOW}After invalidating:${NC}
  - Run will be automatically excluded from future index generation
  - Regenerate indices for affected configurations
  - Reasons are tracked in: ${INVALID_RUNS_LOG}

EOF
    exit 1
}

# Check if AWS CLI is available
if ! command -v aws &> /dev/null; then
    echo -e "${RED}Error: AWS CLI is not installed${NC}"
    exit 1
fi

ACTION=$1
RUN_ID=$2
REASON=$3

# Validate action
if [[ -z "$ACTION" ]]; then
    show_usage
fi

# Validate run_id for actions that need it
if [[ "$ACTION" != "list-invalid" && "$ACTION" != "list-valid" ]] && [[ -z "$RUN_ID" ]]; then
    echo -e "${RED}Error: run_id is required${NC}"
    show_usage
fi

# Validate run_id format
if [[ -n "$RUN_ID" ]] && [[ ! "$RUN_ID" =~ ^[0-9]{8}-[0-9]{6}$ ]]; then
    echo -e "${RED}Error: Invalid run_id format. Expected: YYYYMMDD-HHMMSS${NC}"
    echo -e "${YELLOW}Example: 20251102-112518${NC}"
    exit 1
fi

# Function to find run in S3 and return full path
find_run() {
    local run_id=$1
    local pattern=$2  # "run_id=" or "INVALID/"

    echo -e "${YELLOW}Searching for run ${run_id} in S3...${NC}" >&2

    local result=$(aws s3 ls "${S3_BUCKET}/" --recursive | grep "${pattern}${run_id}/" | head -1)

    if [[ -z "$result" ]]; then
        return 1
    fi

    # Extract the relative path
    echo "$result" | awk '{print $4}'
}

# Function to extract configuration from path
extract_config_from_path() {
    local path=$1

    # Extract engine, cluster, benchmark, run_type from path
    local engine=$(echo "$path" | grep -oP 'engine=\K[^/]+')
    local cluster=$(echo "$path" | grep -oP 'cluster_size=\K[^/]+')
    local benchmark=$(echo "$path" | grep -oP 'benchmark=\K[^/]+')
    local run_type=$(echo "$path" | grep -oP 'run_type=\K[^/]+')

    echo "${engine}|${cluster}|${benchmark}|${run_type}"
}

# Function to log invalidation reason
log_invalidation() {
    local run_id=$1
    local config=$2
    local reason=$3

    # Create log file if it doesn't exist
    if [[ ! -f "$INVALID_RUNS_LOG" ]]; then
        echo "# Invalidated JMeter Test Runs" > "$INVALID_RUNS_LOG"
        echo "# Format: run_id | engine | cluster_size | benchmark | run_type | date_invalidated | reason" >> "$INVALID_RUNS_LOG"
        echo "" >> "$INVALID_RUNS_LOG"
    fi

    local date_invalidated=$(date '+%Y-%m-%d %H:%M:%S')
    echo "${run_id} | ${config} | ${date_invalidated} | ${reason}" >> "$INVALID_RUNS_LOG"
}

# Function to remove from invalidation log
remove_from_log() {
    local run_id=$1

    if [[ -f "$INVALID_RUNS_LOG" ]]; then
        # Create backup
        cp "$INVALID_RUNS_LOG" "${INVALID_RUNS_LOG}.bak"

        # Remove line with run_id
        grep -v "^${run_id} " "$INVALID_RUNS_LOG" > "${INVALID_RUNS_LOG}.tmp" || true
        mv "${INVALID_RUNS_LOG}.tmp" "$INVALID_RUNS_LOG"
    fi
}

# Function to invalidate a run
invalidate_run() {
    local run_id=$1
    local reason=${2:-"No reason provided"}

    # Find the valid run
    local relative_path=$(find_run "$run_id" "run_id=")

    if [[ -z "$relative_path" ]]; then
        echo -e "${RED}Error: Valid run ${run_id} not found in S3${NC}"
        echo -e "${YELLOW}Maybe it's already invalid? Try: $0 list-invalid${NC}"
        exit 1
    fi

    local old_path="${S3_BUCKET}/${relative_path}"

    # Extract directory path and construct new path
    local dir_path=$(dirname "$relative_path")
    local new_path="${S3_BUCKET}/${dir_path}/INVALID/${run_id}/"

    # Extract configuration for logging
    local config=$(extract_config_from_path "$relative_path")

    echo ""
    echo -e "${YELLOW}═══════════════════════════════════════════════════════════${NC}"
    echo -e "${YELLOW}         INVALIDATE RUN${NC}"
    echo -e "${YELLOW}═══════════════════════════════════════════════════════════${NC}"
    echo -e "Run ID:     ${BLUE}${run_id}${NC}"
    echo -e "Config:     ${config/|/ | }"
    echo -e "Reason:     ${reason}"
    echo ""
    echo -e "Old path:   ${old_path}"
    echo -e "New path:   ${new_path}"
    echo -e "${YELLOW}═══════════════════════════════════════════════════════════${NC}"
    echo ""

    # Ask for confirmation
    read -p "Proceed with invalidation? (y/n) " -n 1 -r
    echo ""

    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${YELLOW}Cancelled${NC}"
        exit 0
    fi

    echo -e "${YELLOW}Moving run to INVALID folder...${NC}"

    # Use aws s3 mv for atomic move
    if aws s3 mv "${old_path}" "${new_path}" --recursive; then
        echo -e "${GREEN}✅ Run ${run_id} successfully marked as invalid${NC}"

        # Log the invalidation
        log_invalidation "$run_id" "$config" "$reason"
        echo -e "${GREEN}✅ Logged to ${INVALID_RUNS_LOG}${NC}"

        echo ""
        echo -e "${YELLOW}Next steps:${NC}"
        echo "1. Regenerate index for this configuration:"
        echo "   PYTHONPATH=utilities/athena python3 utilities/athena/generate_runs_index.py \\"
        echo "     \"s3://e6-jmeter/jmeter-results/$(echo $relative_path | cut -d'/' -f1-4)/\" --upload"
        echo ""
        echo "2. Or regenerate all indices:"
        echo "   bash /tmp/regenerate_all_indices.sh"
    else
        echo -e "${RED}❌ Failed to move run${NC}"
        exit 1
    fi
}

# Function to restore a run
restore_run() {
    local run_id=$1

    # Find the invalid run
    local relative_path=$(find_run "$run_id" "INVALID/")

    if [[ -z "$relative_path" ]]; then
        echo -e "${RED}Error: Invalid run ${run_id} not found in S3${NC}"
        echo -e "${YELLOW}Maybe it's already valid? Try: $0 list-valid${NC}"
        exit 1
    fi

    local old_path="${S3_BUCKET}/${relative_path}"

    # Construct new path (remove /INVALID/ from path)
    local dir_path=$(dirname $(dirname "$relative_path"))
    local new_path="${S3_BUCKET}/${dir_path}/run_id=${run_id}/"

    # Extract configuration
    local config=$(extract_config_from_path "$relative_path")

    echo ""
    echo -e "${YELLOW}═══════════════════════════════════════════════════════════${NC}"
    echo -e "${YELLOW}         RESTORE RUN${NC}"
    echo -e "${YELLOW}═══════════════════════════════════════════════════════════${NC}"
    echo -e "Run ID:     ${BLUE}${run_id}${NC}"
    echo -e "Config:     ${config/|/ | }"
    echo ""
    echo -e "Old path:   ${old_path}"
    echo -e "New path:   ${new_path}"
    echo -e "${YELLOW}═══════════════════════════════════════════════════════════${NC}"
    echo ""

    # Ask for confirmation
    read -p "Proceed with restoration? (y/n) " -n 1 -r
    echo ""

    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${YELLOW}Cancelled${NC}"
        exit 0
    fi

    echo -e "${YELLOW}Restoring run to valid location...${NC}"

    # Use aws s3 mv for atomic move
    if aws s3 mv "${old_path}" "${new_path}" --recursive; then
        echo -e "${GREEN}✅ Run ${run_id} successfully restored${NC}"

        # Remove from invalidation log
        remove_from_log "$run_id"
        echo -e "${GREEN}✅ Removed from ${INVALID_RUNS_LOG}${NC}"

        echo ""
        echo -e "${YELLOW}Next steps:${NC}"
        echo "Regenerate index for this configuration to include the restored run."
    else
        echo -e "${RED}❌ Failed to restore run${NC}"
        exit 1
    fi
}

# Function to list all invalid runs
list_invalid_runs() {
    echo -e "${YELLOW}Searching for invalid runs in S3...${NC}"
    echo ""

    local found=0

    # Search for INVALID folders
    aws s3 ls "${S3_BUCKET}/" --recursive | grep "/INVALID/" | awk '{print $4}' | while read -r path; do
        if [[ $path =~ /INVALID/([0-9]{8}-[0-9]{6})/ ]]; then
            local run_id="${BASH_REMATCH[1]}"
            local config=$(extract_config_from_path "$path")

            echo -e "${RED}❌ ${run_id}${NC}"
            echo -e "   Config: ${config/|/ | }"
            echo -e "   Path:   ${S3_BUCKET}/${path}"

            # Check if reason exists in log
            if [[ -f "$INVALID_RUNS_LOG" ]]; then
                local reason=$(grep "^${run_id} " "$INVALID_RUNS_LOG" | cut -d'|' -f6- | xargs)
                if [[ -n "$reason" ]]; then
                    echo -e "   Reason: ${reason}"
                fi
            fi
            echo ""

            found=1
        fi
    done | sort -u

    if [[ $found -eq 0 ]]; then
        echo -e "${GREEN}No invalid runs found${NC}"
    else
        echo -e "${YELLOW}To restore a run: $0 restore <run_id>${NC}"
    fi
}

# Function to list valid runs
list_valid_runs() {
    echo -e "${YELLOW}Listing valid runs in S3...${NC}"
    echo ""

    aws s3 ls "${S3_BUCKET}/" --recursive | grep "run_id=" | grep -v "/INVALID/" | awk '{print $4}' | while read -r path; do
        if [[ $path =~ run_id=([0-9]{8}-[0-9]{6})/ ]]; then
            local run_id="${BASH_REMATCH[1]}"
            local config=$(extract_config_from_path "$path")

            echo -e "${GREEN}✅ ${run_id}${NC} | ${config/|/ | }"
        fi
    done | sort -u
}

# Main action dispatcher
case "$ACTION" in
    invalidate)
        invalidate_run "$RUN_ID" "$REASON"
        ;;
    restore)
        restore_run "$RUN_ID"
        ;;
    list-invalid)
        list_invalid_runs
        ;;
    list-valid)
        list_valid_runs
        ;;
    *)
        echo -e "${RED}Error: Unknown action '$ACTION'${NC}"
        show_usage
        ;;
esac
