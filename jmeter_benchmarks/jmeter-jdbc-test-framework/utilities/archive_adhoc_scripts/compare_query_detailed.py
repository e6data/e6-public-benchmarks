#!/usr/bin/env python3
import json
import sys

def load_json(filepath):
    with open(filepath, 'r') as f:
        return json.load(f)

def normalize_query_name(query_name):
    """Extract TPCDS query number from various formats"""
    import re
    # Match patterns like: TPCDS-69, query-69-TPCDS-69-optimised, etc.
    match = re.search(r'TPCDS-(\d+)', query_name, re.IGNORECASE)
    if match:
        return f"TPCDS-{match.group(1)}"
    return query_name

def calculate_improvement(e6_time, dbr_time):
    """Calculate improvement percentage (positive means e6data is faster)"""
    if dbr_time == 0:
        return 0
    return ((dbr_time - e6_time) / dbr_time) * 100

def format_duration(seconds):
    """Format duration in human readable format"""
    if seconds < 60:
        return f"{seconds:.2f}s"
    elif seconds < 3600:
        mins = int(seconds // 60)
        secs = seconds % 60
        return f"{mins}m {secs:.1f}s"
    else:
        hours = int(seconds // 3600)
        mins = int((seconds % 3600) // 60)
        return f"{hours}h {mins}m"

def main():
    if len(sys.argv) < 3:
        print("Usage: script.py <e6data_json> <databricks_json> [--sort-by-query]")
        sys.exit(1)

    sort_by_query = '--sort-by-query' in sys.argv

    e6_data = load_json(sys.argv[1])
    dbr_data = load_json(sys.argv[2])

    # Extract query data from all_queries_avg_time and normalize names
    e6_queries = {normalize_query_name(q['query']): q['avg_time_sec'] for q in e6_data.get('all_queries_avg_time', [])}
    dbr_queries = {normalize_query_name(q['query']): q['avg_time_sec'] for q in dbr_data.get('all_queries_avg_time', [])}

    # Get all unique query names
    all_queries = sorted(set(list(e6_queries.keys()) + list(dbr_queries.keys())))

    comparisons = []

    for query in all_queries:
        e6_avg = e6_queries.get(query)
        dbr_avg = dbr_queries.get(query)

        if e6_avg is not None and dbr_avg is not None:
            improvement = calculate_improvement(e6_avg, dbr_avg)
            comparisons.append({
                'query': query,
                'e6_avg': e6_avg,
                'dbr_avg': dbr_avg,
                'improvement': improvement
            })
        elif e6_avg is not None:
            comparisons.append({
                'query': query,
                'e6_avg': e6_avg,
                'dbr_avg': None,
                'improvement': None,
                'status': 'only_in_e6data'
            })
        elif dbr_avg is not None:
            comparisons.append({
                'query': query,
                'e6_avg': None,
                'dbr_avg': dbr_avg,
                'improvement': None,
                'status': 'only_in_databricks'
            })

    # Sort by improvement (best to worst) or by query name
    valid_comparisons = [c for c in comparisons if c.get('improvement') is not None]
    if sort_by_query:
        # Sort by query number (extract numeric part)
        import re
        def get_query_num(query_name):
            match = re.search(r'(\d+)', query_name)
            return int(match.group(1)) if match else 0
        valid_comparisons.sort(key=lambda x: get_query_num(x['query']))
    else:
        valid_comparisons.sort(key=lambda x: x['improvement'], reverse=True)

    # Extract performance metrics
    e6_perf = e6_data.get('performance_metrics', {})
    dbr_perf = dbr_data.get('performance_metrics', {})

    # Print header
    print("=" * 140)
    print("COMPREHENSIVE PERFORMANCE COMPARISON: e6data vs Databricks")
    print("=" * 140)
    print()

    # Run information
    print("RUN INFORMATION:")
    print("-" * 140)
    print(f"{'Metric':<30} {'e6data':<50} {'Databricks':<50}")
    print("-" * 140)
    print(f"{'Run ID':<30} {e6_data.get('run_id', 'N/A'):<50} {dbr_data.get('run_id', 'N/A'):<50}")
    print(f"{'Tags':<30} {e6_data.get('tags', 'N/A'):<50} {dbr_data.get('tags', 'N/A'):<50}")
    print(f"{'Engine':<30} {e6_data.get('engine', 'N/A'):<50} {dbr_data.get('engine', 'N/A'):<50}")
    print(f"{'Cluster':<30} {e6_data.get('cluster_hostname', 'N/A'):<50} {dbr_data.get('cluster_hostname', 'N/A'):<50}")
    print(f"{'Cloud':<30} {e6_data.get('cloud', 'N/A'):<50} {dbr_data.get('cloud', 'N/A'):<50}")
    print()

    # Overall performance metrics
    print("OVERALL PERFORMANCE METRICS:")
    print("-" * 140)
    print(f"{'Metric':<30} {'e6data':>20} {'Databricks':>20} {'Improvement':>20} {'Winner':<20}")
    print("-" * 140)

    metrics = [
        ('Total Duration', e6_perf.get('total_time_taken_sec', 0), dbr_perf.get('total_time_taken_sec', 0), 's'),
        ('Average Time', e6_perf.get('avg_time_sec', 0), dbr_perf.get('avg_time_sec', 0), 's'),
        ('Median Time', e6_perf.get('median_time_sec', 0), dbr_perf.get('median_time_sec', 0), 's'),
        ('Min Time', e6_perf.get('min_time_sec', 0), dbr_perf.get('min_time_sec', 0), 's'),
        ('Max Time', e6_perf.get('max_time_sec', 0), dbr_perf.get('max_time_sec', 0), 's'),
        ('Std Deviation', e6_perf.get('std_dev_sec', 0), dbr_perf.get('std_dev_sec', 0), 's'),
        ('P50 Latency', e6_perf.get('p50_latency_sec', 0), dbr_perf.get('p50_latency_sec', 0), 's'),
        ('P90 Latency', e6_perf.get('p90_latency_sec', 0), dbr_perf.get('p90_latency_sec', 0), 's'),
        ('P95 Latency', e6_perf.get('p95_latency_sec', 0), dbr_perf.get('p95_latency_sec', 0), 's'),
        ('P99 Latency', e6_perf.get('p99_latency_sec', 0), dbr_perf.get('p99_latency_sec', 0), 's'),
    ]

    for metric_name, e6_val, dbr_val, unit in metrics:
        if e6_val > 0 and dbr_val > 0:
            improvement = calculate_improvement(e6_val, dbr_val)
            winner = "e6data" if improvement > 0 else "Databricks" if improvement < 0 else "Tie"
            if metric_name == 'Total Duration':
                print(f"{metric_name:<30} {format_duration(e6_val):>20} {format_duration(dbr_val):>20} {improvement:>19.1f}% {winner:<20}")
            else:
                print(f"{metric_name:<30} {e6_val:>19.2f}{unit} {dbr_val:>19.2f}{unit} {improvement:>19.1f}% {winner:<20}")

    # Throughput metrics
    print()
    e6_throughput = e6_perf.get('throughput', 0)
    dbr_throughput = dbr_perf.get('throughput', 0)
    if e6_throughput > 0 and dbr_throughput > 0:
        throughput_improvement = ((e6_throughput - dbr_throughput) / dbr_throughput) * 100
        winner = "e6data" if throughput_improvement > 0 else "Databricks"
        print(f"{'Throughput (queries/sec)':<30} {e6_throughput:>19.2f} {dbr_throughput:>19.2f} {throughput_improvement:>19.1f}% {winner:<20}")

    # Connection metrics
    e6_conn = e6_data.get('connection_metrics', {})
    dbr_conn = dbr_data.get('connection_metrics', {})
    e6_network = e6_conn.get('network_latency_avg_ms', 0)
    dbr_network = dbr_conn.get('network_latency_avg_ms', 0)
    if e6_network > 0 and dbr_network > 0:
        network_improvement = calculate_improvement(e6_network, dbr_network)
        winner = "e6data" if network_improvement > 0 else "Databricks"
        print(f"{'Network Latency Avg':<30} {e6_network:>18.2f}ms {dbr_network:>18.2f}ms {network_improvement:>19.1f}% {winner:<20}")

    print()

    # Query-by-query comparison
    print("=" * 140)
    print(f"QUERY-BY-QUERY COMPARISON {'(Sorted by Query)' if sort_by_query else '(Sorted by Performance)'}")
    print("=" * 140)
    print(f"{'Query':<15} {'e6data (s)':>12} {'DBR (s)':>12} {'Diff (s)':>12} {'Improvement':>15} {'Status':<25}")
    print("-" * 140)

    for comp in valid_comparisons:
        e6_time = f"{comp['e6_avg']:.2f}" if comp['e6_avg'] else "N/A"
        dbr_time = f"{comp['dbr_avg']:.2f}" if comp['dbr_avg'] else "N/A"

        if comp['improvement'] is not None and comp['e6_avg'] is not None and comp['dbr_avg'] is not None:
            diff = comp['e6_avg'] - comp['dbr_avg']
            diff_str = f"{diff:+.2f}"

            if comp['improvement'] > 5:
                status = "✓ e6data faster"
                improvement_str = f"+{comp['improvement']:.1f}%"
            elif comp['improvement'] < -5:
                status = "✗ DBR faster"
                improvement_str = f"{comp['improvement']:.1f}%"
            else:
                status = "≈ similar"
                improvement_str = f"{comp['improvement']:.1f}%"
        else:
            diff_str = "N/A"
            improvement_str = "N/A"
            status = comp.get('status', 'N/A')

        print(f"{comp['query']:<15} {e6_time:>12} {dbr_time:>12} {diff_str:>12} {improvement_str:>15} {status:<25}")

    # Summary statistics
    print()
    print("=" * 140)
    print("SUMMARY STATISTICS")
    print("=" * 140)

    if valid_comparisons:
        improvements = [c['improvement'] for c in valid_comparisons]
        faster_count = sum(1 for i in improvements if i > 5)
        slower_count = sum(1 for i in improvements if i < -5)
        similar_count = sum(1 for i in improvements if -5 <= i <= 5)
        avg_improvement = sum(improvements) / len(improvements)

        e6_avg_overall = e6_perf.get('avg_time_sec', 0)
        dbr_avg_overall = dbr_perf.get('avg_time_sec', 0)
        overall_improvement = calculate_improvement(e6_avg_overall, dbr_avg_overall)

        print(f"Total queries compared: {len(valid_comparisons)}")
        print(f"  e6data faster (>5%):      {faster_count:3d} queries ({100*faster_count/len(valid_comparisons):.1f}%)")
        print(f"  Databricks faster (>5%):  {slower_count:3d} queries ({100*slower_count/len(valid_comparisons):.1f}%)")
        print(f"  Similar performance (±5%): {similar_count:3d} queries ({100*similar_count/len(valid_comparisons):.1f}%)")
        print()
        print(f"Average per-query improvement: {avg_improvement:+.1f}% {'(e6data favored)' if avg_improvement > 0 else '(Databricks favored)'}")
        print(f"Overall average time improvement: {overall_improvement:+.1f}% {'(e6data faster)' if overall_improvement > 0 else '(Databricks faster)'}")
        print()

        # Calculate time savings
        e6_total = e6_perf.get('total_time_taken_sec', 0)
        dbr_total = dbr_perf.get('total_time_taken_sec', 0)
        time_diff = e6_total - dbr_total
        if time_diff < 0:
            print(f"Total time savings with e6data: {format_duration(abs(time_diff))} ({abs(time_diff/dbr_total*100):.1f}% faster)")
        else:
            print(f"Total time savings with Databricks: {format_duration(abs(time_diff))} ({abs(time_diff/e6_total*100):.1f}% faster)")
        print()

        # Top performers section (only if not sorted by query)
        if not sort_by_query:
            print("TOP 10 QUERIES WHERE E6DATA IS FASTER:")
            print("-" * 140)
            e6_faster = [c for c in valid_comparisons if c['improvement'] > 0]
            if e6_faster:
                for i, comp in enumerate(e6_faster[:10], 1):
                    time_saved = comp['dbr_avg'] - comp['e6_avg']
                    print(f"{i:2d}. {comp['query']:<15} e6:{comp['e6_avg']:6.2f}s  DBR:{comp['dbr_avg']:6.2f}s  → {comp['improvement']:+6.1f}%  (saved {time_saved:.2f}s)")
            else:
                print("  None")

            print()
            print("TOP 10 QUERIES WHERE DATABRICKS IS FASTER:")
            print("-" * 140)
            slower_queries = [c for c in valid_comparisons if c['improvement'] < 0]
            slower_queries.sort(key=lambda x: x['improvement'])
            if slower_queries:
                for i, comp in enumerate(slower_queries[:10], 1):
                    time_saved = comp['e6_avg'] - comp['dbr_avg']
                    print(f"{i:2d}. {comp['query']:<15} e6:{comp['e6_avg']:6.2f}s  DBR:{comp['dbr_avg']:6.2f}s  → {comp['improvement']:+6.1f}%  (saved {time_saved:.2f}s)")
            else:
                print("  None")

    print("=" * 140)

if __name__ == '__main__':
    main()
