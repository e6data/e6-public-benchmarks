#!/bin/bash

# Databricks Connectivity Test Script
# Usage: ./test_databricks_connectivity.sh [connection_properties_file] [iterations]

CONNECTION_FILE="${1:-connection_properties/dbr_kantar_connection.properties}"
ITERATIONS="${2:-5}"
DELAY_BETWEEN_TESTS="${3:-10}"

echo "==================================================================="
echo "Databricks Intermittent Connectivity Diagnostic Tool"
echo "==================================================================="
echo "Connection File: $CONNECTION_FILE"
echo "Test Iterations: $ITERATIONS"
echo "Delay Between Tests: ${DELAY_BETWEEN_TESTS}s"
echo "==================================================================="

# Extract connection details
if [ -f "$CONNECTION_FILE" ]; then
    CONNECTION_STRING=$(grep "^CONNECTION_STRING=" "$CONNECTION_FILE" | cut -d'=' -f2)
    HOSTNAME=$(echo "$CONNECTION_STRING" | grep -o '://[^:]*' | sed 's/^:\/\///')
    echo "Databricks Host: $HOSTNAME"
    echo "Full Connection String: $CONNECTION_STRING"
else
    echo "❌ Connection file not found: $CONNECTION_FILE"
    exit 1
fi

echo "==================================================================="

# Function to test connectivity
test_connectivity() {
    local iteration=$1
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    
    echo "[$timestamp] Test #$iteration:"
    
    # DNS Resolution Test
    DNS_TIME=$(dig +short +time=1 +tries=1 "$HOSTNAME" 2>/dev/null | wc -l)
    if [ "$DNS_TIME" -gt 0 ]; then
        echo "  ✅ DNS Resolution: OK"
    else
        echo "  ❌ DNS Resolution: FAILED"
        return 1
    fi
    
    # Basic HTTPS Connectivity Test  
    CURL_OUTPUT=$(curl -s -w "status:%{http_code},connect:%{time_connect},total:%{time_total}" -m 10 -o /dev/null "https://$HOSTNAME/" 2>/dev/null)
    HTTP_STATUS=$(echo "$CURL_OUTPUT" | grep -o 'status:[0-9]*' | cut -d':' -f2)
    CONNECT_TIME=$(echo "$CURL_OUTPUT" | grep -o 'connect:[0-9.]*' | cut -d':' -f2)
    TOTAL_TIME=$(echo "$CURL_OUTPUT" | grep -o 'total:[0-9.]*' | cut -d':' -f2)
    
    if [ "$HTTP_STATUS" = "303" ] || [ "$HTTP_STATUS" = "200" ] || [ "$HTTP_STATUS" = "401" ]; then
        echo "  ✅ HTTPS Connectivity: OK (Status: $HTTP_STATUS, Connect: ${CONNECT_TIME}s)"
    else
        echo "  ❌ HTTPS Connectivity: FAILED (Status: $HTTP_STATUS)"
        return 1
    fi
    
    # SQL Warehouse Endpoint Test (port 443)
    SQL_ENDPOINT_TEST=$(timeout 5 nc -z "$HOSTNAME" 443 2>/dev/null && echo "OK" || echo "FAILED")
    if [ "$SQL_ENDPOINT_TEST" = "OK" ]; then
        echo "  ✅ SQL Warehouse Port 443: OK"
    else
        echo "  ❌ SQL Warehouse Port 443: FAILED"
        return 1
    fi
    
    echo "  📊 Network Metrics: Connect=${CONNECT_TIME}s, Total=${TOTAL_TIME}s"
    return 0
}

# Run connectivity tests
PASSED=0
FAILED=0

for i in $(seq 1 $ITERATIONS); do
    if test_connectivity "$i"; then
        ((PASSED++))
        echo "  ✅ Test #$i: PASSED"
    else
        ((FAILED++))
        echo "  ❌ Test #$i: FAILED"
    fi
    
    echo "  ---"
    
    # Wait between tests (except for the last one)
    if [ $i -lt $ITERATIONS ]; then
        sleep $DELAY_BETWEEN_TESTS
    fi
done

echo "==================================================================="
echo "TEST SUMMARY:"
echo "  Total Tests: $ITERATIONS"
echo "  Passed: $PASSED ($((PASSED * 100 / ITERATIONS))%)"
echo "  Failed: $FAILED ($((FAILED * 100 / ITERATIONS))%)"
echo "==================================================================="

if [ $FAILED -gt 0 ]; then
    echo "⚠️  INTERMITTENT CONNECTIVITY DETECTED!"
    echo ""
    echo "Possible Causes:"
    echo "1. Network instability between client and Azure West Europe"
    echo "2. Databricks SQL Warehouse auto-suspend/resume cycles"
    echo "3. Azure load balancer health checks"
    echo "4. DNS propagation issues"
    echo "5. Rate limiting or throttling"
    echo ""
    echo "Recommendations:"
    echo "- Add connection retry logic with exponential backoff"
    echo "- Increase connection pool timeout settings"
    echo "- Monitor warehouse state before testing"
    echo "- Consider using connection validation queries"
else
    echo "✅ All connectivity tests passed!"
fi