#!/usr/bin/env python3
"""
Upload runs index data to S3 for Athena querying.

Converts runs_index.json to partitioned JSONL format for Athena table.

Usage:
    # Upload from local runs_index.json
    python utilities/upload_runs_index_to_athena.py reports/runs_index.json

    # Generate index and upload directly from S3
    python utilities/upload_runs_index_to_athena.py --from-s3 s3://e6-jmeter/jmeter-results/engine=e6data/cluster_size=M-4x4/benchmark=tpcds_29_1tb/run_type=concurrency_2/

    # Dry run (don't upload, just show what would be uploaded)
    python utilities/upload_runs_index_to_athena.py reports/runs_index.json --dry-run
"""

import json
import sys
import argparse
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List
from datetime import datetime


def flatten_run_for_athena(run: Dict, metadata: Dict) -> Dict:
    """
    Flatten run data to single-level JSON for Athena.
    Add partition columns from metadata.
    """
    flat = {
        # Run identification
        'run_id': run['run_id'],
        'run_date': run['run_date'],
        's3_path': run['s3_path'],
        'status': run['status'],

        # Cluster info
        'cluster_size': run['cluster_info']['cluster_size'],
        'estimated_cores': run['cluster_info']['estimated_cores'],
        'instance_type': run['cluster_info']['instance_type'],
        'executors': run['cluster_info']['executors'],
        'cores_per_executor': run['cluster_info']['cores_per_executor'],
        'serverless': run['cluster_info']['serverless'],
        'cluster_hostname': run['cluster_info']['cluster_hostname'],

        # Test config
        'test_plan_file': run['test_config']['test_plan_file'],
        'concurrent_threads': run['test_config']['concurrent_threads'],
        'benchmark': run['test_config']['benchmark'],
        'total_query_count': run['test_config']['total_query_count'],
        'hold_period_min': run['test_config']['hold_period_min'],
        'ramp_up_time_sec': run['test_config']['ramp_up_time_sec'],
        'query_timeout_sec': run['test_config']['query_timeout_sec'],
        'random_order': run['test_config']['random_order'],

        # Results summary
        'total_samples': run['results_summary']['total_samples'],
        'actual_considered_queries': run['results_summary']['actual_considered_queries'],
        'excluded_queries': run['results_summary']['excluded_queries'],
        'total_success': run['results_summary']['total_success'],
        'total_failed': run['results_summary']['total_failed'],
        'error_rate_pct': run['results_summary']['error_rate_pct'],
        'total_time_taken_sec': run['results_summary']['total_time_taken_sec'],

        # Latency stats
        'avg_latency_sec': run['results_summary']['latency_stats']['avg_latency_sec'],
        'median_latency_sec': run['results_summary']['latency_stats']['median_latency_sec'],
        'min_latency_sec': run['results_summary']['latency_stats']['min_latency_sec'],
        'max_latency_sec': run['results_summary']['latency_stats']['max_latency_sec'],
        'p50_latency_sec': run['results_summary']['latency_stats']['p50_latency_sec'],
        'p90_latency_sec': run['results_summary']['latency_stats']['p90_latency_sec'],
        'p95_latency_sec': run['results_summary']['latency_stats']['p95_latency_sec'],
        'p99_latency_sec': run['results_summary']['latency_stats']['p99_latency_sec'],

        # Throughput
        'queries_per_minute': run['results_summary']['throughput']['queries_per_minute'],
        'queries_per_second': run['results_summary']['throughput']['queries_per_second'],
        'avg_throughput_qpm': run['results_summary']['throughput']['avg_throughput_qpm'],

        # Performance ratings
        'performance_rating': run['results_summary']['performance_rating'],
        'consistency_rating': run['results_summary']['consistency_rating'],

        # Data transfer
        'bytes_received_total': run['data_transfer']['bytes_received_total'],
        'bytes_sent_total': run['data_transfer']['bytes_sent_total'],
        'avg_bytes_per_query': run['data_transfer']['avg_bytes_per_query'],

        # Top slowest queries (keep as array for Athena UNNEST)
        'top_slowest_queries': run['top_slowest_queries'],

        # Partition columns (NOT part of table schema, used for S3 path)
        'engine': metadata['engine'],
        'cluster_size_partition': metadata['cluster_size'],
        'benchmark_partition': metadata['benchmark'],
        'run_type': metadata['run_type']
    }

    return flat


def upload_to_s3(index_file: str, s3_base: str = 's3://e6-jmeter/jmeter-results-index', dry_run: bool = False):
    """
    Upload runs index data to S3 in partitioned structure for Athena.

    Target structure:
    s3://bucket/jmeter-results-index/runs/
        engine=e6data/
            cluster_size=M-4x4/
                benchmark=tpcds_29_1tb/
                    run_type=concurrency_2/
                        data.jsonl  (one JSON object per line)
    """
    # Load index
    with open(index_file, 'r') as f:
        index = json.load(f)

    metadata = index['metadata']
    runs = index['runs']

    if not runs:
        print("⚠️  No runs found in index file")
        return

    print(f"📊 Processing {len(runs)} runs from index")
    print(f"   Engine: {metadata['engine']}")
    print(f"   Cluster: {metadata['cluster_size']}")
    print(f"   Benchmark: {metadata['benchmark']}")
    print(f"   Run Type: {metadata['run_type']}")

    # Flatten all runs
    flat_runs = [flatten_run_for_athena(run, metadata) for run in runs]

    # Create JSONL content (one JSON per line)
    jsonl_content = '\n'.join([json.dumps(run) for run in flat_runs])

    # Build S3 path with partitions
    s3_path = (
        f"{s3_base.rstrip('/')}/runs/"
        f"engine={metadata['engine']}/"
        f"cluster_size={metadata['cluster_size']}/"
        f"benchmark={metadata['benchmark']}/"
        f"run_type={metadata['run_type']}/"
        f"data.jsonl"
    )

    print(f"\n📍 Target S3 path:")
    print(f"   {s3_path}")

    if dry_run:
        print("\n🔍 DRY RUN - Would upload this content:")
        print("-" * 80)
        print(jsonl_content[:500] + "..." if len(jsonl_content) > 500 else jsonl_content)
        print("-" * 80)
        print(f"\n✓ {len(flat_runs)} runs ready to upload")
        return

    # Write to temp file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as tmp:
        tmp.write(jsonl_content)
        tmp_path = tmp.name

    # Upload to S3
    cmd = ['aws', 's3', 'cp', tmp_path, s3_path]

    try:
        print("\n☁️  Uploading to S3...")
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        print(f"✅ Successfully uploaded {len(flat_runs)} runs to:")
        print(f"   {s3_path}")
        print(f"\n💡 Next steps:")
        print(f"   1. Run Athena DDL: utilities/setup_athena_runs_index.sql")
        print(f"   2. Query in Athena console or connect to Superset/QuickSight")
        print(f"   3. Example query:")
        print(f"      SELECT run_id, cluster_size, p50_latency_sec, p90_latency_sec")
        print(f"      FROM jmeter_runs_index")
        print(f"      WHERE engine = '{metadata['engine']}'")
        print(f"        AND run_type = '{metadata['run_type']}'")
        print(f"      ORDER BY run_date DESC;")

    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to upload: {e.stderr}")
        sys.exit(1)
    finally:
        Path(tmp_path).unlink()


def generate_and_upload_from_s3(s3_path: str, s3_base: str, dry_run: bool = False):
    """Generate index from S3 and upload directly to Athena location."""
    # Import generate_runs_index from existing script
    sys.path.insert(0, str(Path(__file__).parent))
    from generate_runs_index import generate_runs_index

    print(f"📊 Generating index from S3: {s3_path}")
    index = generate_runs_index(s3_path)

    if not index:
        print("❌ Failed to generate index")
        sys.exit(1)

    # Save to temp file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as tmp:
        json.dump(index, tmp, indent=2)
        tmp_path = tmp.name

    # Upload to Athena location
    upload_to_s3(tmp_path, s3_base, dry_run)

    # Cleanup
    Path(tmp_path).unlink()


def main():
    parser = argparse.ArgumentParser(
        description='Upload runs index to S3 for Athena querying',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument(
        'index_file',
        nargs='?',
        help='Path to runs_index.json file (not needed with --from-s3)'
    )

    parser.add_argument(
        '--from-s3',
        help='Generate index from S3 path and upload directly',
        metavar='S3_PATH'
    )

    parser.add_argument(
        '--s3-base',
        help='Base S3 path for Athena data (default: s3://e6-jmeter/jmeter-results-index)',
        default='s3://e6-jmeter/jmeter-results-index'
    )

    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be uploaded without actually uploading'
    )

    args = parser.parse_args()

    # Validate input
    if args.from_s3:
        generate_and_upload_from_s3(args.from_s3, args.s3_base, args.dry_run)
    elif args.index_file:
        if not Path(args.index_file).exists():
            print(f"❌ Error: Input file not found: {args.index_file}")
            sys.exit(1)
        upload_to_s3(args.index_file, args.s3_base, args.dry_run)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()
