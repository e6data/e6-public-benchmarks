#!/usr/bin/env python3
"""Export e6 Query History for a completed JMeter result window."""

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode


def jmeter_window(path, padding_seconds):
    minimum = None
    maximum = None
    with open(path, newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            try:
                started = int(row["timeStamp"])
                elapsed = int(row.get("elapsed") or 0)
            except (KeyError, TypeError, ValueError):
                continue
            ended = started + max(0, elapsed)
            minimum = started if minimum is None else min(minimum, started)
            maximum = ended if maximum is None else max(maximum, ended)
    if minimum is None or maximum is None:
        raise ValueError("JMeter result CSV contains no timestamped samples")
    padding = max(0, padding_seconds) * 1000
    return minimum - padding, maximum + padding


def iso_utc(epoch_ms):
    value = datetime.fromtimestamp(epoch_ms / 1000.0, tz=timezone.utc)
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def curl_bytes(url, method="GET", headers=None, data=None, basic_auth=None, timeout=60):
    """Call curl without putting credentials or bearer tokens in argv."""
    def quote(value):
        value = str(value)
        if "\n" in value or "\r" in value:
            raise ValueError("HTTP values must not contain newlines")
        return value.replace("\\", "\\\\").replace('"', '\\"')

    config = [
        "silent",
        "show-error",
        "fail-with-body",
        "request = {}".format(method),
        "max-time = {}".format(timeout),
    ]
    for key, value in (headers or {}).items():
        config.append('header = "{}: {}"'.format(quote(key), quote(value)))
    if basic_auth is not None:
        user, password = basic_auth
        credentials = quote("{}:{}".format(user, password))
        config.append('user = "{}"'.format(credentials))
    if data is not None:
        encoded = data.decode("utf-8") if isinstance(data, bytes) else str(data)
        config.append('data = "{}"'.format(quote(encoded)))
    config.append('url = "{}"'.format(quote(url)))
    try:
        result = subprocess.run(
            ["curl", "--config", "-"],
            input=("\n".join(config) + "\n").encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=timeout + 5,
        )
    except FileNotFoundError as error:
        raise RuntimeError("curl is required for e6 Query History capture") from error
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("Timed out calling {}".format(url)) from error
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        body = result.stdout.decode("utf-8", errors="replace")[:1000]
        raise RuntimeError("curl failed for {}: {} {}".format(url, detail, body).strip())
    return result.stdout


def access_token(base_url, client_id, client_secret, timeout):
    payload = urlencode({"grant_type": "client_credentials"}).encode("utf-8")
    body = curl_bytes(
        base_url.rstrip("/") + "/oauth2/token",
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data=payload,
        basic_auth=(client_id, client_secret),
        timeout=timeout,
    )
    token = json.loads(body.decode("utf-8")).get("access_token")
    if not token:
        raise RuntimeError("OAuth token response did not contain access_token")
    return token


def export_history(base_url, token, start, end, cluster, email, output, timeout):
    filters = {}
    if cluster:
        filters["cluster_name"] = [cluster]
    if email:
        filters["email"] = [email]
    query = urlencode({
        "start": start,
        "end": end,
        "sort_by": "timestamp",
        "sort_order": "desc",
        "filters": json.dumps(filters, separators=(",", ":")),
    })
    body = curl_bytes(
        base_url.rstrip("/") + "/api/v1/query-history/export?" + query,
        headers={"Authorization": "Bearer " + token},
        timeout=timeout,
    )
    output.write_bytes(body)
    with output.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle)
        columns = next(reader, [])
        rows = sum(1 for _ in reader)
    return rows, columns


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True, help="e6 workspace URL")
    parser.add_argument("--jmeter-results", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--status-output", type=Path)
    parser.add_argument("--cluster")
    parser.add_argument("--email")
    parser.add_argument("--client-id", default=os.environ.get("E6_MACHINE_CLIENT_ID"))
    parser.add_argument("--client-secret", default=os.environ.get("E6_MACHINE_CLIENT_SECRET"))
    parser.add_argument("--padding-seconds", type=int, default=5)
    parser.add_argument("--wait-seconds", type=int, default=0)
    parser.add_argument("--timeout", type=int, default=90)
    return parser


def main():
    args = build_parser().parse_args()
    status_path = args.status_output or args.output.with_name("e6_query_history_capture.json")
    capture = {
        "status": "failed",
        "output": str(args.output),
        "cluster": args.cluster or "",
        "email": args.email or "",
    }
    try:
        if not args.client_id or not args.client_secret:
            raise ValueError("E6_MACHINE_CLIENT_ID and E6_MACHINE_CLIENT_SECRET are required")
        start_ms, end_ms = jmeter_window(args.jmeter_results, args.padding_seconds)
        capture.update({"start": iso_utc(start_ms), "end": iso_utc(end_ms)})
        if args.wait_seconds > 0:
            time.sleep(args.wait_seconds)
        token = access_token(args.base_url, args.client_id, args.client_secret, args.timeout)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        rows, columns = export_history(
            args.base_url, token, capture["start"], capture["end"],
            args.cluster, args.email, args.output, args.timeout,
        )
        capture.update({
            "status": "captured",
            "rows": rows,
            "columns": columns,
            "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        })
    except Exception as error:
        capture["error"] = str(error)
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(json.dumps(capture, indent=2) + "\n", encoding="utf-8")
    if capture["status"] != "captured":
        print("e6 Query History capture failed: {}".format(capture.get("error", "unknown error")), file=sys.stderr)
        return 1
    print("Captured {} e6 Query History row(s) to {}".format(capture["rows"], args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
