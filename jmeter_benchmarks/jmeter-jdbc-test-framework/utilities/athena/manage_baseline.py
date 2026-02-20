#!/usr/bin/env python3
"""
Manage baseline runs in Athena.

Allows users to manually mark/unmark runs as baseline for comparison purposes.

Usage:
    # Mark a run as baseline
    python utilities/athena/manage_baseline.py mark \
        --engine e6data --cluster S-2x2 --benchmark tpcds_29_1tb \
        --run-type concurrency_4 --run-id 20251113-144428 \
        --user "george" --notes "Nov 13 verified best performance"

    # Unmark current baseline
    python utilities/athena/manage_baseline.py unmark \
        --engine e6data --cluster S-2x2 --benchmark tpcds_29_1tb \
        --run-type concurrency_4

    # Show current baselines
    python utilities/athena/manage_baseline.py show --engine e6data

    # Compare run against baseline
    python utilities/athena/manage_baseline.py compare \
        --engine e6data --cluster S-2x2 --run-type concurrency_4 \
        --run-id 20251114-120000
"""

import argparse
import json
import os
import time
from datetime import datetime

import boto3


class BaselineManager:
    def __init__(self, region="us-east-1"):
        self.athena = boto3.client("athena", region_name=region)
        self.s3 = boto3.client("s3", region_name=region)
        self.database = "jmeter_analysis"
        self.output_location = os.environ.get(
            "ATHENA_OUTPUT_LOCATION", "s3://your-s3-bucket/athena-query-results/"
        )
        self.baseline_metadata_bucket = os.environ.get("S3_BUCKET", "your-s3-bucket")
        self.baseline_metadata_prefix = "jmeter-results-index/baselines/"

    def execute_query(self, query):
        """Execute Athena query and return results"""
        response = self.athena.start_query_execution(
            QueryString=query,
            QueryExecutionContext={"Database": self.database},
            ResultConfiguration={"OutputLocation": self.output_location},
        )

        query_id = response["QueryExecutionId"]

        # Wait for completion
        while True:
            result = self.athena.get_query_execution(QueryExecutionId=query_id)
            state = result["QueryExecution"]["Status"]["State"]

            if state == "SUCCEEDED":
                break
            elif state in ["FAILED", "CANCELLED"]:
                reason = result["QueryExecution"]["Status"].get(
                    "StateChangeReason", "Unknown"
                )
                raise Exception(f"Query {state}: {reason}")
            time.sleep(0.5)

        # Get results
        return self.athena.get_query_results(QueryExecutionId=query_id)

    def mark_baseline(
        self, engine, cluster_size, benchmark, run_type, run_id, user, notes=""
    ):
        """Mark a specific run as baseline"""

        print("=" * 80)
        print("Marking Run as Baseline")
        print("=" * 80)
        print(f"Engine:       {engine}")
        print(f"Cluster:      {cluster_size}")
        print(f"Benchmark:    {benchmark}")
        print(f"Run Type:     {run_type}")
        print(f"Run ID:       {run_id}")
        print(f"Marked By:    {user}")
        print(f"Notes:        {notes}")
        print("=" * 80)
        print()

        # Step 1: Verify run exists
        check_query = f"""
        SELECT run_id, avg_latency_sec, p50_latency_sec, p90_latency_sec, p95_latency_sec, p99_latency_sec
        FROM jmeter_runs_index
        WHERE engine = '{engine}'
          AND cluster_size = '{cluster_size}'
          AND benchmark = '{benchmark}'
          AND run_type = '{run_type}'
          AND run_id = '{run_id}'
        """

        print("Verifying run exists...")
        results = self.execute_query(check_query)

        if len(results["ResultSet"]["Rows"]) <= 1:
            print(f"❌ Error: Run {run_id} not found!")
            return False

        row = results["ResultSet"]["Rows"][1]
        data = [col.get("VarCharValue", "") for col in row["Data"]]
        print(
            f"✅ Found run: avg={data[1]}s, p50={data[2]}s, p90={data[3]}s, p95={data[4]}s, p99={data[5]}s"
        )
        print()

        # Step 2: Create baseline metadata file in S3
        baseline_key = (
            f"{self.baseline_metadata_prefix}"
            f"engine={engine}/"
            f"cluster_size={cluster_size}/"
            f"benchmark={benchmark}/"
            f"run_type={run_type}/"
            f"baseline_metadata.json"
        )

        metadata = {
            "run_id": run_id,
            "engine": engine,
            "cluster_size": cluster_size,
            "benchmark": benchmark,
            "run_type": run_type,
            "marked_by": user,
            "marked_date": datetime.now().isoformat(),
            "notes": notes,
            "metrics": {
                "avg_latency_sec": float(data[1]),
                "p50_latency_sec": float(data[2]),
                "p90_latency_sec": float(data[3]),
                "p95_latency_sec": float(data[4]),
                "p99_latency_sec": float(data[5]),
            },
        }

        print(f"Saving baseline metadata to S3...")
        self.s3.put_object(
            Bucket=self.baseline_metadata_bucket,
            Key=baseline_key,
            Body=json.dumps(metadata, indent=2),
            ContentType="application/json",
        )

        print(f"✅ Baseline marked successfully!")
        print()
        print(f"Metadata location: s3://{self.baseline_metadata_bucket}/{baseline_key}")
        print()

        # Step 3: Trigger Athena re-upload to sync baseline columns
        print("Syncing baseline to Athena table columns...")
        self._sync_to_athena(engine, cluster_size, benchmark, run_type)

        return True

    def _sync_to_athena(self, engine, cluster_size, benchmark, run_type):
        """Sync baseline metadata to Athena table by re-uploading runs index"""
        import subprocess
        import sys
        from pathlib import Path

        # Build S3 path for this configuration
        s3_bucket = os.environ.get("S3_BUCKET", "your-s3-bucket")
        s3_path = (
            f"s3://{s3_bucket}/jmeter-results/"
            f"engine={engine}/"
            f"cluster_size={cluster_size}/"
            f"benchmark={benchmark}/"
            f"run_type={run_type}/"
        )

        # Get path to upload script
        script_dir = Path(__file__).parent
        upload_script = script_dir / "upload_runs_index_to_athena.py"

        # Call upload script to regenerate Athena data with baseline columns
        cmd = [sys.executable, str(upload_script), "--from-s3", s3_path]

        try:
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            print("✅ Athena table updated with baseline columns")
            print()
        except subprocess.CalledProcessError as e:
            print(f"⚠️  Warning: Failed to sync to Athena: {e.stderr}")
            print("   Baseline metadata saved to S3, but Athena table not updated")
            print(
                "   Run manually: python utilities/athena/upload_runs_index_to_athena.py --from-s3 "
                + s3_path
            )
            print()

    def show_baselines(self, engine=None):
        """Show all current baselines"""

        print("=" * 80)
        print("Current Baselines")
        print("=" * 80)
        print()

        # List all baseline metadata files
        prefix = self.baseline_metadata_prefix
        if engine:
            prefix += f"engine={engine}/"

        response = self.s3.list_objects_v2(
            Bucket=self.baseline_metadata_bucket, Prefix=prefix
        )

        if "Contents" not in response:
            print("No baselines found.")
            return

        baselines = []
        for obj in response["Contents"]:
            if obj["Key"].endswith("baseline_metadata.json"):
                # Download and parse
                data = self.s3.get_object(
                    Bucket=self.baseline_metadata_bucket, Key=obj["Key"]
                )
                metadata = json.loads(data["Body"].read())
                baselines.append(metadata)

        if not baselines:
            print("No baselines found.")
            return

        # Display baselines
        print(
            f"{'Engine':<12} {'Cluster':<12} {'Run Type':<18} {'Run ID':<20} {'Avg (s)':<10} {'Marked By':<15}"
        )
        print("-" * 100)

        for b in baselines:
            print(
                f"{b['engine']:<12} {b['cluster_size']:<12} {b['run_type']:<18} "
                f"{b['run_id']:<20} {b['metrics']['avg_latency_sec']:<10.2f} {b.get('marked_by', 'N/A'):<15}"
            )

        print()

    def compare_with_baseline(
        self,
        engine,
        cluster_size,
        benchmark,
        run_type,
        run_id,
        source="s3",
        output_csv=None,
    ):
        """
        Compare a run with its baseline.

        Args:
            source: 's3' (read baseline from S3 metadata) or 'athena' (read from Athena columns)
            output_csv: Optional CSV file path to write results
        """
        if source == "athena":
            return self._compare_with_baseline_from_athena(
                engine, cluster_size, benchmark, run_type, run_id, output_csv
            )
        else:
            return self._compare_with_baseline_from_s3(
                engine, cluster_size, benchmark, run_type, run_id, output_csv
            )

    def _compare_with_baseline_from_s3(
        self, engine, cluster_size, benchmark, run_type, run_id, output_csv=None
    ):
        """Compare a run with baseline (baseline from S3, current run from Athena)"""

        print(f"📊 Data Source: Baseline from S3, Current run from Athena")
        print()

        # Load baseline metadata from S3
        baseline_key = (
            f"{self.baseline_metadata_prefix}"
            f"engine={engine}/"
            f"cluster_size={cluster_size}/"
            f"benchmark={benchmark}/"
            f"run_type={run_type}/"
            f"baseline_metadata.json"
        )

        try:
            data = self.s3.get_object(
                Bucket=self.baseline_metadata_bucket, Key=baseline_key
            )
            baseline = json.loads(data["Body"].read())
        except:
            print(f"❌ No baseline found for {engine}/{cluster_size}/{run_type}")
            print(f"   Use 'mark' command to set a baseline first.")
            return

        # Get current run metrics
        query = f"""
        SELECT run_id, avg_latency_sec, p50_latency_sec, p90_latency_sec, p95_latency_sec, p99_latency_sec
        FROM jmeter_runs_index
        WHERE engine = '{engine}'
          AND cluster_size = '{cluster_size}'
          AND benchmark = '{benchmark}'
          AND run_type = '{run_type}'
          AND run_id = '{run_id}'
        """

        results = self.execute_query(query)
        if len(results["ResultSet"]["Rows"]) <= 1:
            print(f"❌ Run {run_id} not found!")
            return

        row = results["ResultSet"]["Rows"][1]
        data = [col.get("VarCharValue", "") for col in row["Data"]]

        current_metrics = {
            "avg": float(data[1]),
            "p50": float(data[2]),
            "p90": float(data[3]),
            "p95": float(data[4]),
            "p99": float(data[5]),
        }

        # Compare
        print("=" * 80)
        print(f"Comparison: {run_id} vs Baseline {baseline['run_id']}")
        print("=" * 80)
        print()
        print(
            f"{'Metric':<15} {'Baseline':<15} {'Current':<15} {'Change':<15} {'Status':<10}"
        )
        print("-" * 80)

        metrics_to_compare = [
            ("Average", baseline["metrics"]["avg_latency_sec"], current_metrics["avg"]),
            ("p50", baseline["metrics"]["p50_latency_sec"], current_metrics["p50"]),
            ("p90", baseline["metrics"]["p90_latency_sec"], current_metrics["p90"]),
            ("p95", baseline["metrics"]["p95_latency_sec"], current_metrics["p95"]),
            ("p99", baseline["metrics"]["p99_latency_sec"], current_metrics["p99"]),
        ]

        better_count = 0
        worse_count = 0

        for metric_name, baseline_val, current_val in metrics_to_compare:
            change_pct = ((current_val - baseline_val) / baseline_val) * 100
            if change_pct < -2:
                status = "✅ Better"
                better_count += 1
            elif change_pct > 2:
                status = "⚠️ Worse"
                worse_count += 1
            else:
                status = "➖ Same"
            print(
                f"{metric_name:<15} {baseline_val:<15.2f} {current_val:<15.2f} {change_pct:>+13.1f}% {status:<10}"
            )

        print()
        print("-" * 80)
        if better_count >= 3 and worse_count == 0:
            print("🎉 Overall: SIGNIFICANT IMPROVEMENT - Consider updating baseline!")
            overall_status = "SIGNIFICANT_IMPROVEMENT"
        elif better_count > worse_count:
            print("✅ Overall: Improvement detected")
            overall_status = "IMPROVEMENT"
        elif better_count == worse_count:
            print("➖ Overall: Mixed results")
            overall_status = "MIXED"
        else:
            print("⚠️ Overall: Performance degradation detected")
            overall_status = "DEGRADATION"
        print()

        # Write CSV if requested
        if output_csv:
            self._write_comparison_csv(
                output_csv,
                engine,
                cluster_size,
                benchmark,
                run_type,
                baseline["run_id"],
                run_id,
                metrics_to_compare,
                overall_status,
                baseline.get("marked_by", "unknown"),
            )

    def _compare_with_baseline_from_athena(
        self, engine, cluster_size, benchmark, run_type, run_id, output_csv=None
    ):
        """Compare a run with baseline (both baseline and current run from Athena)"""

        print(f"📊 Data Source: Both baseline and current run from Athena")
        print()

        # Get baseline run from Athena
        baseline_query = f"""
        SELECT run_id, avg_latency_sec, p50_latency_sec, p90_latency_sec, p95_latency_sec, p99_latency_sec,
               baseline_marked_by, baseline_marked_date
        FROM jmeter_runs_index
        WHERE engine = '{engine}'
          AND cluster_size = '{cluster_size}'
          AND benchmark = '{benchmark}'
          AND run_type = '{run_type}'
          AND is_baseline = true
        """

        baseline_results = self.execute_query(baseline_query)
        if len(baseline_results["ResultSet"]["Rows"]) <= 1:
            print(f"❌ No baseline found for {engine}/{cluster_size}/{run_type}")
            print(f"   Use 'mark' command to set a baseline first.")
            return

        baseline_row = baseline_results["ResultSet"]["Rows"][1]
        baseline_data = [col.get("VarCharValue", "") for col in baseline_row["Data"]]

        baseline_metrics = {
            "run_id": baseline_data[0],
            "avg": float(baseline_data[1]),
            "p50": float(baseline_data[2]),
            "p90": float(baseline_data[3]),
            "p95": float(baseline_data[4]),
            "p99": float(baseline_data[5]),
            "marked_by": baseline_data[6] if baseline_data[6] else "unknown",
            "marked_date": baseline_data[7] if baseline_data[7] else "unknown",
        }

        # Get current run from Athena
        current_query = f"""
        SELECT run_id, avg_latency_sec, p50_latency_sec, p90_latency_sec, p95_latency_sec, p99_latency_sec
        FROM jmeter_runs_index
        WHERE engine = '{engine}'
          AND cluster_size = '{cluster_size}'
          AND benchmark = '{benchmark}'
          AND run_type = '{run_type}'
          AND run_id = '{run_id}'
        """

        current_results = self.execute_query(current_query)
        if len(current_results["ResultSet"]["Rows"]) <= 1:
            print(f"❌ Run {run_id} not found!")
            return

        current_row = current_results["ResultSet"]["Rows"][1]
        current_data = [col.get("VarCharValue", "") for col in current_row["Data"]]

        current_metrics = {
            "avg": float(current_data[1]),
            "p50": float(current_data[2]),
            "p90": float(current_data[3]),
            "p95": float(current_data[4]),
            "p99": float(current_data[5]),
        }

        # Compare
        print("=" * 80)
        print(f"Comparison: {run_id} vs Baseline {baseline_metrics['run_id']}")
        print("=" * 80)
        print()
        print(
            f"{'Metric':<15} {'Baseline':<15} {'Current':<15} {'Change':<15} {'Status':<10}"
        )
        print("-" * 80)

        metrics_to_compare = [
            ("Average", baseline_metrics["avg"], current_metrics["avg"]),
            ("p50", baseline_metrics["p50"], current_metrics["p50"]),
            ("p90", baseline_metrics["p90"], current_metrics["p90"]),
            ("p95", baseline_metrics["p95"], current_metrics["p95"]),
            ("p99", baseline_metrics["p99"], current_metrics["p99"]),
        ]

        better_count = 0
        worse_count = 0

        for metric_name, baseline_val, current_val in metrics_to_compare:
            change_pct = ((current_val - baseline_val) / baseline_val) * 100
            if change_pct < -2:
                status = "✅ Better"
                better_count += 1
            elif change_pct > 2:
                status = "⚠️ Worse"
                worse_count += 1
            else:
                status = "➖ Same"
            print(
                f"{metric_name:<15} {baseline_val:<15.2f} {current_val:<15.2f} {change_pct:>+13.1f}% {status:<10}"
            )

        print()
        print("-" * 80)
        if better_count >= 3 and worse_count == 0:
            print("🎉 Overall: SIGNIFICANT IMPROVEMENT - Consider updating baseline!")
            overall_status = "SIGNIFICANT_IMPROVEMENT"
        elif better_count > worse_count:
            print("✅ Overall: Improvement detected")
            overall_status = "IMPROVEMENT"
        elif better_count == worse_count:
            print("➖ Overall: Mixed results")
            overall_status = "MIXED"
        else:
            print("⚠️ Overall: Performance degradation detected")
            overall_status = "DEGRADATION"
        print()

        # Write CSV if requested
        if output_csv:
            self._write_comparison_csv(
                output_csv,
                engine,
                cluster_size,
                benchmark,
                run_type,
                baseline_metrics["run_id"],
                run_id,
                metrics_to_compare,
                overall_status,
                baseline_metrics.get("marked_by", "unknown"),
            )

    def _write_comparison_csv(
        self,
        csv_path,
        engine,
        cluster_size,
        benchmark,
        run_type,
        baseline_run_id,
        current_run_id,
        metrics,
        overall_status,
        marked_by,
    ):
        """Write comparison results to CSV file"""
        import csv
        from pathlib import Path

        # Check if file exists to determine if we need header
        file_exists = Path(csv_path).exists()

        with open(csv_path, "a", newline="") as f:
            writer = csv.writer(f)

            # Write header if new file
            if not file_exists:
                writer.writerow(
                    [
                        "timestamp",
                        "engine",
                        "cluster_size",
                        "benchmark",
                        "run_type",
                        "baseline_run_id",
                        "current_run_id",
                        "baseline_marked_by",
                        "metric",
                        "baseline_value",
                        "current_value",
                        "change_pct",
                        "status",
                        "overall_status",
                    ]
                )

            # Write data rows (one per metric)
            timestamp = datetime.now().isoformat()
            for metric_name, baseline_val, current_val in metrics:
                change_pct = ((current_val - baseline_val) / baseline_val) * 100

                if change_pct < -2:
                    metric_status = "BETTER"
                elif change_pct > 2:
                    metric_status = "WORSE"
                else:
                    metric_status = "SAME"

                writer.writerow(
                    [
                        timestamp,
                        engine,
                        cluster_size,
                        benchmark,
                        run_type,
                        baseline_run_id,
                        current_run_id,
                        marked_by,
                        metric_name,
                        f"{baseline_val:.2f}",
                        f"{current_val:.2f}",
                        f"{change_pct:.1f}",
                        metric_status,
                        overall_status,
                    ]
                )

        print(f"📊 CSV results appended to: {csv_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Manage baseline runs")
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # Mark command
    mark_parser = subparsers.add_parser("mark", help="Mark a run as baseline")
    mark_parser.add_argument("--engine", required=True)
    mark_parser.add_argument("--cluster", required=True)
    mark_parser.add_argument("--benchmark", required=True)
    mark_parser.add_argument("--run-type", required=True)
    mark_parser.add_argument("--run-id", required=True)
    mark_parser.add_argument("--user", required=True)
    mark_parser.add_argument("--notes", default="")

    # Show command
    show_parser = subparsers.add_parser("show", help="Show current baselines")
    show_parser.add_argument("--engine", help="Filter by engine")

    # Compare command
    compare_parser = subparsers.add_parser("compare", help="Compare run with baseline")
    compare_parser.add_argument("--engine", required=True)
    compare_parser.add_argument("--cluster", required=True)
    compare_parser.add_argument("--benchmark", required=True)
    compare_parser.add_argument("--run-type", required=True)
    compare_parser.add_argument("--run-id", required=True)
    compare_parser.add_argument(
        "--source",
        choices=["s3", "athena"],
        default="s3",
        help='Data source: "s3" (baseline from S3, current from Athena) or "athena" (both from Athena)',
    )
    compare_parser.add_argument(
        "--output-csv",
        help="Optional CSV file path to append results for historical analysis",
    )

    args = parser.parse_args()

    manager = BaselineManager()

    if args.command == "mark":
        manager.mark_baseline(
            args.engine,
            args.cluster,
            args.benchmark,
            args.run_type,
            args.run_id,
            args.user,
            args.notes,
        )
    elif args.command == "show":
        manager.show_baselines(args.engine)
    elif args.command == "compare":
        manager.compare_with_baseline(
            args.engine,
            args.cluster,
            args.benchmark,
            args.run_type,
            args.run_id,
            args.source,
            args.output_csv if hasattr(args, "output_csv") else None,
        )
    else:
        parser.print_help()
