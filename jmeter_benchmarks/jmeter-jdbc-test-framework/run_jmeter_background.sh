#!/bin/bash
# Background JMeter Test Runner
#
# Usage: ./run_jmeter_background.sh <metadata_file> <test_plan> <test_properties> <connection_properties> <queries_file>
#
# Example:
#   ./run_jmeter_background.sh \
#     metadata_files/my_test_metadata.txt \
#     Test-Plans/Test-Plan-Fire-QPS-with-load-profile.jmx \
#     test_properties/my_test.properties \
#     connection_properties/my_connection.properties \
#     data_files/my_queries.csv

# Check if all arguments are provided
if [ $# -ne 5 ]; then
    echo "Error: Missing required arguments"
    echo ""
    echo "Usage: $0 <metadata_file> <test_plan> <test_properties> <connection_properties> <queries_file>"
    echo ""
    echo "Example:"
    echo "  $0 \\"
    echo "    metadata_files/sample_metadata.txt \\"
    echo "    Test-Plans/Test-Plan-Fire-QPS-with-load-profile.jmx \\"
    echo "    test_properties/sample_test.properties \\"
    echo "    connection_properties/sample_connection.properties \\"
    echo "    data_files/sample_jmeter_queries.csv"
    echo ""
    exit 1
fi

# Assign arguments to variables
METADATA_FILE="$1"
TEST_PLAN="$2"
TEST_PROPERTIES="$3"
CONNECTION_PROPERTIES="$4"
QUERIES_FILE="$5"

# Validate files exist
for file in "$METADATA_FILE" "Test-Plans/$TEST_PLAN" "test_properties/$TEST_PROPERTIES" "connection_properties/$CONNECTION_PROPERTIES" "data_files/$QUERIES_FILE"; do
    if [ ! -f "$file" ]; then
        echo "❌ Error: File not found: $file"
        exit 1
    fi
done

# Create log filename with timestamp
LOG_FILE="jmeter_run_$(date +%Y%m%d_%H%M%S).log"

echo "=========================================="
echo "Starting JMeter Test in Background"
echo "=========================================="
echo "Metadata:    $METADATA_FILE"
echo "Test Plan:   $TEST_PLAN"
echo "Test Props:  $TEST_PROPERTIES"
echo "Connection:  $CONNECTION_PROPERTIES"
echo "Queries:     $QUERIES_FILE"
echo "Log File:    $LOG_FILE"
echo "=========================================="
echo ""

# Run the test in background with nohup
nohup ./run_jmeter_tests_interactive.sh << INPUT > "$LOG_FILE" 2>&1 &
$METADATA_FILE
$TEST_PLAN
$TEST_PROPERTIES
$CONNECTION_PROPERTIES
$QUERIES_FILE
INPUT

PID=$!

echo "✅ JMeter test started in background"
echo "   Process ID: $PID"
echo ""
echo "Monitor progress with:"
echo "   tail -f $LOG_FILE"
echo ""
echo "Check if running:"
echo "   ps -p $PID"
echo ""
echo "Stop the test:"
echo "   kill $PID"
echo ""
