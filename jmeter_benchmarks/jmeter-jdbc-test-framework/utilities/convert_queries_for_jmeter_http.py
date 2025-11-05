#!/usr/bin/env python3
"""
Convert queries for JMeter HTTP JSON API - NO quote escaping needed!

JMeter substitutes ${QUERY} directly into the JSON template, so we should
NOT escape quotes. The quotes need to remain as-is for proper SQL execution.

Usage:
    python convert_queries_for_jmeter_http.py input.csv output.csv
"""

import csv
import re
import sys

KEYWORDS = ['year', 'week', 'month', 'quarter', 'period', 'date', 'format', 'variant']

def convert_query(query, remove_hints=False):
    """Convert multiline query to single-line WITHOUT quote escaping."""
    
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
        query = re.sub(r'\.(' + keyword + r')\b(?!\()', r'."\1"', query, flags=re.IGNORECASE)
    
    # 7. Fix concat → Concat
    query = re.sub(r'\bconcat\s*\(', 'Concat(', query, flags=re.IGNORECASE)
    
    # 8. Remove optimizer hints (optional)
    if remove_hints:
        query = re.sub(r'/\*\+[^*]*\*/', '', query)
        query = re.sub(r'\s+', ' ', query)
        query = query.strip()
    
    # NOTE: Do NOT escape quotes! JMeter will handle the JSON template properly.
    
    return query

def main():
    if len(sys.argv) < 3:
        print("Usage: python convert_queries_for_jmeter_http.py input.csv output.csv [--remove-hints]")
        sys.exit(1)

    input_file = sys.argv[1]
    output_file = sys.argv[2]
    remove_hints = '--remove-hints' in sys.argv

    print(f"Converting queries from: {input_file}")
    print(f"Output to: {output_file}")
    if remove_hints:
        print("Removing optimizer hints: Yes")
    print()

    queries = []
    with open(input_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        for row in reader:
            queries.append(row)

    print(f"Loaded {len(queries)} queries")
    print()

    for i, row in enumerate(queries, 1):
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

        if i <= 5 or i % 1000 == 0:
            print(f"✓ Query {i}: {len(original):,} → {len(converted):,} chars")

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
    print("  ✓ Quotes preserved (NOT escaped - JMeter handles JSON)")
    if remove_hints:
        print("  ✓ Optimizer hints removed")

if __name__ == "__main__":
    main()
