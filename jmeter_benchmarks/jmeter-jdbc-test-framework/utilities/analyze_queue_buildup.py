#!/usr/bin/env python3
"""
Show queue build-up and drain for an arrivals-based run.

Usage:
    analyze_queue_buildup.py <JmeterResultFile.csv> [--bucket N] [--markdown]

Under a load profile the engine is deliberately pushed past its service rate, so
the interesting result is not average latency but how the backlog forms and
clears. This reconstructs, per time bucket:

    arrivals    queries that started        (timeStamp)
    completions queries that finished       (timeStamp + elapsed)
    in-flight   arrivals - completions so far, i.e. queue depth + active
    latency     mean elapsed of queries completing in that bucket

Rising in-flight means arrivals are outrunning the engine. The peak is the
worst-case backlog; the tail after arrivals stop is pure drain time.
"""

import argparse
import csv
import sys


def load(path):
    rows = list(csv.DictReader(open(path)))
    if not rows:
        raise SystemExit(f"{path}: no samples")
    recs = []
    for r in rows:
        start = int(r["timeStamp"])
        recs.append((start, start + int(r["elapsed"]), int(r["elapsed"])))
    return recs


def buckets(recs, width_ms):
    t0 = min(r[0] for r in recs)
    tend = max(r[1] for r in recs)
    n = (tend - t0) // width_ms + 1
    arrivals = [0] * n
    completions = [0] * n
    lat_sum = [0] * n
    for start, end, elapsed in recs:
        arrivals[(start - t0) // width_ms] += 1
        b = (end - t0) // width_ms
        completions[b] += 1
        lat_sum[b] += elapsed
    return t0, arrivals, completions, lat_sum


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("results")
    ap.add_argument("--bucket", type=int, default=5, help="bucket width in seconds (default 5)")
    ap.add_argument("--markdown", action="store_true")
    args = ap.parse_args()

    recs = load(args.results)
    width = args.bucket * 1000
    _, arrivals, completions, lat_sum = buckets(recs, width)

    inflight, running = [], 0
    for a, c in zip(arrivals, completions):
        running += a - c
        inflight.append(running)

    peak = max(inflight)
    peak_at = inflight.index(peak) * args.bucket
    last_arrival = max(i for i, a in enumerate(arrivals) if a) * args.bucket
    total_s = len(arrivals) * args.bucket

    if args.markdown:
        print(f"| t (s) | arrivals | completions | in-flight | mean latency (s) |")
        print(f"|---|---|---|---|---|")
    else:
        print(f"{'t(s)':>5} {'arr':>5} {'done':>5} {'in-flight':>10}  {'lat(s)':>7}  queue")
        print("-" * 78)

    scale = max(1, peak // 40)
    for i, (a, c, q) in enumerate(zip(arrivals, completions, inflight)):
        lat = (lat_sum[i] / c / 1000) if c else 0
        t = i * args.bucket
        if args.markdown:
            print(f"| {t} | {a} | {c} | {q} | {lat:.1f} |")
        else:
            print(f"{t:>5} {a:>5} {c:>5} {q:>10}  {lat:>7.1f}  {'#' * (q // scale)}")

    print()
    print(f"peak in-flight   : {peak} at t={peak_at}s")
    print(f"arrivals stop    : t={last_arrival}s")
    print(f"drain time       : {total_s - last_arrival}s after last arrival")
    print(f"total wall clock : {total_s}s")
    print(f"samples          : {len(recs)}")


if __name__ == "__main__":
    main()
