#!/usr/bin/env python3
"""Convert Snowflake TPC-DS sources to this framework's two-column CSV.

The official Snowflake script embeds one JSON query marker in each executable
TPC-DS statement. The legacy e6-perf-test CSV has additional metadata columns.
Both are normalized to QUERY_ALIAS,QUERY without changing the SQL text.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path


MARKER = re.compile(r'/\*\s*(\{\s*"query"\s*:\s*"[^"]+".*?\})\s*\*/', re.DOTALL)


def official_queries(source: Path) -> list[tuple[str, str]]:
    text = source.read_text(encoding="utf-8")
    result: list[tuple[str, str]] = []
    for match in MARKER.finditer(text):
        metadata = json.loads(match.group(1))
        start = text.rfind(";", 0, match.start()) + 1
        end = text.find(";", match.end())
        if end < 0:
            raise ValueError(f"unterminated statement for {metadata['query']}")
        sql = text[start:end].strip()
        result.append((f"snowflake-{metadata['query']}", sql))
    aliases = [alias for alias, _ in result]
    if len(result) != 103 or len(set(aliases)) != 103:
        raise ValueError(f"expected 103 unique Snowflake query forms, found {len(result)}")
    return result


def legacy_queries(source: Path) -> list[tuple[str, str]]:
    with source.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or not {"QUERY_ALIAS", "QUERY"}.issubset(reader.fieldnames):
            raise ValueError("legacy CSV must contain QUERY_ALIAS and QUERY columns")
        result = [(row["QUERY_ALIAS"].strip(), row["QUERY"].strip()) for row in reader]
    if not result or any(not alias or not query for alias, query in result):
        raise ValueError("legacy CSV contains a blank alias or query")
    if len({alias for alias, _ in result}) != len(result):
        raise ValueError("legacy CSV contains duplicate query aliases")
    return result


def write_csv(target: Path, rows: list[tuple[str, str]]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["QUERY_ALIAS", "QUERY"])
        # Preserve SQL semantics while normalizing indentation so generated
        # CSVs remain clean under Git's whitespace checks.
        writer.writerows((alias, query.replace("\t", "    ")) for alias, query in rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("official", "legacy"))
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path)
    args = parser.parse_args()
    rows = official_queries(args.source) if args.mode == "official" else legacy_queries(args.source)
    write_csv(args.target, rows)
    print(f"wrote {len(rows)} queries to {args.target}")


if __name__ == "__main__":
    main()
