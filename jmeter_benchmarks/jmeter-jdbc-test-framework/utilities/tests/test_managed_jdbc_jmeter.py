"""Opt-in offline smoke: RUN_MANAGED_JDBC_SMOKE=1 python3 -m unittest ...

Uses installed bundles and JMeter. Does not connect to any database.
"""
import csv
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET

from utilities import install_jdbc_drivers as installer


@unittest.skipUnless(os.environ.get("RUN_MANAGED_JDBC_SMOKE") == "1", "optional installed-JMeter smoke")
class JMeterDriverSmoke(unittest.TestCase):
    def test_selected_bundle_is_visible_inside_jmeter(self):
        executable = installer.ROOT / "apache-jmeter-5.6.3/bin/ApacheJMeter.jar"
        engines = [e for e in installer.SPECS if installer.installed_path(e)]
        self.assertTrue(engines, "Install at least one managed bundle first")
        for engine in engines:
            with self.subTest(engine=engine), tempfile.TemporaryDirectory() as tmp:
                directory = Path(tmp)
                document = ET.Element("jmeterTestPlan", version="1.2", properties="5.0", jmeter="5.6.3")
                root = ET.SubElement(document, "hashTree")
                ET.SubElement(root, "TestPlan", guiclass="TestPlanGui", testclass="TestPlan", testname="Offline JDBC load check", enabled="true")
                plan = ET.SubElement(root, "hashTree")
                threads = ET.SubElement(plan, "ThreadGroup", guiclass="ThreadGroupGui", testclass="ThreadGroup", testname="load", enabled="true")
                ET.SubElement(threads, "stringProp", name="ThreadGroup.num_threads").text = "1"
                ET.SubElement(threads, "stringProp", name="ThreadGroup.ramp_time").text = "0"
                loop = ET.SubElement(threads, "elementProp", name="ThreadGroup.main_controller", elementType="LoopController", guiclass="LoopControlPanel", testclass="LoopController", enabled="true")
                ET.SubElement(loop, "stringProp", name="LoopController.loops").text = "1"
                ET.SubElement(loop, "boolProp", name="LoopController.continue_forever").text = "false"
                group = ET.SubElement(plan, "hashTree")
                sampler = ET.SubElement(group, "JSR223Sampler", guiclass="TestBeanGUI", testclass="JSR223Sampler", testname="driver-load", enabled="true")
                ET.SubElement(sampler, "stringProp", name="scriptLanguage").text = "groovy"
                ET.SubElement(sampler, "stringProp", name="script").text = (
                    "def cls = Class.forName('" + installer.DRIVERS[engine] + "', true, "
                    "Thread.currentThread().getContextClassLoader()); "
                    "assert cls.getDeclaredConstructor().newInstance() instanceof java.sql.Driver; "
                    "SampleResult.setSuccessful(true)"
                )
                ET.SubElement(group, "hashTree")
                jmx = directory / "load.jmx"
                ET.ElementTree(document).write(jmx, encoding="utf-8", xml_declaration=True)
                result = directory / "result.csv"
                log = directory / "jmeter.log"
                completed = subprocess.run([
                    "java", "-jar", str(executable), "-n", "-t", str(jmx), "-l", str(result), "-j", str(log),
                    "-Juser.classpath=" + installer.installed_path(engine),
                    "-Jjmeter.save.saveservice.output_format=csv",
                    "-Jjmeter.save.saveservice.print_field_names=true",
                    "-Jclassfinder.functions.contain=org.apache.jmeter.functions.",
                ], capture_output=True, text=True, timeout=90)
                self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
                with result.open() as handle:
                    rows = list(csv.DictReader(handle))
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["success"], "true", log.read_text())
