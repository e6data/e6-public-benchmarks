#!/usr/bin/env python3
"""
Analyze concurrency scaling behavior for a single engine.

Shows how performance degrades (or improves) as concurrency increases.

Usage:
    python analyze_concurrency_scaling.py S3_BASE_PATH [--output-dir reports]

Example:
    python analyze_concurrency_scaling.py \
        s3://e6-jmeter/jmeter-results/engine=e6data/cluster_size=S-2x2/benchmark=tpcds_29_1tb/
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
    get_timestamp,
)


def find_concurrency_runs(base_s3_path: str) -> List[Tuple[int, str]]:
    """Find all concurrency run directories under a base path."""
    base_path = base_s3_path.rstrip('/') + '/'
    files = list_s3_files(base_path)
    
    concurrency_runs = set()
    for file in files:
        # Try both formats
        match = re.search(r'run_type=(concurrency_\d+)/', file)
        if match:
            run_type = match.group(1)
            concurrency = int(run_type.split('_')[1])
            full_path = base_path + 'run_type=' + run_type + '/'
            concurrency_runs.add((concurrency, full_path))
        else:
            match = re.search(r'/(concurrency_\d+)/', file)
            if match:
                run_type = match.group(1)
                concurrency = int(run_type.split('_')[1])
                full_path = base_path + run_type + '/'
                concurrency_runs.add((concurrency, full_path))
    
    return sorted(list(concurrency_runs))


def calculate_scaling_efficiency(baseline_perf: float, current_perf: float, 
                                 baseline_conc: int, current_conc: int) -> float:
    """
    Calculate scaling efficiency.
    
    Perfect linear scaling: efficiency = 1.0
    Sub-linear scaling: efficiency < 1.0
    Super-linear scaling: efficiency > 1.0
    """
    if baseline_perf == 0 or baseline_conc == 0:
        return 0.0
    
    # Expected performance with linear scaling
    expected_degradation = current_conc / baseline_conc
    
    # Actual degradation
    actual_degradation = current_perf / baseline_perf
    
    # Efficiency = expected / actual (lower is better for latency)
    efficiency = expected_degradation / actual_degradation if actual_degradation > 0 else 0.0
    
    return efficiency


def generate_scaling_csv(
    engine_name: str,
    concurrency_data: Dict[int, Dict],  # concurrency -> statistics
    output_file: Path
):
    """Generate CSV showing performance at each concurrency level."""
    
    concurrency_levels = sorted(concurrency_data.keys())
    
    # Get all unique queries
    all_queries = set()
    for stats in concurrency_data.values():
        all_queries.update(k for k in stats.keys() if k != 'Total')
    all_queries = sorted(all_queries)
    
    with open(output_file, 'w', newline='') as f:
        writer = csv.writer(f)
        
        # Header
        header = ['Query']
        for conc in concurrency_levels:
            header.extend([
                f'C{conc}_Avg(s)',
                f'C{conc}_Median(s)',
                f'C{conc}_p90(s)',
                f'C{conc}_p95(s)',
                f'C{conc}_p99(s)',
                f'C{conc}_Samples',
            ])
        writer.writerow(header)
        
        # Query data
        for query in all_queries:
            row = [query]
            
            for conc in concurrency_levels:
                stats = concurrency_data.get(conc, {})
                metrics = extract_query_metrics(stats, query)
                
                if metrics:
                    row.extend([
                        f"{metrics['avg']:.2f}",
                        f"{metrics['median']:.2f}",
                        f"{metrics['p90']:.2f}",
                        f"{metrics['p95']:.2f}",
                        f"{metrics['p99']:.2f}",
                        f"{metrics['samples']}",
                    ])
                else:
                    row.extend(['', '', '', '', '', ''])
            
            writer.writerow(row)
        
        # Summary statistics
        writer.writerow([])
        writer.writerow(['SUMMARY ACROSS ALL QUERIES'])
        
        for stat_label, metric_key in [('Average', 'avg'), ('Median', 'median'), 
                                        ('p90', 'p90'), ('p95', 'p95'), ('p99', 'p99')]:
            row = [stat_label]
            
            for conc in concurrency_levels:
                stats = concurrency_data.get(conc, {})
                values = []
                for query in all_queries:
                    metrics = extract_query_metrics(stats, query)
                    if metrics:
                        values.append(metrics[metric_key])
                
                if values:
                    avg_value = sum(values) / len(values)
                    row.extend([f"{avg_value:.2f}", '', '', '', '', ''])
                else:
                    row.extend(['', '', '', '', '', ''])
            
            writer.writerow(row)


def generate_scaling_analysis(
    engine_name: str,
    cluster_size: str,
    concurrency_data: Dict[int, Dict],
    output_file: Path
):
    """Generate markdown analysis of concurrency scaling."""
    
    concurrency_levels = sorted(concurrency_data.keys())
    
    # Calculate summary metrics for each concurrency
    summary_metrics = {}
    all_queries = set()
    
    for conc, stats in concurrency_data.items():
        queries = [k for k in stats.keys() if k != 'Total']
        all_queries.update(queries)
        
        avg_values = []
        p99_values = []
        
        for query in queries:
            metrics = extract_query_metrics(stats, query)
            if metrics:
                avg_values.append(metrics['avg'])
                p99_values.append(metrics['p99'])
        
        summary_metrics[conc] = {
            'avg': sum(avg_values) / len(avg_values) if avg_values else 0,
            'p99': sum(p99_values) / len(p99_values) if p99_values else 0,
            'query_count': len(queries)
        }
    
    with open(output_file, 'w') as f:
        f.write(f"# Concurrency Scaling Analysis: {engine_name.upper()}\n\n")
        f.write(f"**Generated**: {get_timestamp()}\n")
        f.write(f"**Engine**: {engine_name}\n")
        f.write(f"**Cluster Size**: {cluster_size}\n")
        f.write(f"**Queries Analyzed**: {len(all_queries)}\n\n")
        
        # Performance by concurrency table
        f.write(f"## Performance by Concurrency Level\n\n")
        f.write(f"| Concurrency | Avg Latency | p99 Latency | Degradation from C={concurrency_levels[0]} | Scaling Efficiency |\n")
        f.write(f"|-------------|-------------|-------------|----------------------|--------------------|\n")
        
        baseline_conc = concurrency_levels[0]
        baseline_avg = summary_metrics[baseline_conc]['avg']
        baseline_p99 = summary_metrics[baseline_conc]['p99']
        
        for conc in concurrency_levels:
            m = summary_metrics[conc]
            
            # Calculate degradation
            if conc == baseline_conc:
                degradation = "Baseline"
                efficiency_str = "100%"
            else:
                avg_degradation = ((m['avg'] - baseline_avg) / baseline_avg) * 100
                efficiency = calculate_scaling_efficiency(baseline_avg, m['avg'], baseline_conc, conc)
                efficiency_str = f"{efficiency * 100:.1f}%"
                
                if avg_degradation > 0:
                    degradation = f"+{avg_degradation:.1f}% slower"
                else:
                    degradation = f"{avg_degradation:.1f}% faster"
            
            f.write(f"| **C={conc}** | {m['avg']:.2f} sec | {m['p99']:.2f} sec | {degradation} | {efficiency_str} |\n")
        
        f.write(f"\n")
        
        # Scaling analysis
        f.write(f"## Scaling Analysis\n\n")
        
        # Calculate overall degradation
        first_conc = concurrency_levels[0]
        last_conc = concurrency_levels[-1]
        
        first_avg = summary_metrics[first_conc]['avg']
        last_avg = summary_metrics[last_conc]['avg']
        
        total_degradation = ((last_avg - first_avg) / first_avg) * 100
        conc_multiplier = last_conc / first_conc
        
        f.write(f"### Overall Scaling (C={first_conc} → C={last_conc})\n\n")
        f.write(f"- **Concurrency increase**: {conc_multiplier:.1f}x ({first_conc} → {last_conc})\n")
        f.write(f"- **Latency increase**: {total_degradation:.1f}% ({first_avg:.2f}s → {last_avg:.2f}s)\n")
        
        # Determine scaling quality
        if total_degradation < conc_multiplier * 20:
            scaling_quality = "✅ **Excellent** - Near-linear scaling"
        elif total_degradation < conc_multiplier * 50:
            scaling_quality = "✅ **Good** - Acceptable degradation"
        elif total_degradation < conc_multiplier * 100:
            scaling_quality = "⚠️ **Fair** - Noticeable degradation"
        else:
            scaling_quality = "🚨 **Poor** - Severe degradation"
        
        f.write(f"- **Scaling quality**: {scaling_quality}\n\n")
        
        # Performance trend
        f.write(f"### Performance Trend\n\n")
        f.write(f"```\n")
        f.write(f"Concurrency  | Avg Latency | Change from Previous\n")
        f.write(f"-------------|-------------|--------------------\n")
        
        prev_avg = None
        for conc in concurrency_levels:
            m = summary_metrics[conc]
            
            if prev_avg is None:
                change_str = "Baseline"
            else:
                change = ((m['avg'] - prev_avg) / prev_avg) * 100
                change_str = f"+{change:.1f}%" if change > 0 else f"{change:.1f}%"
            
            f.write(f"C={conc:2d}         | {m['avg']:6.2f} sec  | {change_str}\n")
            prev_avg = m['avg']
        
        f.write(f"```\n\n")
        
        # Recommendations
        f.write(f"## Recommendations\n\n")
        
        if total_degradation < 50:
            f.write(f"✅ **Production Ready**: {engine_name.upper()} shows good scaling behavior up to C={last_conc}.\n\n")
        elif total_degradation < 150:
            f.write(f"⚠️ **Use with Caution**: Consider limiting production concurrency to C={concurrency_levels[len(concurrency_levels)//2]} or below.\n\n")
        else:
            f.write(f"🚨 **Not Recommended**: Severe performance degradation at high concurrency. Limit to C={concurrency_levels[1]} or lower.\n\n")
        
        # Best concurrency level
        # Find the "sweet spot" - best balance of throughput vs latency
        best_conc = concurrency_levels[0]
        best_score = 0
        
        for conc in concurrency_levels:
            # Score = concurrency / avg_latency (higher is better)
            score = conc / summary_metrics[conc]['avg']
            if score > best_score:
                best_score = score
                best_conc = conc
        
        f.write(f"**Optimal Concurrency**: C={best_conc} (best throughput/latency ratio)\n")


def main():
    parser = argparse.ArgumentParser(
        description='Analyze concurrency scaling for a single engine',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument('s3_base_path', help='S3 base path for the engine')
    parser.add_argument('--output-dir', default='reports', help='Output directory for reports')
    
    args = parser.parse_args()
    
    # Parse base path to get engine info
    # Try to extract engine and cluster info from path
    match = re.search(r'engine=([^/]+)/cluster_size=([^/]+)', args.s3_base_path)
    if match:
        engine_name = match.group(1)
        cluster_size = match.group(2)
    else:
        print("Warning: Could not parse engine and cluster from path", file=sys.stderr)
        engine_name = "unknown"
        cluster_size = "unknown"
    
    print(f"Analyzing concurrency scaling for {engine_name.upper()} ({cluster_size})...\n")
    
    # Find all concurrency runs
    print("Scanning for concurrency runs...")
    concurrency_runs = find_concurrency_runs(args.s3_base_path)
    
    if not concurrency_runs:
        print("Error: No concurrency runs found!", file=sys.stderr)
        sys.exit(1)
    
    print(f"Found {len(concurrency_runs)} concurrency levels:")
    for conc, path in concurrency_runs:
        print(f"  - Concurrency {conc}: {path}")
    
    # Download and load statistics for each concurrency
    concurrency_data = {}
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        
        for conc, path in concurrency_runs:
            print(f"\nLoading concurrency={conc}...")
            
            stats_file = download_jmeter_statistics(path, tmpdir_path / f'c{conc}')
            
            if not stats_file:
                print(f"  ⚠️  Skipping C={conc} (no statistics file found)")
                continue
            
            stats = load_jmeter_statistics(stats_file)
            concurrency_data[conc] = stats
            
            query_count = len([k for k in stats.keys() if k != 'Total'])
            print(f"  ✓ Loaded {query_count} queries")
    
    if not concurrency_data:
        print("\nError: No valid data could be loaded.", file=sys.stderr)
        sys.exit(1)
    
    # Generate reports
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = get_timestamp()
    base_name = f"{engine_name}_{cluster_size}_ConcurrencyScaling_{timestamp}"
    
    # CSV report
    csv_file = output_dir / f"{base_name}.csv"
    print(f"\nGenerating scaling CSV...")
    generate_scaling_csv(engine_name, concurrency_data, csv_file)
    print(f"  ✓ Created: {csv_file}")
    
    # Analysis report
    md_file = output_dir / f"{base_name}_ANALYSIS.md"
    print(f"\nGenerating scaling analysis...")
    generate_scaling_analysis(engine_name, cluster_size, concurrency_data, md_file)
    print(f"  ✓ Created: {md_file}")
    
    print(f"\n✅ Concurrency scaling analysis complete!")
    print(f"\nGenerated files:")
    print(f"  - CSV: {csv_file}")
    print(f"  - Analysis: {md_file}")


if __name__ == '__main__':
    main()
