import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from utilities.build_benchmark_catalog import logical_alias, read_rows, read_snowflake_tpch, write_rows


class BenchmarkCatalogTests(unittest.TestCase):
    def test_aliases_join_across_vendor_conventions(self):
        self.assertEqual(logical_alias("tpcds", "DBR-TPCDS-2.4-14A"), "TPCDS_Q14A")
        self.assertEqual(logical_alias("tpcds", "snowflake-query39_p2"), "TPCDS_Q39B")
        self.assertEqual(logical_alias("tpch", "query-22-TPCH-22"), "TPCH_Q22")

    def test_builder_rejects_incomplete_suite(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.csv"
            source.write_text('QUERY_ALIAS,QUERY\nTPCDS-1,"select 1"\n')
            with self.assertRaisesRegex(ValueError, "expected 103"):
                read_rows(source, "tpcds", False)

    def test_legacy_sequence_is_not_mislabeled_as_reference_query_number(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.csv"
            with source.open("w", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["QUERY_ALIAS", "QUERY"])
                for number in range(1, 104):
                    writer.writerow([f"TPCDS-{number}", f"select {number}"])
            rows = read_rows(source, "tpcds", False, legacy_sequence=True)
            self.assertEqual(rows[5][0], "TPCDS_LEGACY_006")

    def test_writer_emits_runner_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "queries.csv"
            write_rows(target, [("TPCH_Q01", "select 1")])
            with target.open(newline="") as handle:
                self.assertEqual(list(csv.reader(handle)), [["QUERY_ALIAS", "QUERY"], ["TPCH_Q01", "select 1"]])

    def test_snowflake_tpch_parser_requires_full_suite(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "queries.sql"
            source.write_text("-- Q01\n-- ---\nselect 1;\n")
            with self.assertRaisesRegex(ValueError, "expected 22"):
                read_snowflake_tpch(source)

    def test_checked_in_catalog_hashes_and_aliases_match(self):
        root = Path(__file__).resolve().parents[2]
        catalog = json.loads((root / "data_files/benchmarks/catalog.json").read_text())
        for variant in catalog["variants"]:
            # Paths in the manifest are framework-root relative.
            path = root / variant["path"]
            self.assertTrue(path.is_file(), variant["id"])
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), variant["sha256"])
            with path.open(newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), variant["forms"])
            self.assertEqual(len({row["QUERY_ALIAS"] for row in rows}), variant["forms"])


if __name__ == "__main__":
    unittest.main()
