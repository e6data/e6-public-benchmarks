#!/bin/bash

# Convert multi-line CSV queries to single-line format for JMeter compatibility
# Usage: ./convert_multiline_csv.sh [OPTIONS] input.csv output.csv
#
# Options:
#   --keep-comments       Preserve SQL comments (default: remove)
#   --add-semicolon       Add semicolon to end of queries (default: remove)
#   --remove-semicolon    Remove semicolons from queries (default)
#   --help                Show this help message

# Parse command line options
KEEP_COMMENTS=false
ADD_SEMICOLON=false
INPUT_FILE=""
OUTPUT_FILE=""

show_usage() {
    echo "Usage: $0 [OPTIONS] input.csv output.csv"
    echo ""
    echo "Convert multi-line CSV queries to single-line format for JMeter compatibility"
    echo ""
    echo "Options:"
    echo "  --keep-comments       Preserve SQL comments (default: remove all comments)"
    echo "  --add-semicolon       Add semicolon to end of queries"
    echo "  --remove-semicolon    Remove semicolons from queries (default)"
    echo "  --help                Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 input.csv output.csv"
    echo "  $0 --keep-comments input.csv output.csv"
    echo "  $0 --add-semicolon input.csv output.csv"
    exit 1
}

while [[ $# -gt 0 ]]; do
    case $1 in
        --keep-comments)
            KEEP_COMMENTS=true
            shift
            ;;
        --add-semicolon)
            ADD_SEMICOLON=true
            shift
            ;;
        --remove-semicolon)
            ADD_SEMICOLON=false
            shift
            ;;
        --help)
            show_usage
            ;;
        *)
            if [ -z "$INPUT_FILE" ]; then
                INPUT_FILE="$1"
            elif [ -z "$OUTPUT_FILE" ]; then
                OUTPUT_FILE="$1"
            else
                echo "❌ Error: Unexpected argument '$1'"
                show_usage
            fi
            shift
            ;;
    esac
done

if [ -z "$INPUT_FILE" ] || [ -z "$OUTPUT_FILE" ]; then
    echo "❌ Error: Missing required arguments"
    show_usage
fi

if [ ! -f "$INPUT_FILE" ]; then
    echo "❌ Input file not found: $INPUT_FILE"
    exit 1
fi

echo "🔄 Converting multi-line CSV to single-line format..."
echo "Input: $INPUT_FILE"
echo "Output: $OUTPUT_FILE"
echo "Options: Keep Comments=$KEEP_COMMENTS, Add Semicolon=$ADD_SEMICOLON"
echo ""

# Use Python to properly handle CSV parsing and convert to single-line
python3 - "$INPUT_FILE" "$OUTPUT_FILE" "$KEEP_COMMENTS" "$ADD_SEMICOLON" << 'EOF'
import csv
import sys
import re

input_file = sys.argv[1]
output_file = sys.argv[2]
keep_comments = sys.argv[3].lower() == 'true'
add_semicolon = sys.argv[4].lower() == 'true'

def clean_query(query_text, keep_comments, add_semicolon):
    """Clean and normalize a SQL query to single-line format.

    Args:
        query_text: Original multi-line query text
        keep_comments: If False, remove SQL comments
        add_semicolon: If True, ensure query ends with semicolon

    Returns:
        Cleaned single-line query string
    """
    original_length = len(query_text)

    # Step 1: Remove comments BEFORE collapsing whitespace (if requested)
    if not keep_comments:
        # Remove block comments /* ... */ (non-greedy, handles multiline)
        query_text = re.sub(r'/\*.*?\*/', '', query_text, flags=re.DOTALL)

        # Remove single-line comments -- ... (to end of line)
        query_text = re.sub(r'--[^\n]*', '', query_text)

    # Step 2: Collapse all whitespace (newlines, tabs, multiple spaces) to single spaces
    query_cleaned = ' '.join(query_text.split())

    # Step 3: Handle semicolons
    query_cleaned = query_cleaned.strip()

    # Remove existing semicolon(s) first
    while query_cleaned.endswith(';'):
        query_cleaned = query_cleaned[:-1].strip()

    # Add semicolon if requested
    if add_semicolon:
        query_cleaned += ';'

    return query_cleaned, original_length

try:
    rows_processed = 0
    rows_skipped = 0
    rows_empty = 0

    with open(input_file, 'r', encoding='utf-8') as infile, \
         open(output_file, 'w', encoding='utf-8', newline='') as outfile:

        # Use csv.reader to properly parse quoted multi-line fields
        reader = csv.reader(infile)
        writer = csv.writer(outfile, quoting=csv.QUOTE_MINIMAL)

        for row_num, row in enumerate(reader):
            # Preserve header row
            if row_num == 0:
                writer.writerow(row)
                print(f"✅ Header: {', '.join(row)}")
                continue

            # Validate row has sufficient columns
            if len(row) < 2:
                print(f"⚠️  Row {row_num}: Skipping - insufficient columns (has {len(row)}, need 2)")
                rows_skipped += 1
                continue

            query_alias = row[0].strip()
            query_text = row[1]

            # Clean the query
            query_cleaned, original_length = clean_query(query_text, keep_comments, add_semicolon)

            # Validate non-empty after cleaning
            if not query_cleaned:
                print(f"⚠️  Row {row_num} ({query_alias}): Skipping - query is empty after cleaning")
                rows_empty += 1
                continue

            # Preserve original query alias (don't replace with numeric ID)
            writer.writerow([query_alias, query_cleaned])

            # Show progress
            compression_ratio = len(query_cleaned) / original_length * 100 if original_length > 0 else 0
            print(f"✅ Row {row_num} ({query_alias}): {original_length} → {len(query_cleaned)} chars ({compression_ratio:.1f}%)")
            rows_processed += 1

    # Summary
    print("")
    print("=" * 60)
    print("✅ Conversion completed successfully!")
    print(f"   Rows processed: {rows_processed}")
    if rows_skipped > 0:
        print(f"   Rows skipped (insufficient columns): {rows_skipped}")
    if rows_empty > 0:
        print(f"   Rows skipped (empty after cleaning): {rows_empty}")
    print(f"   Total rows in output: {rows_processed + 1} (including header)")
    print("=" * 60)

except FileNotFoundError as e:
    print(f"❌ Error: File not found - {e}")
    sys.exit(1)
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

EOF