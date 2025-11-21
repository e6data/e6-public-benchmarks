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


def parse_jmeter_summary(jmeter_summary: str) -> dict:
    """
    Parse JMeter summary string to extract comprehensive metrics.

    Example input: "summary =     34 in 00:05:01 =    0.1/s Avg:  4529 Min:   511 Max: 13059 Err:     0 (0.00%)"

    Extracts:
    - total_samples: 34
    - duration_sec: 301 (00:05:01 = 5 minutes 1 second)
    - throughput_qps: 0.1 (queries per second)
    - avg_response_time_ms: 4529
    - min_response_time_ms: 511
    - max_response_time_ms: 13059
    - error_count: 0
    - error_pct: 0.00

    Args:
        jmeter_summary: JMeter summary string from test_result.json

    Returns:
        Dictionary with parsed metrics, or defaults if parsing fails
    """
    result = {
        'total_samples': 0,
        'duration_sec': 0.0,
        'throughput_qps': 0.0,
        'avg_response_time_ms': 0,
        'min_response_time_ms': 0,
        'max_response_time_ms': 0,
        'error_count': 0,
        'error_pct': 0.0
    }

    if not jmeter_summary or not isinstance(jmeter_summary, str):
        return result

    # Pattern: "summary =     34 in 00:05:01 =    0.1/s Avg:  4529 Min:   511 Max: 13059 Err:     0 (0.00%)"
    # Extract: total_samples in HH:MM:SS = throughput/s Avg: avg Min: min Max: max Err: err_count (err_pct%)

    # Extract total samples
    samples_match = re.search(r'summary\s*=\s*(\d+)\s+in', jmeter_summary)
    if samples_match:
        result['total_samples'] = int(samples_match.group(1))

    # Extract duration (HH:MM:SS)
    duration_match = re.search(r'in\s+(\d{2}):(\d{2}):(\d{2})', jmeter_summary)
    if duration_match:
        hours = int(duration_match.group(1))
        minutes = int(duration_match.group(2))
        seconds = int(duration_match.group(3))
        result['duration_sec'] = float((hours * 3600) + (minutes * 60) + seconds)

    # Extract throughput (queries per second)
    throughput_match = re.search(r'=\s+([\d.]+)/s', jmeter_summary)
    if throughput_match:
        result['throughput_qps'] = float(throughput_match.group(1))

    # Extract Avg response time
    avg_match = re.search(r'Avg:\s+(\d+)', jmeter_summary)
    if avg_match:
        result['avg_response_time_ms'] = int(avg_match.group(1))

    # Extract Min response time
    min_match = re.search(r'Min:\s+(\d+)', jmeter_summary)
    if min_match:
        result['min_response_time_ms'] = int(min_match.group(1))

    # Extract Max response time
    max_match = re.search(r'Max:\s+(\d+)', jmeter_summary)
    if max_match:
        result['max_response_time_ms'] = int(max_match.group(1))

    # Extract error count
    err_count_match = re.search(r'Err:\s+(\d+)', jmeter_summary)
    if err_count_match:
        result['error_count'] = int(err_count_match.group(1))

    # Extract error percentage
    err_pct_match = re.search(r'\((\d+\.?\d*?)%\)', jmeter_summary)
    if err_pct_match:
        result['error_pct'] = float(err_pct_match.group(1))

    return result


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

    Note: test_result.json has these main sections:
    - run_mode, customer, config, tags, comments (root level)
    - cluster_config (root level)
    - test_execution_config (has test_plan_file, hold_period_min, etc.)
    - performance_metrics (has total_time_taken_sec, queries_per_minute_actual, etc.)
    - data_transfer_metrics (has bytes_sent_total, bytes_received_total, etc.)
    """
    # Map to actual field names in test_result.json
    run_info = {
        'run_mode': test_result.get('run_mode', 'test'),
        'customer': test_result.get('customer', 'default'),
        'config': test_result.get('config', 'default'),
        'tags': test_result.get('tags', ''),
        'comments': test_result.get('comments', '')
    }
    cluster_config = test_result.get('cluster_config', {})
    test_config = test_result.get('test_execution_config', {})
    perf_metrics = test_result.get('performance_metrics', {})
    data_transfer = test_result.get('data_transfer_metrics', {})

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

    # Calculate performance_rating based on avg_latency_sec
    avg_latency_sec = total_stats.get('meanResTime', 0) / 1000.0
    if avg_latency_sec < 2.0:
        performance_rating = "Excellent"
    elif avg_latency_sec < 5.0:
        performance_rating = "Good"
    elif avg_latency_sec < 10.0:
        performance_rating = "Fair"
    else:
        performance_rating = "Poor"

    # Calculate consistency_rating based on p99/p50 ratio
    p50 = total_stats.get('medianResTime', 0) / 1000.0
    p99 = total_stats.get('pct3ResTime', 0) / 1000.0
    if p50 > 0:
        p99_p50_ratio = p99 / p50
        if p99_p50_ratio < 2.0:
            consistency_rating = "Excellent"
        elif p99_p50_ratio < 3.0:
            consistency_rating = "Good"
        elif p99_p50_ratio < 5.0:
            consistency_rating = "Fair"
        else:
            consistency_rating = "Poor"
    else:
        consistency_rating = "Unknown"

    # Calculate test config values first (needed for total_time calculation)
    ramp_up_time_sec = int(test_config.get('ramp_up_time_min', 0)) * 60 if test_config.get('ramp_up_time_min') else 0
    hold_period_min = int(test_config.get('hold_period_min', 0)) if test_config.get('hold_period_min') else 0

    # Parse JMeter summary to extract comprehensive metrics
    # JMeter summary format: "summary =     34 in 00:05:01 =    0.1/s Avg:  4529..."
    # Extracts: duration, throughput_qps, response times, error counts
    jmeter_summary = test_result.get('jmeter_run_summary', '')
    jmeter_metrics = parse_jmeter_summary(jmeter_summary)

    # Get total_time_taken_sec from JMeter summary (most accurate)
    total_time_sec = jmeter_metrics['duration_sec']

    # Fallback: try to get from performance_metrics
    if total_time_sec == 0:
        total_time_sec = perf_metrics.get('actual_test_duration_sec', 0)

        # Validate: if > 86400 (1 day), it's bad data
        # Typical test runs are 5-30 minutes (300-1800 seconds)
        # IMPORTANT: hold_period_min field is actually in SECONDS (despite the name!)
        # So don't multiply by 60
        if total_time_sec > 86400 or total_time_sec == 0:
            total_time_sec = ramp_up_time_sec + hold_period_min  # both in seconds

    total_time_sec = round(total_time_sec, 2)

    # Get throughput from JMeter summary (queries per second)
    throughput_qps = round(jmeter_metrics['throughput_qps'], 2)

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
            'cluster_hostname': test_result.get('cluster_hostname', 'unknown')
        },

        'test_config': {
            'test_plan_file': test_config.get('test_plan_file', 'unknown'),
            'concurrent_threads': int(test_config.get('concurrent_threads', 0)) if test_config.get('concurrent_threads') else extract_thread_count_from_run_type(run_type),
            'benchmark': benchmark,  # Use benchmark parameter from S3 path
            'total_query_count': len([k for k in stats.keys() if k != 'Total']),
            'hold_period_min': hold_period_min,  # Use pre-calculated value
            'ramp_up_time_sec': ramp_up_time_sec,  # Use pre-calculated value
            'query_timeout_sec': int(test_config.get('query_timeout_sec', 0)) if test_config.get('query_timeout_sec') else 0,
            'random_order': test_config.get('random_order', 'false') == 'true'
        },

        'results_summary': {
            'total_samples': total_stats.get('sampleCount', 0),
            'actual_considered_queries': actual_queries,
            'excluded_queries': len([k for k in stats.keys() if 'BOOTSTRAP' in k or 'JSR' in k]),
            'total_success': total_stats.get('sampleCount', 0) - int(total_stats.get('errorCount', 0)),
            'total_failed': int(total_stats.get('errorCount', 0)),
            'error_rate_pct': round(total_stats.get('errorPct', 0), 2),
            'total_time_taken_sec': total_time_sec,

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
                'queries_per_second': throughput_qps,  # From JMeter summary (e.g., 0.1/s)
                'queries_per_minute': round(throughput_qps * 60, 2),  # Convert to QPM
                'avg_throughput_qpm': round(throughput_qps * 60, 2)
            },

            'performance_rating': performance_rating,
            'consistency_rating': consistency_rating
        },

        'data_transfer': {
            'bytes_received_total': int(data_transfer.get('bytes_received_total', 0)),
            'bytes_sent_total': int(data_transfer.get('bytes_sent_total', 0)),
            'avg_bytes_per_query': int(data_transfer.get('bytes_received_avg', 0))
        },

        'top_slowest_queries': top_slowest,

        'run_metadata': {
            'run_mode': run_info.get('run_mode', 'test'),
            'customer': run_info.get('customer', 'default'),
            'config': run_info.get('config', 'default'),
            'tags': run_info.get('tags', ''),
            'comments': run_info.get('comments', '')
        },

        'outlier_info': {
            'outlier_severity': None,
            'p90_z_score': None,
            'p90_deviation_pct': None,
            'p95_z_score': None,
            'p95_deviation_pct': None,
            'p99_z_score': None,
            'p99_deviation_pct': None
        },

        'status': 'completed',

        # Manual outlier flag for filtering bad/incorrect runs
        # Default: "no" - Can be overridden to "yes" to exclude from analysis
        'is_outlier': 'no',

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
