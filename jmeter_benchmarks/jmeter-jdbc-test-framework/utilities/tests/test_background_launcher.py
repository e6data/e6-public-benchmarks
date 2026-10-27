"""Exercise detached startup without opening a port or launching benchmarks."""
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import unittest


class BackgroundLauncherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        source = Path(__file__).resolve().parents[2] / 'start_ui.sh'
        shutil.copy(source, self.root)
        (self.root / '.venv/bin').mkdir(parents=True)
        self.python = self.root / '.venv/bin/python'
        self.python.write_text('#!/bin/bash\necho "args:$*"\nexec sleep 60\n')
        self.python.chmod(0o755)
        (self.root / 'bin').mkdir()
        curl = self.root / 'bin/curl'
        curl.write_text('#!/bin/bash\nexit 0\n')
        curl.chmod(0o755)
        self.env = dict(os.environ, PATH=str(self.root / 'bin') + ':' + os.environ['PATH'])
        for key in ('BENCHMARK_UI_HOST', 'BENCHMARK_UI_PORT', 'BENCHMARK_UI_PID_FILE'):
            self.env.pop(key, None)

    def tearDown(self):
        pid_file = self.root / 'logs/ui.pid'
        if pid_file.exists():
            try:
                os.kill(int(pid_file.read_text()), signal.SIGTERM)
            except ProcessLookupError:
                pass
        self.tmp.cleanup()

    def run_launcher(self, *args):
        return subprocess.run(['bash', str(self.root / 'start_ui.sh'), '--background', *args],
                              env=self.env, capture_output=True, text=True, timeout=25)

    def test_detaches_appends_log_and_refuses_duplicate(self):
        (self.root / 'logs').mkdir()
        log = self.root / 'logs/ui-console.log'
        log.write_text('existing log\n')
        (self.root / '.benchmark-ui.env').write_text('BENCHMARK_UI_PORT=8766\n')
        result = self.run_launcher()
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn('http://127.0.0.1:8766', result.stdout)
        self.assertIn('existing log', log.read_text())
        self.assertIn('args:-m ui.server --host 127.0.0.1 --port 8766', log.read_text())
        duplicate = self.run_launcher()
        self.assertNotEqual(duplicate.returncode, 0)
        self.assertIn('already running', duplicate.stdout)

    def test_early_failure_is_not_reported_as_healthy(self):
        self.python.write_text('#!/bin/bash\nexit 1\n')
        result = self.run_launcher()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('startup failed', result.stderr)

    def test_invalid_arguments_do_not_start(self):
        for args in [('--port', '0'), ('--port', '65536'), ('--port',), ('--bad',)]:
            with self.subTest(args=args):
                self.assertEqual(self.run_launcher(*args).returncode, 2)
        self.assertFalse((self.root / 'logs').exists())

    def test_foreground_preserves_pid_and_does_not_detach(self):
        with subprocess.Popen(['bash', str(self.root / 'start_ui.sh')], env=self.env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as process:
            try:
                self.assertIn('args:-m ui.server --host 127.0.0.1 --port 8765', process.stdout.readline())
                self.assertIsNone(process.poll())
                self.assertEqual(int((self.root / 'logs/ui.pid').read_text()), process.pid)
                self.assertFalse((self.root / 'logs/ui-console.log').exists())
            finally:
                process.terminate()
                process.wait(timeout=5)

    def test_explicit_bind_overrides_environment(self):
        self.env['BENCHMARK_UI_PORT'] = '8766'
        result = self.run_launcher('--host', '0.0.0.0', '--port', '8767')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('http://127.0.0.1:8767', result.stdout)
        self.assertIn('--host 0.0.0.0 --port 8767', (self.root / 'logs/ui-console.log').read_text())
