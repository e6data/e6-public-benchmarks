#!/bin/bash
# Master script to regenerate all Athena analysis reports
# Usage: ./utilities/athena/regenerate_all_reports.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

echo "=========================================="
echo "🔄 Regenerating All Athena Reports"
echo "=========================================="
echo ""

# Set Python path
export PYTHONPATH="$PROJECT_ROOT/utilities/athena"

echo "📊 Step 1: Basic Reports (All Runs & Best Runs)"
echo "--------------------------------------------------"
python3 utilities/athena/query_athena_runs.py 2>&1 | tee reports/athena_all_runs_report_v2.txt
python3 utilities/athena/generate_best_runs_report.py 2>&1 | tee reports/athena_best_runs_report_v2.txt
echo ""

echo "📈 Step 2: Advanced Reports (1-6)"
echo "--------------------------------------------------"
if [ -f /tmp/generate_advanced_reports.py ]; then
    python3 /tmp/generate_advanced_reports.py 2>&1 | tee reports/athena_advanced_reports_1_6.txt
else
    echo "⚠️  Warning: /tmp/generate_advanced_reports.py not found, skipping..."
fi
echo ""

echo "📅 Step 3: Advanced Reports (7-8)"
echo "--------------------------------------------------"
if [ -f /tmp/generate_remaining_reports_fixed.py ]; then
    python3 /tmp/generate_remaining_reports_fixed.py 2>&1 | tee reports/athena_advanced_reports_7_8.txt
else
    echo "⚠️  Warning: /tmp/generate_remaining_reports_fixed.py not found, skipping..."
fi
echo ""

echo "=========================================="
echo "✅ Report Regeneration Complete!"
echo "=========================================="
echo ""
echo "Generated Reports:"
echo "  - reports/athena_all_runs_report_v2.txt"
echo "  - reports/athena_best_runs_report_v2.txt"
echo "  - reports/athena_advanced_reports_1_6.txt"
echo "  - reports/athena_advanced_reports_7_8.txt"
echo "  - reports/ADVANCED_REPORTS_SUMMARY.md (update manually)"
echo ""
echo "💡 Next Steps:"
echo "  1. Review reports for performance trends"
echo "  2. Update ADVANCED_REPORTS_SUMMARY.md with latest insights"
echo "  3. Check for regressions in key metrics"
echo ""
