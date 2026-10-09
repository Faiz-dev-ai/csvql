import io
import subprocess
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from csvql.errors import CsvqlError
from csvql.executor import execute, matches
from csvql.lexer import tokenize
from csvql.parser import parse

ROOT = Path(__file__).resolve().parents[1]


def query(sql):
    return parse(tokenize(sql))


class CountingFile(io.StringIO):
    def __init__(self, text):
        super().__init__(text)
        self.lines_read = 0

    def __next__(self):
        line = super().__next__()
        self.lines_read += 1
        return line


class StreamingTests(unittest.TestCase):
    def test_lazy_read_and_early_close(self):
        source = CountingFile("name,salary\nAda,1\nBen,2\nCara,3\n")
        with patch("csvql.executor.open", return_value=source) as opener:
            rows = execute(query("SELECT name FROM employees WHERE salary >= 2"), "unused.csv")
            opener.assert_not_called()
            try:
                self.assertEqual(next(rows), {"name": "Ben"})
                self.assertEqual(source.lines_read, 3)  # Header + Ada + Ben, no Cara.
                self.assertFalse(source.closed)
            finally:
                rows.close()
            self.assertTrue(source.closed)

    def test_exhaustion_closes_file(self):
        source = CountingFile("name\nAda\nBen\n")
        with patch("csvql.executor.open", return_value=source):
            self.assertEqual(list(execute(query("SELECT * FROM employees"), "unused")),
                             [{"name": "Ada"}, {"name": "Ben"}])
        self.assertTrue(source.closed)

    def test_validation_before_data_read_and_closes_on_error(self):
        source = CountingFile("name\nAda\n")
        with patch("csvql.executor.open", return_value=source):
            rows = execute(query("SELECT missing FROM employees"), "unused")
            with self.assertRaises(CsvqlError):
                next(rows)
        self.assertEqual(source.lines_read, 1)
        self.assertTrue(source.closed)

    def test_error_after_first_result_closes_file(self):
        source = CountingFile("name\nAda\nBen,extra\n")
        with patch("csvql.executor.open", return_value=source):
            rows = execute(query("SELECT * FROM employees"), "unused")
            self.assertEqual(next(rows), {"name": "Ada"})
            with self.assertRaisesRegex(CsvqlError, "more fields"):
                next(rows)
        self.assertTrue(source.closed)

    def test_late_cli_error(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "bad.csv"
            path.write_text("name\nAda\nBen,extra\n")
            result = subprocess.run([sys.executable, "-B", str(ROOT / "cli.py"),
                "SELECT * FROM people", str(path)], capture_output=True, text=True)
            self.assertEqual(result.stdout, "{'name': 'Ada'}\n")
            self.assertEqual(result.returncode, 1)
            self.assertIn("Error:", result.stderr)
            self.assertNotIn("Traceback", result.stderr)

    def test_duplicate_headers_rejected(self):
        with patch("csvql.executor.open", return_value=io.StringIO("name,name\nAda,Ben\n")):
            with self.assertRaisesRegex(CsvqlError, "duplicate"):
                list(execute(query("SELECT * FROM people"), "unused"))


class ComparisonTests(unittest.TestCase):
    def compare(self, cell, expression):
        return matches({"value": cell}, query("SELECT * FROM data WHERE value " + expression)["where"])

    def test_parser_preserves_literal_type(self):
        self.assertIsInstance(query("SELECT * FROM data WHERE value = 1.2")["where"][2], Decimal)
        self.assertIsInstance(query("SELECT * FROM data WHERE value = '1.2'")["where"][2], str)

    def test_large_integers_remain_distinct(self):
        self.assertFalse(self.compare("9007199254740993", "= 9007199254740992"))
        self.assertTrue(self.compare("9007199254740993", "> 9007199254740992"))
        self.assertTrue(self.compare("9007199254740993", "!= 9007199254740992"))

    def test_long_decimals_remain_distinct(self):
        self.assertTrue(self.compare("0.1234567890123456789012345678902", "> 0.1234567890123456789012345678901"))
        self.assertTrue(self.compare("1.00", "= 1"))
        self.assertTrue(self.compare(" -1.50 ", "= -1.5"))

    def test_leading_zeros_and_text(self):
        self.assertTrue(self.compare("001", "= '001'"))
        self.assertFalse(self.compare("001", "= '1'"))
        self.assertTrue(self.compare("001", "= 1"))
        self.assertTrue(self.compare("10", "< '2'"))
        self.assertFalse(self.compare("10", "< 2"))
        self.assertFalse(self.compare("Ada", "= 'ada'"))
        self.assertFalse(self.compare(" Ada ", "= 'Ada'"))

    def test_bad_numeric_cells_never_match(self):
        for cell in (None, "", " ", "N/A", "NaN", "Infinity", "1_000", "12abc"):
            for op in ("=", "!=", ">", "<", ">=", "<="):
                with self.subTest(cell=cell, op=op):
                    self.assertFalse(self.compare(cell, op + " 1"))

    def test_missing_versus_empty_text(self):
        for op in ("=", "!=", ">", "<", ">=", "<="):
            self.assertFalse(self.compare(None, op + " ''"))
        self.assertTrue(self.compare("", "= ''"))
        self.assertTrue(self.compare("N/A", "= 'N/A'"))

    def test_actual_csv_precision_and_missing_cells(self):
        text = "id,value\na,9007199254740992\nb,9007199254740993\nc,\nd\ne,N/A\n"
        for expression, expected in (("> 9007199254740992", ["b"]), ("= ''", ["c"]),
                                     ("= 'N/A'", ["e"]), ("!= 9007199254740992", ["b"])):
            with self.subTest(expression=expression):
                with patch("csvql.executor.open", return_value=io.StringIO(text)):
                    rows = execute(query("SELECT id FROM data WHERE value " + expression), "unused")
                    self.assertEqual([r["id"] for r in rows], expected)
        with patch("csvql.executor.open", return_value=io.StringIO(text)):
            rows = list(execute(query("SELECT * FROM data"), "unused"))
            self.assertEqual(rows[2]["value"], "")
            self.assertIsNone(rows[3]["value"])


if __name__ == "__main__":
    unittest.main()
