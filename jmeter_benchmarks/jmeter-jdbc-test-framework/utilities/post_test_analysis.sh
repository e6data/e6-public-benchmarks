#!/bin/bash
# Post-Test Analysis Automation
#
# This script automates the complete post-test analysis workflow:
# 1. Syncs results to Athena
# 2. Compares against baseline
# 3. Generates performance reports
# 4. Identifies best runs
#
# Usage:
#   ./utilities/post_test_analysis.sh <engine> <cluster_size> <benchmark>
#
# Example:
#   ./utilities/post_test_analysis.sh e6data S-2x2 tpcds_29_1tb

set -e

# Check arguments
if [ $# -lt 3 ]; then
    echo "Usage: $0 <engine> <cluster_size> <benchmark> [user_name]"
    echo ""
    echo "Example:"
    echo "  $0 e6data S-2x2 tpcds_29_1tb george"
    echo ""
    exit 1
fi

ENGINE="$1"
CLUSTER_SIZE="$2"
BENCHMARK="$3"
USER="${4:-$(whoami)}"
CONCURRENCY_LEVELS=(2 4 8 12 16)

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo ""
echo "================================================================================"
echo -e "${BLUE}Post-Test Analysis Automation${NC}"
echo "================================================================================"
echo "Engine:       $ENGINE"
echo "Cluster:      $CLUSTER_SIZE"
echo "Benchmark:    $BENCHMARK"
echo "User:         $USER"
echo "================================================================================"
echo ""

# Navigate to project root
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

# Create reports directory if it doesn't exist
mkdir -p reports

# Timestamp for report naming
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
REPORT_FILE="reports/${ENGINE}_${CLUSTER_SIZE}_PostTest_${TIMESTAMP}.md"
CSV_FILE="reports/${ENGINE}_${CLUSTER_SIZE}_PostTest_${TIMESTAMP}.csv"

echo "📊 Starting post-test analysis workflow..."
echo ""

# Step 1: Sync all concurrency levels to Athena
echo "================================================================================"
echo -e "${GREEN}Step 1: Syncing Results to Athena${NC}"
echo "================================================================================"
echo ""

for concurrency in "${CONCURRENCY_LEVELS[@]}"; do
    echo "Syncing concurrency_${concurrency}..."
    S3_PATH="${S3_RESULTS_PATH:-s3://your-s3-bucket/jmeter-results}/engine=${ENGINE}/cluster_size=${CLUSTER_SIZE}/benchmark=${BENCHMARK}/run_type=concurrency_${concurrency}/"

    if python3 utilities/athena/upload_runs_index_to_athena.py --from-s3 "$S3_PATH" 2>&1 | grep -q "Successfully uploaded"; then
        echo -e "  ${GREEN}✓${NC} concurrency_${concurrency} synced"
    else
        echo -e "  ${YELLOW}⚠${NC} concurrency_${concurrency} - no new data or sync failed"
    fi
done

echo ""
echo -e "${GREEN}✓ Athena sync complete${NC}"
echo ""

# Step 2: Compare against baselines
echo "================================================================================"
echo -e "${GREEN}Step 2: Comparing Against Baselines${NC}"
echo "================================================================================"
echo ""

# Initialize report
cat > "$REPORT_FILE" << EOF
# Post-Test Analysis Report

**Generated**: $(date '+%Y-%m-%d %H:%M:%S')
**Engine**: $ENGINE
**Cluster**: $CLUSTER_SIZE
**Benchmark**: $BENCHMARK
**Analyzed By**: $USER

---

## Baseline Comparisons

EOF

IMPROVEMENTS=0
DEGRADATIONS=0
NO_BASELINE=0

for concurrency in "${CONCURRENCY_LEVELS[@]}"; do
    RUN_TYPE="concurrency_${concurrency}"

    echo "Checking $RUN_TYPE..."

    # Get latest run ID from S3
    LATEST_RUN=$(aws s3 ls ${S3_RESULTS_PATH:-s3://your-s3-bucket/jmeter-results}/engine=${ENGINE}/cluster_size=${CLUSTER_SIZE}/benchmark=${BENCHMARK}/run_type=${RUN_TYPE}/ \
        | grep "PRE run_id=" \
        | tail -1 \
        | awk '{print $2}' \
        | sed 's/run_id=//' \
        | sed 's/\///')

    if [ -z "$LATEST_RUN" ]; then
        echo -e "  ${YELLOW}⚠${NC} No runs found"
        continue
    fi

    echo "  Latest run: $LATEST_RUN"

    # Check if baseline exists
    S3_BUCKET_NAME=$(echo "${S3_RESULTS_PATH:-s3://your-s3-bucket/jmeter-results}" | sed 's|s3://||' | cut -d/ -f1)
    BASELINE_KEY="jmeter-results-index/baselines/engine=${ENGINE}/cluster_size=${CLUSTER_SIZE}/benchmark=${BENCHMARK}/run_type=${RUN_TYPE}/baseline_metadata.json"

    if aws s3 ls "s3://${S3_BUCKET_NAME}/${BASELINE_KEY}" > /dev/null 2>&1; then
        echo "  Comparing against baseline..."

        # Run comparison and capture output (also write to CSV)
        COMPARISON_OUTPUT=$(python3 utilities/athena/manage_baseline.py compare \
            --engine "$ENGINE" \
            --cluster "$CLUSTER_SIZE" \
            --benchmark "$BENCHMARK" \
            --run-type "$RUN_TYPE" \
            --run-id "$LATEST_RUN" \
            --output-csv "$CSV_FILE" 2>&1)

        echo "$COMPARISON_OUTPUT"

        # Add to report
        echo "" >> "$REPORT_FILE"
        echo "### $RUN_TYPE" >> "$REPORT_FILE"
        echo "" >> "$REPORT_FILE"
        echo '```' >> "$REPORT_FILE"
        echo "$COMPARISON_OUTPUT" >> "$REPORT_FILE"
        echo '```' >> "$REPORT_FILE"
        echo "" >> "$REPORT_FILE"

        # Determine if improvement or degradation
        if echo "$COMPARISON_OUTPUT" | grep -q "SIGNIFICANT IMPROVEMENT"; then
            IMPROVEMENTS=$((IMPROVEMENTS + 1))
            echo -e "  ${GREEN}✓ IMPROVEMENT detected${NC}"
        elif echo "$COMPARISON_OUTPUT" | grep -q "degradation"; then
            DEGRADATIONS=$((DEGRADATIONS + 1))
            echo -e "  ${RED}⚠ DEGRADATION detected${NC}"
        else
            echo -e "  ${BLUE}➖ Mixed or stable${NC}"
        fi
    else
        echo -e "  ${YELLOW}⚠${NC} No baseline set for $RUN_TYPE"
        echo "" >> "$REPORT_FILE"
        echo "### $RUN_TYPE" >> "$REPORT_FILE"
        echo "" >> "$REPORT_FILE"
        echo "**Status**: No baseline set" >> "$REPORT_FILE"
        echo "**Latest Run**: $LATEST_RUN" >> "$REPORT_FILE"
        echo "" >> "$REPORT_FILE"
        NO_BASELINE=$((NO_BASELINE + 1))
    fi

    echo ""
done

echo ""
echo -e "${GREEN}✓ Baseline comparisons complete${NC}"
echo ""

# Step 3: Generate summary
echo "================================================================================"
echo -e "${GREEN}Step 3: Generating Analysis Summary${NC}"
echo "================================================================================"
echo ""

# Add summary to report
cat >> "$REPORT_FILE" << EOF

---

## Summary

- **Total Concurrency Levels Tested**: ${#CONCURRENCY_LEVELS[@]}
- **Improvements Detected**: $IMPROVEMENTS
- **Degradations Detected**: $DEGRADATIONS
- **No Baseline Set**: $NO_BASELINE

EOF

if [ $IMPROVEMENTS -gt 0 ]; then
    cat >> "$REPORT_FILE" << EOF

### 🎉 Recommendation

**$IMPROVEMENTS concurrency level(s) showed improvement!**

EOF
    if [ $IMPROVEMENTS -ge 3 ]; then
        cat >> "$REPORT_FILE" << EOF
Consider updating baselines for improved configurations:

\`\`\`bash
# For each improved run_type:
python3 utilities/athena/manage_baseline.py mark \\
    --engine $ENGINE \\
    --cluster $CLUSTER_SIZE \\
    --benchmark $BENCHMARK \\
    --run-type <run_type> \\
    --run-id <run_id> \\
    --user "$USER" \\
    --notes "Post-test analysis $(date +%Y-%m-%d) - verified improvement"
\`\`\`

EOF
    fi
fi

if [ $DEGRADATIONS -gt 0 ]; then
    cat >> "$REPORT_FILE" << EOF

### ⚠️ Action Required

**$DEGRADATIONS concurrency level(s) showed degradation.**

Investigate:
1. Configuration changes
2. Resource contention
3. Data skew
4. Query plan changes

EOF
fi

if [ $NO_BASELINE -gt 0 ]; then
    cat >> "$REPORT_FILE" << EOF

### 📌 Setup Required

**$NO_BASELINE concurrency level(s) have no baseline set.**

Set baselines to enable comparisons:

\`\`\`bash
# Show current best runs
python3 utilities/athena/query_athena_runs.py --engine $ENGINE --cluster $CLUSTER_SIZE --best-runs

# Mark baseline for each run_type
python3 utilities/athena/manage_baseline.py mark \\
    --engine $ENGINE \\
    --cluster $CLUSTER_SIZE \\
    --benchmark $BENCHMARK \\
    --run-type <run_type> \\
    --run-id <run_id> \\
    --user "$USER"
\`\`\`

EOF
fi

cat >> "$REPORT_FILE" << EOF

---

## Best Runs (All Configurations)

EOF

# Get best runs from Athena
echo "Querying best runs..."
BEST_RUNS_OUTPUT=$(python3 utilities/athena/query_athena_runs.py --engine "$ENGINE" --cluster "$CLUSTER_SIZE" --best-runs 2>&1 | grep -A 100 "Best Runs" || true)

if [ -n "$BEST_RUNS_OUTPUT" ]; then
    echo '```' >> "$REPORT_FILE"
    echo "$BEST_RUNS_OUTPUT" >> "$REPORT_FILE"
    echo '```' >> "$REPORT_FILE"
fi

cat >> "$REPORT_FILE" << EOF

---

## Next Steps

1. **Review Report**: Check `$REPORT_FILE`
2. **Update Baselines**: For improved configurations
3. **Investigate Degradations**: If any were detected
4. **Set Missing Baselines**: For new configurations

**Generated by**: Post-Test Analysis Automation
**Timestamp**: $(date '+%Y-%m-%d %H:%M:%S')

EOF

echo ""
echo "================================================================================"
echo -e "${GREEN}✓ Analysis Complete!${NC}"
echo "================================================================================"
echo ""
echo "📄 Markdown report: $REPORT_FILE"
echo "📊 CSV report:      $CSV_FILE"
echo ""

# Print summary
echo "Summary:"
echo "--------"
echo -e "Improvements:    ${GREEN}$IMPROVEMENTS${NC}"
echo -e "Degradations:    ${RED}$DEGRADATIONS${NC}"
echo -e "No Baseline:     ${YELLOW}$NO_BASELINE${NC}"
echo ""

if [ $IMPROVEMENTS -gt 0 ]; then
    echo -e "${GREEN}🎉 Great news! Performance improvements detected!${NC}"
    echo ""
fi

if [ $DEGRADATIONS -gt 0 ]; then
    echo -e "${RED}⚠️  Warning: Performance degradations detected. Review required.${NC}"
    echo ""
fi

echo "View detailed markdown report:"
echo "  cat $REPORT_FILE"
echo ""
echo "Import CSV to Excel/Google Sheets:"
echo "  open $CSV_FILE"
echo ""
echo "View current baselines:"
echo "  python3 utilities/athena/manage_baseline.py show --engine $ENGINE"
echo ""
