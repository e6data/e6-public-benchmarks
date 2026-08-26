import json
import sqlite3
import stat
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from ui import server


class UiTests(unittest.TestCase):
    def test_system_settings_are_read_only_by_default(self):
        with mock.patch.object(server, "ALLOW_SETTINGS_WRITE", False):
            with self.assertRaisesRegex(ValueError, "writes are disabled"):
                server.update_system_settings({})

    def test_system_settings_validate_persist_and_update_runtime_defaults(self):
        original = {
            name: getattr(server, name) for name in (
                "PROMETHEUS_DEFAULT_ENABLED", "PROMETHEUS_DEFAULT_PORT",
                "PROMETHEUS_URL", "GRAFANA_URL", "SYSTEM_COPY_TO_S3",
                "SYSTEM_S3_REPORT_PATH", "SYSTEM_GENERATE_DASHBOARD",
                "REPORT_RETENTION_DAYS", "MAX_LOCAL_REPORT_GB",
            )
        }
        try:
            with tempfile.TemporaryDirectory() as temp, \
                    mock.patch.object(server, "ALLOW_SETTINGS_WRITE", True), \
                    mock.patch.object(server, "SETTINGS_PATH", Path(temp) / "settings.json"):
                values = {
                    "prometheus_enabled": True, "prometheus_port": 9123,
                    "prometheus_url": "http://prometheus:9090",
                    "grafana_url": "http://grafana:3000/d/jmeter",
                    "copy_to_s3": True, "s3_report_path": "s3://bucket/results",
                    "generate_dashboard": False, "retention_days": 45,
                    "max_local_report_gb": 250,
                }
                saved = server.update_system_settings(values)
                self.assertEqual(saved, values)
                self.assertEqual(json.loads(server.SETTINGS_PATH.read_text()), values)
                self.assertEqual(server.PROMETHEUS_DEFAULT_PORT, "9123")
                self.assertTrue(server.SYSTEM_COPY_TO_S3)
                self.assertFalse(server.SYSTEM_GENERATE_DASHBOARD)
                with self.assertRaisesRegex(ValueError, "must start with s3://"):
                    server.update_system_settings({**values, "s3_report_path": "https://bucket/results"})
        finally:
            for name, value in original.items():
                setattr(server, name, value)

    def test_create_jdbc_connection_profile_uses_runner_format_and_private_permissions(self):
        name = "ui_unit_profile"
        target = server.ROOT / "connection_properties" / f"{name}_connection.properties"
        try:
            relative = server.create_connection_profile({
                "name": name, "transport": "jdbc", "engine": "e6data",
                "connection_string": "jdbc:e6data://example:443/secure=true",
                "user": "tester", "password": "secret",
            })
            contents = target.read_text()
            self.assertEqual(relative, f"connection_properties/{target.name}")
            self.assertIn("CONNECTION_STRING=jdbc:e6data://example:443/secure=true", contents)
            self.assertIn("DRIVER_CLASS=io.e6.jdbc.driver.E6Driver", contents)
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
        finally:
            target.unlink(missing_ok=True)

    def test_databricks_profile_uses_selected_driver_without_extra_inputs(self):
        target = server.ROOT / "connection_properties" / "ui_dbr_unit_connection.properties"
        try:
            server.create_connection_profile({
                "name": "ui_dbr_unit", "transport": "jdbc", "engine": "databricks",
                "connection_string": "jdbc:databricks://example:443;HttpPath=/sql/warehouse",
                "password": "secret",
            })
            contents = target.read_text()
            self.assertIn("PASSWORD=secret", contents)
            self.assertIn("DRIVER_CLASS=com.databricks.client.jdbc.Driver", contents)
            self.assertNotIn("JDBC_CONNECTION_PROPERTIES", contents)
        finally:
            target.unlink(missing_ok=True)

    def test_snowflake_profile_uses_current_driver_class(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_root = server.ROOT
            server.ROOT = Path(tmp)
            try:
                relative = server.create_connection_profile({
                    "name": "ui_snowflake_unit", "transport": "jdbc",
                    "engine": "snowflake",
                    "connection_string": "jdbc:snowflake://account.snowflakecomputing.com/?warehouse=BENCH",
                    "user": "benchmark_user", "password": "private-token",
                })
            finally:
                server.ROOT = original_root
            contents = (Path(tmp) / relative).read_text()
            self.assertIn("DRIVER_CLASS=net.snowflake.client.api.driver.SnowflakeDriver", contents)

    def test_create_connection_profile_rejects_injection_and_overwrite(self):
        with self.assertRaisesRegex(ValueError, "invalid character"):
            server.create_connection_profile({
                "name": "ui_bad", "transport": "jdbc",
                "connection_string": "jdbc:test\nPASSWORD=changed", "driver_class": "driver",
            })
        target = server.ROOT / "connection_properties" / "ui_existing_connection.properties"
        try:
            target.write_text("sentinel=true\n")
            with self.assertRaisesRegex(ValueError, "already exists"):
                server.create_connection_profile({
                    "name": "ui_existing", "transport": "jdbc",
                    "connection_string": "jdbc:test", "driver_class": "driver",
                })
            self.assertEqual(target.read_text(), "sentinel=true\n")
        finally:
            target.unlink(missing_ok=True)

    def test_create_http_connection_profile_uses_expected_keys(self):
        target = server.ROOT / "connection_properties" / "ui_http_unit_connection.properties"
        try:
            server.create_connection_profile({
                "name": "ui_http_unit", "transport": "http", "mainhost": "example.test",
                "scheme": "https", "cluster_name": "demo", "catalog": "glue", "schema": "tpch",
            })
            contents = target.read_text()
            self.assertIn("mainhost=example.test", contents)
            self.assertIn("cluster_name=demo", contents)
            self.assertIn("SCHEMA=tpch", contents)
        finally:
            target.unlink(missing_ok=True)

    def test_local_csv_upload_is_scoped_and_does_not_overwrite(self):
        target = server.ROOT / "data_files" / "ui_upload_unit.csv"
        try:
            relative = server.save_input("query", "ui_upload_unit.csv", b"query_alias,query_string\nq1,select 1\n")
            self.assertEqual(relative, "data_files/ui_upload_unit.csv")
            with self.assertRaisesRegex(ValueError, "already exists"):
                server.save_input("query", "ui_upload_unit.csv", b"replacement")
            self.assertIn("select 1", target.read_text())
        finally:
            target.unlink(missing_ok=True)

    def test_csv_upload_rejects_traversal_and_wrong_extension(self):
        for name in ("../outside.csv", "queries.sql"):
            with self.assertRaises(ValueError):
                server.save_input("query", name, b"content")

    def test_s3_import_downloads_to_runner_input_directory(self):
        target = server.ROOT / "test_properties" / "ui_s3_unit.csv"

        def fake_run(command, **_kwargs):
            Path(command[4]).write_text("StartValue,EndValue,Duration\n1,1,1\n")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        try:
            with mock.patch.object(server.subprocess, "run", side_effect=fake_run):
                relative = server.import_s3_input("profile", "s3://example-bucket/folder/ui_s3_unit.csv")
            self.assertEqual(relative, "test_properties/ui_s3_unit.csv")
        finally:
            target.unlink(missing_ok=True)

    def test_s3_import_selects_existing_local_file(self):
        target = server.ROOT / "data_files" / "ui_s3_existing.csv"
        try:
            target.parent.mkdir(exist_ok=True)
            target.write_text("query_alias,query_string\nq1,select 1\n")
            with mock.patch.object(server.subprocess, "run") as download:
                relative = server.import_s3_input(
                    "query", "s3://example-bucket/folder/ui_s3_existing.csv"
                )
            self.assertEqual(relative, "data_files/ui_s3_existing.csv")
            download.assert_not_called()
        finally:
            target.unlink(missing_ok=True)

    def test_s3_import_retries_public_object_when_session_expired(self):
        target = server.ROOT / "test_properties" / "ui_s3_public.csv"
        calls = []

        def fake_run(command, **_kwargs):
            calls.append(command)
            if "--no-sign-request" not in command:
                return SimpleNamespace(returncode=1, stdout="", stderr="ExpiredToken")
            Path(command[4]).write_text("StartValue,EndValue,Duration\n1,1,1\n")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        try:
            with mock.patch.object(server.subprocess, "run", side_effect=fake_run):
                relative = server.import_s3_input(
                    "profile", "s3://example-bucket/folder/ui_s3_public.csv"
                )
            self.assertEqual(relative, "test_properties/ui_s3_public.csv")
            self.assertIn("--no-sign-request", calls[1])
        finally:
            target.unlink(missing_ok=True)

    def test_report_details_reuses_jmeter_statistics(self):
        with tempfile.TemporaryDirectory(dir=server.REPORTS, prefix="ui-stats-test-") as temp:
            directory = Path(temp)
            (directory / "run_summary.json").write_text("{}")
            (directory / "statistics.json").write_text(
                '{"Q1":{"transaction":"Q1","sampleCount":4,"errorCount":1,'
                '"errorPct":25.0,"meanResTime":120.5,"medianResTime":100.0,'
                '"minResTime":80.0,"maxResTime":200.0,"pct1ResTime":180.0,'
                '"pct2ResTime":190.0,"pct3ResTime":200.0,"throughput":2.5}}'
            )
            details = server.report_details(directory.name)
        self.assertEqual(details["per_query_source"], "JMeter statistics.json")
        self.assertEqual(details["per_query"][0]["pct2ResTime"], 190.0)
        self.assertEqual(details["per_query"][0]["sampleCount"], 4)

    def test_comparison_calculates_regression_direction_inputs(self):
        left = {"samples": 100, "successful": 99, "failed": 1, "throughput_per_s": 10, "error_pct": 1, "latency_ms": {"mean": 150, "p50": 100, "p95": 200, "p99": 300}, "peak_in_flight": 5, "arrival_window_s": 60, "drain_s": 2, "wall_clock_s": 62, "load_profile": {"expected": 100, "delivered_pct": 100}, "failure_messages": [{"count": 1, "message": "timeout"}], "meta": {"queries": "queries-a.csv", "test_plan": "run-once.jmx"}}
        right = {"samples": 80, "successful": 60, "failed": 20, "throughput_per_s": 12, "error_pct": 25, "latency_ms": {"mean": 140, "p50": 90, "p95": 180, "p99": 330}, "peak_in_flight": 6, "arrival_window_s": 60, "drain_s": 3, "wall_clock_s": 63, "load_profile": {"expected": 100, "delivered_pct": 80}, "meta": {"queries": "queries-b.csv", "test_plan": "run-once.jmx"}}
        result = server.comparison(left, right)
        self.assertEqual(result["metrics"]["throughput_per_s"]["change_pct"], 20)
        self.assertEqual(result["metrics"]["throughput_per_s"]["ratio"], 1.2)
        self.assertEqual(result["metrics"]["p95_ms"]["change_pct"], -10)
        self.assertEqual(result["metrics"]["accepted_load_pct"]["right"], 80)
        self.assertTrue(result["metrics"]["throughput_per_s"]["higher_is_better"])
        self.assertFalse(result["metrics"]["p95_ms"]["higher_is_better"])
        self.assertEqual(result["compatibility"][0]["severity"], "workload")
        self.assertIn("60/80", result["survivor_bias"])
        self.assertEqual(result["failure_reasons"]["left"][0]["message"], "timeout")

    def test_benchmark_status_separates_jmeter_result_from_artifact_failure(self):
        self.assertEqual(server.benchmark_status(1, {"error_pct": 0}, 5), "completed")
        self.assertEqual(server.benchmark_status(1, {"error_pct": 6}, 5), "failed")
        self.assertEqual(server.benchmark_status(1, None, 5), "failed")
        self.assertEqual(server.benchmark_status(0, {"error_pct": 100}, 5), "failed")

    def test_report_status_defaults_legacy_reports_to_zero_error_only(self):
        self.assertEqual(server.report_status({"failed": 0, "meta": {}}), "completed")
        self.assertEqual(server.report_status({"failed": 1, "meta": {}}), "failed")

    def test_report_status_reuses_persisted_cancelled_state(self):
        run = server.Run("cancelled-report", "test", {}, server.REPORTS, status="cancelled")
        with server.RUN_LOCK:
            old = server.RUNS.get(run.run_id)
            server.RUNS[run.run_id] = run
        try:
            self.assertEqual(server.report_status({"failed": 0, "meta": {"run_id": run.run_id}}), "cancelled")
        finally:
            with server.RUN_LOCK:
                if old is None:
                    server.RUNS.pop(run.run_id, None)
                else:
                    server.RUNS[run.run_id] = old

    def test_per_query_comparison_joins_labels_and_calculates_p95_ratio(self):
        left = {"per_query": [{"transaction": "Q1", "pct2ResTime": 100}, {"transaction": "Q2", "pct2ResTime": 50}]}
        right = {"per_query": [{"transaction": "Q1", "pct2ResTime": 125}, {"transaction": "Q3", "pct2ResTime": 75}]}
        with mock.patch.object(server, "report_details", side_effect=[left, right]):
            rows = server.per_query_comparison("left", "right")
        self.assertEqual([row["label"] for row in rows], ["Q1", "Q2", "Q3"])
        self.assertEqual(rows[0]["p95_ratio"], 1.25)
        self.assertIsNone(rows[1]["right"])
        self.assertIsNone(rows[2]["left"])

    def test_read_preset_parses_inline_comments_and_cluster_config(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "metadata.txt"
            path.write_text(
                'RUN_MODE="prod" # comment\n'
                "CLUSTER_CONFIG='{\n"
                '  "estimated_cores": 60, "serverless": "N"\n'
                "}'\n"
            )
            values = server.read_preset(path)
        self.assertEqual(values["RUN_MODE"], "prod")
        self.assertEqual(values["ESTIMATED_CORES"], "60")
        self.assertEqual(values["SERVERLESS"], "N")

    def test_only_ui_presets_can_be_overwritten_and_deleted(self):
        with tempfile.TemporaryDirectory() as temp, mock.patch.object(server, "ROOT", Path(temp)):
            (Path(temp) / "test_properties").mkdir()
            saved = server.create_preset("workload", {"name": "smoke", "values": {"QPS": 2}})
            self.assertEqual(saved, "test_properties/ui_smoke.properties")
            server.create_preset("workload", {"name": "ui_smoke", "values": {"QPS": 3}}, overwrite=True)
            self.assertEqual(server.read_preset(Path(temp) / saved)["QPS"], "3")
            self.assertEqual(server.delete_preset("workload", "ui_smoke"), saved)
            with self.assertRaises(ValueError):
                server.delete_preset("workload", "repository_example")

    def test_live_metrics_ignores_setup_samples(self):
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp) / "child"
            run.mkdir()
            (run / "JmeterResultFile.csv").write_text(
                "timeStamp,elapsed,label,success,allThreads\n"
                "1000,0,Setup-Loader,true,1\n"
                "1100,100,q1,true,2\n"
                "1200,300,q2,false,2\n"
            )
            metrics = server.live_metrics(Path(temp))
        self.assertEqual(metrics["samples"], 2)
        self.assertEqual(metrics["successful"], 1)
        self.assertEqual(metrics["failed"], 1)
        self.assertEqual(metrics["active"], 2)
        self.assertEqual(metrics["series"]["arrivals"], [2])
        self.assertEqual(metrics["series"]["successful"], [1])
        self.assertEqual(metrics["series"]["failed"], [1])
        self.assertEqual(metrics["series"]["in_flight"], [1])
        self.assertEqual(metrics["series"]["latency_ms"], [100])
        self.assertEqual(metrics["duration_s"], 0.4)
        self.assertEqual(metrics["arrival_rate"], 20.0)
        self.assertEqual(metrics["completion_throughput"], 5.0)
        self.assertEqual(metrics["arrival_window_s"], 0.1)
        self.assertEqual(metrics["drain_s"], 0.3)
        self.assertEqual(metrics["top_failure"]["count"], 1)

    def test_live_metrics_ignores_partially_written_row(self):
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp) / "child"
            run.mkdir()
            (run / "JmeterResultFile.csv").write_text(
                "timeStamp,elapsed,label,success,allThreads\n"
                "1000,100,q1,true,1\n"
                "1100,200,q2"
            )
            metrics = server.live_metrics(Path(temp))
        self.assertEqual(metrics["samples"], 1)

    def test_live_metrics_does_not_invent_overlap_within_a_second(self):
        report = server.ROOT / "reports" / "ui-test-live-overlap"
        result_dir = report / "20260819-000000-000000"
        result_dir.mkdir(parents=True, exist_ok=True)
        result = result_dir / "JmeterResultFile.csv"
        try:
            result.write_text(
                "timeStamp,elapsed,label,success,responseMessage,allThreads\n"
                "1000,200,Q1,true,OK,1\n"
                "1800,100,Q2,true,OK,1\n"
            )
            metrics = server.live_metrics(report)
        finally:
            result.unlink(missing_ok=True)
            result_dir.rmdir()
            report.rmdir()
        self.assertEqual(metrics["series"]["in_flight"], [1])
        self.assertEqual(metrics["successful"], 2)

    def test_path_validation_blocks_traversal(self):
        with self.assertRaises(ValueError):
            server._inside("../../etc/passwd", "connection_properties", ".properties")

    def test_path_validation_accepts_nested_benchmark_query(self):
        query = server.ROOT / "data_files" / "benchmarks" / "ui_nested_test.csv"
        try:
            query.parent.mkdir(parents=True, exist_ok=True)
            query.write_text('QUERY_ALIAS,QUERY\nTPCDS_Q01,"select 1"\n')
            self.assertEqual(
                server._inside("data_files/benchmarks/ui_nested_test.csv", "data_files", ".csv"),
                "data_files/benchmarks/ui_nested_test.csv",
            )
        finally:
            query.unlink(missing_ok=True)

    def test_build_environment_keeps_upload_disabled_and_enables_standard_dashboard(self):
        connection = server.ROOT / "connection_properties" / "ui_test.properties"
        query = server.ROOT / "data_files" / "ui_test.csv"
        try:
            connection.write_text("CONNECTION_STRING=jdbc:test\n")
            query.write_text('query_alias,query_string\nq1,"select 1"\n')
            config = {
                "plan": "jdbc_concurrency",
                "connection": "connection_properties/ui_test.properties",
                "query_file": "data_files/ui_test.csv",
            }
            with mock.patch.object(server, "SYSTEM_COPY_TO_S3", False), \
                    mock.patch.object(server, "SYSTEM_GENERATE_DASHBOARD", True), \
                    mock.patch.object(server, "PROMETHEUS_DEFAULT_ENABLED", False), \
                    mock.patch.object(server, "PROMETHEUS_DEFAULT_PORT", "9270"):
                env = server.build_environment(config, "abc")
        finally:
            connection.unlink(missing_ok=True)
            query.unlink(missing_ok=True)
        self.assertEqual(env["COPY_TO_S3"], "false")
        self.assertEqual(env["GENERATE_DASHBOARD"], "true")
        self.assertEqual(env["REPORT_PATH"], "reports/ui-abc")
        self.assertEqual(env["PROMETHEUS_ENABLED"], "false")
        self.assertEqual(env["PROMETHEUS_PORT"], "9270")

    def test_preflight_accepts_runner_query_header_variants(self):
        connection = server.ROOT / "connection_properties" / "ui_header_test.properties"
        query = server.ROOT / "data_files" / "ui_header_test.csv"
        try:
            connection.write_text("CONNECTION_STRING=jdbc:test\n")
            query.write_text('QUERY_ALIAS,QUERY\nq1,"select 1"\nq2,"select 2"\n')
            result = server.preflight({
                "plan": "jdbc_run_once",
                "connection": "connection_properties/ui_header_test.properties",
                "query_file": "data_files/ui_header_test.csv",
            })
        finally:
            connection.unlink(missing_ok=True)
            query.unlink(missing_ok=True)
        self.assertTrue(result["ok"])
        self.assertEqual(result["query_count"], 2)

    def test_preflight_rejects_blank_incomplete_and_duplicate_query_rows(self):
        connection = server.ROOT / "connection_properties" / "ui_invalid_csv_test.properties"
        query = server.ROOT / "data_files" / "ui_invalid_csv_test.csv"
        try:
            connection.write_text("CONNECTION_STRING=jdbc:test\n")
            query.write_text(
                'QUERY_ALIAS,QUERY\nq1,"select 1"\n\n'
                'q1,"select 2"\nq3,""\n'
            )
            with self.assertRaisesRegex(ValueError, "line 3 is blank.*duplicate query alias.*empty SQL"):
                server.preflight({
                    "plan": "jdbc_run_once",
                    "connection": "connection_properties/ui_invalid_csv_test.properties",
                    "query_file": "data_files/ui_invalid_csv_test.csv",
                })
        finally:
            connection.unlink(missing_ok=True)
            query.unlink(missing_ok=True)

    def test_build_environment_keeps_metadata_descriptive(self):
        connection = server.ROOT / "connection_properties" / "ui_meta_test.properties"
        query = server.ROOT / "data_files" / "ui_meta_test.csv"
        try:
            connection.write_text("CONNECTION_STRING=jdbc:test\n")
            query.write_text('query_alias,query_string\nq1,"select 1"\n')
            with mock.patch.object(server, "SYSTEM_COPY_TO_S3", False):
                env = server.build_environment({
                    "plan": "jdbc_concurrency", "engine": "e6data",
                    "connection": "connection_properties/ui_meta_test.properties",
                    "query_file": "data_files/ui_meta_test.csv",
                    "metadata": {"CLUSTER_SIZE": "S-2x2", "ESTIMATED_CORES": "60", "COMMENTS": "comparison"},
                }, "meta")
        finally:
            connection.unlink(missing_ok=True)
            query.unlink(missing_ok=True)
        self.assertEqual(env["CLUSTER_SIZE"], "S-2x2")
        self.assertEqual(env["ESTIMATED_CORES"], "60")
        self.assertEqual(env["COPY_TO_S3"], "false")

    def test_sequential_runs_execute_in_order(self):
        calls = []

        def fake_prepare(config, label):
            run = server.Run(config["id"], label, config, server.REPORTS / f"ui-{config['id']}")
            return run, {"id": config["id"]}

        def fake_execute(run, _env):
            calls.append(run.run_id)

        with mock.patch.object(server, "prepare_run", side_effect=fake_prepare), mock.patch.object(server, "_execute", side_effect=fake_execute):
            server.start_runs([{"id": "first"}, {"id": "second"}], sequential=True)
            deadline = time.time() + 1
            while len(calls) < 2 and time.time() < deadline:
                time.sleep(0.01)
        self.assertEqual(calls, ["first", "second"])

    def test_compact_summary_bounds_only_api_series(self):
        original = {
            "samples": 1000, "arrivals_per_s": [1] * 1000,
            "in_flight_per_s": list(range(1000)),
            "load_profile": {"expected": 1000, "expected_per_s": [1] * 1000},
        }
        compact = server.compact_summary(original, points=100)
        self.assertEqual(len(compact["arrivals_per_s"]), 100)
        self.assertEqual(sum(compact["arrivals_per_s"]), 1000)
        self.assertEqual(compact["chart_bucket_s"], 10)
        self.assertNotIn("expected_per_s", compact["load_profile"])
        self.assertEqual(len(original["arrivals_per_s"]), 1000)

    def test_registry_restores_running_record_as_interrupted(self):
        old_path, old_ready, old_runs = server.DB_PATH, server.DB_READY, dict(server.RUNS)
        try:
            with tempfile.TemporaryDirectory() as temp:
                server.DB_PATH = Path(temp) / "registry.db"
                server.DB_READY = False
                server.RUNS.clear()
                server.init_registry()
                run = server.Run("persisted", "test", {}, Path(temp) / "reports", status="running")
                server.persist_run(run)
                run.status = "completed"
                server.persist_run(run)
                with sqlite3.connect(server.DB_PATH) as db:
                    count, payload = db.execute(
                        "SELECT COUNT(*), payload FROM runs WHERE run_id=?", (run.run_id,)
                    ).fetchone()
                self.assertEqual(count, 1)
                self.assertEqual(json.loads(payload)["status"], "completed")
                server.RUNS.clear()
                server.restore_runs()
                self.assertEqual(server.RUNS["persisted"].status, "completed")
        finally:
            server.DB_PATH, server.DB_READY = old_path, old_ready
            server.RUNS.clear()
            server.RUNS.update(old_runs)

    def test_run_once_always_disables_recycling(self):
        connection = server.ROOT / "connection_properties" / "ui_test.properties"
        query = server.ROOT / "data_files" / "ui_test.csv"
        try:
            connection.write_text("CONNECTION_STRING=jdbc:test\n")
            query.write_text('query_alias,query_string\nq1,"select 1"\n')
            env = server.build_environment({
                "plan": "jdbc_run_once", "connection": "connection_properties/ui_test.properties",
                "query_file": "data_files/ui_test.csv", "RECYCLE_ON_EOF": True,
            }, "once")
        finally:
            connection.unlink(missing_ok=True)
            query.unlink(missing_ok=True)
        self.assertEqual(env["RECYCLE_ON_EOF"], "false")

    def test_every_ui_plan_builds_a_runner_environment(self):
        jdbc = server.ROOT / "connection_properties" / "ui_test_jdbc.properties"
        http = server.ROOT / "connection_properties" / "ui_test_http.properties"
        query = server.ROOT / "data_files" / "ui_test.csv"
        arrivals = server.ROOT / "test_properties" / "ui_test_arrivals.csv"
        concurrency = server.ROOT / "test_properties" / "ui_test_concurrency.csv"
        try:
            jdbc.write_text("CONNECTION_STRING=jdbc:test\n")
            http.write_text("mainhost=localhost\n")
            query.write_text('query_alias,query_string\nq1,"select 1"\n')
            arrivals.write_text("StartValue,EndValue,Duration\n1,1,1\n")
            concurrency.write_text("Threads,StartTime,StartupTime,HoldTime,ShutdownTime\n1,0,0,1,0\n")
            for plan, (_, expected_path, transport) in server.PLANS.items():
                profile = "test_properties/ui_test_concurrency.csv" if plan == "jdbc_variable_concurrency" else "test_properties/ui_test_arrivals.csv"
                env = server.build_environment({
                    "plan": plan,
                    "connection": f"connection_properties/ui_test_{transport}.properties",
                    "query_file": "data_files/ui_test.csv",
                    "load_profile": profile,
                }, plan)
                self.assertEqual(env["TEST_PLAN"], expected_path)
        finally:
            for path in (jdbc, http, query, arrivals, concurrency):
                path.unlink(missing_ok=True)

    def test_workload_preview_uses_shared_arrival_profile_model(self):
        profile = server.ROOT / "test_properties" / "ui_preview_arrivals.csv"
        try:
            profile.write_text("StartValue,EndValue,Duration\n1,3,3\n3,3,2\n")
            preview = server.workload_preview({
                "plan": "jdbc_arrivals",
                "load_profile": "test_properties/ui_preview_arrivals.csv",
            })
        finally:
            profile.unlink(missing_ok=True)
        self.assertEqual(preview["pattern"], "Variable arrival rate")
        self.assertEqual(preview["kind"], "arrivals")
        self.assertEqual(preview["values"], [1.0, 2.0, 3.0, 3.0, 3.0])
        self.assertEqual(preview["duration_s"], 5)
        self.assertEqual(preview["expected_total"], 12)

    def test_workload_preview_uses_shared_concurrency_profile_model(self):
        profile = server.ROOT / "test_properties" / "ui_preview_concurrency.csv"
        try:
            profile.write_text("Threads,StartTime,StartupTime,HoldTime,ShutdownTime\n4,0,2,2,2\n")
            preview = server.workload_preview({
                "plan": "jdbc_variable_concurrency",
                "load_profile": "test_properties/ui_preview_concurrency.csv",
            })
        finally:
            profile.unlink(missing_ok=True)
        self.assertEqual(preview["pattern"], "Variable concurrency")
        self.assertEqual(preview["kind"], "concurrency")
        self.assertEqual(preview["peak"], 4)
        self.assertEqual(preview["duration_s"], 6)

    def test_qpm_preview_converts_minutes_to_per_second_rate(self):
        preview = server.workload_preview({
            "plan": "jdbc_qpm", "QPM": 120, "RAMP_UP_TIME": 0, "HOLD_PERIOD": 2,
        })
        self.assertEqual(preview["unit"], "queries/sec")
        self.assertEqual(preview["duration_s"], 120)
        self.assertEqual(preview["peak"], 2)
        self.assertEqual(preview["expected_total"], 242)

    def test_run_once_preview_reports_query_file_total(self):
        preview = server.workload_preview({
            "plan": "jdbc_run_once", "query_file": "data_files/simple_queries.csv",
            "CONCURRENT_QUERY_COUNT": 2, "RAMP_UP_TIME": 1,
            "RAMP_UP_STEPS": 1, "HOLD_PERIOD": 1,
        })
        self.assertEqual(preview["expected_total"], 2)

    def test_qps_preview_matches_arrivals_thread_group_step_ramp(self):
        preview = server.workload_preview({
            "plan": "jdbc_qps", "QPS": 4, "RAMP_UP_TIME": 4,
            "RAMP_UP_STEPS": 2, "HOLD_PERIOD": 2,
        })
        self.assertEqual(preview["pattern"], "Constant QPS")
        self.assertEqual(preview["values"], [2.0, 2.0, 4.0, 4.0, 4.0, 4.0, 4.0])
        self.assertEqual(preview["duration_s"], 6)
        self.assertEqual(preview["expected_total"], 24)

    def test_workload_preview_pattern_matches_selected_plan(self):
        base = {
            "query_file": "data_files/simple_queries.csv", "CONCURRENT_QUERY_COUNT": 2,
            "QPS": 2, "QPM": 60, "RAMP_UP_TIME": 1, "RAMP_UP_STEPS": 1,
            "HOLD_PERIOD": 1,
        }
        expected = {
            "jdbc_run_once": "Run once", "jdbc_concurrency": "Fixed concurrency",
            "jdbc_qps": "Constant QPS", "jdbc_qpm": "Constant QPM",
        }
        for plan, label in expected.items():
            with self.subTest(plan=plan):
                self.assertEqual(server.workload_preview({**base, "plan": plan})["pattern"], label)


if __name__ == "__main__":
    unittest.main()
