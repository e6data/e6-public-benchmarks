#!/usr/bin/env python3
"""
Generate metadata JSONL index for jmeter_run_metadata Athena table.

This script extracts test run metadata from test_result.json files and creates
JSONL output files partitioned by engine/cluster_size for Athena ingestion.

Usage:
    # Generate metadata for specific run_type
    python utilities/athena/generate_metadata_index.py \
        s3://your-s3-bucket/jmeter-results/engine=e6data/cluster_size=S-2x2/benchmark=tpcds_29_1tb/run_type=concurrency_8/

    # Generate for all run_types under a benchmark
    python utilities/athena/generate_metadata_index.py \
        s3://your-s3-bucket/jmeter-results/engine=e6data/cluster_size=S-2x2/benchmark=tpcds_29_1tb/ \
        --all-run-types

    # Specify output directory
    python utilities/athena/generate_metadata_index.py s3://path/ --output /tmp/metadata/
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

# Add utilities to path for imports
sys.path.insert(0, str(Path(__file__).parent))
from jmeter_s3_utils import list_s3_files, load_statistics_from_s3


def parse_s3_path(s3_path: str) -> Dict[str, str]:
    """
    Parse S3 path to extract metadata.

    Expected format: s3://bucket/.../engine=X/cluster_size=Y/benchmark=Z/run_type=W/
    """
    pattern = r"s3://([^/]+)/(.+/)?engine=([^/]+)/cluster_size=([^/]+)/benchmark=([^/]+)/run_type=([^/]+)/?"
    match = re.match(pattern, s3_path)

    if not match:
        raise ValueError(f"Invalid S3 path format: {s3_path}")

    return {
        "bucket": match.group(1),
        "prefix": match.group(2) or "",
        "engine": match.group(3),
        "cluster_size": match.group(4),
        "benchmark": match.group(5),
        "run_type": match.group(6),
    }


def list_run_ids(s3_path: str) -> List[str]:
    """
    List all run_id folders in the given S3 path.

    Returns list of run_ids (e.g., ['20251101-121403', '20251031-070614'])
    """
    files = list_s3_files(s3_path, "run_id=")

    run_ids = set()
    for f in files:
        match = re.search(r"run_id=(\d{8}-\d{6})/", f)
        if match:
            run_ids.add(match.group(1))

    return sorted(run_ids, reverse=True)  # Latest first


def format_run_id_to_datetime(run_id: str) -> str:
    """Convert run_id (YYYYMMDD-HHMMSS) to readable datetime string."""
    try:
        dt = datetime.strptime(run_id, "%Y%m%d-%H%M%S")
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return run_id


def load_test_result_from_s3(s3_base_path: str, run_id: str) -> Optional[Dict]:
    """Load test_result.json for a specific run from S3.

    Tries both naming patterns:
    1. test_result.json (new format without timestamp)
    2. test_result_YYYYMMDD-HHMMSS.json (old format with timestamp)
    """
    bucket_match = re.search(r"s3://([^/]+)/", s3_base_path)
    if not bucket_match:
        return None

    bucket = bucket_match.group(1)
    path_base = s3_base_path.replace(f"s3://{bucket}/", "")

    # Try new format first (without timestamp)
    s3_file = f"s3://{bucket}/{path_base}run_id={run_id}/test_result.json"
    cmd = ["aws", "s3", "cp", s3_file, "-"]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return json.loads(result.stdout)
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        pass

    # Try old format with timestamp
    s3_file_old = f"s3://{bucket}/{path_base}run_id={run_id}/test_result_{run_id}.json"
    cmd_old = ["aws", "s3", "cp", s3_file_old, "-"]

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
    if run_type == "sequential":
        return 1

    # Extract number from 'concurrency_X' pattern
    match = re.search(r"concurrency_(\d+)", run_type)
    if match:
        return int(match.group(1))

    # Default to 0 if pattern doesn't match
    return 0


def extract_metadata_record(
    test_result: Dict,
    stats: Dict,
    s3_base_path: str,
    run_id: str,
    engine: str,
    cluster_size: str,
    benchmark: str,
    run_type: str,
) -> Dict:
    """
    Extract metadata record for jmeter_run_metadata table.

    Returns flat dictionary matching Athena table schema.
    """
    # Parse cluster config JSON if it's a string
    cluster_config = test_result.get("cluster_config", {})
    if isinstance(cluster_config, str):
        try:
            cluster_config = json.loads(cluster_config)
        except json.JSONDecodeError:
            cluster_config = {}

    test_config = test_result.get("test_execution_config", {})

    # Build S3 path
    bucket_match = re.search(r"s3://([^/]+)/", s3_base_path)
    bucket = bucket_match.group(1) if bucket_match else ""
    path_base = s3_base_path.replace(f"s3://{bucket}/", "")
    run_s3_path = f"s3://{bucket}/{path_base}run_id={run_id}/"

    # Calculate test config values
    ramp_up_time_sec = (
        int(test_config.get("ramp_up_time_min", 0)) * 60
        if test_config.get("ramp_up_time_min")
        else 0
    )
    hold_period_sec = (
        int(test_config.get("hold_period_min", 0))
        if test_config.get("hold_period_min")
        else 0
    )

    # Get total query count from statistics
    total_query_count = len([k for k in stats.keys() if k != "Total"]) if stats else 0

    # Extract concurrent threads
    concurrent_threads = (
        int(test_config.get("concurrent_threads", 0))
        if test_config.get("concurrent_threads")
        else extract_thread_count_from_run_type(run_type)
    )

    # Build metadata record
    return {
        # Run identifiers
        "run_id": run_id,
        "run_date": format_run_id_to_datetime(run_id),
        "s3_path": run_s3_path,
        "status": "completed",
        # Cluster configuration
        "cluster_hostname": test_result.get("cluster_hostname", "unknown"),
        "instance_type": cluster_config.get("instance_type", "unknown"),
        "estimated_cores": cluster_config.get("estimated_cores", 0),
        "executors": cluster_config.get("executors", 0),
        "cores_per_executor": cluster_config.get("cores_per_executor", 0),
        "serverless": cluster_config.get("serverless", "N") == "Y",
        # Test configuration
        "test_plan_file": test_config.get("test_plan_file", "unknown"),
        "concurrent_threads": concurrent_threads,
        "benchmark": benchmark,
        "total_query_count": total_query_count,
        "hold_period_sec": hold_period_sec,
        "ramp_up_time_sec": ramp_up_time_sec,
        "query_timeout_sec": int(test_config.get("query_timeout_sec", 0))
        if test_config.get("query_timeout_sec")
        else 0,
        "random_order": test_config.get("random_order", "false") == "true",
        # Run metadata
        "run_mode": test_result.get("run_mode", "test"),
        "customer": test_result.get("customer", "default"),
        "config": test_result.get("config", "default"),
        "tags": test_result.get("tags", ""),
        "comments": test_result.get("comments", ""),
        # Outlier detection (initialized as null, to be populated by analysis)
        "is_outlier": "no",
        "outlier_severity": None,
        "p90_z_score": None,
        "p90_deviation_pct": None,
        "p95_z_score": None,
        "p95_deviation_pct": None,
        # Partition fields (included in JSON for clarity, though they're also in S3 path)
        "engine": engine,
        "cluster_size": cluster_size,
    }


def generate_metadata_index(s3_path: str, output_dir: str = "/tmp/metadata") -> bool:
    """
    Generate metadata JSONL file for a given S3 path.

    Creates partitioned JSONL file: engine=X/cluster_size=Y/metadata.jsonl

    Args:
        s3_path: S3 path to run_type directory
        output_dir: Local output directory

    Returns:
        True if successful, False otherwise
    """
    print(f"📊 Generating metadata index for: {s3_path}")

    # Parse S3 path
    try:
        path_info = parse_s3_path(s3_path)
    except ValueError as e:
        print(f"❌ {e}")
        return False

    engine = path_info["engine"]
    cluster_size = path_info["cluster_size"]
    benchmark = path_info["benchmark"]
    run_type = path_info["run_type"]

    # List all run_ids
    run_ids = list_run_ids(s3_path)

    if not run_ids:
        print(f"⚠️  No run_ids found in {s3_path}")
        return False

    print(f"✓ Found {len(run_ids)} runs")

    # Create output directory with partitions
    partition_dir = (
        Path(output_dir) / f"engine={engine}" / f"cluster_size={cluster_size}"
    )
    partition_dir.mkdir(parents=True, exist_ok=True)

    # Output file: one JSONL per partition
    output_file = partition_dir / "metadata.jsonl"

    # Process each run and write to JSONL
    records_written = 0
    with open(output_file, "w") as f:
        for i, run_id in enumerate(run_ids, 1):
            print(
                f"  Processing run {i}/{len(run_ids)}: {run_id}...", end="", flush=True
            )

            # Load test_result.json
            test_result = load_test_result_from_s3(s3_path, run_id)
            if not test_result:
                print(" ⚠️  test_result.json not found")
                continue

            # Load statistics.json
            bucket = path_info["bucket"]
            path_base = s3_path.replace(f"s3://{bucket}/", "")
            stats_path = f"s3://{bucket}/{path_base}run_id={run_id}/statistics.json"
            stats = load_statistics_from_s3(stats_path)

            if not stats:
                print(" ⚠️  statistics.json not found")
                # Continue anyway - we can still extract metadata without stats
                stats = {}

            # Extract metadata record
            record = extract_metadata_record(
                test_result,
                stats,
                s3_path,
                run_id,
                engine,
                cluster_size,
                benchmark,
                run_type,
            )

            # Write as single-line JSON (JSONL format)
            f.write(json.dumps(record) + "\n")
            records_written += 1

            print(" ✓")

    print(f"\n✅ Successfully processed {records_written}/{len(run_ids)} runs")
    print(f"💾 Saved to: {output_file}")

    return records_written > 0


def main():
    parser = argparse.ArgumentParser(
        description="Generate metadata JSONL index for jmeter_run_metadata Athena table",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "s3_path",
        help="S3 path to run_type directory (e.g., s3://bucket/.../run_type=concurrency_8/)",
    )

    parser.add_argument(
        "--output",
        "-o",
        help="Output directory path (default: /tmp/metadata)",
        default="/tmp/metadata",
    )

    parser.add_argument(
        "--all-run-types",
        action="store_true",
        help="Generate indexes for all run_types under the given path (not yet implemented)",
    )

    args = parser.parse_args()

    # Generate metadata index
    success = generate_metadata_index(args.s3_path, args.output)

    if not success:
        sys.exit(1)

    print("\n" + "=" * 70)
    print("📈 METADATA INDEX COMPLETE")
    print("=" * 70)
    print(f"Output directory: {args.output}")
    print("\nNext steps:")
    print("1. Upload to S3:")
    print(f"   python utilities/athena/upload_metadata.py {args.output}")
    print("\n2. Repair partitions in Athena:")
    print("   aws athena start-query-execution \\")
    print("     --query-string 'MSCK REPAIR TABLE jmeter_run_metadata' \\")
    print("     --query-execution-context Database=default \\")
    print(
        "     --result-configuration OutputLocation=s3://your-s3-bucket/athena-query-results/"
    )
    print("=" * 70)


if __name__ == "__main__":
    main()
