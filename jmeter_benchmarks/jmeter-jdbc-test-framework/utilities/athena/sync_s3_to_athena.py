#!/usr/bin/env python3
"""
Automatically discover and sync all JMeter test runs from S3 to Athena.

This script:
1. Scans S3 for all test runs across all engines/clusters/benchmarks
2. Checks which runs are already in Athena
3. Uploads only the missing runs

Usage:
    # Sync all missing runs
    python utilities/sync_s3_to_athena.py

    # Dry run (show what would be uploaded)
    python utilities/sync_s3_to_athena.py --dry-run

    # Sync specific engine
    python utilities/sync_s3_to_athena.py --engine e6data

    # Force re-upload all (overwrites existing)
    python utilities/sync_s3_to_athena.py --force
"""

import argparse
import boto3
import os
import re
import sys
import subprocess
from typing import List, Set, Tuple, Dict
from collections import defaultdict


def get_s3_runs(bucket: str, prefix: str = 'jmeter-results/') -> List[Dict]:
    """
    Discover all test runs in S3.

    Returns:
        List of dicts with: engine, cluster_size, benchmark, run_type, run_id, s3_path
    """
    s3 = boto3.client('s3')
    runs = []

    print(f"🔍 Scanning S3 bucket: {bucket}/{prefix}")
    print("   This may take a moment...\n")

    # List all objects under prefix
    paginator = s3.get_paginator('list_objects_v2')

    for page in paginator.paginate(Bucket=bucket, Prefix=prefix, Delimiter=''):
        for obj in page.get('Contents', []):
            key = obj['Key']

            # Look for statistics.json files (primary indicator of a complete run)
            # Path format: engine=X/cluster_size=Y/benchmark=Z/run_type=W/run_id=YYYYMMDD-HHMMSS/statistics.json
            match = re.search(
                r'engine=([^/]+)/cluster_size=([^/]+)/benchmark=([^/]+)/run_type=([^/]+)/run_id=(\d{8}-\d{6})/statistics\.json',
                key
            )

            if match:
                engine = match.group(1)
                cluster = match.group(2)
                benchmark = match.group(3)
                run_type = match.group(4)
                run_id = match.group(5)

                runs.append({
                    'engine': engine,
                    'cluster_size': cluster,
                    'benchmark': benchmark,
                    'run_type': run_type,
                    'run_id': run_id,
                    's3_path': f"s3://{bucket}/{key.rsplit('/', 1)[0]}/"
                })

    return runs


def get_athena_runs(database: str = 'jmeter_analysis',
                    table: str = 'jmeter_runs_index',
                    region: str = 'us-east-1') -> Set[str]:
    """
    Get all run_ids currently in Athena.

    Returns:
        Set of run_ids
    """
    client = boto3.client('athena', region_name=region)

    query = f"SELECT DISTINCT run_id FROM {database}.{table}"

    response = client.start_query_execution(
        QueryString=query,
        QueryExecutionContext={'Database': database},
        ResultConfiguration={'OutputLocation': 's3://e6-jmeter/athena-results/'}
    )

    query_id = response['QueryExecutionId']

    # Wait for completion
    import time
    while True:
        response = client.get_query_execution(QueryExecutionId=query_id)
        status = response['QueryExecution']['Status']['State']

        if status == 'SUCCEEDED':
            break
        elif status in ['FAILED', 'CANCELLED']:
            print(f"❌ Athena query failed: {status}")
            return set()

        time.sleep(0.5)

    # Get results
    run_ids = set()
    paginator = client.get_paginator('get_query_results')

    for page in paginator.paginate(QueryExecutionId=query_id):
        for row in page['ResultSet']['Rows'][1:]:  # Skip header
            run_id = row['Data'][0].get('VarCharValue', '')
            if run_id:
                run_ids.add(run_id)

    return run_ids


def upload_run_to_athena(s3_path: str, dry_run: bool = False) -> bool:
    """Upload a single run to Athena using existing script."""

    if dry_run:
        print(f"   [DRY RUN] Would upload: {s3_path}")
        return True

    # Get script directory to build absolute path
    script_dir = os.path.dirname(os.path.abspath(__file__))
    upload_script = os.path.join(script_dir, 'upload_runs_index_to_athena.py')

    cmd = [
        'python',
        upload_script,
        '--from-s3',
        s3_path
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

        if result.returncode == 0:
            return True
        else:
            print(f"   ❌ Upload failed: {result.stderr}")
            return False

    except subprocess.TimeoutExpired:
        print(f"   ⏱️  Upload timed out")
        return False
    except Exception as e:
        print(f"   ❌ Upload error: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description='Automatically sync S3 test runs to Athena',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument(
        '--bucket',
        default='e6-jmeter',
        help='S3 bucket name (default: e6-jmeter)'
    )

    parser.add_argument(
        '--prefix',
        default='jmeter-results/',
        help='S3 prefix to scan (default: jmeter-results/)'
    )

    parser.add_argument(
        '--engine',
        help='Only sync specific engine (e6data, databricks, etc.)'
    )

    parser.add_argument(
        '--cluster',
        help='Only sync specific cluster size (S-2x2, M-4x4, etc.)'
    )

    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be uploaded without uploading'
    )

    parser.add_argument(
        '--force',
        action='store_true',
        help='Force re-upload even if already in Athena'
    )

    args = parser.parse_args()

    print("\n" + "="*80)
    print("S3 to Athena Sync Tool".center(80))
    print("="*80)
    print()

    # Step 1: Discover S3 runs
    s3_runs = get_s3_runs(args.bucket, args.prefix)

    if not s3_runs:
        print("❌ No runs found in S3")
        sys.exit(1)

    print(f"✓ Found {len(s3_runs)} total runs in S3\n")

    # Apply filters
    if args.engine:
        s3_runs = [r for r in s3_runs if r['engine'] == args.engine]
        print(f"   Filtered to engine={args.engine}: {len(s3_runs)} runs")

    if args.cluster:
        s3_runs = [r for r in s3_runs if r['cluster_size'] == args.cluster]
        print(f"   Filtered to cluster={args.cluster}: {len(s3_runs)} runs")

    if not s3_runs:
        print("❌ No runs match filters")
        sys.exit(1)

    # Step 2: Get existing Athena runs
    print("\n🔍 Checking existing runs in Athena...")
    athena_runs = get_athena_runs()
    print(f"✓ Found {len(athena_runs)} runs already in Athena\n")

    # Step 3: Find missing runs
    if args.force:
        missing_runs = s3_runs
        print(f"⚠️  FORCE mode: Will re-upload all {len(missing_runs)} runs\n")
    else:
        missing_runs = [r for r in s3_runs if r['run_id'] not in athena_runs]
        print(f"📊 Missing runs: {len(missing_runs)} (need to upload)\n")

    if not missing_runs:
        print("✅ All runs are already in Athena. Nothing to do!")
        sys.exit(0)

    # Organize by configuration
    by_config = defaultdict(list)
    for run in missing_runs:
        key = f"{run['engine']}/{run['cluster_size']}/{run['run_type']}"
        by_config[key].append(run)

    # Show summary
    print("="*80)
    print("MISSING RUNS BY CONFIGURATION")
    print("="*80)
    for config, runs in sorted(by_config.items()):
        print(f"  {config}: {len(runs)} runs")
    print("="*80)
    print()

    if args.dry_run:
        print("🔍 DRY RUN MODE - No uploads will be performed\n")
        for run in missing_runs:
            print(f"Would upload: {run['engine']}/{run['cluster_size']}/{run['run_type']}/{run['run_id']}")
        print(f"\nTotal: {len(missing_runs)} runs")
        sys.exit(0)

    # Step 4: Upload missing runs
    print("📤 Uploading missing runs to Athena...\n")

    success = 0
    failed = 0

    for i, run in enumerate(missing_runs, 1):
        print(f"[{i}/{len(missing_runs)}] {run['engine']}/{run['cluster_size']}/{run['run_type']}/{run['run_id']}")

        # Group by run_type path for upload
        s3_path = f"s3://{args.bucket}/jmeter-results/engine={run['engine']}/cluster_size={run['cluster_size']}/benchmark={run['benchmark']}/run_type={run['run_type']}/"

        if upload_run_to_athena(s3_path, dry_run=False):
            print(f"   ✅ Uploaded successfully")
            success += 1
        else:
            failed += 1

        print()

    # Summary
    print("="*80)
    print("SYNC COMPLETE")
    print("="*80)
    print(f"✅ Successfully uploaded: {success}")
    print(f"❌ Failed: {failed}")
    print(f"📊 Total in Athena (before): {len(athena_runs)}")
    print(f"📊 Total in Athena (after): {len(athena_runs) + success}")
    print("="*80)
    print()

    if success > 0:
        print("You can now query the updated data:")
        print("  python utilities/query_athena_runs.py")
        print("  python utilities/query_athena_runs.py --compare-engines")
        print("  python utilities/compare_runs_athena.py --engine e6data --cluster M-4x4")
        print()


if __name__ == '__main__':
    main()
