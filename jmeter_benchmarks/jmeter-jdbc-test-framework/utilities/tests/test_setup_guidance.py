"""Check setup's completion guidance without installing packages or starting services."""
from pathlib import Path
import subprocess
import unittest


class SetupGuidanceTests(unittest.TestCase):
    def guidance(self, ui):
        root = Path(__file__).resolve().parents[2]
        script = (root / 'setup_jmeter.sh').read_text()
        marker = 'echo "Next steps — guided CLI'
        self.assertIn(marker, script)
        footer = script[script.index(marker):]
        result = subprocess.run(
            ['bash', '-eu', '-c', footer], text=True, capture_output=True,
            env={'SCRIPT_DIR': str(root), 'JMETER_DIR': 'apache-jmeter-5.6.3',
                 'INSTALL_UI': 'true' if ui else 'false'}, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_cli_flow_with_and_without_ui(self):
        for ui in (False, True):
            with self.subTest(ui=ui):
                output = self.guidance(ui)
                steps = ['./create_connection.sh', 'query_alias,query_string',
                         './create_test_config.sh', './run_test.sh test_configs/my_benchmark.env',
                         'Check JmeterResultFile.csv']
                positions = [output.index(step) for step in steps]
                self.assertEqual(positions, sorted(positions))
                self.assertIn('smoke_test,"SELECT 1"', output)
                self.assertIn('docs/jdbc-engines.md', output)
                self.assertIn('No UI, S3 or monitoring service is required', output)
                self.assertNotIn('Copy your JDBC drivers', output)
                self.assertEqual('--background' in output, ui)
                if ui:
                    self.assertGreater(output.index('Optional UI'), positions[-1])
