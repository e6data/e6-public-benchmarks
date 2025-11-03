#!/bin/bash
#
# JMeter Setup Script
# Downloads Apache JMeter 5.6.3 and installs custom JDBC drivers
#
# Usage: ./setup_jmeter.sh
#

set -e  # Exit on error

JMETER_VERSION="5.6.3"
JMETER_DIR="apache-jmeter-${JMETER_VERSION}"
JMETER_ARCHIVE="apache-jmeter-${JMETER_VERSION}.tgz"
JMETER_URL="https://archive.apache.org/dist/jmeter/binaries/${JMETER_ARCHIVE}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=================================================="
echo "JMeter JDBC Test Framework Setup"
echo "=================================================="
echo ""

# Check if JMeter is already set up
if [ -d "${SCRIPT_DIR}/${JMETER_DIR}/lib" ] && [ -f "${SCRIPT_DIR}/${JMETER_DIR}/bin/jmeter" ]; then
    echo "✓ JMeter ${JMETER_VERSION} is already installed"
    echo ""
    echo "To reinstall, run: rm -rf ${JMETER_DIR} && ./setup_jmeter.sh"
    exit 0
fi

echo "Step 1: Downloading Apache JMeter ${JMETER_VERSION}..."
echo "URL: ${JMETER_URL}"
echo ""

if command -v wget &> /dev/null; then
    wget -q "${JMETER_URL}" || { echo "ERROR: Download failed"; exit 1; }
elif command -v curl &> /dev/null; then
    curl -L -# -O "${JMETER_URL}" || { echo "ERROR: Download failed"; exit 1; }
else
    echo "ERROR: Neither wget nor curl found. Please install one of them."
    exit 1
fi

echo ""
echo "Step 2: Extracting JMeter..."
tar -xzf "${JMETER_ARCHIVE}"
rm "${JMETER_ARCHIVE}"

echo ""
echo "Step 3: Installing custom JDBC drivers..."

# Create jdbc_drivers directory if it doesn't exist
JDBC_DRIVERS_DIR="${SCRIPT_DIR}/jdbc_drivers"
if [ -d "${JDBC_DRIVERS_DIR}" ]; then
    # Copy custom JDBC drivers from jdbc_drivers/ to JMeter lib/ext/
    cp -v "${JDBC_DRIVERS_DIR}"/*.jar "${JMETER_DIR}/lib/ext/" 2>/dev/null || {
        echo "  No custom JDBC drivers found in jdbc_drivers/"
    }
else
    echo "  WARNING: jdbc_drivers/ directory not found"
    echo "  You'll need to manually add JDBC drivers to ${JMETER_DIR}/lib/ext/"
fi

echo ""
echo "Step 4: Creating reports directory..."
mkdir -p "${SCRIPT_DIR}/reports"

echo ""
echo "=================================================="
echo "✓ Setup Complete!"
echo "=================================================="
echo ""
echo "JMeter ${JMETER_VERSION} installed at:"
echo "  ${SCRIPT_DIR}/${JMETER_DIR}"
echo ""
echo "Next steps:"
echo "  1. Copy your JDBC drivers to jdbc_drivers/ (if not already there)"
echo "  2. Create connection properties in connection_properties/"
echo "  3. Run tests with: ./run_jmeter_tests_interactive.sh"
echo ""
echo "To verify installation:"
echo "  ${JMETER_DIR}/bin/jmeter --version"
echo ""
