#!/bin/bash
#
# JMeter JDBC Test Framework Setup Script
#
# This script will:
# 1. Check/install required dependencies (Java 17, jq, git)
# 2. Download Apache JMeter 5.6.3
# 3. Install custom JDBC drivers
# 4. Create necessary directories
# 5. Configure JAVA_HOME
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

# Detect OS
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS=$ID
    VERSION_ID=$VERSION_ID
else
    OS=$(uname -s)
fi

echo "Detected OS: $OS"
echo ""

# Function to check if command exists
command_exists() {
    command -v "$1" &> /dev/null
}

# Function to check Java version
check_java_version() {
    if command_exists java; then
        JAVA_VER=$(java -version 2>&1 | awk -F '"' '/version/ {print $2}' | cut -d. -f1)
        if [ "$JAVA_VER" -ge 17 ] 2>/dev/null; then
            return 0
        fi
    fi
    return 1
}

# Function to install Java 17
install_java() {
    echo "Step 1: Installing Java 17..."
    echo ""

    case $OS in
        amzn|amazonlinux)
            echo "Installing Java 17 (Amazon Corretto) on Amazon Linux..."
            if command_exists dnf; then
                # Amazon Linux 2023
                sudo dnf install -y java-17-amazon-corretto-devel
            else
                # Amazon Linux 2
                sudo yum install -y java-17-amazon-corretto-devel
            fi
            ;;
        ubuntu|debian)
            echo "Installing Java 17 (OpenJDK) on Ubuntu/Debian..."
            sudo apt update
            sudo apt install -y openjdk-17-jdk
            ;;
        centos|rhel|fedora)
            echo "Installing Java 17 (OpenJDK) on $OS..."
            sudo yum install -y java-17-openjdk-devel
            ;;
        *)
            echo "WARNING: Unsupported OS for automatic Java installation: $OS"
            echo "Please install Java 17 manually and re-run this script."
            echo ""
            echo "Manual installation:"
            echo "  wget https://download.java.net/java/GA/jdk17.0.2/dfd4a8d0985749f896bed50d7138ee7f/8/GPL/openjdk-17.0.2_linux-x64_bin.tar.gz"
            echo "  tar -xvf openjdk-17.0.2_linux-x64_bin.tar.gz"
            echo "  sudo mv jdk-17.0.2 /usr/local/"
            echo "  export JAVA_HOME=/usr/local/jdk-17.0.2"
            exit 1
            ;;
    esac

    echo ""
}

# Function to configure JAVA_HOME
configure_java_home() {
    echo "Configuring JAVA_HOME..."

    # Try to find Java installation
    if [ -d "/usr/lib/jvm/java-17-amazon-corretto.aarch64" ]; then
        JAVA_HOME_PATH="/usr/lib/jvm/java-17-amazon-corretto.aarch64"
    elif [ -d "/usr/lib/jvm/java-17-amazon-corretto.x86_64" ]; then
        JAVA_HOME_PATH="/usr/lib/jvm/java-17-amazon-corretto.x86_64"
    elif [ -d "/usr/lib/jvm/java-17-amazon-corretto" ]; then
        JAVA_HOME_PATH="/usr/lib/jvm/java-17-amazon-corretto"
    elif [ -d "/usr/lib/jvm/java-17-openjdk-amd64" ]; then
        JAVA_HOME_PATH="/usr/lib/jvm/java-17-openjdk-amd64"
    elif [ -d "/usr/lib/jvm/java-17-openjdk" ]; then
        JAVA_HOME_PATH="/usr/lib/jvm/java-17-openjdk"
    else
        echo "WARNING: Could not auto-detect JAVA_HOME"
        echo "Please set JAVA_HOME manually:"
        echo "  export JAVA_HOME=/path/to/java-17"
        echo "  echo 'export JAVA_HOME=/path/to/java-17' >> ~/.bashrc"
        return
    fi

    export JAVA_HOME="$JAVA_HOME_PATH"

    # Add to bashrc if not already there
    if ! grep -q "JAVA_HOME.*$JAVA_HOME_PATH" ~/.bashrc 2>/dev/null; then
        echo "export JAVA_HOME=$JAVA_HOME_PATH" >> ~/.bashrc
        echo "Added JAVA_HOME to ~/.bashrc"
    fi

    echo "✓ JAVA_HOME set to: $JAVA_HOME"
    echo ""
}

# Function to install jq
install_jq() {
    echo "Installing jq..."

    case $OS in
        amzn|amazonlinux)
            if command_exists dnf; then
                sudo dnf install -y jq
            else
                sudo yum install -y jq
            fi
            ;;
        ubuntu|debian)
            sudo apt install -y jq
            ;;
        centos|rhel|fedora)
            sudo yum install -y jq
            ;;
        *)
            echo "WARNING: Unsupported OS for automatic jq installation: $OS"
            echo "Please install jq manually."
            ;;
    esac

    echo ""
}

# Function to install git
install_git() {
    echo "Installing git..."

    case $OS in
        amzn|amazonlinux)
            if command_exists dnf; then
                sudo dnf install -y git
            else
                sudo yum install -y git
            fi
            ;;
        ubuntu|debian)
            sudo apt install -y git
            ;;
        centos|rhel|fedora)
            sudo yum install -y git
            ;;
        *)
            echo "WARNING: Unsupported OS for automatic git installation: $OS"
            echo "Please install git manually."
            ;;
    esac

    echo ""
}

# Check and install Java 17
if check_java_version; then
    echo "✓ Java 17+ already installed: $(java -version 2>&1 | head -1)"
    echo ""
else
    install_java
    configure_java_home
fi

# Verify Java installation
if ! check_java_version; then
    echo "ERROR: Java 17+ is required but not found after installation"
    echo "Please install Java 17 manually and re-run this script"
    exit 1
fi

# Check and install jq
if command_exists jq; then
    echo "✓ jq already installed: $(jq --version)"
    echo ""
else
    install_jq
fi

# Check and install git
if command_exists git; then
    echo "✓ git already installed: $(git --version)"
    echo ""
else
    install_git
fi

# Check if JMeter is already set up
if [ -d "${SCRIPT_DIR}/${JMETER_DIR}/lib" ] && [ -f "${SCRIPT_DIR}/${JMETER_DIR}/bin/jmeter" ]; then
    echo "✓ JMeter ${JMETER_VERSION} is already installed"
    echo ""
    echo "To reinstall, run: rm -rf ${JMETER_DIR} && ./setup_jmeter.sh"
    exit 0
fi

echo "=================================================="
echo "Installing Apache JMeter ${JMETER_VERSION}"
echo "=================================================="
echo ""

echo "Step 2: Downloading Apache JMeter ${JMETER_VERSION}..."
echo "URL: ${JMETER_URL}"
echo ""

if command_exists wget; then
    wget "${JMETER_URL}" || { echo "ERROR: Download failed"; exit 1; }
elif command_exists curl; then
    curl -L -# -O "${JMETER_URL}" || { echo "ERROR: Download failed"; exit 1; }
else
    echo "ERROR: Neither wget nor curl found. Please install one of them."
    exit 1
fi

echo ""
echo "Step 3: Extracting JMeter..."
tar -xzf "${JMETER_ARCHIVE}"
rm "${JMETER_ARCHIVE}"

echo ""
echo "Step 4: Installing custom JDBC drivers..."

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
echo "Step 5: Creating reports directory..."
mkdir -p "${SCRIPT_DIR}/reports"

echo ""
echo "=================================================="
echo "✓ Setup Complete!"
echo "=================================================="
echo ""
echo "Installed components:"
echo "  - Java: $(java -version 2>&1 | head -1)"
echo "  - jq: $(jq --version 2>/dev/null || echo 'not installed')"
echo "  - git: $(git --version 2>/dev/null || echo 'not installed')"
echo "  - JMeter: ${JMETER_VERSION}"
echo ""
echo "JMeter installed at:"
echo "  ${SCRIPT_DIR}/${JMETER_DIR}"
echo ""
if [ -n "$JAVA_HOME" ]; then
    echo "JAVA_HOME is set to:"
    echo "  $JAVA_HOME"
    echo ""
fi
echo "Next steps:"
echo "  1. Copy your JDBC drivers to jdbc_drivers/ (if not already there)"
echo "  2. Create connection properties in connection_properties/"
echo "  3. Run tests with: ./run_jmeter_tests_interactive.sh"
echo ""
echo "To verify installation:"
echo "  ${JMETER_DIR}/bin/jmeter --version"
echo ""
