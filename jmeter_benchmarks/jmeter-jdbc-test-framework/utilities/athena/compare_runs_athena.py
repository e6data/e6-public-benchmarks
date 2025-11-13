#!/usr/bin/env python3
"""
Compare JMeter test runs using Athena (simpler and faster than S3 direct access).

Usage:
    # Compare last 2 runs (no filter)
    python utilities/compare_runs_athena.py

    # Compare last 2 runs for specific configuration
    python utilities/compare_runs_athena.py --engine e6data --cluster M-4x4 --instance r7iz.8xlarge --run-type concurrency_4

    # Compare specific run IDs
    python utilities/compare_runs_athena.py --run1 20251102-114826 --run2 20251102-111225

    # Compare best (lowest p90) vs latest
    python utilities/compare_runs_athena.py --engine e6data --cluster M-4x4 --best-vs-latest
"""

import argparse
import boto3
import sys
import time
from typing import List, Dict, Tuple


def execute_athena_query(query: str, database: str = 'jmeter_analysis',
                         region: str = 'us-east-1',
                         output_location: str = 's3://e6-jmeter/athena-results/') -> List[List[str]]:
    """Execute Athena query and return results."""

    client = boto3.client('athena', region_name=region)

    response = client.start_query_execution(
        QueryString=query,
        QueryExecutionContext={'Database': database},
        ResultConfiguration={'OutputLocation': output_location}
    )

    query_execution_id = response['QueryExecutionId']
    print(f"Query ID: {query_execution_id}")
    print("Executing query...", end='', flush=True)

    # Wait for query to complete
    max_attempts = 30
    for attempt in range(max_attempts):
        response = client.get_query_execution(QueryExecutionId=query_execution_id)
        status = response['QueryExecution']['Status']['State']

        if status == 'SUCCEEDED':
            print(" ✅")
            break
        elif status in ['FAILED', 'CANCELLED']:
            reason = response['QueryExecution']['Status'].get('StateChangeReason', 'Unknown')
            print(f" ❌\nQuery {status}: {reason}")
            sys.exit(1)

        print(".", end='', flush=True)
        time.sleep(1)
    else:
        print(" ⏱️ Timeout")
        sys.exit(1)

    # Get query results
    results = []
    paginator = client.get_paginator('get_query_results')

    for page in paginator.paginate(QueryExecutionId=query_execution_id):
        for row in page['ResultSet']['Rows']:
            results.append([col.get('VarCharValue', '') for col in row['Data']])

    return results


def get_runs_by_ids(run1: str, run2: str) -> Tuple[Dict, Dict]:
    """Get two runs by their run IDs."""

    query = f"""
    SELECT
        run_id,
        run_date,
        engine,
        cluster_size,
        instance_type,
        run_type,
        concurrent_threads,
        ROUND(avg_latency_sec, 2) as avg_latency_sec,
        ROUND(p50_latency_sec, 2) as p50_latency_sec,
        ROUND(p90_latency_sec, 2) as p90_latency_sec,
        ROUND(p95_latency_sec, 2) as p95_latency_sec,
        ROUND(p99_latency_sec, 2) as p99_latency_sec,
        ROUND(max_latency_sec, 2) as max_latency_sec,
        total_success,
        total_failed,
        ROUND(queries_per_minute, 2) as queries_per_minute,
        ROUND(error_rate_pct, 2) as error_rate_pct
    FROM jmeter_analysis.jmeter_runs_index
    WHERE run_id IN ('{run1}', '{run2}')
    ORDER BY run_id
    """

    results = execute_athena_query(query)

    if len(results) < 3:  # Header + 2 rows
        print(f"❌ Error: Could not find both runs. Found {len(results)-1} runs.")
        sys.exit(1)

    headers = results[0]
    run1_data = dict(zip(headers, results[1]))
    run2_data = dict(zip(headers, results[2]))

    return run1_data, run2_data


def get_last_n_runs(engine: str = None, cluster: str = None, instance: str = None,
                     run_type: str = None, n: int = 2) -> List[Dict]:
    """Get last N runs matching filter."""

    query = """
    SELECT
        run_id,
        run_date,
        engine,
        cluster_size,
        instance_type,
        run_type,
        concurrent_threads,
        ROUND(avg_latency_sec, 2) as avg_latency_sec,
        ROUND(p50_latency_sec, 2) as p50_latency_sec,
        ROUND(p90_latency_sec, 2) as p90_latency_sec,
        ROUND(p95_latency_sec, 2) as p95_latency_sec,
        ROUND(p99_latency_sec, 2) as p99_latency_sec,
        ROUND(max_latency_sec, 2) as max_latency_sec,
        total_success,
        total_failed,
        ROUND(queries_per_minute, 2) as queries_per_minute,
        ROUND(error_rate_pct, 2) as error_rate_pct
    FROM jmeter_analysis.jmeter_runs_index
    WHERE 1=1
    """

    if engine:
        query += f" AND engine = '{engine}'"
    if cluster:
        query += f" AND cluster_size = '{cluster}'"
    if instance:
        query += f" AND instance_type = '{instance}'"
    if run_type:
        query += f" AND run_type = '{run_type}'"

    query += f" ORDER BY run_date DESC LIMIT {n}"

    results = execute_athena_query(query)

    if len(results) < n + 1:
        print(f"❌ Error: Found only {len(results)-1} runs matching filter. Need at least {n}.")
        sys.exit(1)

    headers = results[0]
    runs = [dict(zip(headers, row)) for row in results[1:]]

    return runs


def get_best_and_latest(engine: str = None, cluster: str = None, instance: str = None,
                        run_type: str = None) -> Tuple[Dict, Dict]:
    """Get best (by p90) and latest run."""

    # Get latest
    latest_query = """
    SELECT
        run_id,
        run_date,
        engine,
        cluster_size,
        instance_type,
        run_type,
        concurrent_threads,
        ROUND(avg_latency_sec, 2) as avg_latency_sec,
        ROUND(p50_latency_sec, 2) as p50_latency_sec,
        ROUND(p90_latency_sec, 2) as p90_latency_sec,
        ROUND(p95_latency_sec, 2) as p95_latency_sec,
        ROUND(p99_latency_sec, 2) as p99_latency_sec,
        ROUND(max_latency_sec, 2) as max_latency_sec,
        total_success,
        total_failed,
        ROUND(queries_per_minute, 2) as queries_per_minute,
        ROUND(error_rate_pct, 2) as error_rate_pct
    FROM jmeter_analysis.jmeter_runs_index
    WHERE 1=1
    """

    if engine:
        latest_query += f" AND engine = '{engine}'"
    if cluster:
        latest_query += f" AND cluster_size = '{cluster}'"
    if instance:
        latest_query += f" AND instance_type = '{instance}'"
    if run_type:
        latest_query += f" AND run_type = '{run_type}'"

    latest_query += " ORDER BY run_date DESC LIMIT 1"

    # Get best
    best_query = latest_query.replace("ORDER BY run_date DESC", "ORDER BY p90_latency_sec ASC")

    print("Finding latest run...")
    latest_results = execute_athena_query(latest_query)

    print("Finding best run (lowest p90)...")
    best_results = execute_athena_query(best_query)

    if len(latest_results) < 2 or len(best_results) < 2:
        print("❌ Error: Could not find runs matching filter.")
        sys.exit(1)

    headers = latest_results[0]
    latest_run = dict(zip(headers, latest_results[1]))
    best_run = dict(zip(headers, best_results[1]))

    return best_run, latest_run


def compare_runs(run1: Dict, run2: Dict, label1: str = "Run 1", label2: str = "Run 2"):
    """Compare two runs and display results."""

    print("\n" + "="*130)
    print(f"RUN COMPARISON: {label1} vs {label2}".center(130))
    print("="*130)
    print()

    # Basic info
    print(f"{'Metric':<30} | {label1:<45} | {label2:<45}")
    print("-"*130)

    print(f"{'Run ID':<30} | {run1['run_id']:<45} | {run2['run_id']:<45}")
    print(f"{'Run Date':<30} | {run1['run_date']:<45} | {run2['run_date']:<45}")
    print(f"{'Engine':<30} | {run1['engine']:<45} | {run2['engine']:<45}")
    print(f"{'Cluster Size':<30} | {run1['cluster_size']:<45} | {run2['cluster_size']:<45}")
    print(f"{'Instance Type':<30} | {run1['instance_type']:<45} | {run2['instance_type']:<45}")
    print(f"{'Run Type':<30} | {run1['run_type']:<45} | {run2['run_type']:<45}")
    print(f"{'Concurrent Threads':<30} | {run1['concurrent_threads']:<45} | {run2['concurrent_threads']:<45}")

    print("\n" + "-"*130)
    print("PERFORMANCE METRICS".center(130))
    print("-"*130)

    def format_metric(val1, val2):
        """Format metric with comparison indicator."""
        try:
            v1 = float(val1)
            v2 = float(val2)
            diff = v2 - v1
            pct = (diff / v1 * 100) if v1 != 0 else 0

            if abs(pct) < 1:
                indicator = "≈ (same)"
            elif v2 < v1:
                indicator = f"⬇️  {abs(pct):.1f}% faster"
            else:
                indicator = f"⬆️  {abs(pct):.1f}% slower"

            return f"{v1:.2f}s", f"{v2:.2f}s", indicator
        except:
            return str(val1), str(val2), ""

    metrics = [
        ('Average Latency', 'avg_latency_sec'),
        ('P50 Latency (Median)', 'p50_latency_sec'),
        ('P90 Latency', 'p90_latency_sec'),
        ('P95 Latency', 'p95_latency_sec'),
        ('P99 Latency', 'p99_latency_sec'),
        ('Max Latency', 'max_latency_sec'),
    ]

    for label, key in metrics:
        v1, v2, indicator = format_metric(run1.get(key, '0'), run2.get(key, '0'))
        print(f"{label:<30} | {v1:<45} | {v2:<25} {indicator}")

    print("\n" + "-"*130)
    print("SUCCESS/FAILURE METRICS".center(130))
    print("-"*130)

    print(f"{'Total Success':<30} | {run1['total_success']:<45} | {run2['total_success']:<45}")
    print(f"{'Total Failed':<30} | {run1['total_failed']:<45} | {run2['total_failed']:<45}")
    print(f"{'Error Rate %':<30} | {run1['error_rate_pct']:<45} | {run2['error_rate_pct']:<45}")
    print(f"{'Queries Per Minute':<30} | {run1['queries_per_minute']:<45} | {run2['queries_per_minute']:<45}")

    print("="*130)
    print()


def main():
    parser = argparse.ArgumentParser(
        description='Compare JMeter test runs from Athena',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument('--run1', help='First run ID to compare')
    parser.add_argument('--run2', help='Second run ID to compare')

    parser.add_argument('--best-vs-latest', action='store_true',
                       help='Compare best (lowest p90) vs latest run')

    parser.add_argument('--engine', help='Filter by engine (e6data, databricks)')
    parser.add_argument('--cluster', help='Filter by cluster size (S-2x2, M-4x4, etc.)')
    parser.add_argument('--instance', help='Filter by instance type (r6id.8xlarge, r7iz.8xlarge)')
    parser.add_argument('--run-type', help='Filter by run type (concurrency_2, etc.)')

    args = parser.parse_args()

    try:
        if args.run1 and args.run2:
            # Compare specific runs
            print(f"\n🔍 Comparing specific runs: {args.run1} vs {args.run2}")
            run1, run2 = get_runs_by_ids(args.run1, args.run2)
            compare_runs(run1, run2, f"Run 1 ({args.run1})", f"Run 2 ({args.run2})")

        elif args.best_vs_latest:
            # Compare best vs latest
            filter_desc = []
            if args.engine:
                filter_desc.append(f"engine={args.engine}")
            if args.cluster:
                filter_desc.append(f"cluster={args.cluster}")
            if args.instance:
                filter_desc.append(f"instance={args.instance}")
            if args.run_type:
                filter_desc.append(f"run_type={args.run_type}")

            filter_str = ", ".join(filter_desc) if filter_desc else "no filters"
            print(f"\n🔍 Finding best vs latest run ({filter_str})...")

            best, latest = get_best_and_latest(
                engine=args.engine,
                cluster=args.cluster,
                instance=args.instance,
                run_type=args.run_type
            )
            compare_runs(best, latest, f"BEST ({best['run_id']})", f"LATEST ({latest['run_id']})")

        else:
            # Compare last 2 runs (default)
            filter_desc = []
            if args.engine:
                filter_desc.append(f"engine={args.engine}")
            if args.cluster:
                filter_desc.append(f"cluster={args.cluster}")
            if args.instance:
                filter_desc.append(f"instance={args.instance}")
            if args.run_type:
                filter_desc.append(f"run_type={args.run_type}")

            filter_str = ", ".join(filter_desc) if filter_desc else "no filters"
            print(f"\n🔍 Finding last 2 runs ({filter_str})...")

            runs = get_last_n_runs(
                engine=args.engine,
                cluster=args.cluster,
                instance=args.instance,
                run_type=args.run_type,
                n=2
            )
            compare_runs(runs[1], runs[0], f"2nd Latest ({runs[1]['run_id']})", f"Latest ({runs[0]['run_id']})")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
