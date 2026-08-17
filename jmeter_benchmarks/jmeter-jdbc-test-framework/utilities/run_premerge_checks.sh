#!/bin/bash
# Dependency-light checks that must pass before merging framework changes.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

python3 -m unittest discover -s utilities/tests -v
python3 -m compileall -q utilities

for script in ./*.sh utilities/*.sh utilities/athena/*.sh utilities/athena/setup/*.sh; do
    bash -n "$script"
done

if command -v xmllint >/dev/null 2>&1; then
    for plan in Test-Plans/*.jmx; do
        xmllint --noout "$plan"
    done
else
    python3 - <<'PY'
import glob
import xml.etree.ElementTree as ET
for path in glob.glob("Test-Plans/*.jmx"):
    ET.parse(path)
PY
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
python3 utilities/apply_load_profile.py \
    Test-Plans/Test-Plan-Fire-QPS-with-load-profile.jmx \
    test_properties/load_profile.csv "$tmp/arrivals.jmx"
python3 utilities/apply_load_profile.py \
    Test-Plans/Test-Plan-Maintain-variable-concurrency-with-load-profile.jmx \
    test_properties/utg_load_profile.csv "$tmp/concurrency.jmx"

echo "All JMeter pre-merge checks passed."
