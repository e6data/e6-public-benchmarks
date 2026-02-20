#!/usr/bin/env python3
"""
Verify baseline sync between S3 metadata and Athena table columns.

This script queries both sources and confirms they return identical baseline information.

Usage:
    # Verify specific configuration
    python utilities/athena/verify_baseline_sync.py \
        --engine e6data --cluster S-2x2 --benchmark tpcds_29_1tb --run-type concurrency_4

    # Verify all baselines for an engine
    python utilities/athena/verify_baseline_sync.py --engine e6data --verify-all
"""

import argparse
import json
import os
import time
from typing import Dict, Optional

import boto3


class BaselineSyncVerifier:
    def __init__(self, region="us-east-1"):
        self.athena = boto3.client("athena", region_name=region)
        self.s3 = boto3.client("s3", region_name=region)
        self.database = "jmeter_analysis"
        self.output_location = os.environ.get(
            "ATHENA_OUTPUT_LOCATION", "s3://your-s3-bucket/athena-query-results/"
        )
        self.baseline_bucket = os.environ.get("S3_BUCKET", "your-s3-bucket")
        self.baseline_prefix = "jmeter-results-index/baselines/"

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

    def get_baseline_from_s3(
        self, engine, cluster_size, benchmark, run_type
    ) -> Optional[Dict]:
        """Get baseline from S3 metadata file"""
        key = (
            f"{self.baseline_prefix}"
            f"engine={engine}/"
            f"cluster_size={cluster_size}/"
            f"benchmark={benchmark}/"
            f"run_type={run_type}/"
            f"baseline_metadata.json"
        )

        try:
            response = self.s3.get_object(Bucket=self.baseline_bucket, Key=key)
            return json.loads(response["Body"].read())
        except:
            return None

    def get_baseline_from_athena(
        self, engine, cluster_size, benchmark, run_type
    ) -> Optional[Dict]:
        """Get baseline from Athena table"""
        query = f"""
        SELECT
            run_id,
            is_baseline,
            baseline_marked_by,
            baseline_marked_date,
            baseline_notes,
            avg_latency_sec,
            p50_latency_sec,
            p90_latency_sec,
            p95_latency_sec,
            p99_latency_sec
        FROM jmeter_runs_index
        WHERE engine = '{engine}'
          AND cluster_size = '{cluster_size}'
          AND benchmark = '{benchmark}'
          AND run_type = '{run_type}'
          AND is_baseline = true
        """

        results = self.execute_query(query)

        if len(results["ResultSet"]["Rows"]) <= 1:
            return None

        row = results["ResultSet"]["Rows"][1]
        data = [col.get("VarCharValue", "") for col in row["Data"]]

        return {
            "run_id": data[0],
            "is_baseline": data[1] == "true",
            "baseline_marked_by": data[2] if data[2] else None,
            "baseline_marked_date": data[3] if data[3] else None,
            "baseline_notes": data[4] if data[4] else None,
            "metrics": {
                "avg_latency_sec": float(data[5]) if data[5] else None,
                "p50_latency_sec": float(data[6]) if data[6] else None,
                "p90_latency_sec": float(data[7]) if data[7] else None,
                "p95_latency_sec": float(data[8]) if data[8] else None,
                "p99_latency_sec": float(data[9]) if data[9] else None,
            },
        }

    def verify_config(self, engine, cluster_size, benchmark, run_type):
        """Verify baseline sync for a specific configuration"""
        print("=" * 80)
        print(f"Verifying Baseline Sync")
        print("=" * 80)
        print(f"Engine:       {engine}")
        print(f"Cluster:      {cluster_size}")
        print(f"Benchmark:    {benchmark}")
        print(f"Run Type:     {run_type}")
        print("=" * 80)
        print()

        # Get from both sources
        s3_baseline = self.get_baseline_from_s3(
            engine, cluster_size, benchmark, run_type
        )
        athena_baseline = self.get_baseline_from_athena(
            engine, cluster_size, benchmark, run_type
        )

        # Check if both exist or both don't exist
        if s3_baseline is None and athena_baseline is None:
            print("✅ SYNC OK: No baseline set in either S3 or Athena")
            print()
            return True

        if s3_baseline is None:
            print("❌ SYNC ERROR: Baseline exists in Athena but not in S3!")
            print(f"   Athena shows: {athena_baseline['run_id']}")
            print()
            return False

        if athena_baseline is None:
            print("❌ SYNC ERROR: Baseline exists in S3 but not in Athena!")
            print(f"   S3 shows: {s3_baseline['run_id']}")
            print("   Action: Re-run upload_runs_index_to_athena.py to sync")
            print()
            return False

        # Compare run_id
        if s3_baseline["run_id"] != athena_baseline["run_id"]:
            print("❌ SYNC ERROR: Different run_id in S3 vs Athena!")
            print(f"   S3 shows:     {s3_baseline['run_id']}")
            print(f"   Athena shows: {athena_baseline['run_id']}")
            print()
            return False

        # Compare metadata
        s3_marked_by = s3_baseline.get("marked_by")
        athena_marked_by = athena_baseline.get("baseline_marked_by")

        if s3_marked_by != athena_marked_by:
            print("⚠️  SYNC WARNING: Different marked_by values")
            print(f"   S3:     {s3_marked_by}")
            print(f"   Athena: {athena_marked_by}")

        # Success
        print(f"✅ SYNC OK: Both sources show run_id = {s3_baseline['run_id']}")
        print()
        print("S3 Metadata:")
        print(f"  Marked By:    {s3_baseline.get('marked_by', 'N/A')}")
        print(f"  Marked Date:  {s3_baseline.get('marked_date', 'N/A')}")
        print(f"  Notes:        {s3_baseline.get('notes', 'N/A')}")
        print(f"  Avg Latency:  {s3_baseline['metrics']['avg_latency_sec']:.2f}s")
        print()
        print("Athena Columns:")
        print(f"  Marked By:    {athena_baseline.get('baseline_marked_by', 'N/A')}")
        print(f"  Marked Date:  {athena_baseline.get('baseline_marked_date', 'N/A')}")
        print(f"  Notes:        {athena_baseline.get('baseline_notes', 'N/A')}")
        print(f"  Avg Latency:  {athena_baseline['metrics']['avg_latency_sec']:.2f}s")
        print()

        return True

    def verify_all_for_engine(self, engine):
        """Verify all baselines for an engine"""
        print("=" * 80)
        print(f"Verifying All Baselines for Engine: {engine}")
        print("=" * 80)
        print()

        # List all S3 baseline metadata files for this engine
        prefix = f"{self.baseline_prefix}engine={engine}/"
        response = self.s3.list_objects_v2(Bucket=self.baseline_bucket, Prefix=prefix)

        if "Contents" not in response:
            print("No baselines found in S3")
            return

        configs = []
        for obj in response["Contents"]:
            if obj["Key"].endswith("baseline_metadata.json"):
                # Parse path to extract config
                parts = obj["Key"].split("/")
                config = {}
                for part in parts:
                    if "=" in part:
                        key, val = part.split("=", 1)
                        config[key] = val
                configs.append(config)

        if not configs:
            print("No baselines found in S3")
            return

        print(f"Found {len(configs)} baseline configuration(s) in S3")
        print()

        all_synced = True
        for config in configs:
            result = self.verify_config(
                config["engine"],
                config["cluster_size"],
                config["benchmark"],
                config["run_type"],
            )
            if not result:
                all_synced = False

        print("=" * 80)
        if all_synced:
            print("✅ All baselines are synced between S3 and Athena!")
        else:
            print("❌ Some baselines are out of sync. Re-run upload script to fix.")
        print("=" * 80)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Verify baseline sync between S3 and Athena"
    )

    parser.add_argument("--engine", required=True, help="Engine name (e.g., e6data)")
    parser.add_argument("--cluster", help="Cluster size (e.g., S-2x2)")
    parser.add_argument("--benchmark", help="Benchmark name (e.g., tpcds_29_1tb)")
    parser.add_argument("--run-type", help="Run type (e.g., concurrency_4)")
    parser.add_argument(
        "--verify-all", action="store_true", help="Verify all baselines for the engine"
    )

    args = parser.parse_args()

    verifier = BaselineSyncVerifier()

    if args.verify_all:
        verifier.verify_all_for_engine(args.engine)
    elif args.cluster and args.benchmark and args.run_type:
        verifier.verify_config(args.engine, args.cluster, args.benchmark, args.run_type)
    else:
        parser.print_help()
        print()
        print(
            "Error: Either provide --verify-all or all of: --cluster, --benchmark, --run-type"
        )
