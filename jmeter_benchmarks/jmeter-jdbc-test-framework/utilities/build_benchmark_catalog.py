#!/usr/bin/env python3
"""Build strict JMeter query CSVs with cross-engine logical query identities."""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path


TPCDS_ID = re.compile(r"(?:^|[-_])(\d{1,2})([AaBb]?)$")
SNOWFLAKE_TPCDS_ID = re.compile(r"query(\d{1,2})(?:_[Pp]([12]))?$")
TPCH_ID = re.compile(r"(?:.*?)(\d{1,2})$")
SNOWFLAKE_TPCH_MARKER = re.compile(r"^-- Q(\d{2})\s*$", re.MULTILINE)


def normalize_formatting(sql: str) -> str:
    """Normalize non-semantic indentation and line-end whitespace."""
    return "\n".join(line.rstrip() for line in sql.replace("\t", "    ").strip().splitlines())


def logical_alias(benchmark: str, source_alias: str) -> str:
    alias = source_alias.strip()
    pattern = TPCDS_ID if benchmark == "tpcds" else TPCH_ID
    match = SNOWFLAKE_TPCDS_ID.search(alias) if benchmark == "tpcds" and "query" in alias.lower() else pattern.search(alias)
    if not match:
        raise ValueError(f"cannot derive {benchmark.upper()} identity from {alias!r}")
    number = int(match.group(1))
    if benchmark == "tpch":
        if not 1 <= number <= 22:
            raise ValueError(f"TPC-H query number out of range: {alias}")
        return f"TPCH_Q{number:02d}"
    if not 1 <= number <= 99:
        raise ValueError(f"TPC-DS query number out of range: {alias}")
    if benchmark == "tpcds" and "query" in alias.lower():
        suffix = {"1": "A", "2": "B"}.get(match.group(2) or "", "")
    else:
        suffix = match.group(2)
    return f"TPCDS_Q{number:02d}{suffix.upper()}"


def read_rows(source: Path, benchmark: str, skip_bootstrap: bool, legacy_sequence: bool = False) -> list[tuple[str, str]]:
    with source.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or not {"QUERY_ALIAS", "QUERY"}.issubset(reader.fieldnames):
            raise ValueError("source must contain QUERY_ALIAS and QUERY columns")
        rows = []
        for row in reader:
            source_alias = row["QUERY_ALIAS"].strip()
            if skip_bootstrap and "BOOTSTRAP" in source_alias.upper():
                continue
            if legacy_sequence:
                match = re.fullmatch(r"TPCDS-(\d{1,3})([AaBb]?)", source_alias, re.IGNORECASE)
                if benchmark != "tpcds" or not match:
                    raise ValueError(f"invalid legacy TPC-DS sequence alias: {source_alias!r}")
                alias = f"TPCDS_LEGACY_{int(match.group(1)):03d}{match.group(2).upper()}"
            else:
                alias = logical_alias(benchmark, source_alias)
            rows.append((alias, normalize_formatting(row["QUERY"])))
    expected = 103 if benchmark == "tpcds" else 22
    aliases = [alias for alias, _ in rows]
    if len(rows) != expected or len(set(aliases)) != expected:
        raise ValueError(f"expected {expected} unique {benchmark.upper()} forms, found {len(rows)}")
    if any(not query for _, query in rows):
        raise ValueError("source contains an empty query")
    return sorted(rows, key=lambda row: row[0])


def read_snowflake_tpch(source: Path) -> list[tuple[str, str]]:
    text = source.read_text(encoding="utf-8")
    markers = list(SNOWFLAKE_TPCH_MARKER.finditer(text))
    rows = []
    for index, marker in enumerate(markers):
        end = markers[index + 1].start() if index + 1 < len(markers) else len(text)
        block = text[marker.end():end]
        separator = block.find("\n", block.find("---"))
        sql = normalize_formatting(block[separator + 1:].strip().rstrip(";"))
        rows.append((f"TPCH_Q{int(marker.group(1)):02d}", sql))
    if len(rows) != 22 or len({alias for alias, _ in rows}) != 22 or any(not query for _, query in rows):
        raise ValueError(f"expected 22 unique Snowflake TPC-H queries, found {len(rows)}")
    return rows


def write_rows(target: Path, rows: list[tuple[str, str]]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["QUERY_ALIAS", "QUERY"])
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("benchmark", choices=("tpcds", "tpch"))
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path)
    parser.add_argument("--skip-bootstrap", action="store_true")
    parser.add_argument("--legacy-sequence", action="store_true")
    parser.add_argument("--snowflake-script", action="store_true")
    args = parser.parse_args()
    if args.snowflake_script:
        if args.benchmark != "tpch":
            parser.error("--snowflake-script is only valid for tpch")
        rows = read_snowflake_tpch(args.source)
    else:
        rows = read_rows(args.source, args.benchmark, args.skip_bootstrap, args.legacy_sequence)
    write_rows(args.target, rows)
    print(f"wrote {len(rows)} queries to {args.target}")


if __name__ == "__main__":
    main()
