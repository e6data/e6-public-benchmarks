#!/usr/bin/env python3
"""
Inject a load-profile CSV into a JMeter plan's arrivals-thread-group Schedule.

Usage:
    apply_load_profile.py <plan.jmx> <profile.csv> <output.jmx>

Why this exists
---------------
Test-Plan-Fire-QPS-with-load-profile.jmx ships a JSR223 *PreProcessor* that
tries to apply the load profile at runtime via ctx.getThreadGroup().setData().
That cannot work: a PreProcessor runs when a sampler fires, which is after the
FreeFormArrivalsThreadGroup has already read its Schedule and started firing
arrivals. The result is that the CSV is silently ignored and the plan's
hardcoded Schedule is used instead - typically 25 arrivals over 15s.

Rather than restructuring the JMeter element lifecycle, this rewrites the
Schedule block before JMeter is launched, so any CSV works with the stock plan
and no per-profile plan files are needed.

CSV format (header optional, matching the plan's own parser):
    StartValue,EndValue,Duration
    3,3,1
    5,5,2

Duration is in the unit set by the thread group's Unit property (S = seconds).
"""

import csv
import re
import sys


def read_profile(path):
    rows = []
    with open(path, newline="") as fh:
        for lineno, parts in enumerate(csv.reader(fh), 1):
            if not parts or not any(p.strip() for p in parts):
                continue
            if parts[0].strip().lower().startswith("startvalue"):
                continue  # header
            if len(parts) < 3:
                raise SystemExit(
                    f"{path}:{lineno}: expected 3 columns, got {len(parts)}: {parts!r}"
                )
            try:
                start, end, dur = (int(p.strip()) for p in parts[:3])
            except ValueError:
                raise SystemExit(f"{path}:{lineno}: non-integer value in {parts[:3]!r}")
            if dur <= 0:
                raise SystemExit(f"{path}:{lineno}: duration must be > 0, got {dur}")
            rows.append((start, end, dur))
    if not rows:
        raise SystemExit(f"{path}: no usable rows found")
    return rows


def build_schedule(rows):
    blocks = []
    for i, (start, end, dur) in enumerate(rows):
        blocks.append(
            f'          <collectionProp name="lp{i}">\n'
            f'            <stringProp name="48">{start}</stringProp>\n'
            f'            <stringProp name="49">{end}</stringProp>\n'
            f'            <stringProp name="50">{dur}</stringProp>\n'
            f"          </collectionProp>"
        )
    return (
        '<collectionProp name="Schedule">\n'
        + "\n".join(blocks)
        + "\n        </collectionProp>\n        "
    )


def main():
    if len(sys.argv) != 4:
        raise SystemExit(__doc__.strip())
    plan_path, profile_path, out_path = sys.argv[1:4]

    plan = open(plan_path).read()
    if "FreeFormArrivalsThreadGroup" not in plan:
        raise SystemExit(
            f"{plan_path}: no FreeFormArrivalsThreadGroup - this plan is not "
            f"load-profile driven, nothing to inject"
        )

    rows = read_profile(profile_path)
    plan_out, n = re.subn(
        r'<collectionProp name="Schedule">.*?</collectionProp>\s*(?=<stringProp name="LogFilename">)',
        build_schedule(rows),
        plan,
        count=1,
        flags=re.S,
    )
    if n != 1:
        raise SystemExit(f"{plan_path}: could not locate the Schedule block to replace")

    with open(out_path, "w") as fh:
        fh.write(plan_out)

    # Trapezoid: a step ramping start->end over dur averages (start+end)/2.
    # Using start alone under-reports any ramped step.
    total = round(sum((start + end) / 2 * dur for start, end, dur in rows))
    duration = sum(dur for _, _, dur in rows)
    peak = max(max(s, e) for s, e, _ in rows)
    print(
        f"load profile applied: {len(rows)} steps, {duration}s, "
        f"peak {peak}/s, ~{total} expected samples -> {out_path}"
    )


if __name__ == "__main__":
    main()
