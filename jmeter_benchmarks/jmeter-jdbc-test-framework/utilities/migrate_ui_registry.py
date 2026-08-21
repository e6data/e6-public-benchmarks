#!/usr/bin/env python3
"""Idempotently copy Benchmark Studio run registry rows to PostgreSQL."""

import argparse
import json
import sqlite3
from pathlib import Path


def migrate(sqlite_path: Path, database_url: str) -> int:
    try:
        import psycopg
        from psycopg.types.json import Jsonb
    except ImportError as exc:
        raise SystemExit("Install PostgreSQL support: pip install -r requirements-ui.txt") from exc
    with sqlite3.connect(sqlite_path) as source:
        rows = source.execute("SELECT run_id,payload,updated_at FROM runs ORDER BY updated_at").fetchall()
    with psycopg.connect(database_url) as target:
        target.execute("CREATE TABLE IF NOT EXISTS runs (run_id TEXT PRIMARY KEY, payload JSONB NOT NULL, updated_at DOUBLE PRECISION NOT NULL)")
        for run_id, payload, updated_at in rows:
            target.execute(
                "INSERT INTO runs(run_id,payload,updated_at) VALUES(%s,%s,%s) "
                "ON CONFLICT(run_id) DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at",
                (run_id, Jsonb(json.loads(payload)), updated_at),
            )
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sqlite", type=Path, required=True)
    parser.add_argument("--database-url", required=True)
    args = parser.parse_args()
    count = migrate(args.sqlite, args.database_url)
    print(f"Migrated {count} run registry rows")


if __name__ == "__main__":
    main()
