#!/usr/bin/env python3
"""
Analyze a single JMeter test run from S3 and generate a detailed report.

This script fetches statistics.json from S3 for a specific run and generates
a comprehensive markdown report with all performance metrics.

Usage:
    # Analyze latest run
    python analyze_single_run_from_s3.py \
        --s3-path s3://e6-jmeter/.../run_type=concurrency_8/

    # Analyze specific run ID
    python analyze_single_run_from_s3.py \
        --s3-path s3://e6-jmeter/.../run_type=concurrency_8/ \
        --run-id 20251031-070614
"""

import argparse
import sys
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, List

# Add utilities to path for imports
sys.path.insert(0, str(Path(__file__).parent))
from jmeter_s3_utils import (
    list_s3_files,
    load_statistics_from_s3,
    extract_query_metrics
)


def find_run_file(s3_path: str, run_id: Optional[str] = None) -> tuple[Optional[str], Optional[str]]:
    """
    Find statistics.json file for analysis.

    New structure: .../run_type=concurrency_X/run_id=YYYYMMDD-HHMMSS/statistics.json

    Args:
        s3_path: S3 path to concurrency directory
        run_id: Optional run ID (format: YYYYMMDD-HHMMSS)

    Returns:
        (full_s3_uri, run_id) or (None, None) if not found
    """
    # List all run_id folders
    files = list_s3_files(s3_path, 'run_id=')

    if not files:
        print(f"⚠️  No run_id folders found in {s3_path}")
        return None, None

    # Extract unique run_ids from folder paths
    run_ids = set()
    for f in files:
        match = re.search(r'run_id=(\d{8}-\d{6})/', f)
        if match:
            run_ids.add(match.group(1))

    if not run_ids:
        print(f"⚠️  No valid run_id folders found")
        return None, None

    run_ids = sorted(run_ids, reverse=True)  # Latest first

    # Extract bucket from s3_path
    bucket_match = re.search(r's3://([^/]+)/', s3_path)
    if not bucket_match:
        print(f"⚠️  Cannot parse S3 bucket from path")
        return None, None
    bucket = bucket_match.group(1)

    if run_id:
        # Find specific run ID
        if run_id not in run_ids:
            print(f"⚠️  Run ID {run_id} not found")
            return None, None

        # Build S3 path
        path_base = s3_path.replace(f"s3://{bucket}/", "")
        full_uri = f"s3://{bucket}/{path_base}run_id={run_id}/statistics.json"

        return full_uri, run_id
    else:
        # Use latest run
        latest_run_id = run_ids[0]

        # Build S3 path
        path_base = s3_path.replace(f"s3://{bucket}/", "")
        full_uri = f"s3://{bucket}/{path_base}run_id={latest_run_id}/statistics.json"

        # Format timestamp for display
        try:
            dt = datetime.strptime(latest_run_id, '%Y%m%d-%H%M%S')
            timestamp = dt.strftime('%Y-%m-%d %H:%M:%S')
            print(f"✓ Using latest run: {timestamp} ({latest_run_id})")
        except ValueError:
            print(f"✓ Using latest run: {latest_run_id}")

        return full_uri, latest_run_id


def generate_markdown_report(stats: Dict, metadata: Dict, output_path: str):
    """Generate comprehensive markdown report for a single run."""

    engine = metadata['engine']
    cluster = metadata['cluster_size']
    benchmark = metadata['benchmark']
    concurrency = metadata['concurrency']
    run_id = metadata['run_id']
    cores = metadata.get('cores', 'Unknown')

    # Extract timestamp for display
    ts_match = re.search(r'(\d{8})-(\d{6})', run_id)
    if ts_match:
        dt = datetime.strptime(f"{ts_match.group(1)}_{ts_match.group(2)}", '%Y%m%d_%H%M%S')
        run_timestamp = dt.strftime('%B %d, %Y at %H:%M:%S')
    else:
        run_timestamp = run_id

    lines = [
        f"# Single Run Analysis: {engine.upper()}",
        "",
        f"**Run Date**: {run_timestamp}",
        f"**Run ID**: `{run_id}`",
        f"**Engine**: {engine}",
        f"**Cluster Size**: {cluster} ({cores} cores)",
        f"**Benchmark**: {benchmark}",
        f"**Concurrency Level**: C={concurrency}",
        "",
        "---",
        ""
    ]

    # Overall metrics
    overall_metrics = extract_query_metrics(stats, 'Total')

    if overall_metrics:
        lines.extend([
            "## Overall Performance",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| **Average Latency** | {overall_metrics['avg']:.2f} sec |",
            f"| **Median (p50)** | {overall_metrics['median']:.2f} sec |",
            f"| **p90** | {overall_metrics['p90']:.2f} sec |",
            f"| **p95** | {overall_metrics['p95']:.2f} sec |",
            f"| **p99** | {overall_metrics['p99']:.2f} sec |",
            f"| **Min** | {overall_metrics['min']:.2f} sec |",
            f"| **Max** | {overall_metrics['max']:.2f} sec |",
            f"| **Error Rate** | {overall_metrics['error_pct']:.2f}% |",
            f"| **Total Queries** | {overall_metrics['samples']} |",
            "",
            "---",
            ""
        ])

    # Query-by-query breakdown
    query_names = sorted([k for k in stats.keys() if k != 'Total'])

    if query_names:
        lines.extend([
            "## Query-by-Query Performance",
            "",
            "| Query | Avg (s) | Median (s) | p90 (s) | p95 (s) | p99 (s) | Min (s) | Max (s) | Samples |",
            "|-------|---------|------------|---------|---------|---------|---------|---------|---------|"
        ])

        for query_name in query_names:
            metrics = extract_query_metrics(stats, query_name)
            if metrics:
                lines.append(
                    f"| {query_name} | "
                    f"{metrics['avg']:.2f} | "
                    f"{metrics['median']:.2f} | "
                    f"{metrics['p90']:.2f} | "
                    f"{metrics['p95']:.2f} | "
                    f"{metrics['p99']:.2f} | "
                    f"{metrics['min']:.2f} | "
                    f"{metrics['max']:.2f} | "
                    f"{metrics['samples']} |"
                )

        lines.extend([
            "",
            "---",
            ""
        ])

    # Performance distribution
    if query_names:
        lines.extend([
            "## Performance Distribution",
            "",
            "**Fastest Queries** (by average latency):",
            ""
        ])

        # Sort queries by average latency
        query_metrics = []
        for query_name in query_names:
            metrics = extract_query_metrics(stats, query_name)
            if metrics:
                query_metrics.append((query_name, metrics['avg']))

        query_metrics.sort(key=lambda x: x[1])

        # Top 5 fastest
        for i, (query_name, avg_latency) in enumerate(query_metrics[:5], 1):
            lines.append(f"{i}. **{query_name}**: {avg_latency:.2f} sec")

        lines.extend([
            "",
            "**Slowest Queries** (by average latency):",
            ""
        ])

        # Top 5 slowest
        for i, (query_name, avg_latency) in enumerate(query_metrics[-5:][::-1], 1):
            lines.append(f"{i}. **{query_name}**: {avg_latency:.2f} sec")

        lines.extend([
            "",
            "---",
            ""
        ])

    # Percentile analysis
    if overall_metrics:
        lines.extend([
            "## Latency Analysis",
            "",
            "**Latency Distribution**:",
            ""
        ])

        # Calculate percentile spread
        p50 = overall_metrics['median']
        p90 = overall_metrics['p90']
        p95 = overall_metrics['p95']
        p99 = overall_metrics['p99']

        p90_spread = ((p90 - p50) / p50 * 100) if p50 > 0 else 0
        p99_spread = ((p99 - p50) / p50 * 100) if p50 > 0 else 0

        lines.extend([
            f"- **50% of queries** completed in ≤ {p50:.2f} sec",
            f"- **90% of queries** completed in ≤ {p90:.2f} sec (+{p90_spread:.1f}% from median)",
            f"- **95% of queries** completed in ≤ {p95:.2f} sec",
            f"- **99% of queries** completed in ≤ {p99:.2f} sec (+{p99_spread:.1f}% from median)",
            "",
        ])

        # Performance consistency
        if p99_spread < 50:
            consistency = "✅ **Excellent** - Very consistent performance"
        elif p99_spread < 100:
            consistency = "✅ **Good** - Reasonably consistent performance"
        elif p99_spread < 200:
            consistency = "⚠️ **Moderate** - Some variability in performance"
        else:
            consistency = "🚨 **Poor** - High performance variability"

        lines.extend([
            f"**Performance Consistency**: {consistency}",
            "",
            "---",
            ""
        ])

    # Summary
    lines.extend([
        "## Summary",
        "",
        f"This run executed **{len(query_names)} unique queries** at concurrency level **C={concurrency}**.",
        ""
    ])

    if overall_metrics:
        # Performance assessment
        avg_latency = overall_metrics['avg']

        if concurrency <= 4:
            threshold_good = 5.0
            threshold_acceptable = 10.0
        elif concurrency <= 8:
            threshold_good = 8.0
            threshold_acceptable = 15.0
        else:
            threshold_good = 12.0
            threshold_acceptable = 20.0

        if avg_latency <= threshold_good:
            assessment = f"✅ **Excellent** - Average latency of {avg_latency:.2f}s is well within acceptable range for C={concurrency}"
        elif avg_latency <= threshold_acceptable:
            assessment = f"✅ **Good** - Average latency of {avg_latency:.2f}s is acceptable for C={concurrency}"
        else:
            assessment = f"⚠️ **Needs Attention** - Average latency of {avg_latency:.2f}s may be high for C={concurrency}"

        lines.append(f"**Performance Assessment**: {assessment}")
        lines.append("")

    # Additional info
    lines.extend([
        "---",
        "",
        f"**Generated from**: S3 run `{run_id}`",
        f"**Report generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        ""
    ])

    # Write to file
    with open(output_path, 'w') as f:
        f.write('\n'.join(lines))

    print(f"\n✅ Report written to: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description='Analyze a single JMeter test run from S3',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Analyze latest run
    python analyze_single_run_from_s3.py \\
        --s3-path s3://e6-jmeter/.../run_type=concurrency_8/

    # Analyze specific run ID
    python analyze_single_run_from_s3.py \\
        --s3-path s3://e6-jmeter/.../run_type=concurrency_8/ \\
        --run-id 20251031-070614
        """
    )

    parser.add_argument(
        '--s3-path',
        required=True,
        help='S3 path to concurrency directory (e.g., .../run_type=concurrency_8/)'
    )

    parser.add_argument(
        '--run-id',
        help='Specific run ID to analyze (format: YYYYMMDD-HHMMSS). If not provided, uses latest run.'
    )

    parser.add_argument(
        '--output-dir',
        default='reports',
        help='Output directory for reports (default: reports/)'
    )

    args = parser.parse_args()

    # Parse metadata from S3 path
    match = re.search(
        r'engine=([^/]+)/cluster_size=([^/]+)/benchmark=([^/]+)/(?:run_type=)?(concurrency_\d+|sequential)',
        args.s3_path
    )

    if not match:
        print("❌ ERROR: Cannot parse engine/cluster/benchmark/concurrency from S3 path")
        print("Expected format: .../engine=X/cluster_size=Y/benchmark=Z/run_type=concurrency_N/")
        sys.exit(1)

    engine = match.group(1)
    cluster = match.group(2)
    benchmark = match.group(3)
    run_type = match.group(4)

    # Extract concurrency
    if run_type.startswith('concurrency_'):
        concurrency = int(run_type.split('_')[1])
    else:
        concurrency = 1

    # Get cluster cores
    cluster_map = {
        'XS': 30,
        'S-2x2': 60,
        'M': 120,
        'S-4x4': 120,
        'L': 240,
    }
    cores = cluster_map.get(cluster, 'Unknown')

    print(f"\n{'='*70}")
    print(f"Single Run Analysis")
    print(f"{'='*70}")
    print(f"Engine: {engine}")
    print(f"Cluster: {cluster} ({cores} cores)")
    print(f"Benchmark: {benchmark}")
    print(f"Concurrency: C={concurrency}")
    if args.run_id:
        print(f"Run ID: {args.run_id}")
    else:
        print("Mode: Automatic (using latest run)")
    print(f"{'='*70}\n")

    # Find run file
    print("🔍 Finding statistics file...")
    run_file, run_id = find_run_file(args.s3_path, args.run_id)

    if not run_file or not run_id:
        print("\n❌ No statistics file found")
        sys.exit(1)

    # Load statistics
    print(f"📥 Loading statistics from S3...")
    stats = load_statistics_from_s3(run_file)

    if not stats:
        print("\n❌ Failed to load statistics")
        sys.exit(1)

    # Generate report
    print(f"\n{'='*70}")
    print("Generating Report")
    print(f"{'='*70}\n")

    # Create output filename with run ID
    filename = f"{engine}_{cluster}_C{concurrency}_SingleRun_{run_id}.md"
    output_path = Path(args.output_dir) / filename
    output_path.parent.mkdir(parents=True, exist_ok=True)

    metadata = {
        'engine': engine,
        'cluster_size': cluster,
        'benchmark': benchmark,
        'concurrency': concurrency,
        'run_id': run_id,
        'cores': cores
    }

    generate_markdown_report(stats, metadata, str(output_path))

    print(f"\n{'='*70}")
    print("✅ Analysis Complete!")
    print(f"{'='*70}\n")


if __name__ == '__main__':
    main()
