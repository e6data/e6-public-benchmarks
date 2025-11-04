#!/usr/bin/env python3
"""
Summarize JMeter test results across multiple concurrency levels.

This script analyzes performance metrics for different concurrency levels
within a specific engine/cluster_size/benchmark configuration.

Usage:
    python utilities/summarize_concurrency_runs.py \
        --engine dbr \
        --cluster-size M \
        --benchmark tpcds_29_1tb

    python utilities/summarize_concurrency_runs.py \
        --engine e6data \
        --cluster-size M \
        --benchmark tpcds_29_1tb \
        --format markdown > summary.md
"""

import json
import subprocess
import sys
import argparse
from pathlib import Path
from typing import Dict, List, Tuple
import re


def run_command(cmd: List[str]) -> Tuple[str, int]:
    """Run shell command and return output."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return result.stdout, 0
    except subprocess.CalledProcessError as e:
        return e.stderr, e.returncode


def list_s3_runs(engine: str, cluster_size: str, benchmark: str) -> Dict[int, str]:
    """List all test result files grouped by concurrency level."""
    s3_base = f"s3://e6-jmeter/jmeter-results/engine={engine}/cluster_size={cluster_size}/benchmark={benchmark}/"

    # List all directories under the base path
    cmd = ["aws", "s3", "ls", s3_base]
    output, code = run_command(cmd)

    if code != 0:
        print(f"Error listing S3 path: {s3_base}", file=sys.stderr)
        return {}

    # Find all run_type directories (e.g., concurrency_2, concurrency_4)
    concurrency_runs = {}
    for line in output.strip().split('\n'):
        if 'run_type=' in line:
            match = re.search(r'run_type=concurrency_(\d+)', line)
            if match:
                concurrency = int(match.group(1))
                # Find the latest test_result file for this concurrency
                run_path = f"{s3_base}run_type=concurrency_{concurrency}/"
                cmd = ["aws", "s3", "ls", run_path, "--recursive"]
                files_output, _ = run_command(cmd)

                # Find the most recent test_result file
                test_results = [line for line in files_output.strip().split('\n')
                               if 'test_result_' in line and line.endswith('.json')]
                if test_results:
                    # Get the last (most recent) file
                    latest = test_results[-1].strip().split()[-1]
                    concurrency_runs[concurrency] = f"s3://e6-jmeter/{latest}"

    return concurrency_runs


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


def extract_metrics(test_data: Dict) -> Dict:
    """Extract key metrics from test result."""
    perf = test_data.get('performance_metrics', {})
    test_res = test_data.get('test_results', {})
    timing = test_data.get('timing_distribution', {})

    return {
        'run_id': test_data.get('run_id', 'unknown'),
        'total_queries': test_data.get('query_statistics', {}).get('total_queries', 0),
        'avg_time_sec': perf.get('avg_time_sec', 0),
        'median_time_sec': perf.get('median_time_sec', 0),
        'p90_latency_sec': perf.get('p90_latency_sec', 0),
        'p95_latency_sec': perf.get('p95_latency_sec', 0),
        'p99_latency_sec': perf.get('p99_latency_sec', 0),
        'min_time_sec': perf.get('min_time_sec', 0),
        'max_time_sec': perf.get('max_time_sec', 0),
        'throughput': perf.get('throughput', 0),
        'total_time_sec': perf.get('total_time_taken_sec', 0),
        'success_rate': 100 - test_res.get('error_percent', 0),
        'error_count': test_res.get('total_failed', 0),
        'queries_1_5sec': timing.get('queries_1_to_5sec', 0),
        'queries_5_10sec': timing.get('queries_5_to_10sec', 0),
        'queries_over_10sec': timing.get('queries_over_10sec', 0),
        'cluster_config': test_data.get('cluster_config', {}),
        'test_config': test_data.get('test_execution_config', {})
    }


def format_text_output(engine: str, cluster_size: str, benchmark: str,
                       summaries: Dict[int, Dict]) -> str:
    """Format output as text table."""
    output = []
    output.append("=" * 120)
    output.append(f"CONCURRENCY SCALING ANALYSIS - {engine.upper()}")
    output.append("=" * 120)
    output.append(f"Cluster Size: {cluster_size}")
    output.append(f"Benchmark: {benchmark}")
    output.append(f"Concurrency Levels: {', '.join(map(str, sorted(summaries.keys())))}")
    output.append("")

    # Performance Summary Table
    output.append("-" * 120)
    output.append("PERFORMANCE METRICS BY CONCURRENCY")
    output.append("-" * 120)
    output.append(f"{'Metric':<30} " + " ".join(f"{'C=' + str(c):>12}" for c in sorted(summaries.keys())))
    output.append("-" * 120)

    metrics = [
        ('Avg Response (sec)', 'avg_time_sec', '{:.2f}'),
        ('Median p50 (sec)', 'median_time_sec', '{:.2f}'),
        ('p90 Latency (sec)', 'p90_latency_sec', '{:.2f}'),
        ('p95 Latency (sec)', 'p95_latency_sec', '{:.2f}'),
        ('p99 Latency (sec)', 'p99_latency_sec', '{:.2f}'),
        ('Min Response (sec)', 'min_time_sec', '{:.2f}'),
        ('Max Response (sec)', 'max_time_sec', '{:.2f}'),
        ('Throughput (q/s)', 'throughput', '{:.2f}'),
        ('Total Time (sec)', 'total_time_sec', '{:.2f}'),
        ('Success Rate (%)', 'success_rate', '{:.1f}'),
        ('Error Count', 'error_count', '{:.0f}'),
    ]

    for label, key, fmt in metrics:
        values = [fmt.format(summaries[c][key]) for c in sorted(summaries.keys())]
        output.append(f"{label:<30} " + " ".join(f"{v:>12}" for v in values))

    output.append("")

    # Query Distribution
    output.append("-" * 120)
    output.append("QUERY EXECUTION TIME DISTRIBUTION")
    output.append("-" * 120)

    for c in sorted(summaries.keys()):
        s = summaries[c]
        total = s['total_queries']
        output.append(f"Concurrency {c}:")
        output.append(f"  1-5s:   {s['queries_1_5sec']:3d} queries ({s['queries_1_5sec']/total*100:5.1f}%)")
        output.append(f"  5-10s:  {s['queries_5_10sec']:3d} queries ({s['queries_5_10sec']/total*100:5.1f}%)")
        output.append(f"  >10s:   {s['queries_over_10sec']:3d} queries ({s['queries_over_10sec']/total*100:5.1f}%)")
        output.append("")

    # Scaling Analysis
    output.append("-" * 120)
    output.append("SCALING EFFICIENCY ANALYSIS")
    output.append("-" * 120)

    sorted_concurrencies = sorted(summaries.keys())
    if len(sorted_concurrencies) > 1:
        baseline_c = sorted_concurrencies[0]
        baseline_throughput = summaries[baseline_c]['throughput']

        output.append(f"{'Concurrency':<15} {'Throughput':>15} {'Scaling Factor':>18} {'Efficiency':>15}")
        output.append("-" * 120)

        for c in sorted_concurrencies:
            throughput = summaries[c]['throughput']
            scaling_factor = c / baseline_c
            actual_scaling = throughput / baseline_throughput if baseline_throughput > 0 else 0
            efficiency = (actual_scaling / scaling_factor * 100) if scaling_factor > 0 else 0

            output.append(f"{c:<15} {throughput:>15.2f} {actual_scaling:>18.2f}x {efficiency:>14.1f}%")

    output.append("")
    output.append("-" * 120)
    output.append("RUN DETAILS")
    output.append("-" * 120)
    for c in sorted(summaries.keys()):
        output.append(f"Concurrency {c}: Run ID {summaries[c]['run_id']}")

    output.append("=" * 120)

    return "\n".join(output)


def format_markdown_output(engine: str, cluster_size: str, benchmark: str,
                           summaries: Dict[int, Dict]) -> str:
    """Format output as markdown."""
    output = []
    output.append(f"# Concurrency Scaling Analysis - {engine.upper()}")
    output.append("")
    output.append(f"**Cluster Size:** {cluster_size}  ")
    output.append(f"**Benchmark:** {benchmark}  ")
    output.append(f"**Concurrency Levels Tested:** {', '.join(map(str, sorted(summaries.keys())))}")
    output.append("")

    # Performance Metrics Table
    output.append("## Performance Metrics by Concurrency")
    output.append("")

    headers = ['Metric'] + [f'C={c}' for c in sorted(summaries.keys())]
    output.append("| " + " | ".join(headers) + " |")
    output.append("| " + " | ".join(['---'] * len(headers)) + " |")

    metrics = [
        ('Avg Response (sec)', 'avg_time_sec', '{:.2f}'),
        ('Median p50 (sec)', 'median_time_sec', '{:.2f}'),
        ('p90 Latency (sec)', 'p90_latency_sec', '{:.2f}'),
        ('p95 Latency (sec)', 'p95_latency_sec', '{:.2f}'),
        ('p99 Latency (sec)', 'p99_latency_sec', '{:.2f}'),
        ('Throughput (q/s)', 'throughput', '{:.2f}'),
        ('Total Time (sec)', 'total_time_sec', '{:.2f}'),
        ('Success Rate (%)', 'success_rate', '{:.1f}'),
    ]

    for label, key, fmt in metrics:
        values = [fmt.format(summaries[c][key]) for c in sorted(summaries.keys())]
        output.append("| " + label + " | " + " | ".join(values) + " |")

    output.append("")

    # Query Distribution
    output.append("## Query Execution Time Distribution")
    output.append("")

    for c in sorted(summaries.keys()):
        s = summaries[c]
        total = s['total_queries']
        output.append(f"### Concurrency {c}")
        output.append(f"- **1-5s**: {s['queries_1_5sec']} queries ({s['queries_1_5sec']/total*100:.1f}%)")
        output.append(f"- **5-10s**: {s['queries_5_10sec']} queries ({s['queries_5_10sec']/total*100:.1f}%)")
        output.append(f"- **>10s**: {s['queries_over_10sec']} queries ({s['queries_over_10sec']/total*100:.1f}%)")
        output.append("")

    # Scaling Analysis
    output.append("## Scaling Efficiency Analysis")
    output.append("")

    sorted_concurrencies = sorted(summaries.keys())
    if len(sorted_concurrencies) > 1:
        baseline_c = sorted_concurrencies[0]
        baseline_throughput = summaries[baseline_c]['throughput']

        output.append("| Concurrency | Throughput (q/s) | Scaling Factor | Efficiency |")
        output.append("| --- | --- | --- | --- |")

        for c in sorted_concurrencies:
            throughput = summaries[c]['throughput']
            scaling_factor = c / baseline_c
            actual_scaling = throughput / baseline_throughput if baseline_throughput > 0 else 0
            efficiency = (actual_scaling / scaling_factor * 100) if scaling_factor > 0 else 0

            output.append(f"| {c} | {throughput:.2f} | {actual_scaling:.2f}x | {efficiency:.1f}% |")

        output.append("")
        output.append("**Interpretation:**")
        output.append("- **Scaling Factor**: Expected throughput multiplier based on concurrency increase")
        output.append("- **Efficiency**: How well the system scales compared to ideal linear scaling (100% = perfect scaling)")
        output.append("")

    # Run Details
    output.append("## Run Details")
    output.append("")
    for c in sorted(summaries.keys()):
        output.append(f"- **Concurrency {c}**: Run ID `{summaries[c]['run_id']}`")

    return "\n".join(output)


def format_json_output(engine: str, cluster_size: str, benchmark: str,
                       summaries: Dict[int, Dict]) -> str:
    """Format output as JSON."""
    result = {
        "engine": engine,
        "cluster_size": cluster_size,
        "benchmark": benchmark,
        "concurrency_levels": sorted(list(summaries.keys())),
        "summaries": {str(k): v for k, v in summaries.items()}
    }
    return json.dumps(result, indent=2)


def main():
    parser = argparse.ArgumentParser(
        description='Summarize JMeter test results across concurrency levels',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Summarize DBR Medium cluster runs
  python utilities/summarize_concurrency_runs.py --engine dbr --cluster-size M --benchmark tpcds_29_1tb

  # Generate markdown report for E6Data
  python utilities/summarize_concurrency_runs.py --engine e6data --cluster-size M --benchmark tpcds_29_1tb --format markdown > report.md

  # Get JSON output for programmatic processing
  python utilities/summarize_concurrency_runs.py --engine e6data --cluster-size M --benchmark tpcds_29_1tb --format json
        """
    )

    parser.add_argument('--engine', required=True,
                       help='Engine name (e.g., dbr, e6data)')
    parser.add_argument('--cluster-size', required=True,
                       help='Cluster size (e.g., M, L, XL)')
    parser.add_argument('--benchmark', required=True,
                       help='Benchmark name (e.g., tpcds_29_1tb)')
    parser.add_argument('--format', choices=['text', 'markdown', 'json'], default='text',
                       help='Output format (default: text)')

    args = parser.parse_args()

    # List all concurrency runs
    print(f"Searching for test results in S3...", file=sys.stderr)
    concurrency_runs = list_s3_runs(args.engine, args.cluster_size, args.benchmark)

    if not concurrency_runs:
        print(f"No test results found for {args.engine}/{args.cluster_size}/{args.benchmark}",
              file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(concurrency_runs)} concurrency levels: {sorted(concurrency_runs.keys())}",
          file=sys.stderr)

    # Load and summarize each run
    summaries = {}
    for concurrency, s3_path in sorted(concurrency_runs.items()):
        print(f"Loading concurrency {concurrency}...", file=sys.stderr)
        test_data = load_test_result(s3_path)
        if test_data:
            summaries[concurrency] = extract_metrics(test_data)

    if not summaries:
        print("Failed to load any test results", file=sys.stderr)
        sys.exit(1)

    # Format output
    if args.format == 'text':
        output = format_text_output(args.engine, args.cluster_size, args.benchmark, summaries)
    elif args.format == 'markdown':
        output = format_markdown_output(args.engine, args.cluster_size, args.benchmark, summaries)
    else:  # json
        output = format_json_output(args.engine, args.cluster_size, args.benchmark, summaries)

    print(output)


if __name__ == '__main__':
    main()
