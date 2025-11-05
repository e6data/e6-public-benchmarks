#!/usr/bin/env bash
#
# Compare concurrency scaling between two engines (e.g., E6Data vs DBR)
#
# Usage:
#   ./utilities/compare_engines_concurrency.sh M tpcds_29_1tb
#   ./utilities/compare_engines_concurrency.sh M S-2x2 tpcds_29_1tb markdown > comparison.md
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Parse arguments - support both old and new formats
if [ $# -lt 2 ]; then
    echo "Usage: $0 <e6_cluster_size> [dbr_cluster_size] <benchmark> [format]"
    echo ""
    echo "Arguments:"
    echo "  e6_cluster_size     E6data cluster size (e.g., M, M-4x4, L-8x8)"
    echo "  dbr_cluster_size    DBR cluster size (optional, defaults to same as e6data)"
    echo "  benchmark           Benchmark name (e.g., tpcds_29_1tb)"
    echo "  format              Output format: text (default), markdown, json"
    echo ""
    echo "Examples:"
    echo "  $0 M tpcds_29_1tb                    # Both engines use M"
    echo "  $0 M S-2x2 tpcds_29_1tb              # E6data M vs DBR S-2x2"
    echo "  $0 M-4x4 S-2x2 tpcds_29_1tb markdown > comparison.md"
    exit 1
fi

# Determine if we have separate cluster sizes or same for both
if [ $# -eq 2 ]; then
    # Old format: cluster_size benchmark
    E6_CLUSTER_SIZE="$1"
    DBR_CLUSTER_SIZE="$1"
    BENCHMARK="$2"
    FORMAT="text"
elif [ $# -eq 3 ]; then
    # Could be: cluster_size benchmark format OR e6_size dbr_size benchmark
    if [[ "$3" =~ ^(text|markdown|json)$ ]]; then
        # Old format with format: cluster_size benchmark format
        E6_CLUSTER_SIZE="$1"
        DBR_CLUSTER_SIZE="$1"
        BENCHMARK="$2"
        FORMAT="$3"
    else
        # New format: e6_size dbr_size benchmark
        E6_CLUSTER_SIZE="$1"
        DBR_CLUSTER_SIZE="$2"
        BENCHMARK="$3"
        FORMAT="text"
    fi
else
    # New format with format: e6_size dbr_size benchmark format
    E6_CLUSTER_SIZE="$1"
    DBR_CLUSTER_SIZE="$2"
    BENCHMARK="$3"
    FORMAT="${4:-text}"
fi

ENGINE1="e6data"
ENGINE2="dbr"

echo "Comparing concurrency scaling: E6Data vs DBR" >&2
echo "E6Data Cluster Size: $E6_CLUSTER_SIZE" >&2
echo "DBR Cluster Size: $DBR_CLUSTER_SIZE" >&2
echo "Benchmark: $BENCHMARK" >&2
echo "" >&2

# Generate summaries for both engines
echo "Generating E6Data summary..." >&2
E6_SUMMARY=$(python3 "$SCRIPT_DIR/summarize_concurrency_runs.py" \
    --engine "$ENGINE1" \
    --cluster-size "$E6_CLUSTER_SIZE" \
    --benchmark "$BENCHMARK" \
    --format json 2>/dev/null)

echo "Generating DBR summary..." >&2
DBR_SUMMARY=$(python3 "$SCRIPT_DIR/summarize_concurrency_runs.py" \
    --engine "$ENGINE2" \
    --cluster-size "$DBR_CLUSTER_SIZE" \
    --benchmark "$BENCHMARK" \
    --format json 2>/dev/null)

# Use Python to generate comparison
python3 - "$E6_SUMMARY" "$DBR_SUMMARY" "$FORMAT" <<'PYTHON_SCRIPT'
import json
import sys

def format_text_comparison(e6_data, dbr_data):
    """Format comparison as text."""
    output = []
    output.append("=" * 140)
    output.append("ENGINE COMPARISON: E6DATA vs DBR - CONCURRENCY SCALING")
    output.append("=" * 140)
    output.append(f"Cluster Size: {e6_data['cluster_size']}")
    output.append(f"Benchmark: {e6_data['benchmark']}")
    output.append("")

    # Get all concurrency levels from both engines
    e6_levels = sorted(map(int, e6_data['summaries'].keys()))
    dbr_levels = sorted(map(int, dbr_data['summaries'].keys()))
    common_levels = sorted(set(e6_levels) & set(dbr_levels))

    if not common_levels:
        output.append("⚠️  No common concurrency levels found between engines")
        return "\n".join(output)

    output.append(f"Common Concurrency Levels: {', '.join(map(str, common_levels))}")
    output.append("")

    # Performance comparison for each concurrency level
    for c in common_levels:
        e6_metrics = e6_data['summaries'][str(c)]
        dbr_metrics = dbr_data['summaries'][str(c)]

        output.append("-" * 140)
        output.append(f"CONCURRENCY LEVEL: {c} threads")
        output.append("-" * 140)
        output.append(f"{'Metric':<30} {'E6Data':>15} {'DBR':>15} {'Improvement':>20} {'Winner':>15}")
        output.append("-" * 140)

        metrics = [
            ('Avg Response (sec)', 'avg_time_sec', 'lower'),
            ('Median p50 (sec)', 'median_time_sec', 'lower'),
            ('p95 Latency (sec)', 'p95_latency_sec', 'lower'),
            ('p99 Latency (sec)', 'p99_latency_sec', 'lower'),
            ('Throughput (q/s)', 'throughput', 'higher'),
            ('Total Time (sec)', 'total_time_sec', 'lower'),
        ]

        for label, key, better in metrics:
            e6_val = e6_metrics[key]
            dbr_val = dbr_metrics[key]

            if dbr_val > 0:
                if better == 'lower':
                    improvement = ((dbr_val - e6_val) / dbr_val) * 100
                    winner = "✅ E6Data" if e6_val < dbr_val else "⚠️  DBR"
                else:  # higher is better
                    improvement = ((e6_val - dbr_val) / dbr_val) * 100
                    winner = "✅ E6Data" if e6_val > dbr_val else "⚠️  DBR"
            else:
                improvement = 0
                winner = "🟰 Tie"

            improvement_str = f"{improvement:+.1f}%" if abs(improvement) > 0.1 else "~0%"
            output.append(f"{label:<30} {e6_val:>15.2f} {dbr_val:>15.2f} {improvement_str:>20} {winner:>15}")

        output.append("")

    # Scaling efficiency comparison
    output.append("-" * 140)
    output.append("SCALING EFFICIENCY COMPARISON")
    output.append("-" * 140)
    output.append(f"{'Concurrency':<15} {'E6Data Throughput':>20} {'DBR Throughput':>20} {'E6Data Efficiency':>20} {'DBR Efficiency':>20}")
    output.append("-" * 140)

    if len(common_levels) > 1:
        baseline_c = common_levels[0]
        e6_baseline = e6_data['summaries'][str(baseline_c)]['throughput']
        dbr_baseline = dbr_data['summaries'][str(baseline_c)]['throughput']

        for c in common_levels:
            e6_throughput = e6_data['summaries'][str(c)]['throughput']
            dbr_throughput = dbr_data['summaries'][str(c)]['throughput']

            scaling_factor = c / baseline_c
            e6_actual = e6_throughput / e6_baseline if e6_baseline > 0 else 0
            dbr_actual = dbr_throughput / dbr_baseline if dbr_baseline > 0 else 0

            e6_efficiency = (e6_actual / scaling_factor * 100) if scaling_factor > 0 else 0
            dbr_efficiency = (dbr_actual / scaling_factor * 100) if scaling_factor > 0 else 0

            output.append(f"{c:<15} {e6_throughput:>20.2f} {dbr_throughput:>20.2f} {e6_efficiency:>19.1f}% {dbr_efficiency:>19.1f}%")

    output.append("")
    output.append("=" * 140)

    return "\n".join(output)


def format_markdown_comparison(e6_data, dbr_data):
    """Format comparison as markdown."""
    output = []
    output.append("# Engine Comparison: E6Data vs DBR")
    output.append("## Concurrency Scaling Analysis")
    output.append("")
    output.append(f"**Cluster Size:** {e6_data['cluster_size']}  ")
    output.append(f"**Benchmark:** {e6_data['benchmark']}")
    output.append("")

    # Get common concurrency levels
    e6_levels = sorted(map(int, e6_data['summaries'].keys()))
    dbr_levels = sorted(map(int, dbr_data['summaries'].keys()))
    common_levels = sorted(set(e6_levels) & set(dbr_levels))

    if not common_levels:
        output.append("⚠️ No common concurrency levels found between engines")
        return "\n".join(output)

    output.append(f"**Common Concurrency Levels:** {', '.join(map(str, common_levels))}")
    output.append("")

    # Performance comparison for each level
    for c in common_levels:
        e6_metrics = e6_data['summaries'][str(c)]
        dbr_metrics = dbr_data['summaries'][str(c)]

        output.append(f"## Concurrency Level: {c} threads")
        output.append("")
        output.append("| Metric | E6Data | DBR | Improvement | Winner |")
        output.append("| --- | --- | --- | --- | --- |")

        metrics = [
            ('Avg Response (sec)', 'avg_time_sec', 'lower'),
            ('Median p50 (sec)', 'median_time_sec', 'lower'),
            ('p90 (sec)', 'p90_latency_sec', 'lower'),
            ('p95 (sec)', 'p95_latency_sec', 'lower'),
            ('p99 (sec)', 'p99_latency_sec', 'lower'),
            ('Throughput (q/s)', 'throughput', 'higher'),
            ('Total Time (sec)', 'total_time_sec', 'lower'),
        ]

        for label, key, better in metrics:
            e6_val = e6_metrics[key]
            dbr_val = dbr_metrics[key]

            if dbr_val > 0:
                if better == 'lower':
                    improvement = ((dbr_val - e6_val) / dbr_val) * 100
                    winner = "✅ E6Data" if e6_val < dbr_val else "⚠️ DBR"
                else:
                    improvement = ((e6_val - dbr_val) / dbr_val) * 100
                    winner = "✅ E6Data" if e6_val > dbr_val else "⚠️ DBR"
            else:
                improvement = 0
                winner = "🟰 Tie"

            improvement_str = f"{improvement:+.1f}%" if abs(improvement) > 0.1 else "~0%"
            output.append(f"| {label} | {e6_val:.2f} | {dbr_val:.2f} | {improvement_str} | {winner} |")

        output.append("")

    # Scaling efficiency
    output.append("## Scaling Efficiency Comparison")
    output.append("")
    output.append("| Concurrency | E6Data Throughput | DBR Throughput | E6Data Efficiency | DBR Efficiency |")
    output.append("| --- | --- | --- | --- | --- |")

    if len(common_levels) > 1:
        baseline_c = common_levels[0]
        e6_baseline = e6_data['summaries'][str(baseline_c)]['throughput']
        dbr_baseline = dbr_data['summaries'][str(baseline_c)]['throughput']

        for c in common_levels:
            e6_throughput = e6_data['summaries'][str(c)]['throughput']
            dbr_throughput = dbr_data['summaries'][str(c)]['throughput']

            scaling_factor = c / baseline_c
            e6_actual = e6_throughput / e6_baseline if e6_baseline > 0 else 0
            dbr_actual = dbr_throughput / dbr_baseline if dbr_baseline > 0 else 0

            e6_efficiency = (e6_actual / scaling_factor * 100) if scaling_factor > 0 else 0
            dbr_efficiency = (dbr_actual / scaling_factor * 100) if scaling_factor > 0 else 0

            output.append(f"| {c} | {e6_throughput:.2f} | {dbr_throughput:.2f} | {e6_efficiency:.1f}% | {dbr_efficiency:.1f}% |")

    output.append("")
    output.append("**Note:** Efficiency of 100% means perfect linear scaling.")

    return "\n".join(output)


if __name__ == '__main__':
    e6_json = sys.argv[1]
    dbr_json = sys.argv[2]
    output_format = sys.argv[3]

    e6_data = json.loads(e6_json)
    dbr_data = json.loads(dbr_json)

    if output_format == 'markdown':
        print(format_markdown_comparison(e6_data, dbr_data))
    elif output_format == 'json':
        result = {
            'e6data': e6_data,
            'dbr': dbr_data
        }
        print(json.dumps(result, indent=2))
    else:  # text
        print(format_text_comparison(e6_data, dbr_data))

PYTHON_SCRIPT
