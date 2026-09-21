import csv
import json
import sqlite3
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from utilities import artifact_manifest, cleanup_reports, generator_monitor, inject_jdbc_observer


class EvidenceTests(unittest.TestCase):
    def test_manifest_hashes_final_evidence_and_excludes_receipt(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "run_summary.json").write_text(json.dumps({"meta": {"run_id": "run-1"}}))
            (root / "JmeterResultFile.csv").write_text("a,b\n1,2\n")
            (root / "s3_upload.json").write_text("{}")
            target, manifest = artifact_manifest.build(root)
            names = {item["path"] for item in manifest["artifacts"]}
            self.assertEqual(names, {"JmeterResultFile.csv", "run_summary.json"})
            self.assertEqual(json.loads(target.read_text())["run_id"], "run-1")
            self.assertEqual(json.loads((root / "run_summary.json").read_text())["artifact_integrity"]["status"], "manifested")

    def test_jdbc_observer_is_valid_and_issues_no_query(self):
        with tempfile.TemporaryDirectory() as temp:
            source, target = Path(temp) / "source.jmx", Path(temp) / "target.jmx"
            source.write_text("<jmeterTestPlan><hashTree><JDBCSampler></JDBCSampler>\n        <hashTree/></hashTree></jmeterTestPlan>")
            inject_jdbc_observer.inject(source, target)
            ET.parse(target)
            text = target.read_text()
            self.assertIn("rows_materialized", text)
            self.assertEqual(text.count("<JDBCSampler>"), 1)

    def test_generator_health_requires_sustained_saturation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            metrics, summary = root / "metrics.csv", root / "summary.json"
            with metrics.open("w", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(("timestamp", "cpu_pct", "memory_pct", "swap_used_kb", "load_1m", "network_bytes"))
                for index, cpu in enumerate((30, 95, 40, 91, 92, 93)):
                    writer.writerow((index, cpu, 50, 0, 1, index * 10))
            summary.write_text("{}")
            generator_monitor.summarize(metrics, summary)
            self.assertEqual(json.loads(summary.read_text())["generator_health"]["status"], "invalid")

    def test_cleanup_protects_baselines_recent_and_unpublished_runs(self):
        now = 2_000_000_000
        items = [
            {"path": Path("a"), "run_id": "baseline", "mtime": now - 10000000, "signature": ("a",), "s3_verified": True},
            {"path": Path("b"), "run_id": "recent", "mtime": now, "signature": ("b",), "s3_verified": True},
            {"path": Path("c"), "run_id": "unpublished", "mtime": now - 10000000, "signature": ("c",), "s3_verified": False},
        ]
        original = cleanup_reports.time.time
        cleanup_reports.time.time = lambda: now
        try:
            decisions = cleanup_reports.classify(items, {"baseline"}, 30, 0, 0, True)
        finally:
            cleanup_reports.time.time = original
        reasons = {item["run_id"]: value for item, value in decisions}
        self.assertIn("active baseline", reasons["baseline"])
        self.assertIn("within 30 days", reasons["recent"])
        self.assertIn("S3 publication not verified", reasons["unpublished"])


if __name__ == "__main__":
    unittest.main()
