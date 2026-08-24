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
# 6. Install the optional Benchmark Studio Python environment
# 7. Optionally start its local PostgreSQL registry
#
# Usage: ./setup_jmeter.sh [--with-postgres | --without-ui]
#

set -e  # Exit on error

JMETER_VERSION="5.6.3"
JMETER_DIR="apache-jmeter-${JMETER_VERSION}"
JMETER_ARCHIVE="apache-jmeter-${JMETER_VERSION}.tgz"
JMETER_URL="https://archive.apache.org/dist/jmeter/binaries/${JMETER_ARCHIVE}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WITH_POSTGRES=false
INSTALL_UI=true
for arg in "$@"; do
    case "$arg" in
        --with-postgres) WITH_POSTGRES=true ;;
        --without-ui) INSTALL_UI=false ;;
        -h|--help)
            echo "Usage: ./setup_jmeter.sh [--with-postgres | --without-ui]"
            echo "  Installs JMeter, plugins, JDBC drivers, and Benchmark Studio."
            echo "  --with-postgres also starts the supplied local PostgreSQL container."
            echo "  --without-ui installs only the CLI/remote-worker runtime."
            exit 0
            ;;
        *) echo "Unknown option: $arg"; exit 2 ;;
    esac
done

if [ "$WITH_POSTGRES" = true ] && [ "$INSTALL_UI" = false ]; then
    echo "ERROR: --with-postgres and --without-ui cannot be used together."
    exit 2
fi

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

find_ui_python() {
    for candidate in python3 python3.13 python3.12 python3.11 python3.10; do
        if command_exists "$candidate" && \
            "$candidate" -c 'import ssl, sys, venv; raise SystemExit(sys.version_info < (3, 10))' 2>/dev/null; then
            command -v "$candidate"
            return 0
        fi
    done
    if [ -x "$HOME/.local/e6-benchmark-python-3.11/bin/python3.11" ] && \
        "$HOME/.local/e6-benchmark-python-3.11/bin/python3.11" \
            -c 'import ssl, sys, venv; raise SystemExit(sys.version_info < (3, 10))' 2>/dev/null; then
        echo "$HOME/.local/e6-benchmark-python-3.11/bin/python3.11"
        return 0
    fi
    return 1
}

install_ui_python() {
    echo "Installing a private Python 3.11 runtime for Benchmark Studio..."
    case $OS in
        amzn|amazonlinux)
            if command_exists dnf; then
                sudo dnf install -y python3.11 python3.11-pip
            else
                # Amazon Linux 2 has no supported Python 3.10+ package in its
                # base repositories. Build a pinned CPython under the invoking
                # user's ~/.local without replacing /usr/bin/python3.
                sudo yum groupinstall -y "Development Tools"
                sudo yum install -y openssl11-devel bzip2-devel libffi-devel \
                    zlib-devel xz-devel readline-devel sqlite-devel tar gzip pkgconfig
                PYTHON_SOURCE_VERSION="3.11.16"
                PYTHON_SOURCE_SHA256="6c0bd76ab0ec7d94ed400b1497f01ac6c7751c8822615ee0855a3eb2d893ea76"
                PYTHON_PREFIX="$HOME/.local/e6-benchmark-python-3.11"
                PYTHON_BUILD_DIR="$(mktemp -d /tmp/e6-python-build.XXXXXX)"
                PYTHON_ARCHIVE="$PYTHON_BUILD_DIR/Python-${PYTHON_SOURCE_VERSION}.tgz"
                if command_exists curl; then
                    curl -fL "https://www.python.org/ftp/python/${PYTHON_SOURCE_VERSION}/Python-${PYTHON_SOURCE_VERSION}.tgz" -o "$PYTHON_ARCHIVE"
                else
                    wget -O "$PYTHON_ARCHIVE" "https://www.python.org/ftp/python/${PYTHON_SOURCE_VERSION}/Python-${PYTHON_SOURCE_VERSION}.tgz"
                fi
                echo "${PYTHON_SOURCE_SHA256}  ${PYTHON_ARCHIVE}" | sha256sum -c -
                tar -xzf "$PYTHON_ARCHIVE" -C "$PYTHON_BUILD_DIR"
                OPENSSL_CFLAGS="$(pkg-config --cflags openssl11 2>/dev/null || true)"
                OPENSSL_LDFLAGS="$(pkg-config --libs-only-L openssl11 2>/dev/null || true)"
                (
                    cd "$PYTHON_BUILD_DIR/Python-${PYTHON_SOURCE_VERSION}"
                    CPPFLAGS="$OPENSSL_CFLAGS" LDFLAGS="$OPENSSL_LDFLAGS" \
                        ./configure --prefix="$PYTHON_PREFIX" \
                        --with-openssl=/usr --with-openssl-rpath=auto \
                        --with-ensurepip=install
                    make -j"$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 2)"
                    make install
                )
                "$PYTHON_PREFIX/bin/python3.11" -c \
                    'import ssl, venv; print("Python SSL:", ssl.OPENSSL_VERSION)'
                rm -rf "$PYTHON_BUILD_DIR"
            fi
            ;;
        ubuntu|debian)
            sudo apt update
            sudo apt install -y python3 python3-venv python3-pip
            ;;
        centos|rhel|fedora)
            if command_exists dnf; then
                sudo dnf install -y python3.11 python3.11-pip
            else
                sudo yum install -y python3.11 python3.11-pip
            fi
            ;;
        *)
            echo "ERROR: Automatic Python installation is not supported on $OS."
            return 1
            ;;
    esac
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

# Check if JMeter is already installed
JMETER_ALREADY_INSTALLED=false
if [ -d "${SCRIPT_DIR}/${JMETER_DIR}/lib" ] && [ -f "${SCRIPT_DIR}/${JMETER_DIR}/bin/jmeter" ]; then
    echo "✓ JMeter ${JMETER_VERSION} is already installed"
    echo ""
    JMETER_ALREADY_INSTALLED=true
else
    echo "=================================================="
    echo "Installing Apache JMeter ${JMETER_VERSION}"
    echo "=================================================="
    echo ""

    # This repository retains a small set of customized JMeter text/config
    # files but not the full binary distribution. Preserve those files while
    # extracting the upstream archive so first-time setup leaves Git clean.
    JMETER_PRESERVE_DIR=$(mktemp -d "${TMPDIR:-/tmp}/jmeter-preserve.XXXXXX")
    for relative_path in README.md bin/jmeter.properties bin/log4j2.xml; do
        if [ -f "${SCRIPT_DIR}/${JMETER_DIR}/${relative_path}" ]; then
            mkdir -p "${JMETER_PRESERVE_DIR}/$(dirname "${relative_path}")"
            cp "${SCRIPT_DIR}/${JMETER_DIR}/${relative_path}" "${JMETER_PRESERVE_DIR}/${relative_path}"
        fi
    done

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
    for relative_path in README.md bin/jmeter.properties bin/log4j2.xml; do
        if [ -f "${JMETER_PRESERVE_DIR}/${relative_path}" ]; then
            cp "${JMETER_PRESERVE_DIR}/${relative_path}" "${SCRIPT_DIR}/${JMETER_DIR}/${relative_path}"
        fi
    done
    rm -rf "${JMETER_PRESERVE_DIR}"
fi

echo ""
echo "Step 4: Upgrading Groovy to 4.0.x (fixes Java 23 compatibility)..."

# JMeter 5.6.3 ships with Groovy 3.0.20 which can't handle class files compiled
# with Java 23+ (major version 67). JDBC drivers with Java 23 dependencies cause
# "Unsupported class file major version 67" errors in JSR223/Groovy scripts.
# Groovy 4.0.x supports Java 23. Maven groupId changed: org.codehaus.groovy -> org.apache.groovy

GROOVY_OLD_VERSION="3.0.20"
GROOVY_NEW_VERSION="4.0.29"
GROOVY_MAVEN_BASE="https://repo1.maven.org/maven2/org/apache/groovy"
GROOVY_MODULES="groovy groovy-datetime groovy-dateutil groovy-jmx groovy-json groovy-jsr223 groovy-sql groovy-templates groovy-xml"

# Check if already upgraded
if [ -f "${JMETER_DIR}/lib/groovy-${GROOVY_NEW_VERSION}.jar" ]; then
    echo "  ✓ Groovy already upgraded to ${GROOVY_NEW_VERSION}"
else
    echo "  Removing Groovy ${GROOVY_OLD_VERSION} JARs..."
    rm -f "${JMETER_DIR}"/lib/groovy-*-${GROOVY_OLD_VERSION}.jar "${JMETER_DIR}"/lib/groovy-${GROOVY_OLD_VERSION}.jar

    echo "  Downloading Groovy ${GROOVY_NEW_VERSION} JARs..."
    GROOVY_DOWNLOAD_OK=true
    for module in $GROOVY_MODULES; do
        JAR_URL="${GROOVY_MAVEN_BASE}/${module}/${GROOVY_NEW_VERSION}/${module}-${GROOVY_NEW_VERSION}.jar"
        JAR_FILE="${JMETER_DIR}/lib/${module}-${GROOVY_NEW_VERSION}.jar"
        if command_exists wget; then
            wget -q -O "${JAR_FILE}" "${JAR_URL}" || { echo "  WARNING: Failed to download ${module}"; GROOVY_DOWNLOAD_OK=false; }
        elif command_exists curl; then
            curl -sL -o "${JAR_FILE}" "${JAR_URL}" || { echo "  WARNING: Failed to download ${module}"; GROOVY_DOWNLOAD_OK=false; }
        fi
    done

    if [ "$GROOVY_DOWNLOAD_OK" = true ]; then
        echo "  ✓ Groovy upgraded from ${GROOVY_OLD_VERSION} to ${GROOVY_NEW_VERSION}"
    else
        echo "  WARNING: Some Groovy JARs failed to download. JSR223 scripts may not work."
    fi
fi

echo ""
echo "Step 5: Installing JMeter plugins..."

# Download JMeter Plugins Manager
PLUGINS_MANAGER_URL="https://jmeter-plugins.org/get/"
PLUGINS_MANAGER_JAR="${JMETER_DIR}/lib/ext/jmeter-plugins-manager-1.10.jar"

if [ ! -f "${PLUGINS_MANAGER_JAR}" ]; then
    echo "  Downloading JMeter Plugins Manager..."
    if command_exists wget; then
        wget -O "${PLUGINS_MANAGER_JAR}" "${PLUGINS_MANAGER_URL}" || {
            echo "  WARNING: Failed to download Plugins Manager"
        }
    elif command_exists curl; then
        curl -L -o "${PLUGINS_MANAGER_JAR}" "${PLUGINS_MANAGER_URL}" || {
            echo "  WARNING: Failed to download Plugins Manager"
        }
    fi
else
    echo "  ✓ JMeter Plugins Manager already installed"
fi

# Download required Blazemeter plugins directly
CASUTG_URL="https://repo1.maven.org/maven2/kg/apc/jmeter-plugins-casutg/2.10/jmeter-plugins-casutg-2.10.jar"
CASUTG_JAR="${JMETER_DIR}/lib/ext/jmeter-plugins-casutg-2.10.jar"

if [ ! -f "${CASUTG_JAR}" ]; then
    echo "  Downloading Blazemeter Custom Thread Groups plugin..."
    if command_exists wget; then
        wget -O "${CASUTG_JAR}" "${CASUTG_URL}" || {
            echo "  WARNING: Failed to download Custom Thread Groups plugin"
        }
    elif command_exists curl; then
        curl -L -o "${CASUTG_JAR}" "${CASUTG_URL}" || {
            echo "  WARNING: Failed to download Custom Thread Groups plugin"
        }
    fi
else
    echo "  ✓ Blazemeter Custom Thread Groups plugin already installed"
fi

# Download common jmeter-plugins dependency
COMMON_URL="https://repo1.maven.org/maven2/kg/apc/jmeter-plugins-cmn-jmeter/0.7/jmeter-plugins-cmn-jmeter-0.7.jar"
COMMON_JAR="${JMETER_DIR}/lib/ext/jmeter-plugins-cmn-jmeter-0.7.jar"

if [ ! -f "${COMMON_JAR}" ]; then
    echo "  Downloading JMeter Plugins Common library..."
    if command_exists wget; then
        wget -O "${COMMON_JAR}" "${COMMON_URL}" || {
            echo "  WARNING: Failed to download Plugins Common library"
        }
    elif command_exists curl; then
        curl -L -o "${COMMON_JAR}" "${COMMON_URL}" || {
            echo "  WARNING: Failed to download Plugins Common library"
        }
    fi
else
    echo "  ✓ JMeter Plugins Common library already installed"
fi

# Prometheus listener used when PROMETHEUS_ENABLED=true. The Maven Central
# artifact is the plugin's shaded distribution and belongs in lib/ext.
PROMETHEUS_PLUGIN_VERSION="0.6.0"
PROMETHEUS_PLUGIN_URL="https://repo1.maven.org/maven2/com/github/johrstrom/jmeter-prometheus-plugin/${PROMETHEUS_PLUGIN_VERSION}/jmeter-prometheus-plugin-${PROMETHEUS_PLUGIN_VERSION}.jar"
PROMETHEUS_PLUGIN_JAR="${JMETER_DIR}/lib/ext/jmeter-prometheus-plugin-${PROMETHEUS_PLUGIN_VERSION}.jar"

if [ ! -f "${PROMETHEUS_PLUGIN_JAR}" ]; then
    echo "  Downloading JMeter Prometheus listener ${PROMETHEUS_PLUGIN_VERSION}..."
    if command_exists wget; then
        wget -O "${PROMETHEUS_PLUGIN_JAR}" "${PROMETHEUS_PLUGIN_URL}" || {
            echo "  WARNING: Failed to download Prometheus listener"
            rm -f "${PROMETHEUS_PLUGIN_JAR}"
        }
    elif command_exists curl; then
        curl -L -o "${PROMETHEUS_PLUGIN_JAR}" "${PROMETHEUS_PLUGIN_URL}" || {
            echo "  WARNING: Failed to download Prometheus listener"
            rm -f "${PROMETHEUS_PLUGIN_JAR}"
        }
    fi
else
    echo "  ✓ JMeter Prometheus listener already installed"
fi

echo "  ✓ JMeter plugins check complete"

echo ""
echo "Step 6: Installing custom JDBC drivers..."

# Download Databricks JDBC driver from Maven Central
DBR_JDBC_VERSION="3.3.3"
DBR_JDBC_URL="https://repo1.maven.org/maven2/com/databricks/databricks-jdbc/${DBR_JDBC_VERSION}/databricks-jdbc-${DBR_JDBC_VERSION}.jar"
DBR_JDBC_JAR="${JMETER_DIR}/lib/ext/databricks-jdbc-${DBR_JDBC_VERSION}.jar"

if [ ! -f "${DBR_JDBC_JAR}" ]; then
    echo "  Downloading DBR JDBC driver ${DBR_JDBC_VERSION}..."
    if command_exists wget; then
        wget -O "${DBR_JDBC_JAR}" "${DBR_JDBC_URL}" || {
            echo "  WARNING: Failed to download DBR JDBC driver"
        }
    elif command_exists curl; then
        curl -L -o "${DBR_JDBC_JAR}" "${DBR_JDBC_URL}" || {
            echo "  WARNING: Failed to download DBR JDBC driver"
        }
    fi

    if [ -f "${DBR_JDBC_JAR}" ]; then
        echo "  ✓ DBR JDBC driver installed"
    fi
else
    echo "  ✓ DBR JDBC driver already installed"
fi

# Copy custom JDBC drivers from jdbc_drivers/ directory
JDBC_DRIVERS_DIR="${SCRIPT_DIR}/jdbc_drivers"
if [ -d "${JDBC_DRIVERS_DIR}" ]; then
    # Remove any existing e6 driver first. Leaving several versions in lib/ext/
    # makes the JVM load whichever it finds first, which fails as
    # "UNIMPLEMENTED: No cluster-name header or unknown cluster".
    if ls "${JDBC_DRIVERS_DIR}"/e6-jdbc-driver-*.jar >/dev/null 2>&1; then
        rm -f "${JMETER_DIR}"/lib/ext/e6-jdbc-driver-*.jar
        rm -f "${JMETER_DIR}"/lib/e6-jdbc-driver-*.jar
    fi

    # Copy every jar EXCEPT the e6 driver, then add back only the newest e6 one.
    # Copying jdbc_drivers/*.jar wholesale re-creates the collision above the
    # moment two e6 versions sit side by side in the directory.
    for jar in "${JDBC_DRIVERS_DIR}"/*.jar; do
        [ -e "$jar" ] || continue
        case "$(basename "$jar")" in
            e6-jdbc-driver-*.jar) continue ;;
        esac
        cp -v "$jar" "${JMETER_DIR}/lib/ext/"
    done

    E6_LATEST=$(ls -1 "${JDBC_DRIVERS_DIR}"/e6-jdbc-driver-*.jar 2>/dev/null | sort -V | tail -1)
    if [ -n "${E6_LATEST}" ]; then
        E6_COUNT=$(ls -1 "${JDBC_DRIVERS_DIR}"/e6-jdbc-driver-*.jar 2>/dev/null | wc -l | tr -d ' ')
        if [ "${E6_COUNT}" -gt 1 ]; then
            echo "  NOTE: ${E6_COUNT} e6 driver versions present; installing only $(basename "${E6_LATEST}")"
        fi
        cp -v "${E6_LATEST}" "${JMETER_DIR}/lib/ext/"
    fi

    # Resolve Netty/gRPC collisions introduced by fat "-with-dependencies" jars
    if [ -x "${SCRIPT_DIR}/utilities/fix_jmeter_jar_conflicts.sh" ]; then
        echo ""
        JMETER_HOME="${JMETER_DIR}" "${SCRIPT_DIR}/utilities/fix_jmeter_jar_conflicts.sh"
    fi
else
    echo "  WARNING: jdbc_drivers/ directory not found"
    echo "  You'll need to manually add JDBC drivers to ${JMETER_DIR}/lib/ext/"
fi

echo ""
echo "Step 7: Configuring minimal logging..."

# Configure log4j2 to reduce logging verbosity
LOG4J_CONFIG="${JMETER_DIR}/bin/log4j2.xml"
if [ -f "$LOG4J_CONFIG" ]; then
    # Backup original config
    cp "$LOG4J_CONFIG" "$LOG4J_CONFIG.backup"

    # Set root logger to WARN level (was INFO by default)
    sed -i.tmp 's/<Root level="info">/<Root level="warn">/' "$LOG4J_CONFIG" || \
    sed -i '' 's/<Root level="info">/<Root level="warn">/' "$LOG4J_CONFIG" 2>/dev/null

    # Set JMeter core loggers to WARN
    sed -i.tmp 's/<Logger name="org.apache.jmeter" level="info"/<Logger name="org.apache.jmeter" level="warn"/' "$LOG4J_CONFIG" || \
    sed -i '' 's/<Logger name="org.apache.jmeter" level="info"/<Logger name="org.apache.jmeter" level="warn"/' "$LOG4J_CONFIG" 2>/dev/null

    # Clean up temp files
    rm -f "$LOG4J_CONFIG.tmp" 2>/dev/null

    echo "  ✓ Configured JMeter logging to WARN level (reduces log file size)"
else
    echo "  WARNING: log4j2.xml not found, skipping logging configuration"
fi

# Configure jmeter.properties for minimal dashboard generation
JMETER_PROPS="${JMETER_DIR}/bin/jmeter.properties"
if [ -f "$JMETER_PROPS" ]; then
    # Add the note once; setup must be safe to rerun without modifying tracked
    # installation files on every invocation.
    if ! grep -qF "# Dashboard generation disabled by default (can be enabled via -e -o flags)" "$JMETER_PROPS"; then
        echo "" >> "$JMETER_PROPS"
        echo "# Dashboard generation disabled by default (can be enabled via -e -o flags)" >> "$JMETER_PROPS"
        echo "# To enable: add '-e -o /path/to/dashboard' to jmeter command" >> "$JMETER_PROPS"
        echo "  ✓ Added dashboard generation notes to jmeter.properties"
    else
        echo "  ✓ Dashboard generation notes already configured"
    fi
fi

echo ""
echo "Step 8: Creating reports directory..."
mkdir -p "${SCRIPT_DIR}/reports"

echo ""
if [ "$INSTALL_UI" = true ]; then
    echo "Step 9: Installing Benchmark Studio runtime..."
    if UI_PYTHON="$(find_ui_python)"; then
        echo "  Using Python: $UI_PYTHON"
    else
        install_ui_python
        UI_PYTHON="$(find_ui_python)" || {
            echo "ERROR: Python 3.10+ was not found after installation."
            exit 1
        }
    fi
    if [ "$WITH_POSTGRES" = true ]; then
        BENCHMARK_UI_PYTHON="$UI_PYTHON" "${SCRIPT_DIR}/setup_ui.sh" --with-postgres
    else
        BENCHMARK_UI_PYTHON="$UI_PYTHON" "${SCRIPT_DIR}/setup_ui.sh"
    fi
else
    echo "Step 9: Skipping Benchmark Studio runtime (--without-ui)."
fi

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
echo "  2. Create connection: ./create_connection.sh (or create it in the UI)"
if [ "$INSTALL_UI" = true ]; then
    echo "  3. Start the UI: ./start_ui.sh"
    echo "  4. Open http://127.0.0.1:8765 and launch a test"
    echo "  5. CLI alternative: ./run_test.sh test_configs/<your_config>.env"
else
    echo "  3. Run from CLI: ./run_test.sh test_configs/<your_config>.env"
fi
echo ""
echo "To verify installation:"
echo "  ./${JMETER_DIR}/bin/jmeter --version"
echo ""
