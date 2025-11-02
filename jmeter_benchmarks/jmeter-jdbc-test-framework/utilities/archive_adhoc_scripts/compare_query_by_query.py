#!/usr/bin/env python3
"""
Query-by-Query Comparison Tool for JMeter Aggregate Reports
Compares e6data vs Databricks performance across all concurrency levels
"""

import csv
import sys
import os
from pathlib import Path
from collections import defaultdict
import argparse

# Query name mapping: e6data -> DBR
QUERY_MAPPING = {
    'query-2-TPCDS-2': 'TPCDS-2',
    'query-4-TPCDS-4-optimised': 'TPCDS-4',
    'query-7-TPCDS-7-optimised': 'TPCDS-7',
    'query-9-TPCDS-9': 'TPCDS-9',
    'query-13-TPCDS-13-optimised': 'TPCDS-13',
    'query-14-TPCDS-14-optimised': 'TPCDS-14',
    'query-15-TPCDS-15': 'TPCDS-15',
    'query-18-TPCDS-18-optimised': 'TPCDS-18',
    'query-22-TPCDS-22': 'TPCDS-22',
    'query-27-TPCDS-27-optimised': 'TPCDS-27',
    'query-28-TPCDS-28-optimised': 'TPCDS-28',
    'query-30-TPCDS-30': 'TPCDS-30',
    'query-35-TPCDS-35-optimised': 'TPCDS-35',
    'query-41-TPCDS-41-optimised': 'TPCDS-41',
    'query-44-TPCDS-44-optimised': 'TPCDS-44',
    'query-50-TPCDS-50-optimised': 'TPCDS-50',
    'query-52-TPCDS-52-optimised': 'TPCDS-52',
    'query-54-TPCDS-54-optimised': 'TPCDS-54',
    'query-57-TPCDS-57-optimised': 'TPCDS-57',
    'query-58-TPCDS-58-optimised': 'TPCDS-58',
    'query-63-TPCDS-63': 'TPCDS-63',
    'query-65-TPCDS-65-optimised': 'TPCDS-65',
    'query-66-TPCDS-66': 'TPCDS-66',
    'query-69-TPCDS-69-optimised': 'TPCDS-69',
    'query-75-TPCDS-75': 'TPCDS-75',
    'query-80-TPCDS-80': 'TPCDS-80',
    'query-82-TPCDS-82-optimised': 'TPCDS-82',
    'query-88-TPCDS-88-optimised': 'TPCDS-88',
    'query-98-TPCDS-98-optimised': 'TPCDS-98',
}

def parse_aggregate_report(file_path):
    """Parse JMeter aggregate report CSV file."""
    queries = {}

    with open(file_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            label = row['Label']

            # Skip non-query entries
            if label.startswith('Total') or 'Bootstrap' in label or 'JSR' in label:
                continue

            queries[label] = {
                'samples': int(row['# Samples']),
                'average_ms': float(row['Average']),
                'median_ms': float(row['Median']),
                'p90_ms': float(row['90% Line']),
                'p95_ms': float(row['95% Line']),
                'p99_ms': float(row['99% Line']),
                'min_ms': float(row['Min']),
                'max_ms': float(row['Max']),
                'error_pct': float(row['Error %'].rstrip('%')) if row['Error %'] else 0.0,
                'throughput': float(row['Throughput']),
            }

    return queries

def load_all_reports(report_dir):
    """Load all aggregate reports from directory."""
    reports = {
        'e6data': {},
        'databricks': {}
    }

    for file_path in Path(report_dir).glob('*.csv'):
        filename = file_path.name

        # Parse concurrency level
        if 'Con-2-' in filename or 'con-2-' in filename:
            concurrency = 2
        elif 'Con-4-' in filename or 'con-4-' in filename:
            concurrency = 4
        elif 'Con-8-' in filename or 'Con-8-' in filename:
            concurrency = 8
        elif 'Con-12-' in filename:
            concurrency = 12
        elif 'Con-16-' in filename:
            concurrency = 16
        else:
            continue

        # Determine engine
        if filename.startswith('e6'):
            engine = 'e6data'
        elif filename.startswith('DBR'):
            engine = 'databricks'
        else:
            continue

        reports[engine][concurrency] = parse_aggregate_report(file_path)

    return reports

def normalize_query_name(query_name):
    """Normalize query name to standard TPCDS-X format."""
    if query_name in QUERY_MAPPING:
        return QUERY_MAPPING[query_name]
    return query_name

def generate_summary_comparison(reports):
    """Generate overall summary comparison."""
    output = []
    output.append("=" * 140)
    output.append("QUERY-BY-QUERY COMPARISON: E6DATA M-4x4 (120 cores) vs DATABRICKS S-2x2 (~120 cores)")
    output.append("=" * 140)
    output.append("")

    concurrency_levels = sorted(reports['e6data'].keys())

    for concurrency in concurrency_levels:
        e6_queries = reports['e6data'].get(concurrency, {})
        dbr_queries = reports['databricks'].get(concurrency, {})

        if not e6_queries or not dbr_queries:
            continue

        output.append(f"\n{'=' * 140}")
        output.append(f"CONCURRENCY LEVEL: {concurrency} threads")
        output.append(f"{'=' * 140}\n")

        # Create normalized query mapping
        e6_normalized = {}
        for e6_name, e6_data in e6_queries.items():
            normalized = normalize_query_name(e6_name)
            e6_normalized[normalized] = (e6_name, e6_data)

        # Find common queries
        common_queries = set(e6_normalized.keys()) & set(dbr_queries.keys())

        if not common_queries:
            output.append("⚠️  No common queries found!")
            continue

        # Header
        output.append(f"{'Query':<20} {'E6 Avg(ms)':>12} {'DBR Avg(ms)':>12} {'Improvement':>12} "
                     f"{'E6 p95(ms)':>12} {'DBR p95(ms)':>12} {'Winner':>15}")
        output.append("-" * 140)

        # Query-by-query comparison
        wins = {'e6data': 0, 'databricks': 0, 'tie': 0}

        for query in sorted(common_queries):
            e6_orig_name, e6_data = e6_normalized[query]
            dbr_data = dbr_queries[query]

            e6_avg = e6_data['average_ms']
            dbr_avg = dbr_data['average_ms']
            e6_p95 = e6_data['p95_ms']
            dbr_p95 = dbr_data['p95_ms']

            if dbr_avg > 0:
                improvement = ((dbr_avg - e6_avg) / dbr_avg) * 100
            else:
                improvement = 0

            if abs(improvement) < 1:
                winner = "🟰 Tie"
                wins['tie'] += 1
            elif improvement > 0:
                winner = "✅ E6Data"
                wins['e6data'] += 1
            else:
                winner = "⚠️  Databricks"
                wins['databricks'] += 1

            output.append(f"{query:<20} {e6_avg:>12.0f} {dbr_avg:>12.0f} {improvement:>11.1f}% "
                         f"{e6_p95:>12.0f} {dbr_p95:>12.0f} {winner:>15}")

        # Summary
        output.append("-" * 140)
        output.append(f"Total Queries: {len(common_queries)} | "
                     f"E6Data Wins: {wins['e6data']} | "
                     f"Databricks Wins: {wins['databricks']} | "
                     f"Ties: {wins['tie']}")
        output.append("")

    output.append("=" * 140)
    return "\n".join(output)

def generate_detailed_csv(reports, output_file):
    """Generate detailed CSV comparison."""
    with open(output_file, 'w', newline='') as f:
        writer = csv.writer(f)

        # Header
        writer.writerow([
            'Concurrency', 'Query',
            'E6_Samples', 'E6_Avg_ms', 'E6_Median_ms', 'E6_p90_ms', 'E6_p95_ms', 'E6_p99_ms',
            'E6_Min_ms', 'E6_Max_ms', 'E6_Error_%', 'E6_Throughput',
            'DBR_Samples', 'DBR_Avg_ms', 'DBR_Median_ms', 'DBR_p90_ms', 'DBR_p95_ms', 'DBR_p99_ms',
            'DBR_Min_ms', 'DBR_Max_ms', 'DBR_Error_%', 'DBR_Throughput',
            'Improvement_%', 'Winner'
        ])

        concurrency_levels = sorted(reports['e6data'].keys())

        for concurrency in concurrency_levels:
            e6_queries = reports['e6data'].get(concurrency, {})
            dbr_queries = reports['databricks'].get(concurrency, {})

            if not e6_queries or not dbr_queries:
                continue

            # Create normalized query mapping
            e6_normalized = {}
            for e6_name, e6_data in e6_queries.items():
                normalized = normalize_query_name(e6_name)
                e6_normalized[normalized] = (e6_name, e6_data)

            # Find common queries
            common_queries = sorted(set(e6_normalized.keys()) & set(dbr_queries.keys()))

            for query in common_queries:
                e6_orig_name, e6_data = e6_normalized[query]
                dbr_data = dbr_queries[query]

                improvement = ((dbr_data['average_ms'] - e6_data['average_ms']) / dbr_data['average_ms'] * 100) if dbr_data['average_ms'] > 0 else 0

                if abs(improvement) < 1:
                    winner = "Tie"
                elif improvement > 0:
                    winner = "E6Data"
                else:
                    winner = "Databricks"

                writer.writerow([
                    concurrency, query,
                    e6_data['samples'], e6_data['average_ms'], e6_data['median_ms'],
                    e6_data['p90_ms'], e6_data['p95_ms'], e6_data['p99_ms'],
                    e6_data['min_ms'], e6_data['max_ms'], e6_data['error_pct'], e6_data['throughput'],
                    dbr_data['samples'], dbr_data['average_ms'], dbr_data['median_ms'],
                    dbr_data['p90_ms'], dbr_data['p95_ms'], dbr_data['p99_ms'],
                    dbr_data['min_ms'], dbr_data['max_ms'], dbr_data['error_pct'], dbr_data['throughput'],
                    improvement, winner
                ])

def main():
    parser = argparse.ArgumentParser(description='Compare JMeter aggregate reports query-by-query')
    parser.add_argument('report_dir', help='Directory containing aggregate report CSV files')
    parser.add_argument('--output-csv', help='Output detailed CSV file', default='query_comparison_detailed.csv')

    args = parser.parse_args()

    if not os.path.exists(args.report_dir):
        print(f"Error: Directory '{args.report_dir}' not found", file=sys.stderr)
        sys.exit(1)

    print("Loading aggregate reports...", file=sys.stderr)
    reports = load_all_reports(args.report_dir)

    print(f"Found {len(reports['e6data'])} e6data reports and {len(reports['databricks'])} Databricks reports", file=sys.stderr)

    # Generate summary
    print("\nGenerating summary comparison...", file=sys.stderr)
    summary = generate_summary_comparison(reports)
    print(summary)

    # Generate detailed CSV
    print(f"\nGenerating detailed CSV: {args.output_csv}", file=sys.stderr)
    generate_detailed_csv(reports, args.output_csv)
    print(f"✓ Detailed comparison saved to: {args.output_csv}", file=sys.stderr)

if __name__ == '__main__':
    main()
