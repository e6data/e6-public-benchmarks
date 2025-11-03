#!/usr/bin/env python3
"""
Test SQL queries via e6data HTTP API endpoint (bypassing JMeter)

This script authenticates with the e6data API and executes queries from a CSV file,
reporting success/failure for each query. This helps confirm whether issues are
with JMeter or with the actual SQL queries.

Usage:
    python test_queries_http.py <connection_properties> <query_csv>

Example:
    python test_queries_http.py connection_properties/http_endpoint_connection_kantarWS.properties data_files/kantar_final_working.csv
"""

import sys
import csv
import json
import requests
import time
from datetime import datetime

def load_properties(filepath):
    """Load properties from a Java-style properties file"""
    props = {}
    with open(filepath, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                if '=' in line:
                    key, value = line.split('=', 1)
                    props[key.strip()] = value.strip()
    return props

def authenticate(props):
    """Authenticate with e6data API and return session token"""
    auth_url = f"{props['scheme']}://{props['mainhost']}/api/v1/authenticate"

    # IMPORTANT: JMeter uses "user" not "username"!
    auth_payload = {
        "user": props['USER'],
        "password": props['PASSWORD']
    }

    # IMPORTANT: Include cluster-name header as JMeter does!
    headers = {
        'Content-Type': 'application/json',
        'cluster-name': props.get('cluster_name', '')
    }

    print(f"Authenticating at {auth_url}...")
    print(f"  Cluster: {props.get('cluster_name', 'N/A')}")

    try:
        response = requests.post(auth_url, json=auth_payload, headers=headers, timeout=30)

        if response.status_code == 200:
            # IMPORTANT: Token is in sessionId field, not token field!
            response_data = response.json()
            session_id = response_data.get('sessionId')

            if session_id:
                print(f"✅ Authentication successful")
                print(f"  Session ID: {session_id[:20]}...\n")
                return session_id
            else:
                print(f"⚠️  Authentication returned 200 but no sessionId found")
                print(f"  Response: {json.dumps(response_data, indent=2)}")
                return None
        else:
            print(f"❌ Authentication failed: {response.status_code}")
            try:
                print(f"Response: {json.dumps(response.json(), indent=2)}")
            except:
                print(f"Response: {response.text}")
            return None

    except Exception as e:
        print(f"❌ Authentication error: {e}")
        return None

def execute_query(execute_url, token, query_alias, query_text, catalog, schema, cluster_name):
    """Execute a single query and return result"""
    # IMPORTANT: The query is sent directly WITHOUT pre-escaping
    # json.dumps() will handle all necessary escaping when serializing the payload
    payload = {
        "statement": query_text,  # Raw query - json.dumps will escape it
        "catalog": catalog,
        "schema": schema
    }

    # Match JMeter headers exactly
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f"Bearer {token}",
        'cluster-name': cluster_name,
        'Accept': 'application/json, text/plain, */*',
        'Origin': 'https://espresso-dev.kantar.com',
        'Referer': 'https://espresso-dev.kantar.com/',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'cross-site',
        'Accept-Language': 'en-US,en;q=0.9'
    }

    start_time = time.time()

    try:
        response = requests.post(execute_url, headers=headers, json=payload, timeout=60)
        elapsed_ms = int((time.time() - start_time) * 1000)

        result = {
            'alias': query_alias,
            'status_code': response.status_code,
            'elapsed_ms': elapsed_ms,
            'success': response.status_code == 200,
            'query_length': len(query_text)
        }

        if response.status_code == 200:
            result['response'] = response.json()
        else:
            try:
                result['error'] = response.json()
            except:
                result['error'] = response.text

        return result

    except requests.exceptions.Timeout:
        elapsed_ms = int((time.time() - start_time) * 1000)
        return {
            'alias': query_alias,
            'status_code': 0,
            'elapsed_ms': elapsed_ms,
            'success': False,
            'query_length': len(query_text),
            'error': 'Request timeout (60s)'
        }
    except Exception as e:
        elapsed_ms = int((time.time() - start_time) * 1000)
        return {
            'alias': query_alias,
            'status_code': 0,
            'elapsed_ms': elapsed_ms,
            'success': False,
            'query_length': len(query_text),
            'error': str(e)
        }

def main():
    if len(sys.argv) != 3:
        print("Usage: python test_queries_http.py <connection_properties> <query_csv>")
        print("\nExample:")
        print("  python test_queries_http.py connection_properties/http_endpoint_connection_kantarWS.properties data_files/kantar_final_working.csv")
        sys.exit(1)

    connection_file = sys.argv[1]
    query_file = sys.argv[2]

    print("="*80)
    print("e6data HTTP API Query Tester (Python - Bypassing JMeter)")
    print("="*80)
    print(f"Connection: {connection_file}")
    print(f"Queries: {query_file}")
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*80)
    print()

    # Load connection properties
    try:
        props = load_properties(connection_file)
    except Exception as e:
        print(f"❌ Error loading connection properties: {e}")
        sys.exit(1)

    # Authenticate
    token = authenticate(props)
    if not token:
        sys.exit(1)

    # Build execute URL
    execute_url = f"{props['scheme']}://{props['mainhost']}/api/v1/execute"
    catalog = props.get('CATALOG', 'espresso_gold_test')
    schema = props.get('SCHEMA', 'default')
    cluster_name = props.get('cluster_name', '')

    print(f"Execute URL: {execute_url}")
    print(f"Catalog: {catalog}")
    print(f"Schema: {schema}")
    print(f"Cluster: {cluster_name}")
    print()

    # Load queries
    queries = []
    try:
        with open(query_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                queries.append({
                    'alias': row['QUERY_ALIAS'],
                    'query': row['QUERY']
                })
        print(f"Loaded {len(queries)} queries from CSV\n")
    except Exception as e:
        print(f"❌ Error loading queries: {e}")
        sys.exit(1)

    # Execute each query
    results = []

    print("="*80)
    print("EXECUTING QUERIES")
    print("="*80)
    print()

    for i, query_obj in enumerate(queries, 1):
        alias = query_obj['alias']
        query = query_obj['query']

        print(f"[{i}/{len(queries)}] Testing {alias}...")
        print(f"  Query length: {len(query)} chars")

        result = execute_query(execute_url, token, alias, query, catalog, schema, cluster_name)
        results.append(result)

        if result['success']:
            print(f"  ✅ SUCCESS - {result['elapsed_ms']}ms")
        else:
            print(f"  ❌ FAILED - Status {result['status_code']} - {result['elapsed_ms']}ms")
            if isinstance(result.get('error'), dict):
                error_msg = result['error'].get('message', str(result['error']))
                print(f"  Error: {error_msg[:200]}")
            else:
                print(f"  Error: {str(result.get('error', 'Unknown'))[:200]}")
        print()

        # Small delay between requests to avoid overwhelming API
        time.sleep(0.5)

    # Summary
    print("="*80)
    print("SUMMARY")
    print("="*80)
    print()

    success_count = sum(1 for r in results if r['success'])
    failure_count = len(results) - success_count
    success_rate = (success_count / len(results) * 100) if results else 0

    print(f"Total Queries: {len(results)}")
    print(f"Successful: {success_count} ({success_rate:.2f}%)")
    print(f"Failed: {failure_count} ({100-success_rate:.2f}%)")
    print()

    # Detailed breakdown
    print("Breakdown by Query:")
    print("-" * 80)
    for result in results:
        status = "✅" if result['success'] else "❌"
        print(f"{status} {result['alias']}: Status {result['status_code']} - {result['elapsed_ms']}ms")
    print()

    # Show failures
    failures = [r for r in results if not r['success']]
    if failures:
        print("Failed Queries Details:")
        print("-" * 80)
        for result in failures:
            print(f"\n{result['alias']}:")
            print(f"  Status Code: {result['status_code']}")
            print(f"  Elapsed: {result['elapsed_ms']}ms")
            print(f"  Query Length: {result['query_length']} chars")

            if isinstance(result.get('error'), dict):
                print(f"  Error Message:")
                error_msg = result['error'].get('message', json.dumps(result['error'], indent=2))
                # Show first 500 chars of error
                print(f"    {error_msg[:500]}")
                if len(error_msg) > 500:
                    print(f"    ... (truncated, total {len(error_msg)} chars)")
            else:
                print(f"  Error: {str(result.get('error', 'Unknown'))[:500]}")

    # Save detailed results to JSON
    output_file = f"test_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    try:
        with open(output_file, 'w') as f:
            json.dump({
                'timestamp': datetime.now().isoformat(),
                'connection': connection_file,
                'query_file': query_file,
                'total': len(results),
                'successful': success_count,
                'failed': failure_count,
                'success_rate': success_rate,
                'results': results
            }, f, indent=2)
        print(f"\n📄 Detailed results saved to: {output_file}")
    except Exception as e:
        print(f"\n⚠️  Could not save results file: {e}")

    print("\n" + "="*80)
    print("CONCLUSION")
    print("="*80)

    if success_rate == 100:
        print("✅ All queries executed successfully!")
        print("   The issues were with JMeter configuration, not the queries.")
    elif success_rate > 0:
        print(f"⚠️  Mixed results: {success_count}/{len(results)} queries succeeded")
        print("   Some queries have actual SQL errors unrelated to JMeter.")
        print("   Review the failed queries above for specific error messages.")
    else:
        print("❌ All queries failed!")
        print("   This could indicate:")
        print("   - Connection/authentication issues")
        print("   - Incorrect catalog/schema")
        print("   - Fundamental SQL syntax errors")

    print()

    sys.exit(0 if success_rate == 100 else 1)

if __name__ == "__main__":
    main()
