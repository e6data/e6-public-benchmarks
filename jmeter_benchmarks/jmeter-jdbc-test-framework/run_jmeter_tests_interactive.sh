#!/bin/bash
# Interactive JMeter test runner
# Usage: ./run_jmeter_tests_interactive.sh
#
# Guides users through:
#   1. Select connection properties file
#   2. Select test plan (concurrency, QPS, QPM, load profile, HTTP endpoint, etc.)
#   3. Select or create test properties (with relevant runtime parameters)
#   4. Select query data file (CSV)
#   5. Optionally select metadata file (for S3 upload)
#   6. Run the JMeter test

set -e

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

# Navigate to project root
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

# Directories
CONN_DIR="connection_properties"
TEST_PROPS_DIR="test_properties"
DATA_DIR="data_files"
TEST_PLANS_DIR="Test-Plans"
METADATA_DIR="metadata_files"

# ============================================================================
# Helper functions
# ============================================================================

# Match an answer against a file list, by number OR by filename.
# Filenames are what scripted callers should use: list positions shift whenever a
# file is added to the directory, so a piped number silently selects the wrong
# file, while a filename keeps meaning the same thing.
# Accepts: "3" | "e6data_test_connection.properties" | "e6data_test_connection"
#          | "connection_properties/e6data_test_connection.properties"
# Sets MATCHED_FILE, returns 0 on success.
match_choice() {
    local answer="$1"; shift
    local files=("$@")
    local count=${#files[@]}

    if [[ "$answer" =~ ^[0-9]+$ ]] && [ "$answer" -ge 1 ] && [ "$answer" -le "$count" ]; then
        MATCHED_FILE="${files[$((answer - 1))]}"
        return 0
    fi

    # Prefer an exact path match. Nested workload directories commonly contain
    # repeated names such as queries.csv and queries_fqn.csv, so silently
    # choosing the first matching basename would run the wrong workload.
    local normalized="${answer#./}"
    for f in "${files[@]}"; do
        if [ "${f#./}" = "$normalized" ] || [ "${f#"$PROJECT_ROOT"/}" = "$normalized" ]; then
            MATCHED_FILE="$f"
            return 0
        fi
    done

    local want matches=0 matched=""
    want=$(basename "$answer")
    for f in "${files[@]}"; do
        local b
        b=$(basename "$f")
        if [ "$b" = "$want" ] || [ "${b%.*}" = "$want" ]; then
            matches=$((matches + 1))
            matched="$f"
        fi
    done
    if [ "$matches" -eq 1 ]; then
        MATCHED_FILE="$matched"
        return 0
    fi
    [ "$matches" -gt 1 ] && return 2
    return 1
}

display_path() {
    local path="$1"
    echo "${path#"$PROJECT_ROOT"/}"
}

# Display a numbered list and get user selection
# Usage: select_file "prompt" file1 file2 file3 ...
# Returns: selected file path in SELECTED_FILE variable
select_file() {
    local prompt="$1"
    shift
    local files=("$@")
    local count=${#files[@]}

    if [ "$count" -eq 0 ]; then
        return 1
    fi

    echo -e "${BOLD}${prompt}${NC}"
    echo ""
    for i in "${!files[@]}"; do
        echo "  $((i + 1))) $(display_path "${files[$i]}")"
    done
    echo ""

    while true; do
        read -p "Enter choice [1-${count}] or filename: " choice
        if match_choice "$choice" "${files[@]}"; then
            SELECTED_FILE="$MATCHED_FILE"
            return 0
        else
            match_status=$?
        fi
        if [ "$match_status" -eq 2 ]; then
            echo -e "${RED}That filename exists in more than one directory. Enter its displayed relative path.${NC}"
            continue
        fi
        echo -e "${RED}Invalid choice. Enter a number between 1 and ${count}, or a filename from the list.${NC}"
    done
}

# Prompt with a default value
# Usage: prompt_with_default "prompt" "default"
prompt_with_default() {
    local prompt="$1"
    local default="$2"
    local result
    read -p "${prompt} [${default}]: " result
    echo "${result:-$default}"
}

# ============================================================================
# Step 1: Select Connection Properties
# ============================================================================

echo -e "${BLUE}=========================================="
echo " JMeter Interactive Test Runner"
echo -e "==========================================${NC}"
echo ""

echo -e "${BLUE}--- Step 1: Connection Properties ---${NC}"
echo ""

CONN_FILES=($(ls -1 "$CONN_DIR"/*.properties 2>/dev/null | grep -v '\.template$' | sort))

if [ ${#CONN_FILES[@]} -eq 0 ]; then
    echo -e "${YELLOW}No connection properties files found in ${CONN_DIR}/${NC}"
    echo ""
    echo "Create one first by running:"
    echo "  ./create_connection.sh"
    echo ""
    exit 1
fi

select_file "Select connection properties:" "${CONN_FILES[@]}"
CONNECTION_FILE="$SELECTED_FILE"
CONNECTION_BASENAME=$(basename "$CONNECTION_FILE")
echo ""
echo -e "  ${GREEN}Selected: ${CONNECTION_BASENAME}${NC}"
echo ""

# Detect connection type (JDBC vs HTTP) from file content
if grep -q "^mainhost=" "$CONNECTION_FILE" 2>/dev/null; then
    CONN_TYPE="http"
else
    CONN_TYPE="jdbc"
fi

# ============================================================================
# Step 2: Select Test Plan
# ============================================================================

echo -e "${BLUE}--- Step 2: Select Test Plan ---${NC}"
echo ""

if [ "$CONN_TYPE" = "jdbc" ]; then
    echo -e "${BOLD}Select test plan type:${NC}"
    echo ""
    echo "  1) Static Concurrency        - Maintain N concurrent queries"
    echo "  2) Run Once                   - Run each query once with N threads"
    echo "  3) Constant QPS              - Fire queries at N per second"
    echo "  4) Constant QPM              - Fire queries at N per minute"
    echo "  5) QPS with Load Profile     - Variable QPS from CSV schedule"
    echo "  6) Variable Concurrency      - Variable concurrency from CSV schedule"
    echo ""

    while true; do
        read -p "Enter choice [1-6]: " plan_choice
        if [[ "$plan_choice" =~ ^[1-6]$ ]]; then break; fi
        echo -e "${RED}Invalid choice.${NC}"
    done

    case "$plan_choice" in
        1) TEST_PLAN="Test-Plans/Test-Plan-Maintain-static-concurrency.jmx"; PLAN_TYPE="concurrency" ;;
        2) TEST_PLAN="Test-Plans/Test-Plan-Run-Once-static-concurrency.jmx"; PLAN_TYPE="run_once" ;;
        3) TEST_PLAN="Test-Plans/Test-Plan-Constant-QPS-On-Arrivals-JSR-Optimized.jmx"; PLAN_TYPE="qps" ;;
        4) TEST_PLAN="Test-Plans/Test-Plan-Constant-QPM-On-Arrivals.jmx"; PLAN_TYPE="qpm" ;;
        5) TEST_PLAN="Test-Plans/Test-Plan-Fire-QPS-with-load-profile.jmx"; PLAN_TYPE="qps_loadprofile" ;;
        6) TEST_PLAN="Test-Plans/Test-Plan-Maintain-variable-concurrency-with-load-profile.jmx"; PLAN_TYPE="variable_concurrency" ;;
    esac
else
    echo -e "${BOLD}Select HTTP endpoint test plan:${NC}"
    echo ""
    echo "  1) Static Concurrency (HTTP)  - Maintain N concurrent queries"
    echo "  2) Run Once (HTTP)            - Run each query once with N threads"
    echo "  3) QPS with Load Profile (HTTP) - Variable QPS from CSV schedule"
    echo ""

    while true; do
        read -p "Enter choice [1-3]: " plan_choice
        if [[ "$plan_choice" =~ ^[1-3]$ ]]; then break; fi
        echo -e "${RED}Invalid choice.${NC}"
    done

    case "$plan_choice" in
        1) TEST_PLAN="Test-Plans/Test-Plan-Maintain-static-concurrency-http-endpoint-v2.jmx"; PLAN_TYPE="concurrency" ;;
        2) TEST_PLAN="Test-Plans/Test-Plan-Run-Once-http-endpoint.jmx"; PLAN_TYPE="run_once" ;;
        3) TEST_PLAN="Test-Plans/Test-Plan-Fire-QPS-with-load-profile-http-endpoint_v2.jmx"; PLAN_TYPE="qps_loadprofile" ;;
    esac
fi

echo ""
echo -e "  ${GREEN}Selected: $(basename "$TEST_PLAN")${NC}"
echo -e "  ${DIM}Type: ${PLAN_TYPE}${NC}"
echo ""

# ============================================================================
# Step 3: Canonical Test Properties and Workload Values
# ============================================================================

echo -e "${BLUE}--- Step 3: Workload Configuration ---${NC}"
echo ""

case "$PLAN_TYPE" in
    concurrency)          TEST_PROPERTIES="$TEST_PROPS_DIR/fixed_concurrency.properties" ;;
    run_once)             TEST_PROPERTIES="$TEST_PROPS_DIR/run_once.properties" ;;
    qps)                  TEST_PROPERTIES="$TEST_PROPS_DIR/constant_qps.properties" ;;
    qpm)                  TEST_PROPERTIES="$TEST_PROPS_DIR/constant_qpm.properties" ;;
    qps_loadprofile)      TEST_PROPERTIES="$TEST_PROPS_DIR/variable_arrivals.properties" ;;
    variable_concurrency) TEST_PROPERTIES="$TEST_PROPS_DIR/variable_concurrency.properties" ;;
esac

if [ ! -f "$TEST_PROPERTIES" ]; then
    echo -e "${RED}Canonical properties file is missing: ${TEST_PROPERTIES}${NC}"
    exit 1
fi

property_default() {
    local key="$1" fallback="$2" value
    value=$(awk -F= -v key="$key" '$1 == key {sub(/^[^=]*=/, ""); print; exit}' "$TEST_PROPERTIES")
    echo "${value:-$fallback}"
}

echo -e "  Canonical properties: ${GREEN}$(basename "$TEST_PROPERTIES")${NC}"
echo -e "  ${DIM}Only values relevant to the selected plan are requested; they override this file for this run.${NC}"
echo ""

case "$PLAN_TYPE" in
    concurrency)
        CONCURRENT_QUERY_COUNT=$(prompt_with_default "Concurrent query count" "$(property_default CONCURRENT_QUERY_COUNT 4)")
        RAMP_UP_TIME=$(prompt_with_default "Ramp up time (seconds; 0 starts immediately)" "$(property_default RAMP_UP_TIME 0)")
        RAMP_UP_STEPS=$(prompt_with_default "Ramp up steps" "$(property_default RAMP_UP_STEPS 1)")
        HOLD_PERIOD=$(prompt_with_default "Hold period (seconds)" "$(property_default HOLD_PERIOD 300)")
        ;;
    run_once)
        CONCURRENT_QUERY_COUNT=$(prompt_with_default "Concurrent query count (1 is sequential)" "1")
        MEASURED_ITERATIONS=$(prompt_with_default "Measured iterations" "1")
        RAMP_UP_TIME=0
        RAMP_UP_STEPS=1
        RECYCLE_ON_EOF=false
        ;;
    qps)
        QPS=$(prompt_with_default "Queries per second (QPS)" "$(property_default QPS 1)")
        HOLD_PERIOD=$(prompt_with_default "Duration (seconds)" "$(property_default HOLD_PERIOD 300)")
        ;;
    qpm)
        QPM=$(prompt_with_default "Queries per minute (QPM)" "$(property_default QPM 10)")
        HOLD_PERIOD=$(prompt_with_default "Duration (seconds)" "$(property_default HOLD_PERIOD 300)")
        ;;
    qps_loadprofile|variable_concurrency)
        read -p "Load profile CSV path (local or s3://): " LOAD_PROFILE
        if [ -z "$LOAD_PROFILE" ]; then
            echo -e "${RED}A load profile is required for this plan.${NC}"
            exit 1
        fi
        ;;
esac

echo ""
echo -e "  ${GREEN}Using: $(basename "$TEST_PROPERTIES")${NC}"
echo ""

# ============================================================================
# Step 4: Select Query Data File
# ============================================================================

echo -e "${BLUE}--- Step 4: Query Data File (CSV) ---${NC}"
echo ""

DATA_FILES=()
while IFS= read -r file; do
    DATA_FILES+=("$file")
done < <(find "$DATA_DIR" -type f -name '*.csv' -print 2>/dev/null | LC_ALL=C sort)

if [ ${#DATA_FILES[@]} -eq 0 ]; then
    echo -e "${RED}No CSV data files found in ${DATA_DIR}/${NC}"
    exit 1
fi

select_file "Select query data file:" "${DATA_FILES[@]}"
QUERY_FILE="$SELECTED_FILE"
echo ""
echo -e "  ${GREEN}Selected: $(display_path "$QUERY_FILE")${NC}"
echo ""

# ============================================================================
# Step 5: Metadata File (optional, for S3 upload)
# ============================================================================

echo -e "${BLUE}--- Step 5: Metadata File (optional) ---${NC}"
echo ""

METADATA_FILES=($(ls -1 "$METADATA_DIR"/*.txt 2>/dev/null | sort))

echo -e "${BOLD}Select metadata file:${NC}"
echo ""
echo "  0) Skip (no metadata)"
if [ ${#METADATA_FILES[@]} -gt 0 ]; then
    for i in "${!METADATA_FILES[@]}"; do
        echo "  $((i + 1))) $(basename "${METADATA_FILES[$i]}")"
    done
fi
echo ""

METADATA_FILE=""
while true; do
    read -p "Enter choice [0-${#METADATA_FILES[@]}] or filename: " meta_choice
    if [ "$meta_choice" = "0" ] || [[ "$meta_choice" =~ ^([Ss]kip|[Nn]one)$ ]]; then
        meta_choice=0
        break
    fi
    if [ ${#METADATA_FILES[@]} -gt 0 ] && match_choice "$meta_choice" "${METADATA_FILES[@]}"; then
        METADATA_FILE="$MATCHED_FILE"
        meta_choice=1
        break
    fi
    echo -e "${RED}Invalid choice. Enter 0 to skip, a number, or a filename from the list.${NC}"
done

if [ "$meta_choice" -gt 0 ]; then
    echo -e "  ${GREEN}Selected: $(basename "$METADATA_FILE")${NC}"
else
    echo -e "  ${DIM}Skipped${NC}"
fi
echo ""

# ============================================================================
# Step 6: Review and Run
# ============================================================================

echo -e "${BLUE}=========================================="
echo " Test Configuration Summary"
echo -e "==========================================${NC}"
echo ""
echo "  Connection:      $(basename "$CONNECTION_FILE")"
echo "  Test Plan:       $(basename "$TEST_PLAN")"
echo "  Test Properties: $(basename "$TEST_PROPERTIES")"
echo "  Query File:      $(display_path "$QUERY_FILE")"
if [ -n "$METADATA_FILE" ]; then
    echo "  Metadata:        $(basename "$METADATA_FILE")"
fi
echo ""

# Show the endpoint being tested. The filename alone does not say which cluster
# the run will hit, which matters when several files point at similar clusters.
# Any password embedded in the URL is redacted.
echo -e "${DIM}Target:${NC}"
if [ "$CONN_TYPE" = "http" ]; then
    _host=$(grep -E "^mainhost=" "$CONNECTION_FILE" 2>/dev/null | head -1 | cut -d= -f2-)
    [ -n "$_host" ] && echo "  Host:            ${_host}"
else
    _url=$(grep -E "^CONNECTION_STRING=" "$CONNECTION_FILE" 2>/dev/null | head -1 | cut -d= -f2- \
           | sed -E 's/([Pp][Aa][Ss][Ss][Ww][Oo][Rr][Dd]=)[^&]*/\1<redacted>/g')
    _user=$(grep -E "^USER=" "$CONNECTION_FILE" 2>/dev/null | head -1 | cut -d= -f2-)
    if [ -n "$_url" ]; then
        echo "  JDBC URL:        ${_url}"
        # cluster-name is the parameter that decides which cluster serves the query
        case "$_url" in
            *cluster-name=*) echo "  Cluster:         $(echo "$_url" | sed -E 's/.*cluster-name=([^&]*).*/\1/')" ;;
        esac
    else
        echo -e "  ${YELLOW}No CONNECTION_STRING found in $(basename "$CONNECTION_FILE")${NC}"
    fi
    [ -n "$_user" ] && echo "  User:            ${_user}"
fi
echo ""

# Show key test parameters from properties file
echo -e "${DIM}Key parameters from test properties:${NC}"
grep -E "^(CONCURRENT_QUERY_COUNT|QPS|QPM|HOLD_PERIOD|COPY_TO_S3|RECYCLE_ON_EOF)=" "$TEST_PROPERTIES" 2>/dev/null | while read -r line; do
    echo "  $line"
done
echo -e "${DIM}Interactive overrides for this run:${NC}"
for key in CONCURRENT_QUERY_COUNT MEASURED_ITERATIONS QPS QPM HOLD_PERIOD RAMP_UP_TIME RAMP_UP_STEPS LOAD_PROFILE; do
    [ -n "${!key:-}" ] && echo "  ${key}=${!key}"
done
echo ""

# Source metadata if present (to get COPY_TO_S3 override, ENGINE, etc.)
if [ -n "$METADATA_FILE" ]; then
    echo -e "${DIM}Metadata overrides:${NC}"
    grep -E "^(ENGINE|COPY_TO_S3|S3_REPORT_PATH|S3_BASE_PATH|BENCHMARK_TYPE|RUN_TYPE)=" "$METADATA_FILE" 2>/dev/null | while read -r line; do
        echo "  $line"
    done
    echo ""
fi

read -p "Run test? (y/n): " confirm
if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
    echo "Cancelled."
    exit 0
fi

echo ""

# Interactive mode is a configuration collector only. The canonical runner
# owns property precedence, S3 materialization, JMeter invocation, reporting,
# and uploads for CLI, UI, and interactive runs alike. Existing exported
# variables remain in the environment and therefore override the selected
# test-properties file inside run_test.sh.
echo -e "${BLUE}Delegating to the canonical runner...${NC}"
for key in CONCURRENT_QUERY_COUNT MEASURED_ITERATIONS QPS QPM HOLD_PERIOD RAMP_UP_TIME RAMP_UP_STEPS LOAD_PROFILE RECYCLE_ON_EOF; do
    [ -n "${!key:-}" ] && export "$key"
done

exec env \
    CONNECTION_FILE="$CONNECTION_FILE" \
    TEST_PLAN="$TEST_PLAN" \
    TEST_PROPERTIES_FILE="$TEST_PROPERTIES" \
    QUERY_FILE="$QUERY_FILE" \
    METADATA_FILE="${METADATA_FILE:-}" \
    "${PROJECT_ROOT}/run_test.sh"

# ============================================================================
# Legacy implementation retained below temporarily for history; exec above
# makes it unreachable. It will be removed after rollout validation.
# ============================================================================

# Values set in the environment win over both the metadata file and the
# properties file, so a single config can be reused across runs:
#   LOAD_PROFILE=test_properties/spike.csv ./run_jmeter_tests_interactive.sh
# Matches the precedence run_test.sh already implements.
#
# Captured BEFORE the metadata is sourced: metadata defines COPY_TO_S3 and
# would otherwise overwrite the environment value before it could be saved.
OVERRIDABLE="LOAD_PROFILE GENERATE_DASHBOARD HOLD_PERIOD MAX_CONCURRANCY COPY_TO_S3 RECYCLE_ON_EOF \
RANDOM_ORDER QPS QPM CONCURRENT_QUERY_COUNT RAMP_UP_TIME RAMP_UP_STEPS QUERY_TIMEOUT MAX_ERROR_PCT RUN_TYPE S3_REPORT_PATH"
for _k in $OVERRIDABLE; do
    [ -n "${!_k:-}" ] && printf -v "_ENV_$_k" '%s' "${!_k}"
done

# Source metadata for runtime variables if present
if [ -n "$METADATA_FILE" ]; then
    source "$METADATA_FILE"
fi

if [ -n "${S3_BASE_PATH:-}" ] && [ -n "${S3_REPORT_PATH:-}" ] \
   && [ "$S3_BASE_PATH" != "$S3_REPORT_PATH" ]; then
    echo -e "${YELLOW}Warning: S3_BASE_PATH overrides S3_REPORT_PATH; migrate metadata to S3_REPORT_PATH.${NC}"
fi
S3_UPLOAD_ROOT="${S3_BASE_PATH:-${S3_REPORT_PATH:-}}"

# Read test properties without executing them (values like
# values containing parentheses or spaces are not valid bash)
while IFS='=' read -r key value; do
    [[ "$key" =~ ^[[:space:]]*# ]] && continue
    key=$(echo "$key" | xargs)
    [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    printf -v "$key" '%s' "$value"
done < "$TEST_PROPERTIES"

# Re-apply the environment overrides captured above
for _k in $OVERRIDABLE; do
    _saved="_ENV_$_k"
    if [ -n "${!_saved:-}" ]; then
        printf -v "$_k" '%s' "${!_saved}"
        echo -e "  ${DIM}override: ${_k}=${!_saved}${NC}"
    fi
done

# Determine JMETER_HOME
if [ -z "$JMETER_HOME" ]; then
    # Try to find JMeter in common locations
    if command -v jmeter &>/dev/null; then
        JMETER_BIN=$(which jmeter)
        JMETER_HOME=$(dirname "$(dirname "$JMETER_BIN")")
    elif [ -d "/opt/homebrew/Cellar/jmeter" ]; then
        JMETER_HOME=$(ls -d /opt/homebrew/Cellar/jmeter/*/libexec 2>/dev/null | head -1)
    elif [ -d "/usr/local/Cellar/jmeter" ]; then
        JMETER_HOME=$(ls -d /usr/local/Cellar/jmeter/*/libexec 2>/dev/null | head -1)
    elif [ -d "apache-jmeter-5.6.3" ]; then
        JMETER_HOME="$(pwd)/apache-jmeter-5.6.3"
    fi
fi

if [ -z "$JMETER_HOME" ] || [ ! -f "$JMETER_HOME/bin/jmeter" ]; then
    echo -e "${RED}Error: Cannot find JMeter installation.${NC}"
    echo "Set JMETER_HOME in your test properties or install JMeter."
    echo "  brew install jmeter"
    exit 1
fi

echo -e "${GREEN}Using JMeter: ${JMETER_HOME}${NC}"
echo ""

# Generate report directory with timestamp
TIMESTAMP=$(python3 -c 'from datetime import datetime; print(datetime.now().strftime("%Y%m%d-%H%M%S-%f"))')
REPORT_DIR="${REPORT_PATH:-reports}/${TIMESTAMP}"
mkdir -p "${REPORT_PATH:-reports}"
if ! mkdir "$REPORT_DIR"; then
    echo -e "${RED}Error: report directory already exists: ${REPORT_DIR}${NC}"
    exit 1
fi
ORIGINAL_TEST_PLAN="$TEST_PLAN"

# Apply the load profile CSV to the plan's thread-group schedule.
# Covers both families: FreeFormArrivalsThreadGroup (arrival rate) and
# UltimateThreadGroup (concurrency waves).
# The plans' own JSR223 PreProcessors cannot do this: they run when a sampler
# fires, by which point the thread group has already read its schedule and
# started threads. So the schedule is injected here, before JMeter starts.
if grep -qE "FreeFormArrivalsThreadGroup|UltimateThreadGroup" "$TEST_PLAN" 2>/dev/null; then
    # The two families take different CSV formats, so the default follows the plan.
    if [ -z "${LOAD_PROFILE:-}" ] && grep -q "UltimateThreadGroup" "$TEST_PLAN" 2>/dev/null \
       && [ -f "${PROJECT_ROOT}/test_properties/utg_load_profile.csv" ]; then
        LOAD_PROFILE="test_properties/utg_load_profile.csv"
    fi
    if [ -z "${LOAD_PROFILE:-}" ]; then
        echo -e "${YELLOW}Warning: load-profile plan selected but LOAD_PROFILE is not set.${NC}"
        echo -e "${YELLOW}The plan's built-in schedule will be used instead.${NC}"
        echo ""
    elif [ ! -f "$LOAD_PROFILE" ]; then
        echo -e "${RED}Error: LOAD_PROFILE file not found: ${LOAD_PROFILE}${NC}"
        exit 1
    else
        GENERATED_PLAN="${REPORT_DIR}/$(basename "${TEST_PLAN%.jmx}")-generated.jmx"
        python3 "${PROJECT_ROOT}/utilities/apply_load_profile.py" \
            "$TEST_PLAN" "$LOAD_PROFILE" "$GENERATED_PLAN" || exit 1
        echo -e "  ${DIM}profile: ${LOAD_PROFILE}${NC}"
        echo ""
        TEST_PLAN="$GENERATED_PLAN"
    fi
fi

# Build JMeter command as an array so values containing spaces or shell
# metacharacters (e.g. a query path with spaces) reach JMeter intact
JMETER_CMD=("$JMETER_HOME/bin/jmeter" -n)
JMETER_CMD+=(-t "$TEST_PLAN")
JMETER_CMD+=(-q "$CONNECTION_FILE")
JMETER_CMD+=(-l "${REPORT_DIR}/JmeterResultFile.csv")
# HTML dashboard is ~3.5MB of vendored assets per run. CLAUDE.md documents
# GENERATE_DASHBOARD=false to skip it; honour that here.
if [ "${GENERATE_DASHBOARD:-true}" != "false" ]; then
    JMETER_CMD+=(-e -o "${REPORT_DIR}/dashboard")
fi

# Add all properties as JMeter parameters
JMETER_CMD+=("-JCONNECTION_PROPERTIES=$CONNECTION_FILE")
JMETER_CMD+=("-JQUERY_PATH=$QUERY_FILE")

# Pass test properties as JMeter -J parameters
while IFS='=' read -r key value; do
    # Skip comments, empty lines, and JMETER_HOME
    [[ "$key" =~ ^[[:space:]]*# ]] && continue
    [[ -z "$key" ]] && continue
    [[ "$key" == "JMETER_HOME" ]] && continue
    # Trim whitespace
    key=$(echo "$key" | xargs)
    value=$(echo "$value" | xargs)
    [ -z "$key" ] && continue
    JMETER_CMD+=("-J${key}=${value}")
done < "$TEST_PROPERTIES"

# Override QUERY_PATH with user selection
JMETER_CMD+=("-JQUERY_PATH=$QUERY_FILE")

# The test plans write AggregateReport_<START_TIME>.csv and SummaryReport_... to
# ${REPORT_PATH}. Point that at this run's directory, otherwise they land in the
# reports/ root, are stamped with JMeter's own START_TIME (which differs from the
# run_id by a few seconds), and never reach S3. Last -J wins over the file value.
JMETER_CMD+=("-JREPORT_PATH=$REPORT_DIR")

# The QPM plan uses Unit=M on its thread group, which governs BOTH the arrival rate
# (QPM = per minute) and the hold duration - so HOLD_PERIOD is MINUTES there, unlike
# every other plan where it is seconds. The two cannot be separated: setting Unit=S
# would make QPM mean per-second. Warn rather than silently run 60x too long.
if grep -q '<stringProp name="Unit">M</stringProp>' "$TEST_PLAN" 2>/dev/null; then
    echo -e "${YELLOW}  Note: this plan measures time in MINUTES.${NC}"
    echo -e "${YELLOW}  HOLD_PERIOD=${HOLD_PERIOD:-?} means ${HOLD_PERIOD:-?} minute(s), not seconds.${NC}"
    echo ""
fi

echo -e "${BLUE}Running JMeter...${NC}"
echo -e "${DIM}${JMETER_CMD[*]}${NC}"
echo ""

# Run JMeter, but always finalize whatever artifacts it produced.
set +e
"${JMETER_CMD[@]}"
JMETER_RC=$?
set -e
RUN_FAILED=0
if [ "$JMETER_RC" -ne 0 ]; then
    RUN_FAILED=1
    echo -e "${RED}JMeter exited with status ${JMETER_RC}; finalizing available artifacts.${NC}"
fi

INFERRED_RUN_TYPE=""
case "$PLAN_TYPE" in
    run_once)
        if [ "${CONCURRENT_QUERY_COUNT:-1}" = "1" ]; then INFERRED_RUN_TYPE="sequential";
        else INFERRED_RUN_TYPE="concurrency_${CONCURRENT_QUERY_COUNT}"; fi ;;
    concurrency) INFERRED_RUN_TYPE="concurrency_${CONCURRENT_QUERY_COUNT:-1}" ;;
    qps) INFERRED_RUN_TYPE="qps_${QPS:-1}" ;;
    qpm) INFERRED_RUN_TYPE="qpm_${QPM:-1}" ;;
    qps_loadprofile) INFERRED_RUN_TYPE="qps_load_profile" ;;
    variable_concurrency) INFERRED_RUN_TYPE="variable_concurrency" ;;
    *) INFERRED_RUN_TYPE="custom" ;;
esac
RUN_TYPE=$(printf '%s' "${RUN_TYPE:-$INFERRED_RUN_TYPE}" | tr -cs 'A-Za-z0-9._-' '_')

# Capture a standard run report alongside the raw results, so every run is
# self-describing and the analysis does not depend on anyone remembering to run
# it. Writes run_summary.json + run_report.md into the run directory.
if [ -f "${PROJECT_ROOT}/utilities/capture_run_report.py" ]; then
    CAPTURE_ARGS=("$REPORT_DIR")
    # Only compare against a load profile when the plan is actually profile-driven.
    # LOAD_PROFILE defaults to an existing file, so passing it unconditionally made
    # every non-profile run report a bogus "SHORTFALL" against a schedule it never used.
    if grep -qE "FreeFormArrivalsThreadGroup|UltimateThreadGroup" "$TEST_PLAN" 2>/dev/null \
       && [ -n "${LOAD_PROFILE:-}" ] && [ -f "$LOAD_PROFILE" ]; then
        CAPTURE_ARGS+=(--profile "$LOAD_PROFILE")
    fi
    CAPTURE_ARGS+=(--meta "engine=${ENGINE:-unknown}" --meta "cluster_size=${CLUSTER_SIZE:-unknown}")
    CAPTURE_ARGS+=(--meta "benchmark=${BENCHMARK_TYPE:-unknown}" --meta "run_type=${RUN_TYPE}")
    for _meta_var in RUN_SCOPE RUN_PURPOSE RUN_VALIDITY; do
        _meta_value="${!_meta_var:-}"
        [ -n "$_meta_value" ] && CAPTURE_ARGS+=(--meta "${_meta_var}=${_meta_value}")
    done
    CAPTURE_ARGS+=(--meta "test_plan=$(basename "$ORIGINAL_TEST_PLAN")" --meta "queries=$(basename "$QUERY_FILE")")
    [ -n "${GENERATED_PLAN:-}" ] && CAPTURE_ARGS+=(--meta "generated_plan=$(basename "$GENERATED_PLAN")")
    QUERY_SHA=$(python3 "${PROJECT_ROOT}/utilities/query_file_info.py" "$QUERY_FILE" --field sha256)
    CAPTURE_ARGS+=(--meta "query_sha256=${QUERY_SHA}" --meta "requested_concurrency=${CONCURRENT_QUERY_COUNT:-unknown}")
    CAPTURE_ARGS+=(--meta "requested_qps=${QPS:-unknown}" --meta "requested_qpm=${QPM:-unknown}")
    CAPTURE_ARGS+=(--meta "hold_period=${HOLD_PERIOD:-unknown}" --meta "ramp_up_time=${RAMP_UP_TIME:-unknown}" --meta "ramp_up_steps=${RAMP_UP_STEPS:-unknown}")
    CAPTURE_ARGS+=(--meta "max_concurrency=${MAX_CONCURRANCY:-unknown}" --meta "recycle_on_eof=${RECYCLE_ON_EOF:-unknown}" --meta "random_order=${RANDOM_ORDER:-unknown}")
    CAPTURE_ARGS+=(--meta "jmeter_version=$(basename "$JMETER_HOME")" --meta "java_version=$(java -version 2>&1 | head -1)")
    CAPTURE_ARGS+=(--meta "git_commit=$(git rev-parse --short HEAD 2>/dev/null || echo unknown)")
    if [ -n "${LOAD_PROFILE:-}" ] && [ -f "$LOAD_PROFILE" ] \
       && grep -qE "FreeFormArrivalsThreadGroup|UltimateThreadGroup" "$TEST_PLAN" 2>/dev/null; then
        CAPTURE_ARGS+=(--meta "profile=$(basename "$LOAD_PROFILE")" --meta "profile_sha256=$(python3 "${PROJECT_ROOT}/utilities/query_file_info.py" "$LOAD_PROFILE" --field sha256)")
    fi
    # Exit 2 from the report means the run itself failed (no samples, or an error
    # rate above MAX_ERROR_PCT). Propagate it: a run where the queries did not
    # succeed must not report success, or callers and CI treat it as a result.
    set +e
    python3 "${PROJECT_ROOT}/utilities/capture_run_report.py" "${CAPTURE_ARGS[@]}"
    CAPTURE_RC=$?
    set -e
    if [ "$CAPTURE_RC" -eq 2 ]; then
        RUN_FAILED=1
    elif [ "$CAPTURE_RC" -ne 0 ]; then
        echo -e "  ${YELLOW}run report capture failed (results are unaffected)${NC}"
    fi
fi

# The plan stamps these with JMeter's own START_TIME, which differs from run_id by
# a few seconds. Normalise to the names the analysis and Athena scripts expect.
for _f in "${REPORT_DIR}"/AggregateReport_*.csv; do
    [ -e "$_f" ] && mv -f "$_f" "${REPORT_DIR}/AggregateReport.csv" && break
done
for _f in "${REPORT_DIR}"/SummaryReport_*.csv; do
    [ -e "$_f" ] && mv -f "$_f" "${REPORT_DIR}/SummaryReport.csv" && break
done

# JMeter writes statistics.json under dashboard/; downstream analysis and Athena
# scripts look for it at the run root, so publish a copy there.
[ -f "${REPORT_DIR}/dashboard/statistics.json" ] && \
    cp "${REPORT_DIR}/dashboard/statistics.json" "${REPORT_DIR}/statistics.json"

echo ""
if [ "${RUN_FAILED:-0}" -eq 1 ]; then
    echo -e "${RED}=========================================="
    echo " Test FAILED"
    echo -e "==========================================${NC}"
else
    echo -e "${GREEN}=========================================="
    echo " Test Complete!"
    echo -e "==========================================${NC}"
fi
echo ""
echo "  Results: ${REPORT_DIR}/"
echo "  Report:  ${REPORT_DIR}/run_report.md"
if [ "${GENERATE_DASHBOARD:-true}" != "false" ]; then
    echo "  Dashboard: ${REPORT_DIR}/dashboard/index.html"
else
    echo "  Dashboard: disabled"
fi
echo ""

# Copy to S3 if enabled
if [ "${COPY_TO_S3:-false}" = "true" ] && [ -n "${S3_UPLOAD_ROOT:-}" ]; then
    echo "Uploading results to S3..."
    # Build S3 path from metadata
    ENGINE_VAL="${ENGINE:-unknown}"
    CLUSTER_SIZE_VAL="${CLUSTER_SIZE:-unknown}"
    BENCHMARK_VAL="${BENCHMARK_TYPE:-unknown}"
    RUN_TYPE_VAL="run_type=${RUN_TYPE}"
    S3_DEST="${S3_UPLOAD_ROOT%/}/engine=${ENGINE_VAL}/cluster_size=${CLUSTER_SIZE_VAL}/benchmark=${BENCHMARK_VAL}/${RUN_TYPE_VAL}/run_id=${TIMESTAMP}/"

    echo "  S3 path: ${S3_DEST}"
    # The JMeter HTML dashboard vendors jQuery/Bootstrap/font-awesome/flot -
    # ~120 files and ~3.5MB per run, byte-identical every time and read by
    # nothing downstream. Upload the data and the dashboard pages, skip the
    # vendored assets. Set S3_UPLOAD_DASHBOARD_ASSETS=true to include them.
    if [ "${S3_UPLOAD_DASHBOARD_ASSETS:-false}" = "true" ]; then
        aws s3 cp "${REPORT_DIR}/" "${S3_DEST}" --recursive
    else
        aws s3 cp "${REPORT_DIR}/" "${S3_DEST}" --recursive \
            --exclude "dashboard/sbadmin2-1.0.7/*" \
            --exclude "dashboard/content/css/*" \
            --exclude "dashboard/content/js/*"
    fi
    echo -e "  ${GREEN}Uploaded to S3${NC}"
fi

echo ""

# Exit non-zero when the run produced no usable result, so callers and CI can
# tell a real benchmark from one where every query failed.
exit "${RUN_FAILED:-0}"
