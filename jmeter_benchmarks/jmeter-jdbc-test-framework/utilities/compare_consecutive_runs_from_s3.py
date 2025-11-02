#!/usr/bin/env python3
"""
Compare two consecutive runs of the same engine/cluster/benchmark.
Useful for regression testing and performance tracking over time.

Usage:
    python compare_consecutive_runs_from_s3.py \\
        --base-path s3://e6-jmeter/jmeter-results/engine=e6data/cluster_size=S-2x2/benchmark=tpcds_29_1tb/

This will:
1. Find all concurrency levels under the base path
2. For each concurrency level, find the TWO most recent runs
3. Compare them to show performance changes
"""

import argparse
import sys
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Optional

# Add utilities to path for imports
sys.path.insert(0, str(Path(__file__).parent))
from jmeter_s3_utils import list_s3_files, load_statistics_from_s3, normalize_query_name, extract_query_metrics


def find_two_latest_runs(s3_path: str, base_s3_bucket: str, concurrency: int,
                          run_id1: Optional[str] = None, run_id2: Optional[str] = None) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """
    Find statistics.json files for comparison.

    If run_id1 and run_id2 are provided, find those specific runs.
    Otherwise, find the two most recent runs.

    Args:
        s3_path: S3 path to concurrency directory
        base_s3_bucket: S3 bucket name
        concurrency: Concurrency level
        run_id1: Optional run ID (format: YYYYMMDD-HHMMSS) for first/previous run
        run_id2: Optional run ID (format: YYYYMMDD-HHMMSS) for second/latest run

    Returns:
        (previous_file, latest_file, previous_run_id, latest_run_id) as full S3 URIs and run IDs, or (None, None, None, None) if not found
    """
    # List all run_id folders in this concurrency path
    # New structure: .../run_type=concurrency_X/run_id=YYYYMMDD-HHMMSS/statistics.json
    files = list_s3_files(s3_path, 'run_id=')

    if not files:
        print(f"⚠️  No run_id folders found in {s3_path}")
        return None, None, None, None

    # Extract unique run_ids from folder paths
    run_ids = set()
    for f in files:
        match = re.search(r'run_id=(\d{8}-\d{6})/', f)
        if match:
            run_ids.add(match.group(1))

    if not run_ids:
        print(f"⚠️  No valid run_id folders found")
        return None, None, None, None

    run_ids = sorted(run_ids, reverse=True)  # Latest first

    if run_id1 and run_id2:
        # Verify specific run IDs exist
        if run_id1 not in run_ids:
            print(f"⚠️  Run ID {run_id1} not found for C={concurrency}")
            return None, None, None, None
        if run_id2 not in run_ids:
            print(f"⚠️  Run ID {run_id2} not found for C={concurrency}")
            return None, None, None, None

        # Build S3 paths to statistics.json files
        path_base = s3_path.replace(f"s3://{base_s3_bucket}/", "")
        previous = f"s3://{base_s3_bucket}/{path_base}run_id={run_id1}/statistics.json"
        latest = f"s3://{base_s3_bucket}/{path_base}run_id={run_id2}/statistics.json"

        previous_ts = format_run_id(run_id1)
        latest_ts = format_run_id(run_id2)

        print(f"✓ C={concurrency}: Comparing {previous_ts} ({run_id1}) → {latest_ts} ({run_id2})")

        return previous, latest, run_id1, run_id2

    else:
        # Find two most recent runs
        if len(run_ids) < 2:
            print(f"⚠️  Only found {len(run_ids)} run(s) for C={concurrency}, need at least 2 to compare")
            return None, None, None, None

        latest_run_id = run_ids[0]
        previous_run_id = run_ids[1]

        # Build S3 paths to statistics.json files
        path_base = s3_path.replace(f"s3://{base_s3_bucket}/", "")
        latest = f"s3://{base_s3_bucket}/{path_base}run_id={latest_run_id}/statistics.json"
        previous = f"s3://{base_s3_bucket}/{path_base}run_id={previous_run_id}/statistics.json"

        # Format timestamps for display
        latest_ts = format_run_id(latest_run_id)
        previous_ts = format_run_id(previous_run_id)

        print(f"✓ C={concurrency}: Comparing {previous_ts} → {latest_ts}")

        return previous, latest, previous_run_id, latest_run_id


def format_run_id(run_id: str) -> str:
    """
    Format run ID to human-readable timestamp.

    Args:
        run_id: Run ID in format YYYYMMDD-HHMMSS

    Returns:
        Formatted timestamp string like "2025-10-31 07:06:14"
    """
    try:
        dt = datetime.strptime(run_id, '%Y%m%d-%H%M%S')
        return dt.strftime('%Y-%m-%d %H:%M:%S')
    except ValueError:
        return run_id


def extract_run_id_from_path(path: str) -> str:
    """
    Extract run ID from S3 path containing run_id= folder.

    Args:
        path: S3 path like .../run_id=20251031-070614/...

    Returns:
        Run ID string like "20251031-070614" or "unknown"
    """
    match = re.search(r'run_id=(\d{8}-\d{6})', path)
    if match:
        return match.group(1)
    return "unknown"


def find_concurrency_runs(base_s3_path: str) -> List[Tuple[int, str]]:
    """
    Find all concurrency run directories under a base path.

    Returns:
        List of (concurrency_level, full_s3_path) tuples, sorted by concurrency
    """
    base_path = base_s3_path.rstrip('/') + '/'
    files = list_s3_files(base_path)

    concurrency_runs = set()
    for file in files:
        # Try both formats:
        # 1. run_type=concurrency_X/
        # 2. concurrency_X/ (direct)
        match = re.search(r'run_type=(concurrency_\d+)/', file)
        if match:
            run_type = match.group(1)
            concurrency = int(run_type.split('_')[1])
            full_path = base_path + 'run_type=' + run_type + '/'
            concurrency_runs.add((concurrency, full_path))
        else:
            # Try direct format
            match = re.search(r'/(concurrency_\d+)/', file)
            if match:
                run_type = match.group(1)
                concurrency = int(run_type.split('_')[1])
                full_path = base_path + run_type + '/'
                concurrency_runs.add((concurrency, full_path))

    return sorted(list(concurrency_runs))


def calculate_change(previous: float, latest: float) -> Tuple[float, str]:
    """
    Calculate percentage change and trend indicator.

    Returns:
        (percent_change, trend_emoji)
    """
    if previous == 0:
        return 0.0, "➖"

    pct_change = ((latest - previous) / previous) * 100

    # For latency, lower is better
    if pct_change < -2:  # Improved by >2%
        trend = "⬇️ 🎉"  # Improvement
    elif pct_change > 2:  # Degraded by >2%
        trend = "⬆️ 🚨"  # Degradation
    else:  # Within 2%
        trend = "➖"  # Stable

    return pct_change, trend


def compare_runs(previous_stats: Dict, latest_stats: Dict, concurrency: int) -> Dict:
    """
    Compare two runs and calculate changes.

    Returns:
        Dictionary with comparison metrics including query-by-query analysis
    """
    result = {
        'concurrency': concurrency,
        'previous': {},
        'latest': {},
        'changes': {},
        'queries': []
    }

    # Get overall metrics using 'Total' key
    prev_metrics = extract_query_metrics(previous_stats, 'Total')
    latest_metrics = extract_query_metrics(latest_stats, 'Total')

    if not prev_metrics or not latest_metrics:
        print(f"⚠️  Warning: Could not extract Total metrics for C={concurrency}")
        return result

    metrics = ['avg', 'median', 'p90', 'p95', 'p99']

    for metric in metrics:
        prev_val = prev_metrics.get(metric, 0)
        latest_val = latest_metrics.get(metric, 0)

        result['previous'][metric] = prev_val
        result['latest'][metric] = latest_val

        pct_change, trend = calculate_change(prev_val, latest_val)
        result['changes'][metric] = {
            'percent': pct_change,
            'trend': trend
        }

    # Calculate sample counts
    result['previous']['samples'] = prev_metrics.get('samples', 0)
    result['latest']['samples'] = latest_metrics.get('samples', 0)

    # Query-by-query comparison
    query_names = set()
    for key in previous_stats.keys():
        if key != 'Total':
            query_names.add(key)
    for key in latest_stats.keys():
        if key != 'Total':
            query_names.add(key)

    for query_name in sorted(query_names):
        prev_query = extract_query_metrics(previous_stats, query_name)
        latest_query = extract_query_metrics(latest_stats, query_name)

        if prev_query and latest_query:
            prev_avg = prev_query['avg']
            latest_avg = latest_query['avg']
            pct_change, trend = calculate_change(prev_avg, latest_avg)

            result['queries'].append({
                'name': query_name,
                'previous_avg': prev_avg,
                'latest_avg': latest_avg,
                'change_pct': pct_change,
                'trend': trend
            })

    return result


def generate_markdown_report(comparisons: List[Dict], engine: str, cluster: str,
                            benchmark: str, output_path: str):
    """Generate markdown comparison report."""

    timestamp = datetime.now().strftime('%Y%m%d')

    lines = [
        f"# Consecutive Run Comparison: {engine.upper()}",
        "",
        f"**Generated**: {datetime.now().strftime('%B %d, %Y')}",
        f"**Engine**: {engine}",
        f"**Cluster Size**: {cluster}",
        f"**Benchmark**: {benchmark}",
        "",
        "---",
        "",
        "## Performance Changes by Concurrency Level",
        ""
    ]

    # Overall summary table
    lines.extend([
        "| Concurrency | Previous Avg | Latest Avg | Change | Trend |",
        "|-------------|--------------|------------|--------|-------|"
    ])

    for comp in comparisons:
        c = comp['concurrency']
        prev_avg = comp['previous']['avg']
        latest_avg = comp['latest']['avg']
        change_pct = comp['changes']['avg']['percent']
        trend = comp['changes']['avg']['trend']

        lines.append(
            f"| **C={c}** | {prev_avg:.2f} sec | {latest_avg:.2f} sec | "
            f"{change_pct:+.1f}% | {trend} |"
        )

    lines.extend([
        "",
        "**Legend**:",
        "- ⬇️ 🎉 = Improved (>2% faster)",
        "- ⬆️ 🚨 = Degraded (>2% slower)",
        "- ➖ = Stable (within ±2%)",
        "",
        "---",
        ""
    ])

    # Detailed breakdown by concurrency
    for comp in comparisons:
        c = comp['concurrency']
        lines.extend([
            f"## Concurrency Level: C={c}",
            "",
            "| Metric | Previous Run | Latest Run | Change | Trend |",
            "|--------|--------------|------------|--------|-------|"
        ])

        metrics = ['avg', 'median', 'p90', 'p95', 'p99']
        metric_labels = {
            'avg': 'Average',
            'median': 'Median (p50)',
            'p90': 'p90',
            'p95': 'p95',
            'p99': 'p99'
        }

        for metric in metrics:
            prev_val = comp['previous'][metric]
            latest_val = comp['latest'][metric]
            change_pct = comp['changes'][metric]['percent']
            trend = comp['changes'][metric]['trend']

            lines.append(
                f"| **{metric_labels[metric]}** | {prev_val:.2f} sec | "
                f"{latest_val:.2f} sec | {change_pct:+.1f}% | {trend} |"
            )

        # Sample counts
        prev_samples = comp['previous']['samples']
        latest_samples = comp['latest']['samples']
        lines.extend([
            "",
            f"**Sample Counts**: Previous={prev_samples}, Latest={latest_samples}",
            ""
        ])

        # Query-by-query comparison
        if comp.get('queries'):
            lines.extend([
                "### Query-by-Query Comparison",
                "",
                "| Query | Previous Avg | Latest Avg | Change | Trend |",
                "|-------|--------------|------------|--------|-------|"
            ])

            for query in comp['queries']:
                q_name = query['name']
                prev_avg = query['previous_avg']
                latest_avg = query['latest_avg']
                change_pct = query['change_pct']
                trend = query['trend']

                lines.append(
                    f"| {q_name} | {prev_avg:.2f}s | {latest_avg:.2f}s | "
                    f"{change_pct:+.1f}% | {trend} |"
                )

        lines.extend([
            "",
            "---",
            ""
        ])

    # Summary findings
    lines.extend([
        "## Summary",
        ""
    ])

    # Count improvements, degradations, stable
    improvements = 0
    degradations = 0
    stable = 0

    for comp in comparisons:
        change = comp['changes']['avg']['percent']
        if change < -2:
            improvements += 1
        elif change > 2:
            degradations += 1
        else:
            stable += 1

    total = len(comparisons)

    lines.extend([
        f"- **Total Concurrency Levels Compared**: {total}",
        f"- **Improvements** (>2% faster): {improvements} ({improvements/total*100:.0f}%)",
        f"- **Degradations** (>2% slower): {degradations} ({degradations/total*100:.0f}%)",
        f"- **Stable** (within ±2%): {stable} ({stable/total*100:.0f}%)",
        ""
    ])

    # Overall verdict
    if improvements > degradations:
        lines.append("### ✅ Overall Verdict: **Performance Improved**")
    elif degradations > improvements:
        lines.append("### 🚨 Overall Verdict: **Performance Degraded**")
    else:
        lines.append("### ➖ Overall Verdict: **Performance Stable**")

    lines.extend([
        "",
        "---",
        "",
        f"**Generated from**: {output_path}",
        ""
    ])

    # Write to file
    with open(output_path, 'w') as f:
        f.write('\n'.join(lines))

    print(f"\n✅ Markdown report written to: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description='Compare consecutive runs of the same engine/cluster/benchmark',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Compare two most recent runs automatically
    python compare_consecutive_runs_from_s3.py \\
        --base-path s3://e6-jmeter/jmeter-results/engine=e6data/cluster_size=S-2x2/benchmark=tpcds_29_1tb/

    # Compare specific run IDs
    python compare_consecutive_runs_from_s3.py \\
        --base-path s3://e6-jmeter/jmeter-results/engine=e6data/cluster_size=S-2x2/benchmark=tpcds_29_1tb/ \\
        --run-id1 20251030-171659 \\
        --run-id2 20251031-070614

This will find all concurrency levels and compare the specified runs (or two most recent if not specified).
        """
    )

    parser.add_argument(
        '--base-path',
        required=True,
        help='Base S3 path containing concurrency runs'
    )

    parser.add_argument(
        '--output-dir',
        default='reports',
        help='Output directory for reports (default: reports/)'
    )

    parser.add_argument(
        '--run-id1',
        help='First/previous run ID to compare (format: YYYYMMDD-HHMMSS). If not provided, uses 2nd most recent run.'
    )

    parser.add_argument(
        '--run-id2',
        help='Second/latest run ID to compare (format: YYYYMMDD-HHMMSS). If not provided, uses most recent run.'
    )

    args = parser.parse_args()

    # Validate run IDs - either both provided or neither
    if (args.run_id1 and not args.run_id2) or (args.run_id2 and not args.run_id1):
        print("❌ ERROR: Both --run-id1 and --run-id2 must be provided together")
        sys.exit(1)

    # Parse bucket and metadata from path
    bucket_match = re.search(r's3://([^/]+)/', args.base_path)
    if not bucket_match:
        print("❌ ERROR: Cannot parse S3 bucket from path")
        sys.exit(1)

    bucket = bucket_match.group(1)

    # Parse engine/cluster/benchmark from path
    match = re.search(
        r'engine=([^/]+)/cluster_size=([^/]+)/benchmark=([^/]+)',
        args.base_path
    )
    if not match:
        print("❌ ERROR: Cannot parse engine/cluster/benchmark from path")
        print("Expected format: .../engine=X/cluster_size=Y/benchmark=Z/")
        sys.exit(1)

    engine = match.group(1)
    cluster = match.group(2)
    benchmark = match.group(3)

    print(f"\n{'='*70}")
    print(f"Comparing Consecutive Runs")
    print(f"{'='*70}")
    print(f"Engine: {engine}")
    print(f"Cluster: {cluster}")
    print(f"Benchmark: {benchmark}")
    if args.run_id1 and args.run_id2:
        print(f"Run ID 1: {args.run_id1}")
        print(f"Run ID 2: {args.run_id2}")
    else:
        print("Mode: Automatic (comparing 2 most recent runs)")
    print(f"{'='*70}\n")

    # Find all concurrency runs
    print("🔍 Finding concurrency levels...")
    concurrency_runs = find_concurrency_runs(args.base_path)

    if not concurrency_runs:
        print("❌ No concurrency runs found")
        sys.exit(1)

    print(f"✓ Found {len(concurrency_runs)} concurrency level(s)")
    print()

    # Compare each concurrency level
    comparisons = []
    run_id1_actual = None
    run_id2_actual = None

    for concurrency, s3_path in concurrency_runs:
        print(f"\n{'─'*70}")
        print(f"Concurrency Level: C={concurrency}")
        print(f"{'─'*70}")

        # Find two runs to compare (specific run IDs or latest two)
        # Returns: (previous_file, latest_file, previous_run_id, latest_run_id)
        previous_file, latest_file, prev_run_id, latest_run_id = find_two_latest_runs(
            s3_path, bucket, concurrency,
            run_id1=args.run_id1,
            run_id2=args.run_id2
        )

        if not latest_file or not previous_file:
            continue

        # Store run IDs from first successful comparison (should be same across all concurrency levels)
        if run_id1_actual is None:
            run_id1_actual = prev_run_id
            run_id2_actual = latest_run_id

        # Load statistics
        print(f"📥 Loading statistics...")
        previous_stats = load_statistics_from_s3(previous_file)
        latest_stats = load_statistics_from_s3(latest_file)

        if not previous_stats or not latest_stats:
            print(f"⚠️  Failed to load statistics for C={concurrency}")
            continue

        # Compare
        comparison = compare_runs(previous_stats, latest_stats, concurrency)
        comparisons.append(comparison)

        # Show quick summary
        prev_avg = comparison['previous']['avg']
        latest_avg = comparison['latest']['avg']
        change = comparison['changes']['avg']['percent']
        trend = comparison['changes']['avg']['trend']

        print(f"📊 Average Latency: {prev_avg:.2f}s → {latest_avg:.2f}s ({change:+.1f}%) {trend}")

    if not comparisons:
        print("\n❌ No comparisons could be performed")
        sys.exit(1)

    # Generate report
    print(f"\n{'='*70}")
    print("Generating Reports")
    print(f"{'='*70}\n")

    # Create filename with run IDs
    if run_id1_actual and run_id2_actual:
        md_filename = f"{engine}_{cluster}_ConsecutiveRuns_{run_id1_actual}_vs_{run_id2_actual}.md"
    else:
        # Fallback to timestamp if run IDs not available
        timestamp = datetime.now().strftime('%Y%m%d')
        md_filename = f"{engine}_{cluster}_ConsecutiveRuns_{timestamp}.md"

    md_path = Path(args.output_dir) / md_filename
    md_path.parent.mkdir(parents=True, exist_ok=True)

    generate_markdown_report(comparisons, engine, cluster, benchmark, str(md_path))

    print(f"\n{'='*70}")
    print("✅ Comparison Complete!")
    print(f"{'='*70}\n")


if __name__ == '__main__':
    main()
