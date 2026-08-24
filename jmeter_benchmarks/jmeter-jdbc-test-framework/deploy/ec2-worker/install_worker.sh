#!/usr/bin/env bash
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "Run with sudo: sudo deploy/ec2-worker/install_worker.sh" >&2
  exit 2
fi

FRAMEWORK_ROOT="${BENCHMARK_WORKER_ROOT:-/opt/e6-public-benchmarks/jmeter_benchmarks/jmeter-jdbc-test-framework}"
test -x "$FRAMEWORK_ROOT/run_test.sh" || {
  echo "Framework not found at $FRAMEWORK_ROOT" >&2
  exit 1
}

command -v aws >/dev/null || { echo "AWS CLI is required" >&2; exit 1; }
command -v unzip >/dev/null || { echo "unzip is required" >&2; exit 1; }
command -v python3 >/dev/null || { echo "python3 is required" >&2; exit 1; }

install -d -m 700 /var/lib/e6-benchmark-worker/jobs
chmod 755 "$FRAMEWORK_ROOT/deploy/ec2-worker/run_job.sh" "$FRAMEWORK_ROOT/deploy/ec2-worker/idle_stop.sh"
install -m 644 "$FRAMEWORK_ROOT/deploy/ec2-worker/benchmark-worker-idle-stop@.service" \
  /etc/systemd/system/benchmark-worker-idle-stop@.service
systemctl daemon-reload

cd "$FRAMEWORK_ROOT"
./setup_jmeter.sh
echo "Benchmark worker installation complete"

