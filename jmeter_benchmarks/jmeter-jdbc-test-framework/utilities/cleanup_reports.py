#!/usr/bin/env python3
"""Baseline-aware retention for complete benchmark report directories."""

import argparse
import json
import os
import shutil
import sqlite3
import time
import uuid
from pathlib import Path


ACTIVE_STATUSES = {"queued", "worker_starting", "running", "finalizing", "cancelling"}


def _payload_run_id(payload):
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return None
    return str(payload.get("id")) if isinstance(payload, dict) and payload.get("status") in ACTIVE_STATUSES else None


def registry_protections(database, database_url=""):
    """Return active baseline and in-progress run ids from either registry backend."""
    protected = set()
    if database_url:
        try:
            import psycopg
            with psycopg.connect(database_url) as db:
                protected.update(row[0] for row in db.execute(
                    "SELECT run_id FROM reference_promotions WHERE active=true"
                ))
                protected.update(filter(None, (_payload_run_id(row[0]) for row in db.execute("SELECT payload FROM runs"))))
        except Exception as exc:
            raise RuntimeError(f"could not read PostgreSQL benchmark registry: {exc}") from exc
        return protected
    if not database.is_file():
        return set()
    with sqlite3.connect(database) as db:
        try:
            protected.update(row[0] for row in db.execute(
                "SELECT run_id FROM reference_promotions WHERE active=1"
            ))
        except sqlite3.OperationalError:
            pass
        try:
            protected.update(filter(None, (_payload_run_id(row[0]) for row in db.execute("SELECT payload FROM runs"))))
        except sqlite3.OperationalError:
            pass
    return protected


def active_baselines(database):
    """Backward-compatible SQLite helper used by callers and older tests."""
    return registry_protections(database)


def discover(reports):
    found = []
    for summary_path in reports.glob("**/run_summary.json"):
        if ".trash" in summary_path.parts or summary_path.is_symlink():
            continue
        try:
            summary = json.loads(summary_path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        meta = summary.get("meta", {})
        signature = tuple(str(meta.get(key) or "") for key in (
            "engine", "query_sha256", "test_plan", "run_type", "cluster_size", "CLUSTER_SIZE"
        ))
        marker = summary_path.parent / "s3_upload.json"
        verified = False
        try:
            verified = json.loads(marker.read_text()).get("status") == "verified"
        except (OSError, json.JSONDecodeError):
            pass
        found.append({
            "path": summary_path.parent, "summary": summary, "signature": signature,
            "run_id": str(meta.get("run_id") or summary_path.parent.name),
            "mtime": summary_path.stat().st_mtime, "s3_verified": verified,
        })
    return sorted(found, key=lambda item: item["mtime"], reverse=True)


def classify(items, baselines, keep_days, keep_latest, keep_per_configuration, require_s3):
    cutoff = time.time() - keep_days * 86400
    newest = {item["path"] for item in items[:keep_latest]}
    per_signature = {}
    for item in items:
        per_signature.setdefault(item["signature"], []).append(item)
    protected_by_signature = {
        item["path"] for group in per_signature.values() for item in group[:keep_per_configuration]
    }
    decisions = []
    for item in items:
        reasons = []
        if item["run_id"] in baselines: reasons.append("active baseline")
        if item["path"] in newest: reasons.append(f"latest {keep_latest}")
        if item["path"] in protected_by_signature: reasons.append(f"latest {keep_per_configuration} for configuration")
        if item["mtime"] >= cutoff: reasons.append(f"within {keep_days} days")
        if require_s3 and not item["s3_verified"]: reasons.append("S3 publication not verified")
        decisions.append((item, reasons))
    return decisions


def main():
    parser = argparse.ArgumentParser(description="Safely quarantine old benchmark reports")
    parser.add_argument("--reports", default="reports")
    parser.add_argument("--database", default="ui/benchmark_ui.db")
    parser.add_argument("--database-url", default=os.environ.get("BENCHMARK_UI_DATABASE_URL", ""),
                        help="PostgreSQL registry URL; defaults to BENCHMARK_UI_DATABASE_URL")
    parser.add_argument("--keep-days", type=int, default=30)
    parser.add_argument("--keep-latest", type=int, default=10)
    parser.add_argument("--keep-per-configuration", type=int, default=3)
    parser.add_argument("--require-s3", action="store_true")
    parser.add_argument("--apply", action="store_true", help="Move candidates to reports/.trash")
    args = parser.parse_args()
    reports = Path(args.reports).resolve()
    database = Path(args.database).resolve()
    trash = reports / ".trash"
    decisions = classify(discover(reports), registry_protections(database, args.database_url), max(0, args.keep_days),
                         max(0, args.keep_latest), max(0, args.keep_per_configuration), args.require_s3)
    candidates = 0
    for item, reasons in decisions:
        if reasons:
            print(f"KEEP {item['run_id']}: {', '.join(reasons)}")
            continue
        candidates += 1
        if args.apply:
            trash.mkdir(exist_ok=True)
            destination = trash / f"{int(time.time())}-{uuid.uuid4().hex[:8]}-{item['run_id']}"
            shutil.move(str(item["path"]), destination)
            print(f"QUARANTINED {item['run_id']}: {destination}")
        else:
            print(f"DELETE CANDIDATE {item['run_id']}: {item['path']}")
    print(f"{candidates} candidate(s); {'quarantined' if args.apply else 'dry-run only'}")


if __name__ == "__main__":
    main()
