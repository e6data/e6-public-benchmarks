#!/usr/bin/env bash
set -euo pipefail

IDLE_MINUTES="${1:-20}"
STATE_DIR=/var/lib/e6-benchmark-worker
deadline=$(( $(date +%s) + IDLE_MINUTES * 60 ))

while [ "$(date +%s)" -lt "$deadline" ]; do
  if [ -e "$STATE_DIR/active" ] || pgrep -f '[A]pacheJMeter.jar' >/dev/null; then
    deadline=$(( $(date +%s) + IDLE_MINUTES * 60 ))
  fi
  sleep 30
done

if [ ! -e "$STATE_DIR/active" ] && ! pgrep -f '[A]pacheJMeter.jar' >/dev/null; then
  IMDS_TOKEN="$(curl -fsS -X PUT -H 'X-aws-ec2-metadata-token-ttl-seconds: 60' \
    http://169.254.169.254/latest/api/token)"
  INSTANCE_ID="$(curl -fsS -H "X-aws-ec2-metadata-token: $IMDS_TOKEN" \
    http://169.254.169.254/latest/meta-data/instance-id)"
  /usr/bin/aws ec2 stop-instances --region "${BENCHMARK_AWS_REGION:-us-east-1}" \
    --instance-ids "$INSTANCE_ID"
fi
