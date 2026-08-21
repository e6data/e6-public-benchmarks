import tempfile
import unittest
from pathlib import Path

from utilities.query_file_info import inspect


class QueryFileInfoTests(unittest.TestCase):
    def inspect_text(self, text):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "queries.csv"
            path.write_text(text)
            return inspect(path)

    def test_valid_header_variants_and_quoted_commas(self):
        result = self.inspect_text('query_alias,query_string\nq1,"select 1, 2"\n')
        self.assertTrue(result["valid"])
        self.assertEqual(result["rows"], 1)

    def test_reports_all_record_level_errors(self):
        result = self.inspect_text(
            'QUERY_ALIAS,QUERY\nq1,"select 1"\n\nq1,"select 2"\n,"select 3"\nq4,\nq5,select 5,extra\n'
        )
        self.assertFalse(result["valid"])
        joined = " | ".join(result["errors"])
        self.assertIn("line 3 is blank", joined)
        self.assertIn("duplicate query alias", joined)
        self.assertIn("empty query alias", joined)
        self.assertIn("empty SQL query", joined)
        self.assertIn("exactly 2 columns", joined)

    def test_rejects_missing_header_and_malformed_quotes(self):
        self.assertIn("line 1 must contain", " ".join(self.inspect_text('q1,"select 1"\n')["errors"]))
        malformed = self.inspect_text('QUERY_ALIAS,QUERY\nq1,"select 1\n')
        self.assertIn("invalid CSV", " ".join(malformed["errors"]))
