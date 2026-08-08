#!/usr/bin/env python3
"""
Capture a standard report for a completed run.

Usage:
    capture_run_report.py <run_dir> [--profile <load_profile.csv>] [--meta k=v ...]

Writes two files into <run_dir>:

    run_summary.json   machine-readable metrics (feeds Athena / comparison scripts)
    run_report.md      human-readable summary

Both are derived from JmeterResultFile.csv only, so they work for any engine the
framework can drive. Called automatically by run_jmeter_tests_interactive.sh and
run_test.sh after JMeter exits, so every run is self-describing without anyone
remembering to run the analysis by hand.

Metric definitions (stated so numbers are reproducible):
  arrival     sample timeStamp            (JMeter records query START)
  completion  timeStamp + elapsed
  in-flight   arrivals - completions so far, at 1-second resolution
  percentiles nearest-rank over successful samples
"""

import argparse
import csv
import json
import math
import os
import statistics
import sys


def load(run_dir):
    path = os.path.join(run_dir, "JmeterResultFile.csv")
    if not os.path.exists(path):
        raise SystemExit(f"{path}: not found")
    rows = list(csv.DictReader(open(path)))
    if not rows:
        raise SystemExit(f"{path}: no samples")
    return rows


def read_profile(path):
    rows = []
    for parts in csv.reader(open(path, newline="")):
        if not parts or not any(p.strip() for p in parts):
            continue
        if parts[0].strip().lower().startswith("startvalue"):
            continue
        rows.append(tuple(int(p.strip()) for p in parts[:3]))
    return rows


def expected_per_second(steps):
    out = []
    for start, end, dur in steps:
        for i in range(dur):
            out.append(round(start if dur == 1 else start + (end - start) * i / (dur - 1)))
    return out


def analyse(rows, profile_steps=None):
    ok = [r for r in rows if r["success"] == "true"]
    lat = sorted(int(r["elapsed"]) for r in ok)
    starts = [int(r["timeStamp"]) for r in rows]
    ends = [int(r["timeStamp"]) + int(r["elapsed"]) for r in rows]
    t0, tend = min(starts), max(ends)
    wall = (tend - t0) / 1000
    arrival_window = (max(starts) - t0) / 1000

    n = int(wall) + 2
    arr = [0] * n
    comp = [0] * n
    for s, e in zip(starts, ends):
        arr[(s - t0) // 1000] += 1
        comp[(e - t0) // 1000] += 1
    inflight, running = [], 0
    for a, c in zip(arr, comp):
        running += a - c
        inflight.append(running)

    def p(q):
        return lat[math.ceil(q * len(lat)) - 1] if lat else None

    out = {
        "samples": len(rows),
        "successful": len(ok),
        "failed": len(rows) - len(ok),
        "error_pct": round(100 * (len(rows) - len(ok)) / len(rows), 2),
        "throughput_per_s": round(len(rows) / wall, 2) if wall else None,
        "wall_clock_s": round(wall, 1),
        "arrival_window_s": round(arrival_window, 1),
        "drain_s": round(wall - arrival_window, 1),
        "peak_in_flight": max(inflight),
        "peak_at_s": inflight.index(max(inflight)),
        "latency_ms": {
            "min": lat[0] if lat else None,
            "p50": p(0.50), "p90": p(0.90), "p95": p(0.95), "p99": p(0.99),
            "max": lat[-1] if lat else None,
            "mean": round(statistics.mean(lat)) if lat else None,
        },
        "arrivals_per_s": arr,
        "in_flight_per_s": inflight,
    }

    if profile_steps:
        exp = expected_per_second(profile_steps)
        delivered = sum(arr[: len(exp)])
        out["load_profile"] = {
            "window_s": len(exp),
            "expected": sum(exp),
            "delivered": delivered,
            "delivered_pct": round(100 * delivered / sum(exp), 1) if sum(exp) else None,
            "arrivals_after_window": sum(arr[len(exp):]),
            "expected_per_s": exp,
        }

    if out["failed"]:
        msgs = {}
        for r in rows:
            if r["success"] != "true":
                k = r["responseMessage"][:160]
                msgs[k] = msgs.get(k, 0) + 1
        out["failure_messages"] = sorted(
            ({"count": v, "message": k} for k, v in msgs.items()),
            key=lambda x: -x["count"],
        )[:5]
    return out


def markdown(run_id, s, meta):
    L = [f"# Run report — {run_id}", ""]
    for k, v in meta.items():
        L.append(f"**{k}:** {v}  ")
    L += ["", "## Result", "",
          "| | |", "|---|---|",
          f"| Samples | {s['samples']} |",
          f"| Errors | {s['failed']} ({s['error_pct']}%) |",
          f"| Throughput | {s['throughput_per_s']} /s |",
          f"| Wall clock | {s['wall_clock_s']} s |",
          f"| Arrival window | {s['arrival_window_s']} s |",
          f"| Drain after last arrival | {s['drain_s']} s |",
          f"| Peak in flight | {s['peak_in_flight']} (at t={s['peak_at_s']} s) |",
          ""]
    lt = s["latency_ms"]
    L += ["## Latency (ms)", "",
          "| min | p50 | p90 | p95 | p99 | max | mean |", "|---|---|---|---|---|---|---|",
          f"| {lt['min']} | {lt['p50']} | {lt['p90']} | {lt['p95']} | {lt['p99']} | {lt['max']} | {lt['mean']} |",
          "", "_Percentiles are nearest-rank over successful samples._", ""]

    if "load_profile" in s:
        lp = s["load_profile"]
        verdict = "OK" if lp["delivered_pct"] and lp["delivered_pct"] >= 95 else "SHORTFALL — raise MAX_CONCURRANCY"
        L += ["## Load profile", "",
              f"| window | expected | delivered | after window |", "|---|---|---|---|",
              f"| {lp['window_s']} s | {lp['expected']} | {lp['delivered']} ({lp['delivered_pct']}%) | {lp['arrivals_after_window']} |",
              "", f"**{verdict}**", ""]
        if lp["arrivals_after_window"]:
            L += ["> Arrivals after the profile window mean the schedule was not applied.", ""]

    L += ["## Queue build-up", "", "| t (s) | arrivals | in flight |", "|---|---|---|"]
    step = max(1, len(s["in_flight_per_s"]) // 20)
    for i in range(0, len(s["in_flight_per_s"]), step):
        L.append(f"| {i} | {s['arrivals_per_s'][i]} | {s['in_flight_per_s'][i]} |")
    L.append("")

    if "failure_messages" in s:
        L += ["## Failures", ""]
        for f in s["failure_messages"]:
            L.append(f"- **{f['count']}x** `{f['message']}`")
        L.append("")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--profile")
    ap.add_argument("--meta", action="append", default=[])
    a = ap.parse_args()

    rows = load(a.run_dir)
    steps = read_profile(a.profile) if a.profile and os.path.exists(a.profile) else None
    s = analyse(rows, steps)

    meta = {}
    for kv in a.meta:
        if "=" in kv:
            k, v = kv.split("=", 1)
            meta[k] = v
    s["meta"] = meta

    run_id = os.path.basename(os.path.normpath(a.run_dir))
    with open(os.path.join(a.run_dir, "run_summary.json"), "w") as fh:
        json.dump(s, fh, indent=2)
    with open(os.path.join(a.run_dir, "run_report.md"), "w") as fh:
        fh.write(markdown(run_id, s, meta))

    warn = ""
    if "load_profile" in s and s["load_profile"]["delivered_pct"] < 95:
        warn = f"  [!] only {s['load_profile']['delivered_pct']}% of profile arrivals delivered"
    print(f"  run report: {s['samples']} samples, {s['error_pct']}% errors, "
          f"{s['throughput_per_s']}/s, peak {s['peak_in_flight']} in flight{warn}")


if __name__ == "__main__":
    main()
