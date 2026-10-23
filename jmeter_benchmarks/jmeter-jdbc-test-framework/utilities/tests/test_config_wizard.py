"""Run the interactive wizard in an isolated checkout using scripted input."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class ConfigWizardTests(unittest.TestCase):
    def run_wizard(self, answers):
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            shutil.copy(root / 'create_test_config.sh', cwd)
            for folder in ('connection_properties', 'data_files', 'metadata_files', 'test_properties'):
                (cwd / folder).mkdir()
            (cwd / 'connection_properties/test.properties').write_text('DRIVER_CLASS=example.Driver\n')
            (cwd / 'data_files/queries.csv').write_text('query_alias,query_string\nq1,"SELECT 1"\n')
            for name in ('load_profile.csv', 'utg_load_profile.csv'):
                shutil.copy(root / 'test_properties' / name, cwd / 'test_properties' / name)
            result = subprocess.run(['bash', 'create_test_config.sh'], cwd=cwd,
                                    input='\n'.join(answers) + '\n', text=True,
                                    capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return (cwd / 'test_configs/test.env').read_text(), result.stdout

    def test_sequential(self):
        config, output = self.run_wizard(['1', '1', '1', 'test'])
        self.assertIn('CONCURRENT_QUERY_COUNT=1', config)
        self.assertIn('MEASURED_ITERATIONS=1', config)
        self.assertNotIn('HOLD_PERIOD=', config)
        self.assertIn('4) Advanced', output)

    def test_fixed_qps(self):
        config, _ = self.run_wizard(['1', '2', '1', '2', '300', '', '', 'test'])
        self.assertIn('QPS=2', config)
        self.assertIn('HOLD_PERIOD=300', config)

    def test_arrival_profile(self):
        config, _ = self.run_wizard(['1', '3', '1', '', '', 'test'])
        self.assertIn('LOAD_PROFILE=test_properties/load_profile.csv', config)
        self.assertNotIn('HOLD_PERIOD=', config)

    def test_advanced_concurrency_profile(self):
        config, _ = self.run_wizard(['1', '4', '3', '1', '', '', 'test'])
        self.assertIn('LOAD_PROFILE=test_properties/utg_load_profile.csv', config)
        self.assertNotIn('HOLD_PERIOD=', config)

    def test_advanced_qpm_minutes(self):
        config, _ = self.run_wizard(['1', '4', '4', '1', '', '', '', '', 'test'])
        self.assertIn('QPM=10', config)
        self.assertIn('HOLD_PERIOD=5', config)

    def test_advanced_run_once(self):
        config, _ = self.run_wizard(['1', '4', '2', '1', '4', 'test'])
        self.assertIn('CONCURRENT_QUERY_COUNT=4', config)
