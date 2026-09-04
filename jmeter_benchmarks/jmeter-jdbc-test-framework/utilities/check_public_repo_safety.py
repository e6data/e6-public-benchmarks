#!/usr/bin/env python3
"""Reject local benchmark artifacts that were force-added to this public repo."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path, PurePosixPath


REPO_ROOT = Path(__file__).resolve().parents[3]
FRAMEWORK = "jmeter_benchmarks/jmeter-jdbc-test-framework/"
FORBIDDEN_NAMES = {
    "JmeterResultFile.csv", "AggregateReport.csv", "run_summary.json",
    "statistics.json", "s3_upload.json", "ui_manifest.json",
}
FORBIDDEN_SUFFIXES = {".jtl", ".pem", ".key", ".p12", ".pfx"}


def reason_for(path: str) -> str | None:
    """Return a public-safety violation reason for one repo-relative path."""
    normalized = path.replace("\\", "/").lstrip("./")
    item = PurePosixPath(normalized)
    in_framework = normalized.startswith(FRAMEWORK)
    relative = normalized[len(FRAMEWORK):] if in_framework else normalized

    if in_framework and relative.startswith(("reports/", "logs/", "backups/", "compare_runs/")):
        return "generated benchmark output/runtime directory"
    if in_framework and relative.startswith("connection_properties/") \
            and item.suffix in {".properties", ".bak"}:
        return "local connection profile"
    if in_framework and relative.startswith("ui/") and (
            item.suffix == ".db" or item.name.endswith((".db-shm", ".db-wal"))
    ):
        return "local UI registry"
    if in_framework and relative in {".benchmark-ui.env", "ui/system_settings.json"}:
        return "local deployment configuration"
    if in_framework and relative.startswith("test_configs/") and item.suffix == ".env" \
            and not item.name.startswith("sample_"):
        return "local runner environment"
    if in_framework and relative.startswith("test_properties/ui_"):
        return "locally created workload preset"
    if in_framework and relative.startswith("metadata_files/ui_"):
        return "locally created metadata preset"
    if item.name in FORBIDDEN_NAMES:
        return "generated JMeter/report artifact"
    if item.suffix.lower() in FORBIDDEN_SUFFIXES:
        return "private key, certificate bundle, or JMeter result"
    return None


def content_reason(path: str, root: Path = REPO_ROOT) -> str | None:
    """Recognize renamed JMeter result CSVs without scanning arbitrary binaries."""
    if PurePosixPath(path).suffix.lower() != ".csv":
        return None
    target = root / path
    if not target.is_file():
        return None
    try:
        with target.open(errors="replace") as handle:
            header = handle.readline().strip().lower().replace(" ", "")
    except OSError:
        return None
    fields = set(header.split(","))
    if {"timestamp", "elapsed", "label", "success"}.issubset(fields):
        return "JMeter sample-result content"
    if {"label", "#samples", "average", "error%", "throughput"}.issubset(fields):
        return "JMeter aggregate-report content"
    return None


def violations(paths: list[str], root: Path = REPO_ROOT) -> list[tuple[str, str]]:
    found = []
    for path in paths:
        reason = reason_for(path) or content_reason(path, root)
        if reason:
            found.append((path, reason))
    return found


def git_paths(staged: bool) -> list[str]:
    command = ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"] \
        if staged else ["git", "ls-files"]
    result = subprocess.run(command, cwd=REPO_ROOT, check=True, text=True, capture_output=True)
    return [line for line in result.stdout.splitlines() if line]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged", action="store_true", help="check only files staged for the next commit")
    parser.add_argument("paths", nargs="*", help="explicit repo-relative paths (primarily for tests)")
    args = parser.parse_args()
    found = violations(args.paths or git_paths(args.staged))
    if not found:
        print("Public repository artifact check passed")
        return 0
    print("Public repository artifact check failed:", file=sys.stderr)
    for path, reason in found:
        print(f"  - {path}: {reason}", file=sys.stderr)
    print("Remove these files from Git tracking; keep them local or in configured artifact storage.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
