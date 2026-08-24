#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 3 ]; then
  echo "Usage: run_job.sh s3-input-zip s3-job-prefix run-id" >&2
  exit 2
fi

INPUT_URI="$1"
JOB_PREFIX="$2"
RUN_ID="$3"
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_FRAMEWORK_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)"
FRAMEWORK_ROOT="${BENCHMARK_WORKER_ROOT:-$DEFAULT_FRAMEWORK_ROOT}"
JOB_DIR="/var/lib/e6-benchmark-worker/jobs/$RUN_ID"

install -d -m 700 "$JOB_DIR"
aws s3 cp "$INPUT_URI" "$JOB_DIR/input.zip"
aws s3 rm "$INPUT_URI" --only-show-errors
unzip -q -o "$JOB_DIR/input.zip" -d "$JOB_DIR/input"
touch /var/lib/e6-benchmark-worker/active

sync_results() {
  while [ -e /var/lib/e6-benchmark-worker/active ]; do
    aws s3 sync "$FRAMEWORK_ROOT/reports/ui-$RUN_ID/" "$JOB_PREFIX/results/" --only-show-errors || true
    sleep 10
  done
}
sync_results &
SYNC_PID=$!

cleanup() {
  rm -f /var/lib/e6-benchmark-worker/active
  kill "$SYNC_PID" 2>/dev/null || true
  aws s3 sync "$FRAMEWORK_ROOT/reports/ui-$RUN_ID/" "$JOB_PREFIX/results/" --only-show-errors || true
  date +%s > /var/lib/e6-benchmark-worker/last-finished
  rm -rf "$JOB_DIR"
}
trap cleanup EXIT

python3 - "$JOB_DIR/input/environment.json" "$JOB_DIR/input" "$FRAMEWORK_ROOT/run_test.sh" <<'PY'
import json, os, pathlib, sys
env_file, job_dir, runner = sys.argv[1:]
values = json.loads(pathlib.Path(env_file).read_text())
env = os.environ.copy()
for key, value in values.items():
    env[str(key)] = str(value).replace("{JOB_DIR}", job_dir)
os.chdir(pathlib.Path(runner).parent)
os.execve(runner, [runner], env)
PY
