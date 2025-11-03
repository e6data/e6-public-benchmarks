#!/usr/bin/env python3
"""
Fetch Databricks SQL query history and export to CSV.

Usage:
    python get_dbr_query_history.py <connection_properties> [options]

Arguments:
    connection_properties   Path to Databricks connection properties file

Options:
    --metadata FILE         Metadata file to include in output (default: auto-detect from test context)
    --test-properties FILE  Test properties file to include in output
    --test-result FILE      JMeter test_result JSON file to extract start/end times
    --start-time DATETIME   Start time (format: "YYYY-MM-DD HH:MM:SS")
    --end-time DATETIME     End time (format: "YYYY-MM-DD HH:MM:SS")
    --hours N               Number of hours of history to fetch (default: 6, ignored if --test-result or --start-time/--end-time provided)
    --output FILE           Output CSV file path (default: reports/dbr_query_history_TIMESTAMP.csv)
    --no-metadata           Don't include metadata in output
    --warehouse-id ID       Override warehouse ID from connection string

Examples:
    # Auto-detect from JMeter test result
    python utilities/get_dbr_query_history.py connection_properties/dbr_connection.properties --test-result reports/test_result_20250131_143022.json

    # Manual time range
    python utilities/get_dbr_query_history.py connection_properties/dbr_connection.properties --start-time "2025-01-31 14:00:00" --end-time "2025-01-31 15:30:00"

    # Last N hours
    python utilities/get_dbr_query_history.py connection_properties/dbr_connection.properties --hours 24

    # With metadata and test properties
    python utilities/get_dbr_query_history.py connection_properties/dbr_connection.properties --metadata metadata_files/dbr_s-4x4_metadata.txt --test-properties test_properties/concurrency_16_test.properties --hours 6
"""

import sys
import os
import csv
import json
import re
import argparse
from datetime import datetime, timedelta
from urllib.parse import urlparse, parse_qs

try:
    import requests
except ImportError:
    print("Error: requests module not found. Install with: pip install requests")
    sys.exit(1)


def parse_connection_properties(properties_file):
    """Parse Databricks connection properties file."""
    props = {}

    with open(properties_file, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            if '=' in line:
                key, value = line.split('=', 1)
                props[key.strip()] = value.strip()

    return props


def extract_warehouse_id(connection_string):
    """Extract warehouse ID from Databricks JDBC connection string."""
    # Example: jdbc:databricks://dbc-33354dfe-277f.cloud.databricks.com:443;httpPath=/sql/1.0/warehouses/e020ff73ae69ed5a
    match = re.search(r'/warehouses/([a-f0-9]+)', connection_string)
    if match:
        return match.group(1)
    return None


def extract_host(connection_string):
    """Extract host from JDBC connection string."""
    # jdbc:databricks://HOST:443/...
    match = re.search(r'jdbc:databricks://([^:]+)', connection_string)
    if match:
        return f"https://{match.group(1)}"
    return None


def parse_metadata_file(metadata_file):
    """Parse metadata file and extract CLUSTER_CONFIG JSON."""
    metadata = {}

    if not os.path.exists(metadata_file):
        return metadata

    with open(metadata_file, 'r') as f:
        content = f.read()

        # Extract bash variables
        for match in re.finditer(r'^(\w+)=(.+)$', content, re.MULTILINE):
            key, value = match.groups()
            if key not in ['CLUSTER_CONFIG']:
                metadata[key] = value.strip().strip('"\'')

        # Extract CLUSTER_CONFIG JSON
        cluster_config_match = re.search(r'CLUSTER_CONFIG=\'({[^}]+})\'', content, re.DOTALL)
        if cluster_config_match:
            try:
                cluster_config = json.loads(cluster_config_match.group(1))
                metadata['CLUSTER_CONFIG'] = cluster_config
            except json.JSONDecodeError:
                pass

    return metadata


def parse_test_properties(test_properties_file):
    """Parse test properties file."""
    props = {}

    if not os.path.exists(test_properties_file):
        return props

    with open(test_properties_file, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            if '=' in line:
                key, value = line.split('=', 1)
                props[key.strip()] = value.strip()

    return props


def parse_test_result_json(test_result_file):
    """Parse JMeter test_result JSON file and extract start/end times."""

    if not os.path.exists(test_result_file):
        print(f"Warning: Test result file not found: {test_result_file}")
        return None, None

    try:
        with open(test_result_file, 'r') as f:
            data = json.load(f)

        # Extract start and end times from test_result.json
        # Format: "2025-01-31T14:30:22"
        start_time_str = data.get('test_start_time')
        end_time_str = data.get('test_end_time')

        if not start_time_str or not end_time_str:
            print("Warning: test_start_time or test_end_time not found in test result JSON")
            return None, None

        # Parse ISO format timestamps
        start_time = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
        end_time = datetime.fromisoformat(end_time_str.replace('Z', '+00:00'))

        return start_time, end_time

    except (json.JSONDecodeError, ValueError) as e:
        print(f"Error parsing test result file: {e}")
        return None, None


def get_query_history(host, token, warehouse_id, start_time=None, end_time=None, hours=None):
    """Fetch query history from Databricks API."""

    url = f"{host}/api/2.0/sql/history/queries"
    headers = {
        "Authorization": f"Bearer {token}"
    }

    # Determine time range
    if start_time and end_time:
        # Use provided start/end times
        pass
    elif hours:
        # Calculate from hours
        end_time = datetime.now()
        start_time = end_time - timedelta(hours=hours)
    else:
        # Default to last 6 hours
        end_time = datetime.now()
        start_time = end_time - timedelta(hours=6)

    # Build query parameters
    params = {
        "max_results": 1000,
        "filter_by.query_start_time_range.start_time_ms": int(start_time.timestamp() * 1000),
        "filter_by.query_start_time_range.end_time_ms": int(end_time.timestamp() * 1000)
    }

    # Add warehouse filter
    params["filter_by.warehouse_ids"] = warehouse_id

    print(f"Fetching query history from {start_time.strftime('%Y-%m-%d %H:%M:%S')} to {end_time.strftime('%Y-%m-%d %H:%M:%S')} (warehouse={warehouse_id})...")

    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status()

    return response.json()


def export_to_csv(queries, output_file, metadata=None, test_properties=None, include_metadata=True):
    """Export queries to CSV with optional metadata."""

    with open(output_file, 'w', newline='') as f:
        writer = csv.writer(f)

        # Build header
        header = [
            'query_id', 'query_text', 'status', 'duration_ms',
            'start_time', 'end_time', 'user', 'warehouse_id',
            'rows_produced', 'error_message'
        ]

        # Add metadata columns if requested
        if include_metadata:
            if metadata:
                if 'ENGINE' in metadata:
                    header.append('engine')
                if 'CLUSTER_CONFIG' in metadata:
                    header.extend(['cluster_size', 'estimated_cores', 'instance_type'])

            if test_properties:
                if 'CONCURRENT_QUERY_COUNT' in test_properties:
                    header.append('test_concurrency')
                if 'HOLD_PERIOD' in test_properties:
                    header.append('test_duration_min')

        writer.writerow(header)

        # Write query data
        for query in queries.get('res', []):
            row = [
                query.get('query_id', ''),
                query.get('query_text', '').replace('\n', ' ').replace('\r', ' '),
                query.get('status', ''),
                query.get('duration', ''),
                datetime.fromtimestamp(query.get('query_start_time_ms', 0) / 1000).strftime('%Y-%m-%d %H:%M:%S') if query.get('query_start_time_ms') else '',
                datetime.fromtimestamp(query.get('query_end_time_ms', 0) / 1000).strftime('%Y-%m-%d %H:%M:%S') if query.get('query_end_time_ms') else '',
                query.get('user_name', ''),
                query.get('warehouse_id', ''),
                query.get('rows_produced', ''),
                query.get('error_message', '')
            ]

            # Add metadata values if requested
            if include_metadata:
                if metadata:
                    if 'ENGINE' in metadata:
                        row.append(metadata.get('ENGINE', ''))
                    if 'CLUSTER_CONFIG' in metadata:
                        cluster_config = metadata.get('CLUSTER_CONFIG', {})
                        row.extend([
                            cluster_config.get('cluster_size', ''),
                            cluster_config.get('estimated_cores', ''),
                            cluster_config.get('instance_type', '')
                        ])

                if test_properties:
                    if 'CONCURRENT_QUERY_COUNT' in test_properties:
                        row.append(test_properties.get('CONCURRENT_QUERY_COUNT', ''))
                    if 'HOLD_PERIOD' in test_properties:
                        row.append(test_properties.get('HOLD_PERIOD', ''))

            writer.writerow(row)


def main():
    parser = argparse.ArgumentParser(
        description='Fetch Databricks SQL query history and export to CSV',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument('connection_properties', help='Path to Databricks connection properties file')
    parser.add_argument('--metadata', help='Metadata file to include in output')
    parser.add_argument('--test-properties', help='Test properties file to include in output')
    parser.add_argument('--test-result', help='JMeter test_result JSON file to extract start/end times')
    parser.add_argument('--start-time', help='Start time (format: "YYYY-MM-DD HH:MM:SS")')
    parser.add_argument('--end-time', help='End time (format: "YYYY-MM-DD HH:MM:SS")')
    parser.add_argument('--hours', type=int, help='Number of hours of history to fetch (default: 6)')
    parser.add_argument('--output', help='Output CSV file path (default: reports/dbr_query_history_TIMESTAMP.csv)')
    parser.add_argument('--no-metadata', action='store_true', help="Don't include metadata in output")
    parser.add_argument('--warehouse-id', help='Override warehouse ID from connection string')
    parser.add_argument('--user-filter', help='Filter queries by specific user (default: USER from connection properties)')
    parser.add_argument('--no-user-filter', action='store_true', help="Don't filter by user (include all users)")

    args = parser.parse_args()

    # Parse connection properties
    print(f"Reading connection properties from {args.connection_properties}...")
    conn_props = parse_connection_properties(args.connection_properties)

    # Extract connection details
    connection_string = conn_props.get('CONNECTION_STRING', '')
    if not connection_string:
        print("Error: CONNECTION_STRING not found in connection properties")
        sys.exit(1)

    host = extract_host(connection_string)
    if not host:
        print("Error: Could not extract host from CONNECTION_STRING")
        sys.exit(1)

    warehouse_id = args.warehouse_id or extract_warehouse_id(connection_string)
    if not warehouse_id:
        print("Error: Could not extract warehouse ID from CONNECTION_STRING and --warehouse-id not provided")
        sys.exit(1)

    # Get token from properties or environment
    token = conn_props.get('DATABRICKS_TOKEN') or os.environ.get('DATABRICKS_TOKEN')
    if not token:
        # Try to get from PASSWORD field (some configs use this)
        token = conn_props.get('PASSWORD')

    if not token:
        print("Error: Databricks token not found. Set DATABRICKS_TOKEN in connection properties or environment")
        sys.exit(1)

    print(f"Databricks Host: {host}")
    print(f"Warehouse ID: {warehouse_id}")

    # Parse metadata if provided
    metadata = None
    if args.metadata and not args.no_metadata:
        print(f"Reading metadata from {args.metadata}...")
        metadata = parse_metadata_file(args.metadata)

    # Parse test properties if provided
    test_properties = None
    if args.test_properties and not args.no_metadata:
        print(f"Reading test properties from {args.test_properties}...")
        test_properties = parse_test_properties(args.test_properties)

    # Determine time range for query history
    start_time = None
    end_time = None
    hours = None

    if args.test_result:
        # Extract from test_result JSON
        print(f"Extracting start/end times from {args.test_result}...")
        start_time, end_time = parse_test_result_json(args.test_result)
        if not start_time or not end_time:
            print("Failed to extract times from test result, falling back to --hours")
            hours = args.hours or 6
    elif args.start_time and args.end_time:
        # Use manual start/end times
        try:
            start_time = datetime.strptime(args.start_time, '%Y-%m-%d %H:%M:%S')
            end_time = datetime.strptime(args.end_time, '%Y-%m-%d %H:%M:%S')
        except ValueError as e:
            print(f"Error parsing start/end times: {e}")
            print("Expected format: YYYY-MM-DD HH:MM:SS")
            sys.exit(1)
    elif args.start_time or args.end_time:
        print("Error: Both --start-time and --end-time must be provided together")
        sys.exit(1)
    else:
        # Use hours
        hours = args.hours or 6

    # Fetch query history
    try:
        queries = get_query_history(host, token, warehouse_id, start_time, end_time, hours)
    except requests.exceptions.RequestException as e:
        print(f"Error fetching query history: {e}")
        sys.exit(1)

    query_count = len(queries.get('res', []))
    print(f"Fetched {query_count} queries")

    if query_count == 0:
        print("No queries found in the specified time range")
        return

    # Determine output file
    if args.output:
        output_file = args.output
    else:
        # Create reports directory if it doesn't exist
        os.makedirs('reports', exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_file = f"reports/dbr_query_history_{timestamp}.csv"

    # Export to CSV
    print(f"Exporting to {output_file}...")
    export_to_csv(queries, output_file, metadata, test_properties, not args.no_metadata)

    print(f"✓ Successfully exported {query_count} queries to {output_file}")


if __name__ == '__main__':
    main()
