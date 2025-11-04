#!/bin/bash
# JDBC Connection Test Runner
# Compiles and runs the TestDriver.java program with proper classpath

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color
BOLD='\033[1m'

# Function to print usage
print_usage() {
    echo -e "${BOLD}JDBC Connection Test Runner${NC}"
    echo "========================================="
    echo "Usage: $0 <connection_properties_file> [test_query]"
    echo ""
    echo "Examples:"
    echo "  $0 connection_properties/sample_connection.properties"
    echo "  $0 connection_properties/dbr_sample_connection.properties \"SELECT current_timestamp()\""
    echo "  $0 connection_properties/kantar_e6_connection.properties \"SELECT version()\""
    echo ""
    echo "Available connection property files:"
    if [ -d "connection_properties" ]; then
        ls connection_properties/*.properties 2>/dev/null | sed 's|connection_properties/||' | sed 's/^/  /'
    fi
    echo ""
}

# Check arguments
if [ $# -lt 1 ] || [ "$1" == "-h" ] || [ "$1" == "--help" ]; then
    print_usage
    exit 1
fi

PROPERTIES_FILE="$1"
TEST_QUERY="${2:-SELECT 1 as test_connection}"

# Check if properties file exists
if [ ! -f "$PROPERTIES_FILE" ]; then
    echo -e "${RED}❌ Properties file not found: $PROPERTIES_FILE${NC}"
    echo ""
    print_usage
    exit 1
fi

echo -e "${BLUE}🚀 JDBC Connection Test Runner${NC}"
echo "=================================="

# Get the script directory and project root
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Set Java classpath with all JDBC drivers
CLASSPATH="$SCRIPT_DIR:$PROJECT_ROOT/apache-jmeter-5.6.3/lib/ext/*"

echo -e "${YELLOW}🔧 Compiling TestDriver.java...${NC}"
javac -cp "$CLASSPATH" "$SCRIPT_DIR/TestDriver.java"

if [ $? -ne 0 ]; then
    echo -e "${RED}❌ Compilation failed${NC}"
    exit 1
fi

echo -e "${GREEN}✅ Compilation successful${NC}"
echo ""

echo -e "${YELLOW}🏃 Running JDBC test...${NC}"
echo "Properties file: $PROPERTIES_FILE"
echo "Test query: $TEST_QUERY"
echo ""

# Run the test (TestDriver is now in scripts directory)
java -cp "$CLASSPATH" TestDriver "$PROPERTIES_FILE" "$TEST_QUERY"

# Capture exit code
EXIT_CODE=$?

echo ""
if [ $EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}🎉 Test completed successfully!${NC}"
else
    echo -e "${RED}💥 Test failed with exit code: $EXIT_CODE${NC}"
fi

exit $EXIT_CODE