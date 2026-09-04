import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from utilities import get_e6_query_history as query_history


class E6QueryHistoryTests(unittest.TestCase):
    def test_jmeter_window_uses_sample_start_and_end_with_padding(self):
        with tempfile.TemporaryDirectory() as temp:
            result = Path(temp) / "results.csv"
            result.write_text(
                "timeStamp,elapsed,label\n"
                "10000,250,q1\n"
                "12000,1500,q2\n",
                encoding="utf-8",
            )
            self.assertEqual(query_history.jmeter_window(result, 2), (8000, 15500))

    def test_capture_writes_export_and_secret_free_status(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = root / "results.csv"
            output = root / "history.csv"
            status = root / "capture.json"
            result.write_text("timeStamp,elapsed,label\n10000,250,q1\n", encoding="utf-8")

            def fake_export(_base, _token, _start, _end, _cluster, _email, target, _timeout):
                target.write_text("query_id,status\nq-1,FINISHED\n", encoding="utf-8")
                return 1, ["query_id", "status"]

            argv = [
                "get_e6_query_history.py", "--base-url", "https://workspace.example",
                "--jmeter-results", str(result), "--output", str(output),
                "--status-output", str(status), "--client-id", "sensitive-id",
                "--client-secret", "sensitive-secret",
            ]
            with mock.patch("sys.argv", argv), \
                    mock.patch.object(query_history, "access_token", return_value="sensitive-token"), \
                    mock.patch.object(query_history, "export_history", side_effect=fake_export):
                self.assertEqual(query_history.main(), 0)

            payload = json.loads(status.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "captured")
            self.assertEqual(payload["rows"], 1)
            serialized = status.read_text(encoding="utf-8")
            self.assertNotIn("sensitive-id", serialized)
            self.assertNotIn("sensitive-secret", serialized)
            self.assertNotIn("sensitive-token", serialized)


if __name__ == "__main__":
    unittest.main()
