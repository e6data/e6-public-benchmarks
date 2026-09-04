import unittest
import tempfile
from pathlib import Path

from utilities.check_public_repo_safety import reason_for, violations


class PublicRepoSafetyTests(unittest.TestCase):
    def test_rejects_generated_results_and_local_runtime_state(self):
        paths = [
            "jmeter_benchmarks/jmeter-jdbc-test-framework/reports/run/run_summary.json",
            "jmeter_benchmarks/jmeter-jdbc-test-framework/connection_properties/private.properties",
            "jmeter_benchmarks/jmeter-jdbc-test-framework/ui/benchmark_ui.db",
            "jmeter_benchmarks/jmeter-jdbc-test-framework/logs/ui.log",
            "jmeter_benchmarks/jmeter-jdbc-test-framework/test_configs/private.env",
            "elsewhere/JmeterResultFile.csv",
            "credentials/private.pem",
        ]
        self.assertEqual(len(violations(paths)), len(paths))

    def test_allows_public_templates_catalogs_and_source_files(self):
        paths = [
            "jmeter_benchmarks/jmeter-jdbc-test-framework/connection_properties/connection.properties.template",
            "jmeter_benchmarks/jmeter-jdbc-test-framework/test_configs/sample_benchmark.env",
            "jmeter_benchmarks/jmeter-jdbc-test-framework/data_files/benchmarks/tpcds/reference/public.csv",
            "jmeter_benchmarks/jmeter-jdbc-test-framework/Test-Plans/test.jmx",
            "README.md",
        ]
        self.assertTrue(all(reason_for(path) is None for path in paths))

    def test_detects_renamed_jmeter_result_by_csv_header(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "innocent_name.csv").write_text(
                "timeStamp,elapsed,label,responseCode,success,allThreads\n"
                "1,2,Q1,200,true,1\n"
            )
            found = violations(["innocent_name.csv"], root)
        self.assertEqual(found[0][1], "JMeter sample-result content")


if __name__ == "__main__":
    unittest.main()
