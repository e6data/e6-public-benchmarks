#!/bin/bash

# Script: cleanup_logs.sh
# Purpose: Clean up JMeter logs, test reports, and temporary files
# Usage: ./utilities/cleanup_logs.sh [options]

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color
BOLD='\033[1m'

# Default values
DRY_RUN=false
KEEP_DAYS=3
INTERACTIVE=true
CLEAN_REPORTS=false
CLEAN_JMETER_LOGS=false
CLEAN_DASHBOARDS=false
CLEAN_JSON_RESULTS=false
CLEAN_ALL=false
VERBOSE=false

# Script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Directories to clean
REPORTS_DIR="$PROJECT_ROOT/reports"
JMETER_BIN_DIR="$PROJECT_ROOT/apache-jmeter-5.6.3/bin"

# Display help
show_help() {
    cat << EOF
${BOLD}JMeter Log Cleanup Script${NC}

${BOLD}USAGE:${NC}
    $0 [OPTIONS]

${BOLD}OPTIONS:${NC}
    -h, --help              Show this help message
    -d, --days DAYS         Keep files newer than DAYS days (default: 3)
    -n, --dry-run           Show what would be deleted without actually deleting
    -y, --yes               Skip confirmation prompts (non-interactive mode)
    -v, --verbose           Show detailed output

    ${BOLD}Cleanup Targets:${NC}
    -r, --reports           Clean old report CSV files (AggregateReport_*, JmeterResultFile_*)
    -l, --logs              Clean JMeter log files (jmeter_*.log and jmeter.log)
    -D, --dashboards        Clean old HTML dashboard directories (dashboard_*)
    -j, --json              Clean old JSON result files (test_result_*, statistics_*)
    -a, --all               Clean all log and report files (combines all above)

${BOLD}EXAMPLES:${NC}
    # Interactive mode - prompts for what to clean
    $0

    # Dry run - see what would be deleted (reports older than 3 days)
    $0 --reports --dry-run

    # Clean reports older than 7 days without confirmation
    $0 --reports --days 7 --yes

    # Clean everything older than 60 days
    $0 --all --days 60 --yes

    # Clean only JMeter logs (latest only)
    $0 --logs --yes

    # Verbose dry run to see all file details
    $0 --all --days 14 --dry-run --verbose

${BOLD}NOTES:${NC}
    - By default, runs in interactive mode with 3-day retention
    - Timestamped JMeter logs (jmeter_*.log) older than KEEP_DAYS are deleted
    - The current jmeter.log file in bin directory is truncated (not deleted)
    - Dashboard directories can consume significant disk space
    - Use --dry-run first to preview what will be deleted
    - Files currently in use will not be deleted

EOF
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help)
            show_help
            exit 0
            ;;
        -d|--days)
            KEEP_DAYS="$2"
            shift 2
            ;;
        -n|--dry-run)
            DRY_RUN=true
            shift
            ;;
        -y|--yes)
            INTERACTIVE=false
            shift
            ;;
        -v|--verbose)
            VERBOSE=true
            shift
            ;;
        -r|--reports)
            CLEAN_REPORTS=true
            shift
            ;;
        -l|--logs)
            CLEAN_JMETER_LOGS=true
            shift
            ;;
        -D|--dashboards)
            CLEAN_DASHBOARDS=true
            shift
            ;;
        -j|--json)
            CLEAN_JSON_RESULTS=true
            shift
            ;;
        -a|--all)
            CLEAN_ALL=true
            CLEAN_REPORTS=true
            CLEAN_JMETER_LOGS=true
            CLEAN_DASHBOARDS=true
            CLEAN_JSON_RESULTS=true
            shift
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Validate KEEP_DAYS is a number
if ! [[ "$KEEP_DAYS" =~ ^[0-9]+$ ]]; then
    echo -e "${RED}Error: --days must be a positive number${NC}"
    exit 1
fi

# Display banner
echo -e "${BOLD}${BLUE}═══════════════════════════════════════════════════════════════════${NC}"
echo -e "${BOLD}${BLUE}           JMeter Log Cleanup Utility${NC}"
echo -e "${BOLD}${BLUE}═══════════════════════════════════════════════════════════════════${NC}"
echo

if [ "$DRY_RUN" = true ]; then
    echo -e "${YELLOW}Running in DRY RUN mode - no files will be deleted${NC}"
    echo
fi

# Interactive mode - prompt user for cleanup options
if [ "$INTERACTIVE" = true ] && [ "$CLEAN_ALL" = false ]; then
    echo -e "${CYAN}What would you like to clean?${NC}"
    echo

    read -p "Clean report CSV files older than $KEEP_DAYS days? [y/N]: " response
    [[ "$response" =~ ^[Yy]$ ]] && CLEAN_REPORTS=true

    read -p "Clean JMeter log files? [y/N]: " response
    [[ "$response" =~ ^[Yy]$ ]] && CLEAN_JMETER_LOGS=true

    read -p "Clean HTML dashboard directories older than $KEEP_DAYS days? [y/N]: " response
    [[ "$response" =~ ^[Yy]$ ]] && CLEAN_DASHBOARDS=true

    read -p "Clean JSON result files older than $KEEP_DAYS days? [y/N]: " response
    [[ "$response" =~ ^[Yy]$ ]] && CLEAN_JSON_RESULTS=true

    echo

    # Check if nothing was selected
    if [ "$CLEAN_REPORTS" = false ] && [ "$CLEAN_JMETER_LOGS" = false ] && \
       [ "$CLEAN_DASHBOARDS" = false ] && [ "$CLEAN_JSON_RESULTS" = false ]; then
        echo -e "${YELLOW}No cleanup options selected. Exiting.${NC}"
        exit 0
    fi
fi

# Statistics
TOTAL_FILES_FOUND=0
TOTAL_DIRS_FOUND=0
TOTAL_SIZE=0
FILES_DELETED=0
DIRS_DELETED=0

# Function to get file size in bytes (cross-platform)
get_file_size() {
    local file="$1"
    if [[ "$OSTYPE" == "darwin"* ]]; then
        stat -f%z "$file" 2>/dev/null || echo 0
    else
        stat -c%s "$file" 2>/dev/null || echo 0
    fi
}

# Function to format bytes to human readable
format_size() {
    local bytes=$1
    if [ "$bytes" -lt 1024 ]; then
        echo "${bytes}B"
    elif [ "$bytes" -lt 1048576 ]; then
        echo "$(awk -v b="$bytes" 'BEGIN {printf "%.2f", b/1024}')KB"
    elif [ "$bytes" -lt 1073741824 ]; then
        echo "$(awk -v b="$bytes" 'BEGIN {printf "%.2f", b/1048576}')MB"
    else
        echo "$(awk -v b="$bytes" 'BEGIN {printf "%.2f", b/1073741824}')GB"
    fi
}

# Function to delete file with logging
delete_file() {
    local file="$1"
    local size=$(get_file_size "$file")
    TOTAL_SIZE=$((TOTAL_SIZE + size))
    TOTAL_FILES_FOUND=$((TOTAL_FILES_FOUND + 1))

    if [ "$VERBOSE" = true ]; then
        echo -e "   ${YELLOW}Found:${NC} $(basename "$file") ($(format_size $size))"
    fi

    if [ "$DRY_RUN" = false ]; then
        if rm "$file" 2>/dev/null; then
            FILES_DELETED=$((FILES_DELETED + 1))
            [ "$VERBOSE" = true ] && echo -e "   ${GREEN}✓ Deleted${NC}"
        else
            echo -e "   ${RED}✗ Failed to delete: $file${NC}"
        fi
    fi
}

# Function to delete directory with logging
delete_directory() {
    local dir="$1"
    local size=$(du -sk "$dir" 2>/dev/null | cut -f1)
    size=$((size * 1024))  # Convert KB to bytes
    TOTAL_SIZE=$((TOTAL_SIZE + size))
    TOTAL_DIRS_FOUND=$((TOTAL_DIRS_FOUND + 1))

    if [ "$VERBOSE" = true ]; then
        echo -e "   ${YELLOW}Found:${NC} $(basename "$dir")/ ($(format_size $size))"
    fi

    if [ "$DRY_RUN" = false ]; then
        if rm -rf "$dir" 2>/dev/null; then
            DIRS_DELETED=$((DIRS_DELETED + 1))
            [ "$VERBOSE" = true ] && echo -e "   ${GREEN}✓ Deleted${NC}"
        else
            echo -e "   ${RED}✗ Failed to delete: $dir${NC}"
        fi
    fi
}

# Clean report CSV files
if [ "$CLEAN_REPORTS" = true ]; then
    echo -e "${CYAN}Cleaning report CSV files (older than $KEEP_DAYS days)...${NC}"

    if [ -d "$REPORTS_DIR" ]; then
        file_count=0
        while IFS= read -r -d '' file; do
            delete_file "$file"
            file_count=$((file_count + 1))
        done < <(find "$REPORTS_DIR" -type f \( -name "AggregateReport_*.csv" -o -name "JmeterResultFile_*.csv" \) -mtime "+$KEEP_DAYS" -print0 2>/dev/null)

        if [ "$file_count" -eq 0 ]; then
            echo -e "   ${GREEN}No old report files found${NC}"
        fi
    else
        echo -e "   ${YELLOW}Reports directory not found: $REPORTS_DIR${NC}"
    fi
    echo
fi

# Clean JMeter logs
if [ "$CLEAN_JMETER_LOGS" = true ]; then
    echo -e "${CYAN}Cleaning JMeter log files (older than $KEEP_DAYS days)...${NC}"

    # Clean timestamped log files from project root (jmeter_YYYYMMDD-HHMMSS.log)
    file_count=0
    while IFS= read -r -d '' file; do
        delete_file "$file"
        file_count=$((file_count + 1))
    done < <(find "$PROJECT_ROOT" -maxdepth 1 -type f -name "jmeter_*.log" -mtime "+$KEEP_DAYS" -print0 2>/dev/null)

    # Clean current log file in bin directory (truncate if exists)
    if [ -f "$JMETER_BIN_DIR/jmeter.log" ]; then
        size=$(get_file_size "$JMETER_BIN_DIR/jmeter.log")
        TOTAL_SIZE=$((TOTAL_SIZE + size))
        TOTAL_FILES_FOUND=$((TOTAL_FILES_FOUND + 1))

        echo -e "   ${YELLOW}Found:${NC} jmeter.log ($(format_size $size))"

        if [ "$DRY_RUN" = false ]; then
            if : > "$JMETER_BIN_DIR/jmeter.log" 2>/dev/null; then
                FILES_DELETED=$((FILES_DELETED + 1))
                echo -e "   ${GREEN}✓ Truncated jmeter.log${NC}"
            else
                echo -e "   ${RED}✗ Failed to truncate jmeter.log${NC}"
            fi
        fi
    fi

    if [ "$file_count" -eq 0 ] && [ ! -f "$JMETER_BIN_DIR/jmeter.log" ]; then
        echo -e "   ${GREEN}No old JMeter log files found${NC}"
    fi
    echo
fi

# Clean dashboard directories
if [ "$CLEAN_DASHBOARDS" = true ]; then
    echo -e "${CYAN}Cleaning HTML dashboard directories (older than $KEEP_DAYS days)...${NC}"

    if [ -d "$REPORTS_DIR" ]; then
        dir_count=0
        while IFS= read -r -d '' dir; do
            delete_directory "$dir"
            dir_count=$((dir_count + 1))
        done < <(find "$REPORTS_DIR" -type d -name "dashboard_*" -mtime "+$KEEP_DAYS" -print0 2>/dev/null)

        if [ "$dir_count" -eq 0 ]; then
            echo -e "   ${GREEN}No old dashboard directories found${NC}"
        fi
    else
        echo -e "   ${YELLOW}Reports directory not found: $REPORTS_DIR${NC}"
    fi
    echo
fi

# Clean JSON result files
if [ "$CLEAN_JSON_RESULTS" = true ]; then
    echo -e "${CYAN}Cleaning JSON result files (older than $KEEP_DAYS days)...${NC}"

    if [ -d "$REPORTS_DIR" ]; then
        file_count=0
        while IFS= read -r -d '' file; do
            delete_file "$file"
            file_count=$((file_count + 1))
        done < <(find "$REPORTS_DIR" -type f \( -name "test_result_*.json" -o -name "statistics_*.json" \) -mtime "+$KEEP_DAYS" -print0 2>/dev/null)

        if [ "$file_count" -eq 0 ]; then
            echo -e "   ${GREEN}No old JSON files found${NC}"
        fi
    else
        echo -e "   ${YELLOW}Reports directory not found: $REPORTS_DIR${NC}"
    fi
    echo
fi

# Display summary
echo -e "${BOLD}${BLUE}═══════════════════════════════════════════════════════════════════${NC}"
echo -e "${BOLD}${BLUE}           Cleanup Summary${NC}"
echo -e "${BOLD}${BLUE}═══════════════════════════════════════════════════════════════════${NC}"
echo

if [ "$DRY_RUN" = true ]; then
    echo -e "${YELLOW}DRY RUN - No files were actually deleted${NC}"
    echo
fi

echo -e "${CYAN}Files Found:${NC}"
echo -e "   Total Files: ${YELLOW}$TOTAL_FILES_FOUND${NC}"
echo -e "   Total Directories: ${YELLOW}$TOTAL_DIRS_FOUND${NC}"
echo -e "   Total Size: ${YELLOW}$(format_size $TOTAL_SIZE)${NC}"
echo

if [ "$DRY_RUN" = false ]; then
    echo -e "${CYAN}Cleanup Results:${NC}"
    echo -e "   Files Deleted: ${GREEN}$FILES_DELETED${NC}"
    echo -e "   Directories Deleted: ${GREEN}$DIRS_DELETED${NC}"
    echo -e "   Space Freed: ${GREEN}$(format_size $TOTAL_SIZE)${NC}"
else
    echo -e "${CYAN}Would Delete:${NC}"
    echo -e "   Files: ${YELLOW}$TOTAL_FILES_FOUND${NC}"
    echo -e "   Directories: ${YELLOW}$TOTAL_DIRS_FOUND${NC}"
    echo -e "   Space: ${YELLOW}$(format_size $TOTAL_SIZE)${NC}"
fi

echo
echo -e "${BOLD}${BLUE}═══════════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}✓ Cleanup Complete${NC}"
echo -e "${BOLD}${BLUE}═══════════════════════════════════════════════════════════════════${NC}"
