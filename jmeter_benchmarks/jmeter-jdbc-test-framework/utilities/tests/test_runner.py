import json
import os
import stat
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


FAKE_JMETER = r'''#!/bin/bash
if [ -n "${CAPTURE_JVM_ARGS:-}" ]; then
    printf '%s' "${JVM_ARGS:-}" > "$CAPTURE_JVM_ARGS"
fi
if [ -n "${CAPTURE_JMETER_ARGS:-}" ]; then
    printf '%s\n' "$@" > "$CAPTURE_JMETER_ARGS"
fi
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
            "PROMETHEUS_ENABLED": "false",
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
        self.assertIn("queries.csv (1 unique queries)", completed.stdout)
        self.assertIn("Dashboard: disabled", completed.stdout)
        run_dir = next(self.reports.iterdir())
        summary = json.loads((run_dir / "run_summary.json").read_text())
        self.assertEqual(summary["meta"]["run_type"], "concurrency_4")
        self.assertEqual(summary["raw_samples"], 1)
        self.assertEqual(summary["query_samples"], 1)
        self.assertEqual(summary["ignored_control_samples"], 0)
        self.assertEqual(summary["meta"]["requested_concurrency"], "4")
        self.assertEqual(len(summary["meta"]["query_sha256"]), 64)
        self.assertEqual(
            (run_dir / "inputs" / "query.csv").read_text(),
            self.queries.read_text(),
        )

    def test_shared_system_settings_supply_cli_defaults_and_env_wins(self):
        settings = Path(self.temp.name) / "system_settings.json"
        settings.write_text(json.dumps({
            "copy_to_s3": False,
            "s3_report_path": "s3://shared/benchmark-results/v1",
            "generate_dashboard": False,
            "prometheus_enabled": False,
        }))
        args_capture = Path(self.temp.name) / "args.txt"
        completed = self.run_runner(
            BENCHMARK_SYSTEM_SETTINGS_FILE=str(settings),
            CAPTURE_JMETER_ARGS=str(args_capture),
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        args = args_capture.read_text().splitlines()
        self.assertIn("-JS3_REPORT_PATH=s3://shared/benchmark-results/v1", args)

        explicit_capture = Path(self.temp.name) / "explicit-args.txt"
        completed = self.run_runner(
            BENCHMARK_SYSTEM_SETTINGS_FILE=str(settings),
            CAPTURE_JMETER_ARGS=str(explicit_capture),
            S3_REPORT_PATH="s3://explicit/results",
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        args = explicit_capture.read_text().splitlines()
        self.assertIn("-JS3_REPORT_PATH=s3://explicit/results", args)

    def test_jmeter_failure_is_finalized_and_propagated(self):
        completed = self.run_runner(FAKE_JMETER_RC="7")
        self.assertEqual(completed.returncode, 1)
        self.assertIn("JMeter exited with status 7", completed.stdout)
        self.assertIn("Test FAILED", completed.stdout)

    def test_query_preflight_rejects_blank_record_before_jmeter(self):
        self.queries.write_text('query_alias,query_string\nq1,"select 1"\n\n')
        completed = self.run_runner()
        self.assertEqual(completed.returncode, 1)
        self.assertIn("line 3 is blank", completed.stderr)
        self.assertIn("QUERY_FILE preflight validation failed", completed.stdout)
        self.assertFalse(self.reports.exists())

    def test_s3_query_input_is_downloaded_fresh_and_records_source(self):
        fake_bin = Path(self.temp.name) / "bin"
        fake_bin.mkdir()
        aws = fake_bin / "aws"
        aws.write_text(
            '#!/bin/bash\n'
            'test "$1" = s3 && test "$2" = cp || exit 9\n'
            'cp "$FAKE_S3_OBJECT" "$4"\n'
        )
        aws.chmod(aws.stat().st_mode | stat.S_IXUSR)
        completed = self.run_runner(
            QUERY_FILE="s3://example-bucket/path/remote-queries.csv",
            FAKE_S3_OBJECT=str(self.queries),
            PATH=f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("Downloading QUERY_FILE from s3://example-bucket/path/remote-queries.csv", completed.stdout)
        run_dir = next(self.reports.iterdir())
        summary = json.loads((run_dir / "run_summary.json").read_text())
        self.assertEqual(summary["meta"]["query_source"], "s3://example-bucket/path/remote-queries.csv")
        self.assertEqual(summary["meta"]["queries"], "query-remote-queries.csv")

    def test_test_properties_load_before_environment_overrides(self):
        properties = Path(self.temp.name) / "fixed.properties"
        properties.write_text(
            "CONCURRENT_QUERY_COUNT=7\n"
            "HOLD_PERIOD=41\n"
            "QUERY_TIMEOUT=123\n"
        )
        args_capture = Path(self.temp.name) / "jmeter-args.txt"
        completed = self.run_runner(
            TEST_PROPERTIES_FILE=str(properties),
            CONCURRENT_QUERY_COUNT="5",
            CAPTURE_JMETER_ARGS=str(args_capture),
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        args = args_capture.read_text().splitlines()
        q_positions = [index for index, value in enumerate(args) if value == "-q"]
        self.assertEqual(len(q_positions), 2)
        self.assertEqual(args[q_positions[0] + 1], str(self.connection))
        self.assertEqual(args[q_positions[1] + 1], str(properties))
        self.assertIn("-JCONCURRENT_QUERY_COUNT=5", args)
        self.assertIn("-JHOLD_PERIOD=41", args)
        self.assertIn("-JQUERY_TIMEOUT=123", args)

    def test_s3_test_properties_are_downloaded_and_applied(self):
        properties = Path(self.temp.name) / "remote.properties"
        properties.write_text("HOLD_PERIOD=37\n")
        fake_bin = Path(self.temp.name) / "bin-properties"
        fake_bin.mkdir()
        aws = fake_bin / "aws"
        aws.write_text(
            '#!/bin/bash\n'
            'test "$1" = s3 && test "$2" = cp || exit 9\n'
            'cp "$FAKE_S3_OBJECT" "$4"\n'
        )
        aws.chmod(aws.stat().st_mode | stat.S_IXUSR)
        args_capture = Path(self.temp.name) / "jmeter-args.txt"
        completed = self.run_runner(
            TEST_PROPERTIES_FILE="s3://example-bucket/workloads/remote.properties",
            FAKE_S3_OBJECT=str(properties),
            CAPTURE_JMETER_ARGS=str(args_capture),
            PATH=f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("Downloading TEST_PROPERTIES_FILE", completed.stdout)
        self.assertIn("-JHOLD_PERIOD=37", args_capture.read_text().splitlines())

    def test_snowflake_driver_adds_arrow_java_access_without_losing_caller_options(self):
        capture = Path(self.temp.name) / "jvm-args.txt"
        args_capture = Path(self.temp.name) / "jmeter-args.txt"
        self.connection.write_text(
            "CONNECTION_STRING=jdbc:test\n"
            "DRIVER_CLASS=net.snowflake.client.api.driver.SnowflakeDriver\n"
        )
        completed = self.run_runner(
            JVM_ARGS="-Xmx2g",
            CAPTURE_JVM_ARGS=str(capture),
            CAPTURE_JMETER_ARGS=str(args_capture),
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(
            capture.read_text(),
            "-Xmx2g --add-opens=java.base/java.nio=ALL-UNNAMED",
        )
        self.assertIn(
            "-JJDBC_INIT_SQL=ALTER SESSION SET USE_CACHED_RESULT = FALSE",
            args_capture.read_text().splitlines(),
        )

    def test_warmup_uses_separate_results_and_keeps_measured_summary_clean(self):
        self.plan = Path(self.temp.name) / "Test-Plan-Run-Once-static-concurrency.jmx"
        self.plan.write_text("<jmeterTestPlan/>\n")
        warmup = Path(self.temp.name) / "warmup.csv"
        warmup.write_text('query_alias,query_string\nbootstrap,"select 1"\n')
        completed = self.run_runner(
            WARMUP_ENABLED="true",
            WARMUP_QUERY_FILE=str(warmup),
            WARMUP_ITERATIONS="1",
            MEASURED_ITERATIONS="3",
            E6_QUERY_HISTORY_ENABLED="true",
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("Benchmark warm-up (excluded)", completed.stdout)
        self.assertIn("Warm-up complete; starting measured run", completed.stdout)
        self.assertEqual(
            completed.stdout.count("E6_QUERY_HISTORY_ENABLED=true ignored for a non-e6 JDBC connection"),
            1,
        )
        warmup_summaries = list((self.reports / "_warmup").glob("*/run_summary.json"))
        measured_summaries = list(self.reports.glob("*/run_summary.json"))
        self.assertEqual(len(warmup_summaries), 1)
        self.assertEqual(len(measured_summaries), 1)
        self.assertEqual(list((self.reports / "_warmup").glob("*/measured-queries-3x.csv")), [])
        self.assertEqual(len(list(self.reports.glob("*/measured-queries-3x.csv"))), 1)
        warmup_summary = json.loads(warmup_summaries[0].read_text())
        measured_summary = json.loads(measured_summaries[0].read_text())
        self.assertEqual(warmup_summary["samples"], 1)
        self.assertEqual(measured_summary["samples"], 1)
        self.assertEqual(measured_summary["meta"]["warmup_enabled"], "true")
        self.assertEqual(measured_summary["meta"]["warmup_queries"], "warmup.csv")

    def test_run_once_measured_iterations_repeat_rows_with_same_labels(self):
        self.plan = Path(self.temp.name) / "Test-Plan-Run-Once-static-concurrency.jmx"
        self.plan.write_text("<jmeterTestPlan/>\n")
        self.queries.write_text(
            'query_alias,query_string\nq1,"select 1"\nq2,"select 2"\n'
        )
        args_capture = Path(self.temp.name) / "jmeter-args.txt"
        completed = self.run_runner(
            MEASURED_ITERATIONS="3", CAPTURE_JMETER_ARGS=str(args_capture)
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        query_arg = next(
            line for line in args_capture.read_text().splitlines()
            if line.startswith("-JQUERY_PATH=")
        )
        repeated = Path(query_arg.split("=", 1)[1])
        rows = repeated.read_text().splitlines()
        self.assertEqual(rows[0], "query_alias,query_string")
        self.assertEqual(rows[1:], [
            "q1,select 1", "q2,select 2",
            "q1,select 1", "q2,select 2",
            "q1,select 1", "q2,select 2",
        ])
        summary_path = next(self.reports.glob("*/run_summary.json"))
        summary = json.loads(summary_path.read_text())
        self.assertEqual(summary["meta"]["measured_iterations"], "3")
        self.assertEqual(summary["meta"]["queries"], "queries.csv")

    def test_every_jdbc_plan_initializes_physical_connections_from_property(self):
        plans = ROOT / "Test-Plans"
        for path in plans.glob("*.jmx"):
            data_sources = ET.parse(path).findall(".//JDBCDataSource")
            for source in data_sources:
                init = source.find("./stringProp[@name='initQuery']")
                self.assertIsNotNone(init, path.name)
                self.assertEqual(init.text, "${__P(JDBC_INIT_SQL,)}", path.name)

    def test_prometheus_transform_adds_dashboard_compatible_metrics(self):
        source = self.reports / "source.jmx"
        destination = self.reports / "generated.jmx"
        self.reports.mkdir()
        source.write_text("<jmeterTestPlan><hashTree><TestPlan/><hashTree/></hashTree></jmeterTestPlan>")
        completed = subprocess.run([
            "python3", str(ROOT / "utilities" / "enable_prometheus_listener.py"),
            str(source), str(destination),
        ], text=True, capture_output=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        tree = ET.parse(destination)
        listener = tree.find(".//com.github.johrstrom.listener.PrometheusListener")
        self.assertIsNotNone(listener)
        names = {node.text for node in listener.findall(".//stringProp[@name='collector.metric_name']")}
        self.assertEqual(names, {"ResponseTime", "Ratio"})
        self.assertFalse(listener.findall(".//stringProp[@name='listener.collector.listen_to']"))

    def test_databricks_transform_uses_pwd_without_embedding_secret(self):
        source = self.reports / "source.jmx"
        destination = self.reports / "generated.jmx"
        self.reports.mkdir()
        source.write_text(
            '<jmeterTestPlan><hashTree><JDBCDataSource>'
            '<stringProp name="connectionProperties"></stringProp>'
            '</JDBCDataSource></hashTree></jmeterTestPlan>'
        )
        completed = subprocess.run([
            "python3", str(ROOT / "utilities" / "configure_jdbc_connection.py"),
            str(source), str(destination), "PWD=${PASSWORD}",
        ], text=True, capture_output=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        prop = ET.parse(destination).find(".//stringProp[@name='connectionProperties']")
        self.assertEqual(prop.text, "PWD=${PASSWORD}")
        self.assertNotIn("dapi", destination.read_text())


if __name__ == "__main__":
    unittest.main()
