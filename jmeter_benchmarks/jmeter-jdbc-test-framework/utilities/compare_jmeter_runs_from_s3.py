#!/usr/bin/env python3
"""
Compare two JMeter runs from S3 and generate standardized reports.

Usage:
    python compare_jmeter_runs.py S3_PATH_1 S3_PATH_2 [--output-dir reports]

Example:
    python compare_jmeter_runs.py \
        s3://e6-jmeter/jmeter-results/engine=e6data/cluster_size=M/benchmark=tpcds_29_1tb/run_type=concurrency_2/ \
        s3://e6-jmeter/jmeter-results/engine=dbr/cluster_size=S-4x4/benchmark=tpcds_29_1tb/run_type=concurrency_2/
"""

import sys
import csv
import argparse
from pathlib import Path
from typing import Dict, List
import tempfile

# Import our utilities
from jmeter_s3_utils import (
    JMeterS3Path,
    download_jmeter_statistics,
    load_jmeter_statistics,
    extract_query_metrics,
    create_query_mapping,
    calculate_percentage_diff,
    format_percentage,
    get_timestamp,
)


def generate_comparison_csv(
    engine1_name: str,
    engine2_name: str,
    stats1: Dict,
    stats2: Dict,
    query_mapping: Dict,
    output_file: Path
):
    """Generate detailed CSV comparison."""

    with open(output_file, 'w', newline='') as f:
        writer = csv.writer(f)

        # Header
        header = [
            'Query',
            f'{engine1_name}_Avg(s)',
            f'{engine1_name}_Median(s)',
            f'{engine1_name}_p90(s)',
            f'{engine1_name}_p95(s)',
            f'{engine1_name}_p99(s)',
            f'{engine1_name}_Min(s)',
            f'{engine1_name}_Max(s)',
            f'{engine2_name}_Avg(s)',
            f'{engine2_name}_Median(s)',
            f'{engine2_name}_p90(s)',
            f'{engine2_name}_p95(s)',
            f'{engine2_name}_p99(s)',
            f'{engine2_name}_Min(s)',
            f'{engine2_name}_Max(s)',
            'Diff_Avg(%)',
            'Diff_Median(%)',
            'Diff_p90(%)',
            'Diff_p95(%)',
            'Diff_p99(%)',
            'Diff_Min(%)',
            'Diff_Max(%)',
        ]
        writer.writerow(header)

        # Query data
        for query_name in sorted(query_mapping.keys()):
            q1_name, q2_name = query_mapping[query_name]

            m1 = extract_query_metrics(stats1, q1_name)
            m2 = extract_query_metrics(stats2, q2_name)

            if not m1 or not m2:
                continue

            row = [query_name]

            # Engine 1 metrics
            row.extend([
                f"{m1['avg']:.2f}",
                f"{m1['median']:.2f}",
                f"{m1['p90']:.2f}",
                f"{m1['p95']:.2f}",
                f"{m1['p99']:.2f}",
                f"{m1['min']:.2f}",
                f"{m1['max']:.2f}",
            ])

            # Engine 2 metrics
            row.extend([
                f"{m2['avg']:.2f}",
                f"{m2['median']:.2f}",
                f"{m2['p90']:.2f}",
                f"{m2['p95']:.2f}",
                f"{m2['p99']:.2f}",
                f"{m2['min']:.2f}",
                f"{m2['max']:.2f}",
            ])

            # Differences (positive = engine1 faster)
            for metric in ['avg', 'median', 'p90', 'p95', 'p99', 'min', 'max']:
                diff = calculate_percentage_diff(m1[metric], m2[metric])
                row.append(f"{diff:.1f}")

            writer.writerow(row)

        # Summary statistics
        writer.writerow([])
        writer.writerow(['SUMMARY STATISTICS'])

        for stat_label in ['Average', 'Median', 'p90', 'p95', 'p99']:
            metric_key = stat_label.lower()

            # Collect values
            vals1 = []
            vals2 = []
            for query_name in query_mapping.keys():
                q1_name, q2_name = query_mapping[query_name]
                m1 = extract_query_metrics(stats1, q1_name)
                m2 = extract_query_metrics(stats2, q2_name)
                if m1 and m2:
                    vals1.append(m1[metric_key])
                    vals2.append(m2[metric_key])

            if vals1 and vals2:
                avg1 = sum(vals1) / len(vals1)
                avg2 = sum(vals2) / len(vals2)
                diff = calculate_percentage_diff(avg1, avg2)

                writer.writerow([
                    stat_label,
                    f"{avg1:.2f}",
                    '', '', '', '', '',  # Placeholders
                    f"{avg2:.2f}",
                    '', '', '', '', '',  # Placeholders
                    f"{diff:.1f}",
                    '', '', '', '', '', ''  # Placeholders
                ])


def generate_executive_summary(
    path1: JMeterS3Path,
    path2: JMeterS3Path,
    stats1: Dict,
    stats2: Dict,
    query_mapping: Dict,
    output_file: Path
):
    """Generate executive summary in markdown format."""

    # Calculate summary metrics
    metrics_summary = {}
    for metric in ['avg', 'median', 'p90', 'p95', 'p99', 'min', 'max']:
        vals1 = []
        vals2 = []
        for query_name in query_mapping.keys():
            q1_name, q2_name = query_mapping[query_name]
            m1 = extract_query_metrics(stats1, q1_name)
            m2 = extract_query_metrics(stats2, q2_name)
            if m1 and m2:
                vals1.append(m1[metric])
                vals2.append(m2[metric])

        if vals1 and vals2:
            metrics_summary[metric] = {
                'engine1': sum(vals1) / len(vals1),
                'engine2': sum(vals2) / len(vals2),
                'diff_pct': calculate_percentage_diff(
                    sum(vals1) / len(vals1),
                    sum(vals2) / len(vals2)
                )
            }

    # Write markdown
    with open(output_file, 'w') as f:
        f.write(f"# JMeter Performance Comparison\n\n")
        f.write(f"**Generated**: {get_timestamp()}\n\n")

        # Configuration comparison
        f.write(f"## Configuration\n\n")
        f.write(f"| Aspect | {path1.engine.upper()} | {path2.engine.upper()} |\n")
        f.write(f"|--------|---------|----------|\n")
        f.write(f"| **Cluster Size** | {path1.cluster_size} | {path2.cluster_size} |\n")
        f.write(f"| **Total Cores** | {path1.get_cores()} | {path2.get_cores()} |\n")
        f.write(f"| **Benchmark** | {path1.benchmark} | {path2.benchmark} |\n")
        f.write(f"| **Concurrency** | {path1.concurrency} | {path2.concurrency} |\n")
        f.write(f"| **Run Type** | {path1.run_type} | {path2.run_type} |\n\n")

        # Performance summary
        f.write(f"## Performance Summary\n\n")
        f.write(f"| Metric | {path1.engine.upper()} | {path2.engine.upper()} | Difference |\n")
        f.write(f"|--------|---------|-----------|------------|\n")

        for metric_label, metric_key in [
            ('Average', 'avg'),
            ('Median (p50)', 'median'),
            ('p90', 'p90'),
            ('p95', 'p95'),
            ('p99', 'p99'),
            ('Min', 'min'),
            ('Max', 'max'),
        ]:
            if metric_key in metrics_summary:
                m = metrics_summary[metric_key]
                winner_icon = "✅" if m['diff_pct'] > 0 else "⚠️"
                winner = path1.engine.upper() if m['diff_pct'] > 0 else path2.engine.upper()
                f.write(
                    f"| **{metric_label}** | {m['engine1']:.2f} sec | {m['engine2']:.2f} sec | "
                    f"{winner_icon} **{winner} {format_percentage(abs(m['diff_pct']))} faster** |\n"
                )

        f.write(f"\n")

        # Key findings
        f.write(f"## Key Findings\n\n")

        avg_diff = metrics_summary.get('avg', {}).get('diff_pct', 0)
        p99_diff = metrics_summary.get('p99', {}).get('diff_pct', 0)

        faster_engine = path1.engine.upper() if avg_diff > 0 else path2.engine.upper()
        slower_engine = path2.engine.upper() if avg_diff > 0 else path1.engine.upper()

        f.write(f"### Overall Winner: {faster_engine}\n\n")
        f.write(f"- **Average latency**: {abs(avg_diff):.1f}% faster than {slower_engine}\n")
        f.write(f"- **p99 tail latency**: {abs(p99_diff):.1f}% better than {slower_engine}\n")
        f.write(f"- **Total queries analyzed**: {len(query_mapping)}\n\n")

        # Recommendations
        f.write(f"## Recommendations\n\n")
        if avg_diff > 10:
            f.write(f"✅ **{faster_engine}** is significantly faster ({abs(avg_diff):.1f}%) and recommended for production use.\n\n")
        elif avg_diff < -10:
            f.write(f"⚠️ **{slower_engine}** is significantly slower ({abs(avg_diff):.1f}%) - consider using {faster_engine}.\n\n")
        else:
            f.write(f"📊 Performance is comparable between both engines (< 10% difference).\n\n")

        # S3 paths
        f.write(f"## Source Data\n\n")
        f.write(f"- **{path1.engine.upper()}**: `{path1.raw_path}`\n")
        f.write(f"- **{path2.engine.upper()}**: `{path2.raw_path}`\n")


def main():
    parser = argparse.ArgumentParser(
        description='Compare two JMeter runs from S3',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument('s3_path_1', help='First S3 path (e.g., e6data run)')
    parser.add_argument('s3_path_2', help='Second S3 path (e.g., dbr run)')
    parser.add_argument('--output-dir', default='reports', help='Output directory for reports')

    args = parser.parse_args()

    # Parse S3 paths
    try:
        path1 = JMeterS3Path(args.s3_path_1)
        path2 = JMeterS3Path(args.s3_path_2)
    except ValueError as e:
        print(f"Error parsing S3 paths: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Comparing:")
    print(f"  Path 1: {path1}")
    print(f"  Path 2: {path2}")

    # Create output directory
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Create temp directory for downloads
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)

        # Download statistics files
        print(f"\nDownloading statistics from S3...")
        stats_file1 = download_jmeter_statistics(args.s3_path_1, tmpdir_path / 'run1')
        stats_file2 = download_jmeter_statistics(args.s3_path_2, tmpdir_path / 'run2')

        if not stats_file1:
            print(f"Error: Could not find statistics.json in {args.s3_path_1}", file=sys.stderr)
            sys.exit(1)

        if not stats_file2:
            print(f"Error: Could not find statistics.json in {args.s3_path_2}", file=sys.stderr)
            sys.exit(1)

        print(f"  ✓ Downloaded: {stats_file1.name}")
        print(f"  ✓ Downloaded: {stats_file2.name}")

        # Load statistics
        print(f"\nLoading statistics...")
        stats1 = load_jmeter_statistics(stats_file1)
        stats2 = load_jmeter_statistics(stats_file2)

        # Create query mapping
        query_mapping = create_query_mapping(stats1, stats2, path1.engine, path2.engine)
        print(f"  ✓ Found {len(query_mapping)} matching queries")

        # Generate reports
        timestamp = get_timestamp()
        engine1_short = path1.engine[:3].upper()
        engine2_short = path2.engine[:3].upper()
        cluster1 = path1.cluster_size.replace('-', '')
        cluster2 = path2.cluster_size.replace('-', '')
        run_type = path1.run_type.replace('_', '')

        base_name = f"{engine1_short}_{cluster1}_vs_{engine2_short}_{cluster2}_{run_type}_{timestamp}"

        # CSV report
        csv_file = output_dir / f"{base_name}.csv"
        print(f"\nGenerating CSV report...")
        generate_comparison_csv(
            f"{path1.engine}_{path1.cluster_size}",
            f"{path2.engine}_{path2.cluster_size}",
            stats1,
            stats2,
            query_mapping,
            csv_file
        )
        print(f"  ✓ Created: {csv_file}")

        # Executive summary
        md_file = output_dir / f"{base_name}_SUMMARY.md"
        print(f"\nGenerating executive summary...")
        generate_executive_summary(
            path1,
            path2,
            stats1,
            stats2,
            query_mapping,
            md_file
        )
        print(f"  ✓ Created: {md_file}")

    print(f"\n✅ Comparison complete!")
    print(f"\nGenerated files:")
    print(f"  - CSV: {csv_file}")
    print(f"  - Summary: {md_file}")


if __name__ == '__main__':
    main()
