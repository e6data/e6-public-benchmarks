#!/bin/bash

# Script: analyze_aggregate_report.sh
# Purpose: Analyze JMeter aggregate report CSV files and generate comprehensive summary
# Usage: ./analyze_aggregate_report.sh <aggregate_report.csv>

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color
BOLD='\033[1m'

# Check if file argument is provided
if [ $# -eq 0 ]; then
    echo -e "${RED}Error: No file provided${NC}"
    echo "Usage: $0 <aggregate_report.csv>"
    exit 1
fi

INPUT_FILE="$1"

# Check if file exists
if [ ! -f "$INPUT_FILE" ]; then
    echo -e "${RED}Error: File '$INPUT_FILE' not found${NC}"
    exit 1
fi

# Check if file is not empty
if [ ! -s "$INPUT_FILE" ]; then
    echo -e "${RED}Error: File '$INPUT_FILE' is empty${NC}"
    exit 1
fi

echo -e "${BOLD}${BLUE}═══════════════════════════════════════════════════════════════════${NC}"
echo -e "${BOLD}${BLUE}           JMeter Aggregate Report Analysis${NC}"
echo -e "${BOLD}${BLUE}═══════════════════════════════════════════════════════════════════${NC}"
echo

# Display file information
echo -e "${CYAN}📁 File Analysis:${NC}"
echo -e "   File: ${YELLOW}$(basename "$INPUT_FILE")${NC}"
echo -e "   Path: ${YELLOW}$(dirname "$INPUT_FILE")${NC}"
echo -e "   Size: ${YELLOW}$(ls -lh "$INPUT_FILE" | awk '{print $5}')${NC}"
echo -e "   Modified: ${YELLOW}$(stat -f "%Sm" -t "%Y-%m-%d %H:%M:%S" "$INPUT_FILE" 2>/dev/null || stat -c "%y" "$INPUT_FILE" 2>/dev/null | cut -d' ' -f1,2)${NC}"
echo

# Count total queries (excluding header)
TOTAL_QUERIES=$(grep -c "^[0-9]" "$INPUT_FILE")

# Count successful and failed queries
SUCCESS_COUNT=$(grep -c ",true," "$INPUT_FILE")
FAILED_COUNT=$(grep -c ",false," "$INPUT_FILE")

# Calculate percentages
if [ "$TOTAL_QUERIES" -gt 0 ]; then
    SUCCESS_PERCENT=$(awk "BEGIN {printf \"%.1f\", ($SUCCESS_COUNT/$TOTAL_QUERIES)*100}")
    FAILED_PERCENT=$(awk "BEGIN {printf \"%.1f\", ($FAILED_COUNT/$TOTAL_QUERIES)*100}")
else
    SUCCESS_PERCENT="0.0"
    FAILED_PERCENT="0.0"
fi

# Display overall statistics
echo -e "${CYAN}📊 Overall Statistics:${NC}"
echo -e "   ${BOLD}Total Queries:${NC} ${YELLOW}$TOTAL_QUERIES${NC}"
echo -e "   ${GREEN}✓ Successful:${NC} $SUCCESS_COUNT (${SUCCESS_PERCENT}%)"
echo -e "   ${RED}✗ Failed:${NC} $FAILED_COUNT (${FAILED_PERCENT}%)"
echo

# Get timing information
if [ "$TOTAL_QUERIES" -gt 0 ]; then
    # Get first and last timestamps (in milliseconds)
    FIRST_TIMESTAMP=$(grep "^[0-9]" "$INPUT_FILE" | head -1 | cut -d',' -f1)
    LAST_TIMESTAMP=$(grep "^[0-9]" "$INPUT_FILE" | tail -1 | cut -d',' -f1)
    
    if [ -n "$FIRST_TIMESTAMP" ] && [ -n "$LAST_TIMESTAMP" ]; then
        # Calculate duration in seconds
        DURATION_MS=$((LAST_TIMESTAMP - FIRST_TIMESTAMP))
        DURATION_SEC=$((DURATION_MS / 1000))
        DURATION_MIN=$((DURATION_SEC / 60))
        DURATION_SEC_REMAINDER=$((DURATION_SEC % 60))
        
        echo -e "${CYAN}⏱️  Test Duration:${NC}"
        echo -e "   Duration: ${YELLOW}${DURATION_MIN}m ${DURATION_SEC_REMAINDER}s${NC}"
        
        # Calculate queries per second
        if [ "$DURATION_SEC" -gt 0 ]; then
            QPS=$(awk "BEGIN {printf \"%.2f\", $TOTAL_QUERIES/$DURATION_SEC}")
            echo -e "   Throughput: ${YELLOW}${QPS} queries/sec${NC}"
        fi
        echo
    fi
fi

# Analyze errors if any exist
if [ "$FAILED_COUNT" -gt 0 ]; then
    echo -e "${CYAN}❌ Error Analysis:${NC}"
    echo
    
    # Create temporary file for error analysis
    TEMP_ERROR_FILE=$(mktemp)
    
    # Extract error messages from failed requests
    grep ",false," "$INPUT_FILE" > "$TEMP_ERROR_FILE"
    
    # Count unique error types
    echo -e "${BOLD}   Unique Error Types:${NC}"
    
    # Extract and count HTTP errors
    HTTP_403_COUNT=$(grep -c "HTTP Response code: 403" "$TEMP_ERROR_FILE" 2>/dev/null)
    HTTP_500_COUNT=$(grep -c "HTTP Response code: 500" "$TEMP_ERROR_FILE" 2>/dev/null)
    HTTP_TOTAL_COUNT=$(grep -c "HTTP Response code:" "$TEMP_ERROR_FILE" 2>/dev/null)
    
    # Set defaults if empty
    [ -z "$HTTP_403_COUNT" ] && HTTP_403_COUNT=0
    [ -z "$HTTP_500_COUNT" ] && HTTP_500_COUNT=0
    [ -z "$HTTP_TOTAL_COUNT" ] && HTTP_TOTAL_COUNT=0
    
    # Safely calculate other HTTP errors
    HTTP_OTHER_COUNT=0
    if [ "$HTTP_TOTAL_COUNT" -gt 0 ]; then
        HTTP_OTHER_COUNT=$((HTTP_TOTAL_COUNT - HTTP_403_COUNT - HTTP_500_COUNT))
        [ "$HTTP_OTHER_COUNT" -lt 0 ] && HTTP_OTHER_COUNT=0
    fi
    
    if [ "$HTTP_403_COUNT" -gt 0 ]; then
        echo -e "   ${RED}• HTTP 403 (Forbidden):${NC} $HTTP_403_COUNT occurrences"
    fi
    
    if [ "$HTTP_500_COUNT" -gt 0 ]; then
        echo -e "   ${RED}• HTTP 500 (Server Error):${NC} $HTTP_500_COUNT occurrences"
    fi
    
    if [ "$HTTP_OTHER_COUNT" -gt 0 ]; then
        echo -e "   ${RED}• Other HTTP Errors:${NC} $HTTP_OTHER_COUNT occurrences"
    fi
    
    # Check for SQL exceptions
    SQL_EXCEPTION_COUNT=$(grep -c "java.sql.SQLException" "$TEMP_ERROR_FILE" 2>/dev/null)
    [ -z "$SQL_EXCEPTION_COUNT" ] && SQL_EXCEPTION_COUNT=0
    
    if [ "$SQL_EXCEPTION_COUNT" -gt 0 ]; then
        # Extract unique SQL error codes
        SQL_ERROR_CODES=$(grep -o "SQLException: \[.*\]\[.*\](\([0-9]*\))" "$TEMP_ERROR_FILE" | sed 's/.*(\([0-9]*\)).*/\1/' | sort -u)
        
        echo -e "   ${RED}• SQL Exceptions:${NC} $SQL_EXCEPTION_COUNT total"
        
        for ERROR_CODE in $SQL_ERROR_CODES; do
            CODE_COUNT=$(grep -c "($ERROR_CODE)" "$TEMP_ERROR_FILE")
            case "$ERROR_CODE" in
                "500593")
                    echo -e "     - Error $ERROR_CODE (Communication link failure): $CODE_COUNT"
                    ;;
                "500051")
                    echo -e "     - Error $ERROR_CODE (Query processing error): $CODE_COUNT"
                    ;;
                *)
                    echo -e "     - Error $ERROR_CODE: $CODE_COUNT"
                    ;;
            esac
        done
    fi
    
    # Check for Spark exceptions
    SPARK_EXCEPTION_COUNT=$(grep -c "org.apache.spark.SparkException" "$TEMP_ERROR_FILE" 2>/dev/null)
    [ -z "$SPARK_EXCEPTION_COUNT" ] && SPARK_EXCEPTION_COUNT=0
    
    if [ "$SPARK_EXCEPTION_COUNT" -gt 0 ]; then
        echo -e "   ${RED}• Spark Exceptions:${NC} $SPARK_EXCEPTION_COUNT occurrences"
        
        # Check for specific Spark errors
        SCALAR_SUBQUERY_COUNT=$(grep -c "SCALAR_SUBQUERY_TOO_MANY_ROWS" "$TEMP_ERROR_FILE" 2>/dev/null)
        [ -z "$SCALAR_SUBQUERY_COUNT" ] && SCALAR_SUBQUERY_COUNT=0
        
        if [ "$SCALAR_SUBQUERY_COUNT" -gt 0 ]; then
            echo -e "     - Scalar subquery returning multiple rows: $SCALAR_SUBQUERY_COUNT"
        fi
        
        STAGE_MAT_COUNT=$(grep -c "Multiple failures in stage materialization" "$TEMP_ERROR_FILE" 2>/dev/null)
        [ -z "$STAGE_MAT_COUNT" ] && STAGE_MAT_COUNT=0
        
        if [ "$STAGE_MAT_COUNT" -gt 0 ]; then
            echo -e "     - Stage materialization failures: $STAGE_MAT_COUNT"
        fi
    fi
    
    # Check for timeout errors
    TIMEOUT_COUNT=$(grep -ic "timeout" "$TEMP_ERROR_FILE" 2>/dev/null)
    [ -z "$TIMEOUT_COUNT" ] && TIMEOUT_COUNT=0
    
    if [ "$TIMEOUT_COUNT" -gt 0 ]; then
        echo -e "   ${RED}• Timeout Errors:${NC} $TIMEOUT_COUNT occurrences"
    fi
    
    echo
    
    # Show error timeline
    echo -e "${BOLD}   Error Timeline:${NC}"
    
    # Get first error occurrence
    FIRST_ERROR_LINE=$(grep -n ",false," "$INPUT_FILE" | head -1 | cut -d':' -f1)
    if [ -n "$FIRST_ERROR_LINE" ]; then
        FIRST_ERROR_QUERY=$(grep ",false," "$INPUT_FILE" | head -1 | cut -d',' -f3)
        echo -e "   First error: Query #${YELLOW}${FIRST_ERROR_QUERY}${NC} (Line $FIRST_ERROR_LINE)"
        
        # Check if errors are continuous or intermittent
        LAST_SUCCESS_BEFORE_ERRORS=$(head -n "$FIRST_ERROR_LINE" "$INPUT_FILE" | grep ",true," | tail -1 | cut -d',' -f3)
        if [ -n "$LAST_SUCCESS_BEFORE_ERRORS" ]; then
            echo -e "   Last success before errors: Query #${GREEN}${LAST_SUCCESS_BEFORE_ERRORS}${NC}"
        fi
    fi
    
    # Clean up temp file
    rm -f "$TEMP_ERROR_FILE"
    
    echo
fi

# Response time analysis (if no errors or limited errors for performance insight)
echo -e "${CYAN}⚡ Performance Metrics:${NC}"

# Calculate average, min, max response times for successful requests
if [ "$SUCCESS_COUNT" -gt 0 ]; then
    RESPONSE_TIMES=$(grep ",true," "$INPUT_FILE" | cut -d',' -f2 | grep -E '^[0-9]+$')
    
    if [ -n "$RESPONSE_TIMES" ]; then
        # Use awk for calculations
        STATS=$(echo "$RESPONSE_TIMES" | awk '
            BEGIN {min=999999999; max=0; sum=0; count=0}
            {
                sum+=$1; 
                count++; 
                if($1<min) min=$1; 
                if($1>max) max=$1
            }
            END {
                if(count>0) {
                    avg=sum/count;
                    printf "%.0f %.0f %.0f", min, max, avg
                }
            }
        ')
        
        if [ -n "$STATS" ]; then
            MIN_TIME=$(echo "$STATS" | cut -d' ' -f1)
            MAX_TIME=$(echo "$STATS" | cut -d' ' -f2)
            AVG_TIME=$(echo "$STATS" | cut -d' ' -f3)
            
            echo -e "   Response Times (successful queries):"
            echo -e "     Min: ${GREEN}${MIN_TIME}ms${NC}"
            echo -e "     Max: ${YELLOW}${MAX_TIME}ms${NC}"
            echo -e "     Avg: ${CYAN}${AVG_TIME}ms${NC}"
            
            # Calculate percentiles
            SORTED_TIMES=$(echo "$RESPONSE_TIMES" | sort -n)
            TOTAL_LINES=$(echo "$SORTED_TIMES" | wc -l)
            
            if [ "$TOTAL_LINES" -gt 0 ]; then
                P50_LINE=$((TOTAL_LINES * 50 / 100))
                P90_LINE=$((TOTAL_LINES * 90 / 100))
                P95_LINE=$((TOTAL_LINES * 95 / 100))
                P99_LINE=$((TOTAL_LINES * 99 / 100))
                
                [ "$P50_LINE" -eq 0 ] && P50_LINE=1
                [ "$P90_LINE" -eq 0 ] && P90_LINE=1
                [ "$P95_LINE" -eq 0 ] && P95_LINE=1
                [ "$P99_LINE" -eq 0 ] && P99_LINE=1
                
                P50=$(echo "$SORTED_TIMES" | sed -n "${P50_LINE}p")
                P90=$(echo "$SORTED_TIMES" | sed -n "${P90_LINE}p")
                P95=$(echo "$SORTED_TIMES" | sed -n "${P95_LINE}p")
                P99=$(echo "$SORTED_TIMES" | sed -n "${P99_LINE}p")
                
                echo -e "   Percentiles:"
                echo -e "     P50: ${CYAN}${P50}ms${NC}"
                echo -e "     P90: ${YELLOW}${P90}ms${NC}"
                echo -e "     P95: ${YELLOW}${P95}ms${NC}"
                echo -e "     P99: ${RED}${P99}ms${NC}"
            fi
        fi
    fi
fi

echo
echo -e "${BOLD}${BLUE}═══════════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}✓ Analysis Complete${NC}"
echo -e "${BOLD}${BLUE}═══════════════════════════════════════════════════════════════════${NC}"