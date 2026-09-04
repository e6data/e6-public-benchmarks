#!/bin/bash
# Install the optional Benchmark Studio runtime. SQLite is the default;
# --with-postgres starts the supplied PostgreSQL container; --with-observability
# starts local Prometheus and Grafana containers for the standard JMeter listener.
set -e

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
WITH_POSTGRES=false
WITH_OBSERVABILITY=false

usage() {
    echo "Usage: ./setup_ui.sh [--with-postgres] [--with-observability]"
    echo "  default          install the UI Python environment (SQLite registry)"
    echo "  --with-postgres  also start the local PostgreSQL registry container"
    echo "  --with-observability  also start local Prometheus and Grafana containers"
}

for arg in "$@"; do
    case "$arg" in
        --with-postgres) WITH_POSTGRES=true ;;
        --with-observability) WITH_OBSERVABILITY=true ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown option: $arg"; usage; exit 2 ;;
    esac
done

PYTHON_BIN="${BENCHMARK_UI_PYTHON:-}"
if [ -n "$PYTHON_BIN" ]; then
    if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
        echo "ERROR: BENCHMARK_UI_PYTHON is not executable: $PYTHON_BIN"
        exit 1
    fi
else
    for candidate in python3 python3.13 python3.12 python3.11 python3.10; do
        if command -v "$candidate" >/dev/null 2>&1 && \
            "$candidate" -c 'import ssl, sys, venv; raise SystemExit(sys.version_info < (3, 10))' 2>/dev/null; then
            PYTHON_BIN="$candidate"
            break
        fi
    done
fi

if [ -z "$PYTHON_BIN" ]; then
    SYSTEM_PYTHON_VERSION="not installed"
    if command -v python3 >/dev/null 2>&1; then
        SYSTEM_PYTHON_VERSION=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
    fi
    echo "ERROR: Python 3.10+ is required for Benchmark Studio; default python3 is ${SYSTEM_PYTHON_VERSION}."
    echo "Install Python 3.10+ alongside the system Python, then rerun this script."
    echo "You may select it explicitly with BENCHMARK_UI_PYTHON=/path/to/python3.11 ./setup_ui.sh"
    exit 1
fi

PYTHON_VERSION=$("$PYTHON_BIN" -c 'import sys; print("%d.%d" % sys.version_info[:2])')
if ! "$PYTHON_BIN" -c 'import ssl, sys, venv; raise SystemExit(sys.version_info < (3, 10))'; then
    echo "ERROR: Selected Python must be 3.10+ with SSL and venv support: ${PYTHON_BIN} (${PYTHON_VERSION})."
    exit 1
fi

echo "Setting up Benchmark Studio with ${PYTHON_BIN} (${PYTHON_VERSION})..."
if [ -x "$ROOT/.venv/bin/python" ] && \
    ! "$ROOT/.venv/bin/python" -c 'import ssl, sys; raise SystemExit(sys.version_info < (3, 10))' 2>/dev/null; then
    echo "Replacing incomplete or outdated Benchmark Studio virtual environment..."
    rm -rf "$ROOT/.venv"
fi
if [ ! -x "$ROOT/.venv/bin/python" ]; then
    "$PYTHON_BIN" -m venv "$ROOT/.venv"
fi
"$ROOT/.venv/bin/python" -m pip install --upgrade pip
"$ROOT/.venv/bin/python" -m pip install -r "$ROOT/requirements-ui.txt"
mkdir -p "$ROOT/logs" "$ROOT/reports" "$ROOT/connection_properties" \
    "$ROOT/data_files" "$ROOT/test_properties" "$ROOT/metadata_files"

if [ "$WITH_POSTGRES" = true ] || [ "$WITH_OBSERVABILITY" = true ]; then
    if ! command -v docker >/dev/null 2>&1; then
        echo "ERROR: Docker with Compose is required for the selected local services."
        echo "Install Docker, verify 'docker compose version', and rerun this script."
        exit 1
    fi
    if ! docker compose version >/dev/null 2>&1; then
        echo "ERROR: The Docker Compose plugin is required."
        exit 1
    fi
fi

ENV_FILE="$ROOT/.benchmark-ui.env"

set_env_value() {
    local key="$1" value="$2" temporary
    temporary="${ENV_FILE}.tmp.$$"
    if [ -f "$ENV_FILE" ]; then
        awk -v key="$key" -v value="$value" '
            BEGIN { found=0 }
            index($0, key "=")==1 { print key "=" value; found=1; next }
            { print }
            END { if (!found) print key "=" value }
        ' "$ENV_FILE" > "$temporary"
    else
        printf '%s=%s\n' "$key" "$value" > "$temporary"
    fi
    mv "$temporary" "$ENV_FILE"
    chmod 600 "$ENV_FILE"
}

if [ "$WITH_POSTGRES" = true ]; then
    if [ -f "$ENV_FILE" ]; then
        # shellcheck disable=SC1090
        source "$ENV_FILE"
    else
        if [ -z "${BENCHMARK_POSTGRES_PASSWORD:-}" ]; then
            if docker ps -a --filter 'name=^/e6-benchmark-postgres$' --format '{{.Names}}' | grep -qx 'e6-benchmark-postgres'; then
                echo "ERROR: An existing e6-benchmark-postgres container has no matching .benchmark-ui.env."
                echo "Export its BENCHMARK_POSTGRES_PASSWORD and rerun setup; a new password would not change an existing database volume."
                exit 1
            fi
            if command -v openssl >/dev/null 2>&1; then
                BENCHMARK_POSTGRES_PASSWORD=$(openssl rand -hex 24)
            else
                BENCHMARK_POSTGRES_PASSWORD=$("$PYTHON_BIN" -c 'import secrets; print(secrets.token_hex(24))')
            fi
        fi
        case "$BENCHMARK_POSTGRES_PASSWORD" in
            *[!A-Za-z0-9._~-]*)
                echo "ERROR: BENCHMARK_POSTGRES_PASSWORD must use URL- and shell-safe characters: A-Z a-z 0-9 . _ ~ -"
                exit 1
                ;;
        esac
        BENCHMARK_POSTGRES_PORT="${BENCHMARK_POSTGRES_PORT:-5433}"
        umask 077
        {
            printf 'BENCHMARK_POSTGRES_PASSWORD=%s\n' "$BENCHMARK_POSTGRES_PASSWORD"
            printf 'BENCHMARK_POSTGRES_PORT=%s\n' "$BENCHMARK_POSTGRES_PORT"
            printf 'BENCHMARK_UI_DATABASE_URL=postgresql://benchmark_ui:%s@127.0.0.1:%s/benchmark_ui\n' \
                "$BENCHMARK_POSTGRES_PASSWORD" "$BENCHMARK_POSTGRES_PORT"
        } > "$ENV_FILE"
        chmod 600 "$ENV_FILE"
    fi
    export BENCHMARK_POSTGRES_PASSWORD BENCHMARK_POSTGRES_PORT
    docker compose --env-file "$ENV_FILE" -f deploy/docker-compose.postgres.yml up -d --wait
    echo "PostgreSQL registry is healthy on 127.0.0.1:${BENCHMARK_POSTGRES_PORT}."
    echo "Protected local settings: $ENV_FILE"
fi

if [ "$WITH_OBSERVABILITY" = true ]; then
    if [ -f "$ENV_FILE" ]; then
        # shellcheck disable=SC1090
        source "$ENV_FILE"
    fi
    BENCHMARK_PROMETHEUS_WEB_PORT="${BENCHMARK_PROMETHEUS_WEB_PORT:-9090}"
    BENCHMARK_GRAFANA_WEB_PORT="${BENCHMARK_GRAFANA_WEB_PORT:-3000}"
    BENCHMARK_GRAFANA_ADMIN_USER="${BENCHMARK_GRAFANA_ADMIN_USER:-admin}"
    if [ -z "${BENCHMARK_GRAFANA_ADMIN_PASSWORD:-}" ]; then
        if command -v openssl >/dev/null 2>&1; then
            BENCHMARK_GRAFANA_ADMIN_PASSWORD=$(openssl rand -hex 18)
        else
            BENCHMARK_GRAFANA_ADMIN_PASSWORD=$("$PYTHON_BIN" -c 'import secrets; print(secrets.token_hex(18))')
        fi
    fi

    DASHBOARD_DIR="$ROOT/temp/observability/grafana/dashboards"
    DASHBOARD_FILE="$DASHBOARD_DIR/jmeter-prometheus.json"
    DASHBOARD_URL="https://raw.githubusercontent.com/johrstrom/jmeter-prometheus-plugin/main/docs/examples/grafana.json"
    mkdir -p "$DASHBOARD_DIR"
    echo "Downloading the upstream JMeter Prometheus Grafana dashboard..."
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL "$DASHBOARD_URL" -o "$DASHBOARD_FILE"
    elif command -v wget >/dev/null 2>&1; then
        wget -qO "$DASHBOARD_FILE" "$DASHBOARD_URL"
    else
        echo "ERROR: curl or wget is required to download the upstream dashboard."
        exit 1
    fi
    "$PYTHON_BIN" -m json.tool "$DASHBOARD_FILE" >/dev/null

    set_env_value BENCHMARK_PROMETHEUS_WEB_PORT "$BENCHMARK_PROMETHEUS_WEB_PORT"
    set_env_value BENCHMARK_GRAFANA_WEB_PORT "$BENCHMARK_GRAFANA_WEB_PORT"
    set_env_value BENCHMARK_GRAFANA_ADMIN_USER "$BENCHMARK_GRAFANA_ADMIN_USER"
    set_env_value BENCHMARK_GRAFANA_ADMIN_PASSWORD "$BENCHMARK_GRAFANA_ADMIN_PASSWORD"
    set_env_value PROMETHEUS_ENABLED true
    set_env_value PROMETHEUS_IP 0.0.0.0
    set_env_value PROMETHEUS_PORT 9270
    set_env_value PROMETHEUS_URL "http://localhost:${BENCHMARK_PROMETHEUS_WEB_PORT}"
    set_env_value GRAFANA_URL "http://localhost:${BENCHMARK_GRAFANA_WEB_PORT}/d/jbtLA0-Wk5/jmeter?orgId=1"

    # Browser-managed settings intentionally take precedence over environment
    # defaults. Keep an existing settings file aligned with the local stack,
    # while preserving S3, Query History, retention, and other saved values.
    "$PYTHON_BIN" - "$ROOT/config/system_settings.json" \
        "http://localhost:${BENCHMARK_PROMETHEUS_WEB_PORT}" \
        "http://localhost:${BENCHMARK_GRAFANA_WEB_PORT}/d/jbtLA0-Wk5/jmeter?orgId=1" <<'PY'
import json
import os
import sys
from pathlib import Path

path = Path(sys.argv[1])
settings = json.loads(path.read_text()) if path.is_file() else {}
settings.update({
    "prometheus_enabled": True,
    "prometheus_port": 9270,
    "prometheus_url": sys.argv[2],
    "grafana_url": sys.argv[3],
})
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(settings, indent=2) + "\n")
os.chmod(path, 0o600)
PY

    # shellcheck disable=SC1090
    source "$ENV_FILE"
    export BENCHMARK_PROMETHEUS_WEB_PORT BENCHMARK_GRAFANA_WEB_PORT
    export BENCHMARK_GRAFANA_ADMIN_USER BENCHMARK_GRAFANA_ADMIN_PASSWORD
    docker compose --env-file "$ENV_FILE" -f deploy/docker-compose.observability.yml up -d

    wait_for_http() {
        local name="$1" url="$2" attempt
        for attempt in $(seq 1 30); do
            if { command -v curl >/dev/null 2>&1 && curl -fsS "$url" >/dev/null 2>&1; } || \
               { command -v wget >/dev/null 2>&1 && wget -qO- "$url" >/dev/null 2>&1; }; then
                return 0
            fi
            sleep 2
        done
        echo "ERROR: ${name} did not become ready at ${url}."
        docker compose --env-file "$ENV_FILE" -f deploy/docker-compose.observability.yml ps
        return 1
    }
    wait_for_http Prometheus "http://127.0.0.1:${BENCHMARK_PROMETHEUS_WEB_PORT}/-/ready"
    wait_for_http Grafana "http://127.0.0.1:${BENCHMARK_GRAFANA_WEB_PORT}/api/health"
    echo "Prometheus: http://127.0.0.1:${BENCHMARK_PROMETHEUS_WEB_PORT}"
    echo "Grafana:    http://127.0.0.1:${BENCHMARK_GRAFANA_WEB_PORT}/d/jbtLA0-Wk5/jmeter?orgId=1"
    echo "Grafana credentials are protected in $ENV_FILE (user: ${BENCHMARK_GRAFANA_ADMIN_USER})."
fi

echo ""
echo "Benchmark Studio setup complete."
echo "Start: ./start_ui.sh"
echo "Stop:  ./stop_ui.sh"
if [ "$WITH_POSTGRES" = false ]; then
    echo "Registry: local SQLite (run ./setup_ui.sh --with-postgres to use PostgreSQL)"
else
    echo "Registry: PostgreSQL"
fi
if [ "$WITH_OBSERVABILITY" = true ]; then
    echo "Observability: local Prometheus and Grafana"
else
    echo "Observability: external or disabled (run ./setup_ui.sh --with-observability for the local stack)"
fi
