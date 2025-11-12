#!/usr/bin/env python3
"""
Query Athena runs index and display results in terminal.

Usage:
    # Show all runs
    python utilities/query_athena_runs.py

    # Show runs for specific engine
    python utilities/query_athena_runs.py --engine e6data

    # Show runs for specific cluster size
    python utilities/query_athena_runs.py --cluster M-4x4

    # Compare instance types
    python utilities/query_athena_runs.py --compare-instances

    # Compare performance across concurrency levels
    python utilities/query_athena_runs.py --compare-concurrency

    # Compare e6data vs Databricks
    python utilities/query_athena_runs.py --compare-engines

    # Compare e6data vs Databricks for specific configuration
    python utilities/query_athena_runs.py --compare-engines --cluster M-4x4 --run-type concurrency_2

    # Show how each instance performs at different concurrency
    python utilities/query_athena_runs.py --instance-by-concurrency

    # Analyze concurrency scaling
    python utilities/query_athena_runs.py --scaling-analysis

    # Analyze performance variance by configuration
    python utilities/query_athena_runs.py --variance-analysis

    # Custom SQL query
    python utilities/query_athena_runs.py --query "SELECT * FROM jmeter_analysis.jmeter_runs_index LIMIT 5"

    # Export to CSV for Excel/Google Sheets analysis
    python utilities/query_athena_runs.py --variance-analysis --csv > reports/variance_analysis.csv
    python utilities/query_athena_runs.py --compare-engines --csv > reports/engine_comparison.csv
"""

import argparse
import boto3
import time
import sys
import csv
from typing import List, Dict


def execute_athena_query(query: str, database: str = 'jmeter_analysis',
                         region: str = 'us-east-1',
                         output_location: str = 's3://e6-jmeter/athena-results/') -> List[Dict]:
    """Execute Athena query and return results."""

    client = boto3.client('athena', region_name=region)

    # Start query execution
    response = client.start_query_execution(
        QueryString=query,
        QueryExecutionContext={'Database': database},
        ResultConfiguration={'OutputLocation': output_location}
    )

    query_execution_id = response['QueryExecutionId']

    # Determine output stream based on format (stderr for CSV to keep stdout clean)
    out = sys.stderr if OUTPUT_FORMAT == 'csv' else sys.stdout

    print(f"Query ID: {query_execution_id}", file=out)
    print("Executing query...", end='', flush=True, file=out)

    # Wait for query to complete
    max_attempts = 30
    for attempt in range(max_attempts):
        response = client.get_query_execution(QueryExecutionId=query_execution_id)
        status = response['QueryExecution']['Status']['State']

        if status == 'SUCCEEDED':
            print(" ✅", file=out)
            break
        elif status in ['FAILED', 'CANCELLED']:
            reason = response['QueryExecution']['Status'].get('StateChangeReason', 'Unknown')
            print(f" ❌\nQuery {status}: {reason}", file=out)
            sys.exit(1)

        print(".", end='', flush=True, file=out)
        time.sleep(1)
    else:
        print(" ⏱️ Timeout", file=out)
        sys.exit(1)

    # Get query results
    results = []
    paginator = client.get_paginator('get_query_results')

    for page in paginator.paginate(QueryExecutionId=query_execution_id):
        for row in page['ResultSet']['Rows']:
            results.append([col.get('VarCharValue', '') for col in row['Data']])

    return results


# Global variable to hold output format
OUTPUT_FORMAT = 'table'  # Default to table format


def format_csv(results: List[List[str]]):
    """Format results as CSV."""
    if not results:
        print("No results found")
        return

    writer = csv.writer(sys.stdout)
    for row in results:
        writer.writerow(row)


def format_table(results: List[List[str]], title: str = None):
    """Format results as a nice table or CSV based on OUTPUT_FORMAT."""
    if not results:
        print("No results found")
        return

    # If CSV format requested, use CSV formatter
    if OUTPUT_FORMAT == 'csv':
        format_csv(results)
        return

    # Otherwise, use table format
    # First row is headers
    headers = results[0]
    data = results[1:]

    # Calculate column widths
    widths = [max(len(str(row[i])) for row in results) for i in range(len(headers))]

    # Print table
    total_width = sum(widths) + len(widths) * 3 + 1

    if title:
        print()
        print("=" * total_width)
        print(title.center(total_width))
        print("=" * total_width)

    print()

    # Print header
    header_line = " | ".join(str(headers[i]).ljust(widths[i]) for i in range(len(headers)))
    print(header_line)
    print("-" * total_width)

    # Print data rows
    for row in data:
        row_line = " | ".join(str(row[i]).ljust(widths[i]) for i in range(len(row)))
        print(row_line)

    print("=" * total_width)
    print(f"Total rows: {len(data)}")
    print("=" * total_width)
    print()


def query_all_runs(engine: str = None, cluster: str = None):
    """Query all runs with optional filters."""

    query = """
    SELECT
        engine,
        run_id,
        run_date,
        run_type,
        benchmark,
        cluster_size,
        instance_type,
        concurrent_threads,
        ROUND(p50_latency_sec, 2) as p50,
        ROUND(p90_latency_sec, 2) as p90,
        ROUND(p95_latency_sec, 2) as p95,
        ROUND(p99_latency_sec, 2) as p99,
        total_success,
        total_failed
    FROM jmeter_analysis.jmeter_runs_index
    WHERE 1=1
    """

    if engine:
        query += f" AND engine = '{engine}'"
    if cluster:
        query += f" AND cluster_size = '{cluster}'"

    query += " ORDER BY engine, run_date DESC LIMIT 50"

    results = execute_athena_query(query)
    format_table(results, "JMeter Test Runs")


def compare_instance_types():
    """Compare performance across instance types."""

    query = """
    SELECT
        engine,
        instance_type,
        cluster_size,
        COUNT(*) as runs,
        ROUND(AVG(avg_latency_sec), 2) as avg_time,
        ROUND(AVG(p50_latency_sec), 2) as avg_p50,
        ROUND(AVG(p90_latency_sec), 2) as avg_p90,
        ROUND(AVG(p95_latency_sec), 2) as avg_p95,
        ROUND(AVG(p99_latency_sec), 2) as avg_p99,
        SUM(total_success) as total_success,
        SUM(total_failed) as total_failed,
        ROUND(MIN(p50_latency_sec), 2) as best_p50,
        ROUND(MIN(p95_latency_sec), 2) as best_p95,
        ROUND(MAX(p50_latency_sec), 2) as worst_p50,
        ROUND(MAX(p95_latency_sec), 2) as worst_p95
    FROM jmeter_analysis.jmeter_runs_index
    WHERE instance_type != 'unknown'
    GROUP BY engine, instance_type, cluster_size
    ORDER BY engine, cluster_size, avg_p50
    """

    results = execute_athena_query(query)
    format_table(results, "Instance Type Performance Comparison")


def compare_cluster_sizes():
    """Compare performance across cluster sizes."""

    query = """
    SELECT
        engine,
        cluster_size,
        run_type,
        COUNT(*) as runs,
        ROUND(AVG(avg_latency_sec), 2) as avg_time,
        ROUND(AVG(p50_latency_sec), 2) as avg_p50,
        ROUND(AVG(p90_latency_sec), 2) as avg_p90,
        ROUND(AVG(p95_latency_sec), 2) as avg_p95,
        ROUND(AVG(p99_latency_sec), 2) as avg_p99,
        SUM(total_success) as total_success,
        SUM(total_failed) as total_failed,
        ROUND(AVG(queries_per_minute), 2) as avg_qpm,
        ROUND(AVG(error_rate_pct), 2) as avg_error_pct
    FROM jmeter_analysis.jmeter_runs_index
    GROUP BY engine, cluster_size, run_type
    ORDER BY engine, cluster_size, run_type
    """

    results = execute_athena_query(query)
    format_table(results, "Cluster Size Performance Comparison")


def show_slowest_queries():
    """Show slowest queries across all runs."""

    query = """
    SELECT
        slowest.query as query_name,
        ROUND(AVG(slowest.avg_sec), 2) as avg_time_sec,
        ROUND(MIN(slowest.avg_sec), 2) as min_time_sec,
        ROUND(MAX(slowest.avg_sec), 2) as max_time_sec,
        COUNT(*) as times_in_top3
    FROM jmeter_analysis.jmeter_runs_index
    CROSS JOIN UNNEST(top_slowest_queries) as t(slowest)
    WHERE engine = 'e6data'
    GROUP BY slowest.query
    ORDER BY avg_time_sec DESC
    LIMIT 20
    """

    results = execute_athena_query(query)
    format_table(results, "Slowest Queries Across All Runs")


def compare_concurrency_levels(instance_type: str = None):
    """Compare performance across different concurrency levels."""

    query = """
    SELECT
        engine,
        run_type,
        cluster_size,
        instance_type,
        COUNT(*) as runs,
        ROUND(AVG(avg_latency_sec), 2) as avg_time,
        ROUND(AVG(p50_latency_sec), 2) as avg_p50,
        ROUND(AVG(p90_latency_sec), 2) as avg_p90,
        ROUND(AVG(p95_latency_sec), 2) as avg_p95,
        ROUND(AVG(p99_latency_sec), 2) as avg_p99,
        SUM(total_success) as total_success,
        SUM(total_failed) as total_failed,
        ROUND(AVG(queries_per_minute), 2) as avg_qpm,
        ROUND(AVG(error_rate_pct), 2) as avg_error_pct
    FROM jmeter_analysis.jmeter_runs_index
    WHERE 1=1
    """

    if instance_type:
        query += f" AND instance_type = '{instance_type}'"

    query += """
    GROUP BY engine, run_type, cluster_size, instance_type
    ORDER BY engine, run_type, cluster_size, instance_type
    """

    results = execute_athena_query(query)
    title = f"Concurrency Performance Comparison"
    if instance_type:
        title += f" ({instance_type})"
    format_table(results, title)


def compare_engines(cluster_size: str = None, run_type: str = None):
    """Compare e6data vs Databricks performance."""

    query = """
    SELECT
        engine,
        cluster_size,
        run_type,
        instance_type,
        COUNT(*) as runs,
        ROUND(AVG(avg_latency_sec), 2) as avg_time,
        ROUND(AVG(p50_latency_sec), 2) as avg_p50,
        ROUND(AVG(p90_latency_sec), 2) as avg_p90,
        ROUND(AVG(p95_latency_sec), 2) as avg_p95,
        ROUND(AVG(p99_latency_sec), 2) as avg_p99,
        SUM(total_success) as total_success,
        SUM(total_failed) as total_failed,
        ROUND(AVG(queries_per_minute), 2) as avg_qpm
    FROM jmeter_analysis.jmeter_runs_index
    WHERE 1=1
    """

    if cluster_size:
        query += f" AND cluster_size = '{cluster_size}'"
    if run_type:
        query += f" AND run_type = '{run_type}'"

    query += """
    GROUP BY engine, cluster_size, run_type, instance_type
    ORDER BY cluster_size, run_type, engine, avg_p90
    """

    results = execute_athena_query(query)
    format_table(results, "Engine Performance Comparison (e6data vs Databricks)")


def instance_by_concurrency():
    """Show how each instance type performs at different concurrency levels."""

    query = """
    SELECT
        engine,
        instance_type,
        run_type,
        cluster_size,
        COUNT(*) as runs,
        ROUND(AVG(avg_latency_sec), 2) as avg_time,
        ROUND(AVG(p50_latency_sec), 2) as avg_p50,
        ROUND(AVG(p90_latency_sec), 2) as avg_p90,
        ROUND(AVG(p95_latency_sec), 2) as avg_p95,
        ROUND(AVG(p99_latency_sec), 2) as avg_p99,
        SUM(total_success) as total_success,
        SUM(total_failed) as total_failed,
        ROUND(AVG(queries_per_minute), 2) as avg_qpm
    FROM jmeter_analysis.jmeter_runs_index
    WHERE instance_type != 'unknown'
    GROUP BY engine, instance_type, run_type, cluster_size
    ORDER BY engine, instance_type, run_type
    """

    results = execute_athena_query(query)
    format_table(results, "Instance Type Performance by Concurrency Level")


def concurrency_scaling_analysis():
    """Analyze how performance scales with concurrency."""

    query = """
    WITH concurrency_nums AS (
        SELECT
            engine,
            CAST(REGEXP_EXTRACT(run_type, 'concurrency_(\\d+)', 1) AS INTEGER) as concurrency,
            run_type,
            cluster_size,
            instance_type,
            ROUND(AVG(avg_latency_sec), 2) as avg_time,
            ROUND(AVG(p50_latency_sec), 2) as avg_p50,
            ROUND(AVG(p90_latency_sec), 2) as avg_p90,
            ROUND(AVG(p95_latency_sec), 2) as avg_p95,
            ROUND(AVG(p99_latency_sec), 2) as avg_p99,
            SUM(total_success) as total_success,
            SUM(total_failed) as total_failed,
            ROUND(AVG(queries_per_minute), 2) as avg_qpm
        FROM jmeter_analysis.jmeter_runs_index
        WHERE run_type LIKE 'concurrency_%'
        GROUP BY engine, run_type, cluster_size, instance_type
    )
    SELECT
        engine,
        concurrency,
        cluster_size,
        instance_type,
        avg_time,
        avg_p50,
        avg_p90,
        avg_p95,
        avg_p99,
        total_success,
        total_failed,
        avg_qpm,
        ROUND(avg_qpm / concurrency, 2) as qpm_per_thread
    FROM concurrency_nums
    ORDER BY engine, cluster_size, concurrency, instance_type
    """

    results = execute_athena_query(query)
    format_table(results, "Concurrency Scaling Analysis (Performance vs Load)")


def variance_analysis():
    """
    Analyze performance variance within each configuration.

    Helps identify genuine performance issues vs expected variations.
    Low coefficient of variation (CV) = consistent performance.
    High CV = high variance (potential issues to investigate).
    """

    query = """
    SELECT
        engine,
        benchmark,
        cluster_size,
        run_type,
        instance_type,
        COUNT(*) as num_runs,
        ROUND(AVG(p90_latency_sec), 2) as avg_p90,
        ROUND(MIN(p90_latency_sec), 2) as min_p90,
        ROUND(MAX(p90_latency_sec), 2) as max_p90,
        ROUND(STDDEV(p90_latency_sec), 2) as stddev_p90,
        ROUND((STDDEV(p90_latency_sec) / NULLIF(AVG(p90_latency_sec), 0)) * 100, 1) as cv_p90_pct,
        ROUND(AVG(p95_latency_sec), 2) as avg_p95,
        ROUND(MIN(p95_latency_sec), 2) as min_p95,
        ROUND(MAX(p95_latency_sec), 2) as max_p95,
        ROUND(STDDEV(p95_latency_sec), 2) as stddev_p95,
        ROUND((STDDEV(p95_latency_sec) / NULLIF(AVG(p95_latency_sec), 0)) * 100, 1) as cv_p95_pct,
        CASE
            WHEN COUNT(*) < 2 THEN 'Insufficient data'
            WHEN (STDDEV(p90_latency_sec) / NULLIF(AVG(p90_latency_sec), 0)) * 100 < 5 THEN 'Excellent (CV < 5%)'
            WHEN (STDDEV(p90_latency_sec) / NULLIF(AVG(p90_latency_sec), 0)) * 100 < 10 THEN 'Good (CV < 10%)'
            WHEN (STDDEV(p90_latency_sec) / NULLIF(AVG(p90_latency_sec), 0)) * 100 < 20 THEN 'Moderate (CV < 20%)'
            ELSE 'High variance - investigate'
        END as consistency_rating,
        CONCAT('s3://e6-jmeter/jmeter-results/engine=', engine, '/cluster_size=', cluster_size, '/benchmark=', benchmark, '/run_type=', run_type, '/') as s3_path
    FROM jmeter_analysis.jmeter_runs_index
    GROUP BY engine, benchmark, cluster_size, run_type, instance_type
    HAVING COUNT(*) >= 1
    ORDER BY cv_p90_pct DESC NULLS LAST, engine, cluster_size, run_type
    """

    results = execute_athena_query(query)
    format_table(results, "Performance Variance Analysis by Configuration")


def outlier_detection():
    """Detect outlier runs that deviate significantly from their group average."""
    query = """
    WITH group_stats AS (
        SELECT
            engine,
            benchmark,
            cluster_size,
            run_type,
            instance_type,
            AVG(p90_latency_sec) as avg_p90,
            STDDEV(p90_latency_sec) as stddev_p90,
            AVG(p95_latency_sec) as avg_p95,
            STDDEV(p95_latency_sec) as stddev_p95,
            COUNT(*) as total_runs
        FROM jmeter_analysis.jmeter_runs_index
        GROUP BY engine, benchmark, cluster_size, run_type, instance_type
        HAVING COUNT(*) >= 2
    ),
    run_deviations AS (
        SELECT
            r.engine,
            r.benchmark,
            r.cluster_size,
            r.run_type,
            r.instance_type,
            r.run_id,
            r.p90_latency_sec,
            r.p95_latency_sec,
            g.avg_p90,
            g.stddev_p90,
            g.avg_p95,
            g.stddev_p95,
            g.total_runs,
            ROUND(((r.p90_latency_sec - g.avg_p90) / NULLIF(g.avg_p90, 0)) * 100, 1) as p90_deviation_pct,
            ROUND(((r.p95_latency_sec - g.avg_p95) / NULLIF(g.avg_p95, 0)) * 100, 1) as p95_deviation_pct,
            ROUND((r.p90_latency_sec - g.avg_p90) / NULLIF(g.stddev_p90, 0), 2) as p90_z_score,
            ROUND((r.p95_latency_sec - g.avg_p95) / NULLIF(g.stddev_p95, 0), 2) as p95_z_score,
            CONCAT('s3://e6-jmeter/jmeter-results/engine=', r.engine,
                   '/cluster_size=', r.cluster_size,
                   '/benchmark=', r.benchmark,
                   '/run_type=', r.run_type,
                   '/run_id=', r.run_id, '/') as s3_path
        FROM jmeter_analysis.jmeter_runs_index r
        INNER JOIN group_stats g
            ON r.engine = g.engine
            AND r.benchmark = g.benchmark
            AND r.cluster_size = g.cluster_size
            AND r.run_type = g.run_type
            AND r.instance_type = g.instance_type
    )
    SELECT
        engine,
        benchmark,
        cluster_size,
        run_type,
        instance_type,
        run_id,
        p90_latency_sec,
        avg_p90,
        p90_deviation_pct,
        p90_z_score,
        p95_latency_sec,
        avg_p95,
        p95_deviation_pct,
        p95_z_score,
        total_runs,
        CASE
            WHEN ABS(p90_z_score) > 2 THEN 'SEVERE - Z>2'
            WHEN p90_deviation_pct > 50 THEN 'HIGH - >50% worse'
            WHEN p90_deviation_pct > 25 THEN 'MODERATE - >25% worse'
            WHEN p90_deviation_pct < -15 THEN 'SUSPICIOUSLY GOOD'
            ELSE 'NORMAL'
        END as outlier_severity,
        s3_path
    FROM run_deviations
    WHERE ABS(p90_z_score) > 1.5 OR ABS(p90_deviation_pct) > 20
    ORDER BY ABS(p90_z_score) DESC, p90_deviation_pct DESC
    """

    results = execute_athena_query(query)
    format_table(results, "Outlier Detection - Runs Deviating from Group Average")


def best_runs_comparison():
    """Compare only the best performing run from each unique configuration."""
    query = """
    WITH ranked_runs AS (
        SELECT
            engine,
            benchmark,
            cluster_size,
            run_type,
            instance_type,
            run_id,
            avg_latency_sec,
            p50_latency_sec,
            p90_latency_sec,
            p95_latency_sec,
            p99_latency_sec,
            total_success,
            total_failed,
            ROW_NUMBER() OVER (
                PARTITION BY engine, benchmark, cluster_size, run_type, instance_type
                ORDER BY p90_latency_sec ASC
            ) as rank,
            CONCAT('s3://e6-jmeter/jmeter-results/engine=', engine,
                   '/cluster_size=', cluster_size,
                   '/benchmark=', benchmark,
                   '/run_type=', run_type,
                   '/run_id=', run_id, '/') as s3_path
        FROM jmeter_analysis.jmeter_runs_index
        WHERE total_success > 0
    )
    SELECT
        engine,
        benchmark,
        cluster_size,
        run_type,
        instance_type,
        run_id as best_run_id,
        ROUND(avg_latency_sec, 2) as avg_time,
        ROUND(p50_latency_sec, 2) as p50,
        ROUND(p90_latency_sec, 2) as p90,
        ROUND(p95_latency_sec, 2) as p95,
        ROUND(p99_latency_sec, 2) as p99,
        total_success,
        total_failed,
        ROUND((total_failed * 100.0) / NULLIF(total_success + total_failed, 0), 2) as error_pct,
        s3_path
    FROM ranked_runs
    WHERE rank = 1
    ORDER BY engine, cluster_size, run_type, instance_type
    """

    results = execute_athena_query(query)
    format_table(results, "Best Runs Comparison - Top Performing Run from Each Configuration")


def main():
    parser = argparse.ArgumentParser(
        description='Query Athena runs index from command line',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument(
        '--engine',
        help='Filter by engine (e6data, databricks, etc.)',
        choices=['e6data', 'databricks', 'trino', 'presto', 'athena']
    )

    parser.add_argument(
        '--cluster',
        help='Filter by cluster size (S-2x2, M-4x4, etc.)'
    )

    parser.add_argument(
        '--compare-instances',
        action='store_true',
        help='Compare instance types'
    )

    parser.add_argument(
        '--compare-clusters',
        action='store_true',
        help='Compare cluster sizes'
    )

    parser.add_argument(
        '--slowest-queries',
        action='store_true',
        help='Show slowest queries'
    )

    parser.add_argument(
        '--compare-concurrency',
        action='store_true',
        help='Compare performance across concurrency levels'
    )

    parser.add_argument(
        '--compare-engines',
        action='store_true',
        help='Compare e6data vs Databricks performance'
    )

    parser.add_argument(
        '--instance-by-concurrency',
        action='store_true',
        help='Show how each instance performs at different concurrency'
    )

    parser.add_argument(
        '--scaling-analysis',
        action='store_true',
        help='Analyze how performance scales with concurrency'
    )

    parser.add_argument(
        '--variance-analysis',
        action='store_true',
        help='Analyze performance variance within each configuration'
    )

    parser.add_argument(
        '--outlier-detection',
        action='store_true',
        help='Detect outlier runs that deviate significantly from their group average'
    )

    parser.add_argument(
        '--best-runs',
        action='store_true',
        help='Compare only the best performing run from each unique configuration'
    )

    parser.add_argument(
        '--instance-type',
        help='Filter by specific instance type (e.g., r6id.8xlarge)'
    )

    parser.add_argument(
        '--run-type',
        help='Filter by run type (e.g., concurrency_2)'
    )

    parser.add_argument(
        '--query',
        help='Execute custom SQL query'
    )

    parser.add_argument(
        '--region',
        help='AWS region (default: us-east-1)',
        default='us-east-1'
    )

    parser.add_argument(
        '--csv',
        action='store_true',
        help='Output results in CSV format for Excel/Google Sheets'
    )

    args = parser.parse_args()

    # Set output format based on CSV flag
    if args.csv:
        global OUTPUT_FORMAT
        OUTPUT_FORMAT = 'csv'

    try:
        if args.query:
            results = execute_athena_query(args.query, region=args.region)
            format_table(results, "Custom Query Results")
        elif args.compare_instances:
            compare_instance_types()
        elif args.compare_clusters:
            compare_cluster_sizes()
        elif args.slowest_queries:
            show_slowest_queries()
        elif args.compare_concurrency:
            compare_concurrency_levels(instance_type=args.instance_type)
        elif args.compare_engines:
            compare_engines(cluster_size=args.cluster, run_type=args.run_type)
        elif args.instance_by_concurrency:
            instance_by_concurrency()
        elif args.scaling_analysis:
            concurrency_scaling_analysis()
        elif args.variance_analysis:
            variance_analysis()
        elif args.outlier_detection:
            outlier_detection()
        elif args.best_runs:
            best_runs_comparison()
        else:
            query_all_runs(engine=args.engine, cluster=args.cluster)

    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
