#!/usr/bin/env python3
"""Execute an engine-specific Performance Suite through run_test.sh."""

from __future__ import annotations

import argparse, csv, json, os, re, shutil, signal, socket, subprocess, sys, time, uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAN_DEFAULTS = {
    "jdbc_sequential": ("Test-Plans/Test-Plan-Run-Once-static-concurrency.jmx", "test_properties/run_once.properties"),
    "jdbc_run_once": ("Test-Plans/Test-Plan-Run-Once-static-concurrency.jmx", "test_properties/run_once.properties"),
    "jdbc_concurrency": ("Test-Plans/Test-Plan-Maintain-static-concurrency.jmx", "test_properties/fixed_concurrency.properties"),
    "jdbc_qps": ("Test-Plans/Test-Plan-Constant-QPS-On-Arrivals-JSR-Optimized.jmx", "test_properties/constant_qps.properties"),
    "jdbc_qpm": ("Test-Plans/Test-Plan-Constant-QPM-On-Arrivals.jmx", "test_properties/constant_qpm.properties"),
    "jdbc_arrivals": ("Test-Plans/Test-Plan-Fire-QPS-with-load-profile.jmx", "test_properties/variable_arrivals.properties"),
    "jdbc_variable_concurrency": ("Test-Plans/Test-Plan-Maintain-variable-concurrency-with-load-profile.jmx", "test_properties/variable_concurrency.properties"),
    "http_run_once": ("Test-Plans/Test-Plan-Run-Once-http-endpoint.jmx", "test_properties/run_once.properties"),
    "http_concurrency": ("Test-Plans/Test-Plan-Maintain-static-concurrency-http-endpoint.jmx", "test_properties/fixed_concurrency.properties"),
    "http_arrivals": ("Test-Plans/Test-Plan-Fire-QPS-with-load-profile-http-endpoint_v2.jmx", "test_properties/variable_arrivals.properties"),
}
DRIVER_ENGINES = {"io.e6.jdbc.driver.E6Driver": "e6data", "com.databricks.client.jdbc.Driver": "databricks", "net.snowflake.client.api.driver.SnowflakeDriver": "snowflake", "io.trino.jdbc.TrinoDriver": "trino"}
SETTING_DEFAULTS = {"CONCURRENT_QUERY_COUNT": 1, "QPS": 1, "QPM": 60, "HOLD_PERIOD": 300, "RAMP_UP_TIME": 0, "RAMP_UP_STEPS": 1, "MAX_CONCURRANCY": 900, "QUERY_TIMEOUT": 300, "LIMIT_RESULTSET": 1000, "MAX_ERROR_PCT": 5}
BOOL_SETTINGS = {"RECYCLE_ON_EOF", "RANDOM_ORDER", "GENERATE_DASHBOARD", "PROMETHEUS_ENABLED"}
METADATA_KEYS = {
    "CLUSTER_SIZE", "ESTIMATED_CORES", "MEMORY_GB", "EXECUTORS",
    "CORES_PER_EXECUTOR", "INSTANCE_TYPE", "SERVERLESS", "ENGINE_BUILD",
    "BENCHMARK_TYPE", "DATA_SIZE", "DATA_TYPE", "RUN_MODE", "RUN_SCOPE",
    "RUN_PURPOSE", "RUN_VALIDITY", "CUSTOMER", "CONFIG", "TAGS", "COMMENTS",
}
PROFILE_PLANS = {"jdbc_arrivals", "jdbc_variable_concurrency", "http_arrivals"}
ACTIVE: subprocess.Popen[str] | None = None

def stop(_signum=None, _frame=None):
    if ACTIVE and ACTIVE.poll() is None:
        try: os.killpg(ACTIVE.pid, signal.SIGTERM)
        except ProcessLookupError: pass
        ACTIVE.wait()
    raise SystemExit(130)

def properties(path: Path) -> dict[str, str]:
    values = {}
    for raw in path.read_text(errors="replace").splitlines():
        if "=" in raw and not raw.lstrip().startswith("#"):
            key, value = raw.split("=", 1); values[key.strip()] = value.strip()
    return values

def inside(value: str, directory: str, suffix: str, manifest_root: Path | None = None) -> Path:
    candidate = Path(value)
    if not candidate.is_absolute():
        root_candidate, local_candidate = (ROOT / candidate).resolve(), ((manifest_root or ROOT) / candidate).resolve()
        candidate = root_candidate if root_candidate.is_file() else local_candidate
    candidate, allowed = candidate.resolve(), (ROOT / directory).resolve()
    try:
        candidate.relative_to(allowed)
        within_allowed_directory = True
    except ValueError:
        within_allowed_directory = False
    if not candidate.is_file() or candidate.suffix.lower() != suffix or not within_allowed_directory:
        raise ValueError(f"Invalid {directory} file: {value}")
    return candidate

def legacy_workload(item: dict, manifest_root: Path) -> dict:
    schemas = item.get("schemas") or []; plain = schemas == ["tpcds_1000_delta"]
    query = item.get("queries") if plain else item.get("queries_fqn", item.get("queries"))
    warmup = item.get("warmup") if plain else item.get("warmup_fqn", item.get("warmup", "")); base = manifest_root / str(item.get("id", ""))
    return {**item, "plan": "jdbc_sequential", "query_file": str(base / str(query or "")), "warmup_query_file": str(base / str(warmup or "")) if warmup else "", "settings": {"CONCURRENT_QUERY_COUNT": 1, "RAMP_UP_TIME": 0, "RECYCLE_ON_EOF": False}}

def normalized_workloads(manifest: dict, manifest_root: Path) -> list[dict]:
    if int(manifest.get("schema_version", 1)) >= 3:
        result = []
        for index, snapshot in enumerate(manifest.get("benchmarks") or [], 1):
            run = dict(snapshot.get("run") or {})
            run.update({
                "id": str(snapshot.get("name") or run.get("label") or f"benchmark-{index}"),
                "settings": {key: run[key] for key in (*SETTING_DEFAULTS, *BOOL_SETTINGS) if key in run},
                "warmup_query_file": run.get("WARMUP_QUERY_FILE", "") if run.get("WARMUP_ENABLED") else "",
                "warmup_iterations": run.get("WARMUP_ITERATIONS", 1),
                "measured_iterations": run.get("MEASURED_ITERATIONS", 1),
                "metadata": run.get("metadata") if isinstance(run.get("metadata"), dict) else {},
            })
            result.append(run)
        if not result: raise ValueError("Suite manifest must contain a non-empty benchmarks array")
        return result
    result = []
    for index, raw in enumerate(manifest.get("workloads") or [], 1):
        item = dict(raw)
        if not item.get("query_file"): item = legacy_workload(item, manifest_root)
        item.setdefault("id", f"workload-{index}"); item.setdefault("plan", "jdbc_sequential")
        item.setdefault("measured_iterations", 1); item.setdefault("warmup_iterations", 1); item.setdefault("settings", {})
        result.append(item)
    if not result: raise ValueError("Suite manifest must contain a non-empty workloads array")
    return result

def validate_csv(path: Path) -> int:
    result = subprocess.run([sys.executable, str(ROOT / "utilities/query_file_info.py"), str(path), "--validate"], check=False)
    if result.returncode: raise ValueError(f"Invalid query CSV: {path}")
    with path.open(newline="", encoding="utf-8-sig") as handle: return sum(1 for _ in csv.reader(handle)) - 1

def connection_engine(path: Path) -> str:
    return DRIVER_ENGINES.get(properties(path).get("DRIVER_CLASS", ""), "")

def network_preflight(path: Path) -> None:
    values = properties(path); host = values.get("HOSTNAME", "")
    if not host:
        match = re.search(r"jdbc:[^:]+://([^:/;]+)", values.get("CONNECTION_STRING", "")); host = match.group(1) if match else ""
    if not host: raise ValueError("Unable to determine JDBC hostname from connection profile")
    socket.getaddrinfo(host, None); print(f"Network preflight: resolved {host}")

def run(args: argparse.Namespace) -> int:
    global ACTIVE
    manifest_path = Path(args.manifest).resolve()
    override_connection = Path(args.connection).resolve() if args.connection else None
    if not manifest_path.is_file() or (override_connection and not override_connection.is_file()): raise ValueError("Suite manifest or connection profile not found")
    manifest = json.loads(manifest_path.read_text()); workloads = normalized_workloads(manifest, manifest_path.parent)
    if int(manifest.get("schema_version", 1)) < 3 and not override_connection:
        raise ValueError("Schema-v1/v2 suites require a connection profile argument")
    checked_connections: set[Path] = set()
    suite_id = os.environ.get("SUITE_RUN_ID") or f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{uuid.uuid4().hex[:6]}"
    report_root = Path(os.environ.get("SUITE_REPORT_PATH", f"reports/suite-{suite_id}")); report_root = report_root if report_root.is_absolute() else ROOT / report_root
    report_root.mkdir(parents=True, exist_ok=True); shutil.copy2(manifest_path, report_root / "suite_manifest.json")
    failures = completed = 0; metadata = manifest.get("metadata") if isinstance(manifest.get("metadata"), dict) else {}
    with (report_root / "suite_summary.tsv").open("w", newline="") as summary:
        writer = csv.writer(summary, delimiter="\t"); writer.writerow(["sequence", "workload", "status", "plan", "queries", "warmup", "iterations", "report"])
        for sequence, item in enumerate(workloads, 1):
            workload_id, plan = str(item["id"]), str(item["plan"])
            if plan not in PLAN_DEFAULTS: raise ValueError(f"{workload_id}: unknown plan {plan}")
            connection_value = str(item.get("connection") or "")
            connection = override_connection or inside(connection_value, "connection_properties", ".properties", manifest_path.parent)
            required_engine = str(item.get("engine") or manifest.get("engine") or "").lower()
            actual_engine = connection_engine(connection)
            if required_engine and actual_engine and required_engine != actual_engine:
                raise ValueError(f"{workload_id}: benchmark requires {required_engine}; profile is {actual_engine}")
            if not args.dry_run and connection not in checked_connections:
                network_preflight(connection); checked_connections.add(connection)
            query = inside(str(item.get("query_file", "")), "data_files", ".csv", manifest_path.parent)
            warmup_value = str(item.get("warmup_query_file") or ""); warmup = inside(warmup_value, "data_files", ".csv", manifest_path.parent) if warmup_value else None
            profile_value = str(item.get("load_profile") or ""); load_profile = inside(profile_value, "test_properties", ".csv", manifest_path.parent) if profile_value else None
            if plan in PROFILE_PLANS and not load_profile:
                raise ValueError(f"{workload_id}: plan {plan} requires load_profile")
            props = inside(str(item.get("test_properties_file") or PLAN_DEFAULTS[plan][1]), "test_properties", ".properties")
            rows = validate_csv(query); validate_csv(warmup) if warmup else None; report = report_root / f"{sequence:02d}-{workload_id}"
            print(f"\nPerformance Suite {sequence}/{len(workloads)}: {workload_id}\n  Plan:       {plan}\n  Queries:    {query} ({rows} rows)\n  Warm-up:    {warmup or 'none'}")
            if args.dry_run:
                writer.writerow([sequence, workload_id, "dry-run", plan, query, warmup or "", item["measured_iterations"], report]); completed += 1; continue
            raw_settings = item.get("settings") if isinstance(item.get("settings"), dict) else {}
            allowed_settings = {key: value for key, value in raw_settings.items() if key in SETTING_DEFAULTS or key in BOOL_SETTINGS}
            settings = {**SETTING_DEFAULTS, **allowed_settings}; env = os.environ.copy()
            env.update({"CONNECTION_FILE": str(connection), "TEST_PLAN": PLAN_DEFAULTS[plan][0], "TEST_PROPERTIES_FILE": str(props), "QUERY_FILE": str(query), "WARMUP_ENABLED": "true" if warmup else "false", "WARMUP_QUERY_FILE": str(warmup or ""), "WARMUP_ITERATIONS": str(item.get("warmup_iterations", 1)), "MEASURED_ITERATIONS": str(item.get("measured_iterations", 1)), "LOAD_PROFILE": str(load_profile or ""), "REPORT_PATH": str(report), "RUN_TYPE": f"suite_{plan}", "SUITE_ID": suite_id, "SUITE_RUN_ID": suite_id, "SUITE_SEQUENCE": str(sequence), "SUITE_WORKLOAD": workload_id, "SUITE_NAME": str(manifest.get("name") or manifest.get("catalog_id") or manifest_path.stem), "SUITE_COMPARISON_KEY": str(manifest.get("comparison_key") or "")})
            for key, value in settings.items(): env[key] = ("true" if value else "false") if key in BOOL_SETTINGS and isinstance(value, bool) else str(value)
            item_metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else metadata
            for key, value in item_metadata.items():
                if key in METADATA_KEYS and value not in {None, ""}: env[key] = str(value)
            ACTIVE = subprocess.Popen([str(ROOT / "run_test.sh")], cwd=ROOT, env=env, start_new_session=True, text=True); rc = ACTIVE.wait(); ACTIVE = None
            status = "completed" if rc == 0 else "failed"; writer.writerow([sequence, workload_id, status, plan, query, warmup or "", item["measured_iterations"], report]); summary.flush()
            completed += status == "completed"; failures += status == "failed"
            if rc and not args.continue_on_failure: break
    print(f"\nSuite reports: {report_root}\nCompleted workloads: {completed}\nFailed workloads: {failures}"); return 1 if failures else 0

def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("manifest"); parser.add_argument("connection", nargs="?"); parser.add_argument("--dry-run", action="store_true"); parser.add_argument("--continue-on-failure", action="store_true")
    try: return run(parser.parse_args())
    except (OSError, ValueError, json.JSONDecodeError) as exc: print(f"Suite error: {exc}", file=sys.stderr); return 1

if __name__ == "__main__":
    signal.signal(signal.SIGINT, stop); signal.signal(signal.SIGTERM, stop); raise SystemExit(main())
