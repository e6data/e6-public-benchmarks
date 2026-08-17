#!/usr/bin/env python3
"""Local-only UI/API adapter over the existing run_test.sh contract.

The CLI runner remains the source of truth. This module only validates a small
allowlist of inputs, starts that runner as an isolated process, and reads the
same CSV/JSON artifacts that CLI users already receive.
"""

from __future__ import annotations

import argparse
import csv
import errno
import json
import logging
import mimetypes
import os
import re
import signal
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


ROOT = Path(__file__).resolve().parents[1]
STATIC = Path(__file__).resolve().parent / "static"
REPORTS = ROOT / "reports"
LOG_DIR = ROOT / "logs"
LOGGER = logging.getLogger("benchmark-ui")

PLANS = {
    "jdbc_run_once": ("Run once", "Test-Plans/Test-Plan-Run-Once-static-concurrency.jmx", "jdbc"),
    "jdbc_concurrency": ("Fixed concurrency", "Test-Plans/Test-Plan-Maintain-static-concurrency.jmx", "jdbc"),
    "jdbc_qps": ("Constant QPS", "Test-Plans/Test-Plan-Constant-QPS-On-Arrivals-JSR-Optimized.jmx", "jdbc"),
    "jdbc_qpm": ("Constant QPM", "Test-Plans/Test-Plan-Constant-QPM-On-Arrivals.jmx", "jdbc"),
    "jdbc_arrivals": ("Variable arrival rate", "Test-Plans/Test-Plan-Fire-QPS-with-load-profile.jmx", "jdbc"),
    "jdbc_variable_concurrency": ("Variable concurrency", "Test-Plans/Test-Plan-Maintain-variable-concurrency-with-load-profile.jmx", "jdbc"),
    "http_run_once": ("Run once (HTTP)", "Test-Plans/Test-Plan-Run-Once-http-endpoint.jmx", "http"),
    "http_concurrency": ("Fixed concurrency (HTTP)", "Test-Plans/Test-Plan-Maintain-static-concurrency-http-endpoint-v2.jmx", "http"),
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
    "RECYCLE_ON_EOF", "RANDOM_ORDER", "GENERATE_DASHBOARD", "execution_mode", "metadata",
}
METADATA_FIELDS = {
    "CLUSTER_SIZE": 80, "BENCHMARK_TYPE": 100, "DATA_SIZE": 40,
    "DATA_TYPE": 40, "RUN_MODE": 40, "CUSTOMER": 100, "CONFIG": 120,
    "TAGS": 300, "COMMENTS": 1000, "ESTIMATED_CORES": 20, "MEMORY_GB": 20,
    "INSTANCE_TYPE": 100, "EXECUTORS": 20, "CORES_PER_EXECUTOR": 20,
    "SERVERLESS": 20, "ENGINE_BUILD": 120,
}
DISPLAY_ENV_FIELDS = (
    "ENGINE", "CONNECTION_FILE", "TEST_PLAN", "QUERY_FILE", "LOAD_PROFILE",
    "CONCURRENT_QUERY_COUNT", "QPS", "QPM", "HOLD_PERIOD", "RAMP_UP_TIME",
    "RAMP_UP_STEPS", "MAX_CONCURRANCY", "QUERY_TIMEOUT", "LIMIT_RESULTSET",
    "MAX_ERROR_PCT", "RECYCLE_ON_EOF", "RANDOM_ORDER", "REPORT_PATH",
    "RUN_TYPE", "COPY_TO_S3", "GENERATE_DASHBOARD", *METADATA_FIELDS,
)


def _property_value(value: Any, field: str, required: bool = False) -> str:
    text = str(value or "").strip()
    if required and not text:
        raise ValueError(f"{field} is required")
    if "\n" in text or "\r" in text or "\x00" in text:
        raise ValueError(f"{field} contains an invalid character")
    return text


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


def input_destination(kind: str, filename: str) -> Path:
    directory = {"query": "data_files", "profile": "test_properties"}.get(kind)
    clean_name = Path(filename).name
    if not directory or filename != clean_name or not CSV_NAME.fullmatch(clean_name):
        raise ValueError("Input must be a CSV filename for query or profile")
    target = ROOT / directory / clean_name
    if target.exists():
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
    target = input_destination(kind, filename)
    try:
        result = subprocess.run(
            ["aws", "s3", "cp", uri, str(target), "--only-show-errors"],
            capture_output=True, text=True, timeout=120, check=False,
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
    is_http = any(line.startswith("mainhost=") for line in (ROOT / connection).read_text(errors="ignore").splitlines())
    if (transport == "http") != is_http:
        raise ValueError(f"The selected connection is not a {transport.upper()} connection")
    query = _inside(str(config.get("query_file", "")), "data_files", ".csv")

    env = os.environ.copy()
    env.update({
        "CONNECTION_FILE": connection,
        "TEST_PLAN": plan_path,
        "QUERY_FILE": query,
        "REPORT_PATH": f"reports/ui-{run_id}",
        "RUN_TYPE": f"ui_{plan_key}",
        "COPY_TO_S3": "false",
        "GENERATE_DASHBOARD": "true" if config.get("GENERATE_DASHBOARD", True) is True else "false",
        "RANDOM_ORDER": "true" if config.get("RANDOM_ORDER") is True else "false",
        # A run-once plan must terminate at EOF even if a stale browser form
        # submits RECYCLE_ON_EOF=true. Rate/concurrency plans default to repeat.
        "RECYCLE_ON_EOF": "false" if plan_key.endswith("run_once") else ("true" if config.get("RECYCLE_ON_EOF", True) is True else "false"),
    })
    engine = _property_value(config.get("engine"), "ENGINE") or "unknown"
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
    if plan_key in {"jdbc_arrivals", "http_arrivals"}:
        env["LOAD_PROFILE"] = _inside(str(config.get("load_profile", "")), "test_properties", ".csv")
    elif plan_key == "jdbc_variable_concurrency":
        env["LOAD_PROFILE"] = _inside(str(config.get("load_profile", "")), "test_properties", ".csv")
    return env


def live_metrics(report_root: Path) -> dict[str, Any]:
    files = sorted(report_root.glob("*/JmeterResultFile.csv"), key=lambda p: p.stat().st_mtime)
    if not files:
        return {"samples": 0, "successful": 0, "failed": 0, "throughput": 0, "p50": None, "p95": None, "active": 0, "series": {"arrivals": [], "in_flight": [], "latency_ms": []}}
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
        return {"samples": 0, "successful": 0, "failed": 0, "throughput": 0, "p50": None, "p95": None, "active": 0, "series": {"arrivals": [], "in_flight": [], "latency_ms": []}}
    elapsed = sorted(int(row["elapsed"]) for row in rows if row["success"] == "true")
    started = [int(row["timeStamp"]) for row in rows]
    window = max(1, (max(started) - min(started)) / 1000)
    percentile = lambda pct: elapsed[min(len(elapsed) - 1, max(0, (len(elapsed) * pct + 99) // 100 - 1))] if elapsed else None
    origin = min(started)
    last_second = max(max(0, (int(row["timeStamp"]) + int(row.get("elapsed") or 0) - origin) // 1000) for row in rows)
    arrivals = [0] * (last_second + 1)
    in_flight_delta = [0] * (last_second + 2)
    latency_sum = [0] * (last_second + 1)
    latency_count = [0] * (last_second + 1)
    failures: dict[str, int] = {}
    for row in rows:
        start = max(0, (int(row["timeStamp"]) - origin) // 1000)
        duration = int(row.get("elapsed") or 0)
        end = max(start, (int(row["timeStamp"]) + duration - origin) // 1000)
        arrivals[start] += 1
        # Difference array keeps polling linear in rows + seconds. Iterating
        # over every active second for every sample made long runs block the API.
        in_flight_delta[start] += 1
        in_flight_delta[min(end + 1, len(in_flight_delta) - 1)] -= 1
        latency_sum[end] += duration
        latency_count[end] += 1
        if row["success"] != "true":
            message = (row.get("responseMessage") or row.get("failureMessage") or "Unknown error").strip()
            failures[message[:240]] = failures.get(message[:240], 0) + 1
    in_flight: list[int] = []
    current = 0
    for change in in_flight_delta[:-1]:
        current += change
        in_flight.append(current)
    latency_series = [round(total / count) if count else 0 for total, count in zip(latency_sum, latency_count)]
    top_failure = max(failures.items(), key=lambda item: item[1]) if failures else None
    series = {"arrivals": arrivals, "in_flight": in_flight, "latency_ms": latency_series}
    bucket = max(1, (len(arrivals) + 599) // 600)
    if bucket > 1:
        def chunks(values: list[int]) -> list[list[int]]:
            return [values[index:index + bucket] for index in range(0, len(values), bucket)]
        series = {
            "arrivals": [sum(chunk) for chunk in chunks(arrivals)],
            "in_flight": [max(chunk) for chunk in chunks(in_flight)],
            "latency_ms": [round(sum(value for value in chunk if value) / max(1, sum(1 for value in chunk if value))) for chunk in chunks(latency_series)],
        }
    return {
        "samples": len(rows), "successful": len(elapsed), "failed": len(rows) - len(elapsed),
        "throughput": round(len(rows) / window, 2), "p50": percentile(50), "p95": percentile(95),
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
    longest = max(len(summary.get("arrivals_per_s", [])), len(summary.get("in_flight_per_s", [])))
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
    if bucket > 1:
        compact["chart_bucket_s"] = bucket
    if isinstance(compact.get("load_profile"), dict):
        compact["load_profile"] = {key: value for key, value in compact["load_profile"].items() if key != "expected_per_s"}
    return compact


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
        return {
            "id": self.run_id, "label": self.label, "status": self.status,
            "started_at": self.started_at, "finished_at": self.finished_at,
            "return_code": self.return_code, "config": self.config,
            "metrics": live_metrics(self.report_root), "summary": compact_summary(summary),
            "logs": list(self.logs), "report_path": str(self.report_root.relative_to(ROOT)), "report_id": report_id,
        }


RUNS: dict[str, Run] = {}
RUN_LOCK = threading.Lock()


def _execute(run: Run, env: dict[str, str]) -> None:
    run.status, run.started_at = "running", time.time()
    LOGGER.info("run=%s status=running label=%s plan=%s", run.run_id, run.label, run.config.get("plan"))
    try:
        run.report_root.mkdir(parents=True, exist_ok=True)
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
            run.status = "completed" if run.return_code == 0 else "failed"
    except Exception as exc:  # keep API alive and surface process failures
        run.logs.append(f"UI runner error: {exc}")
        LOGGER.exception("run=%s runner failure", run.run_id)
        run.return_code, run.status = 1, "failed"
    finally:
        run.finished_at = time.time()
        LOGGER.info("run=%s status=%s return_code=%s report=%s", run.run_id, run.status, run.return_code, run.report_root)


def prepare_run(config: dict[str, Any], label: str = "Benchmark") -> tuple[Run, dict[str, str]]:
    run_id = uuid.uuid4().hex[:10]
    env = build_environment(config, run_id)
    public_config = {key: value for key, value in config.items() if key in PUBLIC_RUN_FIELDS}
    public_config["environment"] = {key: env[key] for key in DISPLAY_ENV_FIELDS if key in env}
    run = Run(run_id, label[:80], public_config, REPORTS / f"ui-{run_id}")
    with RUN_LOCK:
        RUNS[run_id] = run
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
        "throughput_per_s": (("throughput_per_s",), True), "error_pct": (("error_pct",), False),
        "p50_ms": (("latency_ms", "p50"), False), "p95_ms": (("latency_ms", "p95"), False),
        "p99_ms": (("latency_ms", "p99"), False), "peak_in_flight": (("peak_in_flight",), False),
        "drain_s": (("drain_s",), False),
    }
    delta = {}
    for name, (path, higher_better) in metrics.items():
        a, b = value(left, *path), value(right, *path)
        pct = round((b - a) / a * 100, 2) if a else None
        delta[name] = {"left": a, "right": b, "change_pct": pct, "higher_is_better": higher_better}
    return {"left": compact_summary(left), "right": compact_summary(right), "metrics": delta}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def log_message(self, fmt: str, *args: Any) -> None:
        LOGGER.info("client=%s %s", self.address_string(), fmt % args)

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
        try:
            if parsed.path == "/api/config":
                connections = sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "connection_properties").glob("*.properties"))
                queries = sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "data_files").glob("*.csv"))
                profiles = sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "test_properties").glob("*.csv"))
                self._json({"plans": [{"id": k, "label": v[0], "path": v[1], "transport": v[2]} for k, v in PLANS.items()], "connections": connections, "queries": queries, "profiles": profiles})
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
                runs = start_runs(configs, sequential=execution_mode == "sequential")
                self._json({"runs": [run.public() for run in runs]}, HTTPStatus.ACCEPTED)
            elif self.path == "/api/connections":
                connection = create_connection_profile(body)
                self._json({"connection": connection}, HTTPStatus.CREATED)
            elif self.path == "/api/import-s3":
                saved = import_s3_input(str(body.get("kind", "")), str(body.get("uri", "")))
                self._json({"file": saved}, HTTPStatus.CREATED)
            elif self.path.endswith("/cancel") and self.path.startswith("/api/runs/"):
                run_id = self.path.split("/")[3]
                with RUN_LOCK:
                    run = RUNS.get(run_id)
                if not run or not run.process or run.status != "running":
                    raise ValueError("Run is not active")
                os.killpg(run.process.pid, signal.SIGTERM)
                run.status = "cancelled"
                LOGGER.info("run=%s cancellation requested", run.run_id)
                self._json(run.public())
            elif self.path == "/api/compare":
                self._json(comparison(report_by_id(str(body.get("left", ""))), report_by_id(str(body.get("right", "")))))
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
    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        LOGGER.warning("Remote binding has no built-in authentication; use a secured reverse proxy")
    try:
        server = ThreadingHTTPServer((args.host, args.port), Handler)
    except OSError as exc:
        if exc.errno == errno.EADDRINUSE:
            parser.exit(
                2,
                f"Benchmark UI could not start: {args.host}:{args.port} is already in use.\n"
                f"Open http://{args.host}:{args.port} if the UI is already running, or use:\n"
                f"  ./run_ui.sh --port {args.port + 1}\n",
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
