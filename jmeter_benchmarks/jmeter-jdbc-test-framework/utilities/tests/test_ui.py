import tempfile
import unittest
from pathlib import Path

from ui import server


class UiTests(unittest.TestCase):
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

    def test_path_validation_blocks_traversal(self):
        with self.assertRaises(ValueError):
            server._inside("../../etc/passwd", "connection_properties", ".properties")

    def test_build_environment_does_not_enable_upload_or_dashboard(self):
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
        self.assertEqual(env["GENERATE_DASHBOARD"], "false")
        self.assertEqual(env["REPORT_PATH"], "reports/ui-abc")


if __name__ == "__main__":
    unittest.main()
