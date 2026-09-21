import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

from ui import server
from utilities import benchmark_cli


def summary(run_id: str, p95: float = 1000, throughput: float = 2.0) -> dict:
    return {
        "samples": 25, "successful": 25, "failed": 0, "error_pct": 0,
        "throughput_per_s": throughput,
        "latency_ms": {"mean": p95 * .7, "p50": p95 * .6, "p95": p95, "p99": p95 * 1.2},
        "meta": {
            "run_id": run_id, "engine": "engine-a", "queries": "queries.csv",
            "query_sha256": "same-query", "test_plan": "run-once.jmx",
            "run_type": "ui_run_once", "requested_concurrency": "1",
        },
    }


class BenchmarkCliTests(unittest.TestCase):
    def setUp(self):
        self.original = (server.REPORTS, server.DB_PATH, server.DATABASE_URL,
                         server.REGISTRY_BACKEND, server.DB_READY)
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        server.REPORTS = root / "reports"
        server.REPORTS.mkdir()
        server.DB_PATH = root / "registry.db"
        server.DATABASE_URL = ""
        server.REGISTRY_BACKEND = "sqlite"
        server.DB_READY = False
        server.init_registry()

    def tearDown(self):
        (server.REPORTS, server.DB_PATH, server.DATABASE_URL,
         server.REGISTRY_BACKEND, server.DB_READY) = self.original
        self.temp.cleanup()

    def write_report(self, report_id: str, data: dict) -> None:
        path = server.REPORTS / report_id
        path.mkdir(parents=True)
        (path / "run_summary.json").write_text(json.dumps(data))

    def test_promote_list_replace_and_deactivate_share_registry(self):
        self.write_report("first", summary("run-first"))
        self.write_report("second", summary("run-second"))
        server.promote_reference("first", {"reason": "initial", "promoted_by": "qa"})
        server.promote_reference("second", {"reason": "new build", "promoted_by": "cli"})
        active = server.reference_promotions()
        history = server.reference_promotions(active_only=False)
        self.assertEqual([item["run_id"] for item in active], ["run-second"])
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["workload_signature"]["query_sha256"], "same-query")
        self.assertEqual(server.deactivate_reference("run-second"), {"run_id": "run-second", "active": False})
        self.assertEqual(server.reference_promotions(), [])

    def test_active_resolution_and_threshold_verdicts(self):
        self.write_report("baseline", summary("run-baseline", p95=1000, throughput=2))
        self.write_report("candidate", summary("run-candidate", p95=1200, throughput=1.8))
        server.promote_reference("baseline", {"reason": "validated", "promoted_by": "qa"})
        candidate = benchmark_cli.resolve_report("run-candidate")
        baseline = benchmark_cli.active_for(candidate)
        result = benchmark_cli.comparison_payload(baseline, candidate, 5, 10)
        self.assertEqual(baseline["id"], "baseline")
        self.assertEqual(result["metrics"]["p95_ms"]["verdict"], "critical")
        self.assertEqual(result["metrics"]["throughput_per_s"]["verdict"], "critical")

    def test_error_increase_from_zero_is_critical(self):
        metric = {"left": 0, "right": 1, "change_pct": None, "higher_is_better": False}
        self.assertEqual(benchmark_cli.verdict("error_pct", metric, 5, 10), "critical")

    def test_direct_report_paths_need_no_registry_baseline(self):
        baseline_path = Path(self.temp.name) / "base.json"
        candidate_path = Path(self.temp.name) / "candidate.json"
        baseline_path.write_text(json.dumps(summary("base", p95=1000)))
        candidate_path.write_text(json.dumps(summary("candidate", p95=1040)))
        args = Namespace(
            run_id=None, candidate_report=str(candidate_path), baseline=None,
            baseline_report=str(baseline_path), warning_pct=5, critical_pct=10, format="json",
        )
        baseline = {"id": str(baseline_path), "summary": json.loads(baseline_path.read_text())}
        candidate = {"id": str(candidate_path), "summary": json.loads(candidate_path.read_text())}
        result = benchmark_cli.comparison_payload(baseline, candidate, args.warning_pct, args.critical_pct)
        self.assertEqual(result["metrics"]["p95_ms"]["verdict"], "within-threshold")


if __name__ == "__main__":
    unittest.main()
