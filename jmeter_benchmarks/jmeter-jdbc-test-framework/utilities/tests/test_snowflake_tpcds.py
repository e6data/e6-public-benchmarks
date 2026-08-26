import csv
import tempfile
import unittest
from pathlib import Path

from utilities.import_snowflake_tpcds import legacy_queries, official_queries, write_csv


class SnowflakeTpcdsImportTests(unittest.TestCase):
    def test_official_import_preserves_marked_statements(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "queries.sql"
            statements = []
            for index in range(103):
                statements.append(
                    f'select /* {{"query":"query{index:02d}","querySequence":{index}}} */ {index}'
                )
            source.write_text("ALTER SESSION SET x=1;\n" + ";\n".join(statements) + ";\n")
            rows = official_queries(source)
            self.assertEqual(len(rows), 103)
            self.assertEqual(rows[0][0], "snowflake-query00")
            self.assertTrue(rows[-1][1].startswith("select"))

    def test_legacy_import_drops_non_runner_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "legacy.csv"
            target = Path(tmp) / "runner.csv"
            source.write_text(
                'S_NO,QUERY_ALIAS,QUERY,SCHEMA,EXPECTED_COUNT_TEXT\n'
                '1,q1,"select 1",schema,1\n'
            )
            rows = legacy_queries(source)
            write_csv(target, rows)
            with target.open(newline="") as handle:
                parsed = list(csv.DictReader(handle))
            self.assertEqual(list(parsed[0]), ["QUERY_ALIAS", "QUERY"])
            self.assertEqual(parsed[0]["QUERY"], "select 1")


if __name__ == "__main__":
    unittest.main()
