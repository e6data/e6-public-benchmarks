#!/usr/bin/env python3
"""
Inject a load-profile CSV into a JMeter plan's thread-group schedule.

Usage:
    apply_load_profile.py <plan.jmx> <profile.csv> <output.jmx>

Why this exists
---------------
Both load-profile plans ship a JSR223 *PreProcessor* that tries to apply the
CSV at runtime via setData() / setProperty(). That cannot work: a PreProcessor
runs when a sampler fires, which is after the thread group has already read its
schedule and started threads. The CSV is silently ignored and the plan's
hardcoded schedule is used instead.

Rather than restructuring the JMeter element lifecycle, this rewrites the
schedule block before JMeter is launched, so any CSV works with the stock plan
and no per-profile plan files are needed.

Two plan families are supported; the format is chosen from the plan, not a flag.

  FreeFormArrivalsThreadGroup  ->  <collectionProp name="Schedule">
      Controls ARRIVAL RATE. 3 columns:
          StartValue,EndValue,Duration
          3,3,1
          5,5,2

  UltimateThreadGroup          ->  <collectionProp name="ultimatethreadgroupdata">
      Controls CONCURRENCY. 5 columns:
          Threads,StartTime,StartupTime,HoldTime,ShutdownTime
          10,0,30,60,10
          20,90,30,60,10
      Rows STACK: a row adds its threads on top of whatever else is running,
      so the two rows above give 10 concurrent, then 30 from t=90s.
      For a flat step with no ramp use StartupTime=0 and ShutdownTime=0.

Durations are in the unit set by the thread group's Unit property (S = seconds).
"""

import re
import sys

from load_profile import read_arrivals_profile, read_concurrency_profile


# ---------------------------------------------------------------- emitting

def build_schedule(rows):
    """FreeFormArrivalsThreadGroup: 3 values per row."""
    blocks = [
        f'          <collectionProp name="lp{i}">\n'
        f'            <stringProp name="48">{start}</stringProp>\n'
        f'            <stringProp name="49">{end}</stringProp>\n'
        f'            <stringProp name="50">{dur}</stringProp>\n'
        f"          </collectionProp>"
        for i, (start, end, dur) in enumerate(rows)
    ]
    return (
        '<collectionProp name="Schedule">\n'
        + "\n".join(blocks)
        + "\n        </collectionProp>\n        "
    )


def build_utg_data(rows):
    """UltimateThreadGroup: 5 values per row.

    Property names inside a collectionProp are positional filler - JMeter reads
    the collection in order and ignores them. The stock plan writes name==value
    (and even repeats a name within a row), so anything unique is safe.
    """
    blocks = []
    for i, row in enumerate(rows):
        vals = "\n".join(
            f'            <stringProp name="c{i}_{j}">{v}</stringProp>'
            for j, v in enumerate(row)
        )
        blocks.append(
            f'          <collectionProp name="utg{i}">\n{vals}\n'
            f"          </collectionProp>"
        )
    return (
        '<collectionProp name="ultimatethreadgroupdata">\n'
        + "\n".join(blocks)
        + "\n        </collectionProp>\n        "
    )


# ---------------------------------------------------------------- reporting

def describe_arrivals(rows):
    # Trapezoid: a step ramping start->end over dur averages (start+end)/2.
    total = round(sum((s + e) / 2 * d for s, e, d in rows))
    duration = sum(d for _, _, d in rows)
    peak = max(max(s, e) for s, e, _ in rows)
    return (f"{len(rows)} steps, {duration}s, peak {peak}/s, "
            f"~{total} expected samples")


def concurrency_timeline(rows):
    """Concurrency at each second, summing the stacked, ramped waves."""
    end = max(st + up + hold + down for _, st, up, hold, down in rows)
    series = []
    for t in range(end + 1):
        n = 0
        for threads, st, up, hold, down in rows:
            if t < st:
                continue
            dt = t - st
            if dt < up:                       # ramping up
                n += threads * dt / up if up else threads
            elif dt < up + hold:              # plateau
                n += threads
            elif dt < up + hold + down:       # ramping down
                n += threads * (1 - (dt - up - hold) / down) if down else 0
        series.append(n)
    return series


def describe_concurrency(rows):
    series = concurrency_timeline(rows)
    peak = max(series)
    duration = len(series) - 1
    steady = sorted({round(v) for v in series if v > 0})
    return (f"{len(rows)} waves, {duration}s, peak {peak:g} concurrent, "
            f"levels {steady}")


# ---------------------------------------------------------------- main

# Each entry: plan marker -> (csv reader, xml builder, block name, anchor, describer)
FAMILIES = [
    (
        "FreeFormArrivalsThreadGroup",
        read_arrivals_profile,
        build_schedule,
        "Schedule",
        r'(?=<stringProp name="LogFilename">)',
        describe_arrivals,
        "arrival rate",
    ),
    (
        "kg.apc.jmeter.threads.UltimateThreadGroup",
        read_concurrency_profile,
        build_utg_data,
        "ultimatethreadgroupdata",
        r'(?=<elementProp name="ThreadGroup\.main_controller")',
        describe_concurrency,
        "concurrency",
    ),
]


def main():
    if len(sys.argv) != 4:
        raise SystemExit(__doc__.strip())
    plan_path, profile_path, out_path = sys.argv[1:4]

    plan = open(plan_path).read()

    for marker, reader, builder, block, anchor, describe, kind in FAMILIES:
        if marker not in plan:
            continue

        try:
            rows = reader(profile_path)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        # Non-greedy plus a lookahead anchor: inner </collectionProp> tags are not
        # followed by the anchor, so the match extends to the correct outer close.
        plan_out, n = re.subn(
            r'<collectionProp name="' + block + r'">.*?</collectionProp>\s*' + anchor,
            builder(rows),
            plan,
            count=1,
            flags=re.S,
        )
        if n != 1:
            raise SystemExit(
                f"{plan_path}: could not locate the {block} block to replace"
            )

        with open(out_path, "w") as fh:
            fh.write(plan_out)
        print(f"load profile applied ({kind}): {describe(rows)} -> {out_path}")
        return

    raise SystemExit(
        f"{plan_path}: no FreeFormArrivalsThreadGroup or UltimateThreadGroup - "
        f"this plan is not load-profile driven, nothing to inject"
    )


if __name__ == "__main__":
    main()
