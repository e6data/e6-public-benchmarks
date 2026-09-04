#!/usr/bin/env python3
"""Build a run-local query CSV containing N measured passes.

Aliases are intentionally preserved. JMeter therefore groups every pass of a
query under the same label in its Aggregate Report and HTML dashboard.
"""

import argparse
import csv
from pathlib import Path


def repeat(source: Path, destination: Path, iterations: int) -> int:
    if iterations < 1:
        raise ValueError("iterations must be positive")
    with source.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.reader(handle, strict=True))
    if len(rows) < 2:
        raise ValueError("query CSV must contain a header and at least one query")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(rows[0])
        for _ in range(iterations):
            writer.writerows(rows[1:])
    return (len(rows) - 1) * iterations


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("iterations", type=int)
    args = parser.parse_args()
    print(repeat(args.source, args.destination, args.iterations))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
