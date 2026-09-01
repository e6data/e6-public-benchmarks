# On-demand EC2 benchmark worker

This directory turns a stopped EC2 instance into an optional JMeter execution
backend. The browser and UI may remain local. The worker still invokes the
unchanged `run_test.sh`; local UI and CLI execution remain the default.

## Worker requirements

- Linux with Java, Python 3, AWS CLI, `unzip`, SSM Agent and this repository.
- An instance profile permitting read/write only under the configured private
  control S3 prefix, plus `ec2:StopInstances` on itself.
- SSM connectivity (private VPC endpoints or outbound HTTPS).
- Bucket encryption and public access blocking. Job bundles contain a temporary
  connection properties file and must be treated as secrets.

Use a clean checkout on the worker. From the framework directory, run the
location-independent installer:

```bash
git clone https://github.com/e6data/e6-public-benchmarks.git
cd e6-public-benchmarks/jmeter_benchmarks/jmeter-jdbc-test-framework
./setup_jmeter.sh --without-ui
sudo ./deploy/ec2-worker/install_worker.sh
```

Run `setup_jmeter.sh --without-ui` as the normal EC2 user so the checkout
remains writable by that user. A remote worker does not host Benchmark Studio,
so it does not require Python 3.10+ or the UI virtual environment. The
privileged worker installer detects the checkout directory,
creates the protected worker state directory, and installs the optional
idle-stop systemd unit. It is safe to use the checkout at
`/home/ec2-user/e6-public-benchmarks`; `/opt` is not required.

For CLI-only execution on the EC2 host, the worker installer is not needed.
Follow the main README: run `./setup_jmeter.sh`, create a connection profile,
and invoke `./run_test.sh`.

Configure the UI service:

```bash
BENCHMARK_UI_RUNNER=ec2
BENCHMARK_EC2_INSTANCE_ID=i-xxxxxxxxxxxxxxxxx
BENCHMARK_EC2_REGION=us-east-1
BENCHMARK_EC2_CONTROL_S3_URI=s3://YOUR-PRIVATE-BUCKET/benchmark-control
BENCHMARK_EC2_IDLE_STOP_MINUTES=20
BENCHMARK_EC2_WORKER_ROOT=/home/ec2-user/e6-public-benchmarks/jmeter_benchmarks/jmeter-jdbc-test-framework
```

For a pre-existing worker whose lifecycle is managed outside Benchmark Studio,
set `BENCHMARK_EC2_MANAGE_POWER=false`. The UI verifies that it is running but
will not call `StartInstances` or schedule an idle stop. SSM command permissions
are still required because SSM is the remote execution channel.

The UI principal needs `ec2:StartInstances`, SSM describe/send/get permissions,
and access to the control prefix. Do not place credentials in SSM command text.
The adapter uploads an encrypted private bundle and sends only its S3 URI.

For optional e6 Query History capture, edit the root-owned worker environment
created by the installer and keep its mode at `0600`:

```bash
sudoedit /etc/e6-benchmark-worker.env
sudo chmod 600 /etc/e6-benchmark-worker.env
```

Set `E6_QUERY_HISTORY_ENABLED=true`, `E6_MACHINE_CLIENT_ID`, and
`E6_MACHINE_CLIENT_SECRET` there. `E6_QUERY_HISTORY_EMAIL` is an optional
additional filter. These credentials are intentionally removed from the UI's
S3 job bundle; configuring them only on the UI host does not enable capture on
the remote worker.
