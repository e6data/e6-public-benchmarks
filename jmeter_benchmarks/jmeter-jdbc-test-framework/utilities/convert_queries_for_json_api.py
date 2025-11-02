#!/usr/bin/env python3
"""
Convert multiline SQL queries to single-line format for JSON API compatibility.

This script is similar to convert_multiline_csv.sh but also applies fixes for:
- Backticks → double quotes
- Reserved keywords quoting
- Schema name quoting (global, default)
- CTE syntax fixes (adding missing AS)
- Function name casing (concat → Concat)
- Optional: Remove optimizer hints

Input: CSV with multiline queries
Output: CSV with single-line JSON-compatible queries

Usage:
    python convert_queries_for_json_api.py input.csv output.csv [--remove-hints]

Example:
    python convert_queries_for_json_api.py raw_queries.csv clean_queries.csv
    python convert_queries_for_json_api.py raw_queries.csv clean_queries.csv --remove-hints
"""

import csv
import re
import sys

# Reserved SQL keywords that need quoting in e6data
KEYWORDS = ['year', 'week', 'month', 'quarter', 'period', 'date', 'format', 'variant']

def convert_query(query, remove_hints=False):
    """Convert multiline query to single-line with JSON/e6data fixes."""

    # 1. Collapse multiline to single line
    query = ' '.join(query.split())

    # 2. Fix CTE syntax: with name( → with name as (
    query = re.sub(r'\bwith\s+(\w+)\s*\(', r'with \1 as (', query, flags=re.IGNORECASE)

    # 3. Fix CTE syntax: , name( → , name as (
    query = re.sub(r',\s*(\w+)\s*\((?=\s*select)', r', \1 as (', query, flags=re.IGNORECASE)

    # 4. Replace backticks with double quotes
    query = query.replace('`', '"')

    # 5. Quote schema names
    query = re.sub(r'\.global\.', '."global".', query, flags=re.IGNORECASE)
    query = re.sub(r'\.default\.', '."default".', query, flags=re.IGNORECASE)

    # 6. Quote reserved keywords as column names
    for keyword in KEYWORDS:
        # Pattern: .keyword → ."keyword"
        query = re.sub(r'\.(' + keyword + r')\b(?!\()', r'."\1"', query, flags=re.IGNORECASE)

        # Pattern: select keyword, → select "keyword",
        query = re.sub(r'(?<=select\s)(' + keyword + r')\b', r'"\1"', query, flags=re.IGNORECASE)
        query = re.sub(r'(?<=,\s)(' + keyword + r')(?=\s*,)', r'"\1"', query, flags=re.IGNORECASE)
        query = re.sub(r'(?<=,\s)(' + keyword + r')(?=\s+from\b)', r'"\1"', query, flags=re.IGNORECASE)

    # 7. Fix concat → Concat
    query = re.sub(r'\bconcat\s*\(', 'Concat(', query, flags=re.IGNORECASE)

    # 8. Remove optimizer hints (optional)
    if remove_hints:
        query = re.sub(r'/\*\+[^*]*\*/', '', query)
        query = re.sub(r'\s+', ' ', query)
        query = query.strip()

    # 9. Escape double quotes for JSON compatibility
    # Replace " with \" so the query can be safely embedded in JSON
    query = query.replace('"', '\\"')

    return query

def main():
    if len(sys.argv) < 3:
        print("Usage: python convert_queries_for_json_api.py input.csv output.csv [--remove-hints]")
        print("\nExample:")
        print("  python convert_queries_for_json_api.py Kantar-queries.csv Kantar-queries-clean.csv")
        print("  python convert_queries_for_json_api.py Kantar-queries.csv Kantar-queries-clean.csv --remove-hints")
        sys.exit(1)

    input_file = sys.argv[1]
    output_file = sys.argv[2]
    remove_hints = '--remove-hints' in sys.argv

    print(f"Converting queries from: {input_file}")
    print(f"Output to: {output_file}")
    if remove_hints:
        print("Removing optimizer hints: Yes")
    print()

    # Read input
    queries = []
    with open(input_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames

        for row in reader:
            queries.append(row)

    print(f"Loaded {len(queries)} queries")
    print()

    # Process each query
    for i, row in enumerate(queries, 1):
        # Find query column (QUERY, Query, query, SQL, etc.)
        query_col = None
        for col in row.keys():
            if col.upper() in ['QUERY', 'SQL', 'STATEMENT']:
                query_col = col
                break

        if not query_col:
            print(f"⚠️  Row {i}: Could not find query column, skipping")
            continue

        original = row[query_col]
        converted = convert_query(original, remove_hints)
        row[query_col] = converted

        print(f"✓ Query {i}: {len(original):,} → {len(converted):,} chars")

    # Write output
    with open(output_file, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in queries:
            writer.writerow(row)

    print()
    print(f"✅ Conversion complete! Output: {output_file}")
    print()
    print("Changes applied:")
    print("  ✓ Multiline → Single-line")
    print("  ✓ Backticks → Double quotes")
    print("  ✓ Reserved keywords quoted")
    print("  ✓ Schema names quoted (global, default)")
    print("  ✓ CTE syntax fixed (added AS)")
    print("  ✓ concat() → Concat()")
    print("  ✓ Double quotes escaped for JSON (\" → \\\")")
    if remove_hints:
        print("  ✓ Optimizer hints removed")

if __name__ == "__main__":
    main()
