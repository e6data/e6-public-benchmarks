#!/usr/bin/env python3
"""Validate and inspect a JMeter query CSV without printing its SQL text."""

import argparse
import csv
import hashlib
import sys


ALIAS_HEADERS = {"query_alias", "query_alias_name", "alias"}
QUERY_HEADERS = {"query", "query_string", "sql"}


def has_header(row):
    names = {cell.strip().lower() for cell in row}
    return bool(names & ALIAS_HEADERS) and bool(names & QUERY_HEADERS)


def inspect(path):
    errors = []
    parsed = []
    try:
        with open(path, newline="", encoding="utf-8-sig") as fh:
            reader = csv.reader(fh, strict=True)
            for row in reader:
                parsed.append((reader.line_num, row))
    except (OSError, UnicodeError, csv.Error) as exc:
        errors.append(f"invalid CSV: {exc}")

    header = bool(parsed and has_header(parsed[0][1]))
    if parsed and not header:
        errors.append("line 1 must contain alias and SQL headers (for example QUERY_ALIAS,QUERY)")
    elif not parsed:
        errors.append("file is empty")

    aliases = set()
    valid_rows = 0
    for line, row in parsed[1 if header else 0:]:
        if not row or not any(cell.strip() for cell in row):
            errors.append(f"line {line} is blank")
            continue
        if len(row) != 2:
            errors.append(f"line {line} must contain exactly 2 columns; found {len(row)}")
            continue
        alias, query = (cell.strip() for cell in row)
        if not alias:
            errors.append(f"line {line} has an empty query alias")
        if not query:
            errors.append(f"line {line} has an empty SQL query")
        if alias:
            folded = alias.casefold()
            if folded in aliases:
                errors.append(f"line {line} has duplicate query alias {alias!r}")
            aliases.add(folded)
        if alias and query:
            valid_rows += 1
    if header and not valid_rows:
        errors.append("file contains no executable queries")

    with open(path, "rb") as fh:
        digest = hashlib.sha256(fh.read()).hexdigest()
    return {"rows": valid_rows, "header": header, "sha256": digest, "errors": errors, "valid": not errors}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    parser.add_argument("--field", choices=("rows", "header", "sha256", "valid"))
    parser.add_argument("--validate", action="store_true", help="exit nonzero and describe invalid records")
    args = parser.parse_args()
    info = inspect(args.path)
    if args.validate and info["errors"]:
        for error in info["errors"]:
            print(f"QUERY_FILE: {error}", file=sys.stderr)
        return 1
    if args.field:
        value = info[args.field]
        print(str(value).lower() if isinstance(value, bool) else value)
    else:
        for key in ("rows", "header", "sha256", "valid"):
            value = info[key]
            print(f"{key}={str(value).lower() if isinstance(value, bool) else value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
