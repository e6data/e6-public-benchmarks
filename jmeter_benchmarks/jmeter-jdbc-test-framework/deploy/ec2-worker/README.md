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

Install on the worker:

```bash
sudo install -d -m 700 /var/lib/e6-benchmark-worker/jobs
sudo install -m 755 deploy/ec2-worker/run_job.sh deploy/ec2-worker/idle_stop.sh \
  /opt/e6-public-benchmarks/jmeter_benchmarks/jmeter-jdbc-test-framework/deploy/ec2-worker/
sudo install -m 644 deploy/ec2-worker/benchmark-worker-idle-stop@.service /etc/systemd/system/
sudo systemctl daemon-reload
./setup_jmeter.sh
```

Configure the UI service:

```bash
BENCHMARK_UI_RUNNER=ec2
BENCHMARK_EC2_INSTANCE_ID=i-xxxxxxxxxxxxxxxxx
BENCHMARK_EC2_REGION=us-east-1
BENCHMARK_EC2_CONTROL_S3_URI=s3://YOUR-PRIVATE-BUCKET/benchmark-control
BENCHMARK_EC2_IDLE_STOP_MINUTES=20
```

The UI principal needs `ec2:StartInstances`, SSM describe/send/get permissions,
and access to the control prefix. Do not place credentials in SSM command text.
The adapter uploads an encrypted private bundle and sends only its S3 URI.
