"""Offline checks for the bundled e6 JDBC release; never connects to an engine."""
import hashlib
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[2]
JAR = ROOT / 'jdbc_drivers/e6-jdbc-driver-2.1.51-with-dependencies.jar'
SHA256 = 'dd3856807af96a6907d67b795742e013a5dd171428d76026e4f2fb07ac5906f3'


class BundledE6DriverTests(unittest.TestCase):
    def test_release_integrity_and_documentation(self):
        self.assertEqual(hashlib.sha256(JAR.read_bytes()).hexdigest(), SHA256)
        documentation = (ROOT / 'jdbc_drivers/README.md').read_text()
        self.assertIn(JAR.name, documentation)
        self.assertIn(SHA256, documentation)
        with zipfile.ZipFile(JAR) as archive:
            self.assertIn('io/e6/jdbc/driver/E6Driver.class', archive.namelist())
            self.assertIsNone(archive.testzip())

    @unittest.skipUnless(shutil.which('java'), 'Java required for offline driver loading')
    def test_driver_loads_without_external_dependencies(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'DriverSmoke.java'
            source.write_text('''
import java.sql.Driver;
class DriverSmoke {
    public static void main(String[] args) throws Exception {
        Driver driver = (Driver) Class.forName("io.e6.jdbc.driver.E6Driver")
            .getDeclaredConstructor().newInstance();
        System.out.println(driver.getClass().getName());
    }
}
''')
            result = subprocess.run(['java', '-cp', str(JAR), str(source)],
                                    capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('io.e6.jdbc.driver.E6Driver', result.stdout)
