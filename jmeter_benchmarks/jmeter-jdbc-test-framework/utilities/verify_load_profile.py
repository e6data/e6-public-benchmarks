#!/usr/bin/env python3
"""
Verify that queries were fired at the rate the load profile asked for.

Usage:
    verify_load_profile.py <JmeterResultFile.csv> <profile.csv>

Compares the per-second arrival rate actually achieved against the profile.
The JMeter `timeStamp` column is each sample's START time, so bucketing it by
second reconstructs the arrival curve independently of how long queries took to
complete - which is what you want, since a saturated cluster stretches
completions long past the profile window without changing arrivals.

A healthy run shows actual tracking expected within a sample or two per second,
and no arrivals after the profile window. Persistent shortfall means the
arrivals thread group could not start threads fast enough - raise
MAX_CONCURRANCY (it feeds ConcurrencyLimit).
"""

import collections
import csv
import sys


def read_profile(path):
    rows = []
    with open(path, newline="") as fh:
        for parts in csv.reader(fh):
            if not parts or not any(p.strip() for p in parts):
                continue
            if parts[0].strip().lower().startswith("startvalue"):
                continue
            start, end, dur = (int(p.strip()) for p in parts[:3])
            rows.append((start, end, dur))
    return rows


def expected_per_second(rows):
    """Expand profile steps into a per-second expected rate, interpolating ramps."""
    out = []
    for start, end, dur in rows:
        for i in range(dur):
            # linear interpolation across the step; flat when start == end
            rate = start if dur == 1 else start + (end - start) * i / (dur - 1)
            out.append(round(rate))
    return out


def main():
    if len(sys.argv) != 3:
        raise SystemExit(__doc__.strip())
    results_path, profile_path = sys.argv[1:3]

    rows = list(csv.DictReader(open(results_path)))
    if not rows:
        raise SystemExit(f"{results_path}: no samples")
    stamps = [int(r["timeStamp"]) for r in rows]
    t0 = min(stamps)
    actual = collections.Counter((t - t0) // 1000 for t in stamps)

    expected = expected_per_second(read_profile(profile_path))

    print(f"{'sec':>4} | {'expected':>8} | {'actual':>6} |")
    print("-" * 30)
    tot_e = tot_a = 0
    for sec, exp in enumerate(expected):
        act = actual.get(sec, 0)
        tot_e += exp
        tot_a += act
        flag = "" if abs(act - exp) <= max(1, exp * 0.1) else "  <-- off"
        print(f"{sec:>4} | {exp:>8} | {act:>6} | {'#' * act}{flag}")

    window = len(expected)
    late = sum(v for k, v in actual.items() if k >= window)
    pct = (tot_a / tot_e * 100) if tot_e else 0

    print()
    print(f"profile window : {window}s")
    print(f"expected       : {tot_e}")
    print(f"actual         : {tot_a}  ({pct:.1f}%)")
    print(f"after window   : {late}")
    print(f"total samples  : {len(rows)}")
    if pct < 95:
        print("\nShortfall >5%: arrivals were dropped. Raise MAX_CONCURRANCY.")
    if late:
        print("\nArrivals after the profile window - the schedule may not have applied.")


if __name__ == "__main__":
    main()
