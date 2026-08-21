#!/bin/bash
# Install the optional Benchmark Studio runtime. SQLite is the default;
# --with-postgres also starts the supplied local PostgreSQL container.
set -e

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
WITH_POSTGRES=false

usage() {
    echo "Usage: ./setup_ui.sh [--with-postgres]"
    echo "  default          install the UI Python environment (SQLite registry)"
    echo "  --with-postgres  also start the local PostgreSQL registry container"
}

for arg in "$@"; do
    case "$arg" in
        --with-postgres) WITH_POSTGRES=true ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown option: $arg"; usage; exit 2 ;;
    esac
done

if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: Python 3 is required for Benchmark Studio."
    echo "Install Python 3.10+ with your OS package manager, then rerun this script."
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
if ! python3 -c 'import sys; raise SystemExit(sys.version_info < (3, 10))'; then
    echo "ERROR: Python 3.10+ is required; found ${PYTHON_VERSION}."
    exit 1
fi

echo "Setting up Benchmark Studio with Python ${PYTHON_VERSION}..."
if [ ! -x "$ROOT/.venv/bin/python" ]; then
    python3 -m venv "$ROOT/.venv"
fi
"$ROOT/.venv/bin/python" -m pip install --upgrade pip
"$ROOT/.venv/bin/python" -m pip install -r "$ROOT/requirements-ui.txt"
mkdir -p "$ROOT/logs" "$ROOT/reports" "$ROOT/connection_properties" \
    "$ROOT/data_files" "$ROOT/test_properties" "$ROOT/metadata_files"

if [ "$WITH_POSTGRES" = true ]; then
    if ! command -v docker >/dev/null 2>&1; then
        echo "ERROR: Docker with Compose is required for --with-postgres."
        echo "Install Docker, verify 'docker compose version', and rerun this script."
        exit 1
    fi
    if ! docker compose version >/dev/null 2>&1; then
        echo "ERROR: The Docker Compose plugin is required."
        exit 1
    fi

    ENV_FILE="$ROOT/.benchmark-ui.env"
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
                BENCHMARK_POSTGRES_PASSWORD=$(python3 -c 'import secrets; print(secrets.token_hex(24))')
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

echo ""
echo "Benchmark Studio setup complete."
echo "Start: ./start_ui.sh"
echo "Stop:  ./stop_ui.sh"
if [ "$WITH_POSTGRES" = false ]; then
    echo "Registry: local SQLite (run ./setup_ui.sh --with-postgres to use PostgreSQL)"
else
    echo "Registry: PostgreSQL"
fi
