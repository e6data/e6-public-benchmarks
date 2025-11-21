#!/usr/bin/env python3
"""
Compare multiple JMeter runs from S3 and generate a comprehensive CSV report.

This utility can compare N runs (not just 2) and includes extensive metadata
columns for better analysis and tracking.

Usage:
    python3 compare_multiple_runs_from_s3.py RUN_ID1 RUN_ID2 RUN_ID3 ... [OPTIONS]

    # Or scan a directory for all runs:
    python3 compare_multiple_runs_from_s3.py --scan s3://path/to/sequential/ [OPTIONS]

Example:
    python3 compare_multiple_runs_from_s3.py \\
        s3://e6-jmeter/jmeter-results/.../run_id=20251119-071502/ \\
        s3://e6-jmeter/jmeter-results/.../run_id=20251119-072441/ \\
        s3://e6-jmeter/jmeter-results/.../run_id=20251119-073304/ \\
        --output /tmp/comparison.csv \\
        --tag "Nov19_InstanceComparison" \\
        --comments "Comparing i4i vs i3 instance types"
"""

import argparse
import boto3
import csv
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse

class S3RunFetcher:
    """Fetch JMeter run data from S3."""

    def __init__(self):
        self.s3_client = boto3.client('s3')

    def parse_s3_path(self, s3_path: str) -> tuple:
        """Parse S3 path into bucket and key."""
        s3_path = s3_path.rstrip('/')
        if s3_path.startswith('s3://'):
            s3_path = s3_path[5:]

        parts = s3_path.split('/', 1)
        bucket = parts[0]
        key = parts[1] if len(parts) > 1 else ''

        return bucket, key

    def fetch_json_from_s3(self, s3_path: str, filename: str) -> Optional[Dict]:
        """Fetch and parse JSON file from S3."""
        try:
            bucket, key_prefix = self.parse_s3_path(s3_path)
            full_key = f"{key_prefix}/{filename}"

            response = self.s3_client.get_object(Bucket=bucket, Key=full_key)
            content = response['Body'].read().decode('utf-8')
            return json.loads(content)
        except Exception as e:
            print(f"Warning: Could not fetch {filename} from {s3_path}: {e}", file=sys.stderr)
            return None

    def extract_metadata_from_path(self, s3_path: str) -> Dict:
        """Extract metadata from S3 path structure."""
        metadata = {
            'engine': 'unknown',
            'cluster_size': 'unknown',
            'benchmark': 'unknown',
            'run_type': 'unknown',
            'run_id': 'unknown'
        }

        # Parse path like: engine=e6data/cluster_size=XS-1x1/benchmark=tpcds_29_1tb/run_type=sequential/run_id=20251119-071502
        patterns = {
            'engine': r'engine=([^/]+)',
            'cluster_size': r'cluster_size=([^/]+)',
            'benchmark': r'benchmark=([^/]+)',
            'run_type': r'run_type=([^/]+)',
            'run_id': r'run_id=([^/]+)'
        }

        for key, pattern in patterns.items():
            match = re.search(pattern, s3_path)
            if match:
                metadata[key] = match.group(1)

        return metadata

    def scan_directory_for_runs(self, s3_directory: str) -> List[str]:
        """Scan S3 directory and find all run_id subdirectories."""
        bucket, prefix = self.parse_s3_path(s3_directory)

        if not prefix.endswith('/'):
            prefix += '/'

        runs = []
        try:
            paginator = self.s3_client.get_paginator('list_objects_v2')

            for page in paginator.paginate(Bucket=bucket, Prefix=prefix, Delimiter='/'):
                if 'CommonPrefixes' in page:
                    for obj in page['CommonPrefixes']:
                        subdir = obj['Prefix']
                        # Check if this looks like a run_id directory
                        if 'run_id=' in subdir or re.search(r'\d{8}-\d{6}', subdir):
                            runs.append(f"s3://{bucket}/{subdir.rstrip('/')}")

        except Exception as e:
            print(f"Error scanning directory {s3_directory}: {e}", file=sys.stderr)

        return sorted(runs)

    def fetch_run_data(self, s3_path: str) -> Dict:
        """Fetch all data for a single run."""
        print(f"Fetching data from {s3_path}...", file=sys.stderr)

        # Extract path metadata
        path_metadata = self.extract_metadata_from_path(s3_path)

        # Fetch test_result.json
        test_result = self.fetch_json_from_s3(s3_path, f"test_result_{path_metadata['run_id']}.json")
        if not test_result:
            # Try without run_id in filename
            test_result = self.fetch_json_from_s3(s3_path, "test_result.json")

        # Fetch statistics.json
        statistics = self.fetch_json_from_s3(s3_path, f"statistics_{path_metadata['run_id']}.json")
        if not statistics:
            statistics = self.fetch_json_from_s3(s3_path, "statistics.json")

        # Parse JMeter summary from test_result
        jmeter_summary = {}
        if test_result and 'jmeter_run_summary' in test_result:
            jmeter_summary = self.parse_jmeter_summary(test_result['jmeter_run_summary'])

        return {
            's3_path': s3_path,
            'path_metadata': path_metadata,
            'test_result': test_result or {},
            'statistics': statistics or {},
            'jmeter_summary': jmeter_summary
        }

    def parse_jmeter_summary(self, summary_str: str) -> Dict:
        """Parse JMeter summary string into structured data."""
        # Example: "summary =     34 in 00:05:01 =    0.1/s Avg:  2456 Min:   177 Max:  7798 Err:     0 (0.00%)"
        parsed = {}

        # Extract duration
        duration_match = re.search(r'in\s+(\d{2}):(\d{2}):(\d{2})', summary_str)
        if duration_match:
            hours = int(duration_match.group(1))
            minutes = int(duration_match.group(2))
            seconds = int(duration_match.group(3))
            parsed['total_duration_sec'] = (hours * 3600) + (minutes * 60) + seconds

        # Extract metrics (in milliseconds)
        for metric in ['Avg', 'Min', 'Max']:
            match = re.search(rf'{metric}:\s*(\d+)', summary_str)
            if match:
                parsed[f'{metric.lower()}_ms'] = int(match.group(1))

        return parsed


class RunComparator:
    """Compare multiple JMeter runs and generate reports."""

    def __init__(self, tag: str = '', comments: str = ''):
        self.tag = tag
        self.comments = comments
        self.runs = []

    def add_run(self, run_data: Dict):
        """Add a run to the comparison."""
        self.runs.append(run_data)

    def generate_comparison_csv(self, output_file: str):
        """Generate comprehensive CSV comparison report."""

        if not self.runs:
            print("Error: No runs to compare", file=sys.stderr)
            return

        # Sort runs by run_id for consistent ordering
        self.runs.sort(key=lambda r: r['path_metadata']['run_id'])

        with open(output_file, 'w', newline='') as f:
            writer = csv.writer(f)

            # Header row
            header = [
                'run_id',
                'engine',
                'cluster_size',
                'instance_type',
                'benchmark',
                'run_type',
                'total_queries',
                'successful_queries',
                'failed_queries',
                'avg_latency_sec',
                'min_latency_sec',
                'max_latency_sec',
                'p50_latency_sec',
                'p90_latency_sec',
                'p95_latency_sec',
                'p99_latency_sec',
                'total_duration_sec',
                'queries_per_sec',
                'tag',
                'comments',
                's3_path'
            ]
            writer.writerow(header)

            # Data rows
            for run in self.runs:
                row = self.extract_row_data(run)
                writer.writerow(row)

        print(f"\nCSV report generated: {output_file}")
        print(f"Total runs compared: {len(self.runs)}")

    def extract_row_data(self, run: Dict) -> List:
        """Extract data for a single row in the CSV."""
        path_meta = run['path_metadata']
        test_result = run['test_result']
        stats = run['statistics']
        jmeter = run['jmeter_summary']

        # Extract cluster config
        cluster_config = test_result.get('cluster_config', {})
        instance_type = cluster_config.get('instance_type', 'unknown')

        # Extract performance metrics
        perf_metrics = test_result.get('performance_metrics', {})
        total_queries = perf_metrics.get('total_queries', stats.get('Total', {}).get('sampleCount', 0))
        successful = perf_metrics.get('successful_queries', 0)
        failed = perf_metrics.get('failed_queries', 0)

        # Get latencies (prefer test_result, fallback to statistics)
        avg_lat = perf_metrics.get('avg_latency_sec')
        if avg_lat is None and jmeter.get('avg_ms'):
            avg_lat = round(jmeter['avg_ms'] / 1000, 3)

        min_lat = perf_metrics.get('min_latency_sec')
        if min_lat is None and jmeter.get('min_ms'):
            min_lat = round(jmeter['min_ms'] / 1000, 3)

        max_lat = perf_metrics.get('max_latency_sec')
        if max_lat is None and jmeter.get('max_ms'):
            max_lat = round(jmeter['max_ms'] / 1000, 3)

        p50_lat = perf_metrics.get('p50_latency_sec')
        p90_lat = perf_metrics.get('p90_latency_sec')
        p95_lat = perf_metrics.get('p95_latency_sec')
        p99_lat = perf_metrics.get('p99_latency_sec')

        # Get total duration
        total_duration = jmeter.get('total_duration_sec', perf_metrics.get('actual_test_duration_sec', 0))

        # Calculate QPS
        qps = 0
        if total_duration and total_duration > 0 and total_queries:
            qps = round(total_queries / total_duration, 2)

        return [
            path_meta['run_id'],
            path_meta['engine'],
            path_meta['cluster_size'],
            instance_type,
            path_meta['benchmark'],
            path_meta['run_type'],
            total_queries,
            successful,
            failed,
            avg_lat,
            min_lat,
            max_lat,
            p50_lat,
            p90_lat,
            p95_lat,
            p99_lat,
            total_duration,
            qps,
            self.tag,
            self.comments,
            run['s3_path']
        ]

    def print_summary(self):
        """Print summary statistics to console."""
        if not self.runs:
            return

        print("\n" + "=" * 100)
        print("COMPARISON SUMMARY")
        print("=" * 100)
        print(f"Total runs: {len(self.runs)}")
        print(f"Tag: {self.tag if self.tag else 'N/A'}")
        print(f"Comments: {self.comments if self.comments else 'N/A'}")
        print("=" * 100)

        # Print key metrics for each run
        print(f"\n{'Run ID':<20} {'Instance':<20} {'Avg (s)':<12} {'P99 (s)':<12} {'QPS':<10}")
        print("-" * 100)

        for run in self.runs:
            row = self.extract_row_data(run)
            run_id = row[0]
            instance = row[3]
            avg_lat = row[9]
            p99_lat = row[15]
            qps = row[17]

            print(f"{run_id:<20} {instance:<20} {avg_lat if avg_lat else 'N/A':<12} {p99_lat if p99_lat else 'N/A':<12} {qps if qps else 'N/A':<10}")

        print("=" * 100)


def main():
    parser = argparse.ArgumentParser(
        description='Compare multiple JMeter runs from S3 and generate comprehensive CSV report.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument(
        'run_paths',
        nargs='*',
        help='S3 paths to individual run directories (e.g., s3://.../run_id=20251119-071502/)'
    )

    parser.add_argument(
        '--scan',
        help='Scan this S3 directory for all runs instead of specifying individual paths'
    )

    parser.add_argument(
        '--output',
        default='reports/jmeter_comparison.csv',
        help='Output CSV file path (default: reports/jmeter_comparison.csv)'
    )

    parser.add_argument(
        '--tag',
        default='',
        help='Tag to add to all rows for categorization (e.g., "Nov19_InstanceTest")'
    )

    parser.add_argument(
        '--comments',
        default='',
        help='Comments to add to all rows (e.g., "Comparing i4i vs i3 instances")'
    )

    args = parser.parse_args()

    # Validate input
    if not args.run_paths and not args.scan:
        parser.error("Must provide either run_paths or --scan directory")

    fetcher = S3RunFetcher()
    comparator = RunComparator(tag=args.tag, comments=args.comments)

    # Collect run paths
    run_paths = []

    if args.scan:
        print(f"Scanning directory: {args.scan}")
        run_paths = fetcher.scan_directory_for_runs(args.scan)
        print(f"Found {len(run_paths)} runs")
    else:
        run_paths = args.run_paths

    if not run_paths:
        print("Error: No runs found to compare", file=sys.stderr)
        sys.exit(1)

    # Fetch data for each run
    print(f"\nFetching data for {len(run_paths)} runs...")
    for run_path in run_paths:
        run_data = fetcher.fetch_run_data(run_path)
        comparator.add_run(run_data)

    # Generate report
    comparator.print_summary()
    comparator.generate_comparison_csv(args.output)

    print(f"\nDone! CSV saved to: {args.output}")


if __name__ == '__main__':
    main()
