#!/usr/bin/env bash
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "Run with sudo: sudo deploy/ec2-worker/install_worker.sh" >&2
  exit 2
fi

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_FRAMEWORK_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)"
FRAMEWORK_ROOT="${BENCHMARK_WORKER_ROOT:-$DEFAULT_FRAMEWORK_ROOT}"
test -x "$FRAMEWORK_ROOT/run_test.sh" || {
  echo "Framework not found at $FRAMEWORK_ROOT" >&2
  exit 1
}

command -v aws >/dev/null || { echo "AWS CLI is required" >&2; exit 1; }
command -v unzip >/dev/null || { echo "unzip is required" >&2; exit 1; }
command -v python3 >/dev/null || { echo "python3 is required" >&2; exit 1; }

install -d -m 700 /var/lib/e6-benchmark-worker/jobs
install -d -m 755 /usr/local/libexec
if [ ! -e /etc/e6-benchmark-worker.env ]; then
  install -m 600 "$FRAMEWORK_ROOT/deploy/ec2-worker/worker.env.example" \
    /etc/e6-benchmark-worker.env
fi
chmod 755 "$FRAMEWORK_ROOT/deploy/ec2-worker/run_job.sh" "$FRAMEWORK_ROOT/deploy/ec2-worker/idle_stop.sh"
install -m 755 "$FRAMEWORK_ROOT/deploy/ec2-worker/idle_stop.sh" \
  /usr/local/libexec/e6-benchmark-worker-idle-stop
install -m 644 "$FRAMEWORK_ROOT/deploy/ec2-worker/benchmark-worker-idle-stop@.service" \
  /etc/systemd/system/benchmark-worker-idle-stop@.service
systemctl daemon-reload
echo "Benchmark worker system integration complete"
echo "Framework root: $FRAMEWORK_ROOT"
