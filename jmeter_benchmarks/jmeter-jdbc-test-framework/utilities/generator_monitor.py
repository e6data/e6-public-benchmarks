#!/usr/bin/env python3
"""Capture lightweight Linux/macOS load-generator health evidence."""

import argparse
import csv
import json
import os
import signal
import time
from pathlib import Path

RUNNING = True


def stop(*_):
    global RUNNING
    RUNNING = False


def linux_sample(previous=None):
    cpu = Path("/proc/stat").read_text().splitlines()[0].split()[1:]
    values = [int(value) for value in cpu]
    idle, total = values[3] + values[4], sum(values)
    cpu_pct = None
    if previous:
        total_delta, idle_delta = total - previous[1], idle - previous[0]
        cpu_pct = 100 * (1 - idle_delta / total_delta) if total_delta else None
    memory = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        key, value = line.split(":", 1)
        memory[key] = int(value.strip().split()[0])
    mem_pct = 100 * (1 - memory.get("MemAvailable", 0) / memory["MemTotal"])
    swap_used = memory.get("SwapTotal", 0) - memory.get("SwapFree", 0)
    network = 0
    for line in Path("/proc/net/dev").read_text().splitlines()[2:]:
        fields = line.replace(":", " ").split()
        if fields[0] != "lo":
            network += int(fields[1]) + int(fields[9])
    return (idle, total), cpu_pct, mem_pct, swap_used, network


def record(output, interval):
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    previous = None
    with Path(output).open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("timestamp", "cpu_pct", "memory_pct", "swap_used_kb", "load_1m", "network_bytes"))
        while RUNNING:
            if Path("/proc/stat").is_file():
                previous, cpu, memory, swap, network = linux_sample(previous)
            else:
                cpu, memory, swap, network = None, None, None, None
            writer.writerow((round(time.time(), 3), "" if cpu is None else round(cpu, 2),
                             "" if memory is None else round(memory, 2), swap if swap is not None else "",
                             round(os.getloadavg()[0], 2), network if network is not None else ""))
            handle.flush()
            time.sleep(interval)


def summarize(path, output):
    with Path(path).open() as handle:
        rows = list(csv.DictReader(handle))
    numeric = lambda key: [float(row[key]) for row in rows if row.get(key) not in {None, ""}]
    cpu, memory, swap, load = numeric("cpu_pct"), numeric("memory_pct"), numeric("swap_used_kb"), numeric("load_1m")
    sustained = lambda values, threshold: any(all(value >= threshold for value in values[index:index + 3])
                                               for index in range(max(0, len(values) - 2)))
    reasons = []
    if sustained(cpu, 90): reasons.append("load-generator CPU stayed at or above 90%")
    if sustained(memory, 90): reasons.append("load-generator memory stayed at or above 90%")
    if swap and max(swap) > 0: reasons.append("load generator used swap")
    health = {
        "status": "invalid" if reasons else "healthy" if cpu or memory else "unknown",
        "samples": len(rows), "peak_cpu_pct": max(cpu) if cpu else None,
        "peak_memory_pct": max(memory) if memory else None,
        "peak_swap_used_kb": max(swap) if swap else None,
        "peak_load_1m": max(load) if load else None, "reasons": reasons,
        "details": Path(path).name,
    }
    target = Path(output)
    summary = json.loads(target.read_text())
    summary["generator_health"] = health
    target.write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(health))


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    monitor = sub.add_parser("record")
    monitor.add_argument("output")
    monitor.add_argument("--interval", type=float, default=1)
    report = sub.add_parser("summarize")
    report.add_argument("metrics")
    report.add_argument("run_summary")
    args = parser.parse_args()
    record(args.output, args.interval) if args.command == "record" else summarize(args.metrics, args.run_summary)


if __name__ == "__main__":
    main()
