#!/usr/bin/env python3
"""Inspect a JMeter query CSV without interpreting or printing its SQL text."""

import argparse
import csv
import hashlib


def has_header(row):
    names = {cell.strip().lower() for cell in row}
    has_alias = bool(names & {"query_alias", "query_alias_name", "alias"})
    has_query = bool(names & {"query", "query_string", "sql"})
    return has_alias and has_query


def inspect(path):
    with open(path, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.reader(fh))
    nonempty = [row for row in rows if any(cell.strip() for cell in row)]
    header = bool(nonempty and has_header(nonempty[0]))
    with open(path, "rb") as fh:
        digest = hashlib.sha256(fh.read()).hexdigest()
    return {
        "rows": max(0, len(nonempty) - int(header)),
        "header": header,
        "sha256": digest,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    parser.add_argument("--field", choices=("rows", "header", "sha256"))
    args = parser.parse_args()
    info = inspect(args.path)
    if args.field:
        value = info[args.field]
        print(str(value).lower() if isinstance(value, bool) else value)
    else:
        for key, value in info.items():
            print(f"{key}={str(value).lower() if isinstance(value, bool) else value}")


if __name__ == "__main__":
    main()
