import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


FAKE_JMETER = r'''#!/bin/bash
result=""
while [ "$#" -gt 0 ]; do
    if [ "$1" = "-l" ]; then
        shift
        result="$1"
    fi
    shift
done
if [ "${FAKE_JMETER_RC:-0}" -eq 0 ]; then
    mkdir -p "$(dirname "$result")"
    printf '%s\n' \
      'timeStamp,elapsed,label,responseCode,responseMessage,threadName,dataType,success,failureMessage,bytes,sentBytes,grpThreads,allThreads,URL,Latency,IdleTime,Connect' \
      '1000,100,q1,200,OK,t,text,true,,1,1,1,1,,100,0,1' > "$result"
fi
exit "${FAKE_JMETER_RC:-0}"
'''


class RunnerIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.jmeter_home = root / "jmeter"
        (self.jmeter_home / "bin").mkdir(parents=True)
        executable = self.jmeter_home / "bin" / "jmeter"
        executable.write_text(FAKE_JMETER)
        executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
        self.connection = root / "connection.properties"
        self.connection.write_text("CONNECTION_STRING=jdbc:test\n")
        self.plan = root / "plain.jmx"
        self.plan.write_text("<jmeterTestPlan/>\n")
        self.queries = root / "queries.csv"
        self.queries.write_text('query_alias,query_string\nq1,"select 1"\n')
        self.reports = root / "reports"

    def run_runner(self, **overrides):
        env = os.environ.copy()
        env.update({
            "CONNECTION_FILE": str(self.connection),
            "TEST_PLAN": str(self.plan),
            "QUERY_FILE": str(self.queries),
            "JMETER_HOME": str(self.jmeter_home),
            "REPORT_PATH": str(self.reports),
            "GENERATE_DASHBOARD": "false",
            "COPY_TO_S3": "false",
            "CONCURRENT_QUERY_COUNT": "4",
        })
        env.update(overrides)
        return subprocess.run(
            [str(ROOT / "run_test.sh")], cwd=ROOT, env=env,
            text=True, capture_output=True, timeout=20,
        )

    def test_success_infers_partition_compatible_run_type(self):
        completed = self.run_runner()
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("queries.csv (1 queries)", completed.stdout)
        self.assertIn("Dashboard: disabled", completed.stdout)
        run_dir = next(self.reports.iterdir())
        summary = json.loads((run_dir / "run_summary.json").read_text())
        self.assertEqual(summary["meta"]["run_type"], "concurrency_4")
        self.assertEqual(summary["raw_samples"], 1)
        self.assertEqual(summary["query_samples"], 1)
        self.assertEqual(summary["ignored_control_samples"], 0)
        self.assertEqual(summary["meta"]["requested_concurrency"], "4")
        self.assertEqual(len(summary["meta"]["query_sha256"]), 64)

    def test_jmeter_failure_is_finalized_and_propagated(self):
        completed = self.run_runner(FAKE_JMETER_RC="7")
        self.assertEqual(completed.returncode, 1)
        self.assertIn("JMeter exited with status 7", completed.stdout)
        self.assertIn("Test FAILED", completed.stdout)


if __name__ == "__main__":
    unittest.main()
