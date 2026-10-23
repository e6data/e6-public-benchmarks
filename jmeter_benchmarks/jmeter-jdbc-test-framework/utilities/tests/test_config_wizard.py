"""Run the interactive wizard in an isolated checkout using scripted input."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from utilities import wizard_input
from ui import server


class ConfigWizardTests(unittest.TestCase):
    def run_wizard(self, answers, expected_code=0, interactive=False):
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            shutil.copy(root / 'create_test_config.sh', cwd)
            shutil.copy(root / 'run_jmeter_tests_interactive.sh', cwd)
            shutil.copytree(root / 'utilities', cwd / 'utilities', ignore=shutil.ignore_patterns('__pycache__'))
            shutil.copytree(root / 'test_properties', cwd / 'test_properties')
            for folder in ('connection_properties', 'data_files', 'metadata_files'):
                (cwd / folder).mkdir()
            (cwd / 'connection_properties/test.properties').write_text('DRIVER_CLASS=example.Driver\n')
            (cwd / 'data_files/queries.csv').write_text('query_alias,query_string\nq1,"SELECT 1"\n')
            for name in ('load_profile.csv', 'utg_load_profile.csv'):
                shutil.copy(root / 'test_properties' / name, cwd / 'test_properties' / name)
            (cwd / 'data_files/nested').mkdir()
            (cwd / 'data_files/nested/queries.csv').write_text('query_alias,query_string\nq1,"SELECT 1"\n')
            runner = cwd / 'run_test.sh'
            runner.write_text('#!/bin/bash\nprintf "RUNNER_CALLED:%s\\n" "$1"\n')
            runner.chmod(0o755)
            result = subprocess.run(['bash', 'run_jmeter_tests_interactive.sh' if interactive else 'create_test_config.sh'], cwd=cwd,
                                    input='\n'.join(answers) + '\n', text=True,
                                    capture_output=True, timeout=10)
            if expected_code:
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((cwd / 'test_configs/test.env').exists())
                return '', result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return (cwd / 'test_configs/test.env').read_text(), result.stdout

    def test_sequential(self):
        config, output = self.run_wizard(['1', '1', '1', '', '', 'test'])
        self.assertIn('CONCURRENT_QUERY_COUNT=1', config)
        self.assertIn('MEASURED_ITERATIONS=1', config)
        self.assertNotIn('HOLD_PERIOD=', config)
        self.assertIn('4) Advanced', output)

    def test_fixed_qps(self):
        config, _ = self.run_wizard(['1', '2', '1', '2', '300', '', '', 'test'])
        self.assertIn('QPS=2', config)
        self.assertIn('HOLD_PERIOD=300', config)

    def test_arrival_profile(self):
        config, output = self.run_wizard(['1', '3', '1', '', '', '', 'test'])
        self.assertIn('LOAD_PROFILE=test_properties/load_profile.csv', config)
        self.assertNotIn('HOLD_PERIOD=', config)
        self.assertIn('Schedule duration: 30 seconds', output)

    def test_advanced_concurrency_profile(self):
        config, _ = self.run_wizard(['1', '4', '3', '1', '', '', 'test'])
        self.assertIn('LOAD_PROFILE=test_properties/utg_load_profile.csv', config)
        self.assertNotIn('HOLD_PERIOD=', config)

    def test_advanced_qpm_minutes(self):
        config, _ = self.run_wizard(['1', '4', '4', '1', '', '', '', '', 'test'])
        self.assertIn('QPM=10', config)
        self.assertIn('HOLD_PERIOD=5', config)

    def test_advanced_run_once(self):
        config, _ = self.run_wizard(['1', '4', '2', '1', '4', '', '', 'test'])
        self.assertIn('CONCURRENT_QUERY_COUNT=4', config)

    def test_defaults_match_ui_properties(self):
        config, _ = self.run_wizard(['1', '2', '1', '', '', '', '', 'test'])
        root = Path(__file__).resolve().parents[2]
        defaults = dict(line.split('=', 1) for line in
                        (root / 'test_properties/constant_qps.properties').read_text().splitlines()
                        if '=' in line and not line.startswith('#'))
        self.assertIn('QPS=' + defaults['QPS'], config)
        self.assertIn('HOLD_PERIOD=' + defaults['HOLD_PERIOD'], config)
        self.assertIn('TEST_PROPERTIES_FILE=test_properties/constant_qps.properties', config)
        self.assertEqual(server.PLAN_TEST_PROPERTIES['jdbc_qps'], 'test_properties/constant_qps.properties')

    def test_concurrency_defaults_match_ui_properties(self):
        config, _ = self.run_wizard(['1', '4', '1', '1', '', '', '', '', '', 'test'])
        defaults = server.read_preset(server.ROOT / server.PLAN_TEST_PROPERTIES['jdbc_concurrency'])
        self.assertIn('CONCURRENT_QUERY_COUNT=' + defaults['CONCURRENT_QUERY_COUNT'], config)
        self.assertIn('HOLD_PERIOD=' + defaults['HOLD_PERIOD'], config)

    def test_profile_durations_match_ui_preview(self):
        for kind, plan, filename in [('arrivals', 'jdbc_arrivals', 'load_profile.csv'),
                                     ('concurrency', 'jdbc_variable_concurrency', 'utg_load_profile.csv')]:
            path = 'test_properties/' + filename
            preview = server.workload_preview({'plan': plan, 'load_profile': path})
            self.assertIn(f"Schedule duration: {preview['duration_s']} seconds",
                          wizard_input.summarize(kind, str(server.ROOT / path)))

    def test_s3_validation_downloads_and_cleans_temporary_file(self):
        downloaded = []
        def download(command, **kwargs):
            self.assertEqual(command[:4], ['aws', 's3', 'cp', 's3://example/query.csv'])
            path = Path(command[4])
            downloaded.append(path)
            path.write_text('query_alias,query_string\nq1,"SELECT 1"\n')
        with mock.patch.object(wizard_input.subprocess, 'run', side_effect=download):
            self.assertEqual(wizard_input.summarize('query', 's3://example/query.csv'), 'Validated 1 queries')
        self.assertFalse(downloaded[0].exists())

    def test_warmup_and_measured_iterations(self):
        config, _ = self.run_wizard(['1', '1', 'data_files/nested/queries.csv', '3', 'y', '', '2', 'test'])
        self.assertIn('MEASURED_ITERATIONS=3', config)
        self.assertIn('WARMUP_ENABLED=true', config)
        self.assertIn('WARMUP_ITERATIONS=2', config)
        self.assertIn('WARMUP_QUERY_FILE=data_files/nested/queries.csv', config)

    def test_wrong_profile_format_rejected(self):
        _, output = self.run_wizard(['1', '3', '1', 'test_properties/utg_load_profile.csv'], expected_code=1)
        self.assertIn('Input validation failed', output)

    def test_invalid_iteration_rejected(self):
        self.run_wizard(['1', '1', '1', '0'], expected_code=1)

    def test_older_entry_point_requires_confirmation(self):
        args = ['1', '1', '1', '', '', 'test']
        _, output = self.run_wizard(args + ['n'], interactive=True)
        self.assertNotIn('RUNNER_CALLED', output)
        _, output = self.run_wizard(args + ['y'], interactive=True)
        self.assertIn('RUNNER_CALLED:test_configs/test.env', output)
