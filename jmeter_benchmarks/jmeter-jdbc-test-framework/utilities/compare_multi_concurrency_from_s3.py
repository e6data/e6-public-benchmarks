#!/usr/bin/env python3
"""
Compare multiple concurrency runs between two engines from S3.

This script automatically finds all concurrency runs for two engines and generates
a comprehensive comparison report across all concurrency levels.

Usage:
    python compare_multi_concurrency.py ENGINE1_BASE_PATH ENGINE2_BASE_PATH [--output-dir reports]

Example:
    python compare_multi_concurrency.py \
        s3://e6-jmeter/jmeter-results/engine=e6data/cluster_size=M/benchmark=tpcds_29_1tb/ \
        s3://e6-jmeter/jmeter-results/engine=dbr/cluster_size=S-4x4/benchmark=tpcds_29_1tb/
"""

import sys
import csv
import argparse
import re
from pathlib import Path
from typing import Dict, List, Tuple
import tempfile

from jmeter_s3_utils import (
    JMeterS3Path,
    list_s3_files,
    download_jmeter_statistics,
    load_jmeter_statistics,
    extract_query_metrics,
    create_query_mapping,
    calculate_percentage_diff,
    format_percentage,
    get_timestamp,
)


def find_concurrency_runs(base_s3_path: str) -> List[Tuple[int, str]]:
    """Find all concurrency run directories under a base path."""
    # List directories
    base_path = base_s3_path.rstrip('/') + '/'

    # List all files to find run_type directories
    files = list_s3_files(base_path)

    # Extract unique run_type directories
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

    # Sort by concurrency level
    return sorted(list(concurrency_runs))


def generate_multi_concurrency_csv(
    engine1_name: str,
    engine2_name: str,
    concurrency_data: Dict[int, Tuple[Dict, Dict, Dict]],  # concurrency -> (stats1, stats2, mapping)
    output_file: Path
):
    """Generate comprehensive CSV with all concurrency levels."""
    
    # Get all unique queries across all concurrencies
    all_queries = set()
    for _, (_, _, mapping) in concurrency_data.items():
        all_queries.update(mapping.keys())
    all_queries = sorted(all_queries)
    
    concurrency_levels = sorted(concurrency_data.keys())
    
    with open(output_file, 'w', newline='') as f:
        writer = csv.writer(f)
        
        # Header
        header = ['Query']
        for conc in concurrency_levels:
            header.extend([
                f'{engine1_name}_C{conc}_Avg(s)',
                f'{engine1_name}_C{conc}_Median(s)',
                f'{engine1_name}_C{conc}_p90(s)',
                f'{engine1_name}_C{conc}_p95(s)',
                f'{engine1_name}_C{conc}_p99(s)',
                f'{engine1_name}_C{conc}_Min(s)',
                f'{engine1_name}_C{conc}_Max(s)',
                f'{engine2_name}_C{conc}_Avg(s)',
                f'{engine2_name}_C{conc}_Median(s)',
                f'{engine2_name}_C{conc}_p90(s)',
                f'{engine2_name}_C{conc}_p95(s)',
                f'{engine2_name}_C{conc}_p99(s)',
                f'{engine2_name}_C{conc}_Min(s)',
                f'{engine2_name}_C{conc}_Max(s)',
                f'Diff_C{conc}_Avg(%)',
                f'Diff_C{conc}_Median(%)',
                f'Diff_C{conc}_p90(%)',
                f'Diff_C{conc}_p95(%)',
                f'Diff_C{conc}_p99(%)',
                f'Diff_C{conc}_Min(%)',
                f'Diff_C{conc}_Max(%)',
            ])
        writer.writerow(header)
        
        # Query data
        for query in all_queries:
            row = [query]
            
            for conc in concurrency_levels:
                if conc not in concurrency_data:
                    row.extend([''] * 21)
                    continue
                
                stats1, stats2, mapping = concurrency_data[conc]
                
                if query not in mapping:
                    row.extend([''] * 21)
                    continue
                
                q1_name, q2_name = mapping[query]
                m1 = extract_query_metrics(stats1, q1_name)
                m2 = extract_query_metrics(stats2, q2_name)
                
                if not m1 or not m2:
                    row.extend([''] * 21)
                    continue
                
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
                
                # Differences
                for metric in ['avg', 'median', 'p90', 'p95', 'p99', 'min', 'max']:
                    diff = calculate_percentage_diff(m1[metric], m2[metric])
                    row.append(f"{diff:.1f}")
            
            writer.writerow(row)
        
        # Summary statistics
        writer.writerow([])
        writer.writerow(['SUMMARY STATISTICS'])
        
        # Map stat labels to metric keys
        stat_metrics = {
            'Average': 'avg',
            'Median': 'median',
            'p90': 'p90',
            'p95': 'p95',
            'p99': 'p99'
        }

        for stat_label, metric_key in stat_metrics.items():
            row = [stat_label]
            
            for conc in concurrency_levels:
                if conc not in concurrency_data:
                    row.extend([''] * 21)
                    continue
                
                stats1, stats2, mapping = concurrency_data[conc]
                
                # Collect values
                vals1 = []
                vals2 = []
                for query in mapping.keys():
                    q1_name, q2_name = mapping[query]
                    m1 = extract_query_metrics(stats1, q1_name)
                    m2 = extract_query_metrics(stats2, q2_name)
                    if m1 and m2:
                        vals1.append(m1[metric_key])
                        vals2.append(m2[metric_key])
                
                if vals1 and vals2:
                    avg1 = sum(vals1) / len(vals1)
                    avg2 = sum(vals2) / len(vals2)
                    diff = calculate_percentage_diff(avg1, avg2)
                    
                    row.extend([
                        f"{avg1:.2f}",
                        '', '', '', '', '', '',  # Placeholders
                        f"{avg2:.2f}",
                        '', '', '', '', '', '',  # Placeholders
                        f"{diff:.1f}",
                        '', '', '', '', '', ''   # Placeholders
                    ])
                else:
                    row.extend([''] * 21)
            
            writer.writerow(row)


def generate_multi_concurrency_summary(
    engine1_name: str,
    engine2_name: str,
    engine1_cluster: str,
    engine2_cluster: str,
    concurrency_data: Dict[int, Tuple[Dict, Dict, Dict]],
    output_file: Path
):
    """Generate executive summary for multi-concurrency comparison."""
    
    concurrency_levels = sorted(concurrency_data.keys())
    
    with open(output_file, 'w') as f:
        f.write(f"# Multi-Concurrency Performance Comparison\n\n")
        f.write(f"**Generated**: {get_timestamp()}\n\n")
        
        # Configuration
        f.write(f"## Configuration\n\n")
        f.write(f"| Aspect | {engine1_name.upper()} | {engine2_name.upper()} |\n")
        f.write(f"|--------|----------|----------|\n")
        f.write(f"| **Cluster Size** | {engine1_cluster} | {engine2_cluster} |\n")
        f.write(f"| **Concurrency Levels** | {', '.join(map(str, concurrency_levels))} | {', '.join(map(str, concurrency_levels))} |\n\n")
        
        # Performance by concurrency
        f.write(f"## Performance by Concurrency Level\n\n")
        
        for conc in concurrency_levels:
            stats1, stats2, mapping = concurrency_data[conc]
            
            # Calculate summary metrics
            vals1_avg = []
            vals2_avg = []
            vals1_p99 = []
            vals2_p99 = []
            
            for query in mapping.keys():
                q1_name, q2_name = mapping[query]
                m1 = extract_query_metrics(stats1, q1_name)
                m2 = extract_query_metrics(stats2, q2_name)
                if m1 and m2:
                    vals1_avg.append(m1['avg'])
                    vals2_avg.append(m2['avg'])
                    vals1_p99.append(m1['p99'])
                    vals2_p99.append(m2['p99'])
            
            avg1 = sum(vals1_avg) / len(vals1_avg)
            avg2 = sum(vals2_avg) / len(vals2_avg)
            p99_1 = sum(vals1_p99) / len(vals1_p99)
            p99_2 = sum(vals2_p99) / len(vals2_p99)
            
            avg_diff = calculate_percentage_diff(avg1, avg2)
            p99_diff = calculate_percentage_diff(p99_1, p99_2)
            
            f.write(f"### Concurrency = {conc}\n\n")
            f.write(f"| Metric | {engine1_name.upper()} | {engine2_name.upper()} | Difference |\n")
            f.write(f"|--------|----------|-----------|------------|\n")
            
            winner_icon = "✅" if avg_diff > 0 else "⚠️"
            winner = engine1_name.upper() if avg_diff > 0 else engine2_name.upper()
            f.write(f"| **Average** | {avg1:.2f} sec | {avg2:.2f} sec | {winner_icon} **{winner} {format_percentage(abs(avg_diff))} faster** |\n")
            
            p99_winner_icon = "✅" if p99_diff > 0 else "⚠️"
            p99_winner = engine1_name.upper() if p99_diff > 0 else engine2_name.upper()
            f.write(f"| **p99** | {p99_1:.2f} sec | {p99_2:.2f} sec | {p99_winner_icon} **{p99_winner} {format_percentage(abs(p99_diff))} faster** |\n\n")
        
        # Overall recommendations
        f.write(f"## Overall Recommendations\n\n")
        
        # Determine which engine is better overall
        total_wins_engine1 = 0
        total_wins_engine2 = 0
        
        for conc in concurrency_levels:
            stats1, stats2, mapping = concurrency_data[conc]
            vals1 = []
            vals2 = []
            for query in mapping.keys():
                q1_name, q2_name = mapping[query]
                m1 = extract_query_metrics(stats1, q1_name)
                m2 = extract_query_metrics(stats2, q2_name)
                if m1 and m2:
                    vals1.append(m1['avg'])
                    vals2.append(m2['avg'])
            
            avg1 = sum(vals1) / len(vals1)
            avg2 = sum(vals2) / len(vals2)
            
            if avg1 < avg2:
                total_wins_engine1 += 1
            else:
                total_wins_engine2 += 1
        
        if total_wins_engine1 > total_wins_engine2:
            f.write(f"✅ **{engine1_name.upper()}** wins at {total_wins_engine1} out of {len(concurrency_levels)} concurrency levels.\n\n")
            f.write(f"**Recommendation**: Use {engine1_name.upper()} for production workloads.\n\n")
        elif total_wins_engine2 > total_wins_engine1:
            f.write(f"✅ **{engine2_name.upper()}** wins at {total_wins_engine2} out of {len(concurrency_levels)} concurrency levels.\n\n")
            f.write(f"**Recommendation**: Use {engine2_name.upper()} for production workloads.\n\n")
        else:
            f.write(f"📊 Both engines are competitive across different concurrency levels.\n\n")


def main():
    parser = argparse.ArgumentParser(
        description='Compare multiple concurrency runs between two engines',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument('engine1_base', help='First engine base S3 path (e.g., e6data)')
    parser.add_argument('engine2_base', help='Second engine base S3 path (e.g., dbr)')
    parser.add_argument('--output-dir', default='reports', help='Output directory for reports')
    
    args = parser.parse_args()
    
    # Find all concurrency runs for each engine
    print("Scanning for concurrency runs...")
    engine1_runs = find_concurrency_runs(args.engine1_base)
    engine2_runs = find_concurrency_runs(args.engine2_base)
    
    print(f"\nEngine 1 runs found: {len(engine1_runs)}")
    for conc, path in engine1_runs:
        print(f"  - Concurrency {conc}: {path}")
    
    print(f"\nEngine 2 runs found: {len(engine2_runs)}")
    for conc, path in engine2_runs:
        print(f"  - Concurrency {conc}: {path}")
    
    # Find matching concurrency levels
    engine1_map = {conc: path for conc, path in engine1_runs}
    engine2_map = {conc: path for conc, path in engine2_runs}
    
    common_concurrencies = set(engine1_map.keys()).intersection(set(engine2_map.keys()))
    
    if not common_concurrencies:
        print("\nError: No matching concurrency levels found between the two engines.", file=sys.stderr)
        sys.exit(1)
    
    print(f"\nMatching concurrency levels: {sorted(common_concurrencies)}")
    
    # Download and process data for each concurrency
    concurrency_data = {}
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        
        for conc in sorted(common_concurrencies):
            print(f"\nProcessing concurrency={conc}...")
            
            path1 = engine1_map[conc]
            path2 = engine2_map[conc]
            
            # Parse paths for metadata
            parsed1 = JMeterS3Path(path1)
            parsed2 = JMeterS3Path(path2)
            
            # Download statistics
            stats_file1 = download_jmeter_statistics(path1, tmpdir_path / f'c{conc}_e1')
            stats_file2 = download_jmeter_statistics(path2, tmpdir_path / f'c{conc}_e2')
            
            if not stats_file1 or not stats_file2:
                print(f"  ⚠️  Skipping C={conc} (missing statistics files)")
                continue
            
            # Load statistics
            stats1 = load_jmeter_statistics(stats_file1)
            stats2 = load_jmeter_statistics(stats_file2)
            
            # Create mapping
            mapping = create_query_mapping(stats1, stats2, parsed1.engine, parsed2.engine)
            
            concurrency_data[conc] = (stats1, stats2, mapping)
            print(f"  ✓ Loaded {len(mapping)} queries")
    
    if not concurrency_data:
        print("\nError: No valid data could be loaded.", file=sys.stderr)
        sys.exit(1)
    
    # Generate reports
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Get metadata from first run
    first_conc = sorted(concurrency_data.keys())[0]
    path1 = engine1_map[first_conc]
    path2 = engine2_map[first_conc]
    parsed1 = JMeterS3Path(path1)
    parsed2 = JMeterS3Path(path2)
    
    timestamp = get_timestamp()
    base_name = f"{parsed1.engine}_{parsed1.cluster_size}_vs_{parsed2.engine}_{parsed2.cluster_size}_MultiConcurrency_{timestamp}"
    
    # CSV report
    csv_file = output_dir / f"{base_name}.csv"
    print(f"\nGenerating multi-concurrency CSV...")
    generate_multi_concurrency_csv(
        parsed1.engine,
        parsed2.engine,
        concurrency_data,
        csv_file
    )
    print(f"  ✓ Created: {csv_file}")
    
    # Summary report
    md_file = output_dir / f"{base_name}_SUMMARY.md"
    print(f"\nGenerating executive summary...")
    generate_multi_concurrency_summary(
        parsed1.engine,
        parsed2.engine,
        parsed1.cluster_size,
        parsed2.cluster_size,
        concurrency_data,
        md_file
    )
    print(f"  ✓ Created: {md_file}")
    
    print(f"\n✅ Multi-concurrency comparison complete!")
    print(f"\nGenerated files:")
    print(f"  - CSV: {csv_file}")
    print(f"  - Summary: {md_file}")


if __name__ == '__main__':
    main()
