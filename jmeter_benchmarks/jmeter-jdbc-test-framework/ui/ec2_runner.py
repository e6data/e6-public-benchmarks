"""On-demand EC2 execution adapter for Benchmark Studio.

The adapter deliberately invokes the existing run_test.sh on the worker.  It
does not interpret JMeter results or modify workload inputs.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse


class EC2RunnerError(RuntimeError):
    pass


@dataclass(frozen=True)
class EC2Config:
    instance_id: str
    region: str
    control_s3_uri: str
    worker_root: str
    startup_timeout: int = 600
    poll_seconds: int = 10
    idle_stop_minutes: int = 20
    command_timeout: int = 172800
    manage_power: bool = True

    @classmethod
    def from_env(cls) -> "EC2Config":
        values = {
            "instance_id": os.environ.get("BENCHMARK_EC2_INSTANCE_ID", ""),
            "region": os.environ.get("BENCHMARK_EC2_REGION", "us-east-1"),
            "control_s3_uri": os.environ.get("BENCHMARK_EC2_CONTROL_S3_URI", ""),
            "worker_root": os.environ.get("BENCHMARK_EC2_WORKER_ROOT", "/opt/e6-public-benchmarks/jmeter_benchmarks/jmeter-jdbc-test-framework"),
        }
        missing = [key for key in ("instance_id", "control_s3_uri") if not values[key]]
        if missing:
            raise EC2RunnerError("Missing EC2 runner settings: " + ", ".join(missing))
        if not values["control_s3_uri"].startswith("s3://"):
            raise EC2RunnerError("BENCHMARK_EC2_CONTROL_S3_URI must be an s3:// URI")
        return cls(
            **values,
            startup_timeout=int(os.environ.get("BENCHMARK_EC2_STARTUP_TIMEOUT", "600")),
            poll_seconds=max(2, int(os.environ.get("BENCHMARK_EC2_POLL_SECONDS", "10"))),
            idle_stop_minutes=max(1, int(os.environ.get("BENCHMARK_EC2_IDLE_STOP_MINUTES", "20"))),
            command_timeout=max(3600, int(os.environ.get("BENCHMARK_EC2_COMMAND_TIMEOUT", "172800"))),
            manage_power=os.environ.get("BENCHMARK_EC2_MANAGE_POWER", "true").lower() == "true",
        )


class EC2Runner:
    def __init__(self, config: EC2Config, command: Callable[..., subprocess.CompletedProcess[str]] | None = None):
        self.config = config
        self.command = command or subprocess.run

    def _run(self, args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
        result = self.command(args, text=True, capture_output=True, check=False)
        if check and result.returncode:
            detail = (result.stderr or result.stdout or "unknown AWS CLI error").strip()
            raise EC2RunnerError(self.redact(detail))
        return result

    def redact(self, value: str) -> str:
        """Keep infrastructure identifiers out of browser-visible errors."""
        value = value.replace(self.config.instance_id, "<worker-instance>")
        value = value.replace(self.config.control_s3_uri.rstrip("/"), "s3://<private-control-prefix>")
        value = re.sub(r"\b\d{12}\b", "<aws-account>", value)
        value = re.sub(r"\b(?:i|mi)-[0-9a-f]{8,32}\b", "<worker-instance>", value)
        value = re.sub(r"\b[0-9a-f]{8}-[0-9a-f-]{27,36}\b", "<command-id>", value, flags=re.I)
        return value

    def _aws(self, service: str, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return self._run(["aws", service, *args, "--region", self.config.region], check=check)

    def stage_job(self, run_id: str, env: dict[str, str], root: Path) -> str:
        """Upload only the resolved environment and selected input files.

        The control prefix must be private.  SSE-S3 is always requested; a
        bucket policy may enforce KMS instead without changing the worker.
        """
        prefix = self.config.control_s3_uri.rstrip("/") + f"/jobs/{run_id}"
        with tempfile.TemporaryDirectory(prefix=f"benchmark-{run_id}-") as temp:
            job = Path(temp) / "job"
            job.mkdir()
            remote_env = dict(env)
            for key in ("CONNECTION_FILE", "QUERY_FILE", "LOAD_PROFILE"):
                value = env.get(key)
                if not value:
                    continue
                source = Path(value)
                if not source.is_absolute():
                    source = root / source
                if not source.is_file():
                    raise EC2RunnerError(f"Selected {key} does not exist: {source}")
                target = job / "inputs" / key.lower() / source.name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                remote_env[key] = f"{{JOB_DIR}}/{target.relative_to(job).as_posix()}"
            remote_env["REPORT_PATH"] = f"reports/ui-{run_id}"
            (job / "environment.json").write_text(json.dumps(remote_env, indent=2) + "\n")
            archive = shutil.make_archive(str(Path(temp) / "job"), "zip", job)
            self._run(["aws", "s3", "cp", archive, f"{prefix}/input.zip", "--sse", "AES256", "--region", self.config.region])
        return prefix

    def ensure_worker_ready(self, status: Callable[[str], None]) -> None:
        status("worker_starting")
        if self.config.manage_power:
            self._aws("ec2", "start-instances", "--instance-ids", self.config.instance_id)
            self._aws("ec2", "wait", "instance-running", "--instance-ids", self.config.instance_id)
        else:
            result = self._aws(
                "ec2", "describe-instances", "--instance-ids", self.config.instance_id,
                "--query", "Reservations[0].Instances[0].State.Name", "--output", "text",
            )
            if result.stdout.strip() != "running":
                raise EC2RunnerError(
                    "The externally managed benchmark worker is not running; start it before launching a test"
                )
        deadline = time.time() + self.config.startup_timeout
        while time.time() < deadline:
            result = self._aws(
                "ssm", "describe-instance-information", "--filters",
                f"Key=InstanceIds,Values={self.config.instance_id}",
                "--query", "InstanceInformationList[0].PingStatus", "--output", "text", check=False,
            )
            if result.returncode == 0 and result.stdout.strip() == "Online":
                return
            time.sleep(self.config.poll_seconds)
        raise EC2RunnerError("EC2 instance started but did not become SSM-ready before timeout")

    def execute(self, run_id: str, env: dict[str, str], root: Path, report_root: Path,
                status: Callable[[str], None], log: Callable[[str], None],
                command_started: Callable[[str], None] | None = None) -> int:
        prefix = self.stage_job(run_id, env, root)
        self.ensure_worker_ready(status)
        status("running")
        command = (
            f"{self.config.worker_root}/deploy/ec2-worker/run_job.sh "
            f"{shlex.quote(prefix + '/input.zip')} {shlex.quote(prefix)} {shlex.quote(run_id)}"
        )
        parameters = json.dumps({"commands": [command], "executionTimeout": [str(self.config.command_timeout)]})
        sent = self._aws(
            "ssm", "send-command", "--instance-ids", self.config.instance_id,
            "--document-name", "AWS-RunShellScript", "--parameters", parameters,
            "--query", "Command.CommandId", "--output", "text",
        )
        command_id = sent.stdout.strip()
        if not command_id:
            raise EC2RunnerError("SSM did not return a command ID")
        if command_started:
            command_started(command_id)
        log("On-demand EC2 worker accepted the benchmark run")
        terminal = {"Success", "Failed", "Cancelled", "TimedOut", "Cancelling"}
        state = "Pending"
        while state not in terminal:
            time.sleep(self.config.poll_seconds)
            self.sync_results(prefix, report_root, check=False)
            result = self._aws(
                "ssm", "get-command-invocation", "--command-id", command_id,
                "--instance-id", self.config.instance_id, "--output", "json", check=False,
            )
            if result.returncode == 0:
                payload = json.loads(result.stdout)
                state = payload.get("Status", "Pending")
                for line in (payload.get("StandardOutputContent", "") + payload.get("StandardErrorContent", "")).splitlines()[-20:]:
                    log(line)
        self.sync_results(prefix, report_root, check=True)
        self.schedule_stop(log)
        return 0 if state == "Success" else 1

    def cancel(self, command_id: str) -> None:
        self._aws("ssm", "cancel-command", "--command-id", command_id,
                  "--instance-ids", self.config.instance_id)

    def sync_results(self, prefix: str, report_root: Path, check: bool) -> None:
        report_root.mkdir(parents=True, exist_ok=True)
        self._run(["aws", "s3", "sync", f"{prefix}/results/", str(report_root), "--region", self.config.region], check=check)

    def schedule_stop(self, log: Callable[[str], None]) -> None:
        if not self.config.manage_power:
            log("Worker power is externally managed; automatic stop is disabled")
            return
        result = self._aws(
            "ssm", "send-command", "--instance-ids", self.config.instance_id,
            "--document-name", "AWS-RunShellScript", "--parameters",
            json.dumps({"commands": [f"sudo systemctl start benchmark-worker-idle-stop@{self.config.idle_stop_minutes}.service"]}),
            "--query", "Command.CommandId", "--output", "text", check=False,
        )
        if result.returncode:
            log("Warning: could not schedule EC2 idle stop; administrator action may be required")
