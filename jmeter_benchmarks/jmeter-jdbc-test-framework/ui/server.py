#!/usr/bin/env python3
"""Local-only UI/API adapter over the existing run_test.sh contract.

The CLI runner remains the source of truth. This module only validates a small
allowlist of inputs, starts that runner as an isolated process, and reads the
same CSV/JSON artifacts that CLI users already receive.
"""

from __future__ import annotations

import argparse
import base64
import csv
import errno
import hashlib
import hmac
import json
import logging
import mimetypes
import os
import re
import signal
import shutil
import sqlite3
import subprocess
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from utilities.query_file_info import inspect as inspect_query_file
from utilities.load_profile import (
    expected_arrivals_per_second, expected_concurrency_per_second,
    read_arrivals_profile, read_concurrency_profile,
)


ROOT = Path(__file__).resolve().parents[1]
STATIC = Path(__file__).resolve().parent / "static"
REPORTS = ROOT / "reports"
LOG_DIR = ROOT / "logs"
LOGGER = logging.getLogger("benchmark-ui")
SETTINGS_PATH = Path(os.environ.get("BENCHMARK_UI_SETTINGS_FILE", ROOT / "ui" / "system_settings.json"))
ALLOW_SETTINGS_WRITE = os.environ.get("BENCHMARK_UI_ALLOW_SETTINGS_WRITE", "false").lower() == "true"
try:
    SAVED_SETTINGS = json.loads(SETTINGS_PATH.read_text()) if SETTINGS_PATH.is_file() else {}
except (OSError, json.JSONDecodeError):
    SAVED_SETTINGS = {}
DB_PATH = Path(os.environ.get("BENCHMARK_UI_DB", ROOT / "ui" / "benchmark_ui.db"))
DATABASE_URL = os.environ.get("BENCHMARK_UI_DATABASE_URL", "")
REGISTRY_BACKEND = "postgresql" if DATABASE_URL else "sqlite"
AUTH_TOKEN = os.environ.get("BENCHMARK_UI_TOKEN", "")
PROMETHEUS_DEFAULT_ENABLED = SAVED_SETTINGS.get("prometheus_enabled", os.environ.get("PROMETHEUS_ENABLED", "false").lower() == "true")
PROMETHEUS_DEFAULT_IP = os.environ.get("PROMETHEUS_IP", "127.0.0.1")
PROMETHEUS_DEFAULT_PORT = str(SAVED_SETTINGS.get("prometheus_port", os.environ.get("PROMETHEUS_PORT", "9270")))
PROMETHEUS_DEFAULT_DELAY = os.environ.get("PROMETHEUS_DELAY", "15")
PROMETHEUS_URL = str(SAVED_SETTINGS.get("prometheus_url", os.environ.get("PROMETHEUS_URL", "")))
GRAFANA_URL = str(SAVED_SETTINGS.get("grafana_url", os.environ.get("GRAFANA_URL", "")))
SYSTEM_COPY_TO_S3 = SAVED_SETTINGS.get("copy_to_s3", os.environ.get("BENCHMARK_UI_COPY_TO_S3", "false").lower() == "true")
SYSTEM_S3_REPORT_PATH = str(SAVED_SETTINGS.get("s3_report_path", os.environ.get("S3_REPORT_PATH", "")))
SYSTEM_GENERATE_DASHBOARD = SAVED_SETTINGS.get("generate_dashboard", os.environ.get("GENERATE_DASHBOARD", "true").lower() == "true")
REPORT_RETENTION_DAYS = int(SAVED_SETTINGS.get("retention_days", os.environ.get("BENCHMARK_UI_REPORT_RETENTION_DAYS", "30")))
MAX_LOCAL_REPORT_GB = int(SAVED_SETTINGS.get("max_local_report_gb", os.environ.get("BENCHMARK_UI_MAX_LOCAL_REPORT_GB", "100")))
DELETE_LOCAL_AFTER_S3 = os.environ.get("BENCHMARK_UI_DELETE_LOCAL_AFTER_S3", "false").lower() == "true"
DB_READY = False

PLANS = {
    "jdbc_run_once": ("Run once", "Test-Plans/Test-Plan-Run-Once-static-concurrency.jmx", "jdbc"),
    "jdbc_concurrency": ("Fixed concurrency", "Test-Plans/Test-Plan-Maintain-static-concurrency.jmx", "jdbc"),
    "jdbc_qps": ("Constant QPS", "Test-Plans/Test-Plan-Constant-QPS-On-Arrivals-JSR-Optimized.jmx", "jdbc"),
    "jdbc_qpm": ("Constant QPM", "Test-Plans/Test-Plan-Constant-QPM-On-Arrivals.jmx", "jdbc"),
    "jdbc_arrivals": ("Variable arrival rate", "Test-Plans/Test-Plan-Fire-QPS-with-load-profile.jmx", "jdbc"),
    "jdbc_variable_concurrency": ("Variable concurrency", "Test-Plans/Test-Plan-Maintain-variable-concurrency-with-load-profile.jmx", "jdbc"),
    "http_run_once": ("Run once (HTTP)", "Test-Plans/Test-Plan-Run-Once-http-endpoint.jmx", "http"),
    "http_concurrency": ("Fixed concurrency (HTTP)", "Test-Plans/Test-Plan-Maintain-static-concurrency-http-endpoint.jmx", "http"),
    "http_arrivals": ("Variable arrival rate (HTTP)", "Test-Plans/Test-Plan-Fire-QPS-with-load-profile-http-endpoint_v2.jmx", "http"),
}

NUMERIC_LIMITS = {
    "CONCURRENT_QUERY_COUNT": (1, 10000), "QPS": (1, 100000), "QPM": (1, 1000000),
    "HOLD_PERIOD": (1, 86400), "RAMP_UP_TIME": (0, 86400), "RAMP_UP_STEPS": (1, 10000),
    "MAX_CONCURRANCY": (1, 100000), "QUERY_TIMEOUT": (1, 86400),
    "LIMIT_RESULTSET": (1, 10000000), "MAX_ERROR_PCT": (0, 100),
}

PROFILE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
CSV_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.csv$", re.IGNORECASE)
JDBC_DRIVERS = {
    "e6data": "io.e6.jdbc.driver.E6Driver",
    "databricks": "com.databricks.client.jdbc.Driver",
    "trino": "io.trino.jdbc.TrinoDriver",
}
PUBLIC_RUN_FIELDS = {
    "plan", "engine", "connection", "query_file", "load_profile", "CONCURRENT_QUERY_COUNT",
    "QPS", "QPM", "HOLD_PERIOD", "RAMP_UP_TIME", "RAMP_UP_STEPS",
    "MAX_CONCURRANCY", "QUERY_TIMEOUT", "LIMIT_RESULTSET", "MAX_ERROR_PCT",
    "RECYCLE_ON_EOF", "RANDOM_ORDER", "GENERATE_DASHBOARD", "PROMETHEUS_ENABLED",
    "PROMETHEUS_PORT", "execution_mode", "metadata", "planned_workload", "rerun_of",
}
METADATA_FIELDS = {
    "CLUSTER_SIZE": 80, "BENCHMARK_TYPE": 100, "DATA_SIZE": 40,
    "DATA_TYPE": 40, "RUN_MODE": 40, "CUSTOMER": 100, "CONFIG": 120,
    "TAGS": 300, "COMMENTS": 1000, "ESTIMATED_CORES": 20, "MEMORY_GB": 20,
    "INSTANCE_TYPE": 100, "EXECUTORS": 20, "CORES_PER_EXECUTOR": 20,
    "SERVERLESS": 20, "ENGINE_BUILD": 120,
}
DISPLAY_ENV_FIELDS = (
    "RUN_ID", "ENGINE", "CONNECTION_FILE", "TEST_PLAN", "QUERY_FILE", "LOAD_PROFILE",
    "CONCURRENT_QUERY_COUNT", "QPS", "QPM", "HOLD_PERIOD", "RAMP_UP_TIME",
    "RAMP_UP_STEPS", "MAX_CONCURRANCY", "QUERY_TIMEOUT", "LIMIT_RESULTSET",
    "MAX_ERROR_PCT", "RECYCLE_ON_EOF", "RANDOM_ORDER", "REPORT_PATH",
    "RUN_TYPE", "COPY_TO_S3", "GENERATE_DASHBOARD", "PROMETHEUS_ENABLED",
    "PROMETHEUS_IP", "PROMETHEUS_PORT", "PROMETHEUS_DELAY", "PROMETHEUS_URL",
    "GRAFANA_URL", "JMETER_RESULT_AUTOFLUSH", *METADATA_FIELDS,
)


def init_registry() -> None:
    global DB_READY
    if REGISTRY_BACKEND == "postgresql":
        try:
            import psycopg
        except ImportError as exc:
            raise RuntimeError("PostgreSQL registry requires: pip install -r requirements-ui.txt") from exc
        with psycopg.connect(DATABASE_URL) as db:
            db.execute("CREATE TABLE IF NOT EXISTS runs (run_id TEXT PRIMARY KEY, payload JSONB NOT NULL, updated_at DOUBLE PRECISION NOT NULL)")
            db.execute("""CREATE TABLE IF NOT EXISTS run_facts (
                run_id TEXT PRIMARY KEY, label TEXT NOT NULL, status TEXT NOT NULL,
                started_at DOUBLE PRECISION, finished_at DOUBLE PRECISION,
                engine TEXT, engine_build TEXT, cluster_size TEXT, benchmark TEXT, run_type TEXT,
                query_sha256 TEXT, test_plan TEXT, requested_concurrency INTEGER,
                requested_qps DOUBLE PRECISION, requested_qpm DOUBLE PRECISION,
                samples BIGINT, error_pct DOUBLE PRECISION, throughput_per_s DOUBLE PRECISION,
                p50_ms DOUBLE PRECISION, p95_ms DOUBLE PRECISION, p99_ms DOUBLE PRECISION,
                peak_in_flight INTEGER, artifact_uri TEXT, updated_at DOUBLE PRECISION NOT NULL
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS query_results (
                run_id TEXT NOT NULL, transaction TEXT NOT NULL, sample_count BIGINT,
                error_count BIGINT, error_pct DOUBLE PRECISION, mean_ms DOUBLE PRECISION,
                p50_ms DOUBLE PRECISION, p90_ms DOUBLE PRECISION, p95_ms DOUBLE PRECISION,
                p99_ms DOUBLE PRECISION, min_ms DOUBLE PRECISION, max_ms DOUBLE PRECISION,
                throughput_per_s DOUBLE PRECISION, PRIMARY KEY(run_id, transaction)
            )""")
            db.execute("CREATE INDEX IF NOT EXISTS run_facts_search_idx ON run_facts(engine, benchmark, cluster_size, started_at DESC)")
            db.execute("CREATE INDEX IF NOT EXISTS query_results_transaction_idx ON query_results(transaction, run_id)")
    else:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(DB_PATH) as db:
            db.execute("CREATE TABLE IF NOT EXISTS runs (run_id TEXT PRIMARY KEY, payload TEXT NOT NULL, updated_at REAL NOT NULL)")
    DB_READY = True


def persist_run(run: "Run") -> None:
    if not DB_READY:
        return
    payload = {
        "id": run.run_id, "label": run.label, "config": run.config,
        "report_root": str(run.report_root), "status": run.status,
        "started_at": run.started_at, "finished_at": run.finished_at,
        "return_code": run.return_code, "logs": list(run.logs),
    }
    if REGISTRY_BACKEND == "postgresql":
        import psycopg
        from psycopg.types.json import Jsonb
        with psycopg.connect(DATABASE_URL) as db:
            db.execute(
                "INSERT INTO runs(run_id,payload,updated_at) VALUES(%s,%s,%s) "
                "ON CONFLICT(run_id) DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at",
                (run.run_id, Jsonb(payload), time.time()),
            )
            persist_run_facts(db, run)
    else:
        with sqlite3.connect(DB_PATH) as db:
            db.execute(
                "INSERT INTO runs(run_id,payload,updated_at) VALUES(?,?,?) "
                "ON CONFLICT(run_id) DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at",
                (run.run_id, json.dumps(payload), time.time()),
            )


def _numeric(value: Any, integer: bool = False) -> int | float | None:
    try:
        return int(value) if integer else float(value)
    except (TypeError, ValueError):
        return None


def persist_run_facts(db: Any, run: "Run") -> None:
    """Upsert searchable summaries; raw JMeter samples remain in S3/local files."""
    summary_paths = sorted(run.report_root.glob("*/run_summary.json"), key=lambda p: p.stat().st_mtime)
    summary = find_summary(run.report_root) or {}
    meta = summary.get("meta", {})
    env = run.config.get("environment", {})
    marker_paths = sorted(run.report_root.glob("*/s3_upload.json"), key=lambda p: p.stat().st_mtime)
    artifact_uri = None
    if marker_paths:
        try:
            artifact_uri = json.loads(marker_paths[-1].read_text()).get("uri")
        except (OSError, json.JSONDecodeError):
            pass
    latency = summary.get("latency_ms", {})
    values = (
        run.run_id, run.label, run.status, run.started_at, run.finished_at,
        meta.get("engine", env.get("ENGINE")), meta.get("ENGINE_BUILD", env.get("ENGINE_BUILD")),
        meta.get("cluster_size", env.get("CLUSTER_SIZE")), meta.get("benchmark", env.get("BENCHMARK_TYPE")),
        meta.get("run_type", env.get("RUN_TYPE")), meta.get("query_sha256"), meta.get("test_plan"),
        _numeric(meta.get("requested_concurrency", env.get("CONCURRENT_QUERY_COUNT")), True),
        _numeric(meta.get("requested_qps", env.get("QPS"))), _numeric(meta.get("requested_qpm", env.get("QPM"))),
        _numeric(summary.get("samples"), True), _numeric(summary.get("error_pct")),
        _numeric(summary.get("throughput_per_s")), _numeric(latency.get("p50")),
        _numeric(latency.get("p95")), _numeric(latency.get("p99")),
        _numeric(summary.get("peak_in_flight"), True), artifact_uri, time.time(),
    )
    db.execute("""INSERT INTO run_facts(
        run_id,label,status,started_at,finished_at,engine,engine_build,cluster_size,benchmark,run_type,
        query_sha256,test_plan,requested_concurrency,requested_qps,requested_qpm,samples,error_pct,
        throughput_per_s,p50_ms,p95_ms,p99_ms,peak_in_flight,artifact_uri,updated_at)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT(run_id) DO UPDATE SET
        label=excluded.label,status=excluded.status,started_at=excluded.started_at,
        finished_at=excluded.finished_at,engine=excluded.engine,engine_build=excluded.engine_build,
        cluster_size=excluded.cluster_size,benchmark=excluded.benchmark,run_type=excluded.run_type,
        query_sha256=excluded.query_sha256,test_plan=excluded.test_plan,
        requested_concurrency=excluded.requested_concurrency,requested_qps=excluded.requested_qps,
        requested_qpm=excluded.requested_qpm,samples=excluded.samples,error_pct=excluded.error_pct,
        throughput_per_s=excluded.throughput_per_s,p50_ms=excluded.p50_ms,p95_ms=excluded.p95_ms,
        p99_ms=excluded.p99_ms,peak_in_flight=excluded.peak_in_flight,
        artifact_uri=excluded.artifact_uri,updated_at=excluded.updated_at""", values)
    if not summary_paths:
        return
    report_id = str(summary_paths[-1].parent.relative_to(REPORTS))
    try:
        per_query = report_details(report_id)["per_query"]
    except (OSError, ValueError, json.JSONDecodeError):
        return
    db.execute("DELETE FROM query_results WHERE run_id=%s", (run.run_id,))
    for item in per_query:
        db.execute("""INSERT INTO query_results(
            run_id,transaction,sample_count,error_count,error_pct,mean_ms,p50_ms,p90_ms,p95_ms,
            p99_ms,min_ms,max_ms,throughput_per_s) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", (
            run.run_id, item.get("transaction"), _numeric(item.get("sampleCount"), True),
            _numeric(item.get("errorCount"), True), _numeric(item.get("errorPct")),
            _numeric(item.get("meanResTime")), _numeric(item.get("medianResTime")),
            _numeric(item.get("pct1ResTime")), _numeric(item.get("pct2ResTime")),
            _numeric(item.get("pct3ResTime")), _numeric(item.get("minResTime")),
            _numeric(item.get("maxResTime")), _numeric(item.get("throughput")),
        ))


def restore_runs() -> None:
    if not DB_READY:
        return
    if REGISTRY_BACKEND == "postgresql":
        import psycopg
        with psycopg.connect(DATABASE_URL) as db:
            rows = db.execute("SELECT payload FROM runs ORDER BY updated_at").fetchall()
    else:
        with sqlite3.connect(DB_PATH) as db:
            rows = db.execute("SELECT payload FROM runs ORDER BY updated_at").fetchall()
    for (raw,) in rows:
        try:
            item = raw if isinstance(raw, dict) else json.loads(raw)
            status = item["status"]
            if status in {"queued", "running"}:
                status = "interrupted"
            run = Run(
                item["id"], item.get("label", "Benchmark"), item.get("config", {}),
                Path(item["report_root"]), status=status,
                started_at=item.get("started_at"), finished_at=item.get("finished_at"),
                return_code=item.get("return_code"), logs=deque(item.get("logs", []), maxlen=300),
            )
            if run.status == "failed" and run.return_code not in {None, 0}:
                run.status = benchmark_status(
                    run.return_code, find_summary(run.report_root),
                    float(run.config.get("MAX_ERROR_PCT", 5)),
                )
            RUNS[run.run_id] = run
            persist_run(run)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            LOGGER.warning("Ignoring invalid persisted run record")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def host_snapshot() -> dict[str, Any]:
    usage = shutil.disk_usage(ROOT)
    return {
        "captured_at": time.time(), "hostname": os.uname().nodename,
        "cpu_count": os.cpu_count(), "load_average": list(os.getloadavg()),
        "disk_free_bytes": usage.free, "disk_total_bytes": usage.total,
    }


def storage_snapshot() -> dict[str, Any]:
    usage = shutil.disk_usage(REPORTS.parent)
    oldest = min((path.stat().st_mtime for path in REPORTS.glob("**/run_summary.json")), default=None)
    return {
        "registry_backend": REGISTRY_BACKEND, "artifact_backend": "s3+local" if SYSTEM_COPY_TO_S3 else "local",
        "retention_days": REPORT_RETENTION_DAYS, "max_local_report_gb": MAX_LOCAL_REPORT_GB,
        "delete_local_after_s3": DELETE_LOCAL_AFTER_S3,
        "disk_free_gb": round(usage.free / 1024 ** 3, 1),
        "oldest_report_at": oldest,
        "automatic_cleanup": False,
    }


def update_system_settings(values: dict[str, Any]) -> dict[str, Any]:
    global PROMETHEUS_DEFAULT_ENABLED, PROMETHEUS_DEFAULT_PORT, PROMETHEUS_URL, GRAFANA_URL
    global SYSTEM_COPY_TO_S3, SYSTEM_S3_REPORT_PATH, SYSTEM_GENERATE_DASHBOARD
    global REPORT_RETENTION_DAYS, MAX_LOCAL_REPORT_GB
    if not ALLOW_SETTINGS_WRITE:
        raise ValueError("System setting writes are disabled; set BENCHMARK_UI_ALLOW_SETTINGS_WRITE=true")
    booleans = {key: values.get(key) is True for key in ("prometheus_enabled", "copy_to_s3", "generate_dashboard")}
    numbers = {
        "prometheus_port": max(1, min(65535, int(values.get("prometheus_port", PROMETHEUS_DEFAULT_PORT)))),
        "retention_days": max(1, min(3650, int(values.get("retention_days", REPORT_RETENTION_DAYS)))),
        "max_local_report_gb": max(1, min(100000, int(values.get("max_local_report_gb", MAX_LOCAL_REPORT_GB)))),
    }
    strings = {key: _property_value(values.get(key), key) for key in ("prometheus_url", "grafana_url", "s3_report_path")}
    if strings["s3_report_path"] and not strings["s3_report_path"].startswith("s3://"):
        raise ValueError("S3 report path must start with s3://")
    saved = {**booleans, **numbers, **strings}
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(saved, indent=2) + "\n")
    PROMETHEUS_DEFAULT_ENABLED = booleans["prometheus_enabled"]
    SYSTEM_COPY_TO_S3 = booleans["copy_to_s3"]
    SYSTEM_GENERATE_DASHBOARD = booleans["generate_dashboard"]
    PROMETHEUS_DEFAULT_PORT = str(numbers["prometheus_port"])
    REPORT_RETENTION_DAYS, MAX_LOCAL_REPORT_GB = numbers["retention_days"], numbers["max_local_report_gb"]
    PROMETHEUS_URL, GRAFANA_URL, SYSTEM_S3_REPORT_PATH = strings["prometheus_url"], strings["grafana_url"], strings["s3_report_path"]
    return saved


def write_manifest(run: "Run", env: dict[str, str]) -> None:
    query = ROOT / env["QUERY_FILE"]
    plan = ROOT / env["TEST_PLAN"]
    manifest = {
        "schema_version": 1, "run_id": run.run_id, "created_at": time.time(),
        "launch_source": "ui", "environment": {key: env[key] for key in DISPLAY_ENV_FIELDS if key in env},
        "artifacts": {"query_sha256": file_sha256(query), "test_plan_sha256": file_sha256(plan)},
        "host_before": host_snapshot(),
    }
    if env.get("LOAD_PROFILE") and (ROOT / env["LOAD_PROFILE"]).is_file():
        manifest["artifacts"]["load_profile_sha256"] = file_sha256(ROOT / env["LOAD_PROFILE"])
    run.report_root.mkdir(parents=True, exist_ok=True)
    (run.report_root / "ui_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


def preflight(config: dict[str, Any]) -> dict[str, Any]:
    env = build_environment(config, "preflight")
    query_path = ROOT / env["QUERY_FILE"]
    query_info = inspect_query_file(query_path)
    if query_info["errors"]:
        raise ValueError("Invalid QUERY_FILE: " + "; ".join(query_info["errors"][:5]))
    query_count = query_info["rows"]
    warnings = []
    free_gb = shutil.disk_usage(ROOT).free / 1024 ** 3
    if free_gb < 5:
        warnings.append(f"Only {free_gb:.1f} GB free on the load generator")
    if int(env["QPS"]) > int(env["MAX_CONCURRANCY"]):
        warnings.append("QPS exceeds MAX_CONCURRANCY; long queries may cause arrival shortfall")
    return {"ok": True, "query_count": query_count, "warnings": warnings,
            "workload_preview": workload_preview(config),
            "environment": {key: env[key] for key in DISPLAY_ENV_FIELDS if key in env}, "host": host_snapshot()}


def _compress_preview(values: list[float], mode: str, max_points: int = 600) -> tuple[list[float], int]:
    bucket = max(1, (len(values) + max_points - 1) // max_points)
    if bucket == 1:
        return [round(value, 3) for value in values], bucket
    chunks = [values[index:index + bucket] for index in range(0, len(values), bucket)]
    if mode == "concurrency":
        return [round(max(chunk), 3) for chunk in chunks], bucket
    return [round(sum(chunk) / len(chunk), 3) for chunk in chunks], bucket


def workload_preview(config: dict[str, Any]) -> dict[str, Any]:
    """Return the backend's planned workload model in real per-second units."""
    plan = str(config.get("plan", ""))
    if plan not in PLANS:
        raise ValueError("Unknown test plan")
    ramp = int(config.get("RAMP_UP_TIME", 1))
    steps = int(config.get("RAMP_UP_STEPS", 1))
    hold = int(config.get("HOLD_PERIOD", 60))
    concurrency = int(config.get("CONCURRENT_QUERY_COUNT", 2))
    if ramp < 0 or steps < 1 or hold < 1 or concurrency < 1:
        raise ValueError("Workload ramp, duration, and concurrency values are invalid")
    source = "resolved run_test.sh inputs"
    expected_total = None
    if plan.endswith("run_once"):
        values, kind, duration_s = [float(concurrency)], "concurrency", None
        query_file = str(config.get("query_file", "")).strip()
        if query_file:
            query_path = _inside(query_file, "data_files", ".csv")
            query_info = inspect_query_file(ROOT / query_path)
            if not query_info["errors"]:
                expected_total = query_info["rows"]
    elif plan in {"jdbc_concurrency", "http_concurrency"}:
        values = ([concurrency * second / ramp for second in range(ramp)] if ramp else []) + [float(concurrency)] * hold
        kind, duration_s = "concurrency", len(values)
    elif plan in {"jdbc_qps"}:
        rate = int(config.get("QPS", 1))
        values = ([rate * min(steps, int(second * steps / ramp) + 1) / steps
                   for second in range(ramp)] if ramp else []) + [float(rate)] * hold
        # The Arrivals Thread Group schedules at both t=0 and the terminal
        # boundary. Preserve elapsed duration while including that last bucket.
        duration_s = ramp + hold
        values.append(float(rate))
        kind, expected_total = "arrivals", round(sum(values))
    elif plan == "jdbc_qpm":
        rate = int(config.get("QPM", 60)) / 60
        ramp_seconds, hold_seconds = ramp * 60, hold * 60
        values = ([rate * min(steps, int(second * steps / ramp_seconds) + 1) / steps
                   for second in range(ramp_seconds)] if ramp_seconds else []) + [rate] * hold_seconds
        duration_s = ramp_seconds + hold_seconds
        values.append(rate)
        kind, expected_total = "arrivals", round(sum(values))
    elif plan in {"jdbc_arrivals", "http_arrivals"}:
        profile = _inside(str(config.get("load_profile", "")), "test_properties", ".csv")
        values = [float(value) for value in expected_arrivals_per_second(read_arrivals_profile(ROOT / profile))]
        kind, duration_s, expected_total, source = "arrivals", len(values), round(sum(values)), profile
    elif plan == "jdbc_variable_concurrency":
        profile = _inside(str(config.get("load_profile", "")), "test_properties", ".csv")
        values = [float(value) for value in expected_concurrency_per_second(read_concurrency_profile(ROOT / profile))]
        kind, duration_s, source = "concurrency", max(0, len(values) - 1), profile
    else:
        raise ValueError("Unsupported workload preview")
    compressed, bucket = _compress_preview(values, kind)
    return {
        "pattern": PLANS[plan][0],
        "kind": kind, "unit": "queries/sec" if kind == "arrivals" else "queries in flight",
        "values": compressed, "bucket_s": bucket, "duration_s": duration_s,
        "peak": round(max(values), 3) if values else 0, "expected_total": expected_total,
        "source": source, "is_run_once": plan.endswith("run_once"),
    }


def _property_value(value: Any, field: str, required: bool = False) -> str:
    text = str(value or "").strip()
    if required and not text:
        raise ValueError(f"{field} is required")
    if "\n" in text or "\r" in text or "\x00" in text:
        raise ValueError(f"{field} contains an invalid character")
    return text


def read_preset(path: Path) -> dict[str, str]:
    """Read simple shell/JMeter assignments without executing a preset file."""
    values: dict[str, str] = {}
    content = path.read_text(errors="replace")
    for raw in content.splitlines():
        match = re.match(r"^\s*(?:export\s+)?([A-Z][A-Z0-9_]*)=(.*)$", raw)
        if not match:
            continue
        value = match.group(2).strip()
        value = value.split(" #", 1)[0].strip()
        if value[:1] in {"'", '"'} and value[-1:] == value[:1]:
            value = value[1:-1]
        values[match.group(1)] = value
    try:
        cluster_match = re.search(r"CLUSTER_CONFIG\s*=\s*(['\"])(\{.*?\})\1", content, re.DOTALL)
        cluster = json.loads(cluster_match.group(2) if cluster_match else "{}")
        aliases = {"cluster_size": "CLUSTER_SIZE", "estimated_cores": "ESTIMATED_CORES", "memory_gb": "MEMORY_GB", "instance_type": "INSTANCE_TYPE", "executors": "EXECUTORS", "cores_per_executor": "CORES_PER_EXECUTOR", "serverless": "SERVERLESS"}
        for source, target in aliases.items():
            if source in cluster and target not in values:
                values[target] = str(cluster[source])
    except (json.JSONDecodeError, TypeError):
        pass
    return values


def preset_catalog(directory: str, pattern: str) -> list[dict[str, Any]]:
    return [{"file": path.relative_to(ROOT).as_posix(), "name": path.stem, "values": read_preset(path), "editable": path.stem.startswith("ui_")}
            for path in sorted((ROOT / directory).glob(pattern)) if path.is_file()]


def create_preset(kind: str, config: dict[str, Any], overwrite: bool = False) -> str:
    directory = {"workload": "test_properties", "metadata": "metadata_files"}.get(kind)
    suffix = {"workload": ".properties", "metadata": ".txt"}.get(kind)
    if not directory or not suffix:
        raise ValueError("Preset kind must be workload or metadata")
    name = _property_value(config.get("name"), "Preset name", required=True)
    if not PROFILE_NAME.fullmatch(name):
        raise ValueError("Preset name may contain only letters, numbers, dot, dash, and underscore")
    if not name.startswith("ui_"):
        name = "ui_" + name
    allowed = set(NUMERIC_LIMITS) | {"TEST_PLAN", "LOAD_PROFILE", "QUERY_PATH", "RANDOM_ORDER", "RECYCLE_ON_EOF"} if kind == "workload" else set(METADATA_FIELDS)
    values = config.get("values")
    if not isinstance(values, dict):
        raise ValueError("Preset values must be an object")
    clean = {key: _property_value(value, key) for key, value in values.items() if key in allowed and value not in {None, ""}}
    if not clean:
        raise ValueError("Preset has no supported values")
    target = ROOT / directory / f"{name}{suffix}"
    if target.exists() and not overwrite:
        raise ValueError("A preset with this name already exists")
    assignments = (f"{key}={value}" if kind == "workload" else f"{key}={json.dumps(value)}"
                   for key, value in clean.items())
    target.write_text("# Created by Benchmark Studio\n" + "\n".join(assignments) + "\n")
    return target.relative_to(ROOT).as_posix()


def delete_preset(kind: str, name: str) -> str:
    directory = {"workload": "test_properties", "metadata": "metadata_files"}.get(kind)
    suffix = {"workload": ".properties", "metadata": ".txt"}.get(kind)
    clean = Path(name).stem
    if not directory or not suffix or not clean.startswith("ui_") or not PROFILE_NAME.fullmatch(clean):
        raise ValueError("Only locally-created ui_* presets can be deleted")
    target = ROOT / directory / f"{clean}{suffix}"
    if not target.is_file():
        raise ValueError("Preset not found")
    target.unlink()
    return target.relative_to(ROOT).as_posix()


def create_connection_profile(config: dict[str, Any]) -> str:
    """Create a local properties file compatible with run_test.sh.

    The returned value is only the repo-relative filename. Credentials are
    never included in API responses or retained in the in-memory run config.
    """
    name = _property_value(config.get("name"), "Profile name", required=True)
    if not PROFILE_NAME.fullmatch(name):
        raise ValueError("Profile name may contain only letters, numbers, dot, dash, and underscore")
    if not name.endswith("_connection"):
        name += "_connection"
    target = ROOT / "connection_properties" / f"{name}.properties"
    if target.exists():
        raise ValueError("A connection profile with this name already exists")

    transport = _property_value(config.get("transport"), "Transport", required=True).lower()
    if transport == "jdbc":
        engine = _property_value(config.get("engine"), "Engine").lower() or "e6data"
        driver = _property_value(config.get("driver_class"), "DRIVER_CLASS") or JDBC_DRIVERS.get(engine, "")
        values = {
            "CONNECTION_STRING": _property_value(config.get("connection_string"), "CONNECTION_STRING", required=True),
            "USER": _property_value(config.get("user"), "USER"),
            "PASSWORD": _property_value(config.get("password"), "PASSWORD"),
            "DRIVER_CLASS": _property_value(driver, "DRIVER_CLASS", required=True),
        }
        heading = "# JDBC Connection Properties"
    elif transport == "http":
        values = {
            "mainhost": _property_value(config.get("mainhost"), "mainhost", required=True),
            "scheme": _property_value(config.get("scheme"), "scheme") or "https",
            "cluster_name": _property_value(config.get("cluster_name"), "cluster_name", required=True),
            "USER": _property_value(config.get("user"), "USER"),
            "PASSWORD": _property_value(config.get("password"), "PASSWORD"),
            "CATALOG": _property_value(config.get("catalog"), "CATALOG"),
            "SCHEMA": _property_value(config.get("schema"), "SCHEMA"),
        }
        if values["scheme"] not in {"http", "https"}:
            raise ValueError("scheme must be http or https")
        heading = "# HTTP Connection Properties"
    else:
        raise ValueError("Transport must be jdbc or http")

    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        temp.write_text(heading + "\n" + "\n".join(f"{key}={value}" for key, value in values.items()) + "\n")
        temp.chmod(0o600)
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)
    LOGGER.info("created local connection profile=%s transport=%s", target.name, transport)
    return target.relative_to(ROOT).as_posix()


def input_destination(kind: str, filename: str, allow_existing: bool = False) -> Path:
    directory = {"query": "data_files", "profile": "test_properties"}.get(kind)
    clean_name = Path(filename).name
    if not directory or filename != clean_name or not CSV_NAME.fullmatch(clean_name):
        raise ValueError("Input must be a CSV filename for query or profile")
    target = ROOT / directory / clean_name
    if target.exists() and not allow_existing:
        raise ValueError("A local input with this filename already exists")
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def save_input(kind: str, filename: str, content: bytes) -> str:
    if not content or len(content) > 50 * 1024 * 1024:
        raise ValueError("CSV input must be between 1 byte and 50 MB")
    target = input_destination(kind, filename)
    temp = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        temp.write_bytes(content)
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)
    return target.relative_to(ROOT).as_posix()


def import_s3_input(kind: str, uri: str) -> str:
    parsed = urlparse(uri)
    filename = Path(parsed.path).name
    if parsed.scheme != "s3" or not parsed.netloc or not filename:
        raise ValueError("Use a complete s3://bucket/path/file.csv URI")
    target = input_destination(kind, filename, allow_existing=True)
    # S3 selection is idempotent: if this exact destination is already local,
    # select it instead of forcing an overwrite or another network operation.
    if target.exists():
        return target.relative_to(ROOT).as_posix()
    try:
        command = ["aws", "s3", "cp", uri, str(target), "--only-show-errors"]
        result = subprocess.run(command, capture_output=True, text=True, timeout=120, check=False)
        # Public buckets remain readable without credentials. AWS CLI may report
        # an expired session as ExpiredToken or only as an HTTP 400, so retry any
        # signed failure anonymously. Private objects still fail without access.
        if result.returncode != 0:
            result = subprocess.run(
                [*command, "--no-sign-request"], capture_output=True, text=True,
                timeout=120, check=False,
            )
        if result.returncode != 0:
            raise ValueError((result.stderr or "S3 download failed; check AWS credentials and URI").strip()[:500])
        if not target.is_file() or not 0 < target.stat().st_size <= 50 * 1024 * 1024:
            raise ValueError("Downloaded CSV must be between 1 byte and 50 MB")
    except FileNotFoundError as exc:
        raise ValueError("AWS CLI is not installed on the UI host") from exc
    except subprocess.TimeoutExpired as exc:
        raise ValueError("S3 download timed out after 120 seconds") from exc
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return target.relative_to(ROOT).as_posix()


def _inside(relative: str, directory: str, suffix: str) -> str:
    """Return a normalized repo-relative file from one allowed directory."""
    candidate = (ROOT / relative).resolve()
    base = (ROOT / directory).resolve()
    if candidate.parent != base or candidate.suffix.lower() != suffix or not candidate.is_file():
        raise ValueError(f"Invalid {directory} file")
    return candidate.relative_to(ROOT).as_posix()


def _number(config: dict[str, Any], key: str, default: int) -> str:
    try:
        value = int(config.get(key, default))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be an integer") from exc
    low, high = NUMERIC_LIMITS[key]
    if not low <= value <= high:
        raise ValueError(f"{key} must be between {low} and {high}")
    return str(value)


def build_environment(config: dict[str, Any], run_id: str) -> dict[str, str]:
    plan_key = str(config.get("plan", ""))
    if plan_key not in PLANS:
        raise ValueError("Unknown test plan")
    _, plan_path, transport = PLANS[plan_key]
    connection = _inside(str(config.get("connection", "")), "connection_properties", ".properties")
    connection_lines = (ROOT / connection).read_text(errors="ignore").splitlines()
    is_http = any(line.startswith("mainhost=") for line in connection_lines)
    if (transport == "http") != is_http:
        raise ValueError(f"The selected connection is not a {transport.upper()} connection")
    query = _inside(str(config.get("query_file", "")), "data_files", ".csv")

    env = os.environ.copy()
    env.update({
        "RUN_ID": run_id,
        "CONNECTION_FILE": connection,
        "TEST_PLAN": plan_path,
        "QUERY_FILE": query,
        "REPORT_PATH": f"reports/ui-{run_id}",
        "RUN_TYPE": f"ui_{plan_key}",
        "COPY_TO_S3": "true" if SYSTEM_COPY_TO_S3 else "false",
        "GENERATE_DASHBOARD": "true" if config.get("GENERATE_DASHBOARD", SYSTEM_GENERATE_DASHBOARD) is True else "false",
        "PROMETHEUS_ENABLED": "true" if config.get("PROMETHEUS_ENABLED", PROMETHEUS_DEFAULT_ENABLED) is True else "false",
        "RANDOM_ORDER": "true" if config.get("RANDOM_ORDER") is True else "false",
        # A run-once plan must terminate at EOF even if a stale browser form
        # submits RECYCLE_ON_EOF=true. Rate/concurrency plans default to repeat.
        "RECYCLE_ON_EOF": "false" if plan_key.endswith("run_once") else ("true" if config.get("RECYCLE_ON_EOF", True) is True else "false"),
        # UI telemetry tails the JMeter CSV while the process runs. CLI keeps
        # JMeter's lower-I/O buffered default unless explicitly overridden.
        "JMETER_RESULT_AUTOFLUSH": "true",
    })
    configured_engine = _property_value(config.get("engine"), "ENGINE") or "unknown"
    driver = next((line.split("=", 1)[1].strip() for line in connection_lines
                   if line.startswith("DRIVER_CLASS=")), "")
    driver_engines = {value: key for key, value in JDBC_DRIVERS.items()}
    # Existing-profile selection is authoritative. This prevents a manually
    # edited run label or stale engine dropdown from calling a Databricks
    # connection "e6data" (or vice versa) in reports and comparisons.
    engine = driver_engines.get(driver, configured_engine)
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", engine):
        raise ValueError("ENGINE contains invalid characters")
    env["ENGINE"] = engine
    metadata = config.get("metadata") or {}
    if not isinstance(metadata, dict):
        raise ValueError("metadata must be an object")
    for key, limit in METADATA_FIELDS.items():
        value = _property_value(metadata.get(key), key)
        if len(value) > limit:
            raise ValueError(f"{key} must not exceed {limit} characters")
        if value:
            env[key] = value
    defaults = {
        "CONCURRENT_QUERY_COUNT": 2, "QPS": 1, "QPM": 60, "HOLD_PERIOD": 60,
        "RAMP_UP_TIME": 1, "RAMP_UP_STEPS": 1, "MAX_CONCURRANCY": 100,
        "QUERY_TIMEOUT": 300, "LIMIT_RESULTSET": 1000, "MAX_ERROR_PCT": 5,
    }
    for key, default in defaults.items():
        env[key] = _number(config, key, default)
    try:
        prometheus_port = int(config.get("PROMETHEUS_PORT", PROMETHEUS_DEFAULT_PORT))
        prometheus_delay = int(PROMETHEUS_DEFAULT_DELAY)
    except (TypeError, ValueError) as exc:
        raise ValueError("Prometheus port and delay must be integers") from exc
    if not 1 <= prometheus_port <= 65535 or prometheus_delay < 0:
        raise ValueError("Prometheus port must be 1-65535 and delay must be non-negative")
    env.update({"PROMETHEUS_IP": PROMETHEUS_DEFAULT_IP,
                "PROMETHEUS_PORT": str(prometheus_port),
                "PROMETHEUS_DELAY": str(prometheus_delay)})
    if PROMETHEUS_URL:
        env["PROMETHEUS_URL"] = PROMETHEUS_URL
    if GRAFANA_URL:
        env["GRAFANA_URL"] = GRAFANA_URL
    if SYSTEM_S3_REPORT_PATH:
        env["S3_REPORT_PATH"] = SYSTEM_S3_REPORT_PATH
    if plan_key in {"jdbc_arrivals", "http_arrivals"}:
        env["LOAD_PROFILE"] = _inside(str(config.get("load_profile", "")), "test_properties", ".csv")
    elif plan_key == "jdbc_variable_concurrency":
        env["LOAD_PROFILE"] = _inside(str(config.get("load_profile", "")), "test_properties", ".csv")
    return env


def live_metrics(report_root: Path) -> dict[str, Any]:
    files = sorted(report_root.glob("*/JmeterResultFile.csv"), key=lambda p: p.stat().st_mtime)
    if not files:
        return {"samples": 0, "successful": 0, "failed": 0, "throughput": 0, "p50": None, "p95": None, "active": 0, "duration_s": 0, "series": {"arrivals": [], "successful": [], "failed": [], "in_flight": [], "latency_ms": []}}
    rows: list[dict[str, str]] = []
    try:
        with files[-1].open(newline="", errors="replace") as handle:
            parsed = csv.DictReader(handle)
            rows = []
            for row in parsed:
                # JMeter may be midway through appending the final row while
                # the UI polls. Ignore incomplete/malformed rows until the
                # next poll instead of failing the entire API response.
                success = row.get("success")
                if success not in {"true", "false"}:
                    continue
                if not (row.get("timeStamp") or "").isdigit() or not (row.get("elapsed") or "").isdigit():
                    continue
                if (row.get("label") or "").startswith(("Setup-", "Control-")):
                    continue
                rows.append(row)
    except (OSError, csv.Error):
        pass
    if not rows:
        return {"samples": 0, "successful": 0, "failed": 0, "throughput": 0, "p50": None, "p95": None, "active": 0, "duration_s": 0, "series": {"arrivals": [], "successful": [], "failed": [], "in_flight": [], "latency_ms": []}}
    elapsed = sorted(int(row["elapsed"]) for row in rows if row["success"] == "true")
    started = [int(row["timeStamp"]) for row in rows]
    arrival_window = max(0.001, (max(started) - min(started)) / 1000)
    percentile = lambda pct: elapsed[min(len(elapsed) - 1, max(0, (len(elapsed) * pct + 99) // 100 - 1))] if elapsed else None
    origin = min(started)
    last_second = max(max(0, (int(row["timeStamp"]) + int(row.get("elapsed") or 0) - origin) // 1000) for row in rows)
    arrivals = [0] * (last_second + 1)
    successful = [0] * (last_second + 1)
    failed = [0] * (last_second + 1)
    in_flight_events: dict[int, list[int]] = {}
    latency_sum = [0] * (last_second + 1)
    latency_count = [0] * (last_second + 1)
    failures: dict[str, int] = {}
    for row in rows:
        start = max(0, (int(row["timeStamp"]) - origin) // 1000)
        duration = int(row.get("elapsed") or 0)
        end = max(start, (int(row["timeStamp"]) + duration - origin) // 1000)
        arrivals[start] += 1
        # Keep exact millisecond boundaries for concurrency. Rounding both
        # ends to seconds makes a query that finishes early in a bucket appear
        # to overlap another query that starts later in the same bucket.
        start_ms = int(row["timeStamp"]) - origin
        end_ms = start_ms + duration
        in_flight_events.setdefault(start_ms, [0, 0])[1] += 1
        in_flight_events.setdefault(end_ms, [0, 0])[0] += 1
        if row["success"] == "true":
            successful[end] += 1
            latency_sum[end] += duration
            latency_count[end] += 1
        else:
            failed[end] += 1
            message = (row.get("responseMessage") or row.get("failureMessage") or "Unknown error").strip()
            failures[message[:240]] = failures.get(message[:240], 0) + 1
    in_flight: list[int] = []
    current = 0
    ordered_events = sorted(in_flight_events.items())
    event_index = 0
    for second in range(last_second + 1):
        bucket_start = second * 1000
        bucket_end = bucket_start + 1000
        # At an exact boundary, completions occur before new samples start.
        while event_index < len(ordered_events) and ordered_events[event_index][0] == bucket_start:
            _, (ended, began) = ordered_events[event_index]
            current -= ended
            current += began
            event_index += 1
        peak = current
        while event_index < len(ordered_events) and ordered_events[event_index][0] < bucket_end:
            _, (ended, began) = ordered_events[event_index]
            current -= ended
            current += began
            peak = max(peak, current)
            event_index += 1
        in_flight.append(peak)
    latency_series = [round(total / count) if count else 0 for total, count in zip(latency_sum, latency_count)]
    top_failure = max(failures.items(), key=lambda item: item[1]) if failures else None
    series = {"arrivals": arrivals, "successful": successful, "failed": failed, "in_flight": in_flight, "latency_ms": latency_series}
    bucket = max(1, (len(arrivals) + 599) // 600)
    if bucket > 1:
        def chunks(values: list[int]) -> list[list[int]]:
            return [values[index:index + bucket] for index in range(0, len(values), bucket)]
        series = {
            "arrivals": [sum(chunk) for chunk in chunks(arrivals)],
            "successful": [sum(chunk) for chunk in chunks(successful)],
            "failed": [sum(chunk) for chunk in chunks(failed)],
            "in_flight": [max(chunk) for chunk in chunks(in_flight)],
            "latency_ms": [round(sum(value for value in chunk if value) / max(1, sum(1 for value in chunk if value))) for chunk in chunks(latency_series)],
        }
    completion_window = max(0.001, (max(int(row["timeStamp"]) + int(row.get("elapsed") or 0) for row in rows) - origin) / 1000)
    return {
        "samples": len(rows), "successful": len(elapsed), "failed": len(rows) - len(elapsed),
        # Keep throughput completion-based so live/cancelled cards mean the
        # same thing as final run_summary.json. Arrival rate is separate.
        "throughput": round(len(rows) / completion_window, 2),
        "completion_throughput": round(len(rows) / completion_window, 2),
        "arrival_rate": round(len(rows) / arrival_window, 2),
        "arrival_window_s": round(arrival_window, 1),
        "drain_s": round(max(0, completion_window - arrival_window), 1),
        "p50": percentile(50), "p95": percentile(95),
        "duration_s": round(completion_window, 1),
        "active": max((int(row.get("allThreads") or 0) for row in rows), default=0),
        "series": series, "chart_bucket_s": bucket,
        "top_failure": {"message": top_failure[0], "count": top_failure[1]} if top_failure else None,
    }


def find_summary(report_root: Path) -> dict[str, Any] | None:
    summaries = sorted(report_root.glob("*/run_summary.json"), key=lambda p: p.stat().st_mtime)
    if not summaries:
        return None
    try:
        return json.loads(summaries[-1].read_text())
    except (OSError, json.JSONDecodeError):
        return None


def compact_summary(summary: dict[str, Any] | None, points: int = 600) -> dict[str, Any] | None:
    """Bound API chart payloads without changing the report stored on disk."""
    if summary is None:
        return None
    compact = dict(summary)
    longest = max(
        len(summary.get("arrivals_per_s", [])), len(summary.get("in_flight_per_s", [])),
        len(summary.get("completions_per_s", [])), len(summary.get("successful_completions_per_s", [])),
    )
    bucket = max(1, (longest + points - 1) // points)

    def aggregate(values: list[Any], mode: str) -> list[Any]:
        if bucket == 1:
            return values
        chunks = [values[index:index + bucket] for index in range(0, len(values), bucket)]
        return [sum(chunk) if mode == "sum" else max(chunk) for chunk in chunks if chunk]

    if "arrivals_per_s" in summary:
        compact["arrivals_per_s"] = aggregate(summary["arrivals_per_s"], "sum")
    if "in_flight_per_s" in summary:
        compact["in_flight_per_s"] = aggregate(summary["in_flight_per_s"], "max")
    if "completions_per_s" in summary:
        compact["completions_per_s"] = aggregate(summary["completions_per_s"], "sum")
    if "successful_completions_per_s" in summary:
        compact["successful_completions_per_s"] = aggregate(summary["successful_completions_per_s"], "sum")
    if bucket > 1:
        compact["chart_bucket_s"] = bucket
    if isinstance(compact.get("load_profile"), dict):
        compact["load_profile"] = {key: value for key, value in compact["load_profile"].items() if key != "expected_per_s"}
    return compact


def benchmark_status(return_code: int, summary: dict[str, Any] | None, max_error_pct: float) -> str:
    """Keep JMeter benchmark validity separate from optional finalization failures."""
    if summary is not None:
        return "completed" if float(summary.get("error_pct", 100)) <= max_error_pct else "failed"
    return "completed" if return_code == 0 else "failed"


@dataclass
class Run:
    run_id: str
    label: str
    config: dict[str, Any]
    report_root: Path
    status: str = "queued"
    started_at: float | None = None
    finished_at: float | None = None
    return_code: int | None = None
    process: subprocess.Popen[str] | None = field(default=None, repr=False)
    logs: deque[str] = field(default_factory=lambda: deque(maxlen=300), repr=False)

    def public(self) -> dict[str, Any]:
        summary_paths = sorted(self.report_root.glob("*/run_summary.json"), key=lambda p: p.stat().st_mtime)
        summary = find_summary(self.report_root)
        report_id = str(summary_paths[-1].parent.relative_to(REPORTS)) if summary_paths else None
        artifact_storage = None
        markers = sorted(self.report_root.glob("*/s3_upload.json"), key=lambda p: p.stat().st_mtime)
        if markers:
            try:
                artifact_storage = json.loads(markers[-1].read_text())
            except (OSError, json.JSONDecodeError):
                pass
        if artifact_storage is None and any("upload failed:" in line for line in self.logs):
            artifact_storage = {
                "status": "failed",
                "message": "S3 artifact upload failed; see runner output",
            }
        public_config = self.config
        planned = self.config.get("planned_workload")
        # Older persisted run-once records predate planned query totals. Fill
        # them from the same validated query CSV without rewriting history.
        if self.config.get("plan", "").endswith("run_once") \
                and isinstance(planned, dict) and planned.get("expected_total") is None:
            try:
                public_config = dict(self.config)
                public_config["planned_workload"] = workload_preview(self.config)
            except (OSError, ValueError):
                pass
        return {
            "id": self.run_id, "label": self.label, "status": self.status,
            "started_at": self.started_at, "finished_at": self.finished_at,
            "return_code": self.return_code, "config": public_config,
            "metrics": live_metrics(self.report_root), "summary": compact_summary(summary),
            "logs": list(self.logs), "report_path": str(self.report_root.relative_to(ROOT)), "report_id": report_id,
            "artifact_storage": artifact_storage,
            "finalization_warning": self.return_code not in {None, 0} and self.status == "completed",
        }


RUNS: dict[str, Run] = {}
RUN_LOCK = threading.Lock()


def _execute(run: Run, env: dict[str, str]) -> None:
    run.status, run.started_at = "running", time.time()
    persist_run(run)
    LOGGER.info("run=%s status=running label=%s plan=%s", run.run_id, run.label, run.config.get("plan"))
    try:
        run.report_root.mkdir(parents=True, exist_ok=True)
        write_manifest(run, env)
        runner_log = run.report_root / "ui_runner.log"
        run.process = subprocess.Popen(
            [str(ROOT / "run_test.sh")], cwd=ROOT, env=env, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, bufsize=1, start_new_session=True,
        )
        assert run.process.stdout
        with runner_log.open("a") as log_handle:
            for line in run.process.stdout:
                clean = line.rstrip()
                run.logs.append(clean)
                log_handle.write(line)
                log_handle.flush()
        run.return_code = run.process.wait()
        if run.status != "cancelled":
            run.status = benchmark_status(
                run.return_code, find_summary(run.report_root),
                float(run.config.get("MAX_ERROR_PCT", 5)),
            )
    except Exception as exc:  # keep API alive and surface process failures
        run.logs.append(f"UI runner error: {exc}")
        LOGGER.exception("run=%s runner failure", run.run_id)
        run.return_code, run.status = 1, "failed"
    finally:
        run.finished_at = time.time()
        try:
            manifest_path = run.report_root / "ui_manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["host_after"] = host_snapshot()
            manifest["return_code"] = run.return_code
            manifest["status"] = run.status
            upload_markers = sorted(run.report_root.glob("*/s3_upload.json"))
            if upload_markers:
                manifest["artifact_storage"] = json.loads(upload_markers[-1].read_text())
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
            for summary_path in run.report_root.glob("*/run_summary.json"):
                (summary_path.parent / "ui_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        except (OSError, json.JSONDecodeError):
            LOGGER.exception("run=%s could not finalize manifest", run.run_id)
        persist_run(run)
        LOGGER.info("run=%s status=%s return_code=%s report=%s", run.run_id, run.status, run.return_code, run.report_root)


def prepare_run(config: dict[str, Any], label: str = "Benchmark") -> tuple[Run, dict[str, str]]:
    run_id = uuid.uuid4().hex[:10]
    env = build_environment(config, run_id)
    public_config = {key: value for key, value in config.items() if key in PUBLIC_RUN_FIELDS}
    public_config["engine"] = env["ENGINE"]
    public_config["planned_workload"] = workload_preview(config)
    public_config["environment"] = {key: env[key] for key in DISPLAY_ENV_FIELDS if key in env}
    run = Run(run_id, label[:80], public_config, REPORTS / f"ui-{run_id}")
    with RUN_LOCK:
        RUNS[run_id] = run
    persist_run(run)
    return run, env


def start_runs(configs: list[dict[str, Any]], sequential: bool = False) -> list[Run]:
    prepared = [prepare_run(item, str(item.get("label") or f"Engine {index + 1}")) for index, item in enumerate(configs)]
    if sequential:
        def execute_in_order() -> None:
            for run, env in prepared:
                _execute(run, env)
        threading.Thread(target=execute_in_order, daemon=True).start()
    else:
        for run, env in prepared:
            threading.Thread(target=_execute, args=(run, env), daemon=True).start()
    return [run for run, _ in prepared]


def completed_reports() -> list[dict[str, Any]]:
    found = []
    for path in REPORTS.glob("**/run_summary.json"):
        try:
            summary = json.loads(path.read_text())
            found.append({"id": str(path.parent.relative_to(REPORTS)), "mtime": path.stat().st_mtime, "summary": compact_summary(summary)})
        except (OSError, json.JSONDecodeError):
            continue
    return sorted(found, key=lambda item: item["mtime"], reverse=True)[:200]


def report_by_id(report_id: str) -> dict[str, Any]:
    path = (REPORTS / report_id / "run_summary.json").resolve()
    if REPORTS.resolve() not in path.parents or not path.is_file():
        raise ValueError("Unknown report")
    return json.loads(path.read_text())


def report_details(report_id: str) -> dict[str, Any]:
    directory = (REPORTS / report_id).resolve()
    if REPORTS.resolve() not in directory.parents or not directory.is_dir():
        raise ValueError("Unknown report")
    summary = report_by_id(report_id)
    statistics_file = directory / "statistics.json"
    if not statistics_file.is_file():
        statistics_file = directory / "dashboard" / "statistics.json"
    if statistics_file.is_file():
        statistics = json.loads(statistics_file.read_text())
        per_query = []
        for label, item in sorted(statistics.items()):
            if label == "Total" or label.startswith(("Setup-", "Control-")) or not isinstance(item, dict):
                continue
            per_query.append({key: item.get(key) for key in (
                "transaction", "sampleCount", "errorCount", "errorPct", "meanResTime",
                "medianResTime", "minResTime", "maxResTime", "pct1ResTime",
                "pct2ResTime", "pct3ResTime", "throughput",
            )})
        artifacts = [path.name for path in directory.iterdir() if path.is_file()]
        return {
            "id": report_id, "summary": summary, "per_query": per_query,
            "per_query_source": "JMeter statistics.json", "artifacts": sorted(artifacts),
            "dashboard": (directory / "dashboard" / "index.html").is_file(),
        }

    result_file = directory / "JmeterResultFile.csv"
    grouped: dict[str, list[dict[str, str]]] = {}
    if result_file.is_file():
        with result_file.open(newline="", errors="replace") as handle:
            for row in csv.DictReader(handle):
                label, success, elapsed = row.get("label"), row.get("success"), row.get("elapsed")
                if not label or label.startswith(("Setup-", "Control-")) or success not in {"true", "false"} or not (elapsed or "").isdigit():
                    continue
                grouped.setdefault(label, []).append(row)

    def percentile(values: list[int], pct: int) -> int | None:
        if not values:
            return None
        ordered = sorted(values)
        index = min(len(ordered) - 1, max(0, (len(ordered) * pct + 99) // 100 - 1))
        return ordered[index]

    per_query = []
    for label, rows in sorted(grouped.items()):
        elapsed_values = [int(row["elapsed"]) for row in rows]
        failures = sum(row["success"] == "false" for row in rows)
        messages: dict[str, int] = {}
        for row in rows:
            if row["success"] == "false":
                message = (row.get("responseMessage") or "Unknown error").strip()[:240]
                messages[message] = messages.get(message, 0) + 1
        top_error = max(messages.items(), key=lambda item: item[1])[0] if messages else None
        per_query.append({
            "transaction": label, "sampleCount": len(rows), "errorCount": failures,
            "errorPct": round(failures / len(rows) * 100, 3),
            "minResTime": min(elapsed_values),
            "meanResTime": round(sum(elapsed_values) / len(elapsed_values)),
            "medianResTime": percentile(elapsed_values, 50), "pct1ResTime": percentile(elapsed_values, 90),
            "pct2ResTime": percentile(elapsed_values, 95), "pct3ResTime": percentile(elapsed_values, 99),
            "maxResTime": max(elapsed_values), "throughput": None,
            "topError": top_error,
        })
    artifacts = [path.name for path in directory.iterdir() if path.is_file()]
    return {"id": report_id, "summary": summary, "per_query": per_query, "per_query_source": "JmeterResultFile.csv fallback", "artifacts": sorted(artifacts), "dashboard": (directory / "dashboard" / "index.html").is_file()}


def comparison(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    def value(data: dict[str, Any], *keys: str) -> float:
        current: Any = data
        for key in keys:
            current = current.get(key, {}) if isinstance(current, dict) else 0
        return float(current or 0)
    metrics = {
        "planned_arrivals": (("load_profile", "expected"), None),
        "fired_samples": (("samples",), None), "successful": (("successful",), True),
        "failed": (("failed",), False),
        "accepted_load_pct": (("load_profile", "delivered_pct"), True),
        "throughput_per_s": (("throughput_per_s",), True), "error_pct": (("error_pct",), False),
        "mean_ms": (("latency_ms", "mean"), False),
        "p50_ms": (("latency_ms", "p50"), False), "p95_ms": (("latency_ms", "p95"), False),
        "p99_ms": (("latency_ms", "p99"), False), "peak_in_flight": (("peak_in_flight",), False),
        "arrival_window_s": (("arrival_window_s",), None), "drain_s": (("drain_s",), False),
        "wall_clock_s": (("wall_clock_s",), False),
    }
    delta = {}
    for name, (path, higher_better) in metrics.items():
        a, b = value(left, *path), value(right, *path)
        pct = round((b - a) / a * 100, 2) if a else None
        ratio = round(b / a, 3) if a else None
        delta[name] = {"left": a, "right": b, "change_pct": pct, "ratio": ratio, "higher_is_better": higher_better}
    left_meta, right_meta = left.get("meta", {}), right.get("meta", {})
    compatibility = []
    for key in ("query_sha256", "test_plan", "profile_sha256", "requested_concurrency", "requested_qps", "requested_qpm", "hold_period"):
        a, b = left_meta.get(key), right_meta.get(key)
        if a not in {None, ""} and b not in {None, ""} and a != b:
            compatibility.append({"field": key, "left": a, "right": b, "severity": "workload"})
    for key, legacy in (("engine", "engine"), ("CLUSTER_SIZE", "cluster_size"), ("ENGINE_BUILD", "ENGINE_BUILD")):
        a = left_meta.get(key, left_meta.get(legacy))
        b = right_meta.get(key, right_meta.get(legacy))
        if a not in {None, ""} and b not in {None, ""} and a != b:
            compatibility.append({"field": key, "left": a, "right": b, "severity": "context"})
    left_success, right_success = int(value(left, "successful")), int(value(right, "successful"))
    left_samples, right_samples = int(value(left, "samples")), int(value(right, "samples"))
    survivor_bias = None
    if left_success != right_success or left_success != left_samples or right_success != right_samples:
        survivor_bias = (
            "Latency percentiles only include successful samples. "
            f"Baseline latency uses {left_success}/{left_samples} successful samples; "
            f"candidate latency uses {right_success}/{right_samples}. "
            "Treat latency ratios as survivor-biased when completion populations differ."
        )

    def failures(summary: dict[str, Any]) -> list[dict[str, Any]]:
        return list(summary.get("failure_messages") or [])[:5]

    return {
        "left": compact_summary(left), "right": compact_summary(right), "metrics": delta,
        "compatibility": compatibility, "survivor_bias": survivor_bias,
        "failure_reasons": {"left": failures(left), "right": failures(right)},
    }


def per_query_comparison(left_id: str, right_id: str) -> list[dict[str, Any]]:
    """Join the standard JMeter per-label statistics without recalculating them."""
    left = {row.get("transaction"): row for row in report_details(left_id)["per_query"]}
    right = {row.get("transaction"): row for row in report_details(right_id)["per_query"]}
    rows = []
    for label in sorted(set(left) | set(right)):
        a, b = left.get(label), right.get(label)
        a_p95 = a.get("pct2ResTime") if a else None
        b_p95 = b.get("pct2ResTime") if b else None
        ratio = round(float(b_p95) / float(a_p95), 3) if a_p95 not in {None, 0} and b_p95 is not None else None
        rows.append({"label": label, "left": a, "right": b, "p95_ratio": ratio})
    return rows


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def log_message(self, fmt: str, *args: Any) -> None:
        LOGGER.info("client=%s %s", self.address_string(), fmt % args)

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        super().end_headers()

    def _authorized(self) -> bool:
        if not AUTH_TOKEN:
            return True
        header = self.headers.get("Authorization", "")
        try:
            scheme, encoded = header.split(" ", 1)
            decoded = base64.b64decode(encoded).decode()
            _, password = decoded.split(":", 1)
            return scheme.lower() == "basic" and hmac.compare_digest(password, AUTH_TOKEN)
        except (ValueError, UnicodeDecodeError):
            return False

    def _require_auth(self) -> bool:
        if self._authorized():
            return False
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="e6data Benchmark Studio"')
        self.send_header("Content-Length", "0")
        self.end_headers()
        return True

    def _json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 1_000_000:
            raise ValueError("Request too large")
        return json.loads(self.rfile.read(length) or b"{}")

    def _dashboard_asset(self, request_path: str) -> None:
        remainder = request_path.removeprefix("/artifacts/")
        encoded_id, separator, asset = remainder.partition("/dashboard/")
        if not separator:
            raise ValueError("Unknown dashboard artifact")
        directory = (REPORTS / unquote(encoded_id) / "dashboard").resolve()
        path = (directory / asset).resolve()
        if REPORTS.resolve() not in directory.parents or directory not in path.parents or not path.is_file():
            raise ValueError("Unknown dashboard artifact")
        content = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/healthz":
            self._json({"status": "ok"})
            return
        if parsed.path == "/readyz":
            ready = DB_READY and (ROOT / "run_test.sh").is_file() and REPORTS.parent.is_dir()
            self._json({"status": "ready" if ready else "not_ready"}, 200 if ready else 503)
            return
        if self._require_auth():
            return
        try:
            if parsed.path == "/api/config":
                connections = sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "connection_properties").glob("*.properties"))
                queries = sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "data_files").glob("*.csv"))
                profiles = sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "test_properties").glob("*.csv"))
                self._json({"plans": [{"id": k, "label": v[0], "path": v[1], "transport": v[2]} for k, v in PLANS.items()], "connections": connections, "queries": queries, "profiles": profiles, "workload_presets": preset_catalog("test_properties", "*.properties"), "metadata_presets": preset_catalog("metadata_files", "*.txt"), "observability": {"enabled": PROMETHEUS_DEFAULT_ENABLED, "port": int(PROMETHEUS_DEFAULT_PORT), "prometheus_url": PROMETHEUS_URL, "grafana_url": GRAFANA_URL}, "system": {"settings_write_enabled": ALLOW_SETTINGS_WRITE, "copy_to_s3": SYSTEM_COPY_TO_S3, "s3_report_path": SYSTEM_S3_REPORT_PATH, "generate_dashboard": SYSTEM_GENERATE_DASHBOARD, "auth_enabled": bool(AUTH_TOKEN), "db_path": str(DB_PATH) if REGISTRY_BACKEND == "sqlite" else "Configured PostgreSQL service", "reports_path": str(REPORTS), **storage_snapshot()}})
            elif parsed.path == "/api/runs":
                with RUN_LOCK:
                    self._json([run.public() for run in RUNS.values()])
            elif parsed.path.startswith("/api/runs/"):
                run_id = parsed.path.rsplit("/", 1)[-1]
                with RUN_LOCK:
                    run = RUNS.get(run_id)
                self._json(run.public() if run else {"error": "Unknown run"}, 200 if run else 404)
            elif parsed.path == "/api/reports":
                self._json(completed_reports())
            elif parsed.path == "/api/report":
                report_id = parse_qs(parsed.query).get("id", [""])[0]
                self._json(report_by_id(report_id))
            elif parsed.path == "/api/report-details":
                report_id = parse_qs(parsed.query).get("id", [""])[0]
                self._json(report_details(report_id))
            elif parsed.path.startswith("/artifacts/"):
                self._dashboard_asset(parsed.path)
            else:
                super().do_GET()
        except (ValueError, json.JSONDecodeError) as exc:
            self._json({"error": str(exc)}, 400)
        except Exception:
            LOGGER.exception("Unhandled GET error path=%s", self.path)
            self._json({"error": "UI backend error; see logs/ui.log"}, 500)

    def do_POST(self) -> None:
        if self._require_auth():
            return
        try:
            parsed = urlparse(self.path)
            if parsed.path == "/api/upload":
                length = int(self.headers.get("Content-Length", "0"))
                if length > 50 * 1024 * 1024:
                    raise ValueError("CSV input must not exceed 50 MB")
                params = parse_qs(parsed.query)
                saved = save_input(params.get("kind", [""])[0], unquote(params.get("name", [""])[0]), self.rfile.read(length))
                self._json({"file": saved}, HTTPStatus.CREATED)
                return
            body = self._body()
            if self.path == "/api/runs":
                configs = body.get("runs") or [body]
                if not isinstance(configs, list) or not 1 <= len(configs) <= 2:
                    raise ValueError("Start one or two runs at a time")
                # Validate the complete pair before starting either process.
                for item in configs:
                    if not isinstance(item, dict):
                        raise ValueError("Each run must be an object")
                    build_environment(item, "validation")
                execution_mode = str(body.get("execution_mode", "parallel"))
                if execution_mode not in {"parallel", "sequential"}:
                    raise ValueError("execution_mode must be parallel or sequential")
                if execution_mode == "parallel" and len(configs) == 2 \
                        and any(item.get("PROMETHEUS_ENABLED") is True for item in configs):
                    raise ValueError(
                        "Parallel Prometheus runs need distinct ports and scrape targets; "
                        "choose sequential execution or disable Prometheus"
                    )
                runs = start_runs(configs, sequential=execution_mode == "sequential")
                self._json({"runs": [run.public() for run in runs]}, HTTPStatus.ACCEPTED)
            elif self.path == "/api/connections":
                connection = create_connection_profile(body)
                self._json({"connection": connection}, HTTPStatus.CREATED)
            elif self.path == "/api/import-s3":
                saved = import_s3_input(str(body.get("kind", "")), str(body.get("uri", "")))
                self._json({"file": saved}, HTTPStatus.CREATED)
            elif self.path == "/api/presets":
                saved = create_preset(str(body.get("kind", "")), body, overwrite=body.get("overwrite") is True)
                self._json({"file": saved}, HTTPStatus.CREATED)
            elif self.path == "/api/presets/delete":
                deleted = delete_preset(str(body.get("kind", "")), str(body.get("name", "")))
                self._json({"file": deleted})
            elif self.path == "/api/system-settings":
                self._json(update_system_settings(body))
            elif self.path == "/api/workload-preview":
                self._json(workload_preview(body))
            elif self.path == "/api/preflight":
                self._json(preflight(body))
            elif self.path.endswith("/cancel") and self.path.startswith("/api/runs/"):
                run_id = self.path.split("/")[3]
                with RUN_LOCK:
                    run = RUNS.get(run_id)
                if not run or not run.process or run.status != "running":
                    raise ValueError("Run is not active")
                os.killpg(run.process.pid, signal.SIGTERM)
                run.status = "cancelled"
                persist_run(run)
                LOGGER.info("run=%s cancellation requested", run.run_id)
                self._json(run.public())
            elif self.path == "/api/compare":
                left_id, right_id = str(body.get("left", "")), str(body.get("right", ""))
                result = comparison(report_by_id(left_id), report_by_id(right_id))
                result["per_query"] = per_query_comparison(left_id, right_id)
                self._json(result)
            else:
                self._json({"error": "Not found"}, 404)
        except (ValueError, json.JSONDecodeError) as exc:
            self._json({"error": str(exc)}, 400)
        except Exception:
            LOGGER.exception("Unhandled POST error path=%s", self.path)
            self._json({"error": "UI backend error; see logs/ui.log"}, 500)


def main() -> None:
    parser = argparse.ArgumentParser(description="Optional local UI for JMeter benchmarks")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address; localhost by default")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(LOG_DIR / "ui.log"), logging.StreamHandler()],
    )
    if args.host not in {"127.0.0.1", "localhost", "::1"} and not AUTH_TOKEN:
        parser.exit(2, "Remote binding requires BENCHMARK_UI_TOKEN. Put TLS in front of this service.\n")
    init_registry()
    restore_runs()
    try:
        server = ThreadingHTTPServer((args.host, args.port), Handler)
    except OSError as exc:
        if exc.errno == errno.EADDRINUSE:
            parser.exit(
                2,
                f"Benchmark UI could not start: {args.host}:{args.port} is already in use.\n"
                f"Open http://{args.host}:{args.port} if the UI is already running, or use:\n"
            f"  ./start_ui.sh --port {args.port + 1}\n",
            )
        raise
    LOGGER.info("JMeter Benchmark UI listening at http://%s:%s", args.host, args.port)
    LOGGER.info("CLI runners remain available and unchanged")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
