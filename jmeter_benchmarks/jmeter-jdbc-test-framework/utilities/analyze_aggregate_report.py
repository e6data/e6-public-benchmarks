#!/usr/bin/env python3
"""
JMeter Aggregate Report Analyzer
Analyzes JMeter aggregate report CSV files and generates comprehensive statistics.
"""

import csv
import sys
import os
from datetime import datetime, timedelta
from collections import Counter, defaultdict
import statistics
import json
import argparse
import re

# ANSI color codes
class Colors:
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    BOLD = '\033[1m'
    END = '\033[0m'

def format_duration(milliseconds):
    """Convert milliseconds to human-readable format"""
    seconds = milliseconds / 1000
    minutes = int(seconds // 60)
    seconds = int(seconds % 60)
    return f"{minutes}m {seconds}s"

def parse_error_message(error_msg):
    """Extract error type and details from error message"""
    if "HTTP Response code: 403" in error_msg:
        return "HTTP_403", "Authentication/Authorization Failed"
    elif "HTTP Response code: 500" in error_msg:
        return "HTTP_500", "Internal Server Error"
    elif "HTTP Response code:" in error_msg:
        match = re.search(r"HTTP Response code: (\d+)", error_msg)
        if match:
            return f"HTTP_{match.group(1)}", "HTTP Error"
    elif "SCALAR_SUBQUERY_TOO_MANY_ROWS" in error_msg:
        return "SCALAR_SUBQUERY_ERROR", "Scalar subquery returned multiple rows"
    elif "Multiple failures in stage materialization" in error_msg:
        return "STAGE_MATERIALIZATION_ERROR", "Spark stage materialization failed"
    elif "timeout" in error_msg.lower():
        return "TIMEOUT", "Query timeout"
    elif "java.sql.SQLException" in error_msg:
        match = re.search(r"\[(\d+)\]", error_msg)
        if match:
            return f"SQL_ERROR_{match.group(1)}", "SQL Exception"
        return "SQL_ERROR", "SQL Exception"
    else:
        return "UNKNOWN", "Unknown error"

def analyze_report(filepath):
    """Main analysis function"""
    
    print(f"{Colors.BOLD}{Colors.BLUE}{'═' * 70}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}           JMeter Aggregate Report Analysis{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}{'═' * 70}{Colors.END}")
    print()
    
    # File information
    file_stats = os.stat(filepath)
    file_size = file_stats.st_size
    mod_time = datetime.fromtimestamp(file_stats.st_mtime)
    
    print(f"{Colors.CYAN}📁 File Information:{Colors.END}")
    print(f"   File: {Colors.YELLOW}{os.path.basename(filepath)}{Colors.END}")
    print(f"   Path: {Colors.YELLOW}{os.path.dirname(filepath)}{Colors.END}")
    print(f"   Size: {Colors.YELLOW}{file_size / 1024:.1f} KB{Colors.END}")
    print(f"   Modified: {Colors.YELLOW}{mod_time.strftime('%Y-%m-%d %H:%M:%S')}{Colors.END}")
    print()
    
    # Read and analyze the CSV
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as csvfile:
        # Skip the header
        header = csvfile.readline().strip().split(',')
        
        # Parse data
        successful_requests = []
        failed_requests = []
        all_requests = []
        error_types = Counter()
        error_details = defaultdict(list)
        
        reader = csv.reader(csvfile)
        for row in reader:
            if len(row) < 8:
                continue
                
            try:
                timestamp = int(row[0])
                elapsed = int(row[1])
                label = row[2]
                response_code = row[3]
                response_message = row[4]
                success = row[7].lower() == 'true'
                
                request_data = {
                    'timestamp': timestamp,
                    'elapsed': elapsed,
                    'label': label,
                    'response_code': response_code,
                    'response_message': response_message,
                    'success': success
                }
                
                all_requests.append(request_data)
                
                if success:
                    successful_requests.append(request_data)
                else:
                    failed_requests.append(request_data)
                    error_type, error_desc = parse_error_message(response_message)
                    error_types[error_type] += 1
                    error_details[error_type].append({
                        'label': label,
                        'message': response_message[:100]  # Truncate long messages
                    })
                    
            except (ValueError, IndexError) as e:
                continue
    
    # Calculate statistics
    total_requests = len(all_requests)
    success_count = len(successful_requests)
    failed_count = len(failed_requests)
    
    if total_requests == 0:
        print(f"{Colors.RED}No valid data found in the file.{Colors.END}")
        return
    
    success_rate = (success_count / total_requests) * 100
    failure_rate = (failed_count / total_requests) * 100
    
    print(f"{Colors.CYAN}📊 Overall Statistics:{Colors.END}")
    print(f"   {Colors.BOLD}Total Requests:{Colors.END} {Colors.YELLOW}{total_requests}{Colors.END}")
    print(f"   {Colors.GREEN}✓ Successful:{Colors.END} {success_count} ({success_rate:.1f}%)")
    print(f"   {Colors.RED}✗ Failed:{Colors.END} {failed_count} ({failure_rate:.1f}%)")
    print()
    
    # Time analysis
    if all_requests:
        first_timestamp = all_requests[0]['timestamp']
        last_timestamp = all_requests[-1]['timestamp']
        duration_ms = last_timestamp - first_timestamp
        duration_sec = duration_ms / 1000
        
        print(f"{Colors.CYAN}⏱️  Test Duration:{Colors.END}")
        print(f"   Duration: {Colors.YELLOW}{format_duration(duration_ms)}{Colors.END}")
        
        if duration_sec > 0:
            throughput = total_requests / duration_sec
            print(f"   Throughput: {Colors.YELLOW}{throughput:.2f} requests/sec{Colors.END}")
        print()
    
    # Error analysis
    if failed_count > 0:
        print(f"{Colors.CYAN}❌ Error Analysis:{Colors.END}")
        print()
        print(f"{Colors.BOLD}   Unique Error Types:{Colors.END}")
        
        for error_type, count in error_types.most_common():
            percentage = (count / failed_count) * 100
            print(f"   {Colors.RED}• {error_type}:{Colors.END} {count} ({percentage:.1f}% of failures)")
        
        print()
        
        # Error timeline
        print(f"{Colors.BOLD}   Error Timeline:{Colors.END}")
        if failed_requests:
            first_error = failed_requests[0]
            first_error_idx = all_requests.index(first_error)
            print(f"   First error at request #{Colors.YELLOW}{first_error['label']}{Colors.END} (position {first_error_idx + 1})")
            
            # Find last success before errors started
            last_success_before = None
            for i in range(first_error_idx - 1, -1, -1):
                if all_requests[i]['success']:
                    last_success_before = all_requests[i]
                    break
            
            if last_success_before:
                print(f"   Last success before errors: #{Colors.GREEN}{last_success_before['label']}{Colors.END}")
        print()
    
    # Performance metrics
    if successful_requests:
        response_times = [req['elapsed'] for req in successful_requests]
        
        print(f"{Colors.CYAN}⚡ Performance Metrics:{Colors.END}")
        print(f"   Response Times (successful requests):")
        print(f"     Min: {Colors.GREEN}{min(response_times):,}ms{Colors.END}")
        print(f"     Max: {Colors.YELLOW}{max(response_times):,}ms{Colors.END}")
        print(f"     Mean: {Colors.CYAN}{statistics.mean(response_times):.0f}ms{Colors.END}")
        print(f"     Median: {Colors.CYAN}{statistics.median(response_times):.0f}ms{Colors.END}")
        
        # Calculate percentiles
        sorted_times = sorted(response_times)
        n = len(sorted_times)
        
        if n > 0:
            p50 = sorted_times[int(n * 0.50)]
            p90 = sorted_times[int(n * 0.90)]
            p95 = sorted_times[int(n * 0.95)]
            p99 = sorted_times[min(int(n * 0.99), n-1)]
            
            print(f"   Percentiles:")
            print(f"     P50: {Colors.CYAN}{p50:,}ms{Colors.END}")
            print(f"     P90: {Colors.YELLOW}{p90:,}ms{Colors.END}")
            print(f"     P95: {Colors.YELLOW}{p95:,}ms{Colors.END}")
            print(f"     P99: {Colors.RED}{p99:,}ms{Colors.END}")
        
        # Standard deviation
        if len(response_times) > 1:
            std_dev = statistics.stdev(response_times)
            print(f"     Std Dev: {Colors.CYAN}{std_dev:.0f}ms{Colors.END}")
    
    print()
    print(f"{Colors.BOLD}{Colors.BLUE}{'═' * 70}{Colors.END}")
    print(f"{Colors.GREEN}✓ Analysis Complete{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}{'═' * 70}{Colors.END}")
    
    # Optional: Save to JSON
    if len(sys.argv) > 2 and sys.argv[2] == '--json':
        output_file = filepath.replace('.csv', '_analysis.json')
        analysis_data = {
            'file': os.path.basename(filepath),
            'timestamp': datetime.now().isoformat(),
            'summary': {
                'total_requests': total_requests,
                'successful': success_count,
                'failed': failed_count,
                'success_rate': success_rate,
                'failure_rate': failure_rate
            },
            'errors': dict(error_types),
            'performance': {
                'min_response_time': min(response_times) if response_times else 0,
                'max_response_time': max(response_times) if response_times else 0,
                'mean_response_time': statistics.mean(response_times) if response_times else 0,
                'median_response_time': statistics.median(response_times) if response_times else 0,
                'p50': p50 if 'p50' in locals() else 0,
                'p90': p90 if 'p90' in locals() else 0,
                'p95': p95 if 'p95' in locals() else 0,
                'p99': p99 if 'p99' in locals() else 0
            }
        }
        
        with open(output_file, 'w') as f:
            json.dump(analysis_data, f, indent=2)
        print(f"\n{Colors.GREEN}Analysis saved to: {output_file}{Colors.END}")

def main():
    parser = argparse.ArgumentParser(description='Analyze JMeter Aggregate Report CSV files')
    parser.add_argument('file', help='Path to the aggregate report CSV file')
    parser.add_argument('--json', action='store_true', help='Save analysis results to JSON file')
    
    args = parser.parse_args()
    
    if not os.path.exists(args.file):
        print(f"{Colors.RED}Error: File '{args.file}' not found{Colors.END}")
        sys.exit(1)
    
    # Pass json flag through sys.argv for backward compatibility
    if args.json:
        sys.argv.append('--json')
    
    analyze_report(args.file)

if __name__ == "__main__":
    main()