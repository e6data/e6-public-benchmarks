#!/usr/bin/env python3
"""Local-only UI/API adapter over the existing run_test.sh contract.

The CLI runner remains the source of truth. This module only validates a small
allowlist of inputs, starts that runner as an isolated process, and reads the
same CSV/JSON artifacts that CLI users already receive.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
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
from urllib.parse import parse_qs, urlparse


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
        "GENERATE_DASHBOARD": "false",
        "RANDOM_ORDER": "true" if config.get("RANDOM_ORDER") is True else "false",
        "RECYCLE_ON_EOF": "true" if config.get("RECYCLE_ON_EOF", True) is True else "false",
    })
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
        return {"samples": 0, "successful": 0, "failed": 0, "throughput": 0, "p50": None, "p95": None, "active": 0}
    rows: list[dict[str, str]] = []
    try:
        with files[-1].open(newline="", errors="replace") as handle:
            rows = [row for row in csv.DictReader(handle) if not row.get("label", "").startswith(("Setup-", "Control-"))]
    except (OSError, csv.Error):
        pass
    if not rows:
        return {"samples": 0, "successful": 0, "failed": 0, "throughput": 0, "p50": None, "p95": None, "active": 0}
    elapsed = sorted(int(row.get("elapsed") or 0) for row in rows if row.get("success", "").lower() == "true")
    started = [int(row["timeStamp"]) for row in rows]
    window = max(1, (max(started) - min(started)) / 1000)
    percentile = lambda pct: elapsed[min(len(elapsed) - 1, max(0, (len(elapsed) * pct + 99) // 100 - 1))] if elapsed else None
    return {
        "samples": len(rows), "successful": len(elapsed), "failed": len(rows) - len(elapsed),
        "throughput": round(len(rows) / window, 2), "p50": percentile(50), "p95": percentile(95),
        "active": max((int(row.get("allThreads") or 0) for row in rows), default=0),
    }


def find_summary(report_root: Path) -> dict[str, Any] | None:
    summaries = sorted(report_root.glob("*/run_summary.json"), key=lambda p: p.stat().st_mtime)
    if not summaries:
        return None
    try:
        return json.loads(summaries[-1].read_text())
    except (OSError, json.JSONDecodeError):
        return None


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
        summary = find_summary(self.report_root)
        return {
            "id": self.run_id, "label": self.label, "status": self.status,
            "started_at": self.started_at, "finished_at": self.finished_at,
            "return_code": self.return_code, "config": self.config,
            "metrics": live_metrics(self.report_root), "summary": summary,
            "logs": list(self.logs), "report_path": str(self.report_root.relative_to(ROOT)),
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


def start_run(config: dict[str, Any], label: str = "Benchmark") -> Run:
    run_id = uuid.uuid4().hex[:10]
    env = build_environment(config, run_id)
    run = Run(run_id, label[:80], config, REPORTS / f"ui-{run_id}")
    with RUN_LOCK:
        RUNS[run_id] = run
    threading.Thread(target=_execute, args=(run, env), daemon=True).start()
    return run


def completed_reports() -> list[dict[str, Any]]:
    found = []
    for path in REPORTS.glob("**/run_summary.json"):
        try:
            summary = json.loads(path.read_text())
            found.append({"id": str(path.parent.relative_to(REPORTS)), "mtime": path.stat().st_mtime, "summary": summary})
        except (OSError, json.JSONDecodeError):
            continue
    return sorted(found, key=lambda item: item["mtime"], reverse=True)[:200]


def report_by_id(report_id: str) -> dict[str, Any]:
    path = (REPORTS / report_id / "run_summary.json").resolve()
    if REPORTS.resolve() not in path.parents or not path.is_file():
        raise ValueError("Unknown report")
    return json.loads(path.read_text())


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
    return {"left": left, "right": right, "metrics": delta}


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

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/config":
                connections = sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "connection_properties").glob("*.properties"))
                queries = sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "data_files").glob("*.csv"))
                profiles = sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "test_properties").glob("*.csv"))
                self._json({"plans": [{"id": k, "label": v[0], "transport": v[2]} for k, v in PLANS.items()], "connections": connections, "queries": queries, "profiles": profiles})
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
            else:
                super().do_GET()
        except (ValueError, json.JSONDecodeError) as exc:
            self._json({"error": str(exc)}, 400)

    def do_POST(self) -> None:
        try:
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
                runs = [start_run(item, str(item.get("label") or f"Engine {i + 1}")) for i, item in enumerate(configs)]
                self._json({"runs": [run.public() for run in runs]}, HTTPStatus.ACCEPTED)
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
    server = ThreadingHTTPServer((args.host, args.port), Handler)
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
