#!/usr/bin/env python3
"""
Generate query-level latency comparison CSV for different cluster sizes per engine.

Usage:
    python utilities/generate_query_comparison_different_clusters.py \
        --e6-cluster M \
        --dbr-cluster S-2x2 \
        --benchmark tpcds_29_1tb \
        --output comparison.csv
"""

import json
import subprocess
import sys
import argparse
import csv
from pathlib import Path
from typing import Dict, List, Tuple
import statistics
import re


def run_command(cmd: List[str]) -> Tuple[str, int]:
    """Run shell command and return output."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return result.stdout, 0
    except subprocess.CalledProcessError as e:
        return e.stderr, e.returncode


def list_test_results(engine: str, cluster_size: str, benchmark: str) -> Dict[int, str]:
    """List all test result JSON files grouped by concurrency level."""
    s3_base = f"s3://e6-jmeter/jmeter-results/engine={engine}/cluster_size={cluster_size}/benchmark={benchmark}/"

    cmd = ["aws", "s3", "ls", s3_base]
    output, code = run_command(cmd)

    if code != 0:
        print(f"Error listing S3 path: {s3_base}", file=sys.stderr)
        return {}

    concurrency_files = {}
    for line in output.strip().split('\n'):
        if 'run_type=' in line:
            match = re.search(r'run_type=concurrency_(\d+)', line)
            if match:
                concurrency = int(match.group(1))
                run_path = f"{s3_base}run_type=concurrency_{concurrency}/"
                cmd = ["aws", "s3", "ls", run_path, "--recursive"]
                files_output, _ = run_command(cmd)

                test_results = [line for line in files_output.strip().split('\n')
                               if 'test_result_' in line and line.endswith('.json')]
                if test_results:
                    latest = test_results[-1].strip().split()[-1]
                    concurrency_files[concurrency] = f"s3://e6-jmeter/{latest}"

    return concurrency_files


def load_test_result(s3_path: str) -> Dict:
    """Download and load test result JSON from S3."""
    local_file = "/tmp/temp_test_result.json"
    cmd = ["aws", "s3", "cp", s3_path, local_file]
    output, code = run_command(cmd)

    if code != 0:
        print(f"Error downloading: {s3_path}", file=sys.stderr)
        return {}

    try:
        with open(local_file, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading JSON: {e}", file=sys.stderr)
        return {}


def parse_aggregate_data(test_data: Dict) -> Dict[str, Dict]:
    """Parse test_result JSON to extract query-level metrics from statistics.json."""
    run_id = test_data.get('run_id', '')
    output_locations = test_data.get('output_file_locations', {})
    s3_upload_path = output_locations.get('s3_upload_path', '')

    if not run_id or not s3_upload_path:
        print(f"Warning: Missing run_id or s3_upload_path", file=sys.stderr)
        return {}

    stats_s3 = f"{s3_upload_path}/statistics.json_{run_id}"

    local_json = "/tmp/temp_statistics.json"
    cmd = ["aws", "s3", "cp", stats_s3, local_json]
    output, code = run_command(cmd)

    if code != 0:
        print(f"Error downloading statistics: {stats_s3}", file=sys.stderr)
        return {}

    query_data = {}
    try:
        with open(local_json, 'r') as f:
            stats = json.load(f)

        for query_name, metrics in stats.items():
            if 'BOOTSTRAP' in query_name.upper() or query_name == 'Total':
                continue

            query_data[query_name] = {
                'avg_sec': metrics.get('meanResTime', 0) / 1000.0,
                'min_sec': metrics.get('minResTime', 0) / 1000.0,
                'max_sec': metrics.get('maxResTime', 0) / 1000.0,
                'median_sec': metrics.get('medianResTime', 0) / 1000.0,
                'p90_sec': metrics.get('pct1ResTime', 0) / 1000.0,
                'p95_sec': metrics.get('pct2ResTime', 0) / 1000.0,
                'p99_sec': metrics.get('pct3ResTime', 0) / 1000.0,
            }
    except Exception as e:
        print(f"Error parsing statistics JSON: {e}", file=sys.stderr)
        return {}

    return query_data


def normalize_query_name(name: str) -> str:
    """Normalize query names for comparison."""
    if name.startswith('query-'):
        parts = name.split('-')
        if len(parts) >= 3:
            return '-'.join(parts[2:])
    return name


def calculate_statistics(values: List[float]) -> Dict[str, float]:
    """Calculate summary statistics."""
    if not values:
        return {
            'avg': 0.0,
            'min': 0.0,
            'max': 0.0,
            'median': 0.0,
            'p90': 0.0,
            'p95': 0.0,
            'p99': 0.0,
        }

    sorted_values = sorted(values)
    n = len(sorted_values)

    return {
        'avg': statistics.mean(values),
        'min': min(values),
        'max': max(values),
        'median': statistics.median(values),
        'p90': sorted_values[int(n * 0.90)] if n > 0 else 0.0,
        'p95': sorted_values[int(n * 0.95)] if n > 0 else 0.0,
        'p99': sorted_values[int(n * 0.99)] if n > 0 else 0.0,
    }


def generate_comparison_csv(e6_cluster: str, dbr_cluster: str, benchmark: str,
                            concurrency_levels: List[int], output_file: str):
    """Generate comparison CSV file."""

    print(f"Generating query latency comparison...", file=sys.stderr)
    print(f"  E6Data: {e6_cluster}", file=sys.stderr)
    print(f"  DBR: {dbr_cluster}", file=sys.stderr)

    # Collect data
    all_data = {}
    engine_configs = {
        'e6data': e6_cluster,
        'dbr': dbr_cluster
    }

    for engine, cluster_size in engine_configs.items():
        print(f"\nProcessing {engine} ({cluster_size})...", file=sys.stderr)
        all_data[engine] = {}

        test_results = list_test_results(engine, cluster_size, benchmark)

        for concurrency in concurrency_levels:
            if concurrency not in test_results:
                print(f"  Warning: Concurrency {concurrency} not found", file=sys.stderr)
                continue

            print(f"  Loading concurrency {concurrency}...", file=sys.stderr)
            test_data = load_test_result(test_results[concurrency])

            if test_data:
                query_data = parse_aggregate_data(test_data)
                normalized = {normalize_query_name(k): v for k, v in query_data.items()}
                all_data[engine][concurrency] = normalized

    # Get all unique query names
    all_queries = set()
    for engine_data in all_data.values():
        for concurrency_data in engine_data.values():
            all_queries.update(concurrency_data.keys())

    all_queries = sorted(all_queries)

    # Build CSV header
    header = ['Query']
    for concurrency in concurrency_levels:
        header.append(f'e6data_C{concurrency}_avg(s)')
        header.append(f'dbr_C{concurrency}_avg(s)')
        header.append(f'diff_C{concurrency}(%)')

    # Write CSV
    with open(output_file, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(header)

        # Write query data
        for query in all_queries:
            row = [query]
            for concurrency in concurrency_levels:
                e6_val = ''
                dbr_val = ''
                diff = ''

                if concurrency in all_data['e6data'] and query in all_data['e6data'][concurrency]:
                    e6_val = f"{all_data['e6data'][concurrency][query]['avg_sec']:.2f}"

                if concurrency in all_data['dbr'] and query in all_data['dbr'][concurrency]:
                    dbr_val = f"{all_data['dbr'][concurrency][query]['avg_sec']:.2f}"

                # Calculate difference
                if e6_val and dbr_val:
                    e6_num = float(e6_val)
                    dbr_num = float(dbr_val)
                    if dbr_num > 0:
                        pct_diff = ((dbr_num - e6_num) / dbr_num) * 100
                        diff = f"{pct_diff:.1f}"

                row.extend([e6_val, dbr_val, diff])
            writer.writerow(row)

        # Add empty row
        writer.writerow([])

        # Add summary statistics
        stat_labels = ['SUMMARY', 'Average', 'Median (p50)', 'p90', 'p95', 'p99', 'Min', 'Max']

        for stat_label in stat_labels:
            if stat_label == 'SUMMARY':
                writer.writerow([stat_label])
                continue

            row = [stat_label]
            for concurrency in concurrency_levels:
                # E6Data stats
                e6_val = ''
                if concurrency in all_data['e6data']:
                    values = [q['avg_sec'] for q in all_data['e6data'][concurrency].values()]
                    if values:
                        stats = calculate_statistics(values)
                        if stat_label == 'Average':
                            e6_val = f'{stats["avg"]:.2f}'
                        elif stat_label == 'Median (p50)':
                            e6_val = f'{stats["median"]:.2f}'
                        elif stat_label == 'p90':
                            e6_val = f'{stats["p90"]:.2f}'
                        elif stat_label == 'p95':
                            e6_val = f'{stats["p95"]:.2f}'
                        elif stat_label == 'p99':
                            e6_val = f'{stats["p99"]:.2f}'
                        elif stat_label == 'Min':
                            e6_val = f'{stats["min"]:.2f}'
                        elif stat_label == 'Max':
                            e6_val = f'{stats["max"]:.2f}'

                # DBR stats
                dbr_val = ''
                if concurrency in all_data['dbr']:
                    values = [q['avg_sec'] for q in all_data['dbr'][concurrency].values()]
                    if values:
                        stats = calculate_statistics(values)
                        if stat_label == 'Average':
                            dbr_val = f'{stats["avg"]:.2f}'
                        elif stat_label == 'Median (p50)':
                            dbr_val = f'{stats["median"]:.2f}'
                        elif stat_label == 'p90':
                            dbr_val = f'{stats["p90"]:.2f}'
                        elif stat_label == 'p95':
                            dbr_val = f'{stats["p95"]:.2f}'
                        elif stat_label == 'p99':
                            dbr_val = f'{stats["p99"]:.2f}'
                        elif stat_label == 'Min':
                            dbr_val = f'{stats["min"]:.2f}'
                        elif stat_label == 'Max':
                            dbr_val = f'{stats["max"]:.2f}'

                # Calculate difference for summary
                diff = ''
                if e6_val and dbr_val:
                    e6_num = float(e6_val)
                    dbr_num = float(dbr_val)
                    if dbr_num > 0:
                        pct_diff = ((dbr_num - e6_num) / dbr_num) * 100
                        diff = f"{pct_diff:.1f}"

                row.extend([e6_val, dbr_val, diff])
            writer.writerow(row)

    print(f"\n✅ CSV file generated: {output_file}", file=sys.stderr)
    print(f"   Queries: {len(all_queries)}", file=sys.stderr)
    print(f"   E6Data cluster: {e6_cluster}", file=sys.stderr)
    print(f"   DBR cluster: {dbr_cluster}", file=sys.stderr)
    print(f"   Concurrency levels: {', '.join(map(str, concurrency_levels))}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(
        description='Generate query-level latency comparison CSV for different cluster sizes'
    )

    parser.add_argument('--e6-cluster', required=True,
                       help='E6Data cluster size (e.g., M, L)')
    parser.add_argument('--dbr-cluster', required=True,
                       help='DBR cluster size (e.g., M, S-2x2)')
    parser.add_argument('--benchmark', required=True,
                       help='Benchmark name (e.g., tpcds_29_1tb)')
    parser.add_argument('--concurrency', nargs='+', type=int, default=[2, 4, 8, 12, 16],
                       help='Concurrency levels (default: 2 4 8 12 16)')
    parser.add_argument('--output', required=True,
                       help='Output CSV file path')

    args = parser.parse_args()

    generate_comparison_csv(
        e6_cluster=args.e6_cluster,
        dbr_cluster=args.dbr_cluster,
        benchmark=args.benchmark,
        concurrency_levels=args.concurrency,
        output_file=args.output
    )


if __name__ == '__main__':
    main()
