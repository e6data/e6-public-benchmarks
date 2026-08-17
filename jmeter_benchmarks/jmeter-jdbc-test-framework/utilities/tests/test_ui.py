import stat
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from ui import server


class UiTests(unittest.TestCase):
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
        left = {"throughput_per_s": 10, "error_pct": 1, "latency_ms": {"p50": 100, "p95": 200, "p99": 300}, "peak_in_flight": 5, "drain_s": 2}
        right = {"throughput_per_s": 12, "error_pct": 2, "latency_ms": {"p50": 90, "p95": 180, "p99": 330}, "peak_in_flight": 6, "drain_s": 3}
        result = server.comparison(left, right)
        self.assertEqual(result["metrics"]["throughput_per_s"]["change_pct"], 20)
        self.assertEqual(result["metrics"]["p95_ms"]["change_pct"], -10)
        self.assertTrue(result["metrics"]["throughput_per_s"]["higher_is_better"])
        self.assertFalse(result["metrics"]["p95_ms"]["higher_is_better"])

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
        self.assertEqual(metrics["series"]["in_flight"], [2])
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
        self.assertEqual(metrics["successful"], 1)

    def test_path_validation_blocks_traversal(self):
        with self.assertRaises(ValueError):
            server._inside("../../etc/passwd", "connection_properties", ".properties")

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
            env = server.build_environment(config, "abc")
        finally:
            connection.unlink(missing_ok=True)
            query.unlink(missing_ok=True)
        self.assertEqual(env["COPY_TO_S3"], "false")
        self.assertEqual(env["GENERATE_DASHBOARD"], "true")
        self.assertEqual(env["REPORT_PATH"], "reports/ui-abc")

    def test_build_environment_keeps_metadata_descriptive(self):
        connection = server.ROOT / "connection_properties" / "ui_meta_test.properties"
        query = server.ROOT / "data_files" / "ui_meta_test.csv"
        try:
            connection.write_text("CONNECTION_STRING=jdbc:test\n")
            query.write_text('query_alias,query_string\nq1,"select 1"\n')
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


if __name__ == "__main__":
    unittest.main()
