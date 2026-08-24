import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ui.ec2_runner import EC2Config, EC2Runner, EC2RunnerError


class EC2RunnerTests(unittest.TestCase):
    def test_config_requires_instance_and_s3_prefix(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(EC2RunnerError, "instance_id, control_s3_uri"):
                EC2Config.from_env()

    def test_config_accepts_on_demand_worker(self):
        with mock.patch.dict(os.environ, {
            "BENCHMARK_EC2_INSTANCE_ID": "i-123",
            "BENCHMARK_EC2_CONTROL_S3_URI": "s3://private/control",
            "BENCHMARK_EC2_IDLE_STOP_MINUTES": "15",
        }, clear=True):
            config = EC2Config.from_env()
        self.assertEqual(config.instance_id, "i-123")
        self.assertEqual(config.idle_stop_minutes, 15)

    def test_stage_job_copies_inputs_and_never_places_secret_in_command_arguments(self):
        calls = []
        def command(args, **kwargs):
            calls.append(args)
            return subprocess.CompletedProcess(args, 0, "", "")
        config = EC2Config("i-123", "us-east-1", "s3://private/control", "/worker")
        runner = EC2Runner(config, command)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "connection.properties").write_text("PASSWORD=top-secret\n")
            prefix = runner.stage_job("abc", {"CONNECTION_FILE": "connection.properties"}, root)
        self.assertEqual(prefix, "s3://private/control/jobs/abc")
        flattened = json.dumps(calls)
        self.assertNotIn("top-secret", flattened)
        self.assertIn("--sse", calls[-1])

    def test_cancel_targets_configured_instance(self):
        calls = []
        def command(args, **kwargs):
            calls.append(args)
            return subprocess.CompletedProcess(args, 0, "", "")
        runner = EC2Runner(EC2Config("i-123", "us-east-1", "s3://private/control", "/worker"), command)
        runner.cancel("cmd-1")
        self.assertIn("cancel-command", calls[0])
        self.assertIn("i-123", calls[0])

    def test_browser_visible_errors_redact_aws_identifiers(self):
        runner = EC2Runner(EC2Config(
            "i-0123456789abcdef0", "us-east-1", "s3://private-bucket/control", "/worker"
        ))
        message = runner.redact(
            "instance i-0123456789abcdef0 in account 123456789012 failed; "
            "input s3://private-bucket/control/jobs/abc"
        )
        self.assertNotIn("i-0123456789abcdef0", message)
        self.assertNotIn("123456789012", message)
        self.assertNotIn("private-bucket", message)

    def test_externally_managed_worker_is_not_started_or_stopped(self):
        calls = []
        def command(args, **kwargs):
            calls.append(args)
            if "describe-instances" in args:
                return subprocess.CompletedProcess(args, 0, "running\n", "")
            if "describe-instance-information" in args:
                return subprocess.CompletedProcess(args, 0, "Online\n", "")
            return subprocess.CompletedProcess(args, 0, "", "")
        config = EC2Config(
            "i-123", "us-east-1", "s3://private/control", "/worker",
            poll_seconds=2, manage_power=False,
        )
        runner = EC2Runner(config, command)
        runner.ensure_worker_ready(lambda _: None)
        messages = []
        runner.schedule_stop(messages.append)
        flattened = json.dumps(calls)
        self.assertNotIn("start-instances", flattened)
        self.assertNotIn("stop-instances", flattened)
        self.assertIn("automatic stop is disabled", messages[0])


if __name__ == "__main__":
    unittest.main()
