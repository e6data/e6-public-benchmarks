import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from utilities.configure_jdbc_connection import configure
from utilities.inject_jdbc_observer import inject


ROOT = Path(__file__).resolve().parents[2]


class JdbcObserverTests(unittest.TestCase):
    def test_databricks_configuration_then_observer_for_all_jdbc_plans(self):
        for source in sorted((ROOT / "Test-Plans").glob("*.jmx")):
            original = ET.parse(source)
            samplers = original.findall(".//JDBCSampler")
            if not samplers:
                continue
            with self.subTest(plan=source.name), tempfile.TemporaryDirectory() as temp:
                configured = Path(temp) / "configured.jmx"
                observed = Path(temp) / "observed.jmx"
                before = source.read_bytes()
                configure(source, configured, "PWD=${PASSWORD}")
                inject(configured, observed)
                result = ET.parse(observed)
                self.assertEqual(len(result.findall(".//JDBCSampler")), len(samplers))
                self.assertEqual(len(result.findall(
                    ".//JSR223PostProcessor[@testname='Record materialized row count']"
                )), len(samplers))
                self.assertEqual(result.find(
                    ".//JDBCDataSource/stringProp[@name='connectionProperties']"
                ).text, "PWD=${PASSWORD}")
                self.assertEqual(source.read_bytes(), before)
                for old, new in zip(samplers, result.findall(".//JDBCSampler")):
                    self.assertEqual([(p.tag, p.attrib, p.text or "") for p in old],
                                     [(p.tag, p.attrib, p.text or "") for p in new])

    def test_preserves_existing_children_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "source.jmx"
            target = Path(temp) / "target.jmx"
            source.write_text('<jmeterTestPlan><hashTree><JDBCSampler />'
                              '<hashTree><ResponseAssertion testname="existing" />'
                              '<hashTree /></hashTree></hashTree></jmeterTestPlan>')
            inject(source, target)
            inject(target, target)
            tree = ET.parse(target)
            self.assertEqual(len(tree.findall(".//ResponseAssertion")), 1)
            self.assertEqual(len(tree.findall(".//JSR223PostProcessor")), 1)
            script = tree.find(".//JSR223PostProcessor/stringProp[@name='script']").text
            self.assertNotIn("executeQuery", script)
            self.assertNotIn("getConnection", script)

    def test_missing_sampler_tree_rejected_without_output(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "source.jmx"
            target = Path(temp) / "target.jmx"
            source.write_text('<jmeterTestPlan><hashTree><JDBCSampler />'
                              '</hashTree></jmeterTestPlan>')
            with self.assertRaisesRegex(ValueError, "child tree"):
                inject(source, target)
            self.assertFalse(target.exists())

    def test_arrival_plans_use_per_worker_connections(self):
        names = ["Test-Plan-Constant-QPS-On-Arrivals-JSR-Optimized.jmx",
                 "Test-Plan-Constant-QPS-On-Arrivals.jmx",
                 "Test-Plan-Fire-QPS-with-load-profile.jmx"]
        for name in names:
            with self.subTest(plan=name):
                tree = ET.parse(ROOT / "Test-Plans" / name)
                self.assertEqual(tree.find(
                    ".//JDBCDataSource/stringProp[@name='poolMax']"
                ).text, "0")


if __name__ == "__main__":
    unittest.main()
