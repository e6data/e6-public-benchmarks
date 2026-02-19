#!/bin/bash
# Create a connection properties file interactively
# Usage: ./create_connection.sh
#
# Supports two connection types:
#   1. JDBC - for e6data, Databricks, Trino, etc.
#   2. HTTP Endpoint - for HTTP API-based testing
#
# Creates properly formatted connection properties files in connection_properties/

set -e

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

# Navigate to project root
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

CONN_DIR="connection_properties"

echo -e "${BLUE}=========================================="
echo " Create Connection Properties"
echo -e "==========================================${NC}"
echo ""

# Show existing connections
EXISTING_FILES=($(ls -1 "$CONN_DIR"/*.properties 2>/dev/null | grep -v '\.template$' || true))
if [ ${#EXISTING_FILES[@]} -gt 0 ]; then
    echo -e "${BOLD}Existing connections:${NC}"
    for f in "${EXISTING_FILES[@]}"; do
        echo "  - $(basename "$f")"
    done
    echo ""
fi

# Choose connection type
echo -e "${BOLD}Select connection type:${NC}"
echo "  1) JDBC     (e6data, Databricks, Trino, etc.)"
echo "  2) HTTP     (HTTP API endpoint)"
echo ""
read -p "Enter choice [1-2]: " conn_type

case "$conn_type" in
    1)
        echo ""
        echo -e "${BLUE}--- JDBC Connection Setup ---${NC}"
        echo ""

        # Engine selection for driver defaults
        echo -e "${BOLD}Select engine:${NC}"
        echo "  1) e6data"
        echo "  2) Databricks"
        echo "  3) Trino"
        echo "  4) Other"
        echo ""
        read -p "Enter choice [1-4]: " engine_choice

        case "$engine_choice" in
            1) ENGINE="e6data"; DRIVER_CLASS="io.e6.jdbc.driver.E6Driver" ;;
            2) ENGINE="dbr"; DRIVER_CLASS="com.databricks.client.jdbc.Driver" ;;
            3) ENGINE="trino"; DRIVER_CLASS="io.trino.jdbc.TrinoDriver" ;;
            4)
                read -p "Engine name (for filename): " ENGINE
                read -p "JDBC Driver class: " DRIVER_CLASS
                ;;
            *) echo -e "${RED}Invalid choice${NC}"; exit 1 ;;
        esac

        echo ""
        read -p "Connection name (e.g., prod, demo, test): " CONN_NAME
        echo ""

        # Collect JDBC parameters
        read -p "Hostname: " HOSTNAME
        read -p "Port [80]: " PORT
        PORT=${PORT:-80}
        read -p "Database: " DATABASE
        read -p "Catalog: " CATALOG
        echo ""
        read -p "Username: " USER_VAL
        read -sp "Password: " PASSWORD_VAL
        echo ""
        echo ""

        # Build connection string based on engine
        if [ "$engine_choice" = "2" ]; then
            echo -e "${YELLOW}For Databricks, paste the full JDBC URL from your SQL Warehouse > Connection Details${NC}"
            read -p "JDBC Connection String: " CONNECTION_STRING
        else
            # Default connection string pattern
            DEFAULT_CONN="jdbc:e6://${HOSTNAME}:${PORT}"
            read -p "Connection string [${DEFAULT_CONN}]: " CONNECTION_STRING
            CONNECTION_STRING=${CONNECTION_STRING:-$DEFAULT_CONN}
        fi

        # Generate filename
        FILENAME="${ENGINE}_${CONN_NAME}_connection.properties"
        FILEPATH="${CONN_DIR}/${FILENAME}"

        if [ -f "$FILEPATH" ]; then
            echo ""
            echo -e "${YELLOW}File already exists: ${FILENAME}${NC}"
            read -p "Overwrite? (y/n): " overwrite
            if [[ ! "$overwrite" =~ ^[Yy]$ ]]; then
                echo "Cancelled."
                exit 0
            fi
        fi

        # Write JDBC connection file
        cat > "$FILEPATH" << EOF
# JDBC Connection Properties
# Engine: ${ENGINE}
# Created: $(date +%Y-%m-%d)

HOSTNAME=${HOSTNAME}
PORT=${PORT}
DATABASE=${DATABASE}
CATALOG=${CATALOG}

USER=${USER_VAL}
PASSWORD=${PASSWORD_VAL}

CONNECTION_STRING=${CONNECTION_STRING}

DRIVER_CLASS=${DRIVER_CLASS}
EOF
        ;;

    2)
        echo ""
        echo -e "${BLUE}--- HTTP Endpoint Connection Setup ---${NC}"
        echo ""

        read -p "Connection name (e.g., prod, demo, test): " CONN_NAME
        echo ""

        read -p "API host (e.g., api-test77629.example.com): " MAINHOST
        echo -e "Protocol:"
        echo "  1) https"
        echo "  2) http"
        read -p "Enter choice [1-2, default=1]: " scheme_choice
        case "$scheme_choice" in
            2) SCHEME="http" ;;
            *) SCHEME="https" ;;
        esac
        read -p "Cluster name: " CLUSTER_NAME
        echo ""
        read -p "Username (email): " USER_VAL
        read -sp "Password/Token: " PASSWORD_VAL
        echo ""
        echo ""
        read -p "Catalog: " CATALOG
        read -p "Schema: " SCHEMA

        FILENAME="http_endpoint_${CONN_NAME}_connection.properties"
        FILEPATH="${CONN_DIR}/${FILENAME}"

        if [ -f "$FILEPATH" ]; then
            echo ""
            echo -e "${YELLOW}File already exists: ${FILENAME}${NC}"
            read -p "Overwrite? (y/n): " overwrite
            if [[ ! "$overwrite" =~ ^[Yy]$ ]]; then
                echo "Cancelled."
                exit 0
            fi
        fi

        # Write HTTP connection file
        cat > "$FILEPATH" << EOF
# HTTP Endpoint Connection Properties
# Created: $(date +%Y-%m-%d)

mainhost=${MAINHOST}
scheme=${SCHEME}
cluster_name=${CLUSTER_NAME}

USER=${USER_VAL}
PASSWORD=${PASSWORD_VAL}

CATALOG=${CATALOG}
SCHEMA=${SCHEMA}
EOF
        ;;

    *)
        echo -e "${RED}Invalid choice${NC}"
        exit 1
        ;;
esac

echo ""
echo -e "${GREEN}=========================================="
echo " Connection file created successfully!"
echo -e "==========================================${NC}"
echo ""
echo "  File: ${FILEPATH}"
echo ""
echo "Next steps:"
echo "  - Create test config: ./create_test_config.sh"
echo "  - Run a test:         ./run_test.sh test_configs/<your_config>.env"
echo "  - Interactive mode:   ./run_jmeter_tests_interactive.sh"
echo ""
