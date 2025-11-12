#!/usr/bin/env python3
"""
Generate consolidated runs index from S3 test results.

This script scans S3 for all test runs and creates a comprehensive index file
with metadata and performance metrics for easy filtering and analysis.

Usage:
    # Generate index for specific run_type
    python utilities/generate_runs_index.py s3://e6-jmeter/jmeter-results/engine=e6data/cluster_size=S-2x2/benchmark=tpcds_29_1tb/run_type=concurrency_8/

    # Generate indexes for all run_types under a benchmark
    python utilities/generate_runs_index.py s3://e6-jmeter/jmeter-results/engine=e6data/cluster_size=S-2x2/benchmark=tpcds_29_1tb/ --all-run-types

    # Generate index and save locally
    python utilities/generate_runs_index.py s3://path/ --output reports/runs_index.json

    # Upload to S3 after generation
    python utilities/generate_runs_index.py s3://path/ --upload
"""

import json
import sys
import argparse
import subprocess
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# Add utilities to path for imports
sys.path.insert(0, str(Path(__file__).parent))
from jmeter_s3_utils import list_s3_files, load_statistics_from_s3


def parse_s3_path(s3_path: str) -> Dict[str, str]:
    """
    Parse S3 path to extract metadata.

    Expected format: s3://bucket/.../engine=X/cluster_size=Y/benchmark=Z/run_type=W/
    """
    pattern = r's3://([^/]+)/(.+/)?engine=([^/]+)/cluster_size=([^/]+)/benchmark=([^/]+)/run_type=([^/]+)/?'
    match = re.match(pattern, s3_path)

    if not match:
        raise ValueError(f"Invalid S3 path format: {s3_path}")

    return {
        'bucket': match.group(1),
        'prefix': match.group(2) or '',
        'engine': match.group(3),
        'cluster_size': match.group(4),
        'benchmark': match.group(5),
        'run_type': match.group(6)
    }


def list_run_ids(s3_path: str) -> List[str]:
    """
    List all run_id folders in the given S3 path.

    Returns list of run_ids (e.g., ['20251101-121403', '20251031-070614'])
    """
    files = list_s3_files(s3_path, 'run_id=')

    run_ids = set()
    for f in files:
        match = re.search(r'run_id=(\d{8}-\d{6})/', f)
        if match:
            run_ids.add(match.group(1))

    return sorted(run_ids, reverse=True)  # Latest first


def format_run_id_to_datetime(run_id: str) -> str:
    """Convert run_id (YYYYMMDD-HHMMSS) to readable datetime string."""
    try:
        dt = datetime.strptime(run_id, '%Y%m%d-%H%M%S')
        return dt.strftime('%Y-%m-%d %H:%M:%S')
    except ValueError:
        return run_id


def load_test_result_from_s3(s3_base_path: str, run_id: str) -> Optional[Dict]:
    """Load test_result.json for a specific run from S3.

    Tries both naming patterns:
    1. test_result.json (new format without timestamp)
    2. test_result_YYYYMMDD-HHMMSS.json (old format with timestamp)
    """
    # Extract bucket from s3_base_path
    bucket_match = re.search(r's3://([^/]+)/', s3_base_path)
    if not bucket_match:
        return None

    bucket = bucket_match.group(1)
    path_base = s3_base_path.replace(f"s3://{bucket}/", "")

    # Try new format first (without timestamp)
    s3_file = f"s3://{bucket}/{path_base}run_id={run_id}/test_result.json"
    cmd = ['aws', 's3', 'cp', s3_file, '-']

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return json.loads(result.stdout)
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        pass

    # Try old format with timestamp
    s3_file_old = f"s3://{bucket}/{path_base}run_id={run_id}/test_result_{run_id}.json"
    cmd_old = ['aws', 's3', 'cp', s3_file_old, '-']

    try:
        result = subprocess.run(cmd_old, capture_output=True, text=True, check=True)
        return json.loads(result.stdout)
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return None


def extract_thread_count_from_run_type(run_type: str) -> int:
    """
    Extract concurrent thread count from run_type string.

    Examples:
        'sequential' -> 1
        'concurrency_1' -> 1
        'concurrency_2' -> 2
        'concurrency_16' -> 16
    """
    if run_type == 'sequential':
        return 1

    # Extract number from 'concurrency_X' pattern
    match = re.search(r'concurrency_(\d+)', run_type)
    if match:
        return int(match.group(1))

    # Default to 0 if pattern doesn't match
    return 0


def extract_run_metadata(test_result: Dict, stats: Dict, s3_base_path: str, run_id: str, benchmark: str = 'unknown', run_type: str = 'unknown') -> Dict:
    """
    Extract comprehensive metadata from test_result.json and statistics.json.

    Returns structured metadata for the runs index.
    """
    run_info = test_result.get('run_info', {})
    cluster_config = test_result.get('cluster_config', {})
    test_config = test_result.get('test_configuration', {})
    overall_stats = test_result.get('overall_statistics', {})

    # Parse cluster config JSON if it's a string
    if isinstance(cluster_config, str):
        try:
            cluster_config = json.loads(cluster_config)
        except json.JSONDecodeError:
            cluster_config = {}

    # Build S3 path
    bucket_match = re.search(r's3://([^/]+)/', s3_base_path)
    bucket = bucket_match.group(1) if bucket_match else ''
    path_base = s3_base_path.replace(f"s3://{bucket}/", "")
    run_s3_path = f"s3://{bucket}/{path_base}run_id={run_id}/"

    # Extract total stats from statistics.json
    total_stats = stats.get('Total', {})

    # Calculate actual query count (exclude BOOTSTRAP and JSR)
    actual_queries = len([k for k in stats.keys() if k != 'Total' and 'BOOTSTRAP' not in k and 'JSR' not in k])

    # Get top 3 slowest queries
    query_times = []
    for query_name, query_stats in stats.items():
        if query_name != 'Total' and 'BOOTSTRAP' not in query_name and 'JSR' not in query_name:
            avg_time = query_stats.get('meanResTime', 0) / 1000.0
            query_times.append({'query': query_name, 'avg_sec': round(avg_time, 2)})

    query_times.sort(key=lambda x: x['avg_sec'], reverse=True)
    top_slowest = query_times[:3]

    return {
        'run_id': run_id,
        'run_date': format_run_id_to_datetime(run_id),
        's3_path': run_s3_path,

        'cluster_info': {
            'cluster_size': cluster_config.get('cluster_size', 'unknown'),
            'estimated_cores': cluster_config.get('estimated_cores', 0),
            'instance_type': cluster_config.get('instance_type', 'unknown'),
            'executors': cluster_config.get('executors', 0),
            'cores_per_executor': cluster_config.get('cores_per_executor', 0),
            'serverless': cluster_config.get('serverless', 'N') == 'Y',
            'cluster_hostname': test_config.get('connection_hostname', 'unknown')
        },

        'test_config': {
            'test_plan_file': test_config.get('test_plan_file', 'unknown'),
            'concurrent_threads': extract_thread_count_from_run_type(run_type),
            'benchmark': benchmark,  # Use benchmark parameter from S3 path
            'total_query_count': len([k for k in stats.keys() if k != 'Total']),
            'hold_period_min': test_config.get('hold_period', 0),
            'ramp_up_time_sec': test_config.get('ramp_up_time', 0),
            'query_timeout_sec': test_config.get('query_timeout', 0),
            'random_order': test_config.get('random_order', False)
        },

        'results_summary': {
            'total_samples': total_stats.get('sampleCount', 0),
            'actual_considered_queries': actual_queries,
            'excluded_queries': len([k for k in stats.keys() if 'BOOTSTRAP' in k or 'JSR' in k]),
            'total_success': total_stats.get('sampleCount', 0) - int(total_stats.get('errorCount', 0)),
            'total_failed': int(total_stats.get('errorCount', 0)),
            'error_rate_pct': round(total_stats.get('errorPct', 0), 2),
            'total_time_taken_sec': round(overall_stats.get('actual_test_duration_sec', 0), 2),

            'latency_stats': {
                'avg_latency_sec': round(total_stats.get('meanResTime', 0) / 1000.0, 2),
                'median_latency_sec': round(total_stats.get('medianResTime', 0) / 1000.0, 2),
                'min_latency_sec': round(total_stats.get('minResTime', 0) / 1000.0, 2),
                'max_latency_sec': round(total_stats.get('maxResTime', 0) / 1000.0, 2),
                'p50_latency_sec': round(total_stats.get('medianResTime', 0) / 1000.0, 2),
                'p90_latency_sec': round(total_stats.get('pct1ResTime', 0) / 1000.0, 2),
                'p95_latency_sec': round(total_stats.get('pct2ResTime', 0) / 1000.0, 2),
                'p99_latency_sec': round(total_stats.get('pct3ResTime', 0) / 1000.0, 2)
            },

            'throughput': {
                'queries_per_minute': round(overall_stats.get('queries_per_minute_actual', 0), 2),
                'queries_per_second': round(overall_stats.get('queries_per_minute_actual', 0) / 60.0, 2),
                'avg_throughput_qpm': round(overall_stats.get('queries_per_minute_actual', 0), 2)
            },

            'performance_rating': overall_stats.get('performance_assessment', 'Unknown'),
            'consistency_rating': overall_stats.get('performance_consistency', 'Unknown')
        },

        'data_transfer': {
            'bytes_received_total': int(overall_stats.get('bytes_received_total', 0)),
            'bytes_sent_total': int(overall_stats.get('bytes_sent_total', 0)),
            'avg_bytes_per_query': int(overall_stats.get('bytes_received_avg', 0))
        },

        'top_slowest_queries': top_slowest,

        'status': 'completed',

        'files': {
            'statistics_json': 'statistics.json',
            'test_result_json': 'test_result.json',
            'aggregate_report_csv': 'AggregateReport.csv',
            'jmeter_result_csv': 'JmeterResultFile.csv'
        }
    }


def generate_runs_index(s3_path: str) -> Dict:
    """
    Generate comprehensive runs index for a given S3 path.

    Args:
        s3_path: S3 path to run_type directory

    Returns:
        Dictionary with index metadata and all runs
    """
    print(f"📊 Generating runs index for: {s3_path}")

    # Parse S3 path
    path_info = parse_s3_path(s3_path)

    # List all run_ids
    run_ids = list_run_ids(s3_path)

    if not run_ids:
        print(f"⚠️  No run_ids found in {s3_path}")
        return None

    print(f"✓ Found {len(run_ids)} runs")

    # Build index structure
    index = {
        'metadata': {
            'engine': path_info['engine'],
            'cluster_size': path_info['cluster_size'],
            'benchmark': path_info['benchmark'],
            'run_type': path_info['run_type'],
            's3_base_path': s3_path.rstrip('/')
        },
        'index_info': {
            'total_runs': len(run_ids),
            'last_updated': datetime.now().strftime('%Y-%m-%dT%H:%M:%SZ'),
            'oldest_run': run_ids[-1] if run_ids else None,
            'newest_run': run_ids[0] if run_ids else None
        },
        'runs': []
    }

    # Process each run
    for i, run_id in enumerate(run_ids, 1):
        print(f"  Processing run {i}/{len(run_ids)}: {run_id}...", end='', flush=True)

        # Load test_result.json
        test_result = load_test_result_from_s3(s3_path, run_id)
        if not test_result:
            print(" ⚠️  test_result.json not found")
            continue

        # Load statistics.json
        bucket_match = re.search(r's3://([^/]+)/', s3_path)
        bucket = bucket_match.group(1)
        path_base = s3_path.replace(f"s3://{bucket}/", "")
        stats_path = f"s3://{bucket}/{path_base}run_id={run_id}/statistics.json"

        stats = load_statistics_from_s3(stats_path)
        if not stats:
            print(" ⚠️  statistics.json not found")
            continue

        # Extract metadata
        run_metadata = extract_run_metadata(test_result, stats, s3_path, run_id, path_info['benchmark'], path_info['run_type'])
        index['runs'].append(run_metadata)

        print(" ✓")

    print(f"\n✅ Successfully processed {len(index['runs'])}/{len(run_ids)} runs")

    return index


def save_index_locally(index: Dict, output_path: str):
    """Save index to local file."""
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    with open(output_file, 'w') as f:
        json.dump(index, f, indent=2)

    print(f"💾 Saved index to: {output_file}")


def upload_index_to_s3(index: Dict, s3_path: str):
    """Upload index file to S3 at run_type level."""
    s3_file = f"{s3_path.rstrip('/')}/runs_index.json"

    # Write to temp file
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as tmp:
        json.dump(index, tmp, indent=2)
        tmp_path = tmp.name

    # Upload to S3
    cmd = ['aws', 's3', 'cp', tmp_path, s3_file]

    try:
        subprocess.run(cmd, check=True, capture_output=True)
        print(f"☁️  Uploaded to: {s3_file}")
        Path(tmp_path).unlink()
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to upload: {e.stderr.decode()}")
        Path(tmp_path).unlink()
        return False


def main():
    parser = argparse.ArgumentParser(
        description='Generate comprehensive runs index from S3 test results',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument(
        's3_path',
        help='S3 path to run_type directory (e.g., s3://bucket/.../run_type=concurrency_8/)'
    )

    parser.add_argument(
        '--output', '-o',
        help='Output file path (default: reports/runs_index.json)',
        default='reports/runs_index.json'
    )

    parser.add_argument(
        '--upload', '-u',
        action='store_true',
        help='Upload generated index to S3'
    )

    parser.add_argument(
        '--all-run-types',
        action='store_true',
        help='Generate indexes for all run_types under the given path'
    )

    args = parser.parse_args()

    # Generate index
    index = generate_runs_index(args.s3_path)

    if not index:
        sys.exit(1)

    # Save locally
    save_index_locally(index, args.output)

    # Upload to S3 if requested
    if args.upload:
        upload_index_to_s3(index, args.s3_path)

    # Print summary
    print("\n" + "="*70)
    print("📈 RUNS INDEX SUMMARY")
    print("="*70)
    print(f"Engine: {index['metadata']['engine']}")
    print(f"Cluster: {index['metadata']['cluster_size']}")
    print(f"Benchmark: {index['metadata']['benchmark']}")
    print(f"Run Type: {index['metadata']['run_type']}")
    print(f"Total Runs: {index['index_info']['total_runs']}")
    print(f"Date Range: {index['index_info']['oldest_run']} → {index['index_info']['newest_run']}")
    print("="*70)


if __name__ == '__main__':
    main()
