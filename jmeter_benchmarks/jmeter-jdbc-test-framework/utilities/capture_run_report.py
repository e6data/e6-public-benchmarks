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

from load_profile import (
    expected_arrivals_per_second,
    expected_concurrency_per_second,
    read_profile,
)


# Exit code meaning "JMeter ran, but the run is not usable as a result".
# Distinct from 1 (this script itself failed) so callers can tell them apart.
EXIT_FAILED_RUN = 2

# Infrastructure samplers may be written to the same JTL as query samplers.
# They are useful in the raw file but must not affect query latency, throughput,
# or error thresholds.
CONTROL_SAMPLE_LABELS = {"Setup-Query-Loader-Trigger"}


def load(run_dir):
    path = os.path.join(run_dir, "JmeterResultFile.csv")
    if not os.path.exists(path):
        # No results file at all: JMeter never got far enough to record a sample.
        # This is a failed run, not a reporting glitch, so it must not exit 0.
        print(f"  [FAIL] {path}: not found - no samples were recorded")
        raise SystemExit(EXIT_FAILED_RUN)
    raw_rows = list(csv.DictReader(open(path)))
    rows = [row for row in raw_rows if row.get("label") not in CONTROL_SAMPLE_LABELS]
    if not rows:
        print(f"  [FAIL] {path}: no samples - nothing executed")
        raise SystemExit(EXIT_FAILED_RUN)
    return rows, len(raw_rows), len(raw_rows) - len(rows)


def peak_inflight_per_second(starts, ends, t0, buckets):
    """Return peak interval overlap in each second.

    Counting only arrivals minus completions at the end of a one-second bucket
    reports zero for every query that starts and finishes within that bucket.
    An event sweep preserves those short-lived queries and measures actual
    query-in-flight concurrency rather than a bucket-end backlog snapshot.
    """
    events = {}
    for start, end in zip(starts, ends):
        events[start] = events.get(start, 0) + 1
        events[end] = events.get(end, 0) - 1
    ordered = sorted(events.items())
    result = []
    active = 0
    position = 0
    for bucket in range(buckets):
        bucket_end = t0 + (bucket + 1) * 1000
        peak = active
        while position < len(ordered) and ordered[position][0] < bucket_end:
            active += ordered[position][1]
            peak = max(peak, active)
            position += 1
        result.append(peak)
    return result


def analyse(rows, profile_steps=None, profile_kind="arrivals"):
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
    inflight = peak_inflight_per_second(starts, ends, t0, n)

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

    if profile_steps and profile_kind == "arrivals":
        exp = expected_arrivals_per_second(profile_steps)
        delivered = sum(arr[: len(exp)])
        out["load_profile"] = {
            "kind": "arrivals",
            "window_s": len(exp),
            "expected": sum(exp),
            "delivered": delivered,
            "delivered_pct": round(100 * delivered / sum(exp), 1) if sum(exp) else None,
            "arrivals_after_window": sum(arr[len(exp):]),
            "expected_per_s": exp,
        }
    elif profile_steps and profile_kind == "concurrency":
        exp = expected_concurrency_per_second(profile_steps)
        # Compare second by second, not on peak. At a wave boundary threads from
        # the outgoing wave finish their in-flight query while the incoming wave
        # starts, so peak in-flight briefly exceeds the profile by design - a
        # peak-based check would flag a correct run. Only the seconds the profile
        # actually asks for load are compared; the tail is drain.
        # Tolerance is the looser of 2 threads or 20%. A fixed +-1 flags correct
        # runs: during a 30s ramp to 20 threads, JMeter starts threads on its own
        # discrete schedule while this model ramps linearly, so the two disagree
        # by 2-3 threads mid-ramp even though the plateau is exact. Calibrated so
        # a run against the wrong profile still scores ~14% against ~95% for a
        # correct one.
        overlap = min(len(exp), len(inflight))
        tol = [max(2.0, 0.20 * exp[i]) for i in range(overlap)]
        matched = sum(1 for i in range(overlap)
                      if abs(inflight[i] - exp[i]) <= tol[i])
        drift = [inflight[i] - exp[i] for i in range(overlap)]
        out["load_profile"] = {
            "kind": "concurrency",
            "window_s": len(exp) - 1,
            "compared_s": overlap,
            "matched_s": matched,
            "matched_pct": round(100 * matched / overlap, 1) if overlap else None,
            "max_overshoot": round(max(drift), 1) if drift else None,
            "max_shortfall": round(min(drift), 1) if drift else None,
            "expected_peak": round(max(exp), 1),
            "observed_peak": max(inflight),
            "expected_levels": sorted({round(v) for v in exp if v > 0}),
            "expected_per_s": [round(v, 2) for v in exp],
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
    if s.get("ignored_control_samples"):
        L += [f"_Excluded {s['ignored_control_samples']} framework control sample(s) "
              f"from {s['raw_samples']} raw samples._", ""]
    lt = s["latency_ms"]
    if lt["min"] is None:
        L += ["## Latency", "",
              "_No successful samples — every query failed, so there are no latencies to report._",
              ""]
    else:
        L += ["## Latency (ms)", "",
              "| min | p50 | p90 | p95 | p99 | max | mean |", "|---|---|---|---|---|---|---|",
              f"| {lt['min']} | {lt['p50']} | {lt['p90']} | {lt['p95']} | {lt['p99']} | {lt['max']} | {lt['mean']} |",
              "", "_Percentiles are nearest-rank over successful samples._", ""]

    if s.get("load_profile", {}).get("kind") == "arrivals":
        lp = s["load_profile"]
        verdict = "OK" if lp["delivered_pct"] and lp["delivered_pct"] >= 95 else "SHORTFALL — raise MAX_CONCURRANCY"
        L += ["## Load profile — arrival rate", "",
              "| window | expected | delivered | after window |", "|---|---|---|---|",
              f"| {lp['window_s']} s | {lp['expected']} | {lp['delivered']} ({lp['delivered_pct']}%) | {lp['arrivals_after_window']} |",
              "", f"**{verdict}**", ""]
        if lp["arrivals_after_window"]:
            L += ["> Arrivals after the profile window mean the schedule was not applied.", ""]

    elif s.get("load_profile", {}).get("kind") == "concurrency":
        lp = s["load_profile"]
        pct = lp["matched_pct"]
        if pct is None:
            verdict = "nothing to compare against"
        elif pct >= 90:
            verdict = "OK — observed concurrency tracks the profile"
        elif lp["max_shortfall"] < -1:
            verdict = ("SHORTFALL — fewer threads in flight than requested; "
                       "threads were idle between queries, or the schedule "
                       "was not applied")
        else:
            verdict = ("MISMATCH — in-flight concurrency does not follow the "
                       "profile; check the schedule was applied")
        L += ["## Load profile — concurrency", "",
              "| window | seconds matched | drift | expected peak | observed peak | levels |",
              "|---|---|---|---|---|---|",
              f"| {lp['window_s']} s | {lp['matched_s']}/{lp['compared_s']} ({pct}%) "
              f"| {lp['max_shortfall']:+g} … {lp['max_overshoot']:+g} "
              f"| {lp['expected_peak']} | {lp['observed_peak']} | {lp['expected_levels']} |",
              "", f"**{verdict}**", "",
              "> Matched = seconds where in-flight is within the looser of 2 threads "
              "or 20% of the profile. In-flight is sampled at 1-second resolution "
              "and a thread finishes its current query before stopping, so brief "
              "drift during a ramp or at a wave boundary is expected, not a fault.", ""]

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
    ap.add_argument(
        "--max-error-pct", type=float,
        default=float(os.environ.get("MAX_ERROR_PCT", "5")),
        help="exit %d if the error rate exceeds this (default 5, or $MAX_ERROR_PCT)"
             % EXIT_FAILED_RUN)
    a = ap.parse_args()

    rows, raw_samples, ignored_control_samples = load(a.run_dir)
    try:
        kind, steps = (read_profile(a.profile)
                       if a.profile and os.path.exists(a.profile) else (None, None))
    except ValueError as exc:
        print(f"  [FAIL] invalid load profile: {exc}")
        raise SystemExit(1) from exc
    s = analyse(rows, steps, kind)
    s["raw_samples"] = raw_samples
    s["query_samples"] = len(rows)
    s["ignored_control_samples"] = ignored_control_samples

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
    lp = s.get("load_profile")
    if lp and lp["kind"] == "arrivals" and (lp["delivered_pct"] or 0) < 95:
        warn = f"  [!] only {lp['delivered_pct']}% of profile arrivals delivered"
    elif lp and lp["kind"] == "concurrency" and (lp["matched_pct"] or 0) < 90:
        warn = (f"  [!] in-flight matched the profile only "
                f"{lp['matched_pct']}% of the time")
    print(f"  run report: {s['samples']} samples, {s['error_pct']}% errors, "
          f"{s['throughput_per_s']}/s, peak {s['peak_in_flight']} in flight{warn}")

    # A run where the queries failed is not a result. Reporting success for it is
    # worse than reporting nothing: the numbers look plausible and mean nothing.
    if s["error_pct"] > a.max_error_pct:
        print(f"  [FAIL] error rate {s['error_pct']}% exceeds the "
              f"{a.max_error_pct}% threshold - this run is not a usable result")
        for f in s.get("failure_messages", [])[:3]:
            print(f"         {f['count']}x {f['message'][:120]}")
        print(f"         raise the bar with MAX_ERROR_PCT=<pct> if errors are expected")
        raise SystemExit(EXIT_FAILED_RUN)


if __name__ == "__main__":
    main()
