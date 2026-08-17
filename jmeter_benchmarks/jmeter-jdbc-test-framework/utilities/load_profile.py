"""Shared parsing and expected-load models for JMeter load-profile CSVs."""

import csv


def _data_rows(path):
    rows = []
    with open(path, newline="") as fh:
        for lineno, parts in enumerate(csv.reader(fh), 1):
            parts = [part.strip() for part in parts]
            if not parts or not any(parts):
                continue
            rows.append((lineno, parts))
    return rows


def _parse(path, width, header):
    parsed = []
    for lineno, parts in _data_rows(path):
        if parts[0].lower() == header:
            continue
        if len(parts) != width:
            raise ValueError(
                f"{path}:{lineno}: expected exactly {width} columns, got {len(parts)}"
            )
        try:
            parsed.append(tuple(int(part) for part in parts))
        except ValueError as exc:
            raise ValueError(f"{path}:{lineno}: profile values must be integers") from exc
    if not parsed:
        raise ValueError(f"{path}: no usable profile rows found")
    return parsed


def read_arrivals_profile(path):
    rows = _parse(path, 3, "startvalue")
    for start, end, duration in rows:
        if start < 0 or end < 0:
            raise ValueError(f"{path}: arrival rates must be >= 0")
        if duration <= 0:
            raise ValueError(f"{path}: Duration must be > 0")
    return rows


def read_concurrency_profile(path):
    rows = _parse(path, 5, "threads")
    for threads, start, startup, hold, shutdown in rows:
        if threads <= 0:
            raise ValueError(f"{path}: Threads must be > 0")
        if min(start, startup, hold, shutdown) < 0:
            raise ValueError(f"{path}: profile times must be >= 0")
        if hold <= 0:
            raise ValueError(f"{path}: HoldTime must be > 0")
    return rows


def read_profile(path):
    rows = _data_rows(path)
    if not rows:
        raise ValueError(f"{path}: no usable profile rows found")
    first = rows[0][1]
    first_name = first[0].lower()
    if first_name == "startvalue" or len(first) == 3:
        return "arrivals", read_arrivals_profile(path)
    if first_name == "threads" or len(first) == 5:
        return "concurrency", read_concurrency_profile(path)
    raise ValueError(f"{path}:{rows[0][0]}: expected a 3- or 5-column profile")


def expected_arrivals_per_second(steps):
    out = []
    for start, end, duration in steps:
        for index in range(duration):
            value = start if duration == 1 else start + (end - start) * index / (duration - 1)
            out.append(round(value))
    return out


def expected_concurrency_per_second(waves):
    end = max(start + startup + hold + shutdown
              for _, start, startup, hold, shutdown in waves)
    out = []
    for second in range(end + 1):
        concurrent = 0.0
        for threads, start, startup, hold, shutdown in waves:
            if second < start:
                continue
            elapsed = second - start
            if elapsed < startup:
                concurrent += threads * elapsed / startup
            elif elapsed < startup + hold:
                concurrent += threads
            elif elapsed < startup + hold + shutdown:
                concurrent += threads * (1 - (elapsed - startup - hold) / shutdown)
        out.append(concurrent)
    return out
