import csv
import os
import sys
import tempfile
import unittest
from pathlib import Path


UTILITIES = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(UTILITIES))

import capture_run_report
import load_profile
import query_file_info


class LoadProfileParsingTests(unittest.TestCase):
    def write(self, text):
        handle = tempfile.NamedTemporaryFile("w", delete=False, newline="")
        self.addCleanup(lambda: os.path.exists(handle.name) and os.unlink(handle.name))
        handle.write(text)
        handle.close()
        return handle.name

    def test_arrivals_profile(self):
        path = self.write("StartValue,EndValue,Duration\n1,3,3\n")
        kind, rows = load_profile.read_profile(path)
        self.assertEqual(kind, "arrivals")
        self.assertEqual(rows, [(1, 3, 3)])
        self.assertEqual(load_profile.expected_arrivals_per_second(rows), [1, 2, 3])

    def test_concurrency_profile(self):
        path = self.write(
            "Threads,StartTime,StartupTime,HoldTime,ShutdownTime\n4,0,0,2,0\n"
        )
        kind, rows = load_profile.read_profile(path)
        self.assertEqual(kind, "concurrency")
        self.assertEqual(load_profile.expected_concurrency_per_second(rows), [4.0, 4.0, 0.0])

    def test_rejects_extra_columns(self):
        path = self.write("StartValue,EndValue,Duration\n1,2,3,4\n")
        with self.assertRaisesRegex(ValueError, "exactly 3 columns"):
            load_profile.read_profile(path)

    def test_rejects_invalid_values(self):
        path = self.write("Threads,StartTime,StartupTime,HoldTime,ShutdownTime\n0,0,0,2,0\n")
        with self.assertRaisesRegex(ValueError, "Threads must be > 0"):
            load_profile.read_profile(path)

    def test_query_file_info_excludes_recognized_header(self):
        path = self.write('Query_Alias,Query\nq1,"select 1"\nq2,"select 2"\n')
        info = query_file_info.inspect(path)
        self.assertEqual(info["rows"], 2)
        self.assertTrue(info["header"])
        self.assertEqual(len(info["sha256"]), 64)

    def test_query_file_info_keeps_headerless_first_query(self):
        path = self.write('q1,"select 1"\nq2,"select 2"\n')
        info = query_file_info.inspect(path)
        self.assertEqual(info["rows"], 2)
        self.assertFalse(info["header"])


class ReportMetricTests(unittest.TestCase):
    @staticmethod
    def row(start, elapsed, success="true"):
        return {
            "timeStamp": str(start),
            "elapsed": str(elapsed),
            "success": success,
            "responseMessage": "OK" if success == "true" else "failed",
        }

    def test_subsecond_queries_contribute_to_peak_inflight(self):
        rows = [self.row(1000, 200), self.row(1050, 200)]
        report = capture_run_report.analyse(rows)
        self.assertEqual(report["peak_in_flight"], 2)

    def test_boundary_completion_does_not_overlap_next_start(self):
        rows = [self.row(1000, 1000), self.row(2000, 100)]
        report = capture_run_report.analyse(rows)
        self.assertEqual(report["peak_in_flight"], 1)

    def test_error_metrics(self):
        rows = [self.row(1000, 100), self.row(1100, 100, "false")]
        report = capture_run_report.analyse(rows)
        self.assertEqual(report["failed"], 1)
        self.assertEqual(report["error_pct"], 50.0)

    def test_failure_breakdown_classifies_every_failed_sample(self):
        rows = [
            self.row(1000, 100), self.row(1100, 100, "false"),
            self.row(1200, 100, "false"), self.row(1300, 100, "false"),
        ]
        rows[1]["responseMessage"] = "Query cancelled: kill"
        rows[2]["responseMessage"] = "SocketTimeoutException: timed out"
        rows[3]["responseMessage"] = "SQL syntax error"
        report = capture_run_report.analyse(rows)
        self.assertEqual(report["failure_breakdown"], {
            "cancelled": 1, "timed_out": 1, "other": 1,
        })

    def test_completion_rate_reports_active_one_second_buckets(self):
        rows = [self.row(1000, 100), self.row(1100, 200), self.row(2200, 100)]
        report = capture_run_report.analyse(rows)
        self.assertEqual(report["completion_rate_per_s"]["min_active"], 1)
        self.assertEqual(report["completion_rate_per_s"]["mean_active"], 1.5)
        self.assertEqual(report["completion_rate_per_s"]["max"], 2)

    def test_control_sampler_can_be_excluded_from_query_metrics(self):
        rows = [self.row(1000, 0), self.row(1000, 250)]
        rows[0]["label"] = "Setup-Query-Loader-Trigger"
        rows[1]["label"] = "Q1"
        query_rows = [row for row in rows
                      if row.get("label") not in capture_run_report.CONTROL_SAMPLE_LABELS]
        report = capture_run_report.analyse(query_rows)
        self.assertEqual(report["samples"], 1)
        self.assertEqual(report["latency_ms"]["min"], 250)


if __name__ == "__main__":
    unittest.main()
